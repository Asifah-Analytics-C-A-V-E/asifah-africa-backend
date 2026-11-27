"""
Asifah Analytics - Democratic Republic of the Congo Humanitarian Pulse (Sensor)
v1.0.0 - November 2026  |  Africa backend

SENSOR module (doctrine: stability pages are dials, not analysts). Raw
epidemic, displacement, food and funding figures for the DRC with honest
sourcing and dates. The meaning lives in the rhetoric / BLUF layer.

Cloned from car_humanitarian.py.

WHY THE DRC'S CARD IS SHAPED DIFFERENTLY
    CAR       A country half outside its borders (refugees abroad > IDPs).
    DRC       A WAR AND AN EPIDEMIC IN THE SAME PROVINCES. The Bundibugyo Ebola
              outbreak (a WHO global health emergency since 17 May 2026) is
              worst in Ituri and North Kivu -- the same provinces as the ADF,
              CODECO and the M23 / FRN front. Fighting moves people, and moving
              people move the virus; insecurity is the response's named obstacle.

The headline dial is EBOLA (confirmed cases and deaths, dated). The second is
DISPLACEMENT (millions inside, ~1.3M refugees in the region). The third is
HUNGER, the largest IPC caseload in the world. The sensor reports all three;
the reading belongs to the analyst layer.

The Ebola figures are a DATED static reading from WHO Disease Outbreak News:
WHO publishes no machine-readable count. The card shows the date in every
render, and data_as_of says when it was last updated by hand.

DATA SOURCES:
  * Live   - IOM DTM API v3 (DRC rounds; overrides the static IDP figure when one lands).
  * Live   - ReliefWeb API (latest reports, including Ebola situation reports).
  * Static - attributed baseline so the card ALWAYS renders.

REDIS:   africa:humanitarian:drc  (12h TTL)
ENDPOINTS:
  GET /api/africa/humanitarian/drc            (cache-first)
  GET /api/africa/humanitarian/drc?force=true (bypass cache; no Claude calls)
  GET /debug/drc-humanitarian

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
COUNTRY_SLUG    = 'drc'
COUNTRY_DISPLAY = 'Democratic Republic of the Congo'
DTM_COUNTRY     = 'Democratic Republic of the Congo'
RELIEFWEB_ISO3  = 'cod'

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
        'id': 'main_rains',
        'label': 'Main rainy season in the east',
        'months': [9, 10, 11, 12],
        'window': 'September - December',
        'note': ('Roads in the Kivus and Ituri degrade, slowing aid convoys and Ebola contact '
                 'tracing; cholera and malaria risk rise in crowded displacement sites.'),
        'source': 'OCHA DRC access reporting / WHO AFRO',
    },
    {
        'id': 'second_rains',
        'label': 'Second rainy season in the east',
        'months': [3, 4, 5],
        'window': 'March - May',
        'note': 'The shorter rains; flooding along Lake Tanganyika and Lake Kivu shores has displaced thousands in past years.',
        'source': 'OCHA DRC',
    },
    {
        'id': 'season_a_harvest',
        'label': 'Season A harvest (east)',
        'months': [12, 1],
        'window': 'December - January',
        'note': ('The main harvest in the Kivus. Where fighting or displacement kept farmers off '
                 'their fields at planting (September), this harvest is the one that fails.'),
        'source': 'FEWS NET DRC',
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
    'data_as_of': '2026-11-20',
    'headline_stats': [
        # THE headline dial: a war and an epidemic in the same provinces.
        {'label': 'Ebola (Bundibugyo) confirmed cases',
         'value': 11613, 'display': '11,613',
         'source': 'WHO Disease Outbreak News DON630 (8 provinces; Ituri 7,946, North Kivu 2,996)', 'as_of': '2026-11-17'},
        {'label': 'Ebola deaths',
         'value': 5678, 'display': '5,678',
         'source': 'WHO DON630 (crude case fatality 48.9%)', 'as_of': '2026-11-17'},
        {'label': 'Internally displaced',
         'value': 5300000, 'display': '5.3M+',
         'source': 'Global Humanitarian Overview 2026 (displacement as of Sep 2025)', 'as_of': '2025-09'},
        {'label': 'People in crisis-level hunger (IPC 3+)',
         'value': 28800000, 'display': '28.8M',
         'source': 'IPC DRC (Sep - Dec 2026; 3.6M in emergency, IPC 4)', 'as_of': '2026-11'},
    ],
    'ebola_note': ('The Bundibugyo Ebola outbreak was declared a public health emergency of '
                   'international concern on 17 May 2026 and confirmed again on 18 November. By '
                   '17 November: 11,613 confirmed cases and 5,678 deaths in 68 health zones of '
                   'eight provinces, with active transmission in 48. Ituri (7,946 cases) and North '
                   'Kivu (2,996) carry most of it; South Kivu and Sud-Ubangi have had no case for '
                   'more than 42 days. Kenya has 9 confirmed cases (no new case since 19 October); '
                   'Nigeria had one imported case, evacuated and recovered. Uganda declared its own '
                   'outbreak over in August. There is no licensed vaccine for the Bundibugyo strain. '
                   '(WHO DON630, 20 Nov 2026)'),
    'displacement_note': ('More than 5.3 million people were internally displaced (Sep 2025), most '
                          'of them in North Kivu, South Kivu and Ituri. About 1.3 million Congolese '
                          'are refugees in the region, 250,811 of them arriving between January 2025 '
                          'and May 2026 -- most to Burundi and Uganda. (GHO 2026; UNHCR regional '
                          'update, 31 May 2026)'),
    'food_note': ('28.8 million people (23% of those analysed) are in crisis-level food insecurity '
                  'or worse through December 2026, 3.6 million in emergency (IPC 4); the projection '
                  'for January - June 2027 is 30.3 million, 4.2 million in emergency. North Kivu, '
                  'South Kivu and Ituri hold 10.4 million of them; Djugu, Fizi, Shabunda and Walungu '
                  'territories are in emergency. Drivers named: conflict, Ebola, prices, El Nino '
                  'flooding and falling aid. (IPC alert via WFP/FAO, Nov 2026)'),
    'insecurity_note': ('The fronts the figures come from: South Kivu, where the FRN (Joseph Kabila\'s '
                        'coalition, launched 12 Oct 2026 with M23/AFC inside it) opened an offensive '
                        'in Kalehe on 6 Nov 2026; North Kivu (Masisi, Rutshuru, Walikale), contested '
                        'between the FRN and the army with allied Wazalendo militias; and Ituri, '
                        'where the ADF and CODECO attack civilians and Ugandan troops fight the ADF '
                        'alongside the Congolese army. (Critical Threats, 11 Nov 2026)'),
    'funding_note': ('The 2026 humanitarian plan asked for $1.4 billion to reach 7.3 million of the '
                     '14.9 million people in need, prioritising 4.7 million in the most severe zones '
                     '($937 million). The 14.9 million is down from 21.2 million in 2025 because of a '
                     'change of method, not an improvement. (GHO 2026)'),
    'sources': [
        {'name': 'WHO Disease Outbreak News DON630 (20 Nov 2026)', 'url': 'https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON630'},
        {'name': 'Global Humanitarian Overview 2026: DRC', 'url': 'https://humanitarianaction.info/document/global-humanitarian-overview-2026/article/democratic-republic-congo-4'},
        {'name': 'UNHCR Eastern DRC regional update (31 May 2026)', 'url': 'https://www.ecoi.net/en/file/local/2141458/38%20DRC%20Situation%20External%20Update%2031%20%20May%202026%20-%20FINAL.pdf'},
        {'name': 'WFP / FAO: hunger deepens in DRC (Nov 2026)', 'url': 'https://www.developmentaid.org/news-stream/post/212441/hunger-deepens-for-millions-in-dr-congo'},
        {'name': 'Critical Threats: Congo War Security Review (11 Nov 2026)', 'url': 'https://www.criticalthreats.org/briefs/congo-war-security-review/november-11-2026'},
        {'name': 'ReliefWeb DRC', 'url': 'https://reliefweb.int/country/cod'},
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
        print('[DRC Humanitarian] redis get error: %s' % str(e)[:120])
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
        print('[DRC Humanitarian] redis set error: %s' % str(e)[:120])


# ------------------------------------------------------------------
# LIVE SOURCE 1 - IOM DTM API v3
# ------------------------------------------------------------------
def fetch_dtm_drc():
    """
    Country-level (Admin 0) IDP figures for the DRC from IOM DTM API v3.
    Returns dict or None. Conservative: only overrides static when a parseable
    figure lands.
    """
    if not DTM_API_KEY:
        print('[DRC DTM] No DTM_API_KEY configured')
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
    }
    try:
        print('[DRC DTM] Fetching country-level IDP data...')
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
            print('[DRC DTM] HTTP %s' % response.status_code)
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            print('[DRC DTM] No data returned')
            return None
        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
        most_recent = latest[0]
        idps = most_recent.get('numPresentIdpInd', 0)
        if not idps:
            return None
        print('[DRC DTM] Country-level: {:,} IDPs (Round {})'.format(
            idps, most_recent.get('roundNumber', '?')))
        return {
            'total_idps':      idps,
            'reporting_date':  most_recent.get('reportingDate', ''),
            'round_number':    most_recent.get('roundNumber', ''),
            'source':          'IOM DTM API v3',
            'fetched_at':      datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print('[DRC DTM] error: %s' % str(e)[:150])
        return None


# ------------------------------------------------------------------
# LIVE SOURCE 2 - ReliefWeb reports
# ------------------------------------------------------------------
def fetch_reliefweb_drc(limit=8):
    """Latest OCHA/UN/NGO reports for the DRC from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/%s' % RELIEFWEB_ISO3,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
    }
    try:
        print('[DRC ReliefWeb] Fetching reports...')
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Democratic Republic of the Congo',
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
        print('[DRC ReliefWeb] Found %d reports' % len(result['reports']))
    except Exception as e:
        result['error'] = str(e)[:200]
        print('[DRC ReliefWeb] Error: %s' % str(e)[:150])
    return result


