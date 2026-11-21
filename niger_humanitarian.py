"""
Asifah Analytics - Niger Humanitarian Pulse (Sensor)
v1.0.0 - November 2026  |  Africa backend

SENSOR module (doctrine: stability pages are dials, not analysts). Raw
displacement, hosting, expulsion, food and access figures for Niger with honest
sourcing and dates. The meaning lives in the rhetoric / BLUF layer.

Cloned from burkina_faso_humanitarian.py, as its CLONE NOTE planned.

WHY NIGER'S CARD IS SHAPED DIFFERENTLY
    Sudan     BIDIRECTIONAL -- mass return alongside new displacement.
    Mali      A SIEGE OF ONE CENTRE (the Bamako fuel blockade).
    Burkina   MOVEMENT IN EVERY DIRECTION, and a population that cannot move.
    Niger     A CROSSROADS. Niger is at once a HOST (more than 436,000 refugees
              and asylum-seekers from Nigeria, Mali, Burkina Faso and further
              afield), a SOURCE (its own displaced in Tillaberi, Tahoua, Diffa
              and Maradi), a TRANSIT country (Agadez, the gateway to Libya and
              Algeria) and a DUMPING GROUND (people expelled from Algeria and
              left at "Point Zero" in the desert near Assamaka).

The headline dial is HOSTING: the share of Niger's displaced who fled someone
else's war. The second is EXPULSIONS INTO ASSAMAKA, because it is the one flow
set by a neighbour's policy rather than by Nigerien conditions -- and Algeria is
now also Niger's newest security patron. The sensor reports both numbers; the
irony is the analyst layer's to draw.

SEASONAL CALENDAR: lean season, flood season (Niger's 2024 floods were among
the worst on record), meningitis season, Harmattan, and the hot season when
desert crossings are deadliest. Facts with dates; the calendar never fires on
its own.

DATA SOURCES:
  * Live   - IOM DTM API v3 (Niger). DTM_API_KEY env var.
  * Live   - ReliefWeb API.
  * Static - attributed baseline so the card ALWAYS renders.

REDIS:   africa:humanitarian:niger  (12h TTL)
ENDPOINTS:
  GET /api/africa/humanitarian/niger            (cache-first)
  GET /api/africa/humanitarian/niger?force=true (bypass cache; no Claude calls)
  GET /debug/niger-humanitarian

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
COUNTRY_SLUG    = 'niger'
COUNTRY_DISPLAY = 'Niger'
DTM_COUNTRY     = 'Niger'
RELIEFWEB_ISO3  = 'ner'

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
# SEASONAL CALENDAR
#
# Facts with dates. The card publishes which windows are OPEN today so a
# reader can weigh every other figure correctly. No forecasting, no scoring --
# a calendar cannot be wrong about what month it is.
# ------------------------------------------------------------------
SEASONAL_CALENDAR = [
    {
        'id': 'lean_season',
        'label': 'Lean season (soudure)',
        'months': [6, 7, 8, 9],
        'window': 'June - September',
        'note': ('The hunger gap between last harvest\'s stocks running out and the '
                 'new harvest. In Tillaberi and Diffa, insecurity has also stopped '
                 'villages planting at all, so the gap there does not close on schedule.'),
        'source': 'FEWS NET / Cadre Harmonise West Africa calendar',
    },
    {
        'id': 'flood_season',
        'label': 'Rainy and flood season',
        'months': [6, 7, 8, 9, 10],
        'window': 'June - October',
        'note': ('Niger\'s rains now bring floods as often as relief: the 2024 floods '
                 'affected more than 1.5 million people. Floods hit the same months as '
                 'the lean season and close the roads aid travels on.'),
        'source': 'OCHA Niger flood reporting',
    },
    {
        'id': 'meningitis_season',
        'label': 'Meningitis belt season',
        'months': [12, 1, 2, 3, 4, 5],
        'window': 'December - May (peaks Feb-April)',
        'note': ('Niger lies in the African meningitis belt. Crowded displacement and '
                 'refugee sites are where seasonal risk becomes an outbreak.'),
        'source': 'WHO African meningitis belt surveillance',
    },
    {
        'id': 'harmattan',
        'label': 'Harmattan',
        'months': [12, 1, 2],
        'window': 'December - February',
        'note': ('Dry, dusty Saharan wind. Meningitis transmission rises under it.'),
        'source': 'Seasonal norms',
    },
    {
        'id': 'desert_heat',
        'label': 'Hot season on the desert routes',
        'months': [4, 5, 6],
        'window': 'April - June',
        'note': ('The deadliest months to cross the Sahara or to be left at Point Zero '
                 'near Assamaka, 15 km from help. Expulsion figures weigh more here.'),
        'source': 'Alarme Phone Sahara / IOM Missing Migrants',
    },
]


def _calendar_state(now=None):
    """Which seasonal windows are OPEN right now. A fact, not a forecast."""
    now = now or datetime.now(timezone.utc)
    month = now.month
    out = []
    for w in SEASONAL_CALENDAR:
        out.append({
            'id': w['id'],
            'label': w['label'],
            'window': w['window'],
            'open': month in w['months'],
            'note': w['note'],
            'source': w['source'],
        })
    open_now = [w['label'] for w in out if w['open']]
    if open_now:
        summary = ('Open this cycle: %s. Read the figures above against these -- '
                   'the same displacement number means something different inside '
                   'the lean season than outside it.' % ', '.join(open_now))
    else:
        summary = ('No seasonal window open this cycle. Figures above are not '
                   'being amplified by the calendar.')
    return {'as_of_month': month, 'windows': out,
            'open_now': open_now, 'summary': summary}


# ------------------------------------------------------------------
# STATIC BASELINE (always-present fallback; update as dashboards publish)
# Every figure attributed. Sensor voice: dials, not diagnosis.
# ------------------------------------------------------------------
STATIC_BASELINE = {
    'data_as_of': '2026-05-17',
    'headline_stats': [
        {'label': 'People in need of assistance',
         'value': 2600000, 'display': '2.6M',
         'source': 'OCHA Niger HNRP 2026 (32 of 63 departments)', 'as_of': '2026'},
        {'label': 'Forcibly displaced (all groups)',
         'value': 1000000, 'display': '1M+',
         'source': 'UNHCR Niger operational update', 'as_of': '2026-03-31'},
        # THE headline dial: Niger as HOST of other countries' wars.
        {'label': 'Refugees & asylum-seekers hosted',
         'value': 436000, 'display': '436K+',
         'source': 'UNHCR Niger operational update', 'as_of': '2026-03-31'},
        # The second dial: a flow set by a neighbour's policy.
        {'label': 'Expelled from Algeria (Jan 18 - May 17)',
         'value': 14602, 'display': '14.6K',
         'source': 'Alarme Phone Sahara, observed at Assamaka', 'as_of': '2026-05-17'},
    ],
    'crossroads_note': ('Niger is a host, a source, a transit country and a dumping ground '
                        'at once. More than 436,000 refugees and asylum-seekers -- from '
                        'Nigeria, Mali, Burkina Faso, Chad, Sudan and beyond -- live '
                        'alongside Niger\'s own displaced: over 1 million forcibly '
                        'displaced people in all. In Tahoua alone UNHCR counts 80,475 '
                        'refugees, 65,892 IDPs and 52,805 asylum-seekers awaiting '
                        'registration. Read any single figure alone and the country is '
                        'misread. (UNHCR, 31 Mar 2026)'),
    'expulsion_note': ('Algeria expelled more than 34,000 people into Niger in 2025, a '
                       'record, and at least 14,602 between 18 January and 17 May 2026. '
                       '"Unofficial" convoys leave people at Point Zero, about 15 km from '
                       'Assamaka, often at night and without water; "official" convoys '
                       'carry mainly Nigeriens on to Arlit. UNHCR recorded 11,752 people '
                       'expelled to Assamaka in Q1 2026. The same neighbour flew fighter '
                       'jets to Niamey after the August 2026 mutiny. (Alarme Phone Sahara '
                       '/ UNHCR)'),
    'transit_note': ('Agadez is the gateway north. In Q1 2026 UNHCR recorded 48,945 people '
                     'in mixed movements there: 15,052 heading to Libya, 12,512 to Algeria '
                     'and 3,086 to Mali; 30,650 left Niger and 18,295 entered. Niger '
                     'repealed its 2015 anti-smuggling law in November 2023, so the route '
                     'is legal again inside Niger. (UNHCR / GI-TOC)'),
    'insecurity_note': ('Tillaberi (the Mali-Burkina border, IS Sahel and JNIM) has the most '
                        'protection incidents: 1,032 schools there were closed by '
                        'insecurity, affecting 89,514 pupils. Diffa (Lake Chad: Boko Haram '
                        'and ISWAP) sees repeated displacement and evictions. Maradi, on '
                        'the Nigeria border, recorded 1,175 protection incidents with 2,423 '
                        'victims in January-June 2025. (OCHA HNRP 2026 / UNHCR)'),
    'famine_note': ('2.2 million people were in crisis-level food insecurity (IPC 3+) at '
                    'the last full analysis, and 412,000 children under five need treatment '
                    'for severe acute malnutrition. 126 localities in Tillaberi and Diffa '
                    'could not plant because of insecurity and dry spells. Read against '
                    'the lean season (June-September). (OCHA HNRP 2026 / IPC)'),
    'funding_note': ('The 2026 humanitarian plan asks for $449 million to reach 1.6 million '
                     'of the 2.6 million in need -- 25% less than 2025, a cut driven by '
                     'donor retrenchment rather than lower need. (OCHA HNRP 2026)'),
    'sources': [
        {'name': 'OCHA Niger HNRP 2026', 'url': 'https://humanitarianaction.info/plan/1513/article/niger-4'},
        {'name': 'UNHCR Niger', 'url': 'https://www.unhcr.org/countries/niger'},
        {'name': 'Alarme Phone Sahara', 'url': 'https://alarmephonesahara.info/en/'},
        {'name': 'IOM DTM Niger', 'url': 'https://dtm.iom.int/niger'},
        {'name': 'ReliefWeb Niger', 'url': 'https://reliefweb.int/country/ner'},
        {'name': 'ACAPS Niger', 'url': 'https://www.acaps.org/en/countries/niger'},
        {'name': 'UNICEF Niger appeal', 'url': 'https://www.unicef.org/appeals/niger'},
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
        print('[Niger Humanitarian] redis get error: %s' % str(e)[:120])
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
        print('[Niger Humanitarian] redis set error: %s' % str(e)[:120])


# ------------------------------------------------------------------
# LIVE SOURCE 1 - IOM DTM API v3
# ------------------------------------------------------------------
def fetch_dtm_niger():
    """
    Country-level (Admin 0) IDP figures for Niger from IOM DTM API v3.
    Returns dict or None. Conservative: only overrides static when a parseable
    figure lands.
    """
    if not DTM_API_KEY:
        print('[Niger DTM] No DTM_API_KEY configured')
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
    }
    try:
        print('[Niger DTM] Fetching country-level IDP data...')
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
            print('[Niger DTM] HTTP %s' % response.status_code)
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            print('[Niger DTM] No data returned')
            return None
        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
        most_recent = latest[0]
        idps = most_recent.get('numPresentIdpInd', 0)
        if not idps:
            return None
        print('[Niger DTM] Country-level: {:,} IDPs (Round {})'.format(
            idps, most_recent.get('roundNumber', '?')))
        return {
            'total_idps':      idps,
            'reporting_date':  most_recent.get('reportingDate', ''),
            'round_number':    most_recent.get('roundNumber', ''),
            'source':          'IOM DTM API v3',
            'fetched_at':      datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print('[Niger DTM] error: %s' % str(e)[:150])
        return None


# ------------------------------------------------------------------
# LIVE SOURCE 2 - ReliefWeb reports
# ------------------------------------------------------------------
def fetch_reliefweb_niger(limit=8):
    """Latest OCHA/UN/NGO reports for Niger from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/%s' % RELIEFWEB_ISO3,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
    }
    try:
        print('[Niger ReliefWeb] Fetching reports...')
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Niger',
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
        print('[Niger ReliefWeb] Found %d reports' % len(result['reports']))
    except Exception as e:
        result['error'] = str(e)[:200]
        print('[Niger ReliefWeb] Error: %s' % str(e)[:150])
    return result


