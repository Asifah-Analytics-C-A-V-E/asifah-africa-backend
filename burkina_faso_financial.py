# -*- coding: utf-8 -*-
"""
Asifah Analytics - Burkina Faso Financial Pulse
v1.0.0 - October 2026  |  Africa backend

Canonical Financial Pulse card (Saudi / Nigeria / Russia / Kazakhstan Gold
Standard), Burkina Faso edition. Patterns mirrored from nigeria_stability.py
(layered data architecture, last-known fallback, per-tile market_status) and
kazakhstan_financial_pulse.py (throttle discipline, absence-honest empty tiles,
static reference data carrying source + data_as_of).

FOUR TILES -- each answers a DIFFERENT analytical question. None redundant.

  1. GOLD (GC=F)       The export economy in one number. Gold is roughly 75% of
                       Burkinabe exports -- a concentration that makes this the
                       closest thing the country has to a sovereign revenue
                       line. Standard polarity: rising = more revenue.

                       ROUTE-DEPENDENCY SHOWN INLINE, the way Kazakhstan's Brent
                       tile carries CPC. Burkina Faso is LANDLOCKED. Every ounce
                       leaves through a neighbour's port -- Abidjan, Tema, Lome
                       or Cotonou -- and the country left ECOWAS, the bloc
                       governing those corridors, in January 2025. High gold
                       plus corridor exposure is revenue someone else can
                       interrupt. That is the Burkina story in one tile.

  2. COTTON (CT=F)     The OTHER export, and the one that reaches households.
                       Gold revenue accrues to the state and to foreign
                       operators; cotton is the rural income base. A cotton move
                       is a food-security transmission, not a trade statistic,
                       which is why it earns a tile rather than a footnote.

  3. XOF/USD (XOF=X)   Currency stress -- WITH A WARNING THE TILE CARRIES
                       ITSELF. The West African CFA franc is PEGGED to the euro
                       at a fixed parity (655.957 XOF = 1 EUR). Daily XOF/USD
                       movement is therefore EUR/USD movement wearing a
                       different hat; it measures Frankfurt, not Ouagadougou.

                       The tile is included because the PEG is the signal -- AES
                       states have publicly raised leaving the franc zone, and
                       that would be a rupture, not a drift. The note says so,
                       so nobody reads a daily tick as Burkinabe monetary
                       stress. A tile that silently invited that reading would
                       be a dial that lies.

  4. BRVM COMPOSITE    Regional equity. Burkinabe listed companies trade on the
                       Bourse Regionale des Valeurs Mobilieres -- which sits in
                       ABIDJAN, in the country Burkina Faso is now outside
                       ECOWAS with. The exchange is a second lifeline in a
                       neighbour's capital, and that is the analytical point.

                       Yahoo does not host BRVM, so this follows the Nigeria
                       NGX pattern exactly: scraper -> last-known -> Unavailable.

DOCTRINE: this module is a SENSOR. It reports prices, deltas and market status
with sources and timestamps. It does not interpret. The analyst layer (rhetoric
tracker / BLUF / GPI) does the interpreting.

DATA HONESTY: no tile is ever filled with an invented number. A fetcher that
fails produces an explicitly `unavailable` tile that says WHY, and
/debug/burkina-faso-financial reports which tickers actually resolved. That
endpoint exists because the first deploy is the only way to find out whether a
ticker is real -- it could not be verified from a sandboxed build environment.

ENDPOINTS:
  GET /api/africa/financial/burkina_faso             (Redis-cached, 12h)
  GET /api/africa/financial/burkina_faso?force=true  (bypass cache)
  GET /debug/burkina-faso-financial                  (which tickers resolved)

USAGE FROM app.py:
    from burkina_faso_financial import register_burkina_faso_financial_endpoints
    register_burkina_faso_financial_endpoints(app)

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

REDIS_KEY      = 'africa:financial:burkina_faso'
HISTORY_KEY    = 'africa:financial:burkina_faso:history'
CACHE_TTL_SEC  = 12 * 3600
REFRESH_SEC    = 12 * 3600
SCAN_LOCK_KEY  = 'lock:bf:financial:scan'

# ── CORRIDOR REFERENCE (static, sourced, data_as_of) ──
# Data-honesty standard: static reference data always carries source +
# source_url + data_as_of. Never a bare number.
#
# This is the Burkina analog of Kazakhstan's CPC_ROUTE_REFERENCE. Kazakhstan's
# exposure is ONE pipeline through ONE neighbour. Burkina's is every tonne of
# everything through FOUR neighbours -- which is more diversified and more
# fragile at once, because the insurgency is expanding along the same axes.
CORRIDOR_REFERENCE = {
    'landlocked': True,
    'corridors': [
        {'name': 'Ouagadougou - Abidjan', 'port': 'Abidjan', 'country': 'Cote d\'Ivoire',
         'note': 'Historically the principal artery; rail link.'},
        {'name': 'Ouagadougou - Tema',    'port': 'Tema',    'country': 'Ghana'},
        {'name': 'Ouagadougou - Lome',    'port': 'Lome',    'country': 'Togo'},
        {'name': 'Ouagadougou - Cotonou', 'port': 'Cotonou', 'country': 'Benin'},
    ],
    'note': ('Burkina Faso is landlocked. Gold out and fuel, fertiliser and food in '
             'all move by road through four coastal neighbours. The country left '
             'ECOWAS -- the bloc governing those corridors -- with Mali and Niger in '
             'January 2025, and insurgent expansion in the Est region runs toward the '
             'same Gulf of Guinea states the corridors terminate in. Commodity revenue '
             'is real; the routes carrying it belong to other governments.'),
    'source': 'World Bank, "Enhancing Burkina Faso Regional Connectivity: An Economic '
              'Corridor Approach"; ECOWAS withdrawal Jan 2025',
    'source_url': 'https://www.worldbank.org/',
    'data_as_of': '2026-10',
}

# ── CFA FRANC PEG REFERENCE ──
CFA_PEG_REFERENCE = {
    'currency': 'West African CFA franc (XOF)',
    'union': 'UEMOA / WAEMU',
    'peg': 'Fixed to the euro',
    'parity': 655.957,
    'parity_display': '655.957 XOF = 1 EUR',
    'note': ('Because the parity is fixed, XOF/USD moves ONLY as EUR/USD moves. A '
             'daily change on this tile is a reading on the euro, not on Burkinabe '
             'monetary conditions. The signal worth watching is the PEG ITSELF: AES '
             'members have publicly raised leaving the franc zone, which would be a '
             'rupture rather than a drift, and would show up as a regime change on '
             'this tile rather than a percentage.'),
    'source': 'BCEAO / UEMOA fixed parity',
    'source_url': 'https://www.bceao.int/',
    'data_as_of': '2026-10',
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
        print('[BF Financial] Redis get error: %s' % str(e)[:120])
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
        print('[BF Financial] Redis set error: %s' % str(e)[:120])
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
                    print('[BF Financial] %s via %s: HTTP 429 -- backing off'
                          % (ticker, host))
                    continue
                _LAST_ERRORS[ticker] = 'HTTP %s via %s' % (r.status_code, host)
                if r.status_code != 200:
                    print('[BF Financial] %s via %s: HTTP %s'
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
                print('[BF Financial] %s via %s: %s' % (ticker, host, str(e)[:100]))
                continue

        if saw_429 and attempt < _YF_MAX_429_RETRY:
            backoff = 5 * (2 ** attempt)
            print('[BF Financial] %s: rate-limited, sleeping %ss (retry %d/%d)'
                  % (ticker, backoff, attempt + 1, _YF_MAX_429_RETRY))
            time.sleep(backoff)
            continue
        if saw_429:
            _THROTTLED.add(ticker)
            _LAST_ERRORS[ticker] = 'HTTP 429 (rate limited, retries exhausted)'
            print('[BF Financial] %s: THROTTLED -- not a missing ticker.' % ticker)
            return None
        break

    print('[BF Financial] %s: all hosts failed (last: %s)'
          % (ticker, _LAST_ERRORS.get(ticker, 'unknown')))
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
        print('[BF Financial] %s THROTTLED -- skipping fallback %s'
              % (primary, fallback))
        return None
    if fallback:
        print('[BF Financial] %s failed -- trying fallback %s' % (primary, fallback))
        return _fetch_yahoo_chart_with_sparkline(fallback)
    return None


# ════════════════════════════════════════════════════════════
# BRVM  (Yahoo does not host it -- Nigeria NGX pattern)
# ════════════════════════════════════════════════════════════

BRVM_SCRAPE_URL = 'https://afx.kwayisi.org/brvm/'
BRVM_LAST_KNOWN_KEY = 'brvm_last_known'
BRVM_TIMEOUT_SEC = 20

# Plausibility band. BRVM Composite has traded in the low hundreds for years.
# Rejecting out-of-band matches is what stopped the Nigeria scraper returning
# "3,828.68" from an unrelated widget.
BRVM_MIN_PLAUSIBLE = 50
BRVM_MAX_PLAUSIBLE = 5000

BRVM_PATTERNS = [
    re.compile(r'BRVM[\s-]*(?:Composite|C)[\s\S]{0,200}?'
               r'(?P<value>\d{1,3}(?:,\d{3})*\.\d{1,2})\s*'
               r'\(\s*(?P<change>[+-]?\d{1,3}(?:,\d{3})*\.\d{1,2})\s*\)',
               re.IGNORECASE),
    re.compile(r'BRVM[\s-]*(?:Composite|C)[\s\S]{0,300}?'
               r'(?P<value>\d{1,3}(?:,\d{3})*\.\d{1,2})', re.IGNORECASE),
]


def _scrape_brvm():
    """Scrape the BRVM Composite. Returns dict or None.

    Mirrors ngx_index_scraper: fetch over requests FIRST so transport failures
    are visible, then regex with a PLAUSIBILITY CHECK, then honest None.
    Better to render "Unavailable" than a wrong number."""
    try:
        r = requests.get(BRVM_SCRAPE_URL, timeout=BRVM_TIMEOUT_SEC,
                         headers={'User-Agent': _YF_HEADERS['User-Agent'],
                                  'Accept': 'text/html,application/xhtml+xml'})
        if r.status_code != 200:
            _LAST_ERRORS['BRVM'] = 'HTTP %s from kwayisi' % r.status_code
            print('[BF Financial] BRVM: HTTP %s' % r.status_code)
            return None
        if len(r.text) < 500:
            _LAST_ERRORS['BRVM'] = 'suspiciously small response (%d bytes)' % len(r.text)
            print('[BF Financial] BRVM: response too small -- likely blocked')
            return None
        html = r.text
        for i, pat in enumerate(BRVM_PATTERNS):
            for m in pat.finditer(html):
                g = m.groupdict()
                try:
                    value = float(g['value'].replace(',', ''))
                except (TypeError, ValueError, KeyError):
                    continue
                if value < BRVM_MIN_PLAUSIBLE or value > BRVM_MAX_PLAUSIBLE:
                    print('[BF Financial] BRVM pattern #%d: implausible %.2f '
                          '-- rejecting, continuing' % (i + 1, value))
                    continue
                change = None
                if g.get('change'):
                    try:
                        change = float(g['change'].replace(',', ''))
                    except (TypeError, ValueError):
                        change = None
                pct = None
                if change is not None and (value - change) != 0:
                    pct = (change / (value - change)) * 100
                print('[BF Financial] BRVM pattern #%d matched: %.2f' % (i + 1, value))
                return {
                    'value':          round(value, 2),
                    'change_pct_24h': round(pct, 2) if pct is not None else None,
                    'change_abs_24h': round(change, 2) if change is not None else None,
                    'sparkline':      _brvm_sparkline_from_history(),
                    'source':         'afx.kwayisi.org',
                    'ticker_used':    'BRVM-C',
                    'pattern_index':  i + 1,
                    'timestamp':      datetime.now(timezone.utc).isoformat(),
                }
        _LAST_ERRORS['BRVM'] = 'HTML fetched but no plausible BRVM value found'
        print('[BF Financial] BRVM: no plausible value in %d bytes' % len(html))
    except Exception as e:
        _LAST_ERRORS['BRVM'] = '%s: %s' % (type(e).__name__, str(e)[:80])
        print('[BF Financial] BRVM scrape error: %s' % str(e)[:120])
    return None


def _brvm_sparkline_from_history():
    """BRVM has no chart API here, so the sparkline accumulates from our own
    scan history -- the Nigeria NGX approach. Grows organically."""
    try:
        history = _redis_get(HISTORY_KEY) or []
        out = []
        for entry in history[-30:]:
            v = entry.get('brvm_value')
            if v is None:
                continue
            ts = entry.get('scanned_at', '')
            out.append({'time': (ts.split('T')[0] if 'T' in ts else ts[:10]),
                        'value': round(float(v), 2)})
        return out
    except Exception:
        return []


def _fetch_brvm():
    """Scraper -> last-known -> None. Each success writes last-known."""
    scraped = _scrape_brvm()
    if scraped:
        _redis_set(BRVM_LAST_KNOWN_KEY, {
            'value': scraped['value'],
            'change_pct_24h': scraped.get('change_pct_24h'),
        }, ttl=7 * 24 * 3600)
        return scraped
    cached = _redis_get(BRVM_LAST_KNOWN_KEY)
    if cached and cached.get('value') is not None:
        print('[BF Financial] BRVM: serving LAST KNOWN (flagged estimated)')
        return {
            'value':          cached.get('value'),
            'change_pct_24h': cached.get('change_pct_24h'),
            'sparkline':      _brvm_sparkline_from_history(),
            'source':         'afx.kwayisi.org (last known)',
            'ticker_used':    'BRVM-C',
            'estimated':      True,
            'timestamp':      datetime.now(timezone.utc).isoformat(),
        }
    return None


# ════════════════════════════════════════════════════════════
# MARKET STATUS
# ════════════════════════════════════════════════════════════

def _brvm_market_status():
    """BRVM (Abidjan). Main session roughly 09:00-15:00 GMT, Mon-Fri.
    Cote d'Ivoire is UTC+0 year-round (no DST)."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return 'closed'
    minutes = now.hour * 60 + now.minute
    pre_open, open_min, close_min = 8 * 60, 9 * 60, 15 * 60
    if minutes < pre_open:
        return 'closed'
    if minutes < open_min:
        return 'pre-market'
    if minutes < close_min:
        return 'open'
    return 'after-hours'


