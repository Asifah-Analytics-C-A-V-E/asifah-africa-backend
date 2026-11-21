# -*- coding: utf-8 -*-
"""
Asifah Analytics - Niger Financial Pulse
v1.0.0 - November 2026  |  Africa backend

Canonical Financial Pulse card, Niger edition. Cloned from
burkina_faso_financial.py (same throttle discipline, cross-worker lock,
absence-honest empty tiles, BRVM scraper). What changes is WHICH four numbers
answer Niger's questions.

FOUR TILES -- each answers a DIFFERENT question:

  1. URANIUM (URA, via the ME commodity proxy)
                       Niger's strategic export and its geopolitical bargaining
                       chip: world #7 producer, historically 15-25% of EU supply,
                       SOMAIR nationalised (2025) and its stockpile put up for
                       sale; Russia in purchase talks; the US financing Dasa
                       (DFC, Sep 2026). There is NO free spot uranium price (UxC
                       is paywalled), so this is the Global X Uranium ETF -- a
                       PROXY, and the tile says so. Route dependency shown
                       inline: Arlit yellowcake historically left by road to
                       Cotonou (Benin), a border Niger has kept shut; Dasa's
                       operator is studying a northern route through Algeria.

  2. BRENT (BZ=F, via proxy)
                       The pipeline economy. Agadem crude (CNPC) leaves through
                       the ~2,000 km Niger-Benin pipeline to Seme. Oil is the
                       budget line the junta has fought CNPC over. Brent tells
                       you what a barrel is worth; whether barrels FLOW depends
                       on Benin and on pipeline sabotage -- the route note says
                       so.

  3. XOF/USD (XOF=X)   Same peg warning as Burkina: the CFA franc is fixed to the
                       euro, so a daily tick is EUR/USD. The signal is the peg
                       itself -- AES states have raised leaving the franc zone.

  4. BRVM COMPOSITE    The regional bourse, in Abidjan. Niger raises money on the
                       regional UMOA-Titres market and fell into arrears there
                       under 2023 ECOWAS sanctions; the bourse is the regional
                       capital market Niger still depends on.

DOCTRINE: SENSOR. Prices, deltas, market status, sources and timestamps. The
analyst layer interprets. No tile is ever filled with an invented number.

ENDPOINTS:
  GET /api/africa/financial/niger             (Redis-cached, 12h)
  GET /api/africa/financial/niger?force=true  (bypass cache; no Claude calls)
  GET /debug/niger-financial                  (which tickers resolved)

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

REDIS_KEY      = 'africa:financial:niger'
HISTORY_KEY    = 'africa:financial:niger:history'
CACHE_TTL_SEC  = 12 * 3600
REFRESH_SEC    = 12 * 3600
SCAN_LOCK_KEY  = 'lock:ne:financial:scan'

# ── CORRIDOR REFERENCE (static, sourced, data_as_of) ──
# Niger is landlocked and its two strategic exports leave by two different
# routes, both through neighbours it has quarrelled with.
CORRIDOR_REFERENCE = {
    'landlocked': True,
    'corridors': [
        {'name': 'Agadem - Seme (Niger-Benin pipeline)', 'port': 'Seme / Cotonou', 'country': 'Benin',
         'note': 'Crude export line (CNPC/WAPCO), ~2,000 km. Flows have been halted by the Benin border feud and by rebel sabotage.'},
        {'name': 'Arlit - Cotonou (road)', 'port': 'Cotonou', 'country': 'Benin',
         'note': 'Historic uranium export road. The Benin land border has stayed shut since the 2023 coup.'},
        {'name': 'Niamey - Lome (road)', 'port': 'Lome', 'country': 'Togo',
         'note': 'The AES route to the sea while Benin is shut.'},
        {'name': 'Maradi/Zinder - Kano - Lagos', 'port': 'Lagos', 'country': 'Nigeria',
         'note': 'Trade and fuel artery to the south.'},
        {'name': 'Agadez - Tamanrasset (Trans-Sahara road)', 'port': 'Algiers', 'country': 'Algeria',
         'note': 'Northern route; studied for Dasa uranium exports; the planned Trans-Saharan Gas Pipeline would run alongside.'},
    ],
    'note': ('Niger is landlocked. Its crude leaves by one pipeline through Benin; '
             'its uranium historically left by road through Benin too, and that '
             'border has stayed shut since the 2023 coup. Togo and Nigeria carry '
             'the trade; Algeria is the route being opened in the north. Commodity '
             'value is real; whether it reaches a port depends on neighbours.'),
    'source': 'WAPCO / CNPC; IOM & GI-TOC corridor reporting; Global Atomic (Dasa) route study',
    'source_url': 'https://www.worldbank.org/en/country/niger',
    'data_as_of': '2026-11',
}

# ── CFA FRANC PEG REFERENCE ──
CFA_PEG_REFERENCE = {
    'currency': 'West African CFA franc (XOF)',
    'union': 'UEMOA / WAEMU',
    'peg': 'Fixed to the euro',
    'parity': 655.957,
    'parity_display': '655.957 XOF = 1 EUR',
    'note': ('Because the parity is fixed, XOF/USD moves ONLY as EUR/USD moves. A '
             'daily change on this tile is a reading on the euro, not on Nigerien '
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
        print('[NE Financial] Redis get error: %s' % str(e)[:120])
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
        print('[NE Financial] Redis set error: %s' % str(e)[:120])
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
                    print('[NE Financial] %s via %s: HTTP 429 -- backing off'
                          % (ticker, host))
                    continue
                _LAST_ERRORS[ticker] = 'HTTP %s via %s' % (r.status_code, host)
                if r.status_code != 200:
                    print('[NE Financial] %s via %s: HTTP %s'
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
                print('[NE Financial] %s via %s: %s' % (ticker, host, str(e)[:100]))
                continue

        if saw_429 and attempt < _YF_MAX_429_RETRY:
            backoff = 5 * (2 ** attempt)
            print('[NE Financial] %s: rate-limited, sleeping %ss (retry %d/%d)'
                  % (ticker, backoff, attempt + 1, _YF_MAX_429_RETRY))
            time.sleep(backoff)
            continue
        if saw_429:
            _THROTTLED.add(ticker)
            _LAST_ERRORS[ticker] = 'HTTP 429 (rate limited, retries exhausted)'
            print('[NE Financial] %s: THROTTLED -- not a missing ticker.' % ticker)
            return None
        break

    print('[NE Financial] %s: all hosts failed (last: %s)'
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
        data = get_africa_commodity_data('niger') or {}
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
        print('[NE Financial] %s THROTTLED -- skipping fallback %s'
              % (primary, fallback))
        return None
    if fallback:
        print('[NE Financial] %s failed -- trying fallback %s' % (primary, fallback))
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
            print('[NE Financial] BRVM: HTTP %s' % r.status_code)
            return None
        if len(r.text) < 500:
            _LAST_ERRORS['BRVM'] = 'suspiciously small response (%d bytes)' % len(r.text)
            print('[NE Financial] BRVM: response too small -- likely blocked')
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
                    print('[NE Financial] BRVM pattern #%d: implausible %.2f '
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
                print('[NE Financial] BRVM pattern #%d matched: %.2f' % (i + 1, value))
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
        print('[NE Financial] BRVM: no plausible value in %d bytes' % len(html))
    except Exception as e:
        _LAST_ERRORS['BRVM'] = '%s: %s' % (type(e).__name__, str(e)[:80])
        print('[NE Financial] BRVM scrape error: %s' % str(e)[:120])
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
        print('[NE Financial] BRVM: serving LAST KNOWN (flagged estimated)')
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
    """Uranium-fund (US equity hours) and Brent trade on weekdays; Brent nearly 24h Sun evening - Fri
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
      Standard polarity (uranium, Brent, BRVM): rising = more export revenue.
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

