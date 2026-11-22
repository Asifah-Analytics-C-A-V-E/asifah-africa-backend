"""
Asifah Analytics - Central African Republic Humanitarian Pulse (Sensor)
v1.0.0 - November 2026  |  Africa backend

SENSOR module (doctrine: stability pages are dials, not analysts). Raw
displacement, hosting, food and access figures for CAR with honest sourcing and
dates. The meaning lives in the rhetoric / BLUF layer.

Cloned from niger_humanitarian.py.

WHY CAR'S CARD IS SHAPED DIFFERENTLY
    Niger     A CROSSROADS (host, source, transit, dumping ground).
    CAR       A COUNTRY HALF OUTSIDE ITS BORDERS. More Central Africans live as
              refugees abroad (~668,000 -- in Cameroon, the DRC and Chad) than are
              displaced inside the country (~442,000): about one person in five.
              CAR is ALSO a host: ~40,000 Sudanese at Korsi (Birao, Vakaga) and
              beyond, at the end of a road that closes for half the year.

The headline dial is DISPLACED ABROAD vs AT HOME. The second is the SUDAN
OVERSPILL into Vakaga, because it is the one flow set by a neighbour's war. The
sensor reports both; the reading belongs to the analyst layer.

SEASONAL CALENDAR: transhumance (Dec-Apr, herders from Chad and Sudan move
south -- a recurring trigger of farmer-herder violence and armed-group
predation), the rainy season (roads to the northeast close), the lean season,
malaria's peak, and the Ubangi river's barge window. Facts with dates; the
calendar never fires on its own.

DATA SOURCES:
  * Live   - IOM DTM API v3 (CAR coverage is thin; the static figure stands if no round lands).
  * Live   - ReliefWeb API.
  * Static - attributed baseline so the card ALWAYS renders.

REDIS:   africa:humanitarian:car  (12h TTL)
ENDPOINTS:
  GET /api/africa/humanitarian/car            (cache-first)
  GET /api/africa/humanitarian/car?force=true (bypass cache; no Claude calls)
  GET /debug/car-humanitarian

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
COUNTRY_SLUG    = 'car'
COUNTRY_DISPLAY = 'Central African Republic'
DTM_COUNTRY     = 'Central African Republic'
RELIEFWEB_ISO3  = 'caf'

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
        'id': 'transhumance',
        'label': 'Transhumance season',
        'months': [12, 1, 2, 3, 4],
        'window': 'December - April',
        'note': ('Herders from Chad and Sudan drive cattle south into CAR for dry-season '
                 'grazing. Armed groups tax and escort the herds; clashes with farmers and '
                 'reprisal killings peak in these months, especially in the northwest '
                 '(Ouham, Ouham-Pende, Nana-Mambere) and the centre-east.'),
        'source': 'MINUSCA / Crisis Group reporting on transhumance corridors',
    },
    {
        'id': 'rainy_season',
        'label': 'Rainy season (roads close)',
        'months': [5, 6, 7, 8, 9, 10],
        'window': 'May - October',
        'note': ('Unpaved roads become impassable; Vakaga (Birao, Korsi) is largely cut off by '
                 'road for months, so aid to the Sudanese refugees there moves by air or not at all.'),
        'source': 'OCHA CAR access reporting / Logistics Cluster',
    },
    {
        'id': 'lean_season',
        'label': 'Lean season',
        'months': [4, 5, 6, 7, 8],
        'window': 'April - August',
        'note': ('IPC projects 2.29 million people (35%) in crisis or worse in April-August 2026, '
                 'against 1.92 million in the September-March period.'),
        'source': 'IPC CAR, Sep 2025 - Aug 2026',
    },
    {
        'id': 'malaria_peak',
        'label': 'Malaria peak',
        'months': [7, 8, 9, 10],
        'window': 'July - October',
        'note': 'Malaria is the leading cause of death among children under five in CAR; the rains drive the peak.',
        'source': 'WHO / UNICEF CAR',
    },
    {
        'id': 'ubangi_barge',
        'label': 'Ubangi river barge window',
        'months': [7, 8, 9, 10, 11, 12],
        'window': 'roughly July - December',
        'note': ('High water lets barges reach Bangui from Brazzaville and Kinshasa: the only '
                 'alternative to the Douala road. Outside it, the road carries everything.'),
        'source': 'Logistics Cluster CAR',
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
    'data_as_of': '2026-02-05',
    'headline_stats': [
        {'label': 'People in need of assistance',
         'value': 2300000, 'display': '2.3M',
         'source': 'OCHA CAR HRP 2026 (about 35% of the population)', 'as_of': '2026-02-05'},
        # THE headline dial: more Central Africans displaced ABROAD than at home.
        {'label': 'Central Africans who are refugees abroad',
         'value': 668000, 'display': '~668K',
         'source': 'UNHCR Global Appeal 2026 (Cameroon 42%, DRC 31%, Chad 21%)', 'as_of': '2025-12'},
        {'label': 'Internally displaced',
         'value': 442000, 'display': '442K',
         'source': 'UNHCR / Commission Mouvement de Populations', 'as_of': '2025-09'},
        # The second dial: a flow set by a neighbour's war.
        {'label': 'Sudanese refugees hosted (Korsi / Birao and beyond)',
         'value': 40211, 'display': '40.2K',
         'source': 'UNHCR CAR Sudan situation update', 'as_of': '2025-12-08'},
    ],
    'diaspora_note': ('About one Central African in five is displaced, and more of them live as '
                      'refugees abroad (~668,000) than as displaced people at home (~442,000). '
                      'Cameroon hosts 42% of the refugees, the DRC 31% and Chad 21%. Returns are '
                      'real but small: about 69,000 since 2017, with roughly 15,000 in 2025. '
                      '(UNHCR Global Appeal 2026)'),
    'host_note': ('CAR is also a host. Some 47,000 people crossed from Sudan, mostly at Am '
                  'Dafock in Vakaga; 40,211 Sudanese refugees were counted in December 2025, '
                  '26,981 of them at the Korsi site about 60 km from the border, the rest in '
                  'hard-to-reach Bamingui-Bangoran, Haute-Kotto, Ouaka, Mbomou and Haut-Mbomou. '
                  'About 6,900 Central Africans who had been refugees in Darfur came home the '
                  'same way. (UNHCR, 8 Dec 2025)'),
    'food_note': ('1.92 million people (29%) were in crisis-level food insecurity or worse '
                  '(IPC 3+) in September 2025 - March 2026, 269,000 of them in emergency (IPC 4). '
                  'The lean-season projection for April - August 2026 was 2.29 million (35%), '
                  'with 400,000 in emergency. Drivers named: armed conflict in the north and '
                  'south, displacement, low harvests and stocks, high imported food and fuel '
                  'prices, and falling food aid. (IPC CAR)'),
    'access_note': ('CAR imports almost everything, fuel included, up one road from Douala. In '
                    'July 2026 Bangui ran about ten days of fuel queues (street price 1,500 FCFA a '
                    'litre against 1,100 official); in October 2026 more than 100 trucks sat at '
                    'Garoua-Boulai when Cameroonian drivers struck over harassment on the CAR '
                    'side. (Radio Ndeke Luka; Journal de Bangui)'),
    'insecurity_note': ('The fronts the displacement figures come from: the northwest (3R remnants, '
                        'CPC; transhumance corridors), the southeast (Haut-Mbomou, where the Azande '
                        'Ani Kpi Gbe militia and others fight), and the northeast tri-border with '
                        'Chad and Sudan (Vakaga). Ex-3R members have alleged ceasefire violations by '
                        'Russian fighters. (MINUSCA / HRW World Report 2026)'),
    'funding_note': ('The 2026 humanitarian plan asks for $264.1 million to reach 1.3 million of the '
                     '2.3 million in need; partners say funding continues to fall far below needs. '
                     'MINUSCA, renewed on 13 Nov 2026 to 15 Nov 2027, operates under the UN\'s own '
                     'cash crisis. (OCHA, 5 Feb 2026; Africanews)'),
    'sources': [
        {'name': 'OCHA CAR HRP 2026', 'url': 'https://reliefweb.int/report/central-african-republic/car-humanitarian-community-calls-urgent-support-assist-13-million-people-2026'},
        {'name': 'UNHCR CAR Global Appeal 2026', 'url': 'https://www.unhcr.org/sites/default/files/2025-12/Central%20Africa%20Republic%20situation%20overview%20-%20Global%20Appeal%202026.pdf'},
        {'name': 'UNHCR CAR Sudan situation (Dec 2025)', 'url': 'https://www.unhcr.org/sites/default/files/2025-12/Central%20African%20Republic%20Sudan%20Situation%20Update%20-%208%20December%202025.pdf'},
        {'name': 'IPC CAR Sep 2025 - Aug 2026', 'url': 'https://www.foodsecurityportal.org/sites/default/files/2025-11/IPC_CAR_Acute_Food_Insecurity_Sep2025_Aug2026_Snapshot_English.pdf'},
        {'name': 'ReliefWeb CAR', 'url': 'https://reliefweb.int/country/caf'},
        {'name': 'HRW World Report 2026: CAR', 'url': 'https://www.hrw.org/world-report/2026/country-chapters/central-african-republic'},
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
        print('[CAR Humanitarian] redis get error: %s' % str(e)[:120])
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
        print('[CAR Humanitarian] redis set error: %s' % str(e)[:120])


# ------------------------------------------------------------------
# LIVE SOURCE 1 - IOM DTM API v3
# ------------------------------------------------------------------
def fetch_dtm_car():
    """
    Country-level (Admin 0) IDP figures for CAR from IOM DTM API v3.
    Returns dict or None. Conservative: only overrides static when a parseable
    figure lands.
    """
    if not DTM_API_KEY:
        print('[CAR DTM] No DTM_API_KEY configured')
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
    }
    try:
        print('[CAR DTM] Fetching country-level IDP data...')
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
            print('[CAR DTM] HTTP %s' % response.status_code)
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            print('[CAR DTM] No data returned')
            return None
        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
        most_recent = latest[0]
        idps = most_recent.get('numPresentIdpInd', 0)
        if not idps:
            return None
        print('[CAR DTM] Country-level: {:,} IDPs (Round {})'.format(
            idps, most_recent.get('roundNumber', '?')))
        return {
            'total_idps':      idps,
            'reporting_date':  most_recent.get('reportingDate', ''),
            'round_number':    most_recent.get('roundNumber', ''),
            'source':          'IOM DTM API v3',
            'fetched_at':      datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print('[CAR DTM] error: %s' % str(e)[:150])
        return None


# ------------------------------------------------------------------
# LIVE SOURCE 2 - ReliefWeb reports
# ------------------------------------------------------------------
def fetch_reliefweb_car(limit=8):
    """Latest OCHA/UN/NGO reports for CAR from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/%s' % RELIEFWEB_ISO3,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
    }
    try:
        print('[CAR ReliefWeb] Fetching reports...')
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Central African Republic',
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
        print('[CAR ReliefWeb] Found %d reports' % len(result['reports']))
    except Exception as e:
        result['error'] = str(e)[:200]
        print('[CAR ReliefWeb] Error: %s' % str(e)[:150])
    return result


