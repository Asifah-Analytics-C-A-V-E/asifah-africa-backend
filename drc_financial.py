# -*- coding: utf-8 -*-
"""
Asifah Analytics - Democratic Republic of the Congo Financial Pulse
v1.0.0 - November 2026  |  Africa backend

Canonical Financial Pulse card, DRC edition. Cloned from car_financial.py
(same throttle discipline, cross-worker lock, absence-honest empty tiles).
What changes is WHICH four numbers answer the DRC's questions.

FOUR TILES -- each answers a DIFFERENT question:

  1. COPPER (via the ME commodity proxy; HG=F fallback)
                       The revenue line. The Katanga copper belt (Kolwezi,
                       Lubumbashi) is the state's real income; copper sales to
                       the US grew sharply under the US-DRC strategic
                       partnership (signed 4 Dec 2025). Cobalt is mostly a
                       by-product of copper mining.

  2. COBALT (dated reference -- no clean live ticker)
                       The leverage line. The DRC mines roughly 70% of the
                       world's cobalt and has run export quotas since 2025.
                       There is no exchange-traded cobalt price on Yahoo (the
                       ME tracker's BATT is a battery ETF, not cobalt), so this
                       tile is a dated Platts reading and says so.

  3. GOLD (via the ME commodity proxy; GC=F fallback)
                       The war line. Eastern Congo's artisanal gold (Ituri, the
                       Kivus) is the armed groups' cash, and much of it is
                       reported to leave through Uganda, Rwanda and Burundi
                       toward UAE refiners. The price is what that gold is
                       worth, not who holds it.

  4. USD/CDF (CDF=X live if Yahoo carries it; else a dated BCC reading)
                       The household line. The Congolese franc, interbank vs
                       parallel. A widening gap is the stress signal.

DOCTRINE: SENSOR. Prices, deltas, market status, sources and timestamps. The
analyst layer interprets. No tile is ever filled with an invented number.

ENDPOINTS:
  GET /api/africa/financial/drc             (Redis-cached, 12h)
  GET /api/africa/financial/drc?force=true  (bypass cache; no Claude calls)
  GET /debug/drc-financial                  (which tickers resolved)

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import random
import threading
from datetime import datetime, timezone, timedelta

import requests
from flask import jsonify, request

VERSION = '1.0.0'

UPSTASH_REDIS_URL   = (os.environ.get('UPSTASH_REDIS_URL')
                       or os.environ.get('UPSTASH_REDIS_REST_URL') or '').rstrip('/')
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN') or '')

REDIS_KEY      = 'africa:financial:drc'
HISTORY_KEY    = 'africa:financial:drc:history'
CACHE_TTL_SEC  = 12 * 3600
REFRESH_SEC    = 12 * 3600
SCAN_LOCK_KEY  = 'lock:drc:financial:scan'

# ── MINERALS ROUTE REFERENCE (static, sourced, data_as_of) ──
ROUTE_REFERENCE = {
    'corridors': [
        {'name': 'Lobito Corridor (Kolwezi - Zambia - Lobito, Angola)', 'port': 'Lobito', 'country': 'Angola',
         'note': 'US/EU-backed Atlantic rail route for Katanga copper and cobalt, built to route around East African ports.'},
        {'name': 'Southern road and rail to Dar es Salaam and Durban', 'port': 'Dar es Salaam / Durban', 'country': 'Tanzania / South Africa',
         'note': 'The historic export route for most copper-cobalt hydroxide headed to China.'},
        {'name': 'Eastern artisanal routes (Kivus, Ituri)', 'port': None, 'country': 'Uganda / Rwanda / Burundi',
         'note': 'Gold and coltan leave the east largely informally; UN experts have documented flows through neighbours toward UAE refiners.'},
    ],
    'note': ('The money and the war sit at opposite ends of the country: copper and cobalt in the '
             'south-east (Katanga), conflict gold and coltan in the east (the Kivus, Ituri).'),
    'source': 'Commodity tracker country profile; UN Group of Experts reporting',
    'data_as_of': '2026-11',
}

# ── COBALT (dated reading; no clean live feed) ──
COBALT_REFERENCE = {
    'metal_usd_per_lb': 17.22,
    'metal_usd_per_lb_prior': 25.75,
    'prior_as_of': '2026-07-01',
    'as_of': '2026-10-12',
    'note': ('Cobalt metal (99.95%, EXW Shanghai) fell about a third between 1 July and 12 October '
             '2026 as DRC shipments delayed by the export quotas finally reached China (hydroxide '
             'imports jumped in July-August). Market participants were watching for quota '
             'adjustments rather than a new ban.'),
    'source': 'S&P Global Platts (13 Oct 2026)',
    'source_url': 'https://www.spglobal.com/energy/en/news-research/latest-news/metals/101326-trade-review-asian-cobalt-market-to-remain-pressured-in-q4-amid-lackluster-demand',
}

# ── CONGOLESE FRANC (dated BCC reading; used when no live ticker resolves) ──
CDF_REFERENCE = {
    'interbank_cdf_per_usd': 2265.67,
    'parallel_cdf_per_usd': 2327.89,
    'as_of': '2026-10-09',
    'inflation_note': ('Cumulative inflation 7.4% since end-December 2025; the central bank '
                       'projects 8.9% for 2026 and 6.4% for 2027.'),
    'source': 'Banque Centrale du Congo via ACP (12 Oct 2026)',
    'source_url': 'https://acp.cd/anglais/drc-foreign-exchange-market-congolese-franc-appreciates-in-both-market-segments/',
}


# ════════════════════════════════════════════════════════════
# REDIS
# ════════════════════════════════════════════════════════════

def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get('%s/get/%s' % (UPSTASH_REDIS_URL, key),
                         headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
                         timeout=5)
        d = r.json()
        if d.get('result'):
            return json.loads(d['result'])
    except Exception as e:
        print('[DRC Financial] Redis get error: %s' % str(e)[:120])
    return None


def _redis_set(key, value, ttl=None):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        payload = ['SET', key, json.dumps(value, default=str)]
        if ttl:
            payload.extend(['EX', str(int(ttl))])
        r = requests.post(UPSTASH_REDIS_URL,
                          headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN,
                                   'Content-Type': 'application/json'},
                          json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print('[DRC Financial] Redis set error: %s' % str(e)[:120])
        return False


def _acquire_scan_lock(ttl_sec=600):
    """Cross-worker atomic lock -- only the lock-owning worker runs the
    background refresh."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return True
    try:
        r = requests.post(UPSTASH_REDIS_URL,
                          headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN,
                                   'Content-Type': 'application/json'},
                          json=['SET', SCAN_LOCK_KEY,
                                datetime.now(timezone.utc).isoformat(),
                                'NX', 'EX', ttl_sec],
                          timeout=8)
        return (r.json() or {}).get('result') == 'OK'
    except Exception:
        return True