def _build_financial_pulse(uranium, brent, xof, brvm):
    comm_status = _commodity_market_status()
    fx_status   = _fx_market_status()
    brvm_status = _brvm_market_status()

    tiles = {}

    # ── Tile 1: URANIUM (proxy) + route dependency inline ──
    if uranium:
        tiles['URANIUM'] = {
            'name':           'Uranium (URA fund)',
            'ticker':         uranium.get('ticker_used') or 'URA',
            'value':          uranium.get('value'),
            'change_pct_24h': uranium.get('change_pct_24h'),
            'change_pct_30d': uranium.get('change_pct_30d'),
            'trend':          _trend(uranium.get('change_pct_24h')),
            'tier':           _fp_tier(uranium.get('change_pct_24h')),
            'source':         uranium.get('source'),
            'market_status':  comm_status,
            'timestamp':      uranium.get('timestamp'),
            'sparkline':      uranium.get('sparkline', []),
            'proxy':          True,
            'note':           ('PROXY: the Global X Uranium fund, not the uranium price '
                               '(spot is paywalled). Niger is the world\'s #7 producer; '
                               'SOMAIR is nationalised and its stockpile is for sale, '
                               'Russia is in purchase talks and the US is financing Dasa.'),
            'landlocked':       True,
            'route_name':       'Arlit - Cotonou (shut) · Agadez - Algeria (studied)',
            'route_note':       ('Landlocked: yellowcake historically left by road through '
                                 'Benin, a border shut since 2023; a northern Algerian '
                                 'route is being studied. As of %s' % CORRIDOR_REFERENCE['data_as_of']),
            'route_reference':  CORRIDOR_REFERENCE,
        }
    else:
        tiles['URANIUM'] = _empty_tile('Uranium (URA fund)', 'URA', comm_status,
                                       'Proxy fund; Niger is the world #7 uranium producer')

    # ── Tile 2: BRENT + pipeline dependency ──
    if brent:
        tiles['BRENT'] = {
            'name':           'Brent crude',
            'ticker':         brent.get('ticker_used') or 'BZ=F',
            'value':          brent.get('value'),
            'change_pct_24h': brent.get('change_pct_24h'),
            'change_pct_30d': brent.get('change_pct_30d'),
            'trend':          _trend(brent.get('change_pct_24h')),
            'tier':           _fp_tier(brent.get('change_pct_24h')),
            'source':         brent.get('source'),
            'market_status':  comm_status,
            'timestamp':      brent.get('timestamp'),
            'sparkline':      brent.get('sparkline', []),
            'note':           ('What a barrel of Agadem crude is worth. Whether barrels '
                               'FLOW is a different question: they leave by one pipeline '
                               'through Benin, which border feuds and sabotage have halted.'),
            'landlocked':       True,
            'route_name':       'Agadem - Seme pipeline (Benin)',
            'route_note':       'One pipeline, one neighbour. CNPC/WAPCO. As of %s' % CORRIDOR_REFERENCE['data_as_of'],
            'route_reference':  CORRIDOR_REFERENCE,
        }
    else:
        tiles['BRENT'] = _empty_tile('Brent crude', 'BZ=F', comm_status,
                                     'Agadem crude exports via the Benin pipeline')

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
                               'here is EUR/USD, not Nigerien monetary stress. The '
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
                               'sits in ABIDJAN. Niger borrows on the regional UMOA-Titres '
                               'market and fell into arrears there under the 2023 ECOWAS '
                               'sanctions. Yahoo does not host BRVM; scraped, with an honest '
                               '"Unavailable" rather than an invented number.'),
        }
    else:
        tiles['BRVM'] = _empty_tile('BRVM Composite', 'BRVM-C', brvm_status,
                                    'Regional UEMOA bourse, located in Abidjan')

    agg = _aggregate_market_status([comm_status, fx_status, brvm_status])

    return {
        'country':        'NE',
        'card_label':     'Niger Financial Pulse',
        'version':        VERSION,
        'last_refreshed': datetime.now(timezone.utc).isoformat(),
        'market_status':  agg,
        'brvm_status':    brvm_status,
        'tiles':          tiles,
        'corridor_reference': CORRIDOR_REFERENCE,
        'peg_reference':      CFA_PEG_REFERENCE,
    }