# ------------------------------------------------------------------
# Sensor-voice so_what (the dial named, not diagnosed)
# ------------------------------------------------------------------
def _build_so_what(dtm_live, calendar):
    base = ('About one Central African in five is displaced, and more of them are refugees '
            'abroad (~668,000) than displaced at home (~442,000). CAR is also a host: some '
            '40,000 Sudanese at the far end of a road that closes for half the year. 2.3 '
            'million people (35%) need assistance.')
    if calendar.get('open_now'):
        base += ' Seasonal windows open this cycle: %s.' % ', '.join(calendar['open_now'])
    if dtm_live:
        return base + ' Internal displacement reflects the latest IOM DTM round.'
    return base + ' Figures are the latest published, shown with their dates (absence-honest).'


def build_car_humanitarian(force=False):
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            return cached
    with _hum_lock:
        payload = json.loads(json.dumps(STATIC_BASELINE))
        payload.update(country=COUNTRY_SLUG, country_display=COUNTRY_DISPLAY,
                       module='car_humanitarian', version=MODULE_VERSION, live_dtm=False,
                       cached=False, generated_at=datetime.now(timezone.utc).isoformat())
        dtm = fetch_dtm_car()
        if dtm and dtm.get('total_idps'):
            for stat in payload['headline_stats']:
                if stat['label'] == 'Internally displaced':
                    stat['value'] = dtm['total_idps']
                    stat['display'] = '{:,}'.format(dtm['total_idps'])
                    stat['source'] = 'IOM DTM API v3 (Round %s)' % dtm.get('round_number', '?')
                    stat['as_of'] = (dtm.get('reporting_date', '') or '')[:10]
            payload['live_dtm'] = True
            payload['dtm_detail'] = dtm
        rw = fetch_reliefweb_car()
        payload['reliefweb_reports'] = rw.get('reports', [])
        payload['reliefweb_error'] = rw.get('error')
        payload['seasonal_calendar'] = _calendar_state()
        payload['so_what'] = _build_so_what(payload['live_dtm'], payload['seasonal_calendar'])
        _redis_set(CACHE_KEY, payload)
        return payload


def register_car_humanitarian_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/africa/humanitarian/car', methods=['GET'])
    def car_humanitarian():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        try:
            return jsonify(build_car_humanitarian(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200], 'fallback': STATIC_BASELINE}), 500

    @app.route('/debug/car-humanitarian', methods=['GET'])
    def debug_car_humanitarian():
        dtm = fetch_dtm_car()
        rw = fetch_reliefweb_car(limit=3)
        return jsonify({'module': 'car_humanitarian v%s' % MODULE_VERSION, 'cache_key': CACHE_KEY,
                        'dtm_api_key_set': bool(DTM_API_KEY), 'dtm_live_pull': dtm,
                        'reliefweb_count': len(rw.get('reports', [])), 'reliefweb_error': rw.get('error'),
                        'redis_wired': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
                        'static_as_of': STATIC_BASELINE['data_as_of'], 'calendar_now': _calendar_state()})

    print('[Africa Backend] ✅ CAR humanitarian endpoints registered')
