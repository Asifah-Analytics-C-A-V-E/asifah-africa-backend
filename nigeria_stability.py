# -*- coding: utf-8 -*-
"""
Nigeria Stability Backend — v1.0.0 (May 30 2026)
================================================

Lives on the Africa backend (asifah-africa-backend.onrender.com) alongside
the article gatherer, commodity proxy, and Sudan rhetoric tracker.

v1.0 ships:
  - NGX All-Share Index fetcher (Yahoo ^NGSE)
  - NGN/USD exchange rate fetcher (Yahoo NGN=X) — INVERTED polarity (rising = weaker naira)
  - Brent crude full Financial Pulse fetcher (Yahoo BZ=F, with sparkline)
  - Per-tile market_status logic (NGX Mon-Fri Lagos time, Brent ICE 24/5)
  - Aggregate market_status (open/closed/pre-market/after-hours/partial)
  - Canonical Financial Pulse Card payload assembly
  - Background refresh loop (12h cycle)

v1.0 explicitly does NOT include:
  - Stability vector scoring (deferred to v1.5)
  - Rhetoric tracker integration (Nigeria has no tracker yet — placeholder on frontend)
  - Humanitarian module
  - FX parallel-market premium (deferred to Black Swan Markets page)
  - Article scanning (handled by africa_article_gatherer)
  - Commodity exposure (handled by commodity_proxy_africa)

Patterns mirrored from saudi_stability.py for consistency.
"""

import os
import json
import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from flask import jsonify, request


# ============================================
# CONFIG
# ============================================

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL', '').rstrip('/')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '')

CACHE_KEY = 'nigeria_stability_v1.0'
HISTORY_KEY = 'nigeria_stability_history'
CACHE_TTL = 12 * 3600  # 12 hours


# ============================================
# REDIS HELPERS
# ============================================

def _redis_get(key):
    """Get value from Redis. Returns parsed JSON or None."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get('result') is None:
            return None
        return json.loads(data['result'])
    except Exception as e:
        print(f'[Nigeria Stability] Redis GET error: {str(e)[:120]}')
        return None


def _redis_set(key, value, ttl=None):
    """Set value in Redis with optional TTL (seconds)."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        payload = ['SET', key, json.dumps(value)]
        if ttl:
            payload.extend(['EX', str(ttl)])
        r = requests.post(
            UPSTASH_REDIS_URL,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            json=payload,
            timeout=5,
        )
        return r.status_code == 200
    except Exception as e:
        print(f'[Nigeria Stability] Redis SET error: {str(e)[:120]}')
        return False


# ============================================
# MARKET STATUS HELPERS
# ============================================

def _ngx_market_status():
    """
    Nigerian Exchange Group (NGX) trades Mon-Fri 10:00-14:30 WAT (UTC+1).
    Returns 'open' / 'closed' / 'pre-market' / 'after-hours'.
    """
    now = datetime.now(timezone.utc)
    # Lagos = UTC+1 (no DST)
    lagos_time = now + timedelta(hours=1)
    weekday = lagos_time.weekday()  # Mon=0 ... Sun=6

    # Weekend = closed
    if weekday >= 5:
        return 'closed'

    h = lagos_time.hour
    m = lagos_time.minute
    minutes = h * 60 + m

    open_minutes = 10 * 60          # 10:00
    close_minutes = 14 * 60 + 30    # 14:30
    pre_open_minutes = 9 * 60       # 09:00

    if minutes < pre_open_minutes:
        return 'closed'
    elif minutes < open_minutes:
        return 'pre-market'
    elif minutes < close_minutes:
        return 'open'
    elif minutes < close_minutes + 90:  # 90-min after-hours window
        return 'after-hours'
    else:
        return 'closed'


def _brent_market_status():
    """
    ICE Brent trades Mon 01:00 UTC → Sat 22:00 UTC (effectively 24/5).
    Returns 'open' / 'closed'.
    """
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    h = now.hour

    # Saturday before 22:00 = closed (close)
    if weekday == 5 and h < 22:
        return 'open'  # still trading week
    # Saturday 22:00 onward = closed for weekend
    if weekday == 5:
        return 'closed'
    # Sunday before 22:00 = closed (markets reopen at 22:00 UTC Sun = Mon 23:00 Asia)
    if weekday == 6 and h < 22:
        return 'closed'
    return 'open'


