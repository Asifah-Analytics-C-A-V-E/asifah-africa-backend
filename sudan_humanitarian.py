"""
Asifah Analytics - Sudan Humanitarian Pulse (Sensor)
v1.0.0 - July 2026  |  Africa backend

SENSOR module (doctrine: stability pages are dials, not analysts). Emits RAW
displacement, return, food-security, and disease figures for Sudan with honest
sourcing and data_as_of dates. The analyst meaning (what the compound
famine-kinetic-displacement pattern indicates) lives in the rhetoric / BLUF
layer, NOT here.

THE LIVE PICTURE (2025-2026): the world's largest displacement crisis -- ~9.0M
IDPs (down from the 11.59M peak of Jan 2025) with ~3.9M returnees, making
Sudan the flagship BIDIRECTIONAL migration case: mass return to Khartoum /
Gezira / Sennar where frontlines shifted, WHILE new displacement continues
from the Kordofan escalation (El Obeid siege) and Darfur. IPC Phase 5 famine
confirmed at multiple sites; cholera epidemic ongoing since Aug 2024.

DATA SOURCES:
  * Live   - IOM DTM API v3 (Sudan is DTM's largest operation: ~13,000
             locations, 185 localities, all 18 states). DTM_API_KEY env var
             required -- set on ME backend; COPY to Africa Render env for the
             LIVE badge, otherwise module falls back to attributed baseline.
  * Live   - ReliefWeb API (OCHA/UN/NGO reports, appname pattern).
  * Static - manually-maintained baseline so the card ALWAYS renders even if
             both live pulls miss. Every figure carries source + as_of.

REDIS:
  Cache: africa:humanitarian:sudan  (12h TTL)
  NOTE: rhetoric_tracker_sudan (next build) reads this key for its
  humanitarian convergence layer -- emit once, consume many.

ENDPOINTS:
  GET /api/africa/humanitarian/sudan            (cache-first)
  GET /api/africa/humanitarian/sudan?force=true (bypass cache)
  GET /debug/sudan-humanitarian

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

CACHE_KEY = 'africa:humanitarian:sudan'
CACHE_TTL = 12 * 3600   # 12 hours

_hum_lock = threading.Lock()

# ------------------------------------------------------------------
# STATIC BASELINE (always-present fallback; update as dashboards publish)
# Every figure attributed. Sensor voice: dials, not diagnosis.
# ------------------------------------------------------------------
STATIC_BASELINE = {
    'data_as_of': '2026-07-24',
    'headline_stats': [
        {'label': 'Internally displaced (IDPs)',
         'value': 9044786, 'display': '~9.0M',
         'source': 'IOM DTM Sudan snapshot', 'as_of': '2026-04'},
        {'label': 'Returnees (internal + from abroad)',
         'value': 3858136, 'display': '~3.9M',
         'source': 'IOM DTM Sudan snapshot', 'as_of': '2026-04'},
        {'label': 'Refugees / cross-border outflow',
         'value': 3500000, 'display': '3.5M+',
         'source': 'UNHCR regional (Chad, Egypt, South Sudan, Libya, CAR, Ethiopia, Uganda)',
         'as_of': '2026-H1'},
        {'label': 'People in Crisis+ food insecurity (IPC 3+)',
         'value': 24600000, 'display': '~24.6M',
         'source': 'IPC Sudan', 'as_of': '2025-26 IPC cycle'},
    ],
    'famine_note': ('IPC Phase 5 famine confirmed at Zamzam camp (Aug 2024) '
                    'and additional Darfur sites; famine-risk monitoring active '
                    'in Kordofan amid the El Obeid siege and humanitarian '
                    'access denial. (IPC / FEWS NET)'),
    'disease_note': ('Cholera epidemic ongoing since Aug 2024 across multiple '
                     'states, driven by water/sanitation collapse and health '
                     'system destruction. (WHO Disease Outbreak News / Federal '
                     'MoH situation reports)'),
    # Sensor-level factual note (drivers list), NOT analysis.
    'drivers_note': ('Displacement drivers: the Kordofan escalation since 25 Oct '
                     '2025 (219K+ displaced, El Obeid siege), the El Fasher '
                     'displacement wave (138K+ Oct 2025 - Mar 2026), and '
                     'Chad-border insecurity (Kebkabiya, Kernoi, Um Baru, At '
                     'Tina). Darfur holds ~63% of the national IDP stock. '
                     'SIMULTANEOUSLY, large-scale returns to Khartoum, Gezira, '
                     'and Sennar where frontlines shifted -- displacement and '
                     'return are measured together (bidirectional dial).'),
    'funding_note': ('Humanitarian response severely underfunded in the '
                     '2025-26 aid-cut environment; access systematically '
                     'constrained by both belligerents.'),
    'sources': [
        {'name': 'IOM DTM Sudan', 'url': 'https://dtm.iom.int/sudan'},
        {'name': 'UNHCR Sudan situation',
         'url': 'https://data.unhcr.org/en/situations/sudansituation'},
        {'name': 'OCHA Sudan', 'url': 'https://www.unocha.org/sudan'},
        {'name': 'IPC Sudan',
         'url': 'https://www.ipcinfo.org/ipc-country-analysis/details-map/en/c/1156903/'},
        {'name': 'ReliefWeb Sudan', 'url': 'https://reliefweb.int/country/sdn'},
        {'name': 'WHO Disease Outbreak News',
         'url': 'https://www.who.int/emergencies/disease-outbreak-news'},
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
        print('[Sudan Humanitarian] redis get error: %s' % str(e)[:120])
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
        print('[Sudan Humanitarian] redis set error: %s' % str(e)[:120])


# ------------------------------------------------------------------
# LIVE SOURCE 1 - IOM DTM API v3 (clones proven ukraine_humanitarian pattern)
# ------------------------------------------------------------------
def fetch_dtm_sudan():
    """
    Country-level (Admin 0) IDP figures for Sudan from IOM DTM API v3.
    Returns dict or None. Conservative: only overrides static when a
    parseable figure lands.
    """
    if not DTM_API_KEY:
        print('[Sudan DTM] No DTM_API_KEY configured')
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
    }
    try:
        print('[Sudan DTM] Fetching country-level IDP data...')
        params = {
            'CountryName': 'Sudan',
            'FromReportingDate': '2024-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d'),
        }
        response = requests.get(
            '%s/displacement/admin0' % DTM_BASE_URL,
            headers=headers, params=params, timeout=15,
        )
        if response.status_code != 200:
            print('[Sudan DTM] HTTP %s' % response.status_code)
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            print('[Sudan DTM] No data returned')
            return None
        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
        most_recent = latest[0]
        idps = most_recent.get('numPresentIdpInd', 0)
        if not idps:
            return None
        print('[Sudan DTM] Country-level: {:,} IDPs (Round {})'.format(
            idps, most_recent.get('roundNumber', '?')))
        return {
            'total_idps':      idps,
            'reporting_date':  most_recent.get('reportingDate', ''),
            'round_number':    most_recent.get('roundNumber', ''),
            'source':          'IOM DTM API v3',
            'fetched_at':      datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print('[Sudan DTM] error: %s' % str(e)[:150])
        return None


# ------------------------------------------------------------------
# LIVE SOURCE 2 - ReliefWeb reports (clones proven pattern)
# ------------------------------------------------------------------
def fetch_reliefweb_sudan(limit=8):
    """Latest OCHA/UN/NGO reports for Sudan from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/sdn',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
    }
    try:
        print('[Sudan ReliefWeb] Fetching reports...')
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Sudan displacement famine cholera humanitarian',
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
        print('[Sudan ReliefWeb] Found %d reports' % len(result['reports']))
    except Exception as e:
        result['error'] = str(e)[:200]
        print('[Sudan ReliefWeb] Error: %s' % str(e)[:150])
    return result


