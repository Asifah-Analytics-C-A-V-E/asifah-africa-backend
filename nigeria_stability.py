# -*- coding: utf-8 -*-
"""
Nigeria Stability Backend — v1.0.2 (May 31 2026)
================================================

Lives on the Africa backend (asifah-africa-backend.onrender.com) alongside
the article gatherer, commodity proxy, and Sudan rhetoric tracker.

v1.0.2 ships:
  - NGX All-Share Index (real ASI value scraped from kwayisi/african-markets
    via new ngx_index_scraper.py module — Yahoo Finance does NOT host the NGX
    index directly, so we scrape with multi-pattern regex resilience)
  - NGN/USD exchange rate fetcher (Yahoo NGN=X) — INVERTED polarity
  - Brent crude full Financial Pulse fetcher (Yahoo BZ=F)
  - SPARKLINE-derived 24h math for Yahoo tiles (NGN/USD + Brent) — robust on weekends
  - NGX sparkline accumulates from our own scan history (Redis HISTORY_KEY)
  - Per-tile market_status (NGX Lagos Mon-Fri 09:00-16:00 WAT, Brent ICE 24/5, NGN/USD FX 24/5)
  - 12-hour Redis cache + background refresh

v1.0.2 explicitly does NOT include:
  - Stability vector scoring (deferred to v1.5)
  - Rhetoric tracker integration (Nigeria has no tracker yet — placeholder on frontend)
  - Humanitarian module
  - FX parallel-market premium (deferred to Black Swan Markets page)
  - Article scanning (handled by africa_article_gatherer)
  - Commodity exposure (handled by commodity_proxy_africa)
  - Historical NGX sparkline backfill (sparkline grows organically as we scan daily)

Patterns mirrored from saudi_stability.py for consistency.
"""

import os
import re
import json
import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

# NGX scraper (v1.0.2 — May 31 2026): pulls real NGX All-Share Index from
# african open data mirrors (kwayisi primary, african-markets fallback).
# Yahoo Finance does not host the NGX index directly.
try:
    from ngx_index_scraper import scrape_ngx_index
    NGX_SCRAPER_AVAILABLE = True
except ImportError as e:
    NGX_SCRAPER_AVAILABLE = False
    print(f'[Nigeria Stability] ⚠️ ngx_index_scraper not available: {e}')


# ============================================
# CONFIG
# ============================================

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL', '').rstrip('/')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '')

CACHE_KEY = 'nigeria_stability_v1.0.2'
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