def _aggregate_market_status(statuses):
    """Combine per-tile statuses into a single card-level status."""
    if all(s == 'open' for s in statuses):
        return 'open'
    if all(s == 'closed' for s in statuses):
        return 'closed'
    if any(s == 'pre-market' for s in statuses):
        return 'pre-market'
    if any(s == 'after-hours' for s in statuses):
        return 'after-hours'
    if any(s == 'open' for s in statuses):
        return 'partial'
    return 'closed'


# ============================================
# TIER LOGIC (polarity-aware)
# ============================================

def _tier(chg, inverted=False):
    """
    Map a 24h change percentage to a tier color band.
      Standard polarity (e.g. NSE, Brent): rising = good
      Inverted polarity (e.g. NGN/USD):   rising = bad (weaker naira)
    Tiers: rally / stable / warning / stress
    """
    if chg is None:
        return 'stable'
    c = -chg if inverted else chg
    if c <= -2:
        return 'stress'
    if c <= -1:
        return 'warning'
    if c >= 2:
        return 'rally'
    return 'stable'


# ============================================
# FETCHERS
# ============================================

def _fetch_yahoo_chart(ticker, ticker_url_encoded=None):
    """
    Generic Yahoo Finance chart endpoint fetch. Returns dict with:
      - price (latest)
      - change_pct_24h (yesterday → today)
      - sparkline (list of {time, value})
    Returns None on error.
    """
    if ticker_url_encoded is None:
        ticker_url_encoded = ticker
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker_url_encoded}'
    try:
        r = requests.get(
            url,
            params={'interval': '1d', 'range': '1mo'},
            timeout=10,
            headers={'User-Agent': 'Mozilla/5.0 (AsifahAnalytics/1.0)'},
        )
        if r.status_code != 200:
            return None
        data = r.json()
        result = (data.get('chart', {}).get('result') or [{}])[0]
        meta = result.get('meta', {})
        price = meta.get('regularMarketPrice')
        # v1.0.0 — same fix as Saudi v0.5.1:
        # previousClose = yesterday's close (correct for 24h%)
        # chartPreviousClose = first datapoint of chart range (gives MONTHLY% not 24h%)
        prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
        if price is None or prev_close in (None, 0):
            return None
        change_pct = ((price - prev_close) / prev_close) * 100

        # Build sparkline
        sparkline = []
        try:
            timestamps = result.get('timestamp', []) or []
            closes = (result.get('indicators', {}).get('quote') or [{}])[0].get('close', []) or []
            for i, ts in enumerate(timestamps):
                if i < len(closes) and closes[i] is not None:
                    sparkline.append({
                        'time':  datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
                        'value': round(float(closes[i]), 4),
                    })
        except Exception:
            pass

        return {
            'price': round(float(price), 4),
            'change_pct': round(change_pct, 3),
            'sparkline': sparkline,
        }
    except Exception as e:
        print(f'[Nigeria Stability] Yahoo fetch error for {ticker}: {str(e)[:120]}')
        return None