# ------------------------------------------------------------------
# Sensor-voice so_what (the dial named, not diagnosed)
# ------------------------------------------------------------------
def _build_so_what(dtm_live):
    base = ('Displacement stock and return flow are measured together -- '
            'Sudan is the flagship bidirectional case: mass return where '
            'frontlines shifted (Khartoum, Gezira, Sennar) WHILE new '
            'displacement continues from Kordofan and Darfur. Both dials '
            'are standing pressure readings on absorption, aid logistics, '
            'and access negotiation.')
    if dtm_live:
        return (base + ' Figures reflect the latest IOM DTM round; movements '
                'co-occurring with offensive cycles and famine sites are '
                'surfaced for the analyst layer to read.')
    return (base + ' Live DTM round unavailable this cycle -- baseline '
            'figures shown with source dates (absence-honest).')


# ------------------------------------------------------------------
# Payload assembly
# ------------------------------------------------------------------
def build_sudan_humanitarian(force=False):
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            return cached

    with _hum_lock:
        payload = json.loads(json.dumps(STATIC_BASELINE))  # deep copy
        payload['country'] = 'sudan'
        payload['module']  = 'sudan_humanitarian'
        payload['version'] = '1.0.0'
        payload['live_dtm'] = False
        payload['cached'] = False
        payload['generated_at'] = datetime.now(timezone.utc).isoformat()

        dtm = fetch_dtm_sudan()
        if dtm and dtm.get('total_idps'):
            for stat in payload['headline_stats']:
                if stat['label'].startswith('Internally displaced'):
                    stat['value'] = dtm['total_idps']
                    stat['display'] = '{:,}'.format(dtm['total_idps'])
                    stat['source'] = 'IOM DTM API v3 (Round %s)' % dtm.get('round_number', '?')
                    stat['as_of'] = (dtm.get('reporting_date', '') or '')[:10]
            payload['live_dtm'] = True
            payload['dtm_detail'] = dtm

        rw = fetch_reliefweb_sudan()
        payload['reliefweb_reports'] = rw.get('reports', [])
        payload['reliefweb_error']   = rw.get('error')

        payload['so_what'] = _build_so_what(payload['live_dtm'])

        _redis_set(CACHE_KEY, payload)
        return payload


# ------------------------------------------------------------------
# Endpoint registration
# ------------------------------------------------------------------
def register_sudan_humanitarian_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/africa/humanitarian/sudan', methods=['GET'])
    def sudan_humanitarian():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        try:
            return jsonify(build_sudan_humanitarian(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200],
                            'fallback': STATIC_BASELINE}), 500

    @app.route('/debug/sudan-humanitarian', methods=['GET'])
    def debug_sudan_humanitarian():
        """Raw source statuses for deploy verification."""
        dtm = fetch_dtm_sudan()
        rw = fetch_reliefweb_sudan(limit=3)
        return jsonify({
            'module':          'sudan_humanitarian v1.0.0',
            'cache_key':       CACHE_KEY,
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_live_pull':   dtm,
            'reliefweb_count': len(rw.get('reports', [])),
            'reliefweb_error': rw.get('error'),
            'redis_wired':     bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'static_as_of':    STATIC_BASELINE['data_as_of'],
        })

    print('[Africa Backend] \u2705 Sudan humanitarian endpoints registered')