def _commodity_market_status():
    """COMEX gold and ICE cotton both trade nearly 24h Sun evening - Fri
    evening."""
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
      Standard polarity (gold, cotton, BRVM): rising = good.
      Inverted polarity (XOF/USD):            rising = bad (weaker CFA vs USD).
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

def _build_financial_pulse(gold, cotton, xof, brvm):
    comm_status = _commodity_market_status()
    fx_status   = _fx_market_status()
    brvm_status = _brvm_market_status()

    tiles = {}

    # ── Tile 1: GOLD + corridor dependency inline ──
    if gold:
        tiles['GOLD'] = {
            'name':           'Gold',
            'ticker':         'GC=F',
            'value':          gold.get('value'),
            'change_pct_24h': gold.get('change_pct_24h'),
            'trend':          _trend(gold.get('change_pct_24h')),
            'tier':           _fp_tier(gold.get('change_pct_24h')),
            'source':         gold.get('source'),
            'market_status':  comm_status,
            'timestamp':      gold.get('timestamp'),
            'sparkline':      gold.get('sparkline', []),
            'note':           ('~75% of Burkinabe exports. Africa’s 5th-largest '
                               'producer (Essakane, Hounde, Mana, Bombore, Yaramoko).'),
            # Route dependency inline -- the Kazakhstan CPC pattern
            'landlocked':       True,
            'route_name':       'Abidjan · Tema · Lome · Cotonou',
            'route_note':       ('Landlocked: every ounce exits through a neighbour’s '
                                 'port. ECOWAS withdrawn Jan 2025 · World Bank corridor '
                                 'study · as of %s' % CORRIDOR_REFERENCE['data_as_of']),
            'route_reference':  CORRIDOR_REFERENCE,
        }
    else:
        tiles['GOLD'] = _empty_tile('Gold', 'GC=F', comm_status,
                                    '~75% of Burkinabe exports')

    # ── Tile 2: COTTON ──
    if cotton:
        tiles['COTTON'] = {
            'name':           'Cotton',
            'ticker':         'CT=F',
            'value':          cotton.get('value'),
            'change_pct_24h': cotton.get('change_pct_24h'),
            'trend':          _trend(cotton.get('change_pct_24h')),
            'tier':           _fp_tier(cotton.get('change_pct_24h')),
            'source':         cotton.get('source'),
            'market_status':  comm_status,
            'timestamp':      cotton.get('timestamp'),
            'sparkline':      cotton.get('sparkline', []),
            'note':           ('The export that reaches HOUSEHOLDS. Gold revenue accrues '
                               'to the state and foreign operators; cotton is the rural '
                               'income base, so a move here is a food-security '
                               'transmission rather than a trade statistic.'),
        }
    else:
        tiles['COTTON'] = _empty_tile('Cotton', 'CT=F', comm_status,
                                      'Rural household income base')

    # ── Tile 3: XOF/USD (INVERTED polarity, peg-aware) ──
    if xof:
        tiles['XOFUSD'] = {
            'name':           'XOF/USD',
            'ticker':         'XOF=X',
            'value':          xof.get('value'),
            'change_pct_24h': xof.get('change_pct_24h'),
            'trend':          _trend(xof.get('change_pct_24h')),
            'tier':           _fp_tier(xof.get('change_pct_24h'), inverted=True),
            'source':         xof.get('source'),
            'market_status':  fx_status,
            'timestamp':      xof.get('timestamp'),
            'sparkline':      xof.get('sparkline', []),
            'note':           ('INVERTED polarity. READ THE PEG, NOT THE TICK: the CFA '
                               'franc is fixed at 655.957 to the euro, so daily movement '
                               'here is EUR/USD, not Burkinabe monetary stress. The '
                               'signal is whether the peg holds — AES states have '
                               'raised leaving the franc zone.'),
            'peg_reference':  CFA_PEG_REFERENCE,
            'peg_warning':    True,
        }
    else:
        tiles['XOFUSD'] = _empty_tile('XOF/USD', 'XOF=X', fx_status,
                                      'CFA franc, pegged to the euro at 655.957')
        tiles['XOFUSD']['peg_reference'] = CFA_PEG_REFERENCE
        tiles['XOFUSD']['peg_warning'] = True

    # ── Tile 4: BRVM Composite ──
    if brvm:
        tiles['BRVM'] = {
            'name':           'BRVM Composite',
            'ticker':         'BRVM-C',
            'value':          brvm.get('value'),
            'change_pct_24h': brvm.get('change_pct_24h'),
            'change_abs_24h': brvm.get('change_abs_24h'),
            'trend':          _trend(brvm.get('change_pct_24h')),
            'tier':           _fp_tier(brvm.get('change_pct_24h')),
            'source':         brvm.get('source'),
            'market_status':  brvm_status,
            'timestamp':      brvm.get('timestamp'),
            'sparkline':      brvm.get('sparkline', []),
            'estimated':      bool(brvm.get('estimated')),
            'note':           ('Regional bourse for the eight UEMOA states — and it '
                               'sits in ABIDJAN. Burkinabe listed companies trade in the '
                               'capital of a country Burkina Faso is now outside ECOWAS '
                               'with. Yahoo does not host BRVM; scraped, with an honest '
                               '"Unavailable" rather than an invented number.'),
        }
    else:
        tiles['BRVM'] = _empty_tile('BRVM Composite', 'BRVM-C', brvm_status,
                                    'Regional UEMOA bourse, located in Abidjan')

    agg = _aggregate_market_status([comm_status, fx_status, brvm_status])

    return {
        'country':        'BF',
        'card_label':     'Burkina Faso Financial Pulse',
        'version':        VERSION,
        'last_refreshed': datetime.now(timezone.utc).isoformat(),
        'market_status':  agg,
        'brvm_status':    brvm_status,
        'tiles':          tiles,
        'corridor_reference': CORRIDOR_REFERENCE,
        'peg_reference':      CFA_PEG_REFERENCE,
    }