# ════════════════════════════════════════════════════════════
# YAHOO FETCHER  (canonical helper + query1 -> query2 failover + throttle)
# ════════════════════════════════════════════════════════════

_LAST_ERRORS = {}

# Yahoo rate-limit discipline, inherited from kazakhstan_financial_pulse.
# A 429 IS NOT A MISSING TICKER -- it is a throttle signal, and a failover chain
# that sprints past it deepens the limit while learning nothing.
_YF_MIN_GAP_SEC = 2.0
_YF_MAX_429_RETRY = 2
_yf_last_call = [0.0]
_yf_gap_lock = threading.Lock()
_THROTTLED = set()

_YF_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/124.0.0.0 Safari/537.36'),
    'Accept': 'application/json',
}


def _yf_throttle():
    with _yf_gap_lock:
        elapsed = time.time() - _yf_last_call[0]
        if elapsed < _YF_MIN_GAP_SEC:
            time.sleep(_YF_MIN_GAP_SEC - elapsed)
        _yf_last_call[0] = time.time()


def _fetch_yahoo_chart_with_sparkline(ticker, ticker_url_encoded=None):
    """Canonical Yahoo helper. Returns dict with value / change_pct_24h /
    sparkline (30d) / source / timestamp, or None.

    SPARKLINE-DERIVED 24H MATH: previousClose can equal chartPreviousClose on
    weekends (both drift to chart-range-start), so the 24h delta comes from
    sparkline[-1] vs sparkline[-2] -- always the last two trading days.

    '=' in a Yahoo ticker MUST be percent-encoded to %3D in the URL path.
    """
    if ticker_url_encoded is None:
        ticker_url_encoded = ticker.replace('=', '%3D').replace('^', '%5E')
    _THROTTLED.discard(ticker)

    for attempt in range(_YF_MAX_429_RETRY + 1):
        saw_429 = False
        for host in ('query1', 'query2'):
            url = ('https://%s.finance.yahoo.com/v8/finance/chart/%s'
                   % (host, ticker_url_encoded))
            try:
                _yf_throttle()
                r = requests.get(url, params={'interval': '1d', 'range': '1mo'},
                                 timeout=10, headers=_YF_HEADERS)
                if r.status_code == 429:
                    saw_429 = True
                    _LAST_ERRORS[ticker] = 'HTTP 429 (rate limited) via %s' % host
                    print('[DRC Financial] %s via %s: HTTP 429 -- backing off'
                          % (ticker, host))
                    continue
                _LAST_ERRORS[ticker] = 'HTTP %s via %s' % (r.status_code, host)
                if r.status_code != 200:
                    print('[DRC Financial] %s via %s: HTTP %s'
                          % (ticker, host, r.status_code))
                    continue
                data = r.json()
                result = (data.get('chart', {}).get('result') or [{}])[0]
                meta = result.get('meta', {})

                sparkline = []
                try:
                    timestamps = result.get('timestamp', []) or []
                    closes = ((result.get('indicators', {}).get('quote')
                               or [{}])[0].get('close', []) or [])
                    for i, ts in enumerate(timestamps):
                        if i < len(closes) and closes[i] is not None:
                            sparkline.append({
                                'time': datetime.fromtimestamp(
                                    ts, tz=timezone.utc).date().isoformat(),
                                'value': round(float(closes[i]), 4),
                            })
                except Exception:
                    pass

                price = meta.get('regularMarketPrice')
                if price is None and sparkline:
                    price = sparkline[-1]['value']

                prev_close = None
                if len(sparkline) >= 2:
                    prev_close = sparkline[-2]['value']
                if prev_close in (None, 0):
                    prev_close = (meta.get('previousClose')
                                  or meta.get('chartPreviousClose'))

                if price is None or prev_close in (None, 0):
                    continue

                change_pct = ((float(price) - float(prev_close))
                              / float(prev_close)) * 100
                return {
                    'value':          round(float(price), 4),
                    'change_pct_24h': round(change_pct, 2),
                    'sparkline':      sparkline[-30:],
                    'source':         'Yahoo Finance',
                    'ticker_used':    ticker,
                    'timestamp':      datetime.now(timezone.utc).isoformat(),
                }
            except Exception as e:
                _LAST_ERRORS[ticker] = '%s: %s' % (type(e).__name__, str(e)[:80])
                print('[DRC Financial] %s via %s: %s' % (ticker, host, str(e)[:100]))
                continue

        if saw_429 and attempt < _YF_MAX_429_RETRY:
            backoff = 5 * (2 ** attempt)
            print('[DRC Financial] %s: rate-limited, sleeping %ss (retry %d/%d)'
                  % (ticker, backoff, attempt + 1, _YF_MAX_429_RETRY))
            time.sleep(backoff)
            continue
        if saw_429:
            _THROTTLED.add(ticker)
            _LAST_ERRORS[ticker] = 'HTTP 429 (rate limited, retries exhausted)'
            print('[DRC Financial] %s: THROTTLED -- not a missing ticker.' % ticker)
            return None
        break

    print('[DRC Financial] %s: all hosts failed (last: %s)'
          % (ticker, _LAST_ERRORS.get(ticker, 'unknown')))
    return None


