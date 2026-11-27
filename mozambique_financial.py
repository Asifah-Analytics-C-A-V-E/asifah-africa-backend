# -*- coding: utf-8 -*-
"""
Asifah Analytics - Mozambique Financial Pulse
v1.0.0 - November 2026  |  Africa backend

Canonical Financial Pulse card, Mozambique edition. Cloned from
rwanda_financial.py (same throttle discipline, cross-worker lock,
absence-honest empty tiles).

THREE TILES -- each answers a DIFFERENT question:

  1. NATURAL GAS (via the ME commodity proxy; NG=F fallback)
                       The bet. Three LNG projects (Coral Sul exporting, Coral
                       Norte 2028, TotalEnergies 2029, ExxonMobil ~2031) are the
                       state's fiscal future. Henry Hub is the US benchmark;
                       Mozambican cargoes price off Asian (JKM) and European
                       (TTF) markets, which move with it but not in lockstep.

  2. BRENT (BZ=F, via proxy) -- INVERTED polarity
                       Mozambique imports its refined fuel; a rising barrel is a
                       cost for a state with no IMF programme.

  3. USD/MZN (MZN=X live if Yahoo carries it; else a dated reading)
                       The metical has been held near 63.7 to the dollar for
                       years. INVERTED: a rising USD/MZN is a weaker metical -- and
                       a break from the peg would itself be news.

Two dated reference blocks, because the stories have no live price: the LNG
PROJECTS (status of each) and the EXPORT ECONOMY (graphite, coal, the Mozal
smelter's shutdown, debt and the IMF).

DOCTRINE: SENSOR. Prices, deltas, market status, sources and timestamps. The
analyst layer interprets. No tile is ever filled with an invented number.

ENDPOINTS:
  GET /api/africa/financial/mozambique             (Redis-cached, 12h)
  GET /api/africa/financial/mozambique?force=true  (bypass cache; no Claude calls)
  GET /debug/mozambique-financial                  (which tickers resolved)

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

REDIS_KEY      = 'africa:financial:mozambique'
HISTORY_KEY    = 'africa:financial:mozambique:history'
CACHE_TTL_SEC  = 12 * 3600
REFRESH_SEC    = 12 * 3600
SCAN_LOCK_KEY  = 'lock:mozambique:financial:scan'

# ── LNG PROJECTS (dated reference; the status of each, not a price) ──
LNG_REFERENCE = {
    'projects': [
        {'name': 'Coral Sul FLNG (Eni)', 'capacity_mtpa': 3.4, 'status': 'Exporting since Q4 2022',
         'note': 'Offshore and floating: out of the insurgents\' reach.'},
        {'name': 'Coral Norte FLNG (Eni)', 'capacity_mtpa': 3.55, 'status': 'FID Oct 2025; drilling began Nov 2026; first LNG 2028',
         'note': 'A second floating unit; Eni plans a decision on a third by 2027.'},
        {'name': 'Mozambique LNG (TotalEnergies)', 'capacity_mtpa': 13.1, 'status': 'Force majeure lifted 7 Nov 2025; full restart 29 Jan 2026; first LNG targeted 2029',
         'note': ('$20B, onshore at Afungi, behind Mozambiquen troops. The UK and Dutch export-credit agencies withdrew '
                  'about $1.15B in Dec 2025; Total replaced the cover and US EXIM stayed.')},
        {'name': 'Rovuma LNG (ExxonMobil)', 'capacity_mtpa': 18.6, 'status': 'Revised plan approved Nov 2026; FID expected by end-2026; start-up ~2031',
         'note': 'About $26-30B; modular, electrified trains next to the Total site.'},
    ],
    'note': ('Together the projects would make Mozambique one of Africa\'s largest LNG exporters around 2030. The two '
             'offshore units are beyond the insurgents\' reach; the two onshore ones depend on the security of the '
             'Afungi peninsula.'),
    'as_of': '2026-11-27',
    'source': 'Rio Times (23 Oct 2026); Energy Connects / Bloomberg (18 Nov 2026); World Oil (Jan and Nov 2026); ISS (27 Nov 2026)',
    'source_url': 'https://www.energyconnects.com/news/gas-lng/2026/november/exxon-s-rovuma-lng-plan-wins-mozambique-government-approval/',
}

# ── THE EXPORT ECONOMY AND THE DEBT (dated reference) ──
ECONOMY_REFERENCE = {
    'note': ('Debt: 91.4% of GDP at end-2025, projected 94.6% in 2026, judged unsustainable by the IMF; no '
             'programme since the 2022 facility was suspended in 2025. Mozambique repaid the IMF early (about $630M, '
             'March 2026) and is negotiating a new programme, with a decision expected in December 2026; the '
             'state owes suppliers about $1.29B. Growth 1.7% in Q2 2026; inflation 6.31% in September; policy rate '
             '9.25%. Exports beyond gas: Balama graphite (restarted 2025 after the post-election force majeure), '
             'Moatize coking coal via the Nacala corridor, and rubies -- while the Mozal aluminium smelter, long the '
             'largest manufacturing exporter, was placed on care and maintenance on 16 Mar 2026 after failing to '
             'secure affordable power.'),
    'as_of': '2026-11',
    'source': 'Rio Times (23 Oct 2026, IMF figures); Africanews (2 Apr 2026); AIM / allAfrica (21 Sep 2026); Engineering News (16 Mar 2026)',
    'source_url': 'https://www.imf.org/en/news/articles/2026/02/14/pr-26052-mozambique-imf-executive-board-concludes-2025-article-iv-consultation-with-mozambique',
}

# ── METICAL (dated reading; used when no live ticker resolves) ──
MZN_REFERENCE = {
    'mzn_per_usd': 63.72,
    'as_of': '2026-10-23',
    'peg_note': ('The Bank of Mozambique has held the metical close to 63.7 per dollar for several years; a move '
                 'off that line would be a signal in itself.'),
    'source': 'Rio Times (23 Oct 2026 rates)',
    'source_url': 'https://www.riotimesonline.com/mozambique-economy-key-players-2026/',
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
        print('[Mozambique Financial] Redis get error: %s' % str(e)[:120])
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
        print('[Mozambique Financial] Redis set error: %s' % str(e)[:120])
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
                    print('[Mozambique Financial] %s via %s: HTTP 429 -- backing off'
                          % (ticker, host))
                    continue
                _LAST_ERRORS[ticker] = 'HTTP %s via %s' % (r.status_code, host)
                if r.status_code != 200:
                    print('[Mozambique Financial] %s via %s: HTTP %s'
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
                print('[Mozambique Financial] %s via %s: %s' % (ticker, host, str(e)[:100]))
                continue

        if saw_429 and attempt < _YF_MAX_429_RETRY:
            backoff = 5 * (2 ** attempt)
            print('[Mozambique Financial] %s: rate-limited, sleeping %ss (retry %d/%d)'
                  % (ticker, backoff, attempt + 1, _YF_MAX_429_RETRY))
            time.sleep(backoff)
            continue
        if saw_429:
            _THROTTLED.add(ticker)
            _LAST_ERRORS[ticker] = 'HTTP 429 (rate limited, retries exhausted)'
            print('[Mozambique Financial] %s: THROTTLED -- not a missing ticker.' % ticker)
            return None
        break

    print('[Mozambique Financial] %s: all hosts failed (last: %s)'
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
        data = get_africa_commodity_data('mozambique') or {}
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
        print('[Mozambique Financial] %s THROTTLED -- skipping fallback %s'
              % (primary, fallback))
        return None
    if fallback:
        print('[Mozambique Financial] %s failed -- trying fallback %s' % (primary, fallback))
        return _fetch_yahoo_chart_with_sparkline(fallback)
    return None


def _commodity_market_status():
    """Gas and Brent futures trade nearly 24h Sunday evening to Friday evening."""
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
      Standard polarity (gas): rising = more value in the export economy.
      Inverted polarity (Brent, USD/MZN): rising = a cost = bad.
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


def _build_financial_pulse(gas, brent, mzn):
    comm_status = _commodity_market_status()
    fx_status   = _fx_market_status()
    tiles = {}

    gas_note = ('The bet: Coral Sul exports now; Coral Norte (2028), TotalEnergies (2029) and ExxonMobil (~2031) '
                'are the state\'s fiscal future. This is Henry Hub, the US benchmark -- Mozambican cargoes price '
                'off Asian (JKM) and European (TTF) markets, which move with it but not in lockstep.')
    tiles['GAS'] = (_live_tile('Natural gas (benchmark)', 'NG=F', gas, comm_status, False, gas_note,
                               lng_reference=LNG_REFERENCE)
                    if gas else _empty_tile('Natural gas (benchmark)', 'NG=F', comm_status, 'Mozambique\'s LNG future'))

    brent_note = ('INVERTED polarity: Mozambique imports its refined fuel. A rising barrel is a cost for a state '
                  'with debt above 90% of GDP and no IMF programme.')
    tiles['BRENT'] = (_live_tile('Brent crude (import cost)', 'BZ=F', brent, comm_status, True, brent_note)
                      if brent else _empty_tile('Brent crude (import cost)', 'BZ=F', comm_status, 'Mozambique imports its fuel'))

    r = MZN_REFERENCE
    mzn_note = 'INVERTED polarity: a rising USD/MZN is a weaker metical and dearer imports. %s' % r['peg_note']
    if mzn:
        tiles['USDMZN'] = _live_tile('USD/MZN', 'MZN=X', mzn, fx_status, True, mzn_note, mzn_reference=MZN_REFERENCE)
    else:
        tiles['USDMZN'] = {
            'name': 'USD/MZN (metical)', 'ticker': 'reference', 'value': r['mzn_per_usd'],
            'display': '%.2f meticais per dollar' % r['mzn_per_usd'],
            'change_pct_24h': None, 'trend': 'flat', 'tier': 'stable',
            'source': r['source'], 'source_url': r['source_url'], 'market_status': 'reference',
            'timestamp': r['as_of'], 'sparkline': [], 'reference': True,
            'note': 'DATED READING (no live ticker resolved). ' + mzn_note, 'mzn_reference': MZN_REFERENCE,
        }

    return {
        'country':        'MOZAMBIQUE',
        'card_label':     'Mozambique Financial Pulse',
        'version':        VERSION,
        'last_refreshed': datetime.now(timezone.utc).isoformat(),
        'market_status':  _aggregate_market_status([comm_status, fx_status]),
        'tiles':          tiles,
        'lng_reference':     LNG_REFERENCE,
        'economy_reference': ECONOMY_REFERENCE,
        'mzn_reference':     MZN_REFERENCE,
    }


def get_mozambique_financial(force=False):
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

    print('[Mozambique Financial] Fetching fresh market data...')
    gas = _fetch_via_commodity_proxy('natural_gas', 'NG=F') or _fetch_yahoo_chart_with_sparkline('NG=F')
    brent = _fetch_via_commodity_proxy('oil', 'BZ=F') or _fetch_yahoo_chart_with_sparkline('BZ=F')
    mzn = _fetch_yahoo_chart_with_sparkline('MZN=X')

    payload = _build_financial_pulse(gas, brent, mzn)
    payload['cache_status'] = 'fresh'
    resolved = [k for k, v in payload['tiles'].items() if not v.get('unavailable')]
    print('[Mozambique Financial] Tiles resolved: %d/3 -> %s' % (len(resolved), resolved))
    _redis_set(REDIS_KEY, payload, ttl=CACHE_TTL_SEC)
    try:
        history = _redis_get(HISTORY_KEY) or []
        history.append({'scanned_at': payload['last_refreshed'],
                        'gas_value': (gas or {}).get('value'), 'brent_value': (brent or {}).get('value'),
                        'mzn_value': (mzn or {}).get('value')})
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
                get_mozambique_financial(force=True)
            else:
                print('[Mozambique Financial] Another worker owns the refresh window -- skipping')
        except Exception as e:
            print('[Mozambique Financial] Background error: %s' % str(e)[:120])
        time.sleep(REFRESH_SEC + random.randint(0, 600))


def start_background_refresh():
    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()
    print('[Mozambique Financial] Background refresh started (12h cycle, cross-worker lock)')


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════

def register_mozambique_financial_endpoints(app, start_background=True):

    @app.route('/api/africa/financial/mozambique', methods=['GET'])
    def api_africa_financial_mozambique():
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            return jsonify(get_mozambique_financial(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200], 'country': 'RWANDA', 'tiles': {}}), 500

    @app.route('/debug/mozambique-financial', methods=['GET'])
    def debug_mozambique_financial():
        """Which tickers actually resolved -- first-deploy verification."""
        data = get_mozambique_financial(force=True)
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
    print('[Mozambique Financial] ✅ Endpoints registered: /api/africa/financial/mozambique, /debug/mozambique-financial')