# ------------------------------------------------------------------
# Sensor-voice so_what (the dial named, not diagnosed)
# ------------------------------------------------------------------
def _build_so_what(dtm_live, calendar):
    base = ('Niger is a crossroads, and the dial that shows it is HOSTING: more than '
            '436,000 of the people displaced in Niger fled someone else\'s war, '
            'alongside Niger\'s own displaced -- over 1 million in all. The second '
            'dial is EXPULSIONS: tens of thousands of people a year left in the desert '
            'near Assamaka by Algeria. That flow is set by a neighbour\'s policy, not by '
            'conditions inside Niger.')
    if calendar.get('open_now'):
        base += ' Seasonal windows open this cycle: %s.' % ', '.join(calendar['open_now'])
    if dtm_live:
        return base + ' Displacement figures reflect the latest IOM DTM round.'
    return (base + ' Live DTM round unavailable this cycle -- baseline figures shown '
            'with their dates (absence-honest).')


# ------------------------------------------------------------------
# Payload assembly
# ------------------------------------------------------------------
def build_niger_humanitarian(force=False):
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            return cached

    with _hum_lock:
        payload = json.loads(json.dumps(STATIC_BASELINE))  # deep copy
        payload['country'] = COUNTRY_SLUG
        payload['country_display'] = COUNTRY_DISPLAY
        payload['module']  = 'niger_humanitarian'
        payload['version'] = MODULE_VERSION
        payload['live_dtm'] = False
        payload['cached'] = False
        payload['generated_at'] = datetime.now(timezone.utc).isoformat()

        dtm = fetch_dtm_niger()
        if dtm and dtm.get('total_idps'):
            for stat in payload['headline_stats']:
                if stat['label'].startswith('Forcibly displaced'):
                    stat['value'] = dtm['total_idps']
                    stat['display'] = '{:,}'.format(dtm['total_idps'])
                    stat['source'] = ('IOM DTM API v3 (Round %s)'
                                      % dtm.get('round_number', '?'))
                    stat['as_of'] = (dtm.get('reporting_date', '') or '')[:10]
            payload['live_dtm'] = True
            payload['dtm_detail'] = dtm

        rw = fetch_reliefweb_niger()
        payload['reliefweb_reports'] = rw.get('reports', [])
        payload['reliefweb_error']   = rw.get('error')

        payload['seasonal_calendar'] = _calendar_state()
        payload['so_what'] = _build_so_what(payload['live_dtm'],
                                            payload['seasonal_calendar'])

        _redis_set(CACHE_KEY, payload)
        return payload


# ------------------------------------------------------------------
# Endpoint registration
# ------------------------------------------------------------------
def register_niger_humanitarian_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/africa/humanitarian/niger', methods=['GET'])
    def niger_humanitarian():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        try:
            return jsonify(build_niger_humanitarian(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200],
                            'fallback': STATIC_BASELINE}), 500

    @app.route('/debug/niger-humanitarian', methods=['GET'])
    def debug_niger_humanitarian():
        """Raw source statuses for deploy verification."""
        dtm = fetch_dtm_niger()
        rw = fetch_reliefweb_niger(limit=3)
        return jsonify({
            'module':          'niger_humanitarian v%s' % MODULE_VERSION,
            'cache_key':       CACHE_KEY,
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_live_pull':   dtm,
            'reliefweb_count': len(rw.get('reports', [])),
            'reliefweb_error': rw.get('error'),
            'redis_wired':     bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'static_as_of':    STATIC_BASELINE['data_as_of'],
            'calendar_now':    _calendar_state(),
        })

    print('[Africa Backend] ✅ Niger humanitarian endpoints registered')