# ------------------------------------------------------------------
# COMMODITIES VIA THE COMMODITY PROXY -- ONE WRITER, MANY READERS (inherited note from the Burkina build)
#
# 11 Oct 2026. The Africa backend's IP is rate-limited by Yahoo; the ME
# backend's is not. On the same day, at the same minute, the Africa
# backend got HTTP 429 on GC=F while commodity_tracker on the ME backend
# returned GC=F at 4216.30 with a 21-point sparkline.
#
# So the Africa backend should not be asking Yahoo for gold at all. The
# price already crosses the wire inside the commodity payload that the
# stability page is ALREADY rendering. We read it from there.
#
# Direct function call, not a self-HTTP call: this module runs inside the
# same Flask app as the proxy, and a single-worker gunicorn calling back
# into itself deadlocks.
#
# NOTE ON SPARKLINE SHAPE: commodity_tracker emits a FLAT list of floats;
# the Yahoo fetcher above emits [{time, value}]. We pass the flat list
# through rather than inventing dates for points whose dates we were not
# given. The frontend accepts both shapes.
# ------------------------------------------------------------------
def _fetch_via_commodity_proxy(commodity, err_key):
    """Read one commodity price out of the Africa commodity proxy (the ME
    backend's commodity tracker, whose IP is not Yahoo-throttled).

    Returns the same dict shape as _fetch_yahoo_chart_with_sparkline, or None.
    ABSENCE-HONEST: a miss returns None and the tile says UNAVAILABLE."""
    try:
        from commodity_proxy_africa import get_africa_commodity_data
    except ImportError as e:
        _LAST_ERRORS[err_key] = 'commodity proxy not importable: %s' % str(e)[:60]
        return None
    try:
        data = get_africa_commodity_data('drc') or {}
        for tile in (data.get('commodity_summaries') or []):
            if tile.get('commodity') != commodity:
                continue
            spark = tile.get('sparkline') or {}
            price = spark.get('price')
            if price is None:
                continue
            pct = spark.get('change_pct_1d')
            series = [p for p in (spark.get('spark') or []) if p is not None]
            src = 'commodity_tracker (ME) via Africa proxy'
            if spark.get('fallback_used'):
                src += ' -- FALLBACK TICKER'
            _LAST_ERRORS.pop(err_key, None)
            return {
                'value':          round(float(price), 4),
                'change_pct_24h': (round(float(pct), 2) if pct is not None else None),
                'change_pct_30d': spark.get('change_pct_30d'),
                'sparkline':      series[-30:],
                'source':         src,
                'ticker_used':    spark.get('source_ticker_used') or spark.get('ticker') or err_key,
                'timestamp':      spark.get('last_updated'),
                'via_proxy':      True,
            }
        _LAST_ERRORS[err_key] = 'commodity proxy returned no %s price' % commodity
    except Exception as e:
        _LAST_ERRORS[err_key] = 'proxy read %s: %s' % (type(e).__name__, str(e)[:60])
    return None