def _ngx_lagos_market_status():
    """
    Nigerian Exchange Group (NGX) trading hours.

    Per african-markets news (April 27 2026): NGX expanded trading hours to
    9:00-16:00 WAT Mon-Fri (was previously 9:30-14:30).

    Lagos = UTC+1 year-round (no DST).
    Returns 'open' / 'closed' / 'pre-market' / 'after-hours'.
    """
    now = datetime.now(timezone.utc)
    lagos_time = now + timedelta(hours=1)
    weekday = lagos_time.weekday()  # Mon=0 ... Sun=6

    # Weekend = closed
    if weekday >= 5:
        return 'closed'

    h = lagos_time.hour
    m = lagos_time.minute
    minutes = h * 60 + m

    pre_open_minutes = 8 * 60        # 08:00 (pre-market window)
    open_minutes     = 9 * 60        # 09:00 (cash market open)
    close_minutes    = 16 * 60       # 16:00 (cash market close)
    after_hours_end  = 17 * 60       # 17:00 (after-hours window end)

    if minutes < pre_open_minutes:
        return 'closed'
    elif minutes < open_minutes:
        return 'pre-market'
    elif minutes < close_minutes:
        return 'open'
    elif minutes < after_hours_end:
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
      - change_pct_24h (yesterday → today, computed from sparkline NOT meta)
      - sparkline (list of {time, value})
    Returns None on error.

    v1.0.1 (May 31 2026): 24h math now derived from sparkline[-1] vs sparkline[-2].
    Previously used meta.previousClose / meta.chartPreviousClose, but on weekends
    Yahoo can return identical values for both fields (both equal chart-range start),
    causing change_pct_24h to display the monthly delta instead of the daily delta.
    Sparkline-derived math is robust because we explicitly use the last two trading
    days from the chart range.
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

        # Build sparkline FIRST so we can derive prev_close from it
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

        # Determine latest price (prefer regularMarketPrice meta, fall back to sparkline[-1])
        price = meta.get('regularMarketPrice')
        if price is None and sparkline:
            price = sparkline[-1]['value']

        # v1.0.1 sparkline-derived 24h delta
        prev_close = None
        if len(sparkline) >= 2:
            prev_close = sparkline[-2]['value']
        # Fallback chain if sparkline too short
        if prev_close in (None, 0):
            prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')

        if price is None or prev_close in (None, 0):
            return None
        change_pct = ((price - prev_close) / prev_close) * 100

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
    Fetch the NGX All-Share Index by scraping african open data mirrors.

    Primary: afx.kwayisi.org/ngx/  (kwayisi)
    Secondary: african-markets.com/en/stock-markets/ngse

    Yahoo Finance does NOT host the NGX index directly (confirmed via web search
    May 31 2026), so we scrape. The scraper module handles regex-based parsing
    with multi-pattern fallback for site-layout resilience.

    Sparkline: this function does NOT build a 30-day sparkline (the scrape
    sources don't expose historical chart data in scrapeable form). Instead,
    we accumulate sparkline data from our OWN historical scan snapshots over
    time — Redis HISTORY_KEY collects the last 30 values, which the frontend
    can render as the sparkline.

    Returns Financial Pulse-shaped dict. Returns 'Unavailable' state if both
    scrape sources fail AND no last-known cache exists.
    """
    NGX_LAST_KNOWN_KEY = 'ngx_last_known'

    if not NGX_SCRAPER_AVAILABLE:
        print('[Nigeria Stability] ⚠️ NGX scraper module not loaded — cannot fetch ASI')
        return _ngx_last_known_or_unavailable(NGX_LAST_KNOWN_KEY)

    print('[Nigeria Stability] Scraping NGX All-Share Index...')
    try:
        scraped = scrape_ngx_index()
        if scraped is None:
            raise Exception('Both kwayisi and african-markets unreachable')

        value = scraped['value']
        change_pct = scraped.get('change_pct_24h', 0) or 0

        # Build sparkline from our own scan history (if available)
        sparkline = _build_ngx_sparkline_from_history()

        payload = {
            'index':           'NGX-ASI',
            'value':           round(value, 2),
            'change_pct_24h':  round(change_pct, 3),
            'change_abs_24h':  scraped.get('change_24h'),
            'trend':           'rising' if change_pct > 0.3 else ('falling' if change_pct < -0.3 else 'flat'),
            'source':          f"Asifah scrape via {scraped.get('source', 'kwayisi')}",
            'sparkline':       sparkline,
            'timestamp':       datetime.now(timezone.utc).isoformat(),
        }
        # Cache for last-known fallback (7-day TTL)
        try:
            _redis_set(NGX_LAST_KNOWN_KEY, {
                'value':          payload['value'],
                'change_pct_24h': payload['change_pct_24h'],
                'change_abs_24h': payload.get('change_abs_24h'),
            }, ttl=7 * 24 * 3600)
        except Exception:
            pass
        print(f"[Nigeria Stability] NGX-ASI: {payload['value']:,.2f} ({payload['change_pct_24h']:+.2f}%)")
        return payload
    except Exception as e:
        print(f'[Nigeria Stability] NGX scrape error: {str(e)[:120]}')

    return _ngx_last_known_or_unavailable(NGX_LAST_KNOWN_KEY)


def _ngx_last_known_or_unavailable(redis_key):
    """Return last-known NGX value from Redis, or Unavailable shell."""
    try:
        cached = _redis_get(redis_key)
        if cached:
            return {
                'index':           'NGX-ASI',
                'value':           cached.get('value'),
                'change_pct_24h':  cached.get('change_pct_24h', 0),
                'change_abs_24h':  cached.get('change_abs_24h'),
                'trend':           'unknown',
                'source':          'Asifah scrape (last known)',
                'sparkline':       _build_ngx_sparkline_from_history(),
                'estimated':       True,
                'timestamp':       datetime.now(timezone.utc).isoformat(),
            }
    except Exception:
        pass
    return {
        'index':           'NGX-ASI',
        'value':           None,
        'change_pct_24h':  0,
        'trend':           'unknown',
        'source':          'Unavailable',
        'sparkline':       [],
        'timestamp':       datetime.now(timezone.utc).isoformat(),
    }


def _build_ngx_sparkline_from_history():
    """
    Build a sparkline from our accumulated scan history (Redis HISTORY_KEY).
    Returns list of {time, value} suitable for Chart.js.

    Since this is a scraped index, we don't have historical chart data
    from the source. Sparkline grows organically as we accumulate daily scans.
    """
    try:
        history = _redis_get(HISTORY_KEY) or []
        sparkline = []
        for entry in history[-30:]:  # last 30 snapshots
            ngx_val = entry.get('ngx_value')
            if ngx_val is None:
                continue
            ts_str = entry.get('scanned_at', '')
            # Extract date portion from ISO timestamp
            try:
                date_str = ts_str.split('T')[0] if 'T' in ts_str else ts_str[:10]
            except Exception:
                date_str = ts_str
            sparkline.append({
                'time':  date_str,
                'value': round(float(ngx_val), 2),
            })
        return sparkline
    except Exception as e:
        print(f'[Nigeria Stability] Sparkline build error: {str(e)[:80]}')
        return []


def _fetch_nge_etf():
    """
    [DEPRECATED IN v1.0.2 — kept as emergency fallback only, not called by scan]

    Fetch Global X MSCI Nigeria ETF (NGE) from Yahoo Finance.
    Yahoo ticker: NGE (US-listed NYSE Arca, USD-denominated)

    This function was the primary equity fetcher in v1.0.1 but was replaced
    by _fetch_ngx_index() (real NGX ASI via scraper) in v1.0.2 because NGE is
    a dormant ETF showing $3.74 with 0.00% daily change for months — it does
    not represent live Nigerian equity activity.

    Kept as one-line-swap emergency fallback if scraper module ever breaks:
      In run_nigeria_stability_scan(): swap `_fetch_ngx_index()` for `_fetch_nge_etf()`.
    """
    print('[Nigeria Stability] [DEPRECATED] Fetching Global X MSCI Nigeria ETF (NGE)...')
    NGE_LAST_KNOWN_KEY = 'nge_last_known'
    try:
        data = _fetch_yahoo_chart('NGE', 'NGE')
        if data is None:
            raise Exception('Yahoo chart fetch returned None')

        payload = {
            'index':           'NGE',
            'value':           round(data['price'], 2),
            'change_pct_24h':  data['change_pct'],
            'trend':           'rising' if data['change_pct'] > 0.3 else ('falling' if data['change_pct'] < -0.3 else 'flat'),
            'source':          'Yahoo Finance (NYSE Arca)',
            'sparkline':       data['sparkline'],
            'timestamp':       datetime.now(timezone.utc).isoformat(),
        }
        # Cache for last-known fallback (7-day TTL)
        try:
            _redis_set(NGE_LAST_KNOWN_KEY, {
                'value':          payload['value'],
                'change_pct_24h': payload['change_pct_24h'],
            }, ttl=7 * 24 * 3600)
        except Exception:
            pass
        print(f"[Nigeria Stability] NGE: ${payload['value']:,.2f} ({payload['change_pct_24h']:+.2f}%)")
        return payload
    except Exception as e:
        print(f'[Nigeria Stability] NGE fetch error: {str(e)[:80]}')

    # Last-known fallback
    try:
        cached = _redis_get(NGE_LAST_KNOWN_KEY)
        if cached:
            return {
                'index':           'NGE',
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
        'index':           'NGE',
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
    Tiles: NGX-ASI (real NGX All-Share, scraped) · NGN/USD (INVERTED) · Brent (standard)
    """
    # NGX trades 9-4 Lagos time Mon-Fri (10-14:30 historically, expanded April 2026)
    ngx_status   = _ngx_lagos_market_status()
    # NGN/USD is FX — trades essentially 24/5. Mirror Brent's logic for liveness.
    ngn_status   = _brent_market_status()
    brent_status = _brent_market_status()

    tiles = {
        'NGX': {
            'name':            'NGX All-Share',
            'ticker':          'NGX-ASI',
            'value':           ngx.get('value'),
            'change_pct_24h':  ngx.get('change_pct_24h'),
            'change_abs_24h':  ngx.get('change_abs_24h'),
            'trend':           ngx.get('trend'),
            'tier':            _tier(ngx.get('change_pct_24h')),
            'source':          ngx.get('source'),
            'market_status':   ngx_status,
            'timestamp':       ngx.get('timestamp'),
            'sparkline':       ngx.get('sparkline', []),
            'note':            'Real NGX All-Share Index — scraped from kwayisi (Yahoo does not host)',
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
    ngx   = _fetch_ngx_index()    # v1.0.2: scraped from kwayisi/african-markets
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
        'version':         '1.0.2-nigeria-stability',
        'from_cache':      False,
    }

    _redis_set(CACHE_KEY, payload, ttl=CACHE_TTL)

    # History snapshot (no TTL — pruned to last 30 by daily cron, optional future)
    # ngx_value is critical here — it builds the sparkline organically over time
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
                'version':         '1.0.2-nigeria-stability',
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