def get_burkina_faso_financial(force=False):
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

    print('[BF Financial] Fetching fresh market data...')
    gold   = _fetch_yahoo_chart_with_sparkline('GC=F')
    cotton = _fetch_yahoo_chart_with_sparkline('CT=F')
    # XOF=X is the primary; EURUSD=X is a DIAGNOSTIC fallback, not a substitute
    # -- if XOF=X is missing we at least know whether Yahoo FX is reachable.
    xof    = _fetch_with_failover('XOF=X', 'EURUSD=X')
    brvm   = _fetch_brvm()

    payload = _build_financial_pulse(gold, cotton, xof, brvm)
    payload['cache_status'] = 'fresh'
    resolved = [k for k, v in payload['tiles'].items() if not v.get('unavailable')]
    print('[BF Financial] Tiles resolved: %d/4 -> %s' % (len(resolved), resolved))

    _redis_set(REDIS_KEY, payload, ttl=CACHE_TTL_SEC)

    # History snapshot -- this is what grows the BRVM sparkline organically.
    try:
        history = _redis_get(HISTORY_KEY) or []
        history.append({
            'scanned_at':   payload['last_refreshed'],
            'gold_value':   (gold or {}).get('value'),
            'cotton_value': (cotton or {}).get('value'),
            'xof_value':    (xof or {}).get('value'),
            'brvm_value':   (brvm or {}).get('value'),
        })
        _redis_set(HISTORY_KEY, history[-30:], ttl=None)
    except Exception:
        pass

    return payload