def _fetch_with_failover(primary, fallback=None):
    """Try primary, then fallback. ABSENCE-HONEST: returns None if both fail.

    THROTTLE-AWARE: if the primary was rate-limited (429) rather than genuinely
    missing, do NOT try the fallback -- a 429 says nothing about whether the
    fallback exists, and firing it deepens the limit for zero information."""
    out = _fetch_yahoo_chart_with_sparkline(primary)
    if out:
        return out
    if primary in _THROTTLED:
        print('[DRC Financial] %s THROTTLED -- skipping fallback %s'
              % (primary, fallback))
        return None
    if fallback:
        print('[DRC Financial] %s failed -- trying fallback %s' % (primary, fallback))
        return _fetch_yahoo_chart_with_sparkline(fallback)
    return None


def _commodity_market_status():
    """Gold and Brent futures trade nearly 24h Sunday evening to Friday evening."""
    now = datetime.now(timezone.utc)
    wd = now.weekday()
    if wd == 5:
        return 'closed'
    if wd == 6 and now.hour < 23:
        return 'closed'
    return 'open'


def _fx_market_status():
    """FX is 24/5."""
    now = datetime.now(timezone.utc)
    wd = now.weekday()
    if wd == 5:
        return 'closed'
    if wd == 6 and now.hour < 21:
        return 'closed'
    if wd == 4 and now.hour >= 22:
        return 'closed'
    return 'open'


def _aggregate_market_status(statuses):
    if 'open' in statuses:
        return 'open'
    if 'pre-market' in statuses:
        return 'pre-market'
    if 'after-hours' in statuses:
        return 'after-hours'
    return 'closed'


# ════════════════════════════════════════════════════════════
# TIER LOGIC (polarity-aware)
# ════════════════════════════════════════════════════════════

