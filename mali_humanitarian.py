"""
Asifah Analytics - Mali Humanitarian Pulse (Sensor)
v1.0.0 - July 2026  |  Africa backend

SENSOR module (doctrine: stability pages are dials, not analysts). Emits RAW
displacement, blockade, and food-security figures for Mali with honest sourcing
and data_as_of dates. The analyst meaning lives in the rhetoric / BLUF layer.

WHY THIS CARD IS SHAPED DIFFERENTLY FROM SUDAN'S
Sudan's humanitarian signature is BIDIRECTIONAL -- mass return alongside new
displacement, two dials read together. Mali's is a SIEGE. Since the JNIM fuel
blockade began in September 2025, the mechanism has been:

    blockade -> fuel scarcity -> market/price collapse -> displacement south

That is an economic strangulation of a capital, not a frontline displacement
wave, and the card measures it as such. The blockade read is the headline dial;
IDP stock is context. Getting this backwards would show Mali as a mid-sized
displacement crisis and miss that its capital is being squeezed.

THE 2026 DETERIORATION (why the figures move):
  Sep 2025  JNIM fuel blockade on Bamako -- unprecedented scarcity, crisis
            spreads SOUTH into the country's food basket
  Apr 2026  Coordinated FLA+JNIM attacks on Bamako, Kati, Gao, Kidal, Mopti,
            Sevare; Kidal falls; the defence minister is killed
  Jul 2026  Five-location simultaneous attacks; Anefis contested

CLONE NOTE (Burkina Faso / Niger, tier-two Russia spokes): this module is
deliberately parameterised at the top -- COUNTRY_ISO3, COUNTRY_SLUG, DTM
country name, ReliefWeb slug and the STATIC_BASELINE dict. A Burkina or Niger
build is a transform of those constants plus new baseline figures, not a
rewrite. The blockade framing generalises: all three AES states face
supply-route interdiction as the primary humanitarian mechanism.

DATA SOURCES:
  * Live   - IOM DTM API v3 (Mali DTM/DNDS operation). DTM_API_KEY env var.
  * Live   - ReliefWeb API (OCHA/UN/NGO reports).
  * Static - attributed baseline so the card ALWAYS renders. Every figure
             carries source + as_of.

REDIS:
  Cache: africa:humanitarian:mali  (12h TTL)
  NOTE: rhetoric_tracker_mali reads this key for its humanitarian convergence
  layer -- emit once, consume many.

ENDPOINTS:
  GET /api/africa/humanitarian/mali            (cache-first)
  GET /api/africa/humanitarian/mali?force=true (bypass cache)
  GET /debug/mali-humanitarian

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import threading
from datetime import datetime, timezone

import requests

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL') or '')
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN') or '')

DTM_API_KEY  = os.environ.get('DTM_API_KEY')
DTM_BASE_URL = 'https://dtmapi.iom.int/v3'

RELIEFWEB_API_URL = 'https://api.reliefweb.int/v1'

CACHE_KEY = 'africa:humanitarian:mali'
CACHE_TTL = 12 * 3600   # 12 hours

_hum_lock = threading.Lock()

# ------------------------------------------------------------------
# STATIC BASELINE (always-present fallback; update as dashboards publish)
# Every figure attributed. Sensor voice: dials, not diagnosis.
# ------------------------------------------------------------------
STATIC_BASELINE = {
    'data_as_of': '2026-07-25',
    'headline_stats': [
        {'label': 'People in need of assistance',
         'value': 5100000, 'display': '5.1M',
         'source': 'IRC / OCHA Mali 2026 HNRP', 'as_of': '2026'},
        {'label': 'Internally displaced (IDPs)',
         'value': 415000, 'display': '415K+',
         'source': 'IOM DTM / DNDS Mali', 'as_of': '2026-H1'},
        {'label': 'Bamako fuel blockade',
         'value': 0, 'display': 'ACTIVE',
         'source': 'JNIM interdiction of fuel convoys, ongoing',
         'as_of': 'since 2025-09'},
        {'label': 'Koro refugee projection',
         'value': 110000, 'display': '~110K',
         'source': 'ACAPS -- would outnumber the host population',
         'as_of': '2026 projection'},
    ],
    # THE headline mechanism for Mali. Read this before the IDP stock.
    'blockade_note': ('JNIM has interdicted fuel convoys to Bamako since September '
                      '2025, producing unprecedented fuel scarcity across the south '
                      'and centre. The sequence is blockade -> fuel scarcity -> '
                      'market and price collapse -> displacement. This is economic '
                      'strangulation of a capital rather than a frontline '
                      'displacement wave. (NRC / ACAPS / IRC)'),
    'famine_note': ('Food insecurity is spreading SOUTH into what NRC calls the '
                    'country\'s food basket -- a reversal of the decade-long '
                    'north-and-centre pattern. Families report cutting meals; '
                    'markets abandoned in blockade-affected areas. (NRC / IPC Mali)'),
    'disease_note': ('IDP concentrations in informal Bamako sites (livestock '
                     'markets, waste grounds) carry elevated waterborne-disease '
                     'risk; 12% of displacement sites rely on unsafe water. '
                     'Health access for displaced households is poor. '
                     '(Lancet Regional Health - Africa / IOM DTM)'),
    'drivers_note': ('Displacement drivers: the April 25 2026 coordinated FLA+JNIM '
                     'attacks on Bamako, Kati, Gao, Kidal, Mopti and Sevare; the '
                     'fall of Kidal and the killing of the defence minister; and '
                     'sustained supply-route interdiction. Roughly 4,000 IDPs were '
                     'relocated by government order from the Senou, Niamana and '
                     'Faladie sites -- over 75% of the displaced are women and '
                     'children. Liptako-Gourma (Mali-Niger-Burkina tri-border) '
                     'remains the structural driver.'),
    'funding_note': ('Severely underfunded amid 2025-26 aid cuts; in 2024 only 2.1M '
                     'of 4.1M targeted people were reached. Mali sits on the IRC '
                     '2026 Emergency Watchlist and is repeatedly described as one '
                     'of the world\'s most underreported humanitarian crises.'),
    'sources': [
        {'name': 'IOM DTM Mali', 'url': 'https://dtm.iom.int/mali'},
        {'name': 'OCHA Mali', 'url': 'https://www.unocha.org/mali'},
        {'name': 'ACAPS Mali', 'url': 'https://www.acaps.org/en/countries/mali'},
        {'name': 'ReliefWeb Mali', 'url': 'https://reliefweb.int/country/mli'},
        {'name': 'NRC', 'url': 'https://www.nrc.no/countries/africa/mali/'},
        {'name': 'IRC Emergency Watchlist',
         'url': 'https://www.rescue.org/emergency-watchlist'},
    ],
}


# ------------------------------------------------------------------
# Redis helpers (Upstash REST, dual env-var fallback)
# ------------------------------------------------------------------
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        r = requests.get(
            '%s/get/%s' % (UPSTASH_REDIS_URL, key),
            headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
            timeout=8,
        )
        if r.status_code == 200:
            val = r.json().get('result')
            if val:
                return json.loads(val)
    except Exception as e:
        print('[Mali Humanitarian] redis get error: %s' % str(e)[:120])
    return None


def _redis_set(key, value, ttl=CACHE_TTL):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return
    try:
        requests.post(
            UPSTASH_REDIS_URL,
            headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
            json=['SET', key, json.dumps(value), 'EX', str(ttl)],
            timeout=8,
        )
    except Exception as e:
        print('[Mali Humanitarian] redis set error: %s' % str(e)[:120])


# ------------------------------------------------------------------
# LIVE SOURCE 1 - IOM DTM API v3 (clones proven ukraine_humanitarian pattern)
# ------------------------------------------------------------------
def fetch_dtm_mali():
    """
    Country-level (Admin 0) IDP figures for Mali from IOM DTM API v3.
    Returns dict or None. Conservative: only overrides static when a
    parseable figure lands.
    """
    if not DTM_API_KEY:
        print('[Mali DTM] No DTM_API_KEY configured')
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
    }
    try:
        print('[Mali DTM] Fetching country-level IDP data...')
        params = {
            'CountryName': 'Mali',
            'FromReportingDate': '2024-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d'),
        }
        response = requests.get(
            '%s/displacement/admin0' % DTM_BASE_URL,
            headers=headers, params=params, timeout=15,
        )
        if response.status_code != 200:
            print('[Mali DTM] HTTP %s' % response.status_code)
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            print('[Mali DTM] No data returned')
            return None
        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
        most_recent = latest[0]
        idps = most_recent.get('numPresentIdpInd', 0)
        if not idps:
            return None
        print('[Mali DTM] Country-level: {:,} IDPs (Round {})'.format(
            idps, most_recent.get('roundNumber', '?')))
        return {
            'total_idps':      idps,
            'reporting_date':  most_recent.get('reportingDate', ''),
            'round_number':    most_recent.get('roundNumber', ''),
            'source':          'IOM DTM API v3',
            'fetched_at':      datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print('[Mali DTM] error: %s' % str(e)[:150])
        return None


# ------------------------------------------------------------------
# LIVE SOURCE 2 - ReliefWeb reports (clones proven pattern)
# ------------------------------------------------------------------
def fetch_reliefweb_mali(limit=8):
    """Latest OCHA/UN/NGO reports for Mali from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/mli',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
    }
    try:
        print('[Mali ReliefWeb] Fetching reports...')
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Mali displacement blockade Bamako fuel humanitarian',
            'query[operator]': 'AND',
            'sort[]': 'date:desc',
            'limit': limit,
            'fields[include][]': ['title', 'date.created', 'url_alias', 'source.name'],
        }
        response = requests.get(
            '%s/reports' % RELIEFWEB_API_URL, params=params, timeout=15,
        )
        if response.status_code != 200:
            result['error'] = 'HTTP %s' % response.status_code
            return result
        data = response.json()
        for report in (data.get('data') or [])[:limit]:
            fields = report.get('fields', {})
            src = 'OCHA'
            if fields.get('source'):
                src = fields.get('source', [{}])[0].get('name', 'OCHA')
            result['reports'].append({
                'title':  fields.get('title', ''),
                'date':   (fields.get('date', {}) or {}).get('created', ''),
                'url':    'https://reliefweb.int%s' % fields.get('url_alias', ''),
                'source': src,
            })
        print('[Mali ReliefWeb] Found %d reports' % len(result['reports']))
    except Exception as e:
        result['error'] = str(e)[:200]
        print('[Mali ReliefWeb] Error: %s' % str(e)[:150])
    return result


