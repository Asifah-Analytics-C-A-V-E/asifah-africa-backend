"""
Asifah Analytics - Rwanda Humanitarian Pulse (Sensor)
v1.0.0 - November 2026  |  Africa backend

SENSOR module (doctrine: stability pages are dials, not analysts). Cloned from
drc_humanitarian.py.

WHY RWANDA'S CARD IS SHAPED DIFFERENTLY
    DRC       A war and an epidemic in the same provinces.
    Rwanda    A HOST AND A GATEWAY. Rwanda is not in a humanitarian crisis; it
              hosts about 140,000 refugees (60% Congolese, 38% Burundian) and
              sits on the DRC's busiest border (Rubavu-Goma), where Ebola and
              the war arrive first. It is also offering itself as a host for
              people Europe wants to remove (the Nov 2026 "return hub" plan).

The headline dial is REFUGEES HOSTED. The notes record the border (Ebola
restrictions), the European return-hub plan, and the economy's pressure
(inflation). The sensor reports; the reading belongs to the analyst layer.

DATA SOURCES:
  * Live   - IOM DTM API v3 (Rwanda rounds are rare; static stands otherwise).
  * Live   - ReliefWeb API.
  * Static - attributed baseline so the card ALWAYS renders.

REDIS:   africa:humanitarian:rwanda  (12h TTL)
ENDPOINTS:
  GET /api/africa/humanitarian/rwanda            (cache-first)
  GET /api/africa/humanitarian/rwanda?force=true (bypass cache; no Claude calls)
  GET /debug/rwanda-humanitarian

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import threading
from datetime import datetime, timezone

import requests

# ------------------------------------------------------------------
# Config  (CLONE SURFACE)
# ------------------------------------------------------------------
COUNTRY_SLUG    = 'rwanda'
COUNTRY_DISPLAY = 'Rwanda'
DTM_COUNTRY     = 'Rwanda'
RELIEFWEB_ISO3  = 'rwa'

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL') or '')
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN') or '')

DTM_API_KEY  = os.environ.get('DTM_API_KEY')
DTM_BASE_URL = 'https://dtmapi.iom.int/v3'

RELIEFWEB_API_URL = 'https://api.reliefweb.int/v1'

CACHE_KEY = 'africa:humanitarian:%s' % COUNTRY_SLUG
CACHE_TTL = 12 * 3600   # 12 hours

MODULE_VERSION = '1.0.0'

_hum_lock = threading.Lock()


# ------------------------------------------------------------------
# SEASONAL CALENDAR -- facts with dates, never a forecast
# ------------------------------------------------------------------
SEASONAL_CALENDAR = [
    {
        'id': 'long_rains',
        'label': 'Long rains',
        'months': [3, 4, 5],
        'window': 'March - May',
        'note': ('The heaviest rains; landslides and floods in the north and west (Rubavu, Ngororero) have '
                 'killed scores in past years (May 2023).'),
        'source': 'Rwanda Meteorology Agency / MINEMA',
    },
    {
        'id': 'short_rains',
        'label': 'Short rains',
        'months': [9, 10, 11, 12],
        'window': 'September - December',
        'note': 'The second rainy season; Season A planting.',
        'source': 'Rwanda Meteorology Agency',
    },
    {
        'id': 'kwibuka',
        'label': 'Kwibuka (genocide commemoration)',
        'months': [4, 5, 6, 7],
        'window': '7 April - 4 July (100 days)',
        'note': ('The national commemoration of the 1994 genocide against the Tutsi. It frames how Kigali speaks '
                 'about the FDLR and the eastern DRC every year.'),
        'source': 'Government of Rwanda (CNLG / MINUBUMWE)',
    },
]


def _calendar_state(now=None):
    """Which seasonal windows are OPEN right now. A fact, not a forecast."""
    now = now or datetime.now(timezone.utc)
    month = now.month
    out = []
    for w in SEASONAL_CALENDAR:
        out.append({'id': w['id'], 'label': w['label'], 'window': w['window'],
                    'open': month in w['months'], 'note': w['note'], 'source': w['source']})
    open_now = [w['label'] for w in out if w['open']]
    if open_now:
        summary = ('Open this cycle: %s. Read the figures above against these.' % ', '.join(open_now))
    else:
        summary = 'No seasonal window open this cycle.'
    return {'as_of_month': month, 'windows': out, 'open_now': open_now, 'summary': summary}


# ------------------------------------------------------------------
# STATIC BASELINE (always-present fallback; update as dashboards publish)
# ------------------------------------------------------------------
STATIC_BASELINE = {
    'data_as_of': '2026-11-27',
    'headline_stats': [
        # THE headline dial: a host, not a crisis.
        {'label': 'Refugees and others hosted in Rwanda',
         'value': 140750, 'display': '140.8K',
         'source': 'UNHCR / MINEMA (60.6% from the DRC, 38.3% from Burundi)', 'as_of': '2026-10-31'},
        {'label': 'Congolese refugees hosted',
         'value': 85291, 'display': '85.3K',
         'source': 'UNHCR / MINEMA', 'as_of': '2026-10-31'},
        {'label': 'Burundian refugees hosted',
         'value': 53840, 'display': '53.8K',
         'source': 'UNHCR / MINEMA', 'as_of': '2026-10-31'},
    ],
    'host_note': ('Rwanda hosts about 140,750 forcibly displaced people (31 Oct 2026): 85,291 from the DRC and '
                  '53,840 from Burundi -- both neighbours it has fraught relations with. (UNHCR / MINEMA)'),
    'border_note': ('The Rubavu-Goma crossing is the DRC\'s busiest border. Rwanda restricted it over Ebola in '
                    'May 2026, eased later; from 10 Oct 2026 Congolese without residence may not stay overnight '
                    'in Rwanda, after Ebola cases in southern Lubero (North Kivu). Rwanda has stepped up '
                    'screening; no Rwandan case has been reported in the sources reviewed. (Africanews, May '
                    '2026; allAfrica, 11 Oct 2026)'),
    'migration_note': ('On 16 Nov 2026 Austria, Denmark, Germany, Greece and the Netherlands announced plans for a '
                       '"return hub" in Rwanda for people with enforceable removal orders, targeting transfers in '
                       '2027; no formal agreement is signed and numbers are not public. The UK\'s earlier '
                       'scheme was ruled unlawful (2023) and scrapped (2024) after the UK paid about £290M and '
                       'four people relocated voluntarily. (Al Jazeera, 17 Nov 2026)'),
    'economy_note': ('Strong growth (9.7% in H1 2026) alongside 15.7% inflation in August 2026 -- three times '
                     'the 5% target -- and a policy rate raised to 8.75%. Rising prices land first on food. '
                     '(IMF, Oct 2026)'),
    'sources': [
        {'name': 'UNHCR Rwanda data portal (31 Oct 2026)', 'url': 'https://data.unhcr.org/en/country/rwa'},
        {'name': 'Africanews: Rwanda tightens border controls over Ebola (May 2026)', 'url': 'https://www.africanews.com/2026/05/20/rwanda-tightens-border-controls-over-deadly-ebola-outbreak-in-dr-congo/'},
        {'name': 'allAfrica: Goma-Gisenyi restrictions (Oct 2026)', 'url': 'https://fr.allafrica.com/stories/202610120291.html'},
        {'name': 'Al Jazeera: five EU countries and a Rwanda return hub (Nov 2026)', 'url': 'https://aljazeera.com/news/2026/11/17/why-are-five-eu-countries-reviving-plans-to-deport-migrants-to-rwanda'},
        {'name': 'IMF: Rwanda ECF first review (Oct 2026)', 'url': 'https://www.imf.org/en/news/articles/2026/10/05/pr26321-rwanda-ecf-review'},
        {'name': 'ReliefWeb Rwanda', 'url': 'https://reliefweb.int/country/rwa'},
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
        print('[Rwanda Humanitarian] redis get error: %s' % str(e)[:120])
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
        print('[Rwanda Humanitarian] redis set error: %s' % str(e)[:120])


# ------------------------------------------------------------------
# LIVE SOURCE 1 - IOM DTM API v3
# ------------------------------------------------------------------
def fetch_dtm_rwanda():
    """
    Country-level (Admin 0) figures for Rwanda from IOM DTM API v3.
    Returns dict or None. Conservative: only overrides static when a parseable
    figure lands.
    """
    if not DTM_API_KEY:
        print('[Rwanda DTM] No DTM_API_KEY configured')
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
    }
    try:
        print('[Rwanda DTM] Fetching country-level IDP data...')
        params = {
            'CountryName': DTM_COUNTRY,
            'FromReportingDate': '2024-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d'),
        }
        response = requests.get(
            '%s/displacement/admin0' % DTM_BASE_URL,
            headers=headers, params=params, timeout=15,
        )
        if response.status_code != 200:
            print('[Rwanda DTM] HTTP %s' % response.status_code)
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            print('[Rwanda DTM] No data returned')
            return None
        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
        most_recent = latest[0]
        idps = most_recent.get('numPresentIdpInd', 0)
        if not idps:
            return None
        print('[Rwanda DTM] Country-level: {:,} IDPs (Round {})'.format(
            idps, most_recent.get('roundNumber', '?')))
        return {
            'total_idps':      idps,
            'reporting_date':  most_recent.get('reportingDate', ''),
            'round_number':    most_recent.get('roundNumber', ''),
            'source':          'IOM DTM API v3',
            'fetched_at':      datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print('[Rwanda DTM] error: %s' % str(e)[:150])
        return None


# ------------------------------------------------------------------
# LIVE SOURCE 2 - ReliefWeb reports
# ------------------------------------------------------------------
def fetch_reliefweb_rwanda(limit=8):
    """Latest OCHA/UN/NGO reports for Rwanda from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/%s' % RELIEFWEB_ISO3,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
    }
    try:
        print('[Rwanda ReliefWeb] Fetching reports...')
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Rwanda',
            'filter[field]': 'primary_country.iso3',
            'filter[value]': RELIEFWEB_ISO3,
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
        print('[Rwanda ReliefWeb] Found %d reports' % len(result['reports']))
    except Exception as e:
        result['error'] = str(e)[:200]
        print('[Rwanda ReliefWeb] Error: %s' % str(e)[:150])
    return result


