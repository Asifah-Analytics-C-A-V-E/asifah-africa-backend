"""
Asifah Analytics - Somalia Humanitarian Pulse (Sensor)
v1.0.0 - July 2026  |  Africa backend

SENSOR module (doctrine: stability pages are dials, not analysts). Emits RAW
displacement, food-security, and funding figures for Somalia with honest
sourcing and data_as_of dates. The analyst meaning (what the compound
famine-conflict-displacement pattern indicates) lives in the rhetoric / BLUF
layer, NOT here.

THE LIVE PICTURE (2025-2026): one of the world's largest displacement
caseloads (~3.8M IDPs) atop a drought-flood whiplash cycle, hit hard by the
2025-26 global aid cuts -- while the al-Shabaab resurgence and the AUSSOM
funding crisis squeeze humanitarian access from both ends.

DATA SOURCES:
  * Live   - IOM DTM API v3 (Ocp-Apim-Subscription-Key auth via DTM_API_KEY
             env var; Somalia is a flagship DTM country). Clones the proven
             ukraine_humanitarian.py call pattern.
  * Live   - ReliefWeb API (OCHA/UN/NGO reports, appname pattern).
  * Static - manually-maintained baseline so the card ALWAYS renders even if
             both live pulls miss. Every figure carries source + as_of.

REDIS:
  Cache: africa:humanitarian:somalia  (12h TTL)

ENDPOINTS:
  GET /api/africa/humanitarian/somalia            (cache-first)
  GET /api/africa/humanitarian/somalia?force=true (bypass cache)
  GET /debug/somalia-humanitarian

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

CACHE_KEY = 'africa:humanitarian:somalia'
CACHE_TTL = 12 * 3600   # 12 hours

_hum_lock = threading.Lock()

# ------------------------------------------------------------------
# STATIC BASELINE (always-present fallback; update as dashboards publish)
# Every figure attributed. Sensor voice: dials, not diagnosis.
# ------------------------------------------------------------------
STATIC_BASELINE = {
    'data_as_of': '2026-06-01',
    'headline_stats': [
        {'label': 'Internally displaced (IDPs)',
         'value': 3800000, 'display': '~3.8M',
         'source': 'IOM DTM / UNHCR', 'as_of': '2025-12'},
        {'label': 'People in Crisis+ food insecurity (IPC 3+)',
         'value': 4400000, 'display': '~4.4M',
         'source': 'IPC Somalia (projection)', 'as_of': '2026-H1'},
        {'label': 'Children acutely malnourished',
         'value': 1700000, 'display': '~1.7M',
         'source': 'OCHA / nutrition cluster', 'as_of': '2025-26 cycle'},
        {'label': 'Somali refugees in the region',
         'value': 900000, 'display': '~900K',
         'source': 'UNHCR (Kenya / Ethiopia / Yemen / Djibouti)', 'as_of': '2025'},
    ],
    'funding_note': ('Humanitarian response severely underfunded in the '
                     '2025-26 aid-cut environment; UN appeal coverage has run '
                     'far below need, forcing ration and program reductions.'),
    # Sensor-level factual note (drivers list), NOT analysis.
    'drivers_note': ('Displacement drivers: conflict (al-Shabaab offensive zones, '
                     'AUSSOM transition areas), drought-flood cycling (2022-23 '
                     'near-famine, El Nino flooding), and evictions in urban '
                     'IDP-hosting corridors. Access constrained in contested '
                     'districts.'),
    'sources': [
        {'name': 'IOM DTM Somalia', 'url': 'https://dtm.iom.int/somalia'},
        {'name': 'UNHCR Somalia Operational Data',
         'url': 'https://data.unhcr.org/en/country/som'},
        {'name': 'OCHA Somalia', 'url': 'https://www.unocha.org/somalia'},
        {'name': 'IPC Somalia',
         'url': 'https://www.ipcinfo.org/ipc-country-analysis/details-map/en/c/1157440/'},
        {'name': 'ReliefWeb Somalia', 'url': 'https://reliefweb.int/country/som'},
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
        print('[Somalia Humanitarian] redis get error: %s' % str(e)[:120])
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
        print('[Somalia Humanitarian] redis set error: %s' % str(e)[:120])


# ------------------------------------------------------------------
# LIVE SOURCE 1 - IOM DTM API v3 (clones proven ukraine_humanitarian pattern)
# ------------------------------------------------------------------
def fetch_dtm_somalia():
    """
    Country-level (Admin 0) IDP figures for Somalia from IOM DTM API v3.
    Returns dict or None. Conservative: only overrides static when a
    parseable figure lands.
    """
    if not DTM_API_KEY:
        print('[Somalia DTM] No DTM_API_KEY configured')
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
    }
    try:
        print('[Somalia DTM] Fetching country-level IDP data...')
        params = {
            'CountryName': 'Somalia',
            'FromReportingDate': '2024-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d'),
        }
        response = requests.get(
            '%s/displacement/admin0' % DTM_BASE_URL,
            headers=headers, params=params, timeout=15,
        )
        if response.status_code != 200:
            print('[Somalia DTM] HTTP %s' % response.status_code)
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            print('[Somalia DTM] No data returned')
            return None
        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
        most_recent = latest[0]
        idps = most_recent.get('numPresentIdpInd', 0)
        if not idps:
            return None
        print('[Somalia DTM] Country-level: {:,} IDPs (Round {})'.format(
            idps, most_recent.get('roundNumber', '?')))
        return {
            'total_idps':      idps,
            'reporting_date':  most_recent.get('reportingDate', ''),
            'round_number':    most_recent.get('roundNumber', ''),
            'source':          'IOM DTM API v3',
            'fetched_at':      datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print('[Somalia DTM] error: %s' % str(e)[:150])
        return None


# ------------------------------------------------------------------
# LIVE SOURCE 2 - ReliefWeb reports (clones proven pattern)
# ------------------------------------------------------------------
def fetch_reliefweb_somalia(limit=8):
    """Latest OCHA/UN/NGO reports for Somalia from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/som',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
    }
    try:
        print('[Somalia ReliefWeb] Fetching reports...')
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Somalia displacement drought humanitarian famine',
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
        print('[Somalia ReliefWeb] Found %d reports' % len(result['reports']))
    except Exception as e:
        result['error'] = str(e)[:200]
        print('[Somalia ReliefWeb] Error: %s' % str(e)[:150])
    return result