# ------------------------------------------------------------------
# Sensor-voice so_what (the dial named, not diagnosed)
# ------------------------------------------------------------------
def _build_so_what(dtm_live, calendar):
    base = ('A war and an epidemic in the same provinces: 11,613 confirmed Ebola cases and 5,678 '
            'deaths (WHO, to 17 Nov 2026), most of them in Ituri and North Kivu, where the fighting '
            'is. More than 5.3 million people are displaced inside the country and about 1.3 million '
            'are refugees in the region; 28.8 million face crisis-level hunger.')
    if calendar.get('open_now'):
        base += ' Seasonal windows open this cycle: %s.' % ', '.join(calendar['open_now'])
    if dtm_live:
        return base + ' Internal displacement reflects the latest IOM DTM round.'
    return base + ' Figures are the latest published, shown with their dates (absence-honest).'


def build_drc_humanitarian(force=False):
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            return cached
    with _hum_lock:
        payload = json.loads(json.dumps(STATIC_BASELINE))
        payload.update(country=COUNTRY_SLUG, country_display=COUNTRY_DISPLAY,
                       module='drc_humanitarian', version=MODULE_VERSION, live_dtm=False,
                       cached=False, generated_at=datetime.now(timezone.utc).isoformat())
        dtm = fetch_dtm_drc()
        if dtm and dtm.get('total_idps'):
            for stat in payload['headline_stats']:
                if stat['label'] == 'Internally displaced':
                    stat['value'] = dtm['total_idps']
                    stat['display'] = '{:,}'.format(dtm['total_idps'])
                    stat['source'] = 'IOM DTM API v3 (Round %s)' % dtm.get('round_number', '?')
                    stat['as_of'] = (dtm.get('reporting_date', '') or '')[:10]
            payload['live_dtm'] = True
            payload['dtm_detail'] = dtm
        rw = fetch_reliefweb_drc()
        payload['reliefweb_reports'] = rw.get('reports', [])
        payload['reliefweb_error'] = rw.get('error')
        payload['seasonal_calendar'] = _calendar_state()
        payload['so_what'] = _build_so_what(payload['live_dtm'], payload['seasonal_calendar'])
        _redis_set(CACHE_KEY, payload)
        return payload


def register_drc_humanitarian_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/africa/humanitarian/drc', methods=['GET'])
    def drc_humanitarian():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        try:
            return jsonify(build_drc_humanitarian(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200], 'fallback': STATIC_BASELINE}), 500

    @app.route('/debug/drc-humanitarian', methods=['GET'])
    def debug_drc_humanitarian():
        dtm = fetch_dtm_drc()
        rw = fetch_reliefweb_drc(limit=3)
        return jsonify({'module': 'drc_humanitarian v%s' % MODULE_VERSION, 'cache_key': CACHE_KEY,
                        'dtm_api_key_set': bool(DTM_API_KEY), 'dtm_live_pull': dtm,
                        'reliefweb_count': len(rw.get('reports', [])), 'reliefweb_error': rw.get('error'),
                        'redis_wired': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
                        'static_as_of': STATIC_BASELINE['data_as_of'], 'calendar_now': _calendar_state()})

    print('[Africa Backend] ✅ DRC humanitarian endpoints registered')