def _fetch_ngx_index():
    """
    Fetch Nigerian Exchange Group All-Share Index from Yahoo Finance.
    Yahoo ticker: ^NGSE
    Returns Financial Pulse-shaped dict.
    """
    print('[Nigeria Stability] Fetching NGX All-Share Index (^NGSE)...')
    NGX_LAST_KNOWN_KEY = 'ngx_last_known'
    try:
        data = _fetch_yahoo_chart('^NGSE', '%5ENGSE')
        if data is None:
            raise Exception('Yahoo chart fetch returned None')

        payload = {
            'index':           'NGSE',
            'value':           round(data['price'], 2),
            'change_pct_24h':  data['change_pct'],
            'trend':           'rising' if data['change_pct'] > 0.3 else ('falling' if data['change_pct'] < -0.3 else 'flat'),
            'source':          'Yahoo Finance',
            'sparkline':       data['sparkline'],
            'timestamp':       datetime.now(timezone.utc).isoformat(),
        }
        # Cache for last-known fallback (7-day TTL)
        try:
            _redis_set(NGX_LAST_KNOWN_KEY, {
                'value':          payload['value'],
                'change_pct_24h': payload['change_pct_24h'],
            }, ttl=7 * 24 * 3600)
        except Exception:
            pass
        print(f"[Nigeria Stability] NGX: {payload['value']:,.2f} ({payload['change_pct_24h']:+.2f}%)")
        return payload
    except Exception as e:
        print(f'[Nigeria Stability] NGX fetch error: {str(e)[:80]}')

    # Last-known fallback
    try:
        cached = _redis_get(NGX_LAST_KNOWN_KEY)
        if cached:
            return {
                'index':           'NGSE',
                'value':           cached.get('value'),
                'change_pct_24h':  cached.get('change_pct_24h', 0),
                'trend':           'unknown',
                'source':          'Yahoo Finance (last known)',
                'sparkline':       [],
                'estimated':       True,
                'timestamp':       datetime.now(timezone.utc).isoformat(),
            }
    except Exception:
        pass
    return {
        'index':           'NGSE',
        'value':           None,
        'change_pct_24h':  0,
        'trend':           'unknown',
        'source':          'Unavailable',
        'sparkline':       [],
        'timestamp':       datetime.now(timezone.utc).isoformat(),
    }


def _fetch_ngn_usd():
    """
    Fetch NGN/USD exchange rate from Yahoo Finance.
    Yahoo ticker: NGN=X (Naira per USD; rising = weaker naira)
    Returns Financial Pulse-shaped dict.
    """
    print('[Nigeria Stability] Fetching NGN/USD (NGN=X)...')
    NGN_LAST_KNOWN_KEY = 'ngn_last_known'
    try:
        data = _fetch_yahoo_chart('NGN=X', 'NGN%3DX')
        if data is None:
            raise Exception('Yahoo chart fetch returned None')

        payload = {
            'index':           'NGN/USD',
            'value':           round(data['price'], 2),
            'change_pct_24h':  data['change_pct'],
            'trend':           'rising' if data['change_pct'] > 0.3 else ('falling' if data['change_pct'] < -0.3 else 'flat'),
            'source':          'Yahoo Finance',
            'sparkline':       data['sparkline'],
            'timestamp':       datetime.now(timezone.utc).isoformat(),
        }
        try:
            _redis_set(NGN_LAST_KNOWN_KEY, {
                'value':          payload['value'],
                'change_pct_24h': payload['change_pct_24h'],
            }, ttl=7 * 24 * 3600)
        except Exception:
            pass
        print(f"[Nigeria Stability] NGN/USD: {payload['value']:,.2f} ({payload['change_pct_24h']:+.2f}%)")
        return payload
    except Exception as e:
        print(f'[Nigeria Stability] NGN/USD fetch error: {str(e)[:80]}')

    try:
        cached = _redis_get(NGN_LAST_KNOWN_KEY)
        if cached:
            return {
                'index':           'NGN/USD',
                'value':           cached.get('value'),
                'change_pct_24h':  cached.get('change_pct_24h', 0),
                'trend':           'unknown',
                'source':          'Yahoo Finance (last known)',
                'sparkline':       [],
                'estimated':       True,
                'timestamp':       datetime.now(timezone.utc).isoformat(),
            }
    except Exception:
        pass
    return {
        'index':           'NGN/USD',
        'value':           None,
        'change_pct_24h':  0,
        'trend':           'unknown',
        'source':          'Unavailable',
        'sparkline':       [],
        'timestamp':       datetime.now(timezone.utc).isoformat(),
    }