# ------------------------------------------------------------------
# Sensor-voice so_what (the dial named, not diagnosed)
# ------------------------------------------------------------------
def _build_so_what(dtm_live):
    base = ('Displacement stock measures Somalia\'s humanitarian load -- a '
            'standing pressure reading on urban absorption, aid logistics, '
            'and access negotiation with armed actors.')
    if dtm_live:
        return (base + ' Figures reflect the latest IOM DTM round; movements '
                'co-occurring with offensive cycles and flood seasons are '
                'surfaced for the analyst layer to read.')
    return (base + ' Live DTM round unavailable this cycle -- baseline '
            'figures shown with source dates (absence-honest).')


# ------------------------------------------------------------------
# Payload assembly
# ------------------------------------------------------------------
def build_somalia_humanitarian(force=False):
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            return cached

    with _hum_lock:
        payload = json.loads(json.dumps(STATIC_BASELINE))  # deep copy
        payload['country'] = 'somalia'
        payload['module']  = 'somalia_humanitarian'
        payload['version'] = '1.0.0'
        payload['live_dtm'] = False
        payload['cached'] = False
        payload['generated_at'] = datetime.now(timezone.utc).isoformat()

        dtm = fetch_dtm_somalia()
        if dtm and dtm.get('total_idps'):
            for stat in payload['headline_stats']:
                if stat['label'].startswith('Internally displaced'):
                    stat['value'] = dtm['total_idps']
                    stat['display'] = '{:,}'.format(dtm['total_idps'])
                    stat['source'] = 'IOM DTM API v3 (Round %s)' % dtm.get('round_number', '?')
                    stat['as_of'] = (dtm.get('reporting_date', '') or '')[:10]
            payload['live_dtm'] = True
            payload['dtm_detail'] = dtm

        rw = fetch_reliefweb_somalia()
        payload['reliefweb_reports'] = rw.get('reports', [])
        payload['reliefweb_error']   = rw.get('error')

        payload['so_what'] = _build_so_what(payload['live_dtm'])

        _redis_set(CACHE_KEY, payload)
        return payload


# ------------------------------------------------------------------
# Endpoint registration
# ------------------------------------------------------------------
def register_somalia_humanitarian_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/africa/humanitarian/somalia', methods=['GET'])
    def somalia_humanitarian():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        try:
            return jsonify(build_somalia_humanitarian(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200],
                            'fallback': STATIC_BASELINE}), 500

    @app.route('/debug/somalia-humanitarian', methods=['GET'])
    def debug_somalia_humanitarian():
        """Raw source statuses for deploy verification."""
        dtm = fetch_dtm_somalia()
        rw = fetch_reliefweb_somalia(limit=3)
        return jsonify({
            'module':          'somalia_humanitarian v1.0.0',
            'cache_key':       CACHE_KEY,
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_live_pull':   dtm,
            'reliefweb_count': len(rw.get('reports', [])),
            'reliefweb_error': rw.get('error'),
            'redis_wired':     bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'static_as_of':    STATIC_BASELINE['data_as_of'],
        })

    print('[Africa Backend] \u2705 Somalia humanitarian endpoints registered')