def _fp_tier(chg, inverted=False):
    """Tile colour band.
      Standard polarity (copper, gold): rising = more value in the export economy.
      Inverted polarity (USD/CDF): rising = a weaker franc = bad.
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


def _trend(chg):
    v = chg or 0
    return 'rising' if v > 0.3 else ('falling' if v < -0.3 else 'flat')


def _empty_tile(name, ticker, market_status, note, chain=None):
    """Shell tile when a fetcher fails -- keeps shape consistent and is
    ABSENCE-HONEST. We never invent a number to fill a tile."""
    _chain = chain or [ticker]
    throttled = any(tk in _THROTTLED for tk in _chain)
    return {
        'name':           name,
        'ticker':         ticker,
        'value':          None,
        'change_pct_24h': None,
        'trend':          'flat',
        'tier':           'stable',
        'source':         None,
        'market_status':  market_status,
        'timestamp':      None,
        'sparkline':      [],
        'note':           note,
        'unavailable':    True,
        'throttled':      throttled,
        'unavailable_reason': ('rate_limited' if throttled else 'no_data'),
        'last_error':     _LAST_ERRORS.get(ticker),
    }


# ════════════════════════════════════════════════════════════
# BUILD THE CARD
# ════════════════════════════════════════════════════════════

def _live_tile(name, ticker, d, status, inverted, note, **extra):
    t = {
        'name':           name,
        'ticker':         d.get('ticker_used') or ticker,
        'value':          d.get('value'),
        'change_pct_24h': d.get('change_pct_24h'),
        'change_pct_30d': d.get('change_pct_30d'),
        'trend':          _trend(d.get('change_pct_24h')),
        'tier':           _fp_tier(d.get('change_pct_24h'), inverted=inverted),
        'source':         d.get('source'),
        'market_status':  status,
        'timestamp':      d.get('timestamp'),
        'sparkline':      d.get('sparkline', []),
        'note':           note,
    }
    t.update(extra)
    return t


def _reference_tile(name, value, display, tier, src, src_url, as_of, note, **extra):
    t = {
        'name': name, 'ticker': 'reference', 'value': value, 'display': display,
        'change_pct_24h': None, 'trend': 'flat', 'tier': tier,
        'source': src, 'source_url': src_url, 'market_status': 'reference',
        'timestamp': as_of, 'sparkline': [], 'reference': True, 'note': note,
    }
    t.update(extra)
    return t


def _build_financial_pulse(copper, gold, cdf):
    comm_status = _commodity_market_status()
    fx_status   = _fx_market_status()
    tiles = {}

    copper_note = ('The revenue line: Katanga copper (Kolwezi, Lubumbashi) is the state\'s real '
                   'income, and cobalt mostly comes out of the same mines. Sales to the US rose '
                   'sharply under the US-DRC strategic partnership signed on 4 Dec 2025.')
    tiles['COPPER'] = (_live_tile('Copper', 'HG=F', copper, comm_status, False, copper_note,
                                  route_name='Katanga -> Lobito / Dar es Salaam / Durban',
                                  route_reference=ROUTE_REFERENCE)
                       if copper else _empty_tile('Copper', 'HG=F', comm_status, 'The DRC\'s main export'))

    c = COBALT_REFERENCE
    move = round((c['metal_usd_per_lb'] / c['metal_usd_per_lb_prior'] - 1) * 100)
    tiles['COBALT'] = _reference_tile(
        'Cobalt metal', c['metal_usd_per_lb'],
        '$%.2f/lb (%+d%% since %s)' % (c['metal_usd_per_lb'], move, c['prior_as_of']),
        'stress' if move <= -20 else ('warning' if move <= -10 else ('rally' if move >= 10 else 'stable')),
        c['source'], c['source_url'], c['as_of'],
        ('DATED READING, NOT A LIVE FEED (as of %s). The DRC mines about 70%% of the world\'s cobalt '
         'and has rationed exports by quota since 2025; this price is where that leverage shows. %s'
         % (c['as_of'], c['note'])),
        change_since_prior_pct=move)

    gold_note = ('The war line: eastern Congo\'s artisanal gold (Ituri, the Kivus) is armed-group '
                 'cash, and UN experts report much of it leaving through neighbours toward UAE '
                 'refiners. The price is what that gold is worth, not who holds it.')
    tiles['GOLD'] = (_live_tile('Gold', 'GC=F', gold, comm_status, False, gold_note,
                                route_name='Ituri / Kivus -> neighbours -> Dubai')
                     if gold else _empty_tile('Gold', 'GC=F', comm_status, 'Eastern Congo\'s conflict-finance export'))

    r = CDF_REFERENCE
    gap = round((r['parallel_cdf_per_usd'] / r['interbank_cdf_per_usd'] - 1) * 100, 1)
    cdf_note = ('INVERTED polarity: a rising USD/CDF is a weaker franc and dearer imports. The '
                'stress signal is the gap between the interbank and street rates (%.1f%% as of %s). %s'
                % (gap, r['as_of'], r['inflation_note']))
    if cdf:
        tiles['USDCDF'] = _live_tile('USD/CDF', 'CDF=X', cdf, fx_status, True, cdf_note,
                                     cdf_reference=CDF_REFERENCE, parallel_gap_pct=gap)
    else:
        tiles['USDCDF'] = _reference_tile(
            'USD/CDF (Congolese franc)', r['interbank_cdf_per_usd'],
            '%s interbank / %s street' % (format(r['interbank_cdf_per_usd'], ',.0f'), format(r['parallel_cdf_per_usd'], ',.0f')),
            'warning' if gap >= 5 else 'stable', r['source'], r['source_url'], r['as_of'],
            'DATED READING (no live ticker resolved). ' + cdf_note,
            parallel_gap_pct=gap, cdf_reference=CDF_REFERENCE)

    return {
        'country':        'DRC',
        'card_label':     'DR Congo Financial Pulse',
        'version':        VERSION,
        'last_refreshed': datetime.now(timezone.utc).isoformat(),
        'market_status':  _aggregate_market_status([comm_status, fx_status]),
        'tiles':          tiles,
        'route_reference':  ROUTE_REFERENCE,
        'cobalt_reference': COBALT_REFERENCE,
        'cdf_reference':    CDF_REFERENCE,
    }


def get_drc_financial(force=False):
    if not force:
        cached = _redis_get(REDIS_KEY)
        if cached and cached.get('last_refreshed'):
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(cached['last_refreshed'])).total_seconds()
                if age < CACHE_TTL_SEC:
                    cached['cache_status'] = 'hit'
                    return cached
            except Exception:
                pass

    print('[DRC Financial] Fetching fresh market data...')
    copper = _fetch_via_commodity_proxy('copper', 'HG=F')
    if copper is None:
        copper = _fetch_yahoo_chart_with_sparkline('HG=F')
    gold = _fetch_via_commodity_proxy('gold', 'GC=F')
    if gold is None:
        gold = _fetch_yahoo_chart_with_sparkline('GC=F')
    cdf = _fetch_yahoo_chart_with_sparkline('CDF=X')

    payload = _build_financial_pulse(copper, gold, cdf)
    payload['cache_status'] = 'fresh'
    resolved = [k for k, v in payload['tiles'].items() if not v.get('unavailable')]
    print('[DRC Financial] Tiles resolved: %d/4 -> %s' % (len(resolved), resolved))
    _redis_set(REDIS_KEY, payload, ttl=CACHE_TTL_SEC)
    try:
        history = _redis_get(HISTORY_KEY) or []
        history.append({'scanned_at': payload['last_refreshed'],
                        'copper_value': (copper or {}).get('value'),
                        'gold_value': (gold or {}).get('value'),
                        'cdf_value': (cdf or {}).get('value')})
        _redis_set(HISTORY_KEY, history[-30:], ttl=None)
    except Exception:
        pass
    return payload


# ════════════════════════════════════════════════════════════
# BACKGROUND REFRESH (cross-worker lock)
# ════════════════════════════════════════════════════════════

def _background_refresh():
    time.sleep(240 + random.randint(0, 240))     # jittered: shares Yahoo quota with other pulses
    while True:
        try:
            if _acquire_scan_lock(ttl_sec=600):
                get_drc_financial(force=True)
            else:
                print('[DRC Financial] Another worker owns the refresh window -- skipping')
        except Exception as e:
            print('[DRC Financial] Background error: %s' % str(e)[:120])
        time.sleep(REFRESH_SEC + random.randint(0, 600))


def start_background_refresh():
    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()
    print('[DRC Financial] Background refresh started (12h cycle, cross-worker lock)')


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════

def register_drc_financial_endpoints(app, start_background=True):

    @app.route('/api/africa/financial/drc', methods=['GET'])
    def api_africa_financial_drc():
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            return jsonify(get_drc_financial(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200], 'country': 'DRC', 'tiles': {}}), 500

    @app.route('/debug/drc-financial', methods=['GET'])
    def debug_drc_financial():
        """Which tickers actually resolved -- first-deploy verification."""
        data = get_drc_financial(force=True)
        tiles = data.get('tiles', {})
        return jsonify({
            'version': VERSION, 'market_status': data.get('market_status'),
            'tickers': {k: {'ticker': v.get('ticker'), 'resolved': not v.get('unavailable', False),
                            'value': v.get('value'), 'change_24h': v.get('change_pct_24h'),
                            'sparkline_pts': len(v.get('sparkline') or []),
                            'reason': v.get('unavailable_reason')} for k, v in tiles.items()},
            'resolved_count': sum(1 for v in tiles.values() if not v.get('unavailable')),
            'last_errors': dict(_LAST_ERRORS),
            'redis_configured': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
        })

    if start_background:
        start_background_refresh()
    print('[DRC Financial] ✅ Endpoints registered: /api/africa/financial/drc, /debug/drc-financial')