def _fetch_brent_full():
    """
    Fetch Brent crude full Financial Pulse payload.
    Yahoo ticker: BZ=F
    """
    print('[Nigeria Stability] Fetching Brent Crude full (BZ=F)...')
    BRENT_LAST_KNOWN_KEY = 'brent_last_known_nigeria'
    try:
        data = _fetch_yahoo_chart('BZ=F', 'BZ%3DF')
        if data is None:
            raise Exception('Yahoo chart fetch returned None')

        payload = {
            'index':           'BRENT',
            'value':           round(data['price'], 2),
            'change_pct_24h':  data['change_pct'],
            'trend':           'rising' if data['change_pct'] > 0.3 else ('falling' if data['change_pct'] < -0.3 else 'flat'),
            'source':          'Yahoo Finance (ICE Brent)',
            'sparkline':       data['sparkline'],
            'timestamp':       datetime.now(timezone.utc).isoformat(),
        }
        try:
            _redis_set(BRENT_LAST_KNOWN_KEY, {
                'value':          payload['value'],
                'change_pct_24h': payload['change_pct_24h'],
            }, ttl=7 * 24 * 3600)
        except Exception:
            pass
        print(f"[Nigeria Stability] Brent: ${payload['value']:,.2f} ({payload['change_pct_24h']:+.2f}%)")
        return payload
    except Exception as e:
        print(f'[Nigeria Stability] Brent fetch error: {str(e)[:80]}')

    try:
        cached = _redis_get(BRENT_LAST_KNOWN_KEY)
        if cached:
            return {
                'index':           'BRENT',
                'value':           cached.get('value'),
                'change_pct_24h':  cached.get('change_pct_24h', 0),
                'trend':           'unknown',
                'source':          'Yahoo Finance (last known)',
                'sparkline':       [],
                'estimated':       True,
                'timestamp':       datetime.now(timezone.utc).isoformat(),
            }
    except Exception:
        pass
    return {
        'index':           'BRENT',
        'value':           None,
        'change_pct_24h':  0,
        'trend':           'unknown',
        'source':          'Unavailable',
        'sparkline':       [],
        'timestamp':       datetime.now(timezone.utc).isoformat(),
    }


# ============================================
# FINANCIAL PULSE ASSEMBLY
# ============================================

def _build_financial_pulse(ngx, ngn, brent):
    """
    Build the canonical Financial Pulse card payload.
    Tiles: NGX (standard polarity) · NGN/USD (INVERTED — rising = weaker naira) · Brent (standard)
    """
    ngx_status   = _ngx_market_status()
    # NGN/USD is FX — trades essentially 24/5. Mirror Brent's logic for liveness.
    ngn_status   = _brent_market_status()
    brent_status = _brent_market_status()

    tiles = {
        'NGSE': {
            'name':            'NGX All-Share',
            'ticker':          '^NGSE',
            'value':           ngx.get('value'),
            'change_pct_24h':  ngx.get('change_pct_24h'),
            'trend':           ngx.get('trend'),
            'tier':            _tier(ngx.get('change_pct_24h')),
            'source':          ngx.get('source'),
            'market_status':   ngx_status,
            'timestamp':       ngx.get('timestamp'),
            'sparkline':       ngx.get('sparkline', []),
        },
        'NGNUSD': {
            'name':            'NGN/USD',
            'ticker':          'NGN=X',
            'value':           ngn.get('value'),
            'change_pct_24h':  ngn.get('change_pct_24h'),
            'trend':           ngn.get('trend'),
            'tier':            _tier(ngn.get('change_pct_24h'), inverted=True),
            'source':          ngn.get('source'),
            'market_status':   ngn_status,
            'timestamp':       ngn.get('timestamp'),
            'sparkline':       ngn.get('sparkline', []),
            'note':            'Inverted polarity: rising NGN/USD = weaker naira',
        },
        'BRENT': {
            'name':            'Brent Crude',
            'ticker':          'BZ=F',
            'value':           brent.get('value'),
            'change_pct_24h':  brent.get('change_pct_24h'),
            'trend':           brent.get('trend'),
            'tier':            _tier(brent.get('change_pct_24h')),
            'source':          brent.get('source'),
            'market_status':   brent_status,
            'timestamp':       brent.get('timestamp'),
            'sparkline':       brent.get('sparkline', []),
        },
    }

    agg_status = _aggregate_market_status([ngx_status, ngn_status, brent_status])

    return {
        'country':         'NG',
        'card_label':      'Nigeria Financial Pulse',
        'last_refreshed':  datetime.now(timezone.utc).isoformat(),
        'market_status':   agg_status,
        'tiles':           tiles,
    }


# ============================================
# MAIN SCAN
# ============================================