def get_niger_financial(force=False):
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

    print('[NE Financial] Fetching fresh market data...')
    # Commodity tiles: proxy FIRST (ME backend IP is not throttled), Yahoo fallback.
    uranium = _fetch_via_commodity_proxy('uranium', 'URA')
    if uranium is None:
        uranium = _fetch_with_failover('URA', 'SRUUF')
    brent = _fetch_via_commodity_proxy('oil', 'BZ=F')
    if brent is None:
        brent = _fetch_yahoo_chart_with_sparkline('BZ=F')
    xof    = _fetch_with_failover('XOF=X', 'EURUSD=X')
    brvm   = _fetch_brvm()

    payload = _build_financial_pulse(uranium, brent, xof, brvm)
    payload['cache_status'] = 'fresh'
    resolved = [k for k, v in payload['tiles'].items() if not v.get('unavailable')]
    print('[NE Financial] Tiles resolved: %d/4 -> %s' % (len(resolved), resolved))

    _redis_set(REDIS_KEY, payload, ttl=CACHE_TTL_SEC)

    # History snapshot -- this is what grows the BRVM sparkline organically.
    try:
        history = _redis_get(HISTORY_KEY) or []
        history.append({
            'scanned_at':   payload['last_refreshed'],
            'uranium_value': (uranium or {}).get('value'),
            'brent_value':   (brent or {}).get('value'),
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
                get_niger_financial(force=True)
            else:
                print('[NE Financial] Another worker owns the refresh window -- skipping')
        except Exception as e:
            print('[NE Financial] Background error: %s' % str(e)[:120])
        time.sleep(REFRESH_SEC + random.randint(0, 600))


def start_background_refresh():
    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()
    print('[NE Financial] Background refresh started (12h cycle, cross-worker lock)')


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════

def register_niger_financial_endpoints(app, start_background=True):

    @app.route('/api/africa/financial/niger', methods=['GET'])
    def api_africa_financial_niger():
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            return jsonify(get_niger_financial(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200],
                            'country': 'NE', 'tiles': {}}), 500

    @app.route('/debug/niger-financial', methods=['GET'])
    def debug_niger_financial():
        """Which tickers actually resolved -- FIRST-DEPLOY VERIFICATION.

        This endpoint is load-bearing: URA, BZ=F and XOF=X could not be probed
        from the sandboxed build environment, and BRVM scraping depends on a
        third-party page layout. This is how we find out which of the four are
        real rather than assuming."""
        data = get_niger_financial(force=True)
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

    print('[NE Financial] ✅ Endpoints registered: '
          '/api/africa/financial/niger, /debug/niger-financial')