# ------------------------------------------------------------------
# Sensor-voice so_what (the dial named, not diagnosed)
# ------------------------------------------------------------------
def _build_so_what(dtm_live, calendar):
    base = ('A host and a gateway, not a crisis: Rwanda shelters about 140,750 refugees (85,291 Congolese, '
            '53,840 Burundian) and sits on the DRC\'s busiest border, where Ebola restrictions have tightened '
            'twice in 2026. Five EU states now want to send people Europe is removing to a "return hub" here.')
    if calendar.get('open_now'):
        base += ' Seasonal windows open this cycle: %s.' % ', '.join(calendar['open_now'])
    return base + ' Figures are the latest published, shown with their dates (absence-honest).'


def build_rwanda_humanitarian(force=False):
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            return cached
    with _hum_lock:
        payload = json.loads(json.dumps(STATIC_BASELINE))
        payload.update(country=COUNTRY_SLUG, country_display=COUNTRY_DISPLAY,
                       module='rwanda_humanitarian', version=MODULE_VERSION, live_dtm=False,
                       cached=False, generated_at=datetime.now(timezone.utc).isoformat())
        dtm = None   # Rwanda has no IDP caseload to override; DTM stays off (debug route still probes it)
        if dtm and dtm.get('total_idps'):
            for stat in payload['headline_stats']:
                if stat['label'] == 'Internally displaced':
                    stat['value'] = dtm['total_idps']
                    stat['display'] = '{:,}'.format(dtm['total_idps'])
                    stat['source'] = 'IOM DTM API v3 (Round %s)' % dtm.get('round_number', '?')
                    stat['as_of'] = (dtm.get('reporting_date', '') or '')[:10]
            payload['live_dtm'] = True
            payload['dtm_detail'] = dtm
        rw = fetch_reliefweb_rwanda()
        payload['reliefweb_reports'] = rw.get('reports', [])
        payload['reliefweb_error'] = rw.get('error')
        payload['seasonal_calendar'] = _calendar_state()
        payload['so_what'] = _build_so_what(payload['live_dtm'], payload['seasonal_calendar'])
        _redis_set(CACHE_KEY, payload)
        return payload


def register_rwanda_humanitarian_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/africa/humanitarian/rwanda', methods=['GET'])
    def rwanda_humanitarian():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        try:
            return jsonify(build_rwanda_humanitarian(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200], 'fallback': STATIC_BASELINE}), 500

    @app.route('/debug/rwanda-humanitarian', methods=['GET'])
    def debug_rwanda_humanitarian():
        dtm = fetch_dtm_rwanda()
        rw = fetch_reliefweb_rwanda(limit=3)
        return jsonify({'module': 'rwanda_humanitarian v%s' % MODULE_VERSION, 'cache_key': CACHE_KEY,
                        'dtm_api_key_set': bool(DTM_API_KEY), 'dtm_live_pull': dtm,
                        'reliefweb_count': len(rw.get('reports', [])), 'reliefweb_error': rw.get('error'),
                        'redis_wired': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
                        'static_as_of': STATIC_BASELINE['data_as_of'], 'calendar_now': _calendar_state()})

    print('[Africa Backend] ✅ Rwanda humanitarian endpoints registered')