def run_nigeria_stability_scan(force=False):
    """
    Run a full Nigeria Financial Pulse scan.
    Returns the canonical payload.
    """
    print(f'[Nigeria Stability] Starting scan at {datetime.now(timezone.utc).isoformat()}')
    scan_start = time.time()

    # Cache check
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['from_cache'] = True
            print(f'[Nigeria Stability] Cache hit — returning cached payload')
            return cached

    # Fetch each tile (independent — one failure does not block others)
    ngx   = _fetch_ngx_index()
    ngn   = _fetch_ngn_usd()
    brent = _fetch_brent_full()

    fp = _build_financial_pulse(ngx, ngn, brent)

    payload = {
        'country':         'NG',
        'country_name':    'Nigeria',
        'ngx':             ngx,
        'ngn_usd':         ngn,
        'brent':           brent,
        'financial_pulse': fp,
        'scanned_at':      datetime.now(timezone.utc).isoformat(),
        'scan_duration_sec': round(time.time() - scan_start, 1),
        'success':         True,
        'version':         '1.0.0-nigeria-stability',
        'from_cache':      False,
    }

    _redis_set(CACHE_KEY, payload, ttl=CACHE_TTL)

    # History snapshot (no TTL — pruned to last 30 by daily cron, optional future)
    try:
        history = _redis_get(HISTORY_KEY) or []
        history.append({
            'scanned_at':     payload['scanned_at'],
            'ngx_value':      ngx.get('value'),
            'ngn_usd_value':  ngn.get('value'),
            'brent_value':    brent.get('value'),
        })
        history = history[-30:]
        _redis_set(HISTORY_KEY, history, ttl=None)
    except Exception:
        pass

    print(f"[Nigeria Stability] Scan complete in {payload['scan_duration_sec']}s | "
          f"NGX={ngx.get('value')} · NGN/USD={ngn.get('value')} · Brent={brent.get('value')}")
    return payload


# ============================================
# BACKGROUND REFRESH
# ============================================

def _background_refresh_loop():
    """12-hour background refresh loop. Daemon thread."""
    time.sleep(90)  # boot delay
    while True:
        try:
            print('[Nigeria Stability] Background refresh triggered')
            run_nigeria_stability_scan(force=True)
        except Exception as e:
            print(f'[Nigeria Stability] Background refresh error: {str(e)[:120]}')
        time.sleep(CACHE_TTL)


# ============================================
# FLASK ENDPOINTS
# ============================================

def register_nigeria_stability_endpoints(app, start_background=True):
    """
    Register Nigeria Stability endpoints on the Flask app.

    Endpoints:
      GET /api/nigeria/stability             full payload (cached)
      GET /api/nigeria/stability?force=true  bypass cache, fresh scan
      GET /api/nigeria/stability/summary     lightweight summary (Financial Pulse only)
      GET /api/nigeria/stability/history     last 30 scan snapshots
    """

    @app.route('/api/nigeria/stability', methods=['GET', 'OPTIONS'])
    def api_nigeria_stability():
        if request.method == 'OPTIONS':
            return '', 200
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            payload = run_nigeria_stability_scan(force=force)
            return app.response_class(
                response=json.dumps(payload, default=str),
                status=200,
                mimetype='application/json',
            )
        except Exception as e:
            print(f'[Nigeria Stability] Endpoint error: {str(e)[:120]}')
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/nigeria/stability/summary', methods=['GET', 'OPTIONS'])
    def api_nigeria_stability_summary():
        if request.method == 'OPTIONS':
            return '', 200
        try:
            payload = run_nigeria_stability_scan(force=False)
            return jsonify({
                'success':         True,
                'country':         'NG',
                'country_name':    'Nigeria',
                'financial_pulse': payload.get('financial_pulse', {}),
                'scanned_at':      payload.get('scanned_at'),
                'version':         '1.0.0-nigeria-stability',
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/nigeria/stability/history', methods=['GET', 'OPTIONS'])
    def api_nigeria_stability_history():
        if request.method == 'OPTIONS':
            return '', 200
        try:
            history = _redis_get(HISTORY_KEY) or []
            return jsonify({
                'success':  True,
                'country':  'NG',
                'history':  history,
                'count':    len(history),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    if start_background:
        t = threading.Thread(target=_background_refresh_loop, daemon=True)
        t.start()
        print('[Nigeria Stability] Background thread started (12h cycle)')

    print('[Nigeria Stability] ✅ Endpoints registered: /api/nigeria/stability (+ /summary, /history)')