# ------------------------------------------------------------------
# Sensor-voice so_what (the dial named, not diagnosed)
# ------------------------------------------------------------------
def _build_so_what(dtm_live):
    base = ('The dial that matters here is the BLOCKADE, not the displacement '
            'stock. Since September 2025 supply-route interdiction has squeezed '
            'Bamako directly -- fuel scarcity, then market and price collapse, '
            'then movement. Reading Mali as a mid-sized displacement crisis '
            'misses that its capital is under economic siege and that the '
            'humanitarian frontier has moved SOUTH into the food basket, '
            'reversing a decade-long north-and-centre pattern.')
    if dtm_live:
        return (base + ' Figures reflect the latest IOM DTM round; movements '
                'co-occurring with route interdiction and offensive cycles are '
                'surfaced for the analyst layer to read.')
    return (base + ' Live DTM round unavailable this cycle -- baseline figures '
            'shown with source dates (absence-honest).')


# ------------------------------------------------------------------
# Payload assembly
# ------------------------------------------------------------------
def build_mali_humanitarian(force=False):
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            return cached

    with _hum_lock:
        payload = json.loads(json.dumps(STATIC_BASELINE))  # deep copy
        payload['country'] = 'mali'
        payload['module']  = 'mali_humanitarian'
        payload['version'] = '1.0.0'
        payload['live_dtm'] = False
        payload['cached'] = False
        payload['generated_at'] = datetime.now(timezone.utc).isoformat()

        dtm = fetch_dtm_mali()
        if dtm and dtm.get('total_idps'):
            for stat in payload['headline_stats']:
                if stat['label'].startswith('Internally displaced'):
                    stat['value'] = dtm['total_idps']
                    stat['display'] = '{:,}'.format(dtm['total_idps'])
                    stat['source'] = 'IOM DTM API v3 (Round %s)' % dtm.get('round_number', '?')
                    stat['as_of'] = (dtm.get('reporting_date', '') or '')[:10]
            payload['live_dtm'] = True
            payload['dtm_detail'] = dtm

        rw = fetch_reliefweb_mali()
        payload['reliefweb_reports'] = rw.get('reports', [])
        payload['reliefweb_error']   = rw.get('error')

        payload['so_what'] = _build_so_what(payload['live_dtm'])

        _redis_set(CACHE_KEY, payload)
        return payload


# ------------------------------------------------------------------
# Endpoint registration
# ------------------------------------------------------------------
def register_mali_humanitarian_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/africa/humanitarian/mali', methods=['GET'])
    def mali_humanitarian():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        try:
            return jsonify(build_mali_humanitarian(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200],
                            'fallback': STATIC_BASELINE}), 500

    @app.route('/debug/mali-humanitarian', methods=['GET'])
    def debug_mali_humanitarian():
        """Raw source statuses for deploy verification."""
        dtm = fetch_dtm_mali()
        rw = fetch_reliefweb_mali(limit=3)
        return jsonify({
            'module':          'mali_humanitarian v1.0.0',
            'cache_key':       CACHE_KEY,
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_live_pull':   dtm,
            'reliefweb_count': len(rw.get('reports', [])),
            'reliefweb_error': rw.get('error'),
            'redis_wired':     bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'static_as_of':    STATIC_BASELINE['data_as_of'],
        })

    print('[Africa Backend] \u2705 Mali humanitarian endpoints registered')