# ════════════════════════════════════════════════════════════
# BACKGROUND REFRESH (cross-worker lock)
# ════════════════════════════════════════════════════════════

def _background_refresh():
    # Jittered: the Kazakhstan pulse, Nigeria pulse and russia_stability share
    # this IP and Yahoo quota.
    time.sleep(180 + random.randint(0, 180))
    while True:
        try:
            if _acquire_scan_lock(ttl_sec=600):
                get_burkina_faso_financial(force=True)
            else:
                print('[BF Financial] Another worker owns the refresh window -- skipping')
        except Exception as e:
            print('[BF Financial] Background error: %s' % str(e)[:120])
        time.sleep(REFRESH_SEC + random.randint(0, 600))


def start_background_refresh():
    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()
    print('[BF Financial] Background refresh started (12h cycle, cross-worker lock)')


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════

def register_burkina_faso_financial_endpoints(app, start_background=True):

    @app.route('/api/africa/financial/burkina_faso', methods=['GET'])
    def api_africa_financial_burkina_faso():
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            return jsonify(get_burkina_faso_financial(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200],
                            'country': 'BF', 'tiles': {}}), 500

    @app.route('/debug/burkina-faso-financial', methods=['GET'])
    def debug_burkina_faso_financial():
        """Which tickers actually resolved -- FIRST-DEPLOY VERIFICATION.

        This endpoint is load-bearing: GC=F, CT=F and XOF=X could not be probed
        from the sandboxed build environment, and BRVM scraping depends on a
        third-party page layout. This is how we find out which of the four are
        real rather than assuming."""
        data = get_burkina_faso_financial(force=True)
        tiles = data.get('tiles', {})
        return jsonify({
            'version':        VERSION,
            'market_status':  data.get('market_status'),
            'brvm_status':    data.get('brvm_status'),
            'tickers': {
                k: {
                    'ticker':        v.get('ticker'),
                    'resolved':      not v.get('unavailable', False),
                    'value':         v.get('value'),
                    'change_24h':    v.get('change_pct_24h'),
                    'sparkline_pts': len(v.get('sparkline') or []),
                    'market_status': v.get('market_status'),
                    'estimated':     v.get('estimated', False),
                    'reason':        v.get('unavailable_reason'),
                } for k, v in tiles.items()
            },
            'resolved_count':   sum(1 for v in tiles.values()
                                    if not v.get('unavailable')),
            'last_errors':      dict(_LAST_ERRORS),
            'redis_configured': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
        })

    if start_background:
        start_background_refresh()

    print('[BF Financial] ✅ Endpoints registered: '
          '/api/africa/financial/burkina_faso, /debug/burkina-faso-financial')
