"""
Asifah Analytics - Burkina Faso Humanitarian Pulse (Sensor)
v1.0.0 - October 2026  |  Africa backend

SENSOR module (doctrine: stability pages are dials, not analysts). Emits RAW
displacement, siege, education and food-security figures for Burkina Faso with
honest sourcing and data_as_of dates. The analyst meaning lives in the rhetoric
/ BLUF layer.

Built as the clone mali_humanitarian.py's CLONE NOTE anticipated: same shape,
same Redis idiom, same absence-honesty, different constants and a different
headline mechanism.

WHY THIS CARD IS SHAPED DIFFERENTLY FROM SUDAN'S AND MALI'S
    Sudan     BIDIRECTIONAL -- mass return alongside new displacement.
    Mali      A SIEGE OF ONE CENTRE -- the JNIM fuel blockade strangles Bamako,
              so the dial is the blockade and IDP stock is context.
    Burkina   MOVEMENT IN EVERY DIRECTION AT ONCE, and one population that
              cannot move at all.

Four flows run simultaneously here, and reading any one of them alone gets the
country wrong:

    2.1 million   still displaced inside the country
    1.14 million  RETURNEES (31 Oct 2025) -- a flow the government counts as
                  success; this module reports the number and nothing more
    ~800,000      inside besieged towns -- the population that cannot move
    ~51,000       Burkinabe who left FOR MALI (Apr-Sep 2025)

The last two are the ones the card leads on.

BESIEGED is the headline dial because it is the only figure that measures
people to whom movement is unavailable -- Djibo has been blockaded since
February 2022, which is longer than most wars. Resupply is by air.

The OUTBOUND flow is the second dial, and it is a comparative measurement
rather than a claim: when a population leaves for Mali, which is itself in
crisis, that is a reading on conditions at home. The sensor reports the flow.
Whether it means what it appears to mean is the analyst layer's problem.

ON THE RETURNEE FIGURE -- deliberate restraint. 1.14 million returns is a real,
counted, sourced number and it appears here as one. Whether those returns are
voluntary, whether the areas returned to are safe, and whether the figure is
being used as a political success metric are ALL analyst-layer questions. A
sensor that editorialised them would be doing the rhetoric tracker's job badly.
The number goes on the dial; the argument goes elsewhere.

SEASONAL CALENDAR (v1.0.0): this module also publishes WHERE IN THE YEAR WE
ARE. The lean season and the meningitis-belt season are facts with dates, not
forecasts, and every other figure on this card means something different
depending on which one is open. Same logic as the Kazakhstan winter multiplier:
the calendar never fires on its own, it tells a reader how to weigh what else
is firing.

CLONE NOTE (Niger next): parameterised at the top -- COUNTRY_ISO3,
COUNTRY_SLUG, DTM country name, ReliefWeb slug, STATIC_BASELINE and
SEASONAL_CALENDAR. A Niger build is a transform of those constants plus new
baseline figures.

DATA SOURCES:
  * Live   - IOM DTM API v3 (Burkina Faso operation). DTM_API_KEY env var.
  * Live   - ReliefWeb API (OCHA/UN/NGO reports).
  * Static - attributed baseline so the card ALWAYS renders. Every figure
             carries source + as_of.

REDIS:
  Cache: africa:humanitarian:burkina_faso  (12h TTL)
  NOTE: rhetoric_tracker_burkina_faso will read this key for its humanitarian
  convergence layer -- emit once, consume many.

ENDPOINTS:
  GET /api/africa/humanitarian/burkina_faso            (cache-first)
  GET /api/africa/humanitarian/burkina_faso?force=true (bypass cache)
  GET /debug/burkina-faso-humanitarian

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import threading
from datetime import datetime, timezone

import requests

# ------------------------------------------------------------------
# Config  (CLONE SURFACE -- change these for Niger)
# ------------------------------------------------------------------
COUNTRY_SLUG    = 'burkina_faso'
COUNTRY_DISPLAY = 'Burkina Faso'
DTM_COUNTRY     = 'Burkina Faso'
RELIEFWEB_ISO3  = 'bfa'

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
        'note': ('The hunger gap between the exhaustion of last year\'s stocks and '
                 'the new harvest. Food-security figures mean something different '
                 'inside this window than outside it, and displacement that '
                 'coincides with it removes a household\'s ability to plant.'),
        'source': 'FEWS NET / FAO West Africa seasonal calendar',
    },
    {
        'id': 'meningitis_season',
        'label': 'Meningitis belt season',
        'months': [12, 1, 2, 3, 4, 5],
        'window': 'December - May (peaks Feb-April)',
        'note': ('Burkina Faso sits in the African meningitis belt. The epidemic '
                 'season runs through the dry, dusty Harmattan months and ends with '
                 'the rains. Crowded displacement sites are the exposure that turns '
                 'a seasonal risk into an outbreak.'),
        'source': 'WHO African meningitis belt surveillance',
    },
    {
        'id': 'rainy_season',
        'label': 'Rainy season',
        'months': [6, 7, 8, 9],
        'window': 'June - September',
        'note': ('Roads to besieged and remote localities degrade or close. For a '
                 'population resupplied by road convoy or air, rainfall is a '
                 'humanitarian access variable, not weather. It overlaps the lean '
                 'season exactly, which is the compounding to watch.'),
        'source': 'Seasonal norms; OCHA access reporting',
    },
    {
        'id': 'harmattan',
        'label': 'Harmattan',
        'months': [12, 1, 2],
        'window': 'December - February',
        'note': ('Dry dust-laden wind off the Sahara. Reduces visibility (relevant '
                 'to air resupply of besieged towns) and is the condition under '
                 'which meningitis transmission rises.'),
        'source': 'Seasonal norms',
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
    'data_as_of': '2026-10-07',
    'headline_stats': [
        {'label': 'People in need of assistance',
         'value': 4500000, 'display': '4.5M',
         'source': 'UNICEF Humanitarian Action for Children 2026',
         'as_of': '2026-early'},
        {'label': 'Internally displaced (IDPs)',
         'value': 2100000, 'display': '2.1M',
         'source': 'ACAPS / IOM DTM Burkina Faso', 'as_of': '2026-04-29'},
        # THE headline dial. The only figure here that measures people to whom
        # movement is unavailable.
        {'label': 'People in besieged towns',
         'value': 800000, 'display': '~800K',
         'source': 'ACAPS -- localities isolated by armed-group encirclement',
         'as_of': '2026'},
        {'label': 'Returnees recorded',
         'value': 1142260, 'display': '1.14M',
         'source': 'UNICEF HAC 2026 (189,453 households)', 'as_of': '2025-10-31'},
    ],
    # The mechanism, named. Read this before any single number.
    'siege_note': ('Roughly 800,000 people live in towns encircled by armed groups '
                   'and cannot leave. Djibo, in Soum province, has been blockaded '
                   'since February 2022 -- longer than most wars run -- and is '
                   'resupplied largely by air. Sebba and Titao have been surrounded '
                   'since 2022 as well. This is a DISTRIBUTED siege: not one '
                   'strangled capital, as in Mali, but dozens of simultaneous '
                   'encirclements across the Sahel, Centre-Nord and Est regions. '
                   'Around 40% of national territory sits outside effective '
                   'government control. (ACAPS / Crisis Group)'),
    'movement_note': ('Four flows run at once and reading any one alone gets the '
                      'country wrong: 2.1 million still displaced; 1.14 million '
                      'recorded as returned; ~800,000 who cannot move at all; and '
                      'roughly 51,000 Burkinabe who crossed INTO Mali between April '
                      'and September 2025. That last flow is a comparative reading '
                      'rather than a claim -- a population leaving for a country in '
                      'its own crisis is a measurement of conditions at home. '
                      '(ACAPS / IOM DTM / UNHCR)'),
    'returns_note': ('1,142,260 returnees across 189,453 households were recorded as '
                     'of 31 October 2025. The figure is reported here as counted. '
                     'Whether returns are voluntary, whether return areas are '
                     'secure, and how the figure is used politically are questions '
                     'for the analyst layer, not for this dial. (UNICEF HAC 2026)'),
    'education_note': ('More than 5,300 schools -- about 20% of the country\'s '
                       'educational infrastructure -- were non-functional, affecting '
                       'over 818,000 children and 24,300 teachers (March 2024). '
                       'Close to 1.9 million children needed educational assistance '
                       'in 2025. School closure is one of the few siege effects that '
                       'is counted precisely, which makes it a usable proxy for '
                       'territorial control. (UNICEF)'),
    'famine_note': ('Food insecurity concentrates in blockaded and conflict-affected '
                    'communes where markets cannot be reached and planting cycles '
                    'have been interrupted. More than 1.3 million children under five '
                    'require nutrition assistance. Figures should be read against the '
                    'lean season (June-September), when stocks from the previous '
                    'harvest are exhausted. (UNICEF / FEWS NET / IPC)'),
    'disease_note': ('Burkina Faso lies in the African meningitis belt; the epidemic '
                     'season runs December-May and peaks February-April. Crowded '
                     'displacement sites are the exposure that converts seasonal risk '
                     'into outbreak. 2.4 million people lack access to safe water, '
                     'which is the standing condition behind waterborne-disease risk. '
                     'Dengue epidemics have recurred in Ouagadougou. (WHO / UNICEF)'),
    'drivers_note': ('JNIM (al-Qaeda aligned) is the primary insurgency across the '
                     'north, east and increasingly the centre; ISGS operates in the '
                     'eastern Liptako-Gourma tri-border area, where its rivalry with '
                     'JNIM produces inter-jihadist fighting; Ansaroul Islam is active '
                     'in Soum. Mass-casualty events against civilians have included '
                     'Solhan (June 2021, 160+), Karma (April 2023, 100+) and '
                     'Barsalogho (August 2024, ~200+). Liptako-Gourma -- the '
                     'Mali-Niger-Burkina tri-border -- is the structural driver '
                     'shared with both neighbours. (ACLED / Crisis Group / HRW)'),
    'funding_note': ('UNICEF alone requires $168.9 million for its 2026 Burkina Faso '
                     'appeal, targeting 2.9 million people including 2.5 million '
                     'children. Sahel appeals have been chronically underfunded '
                     'through the 2025-26 aid-cut cycle, and Burkina Faso is '
                     'routinely described as one of the world\'s most underreported '
                     'humanitarian crises. (UNICEF HAC 2026 / IRC)'),
    'sources': [
        {'name': 'IOM DTM Burkina Faso', 'url': 'https://dtm.iom.int/burkina-faso'},
        {'name': 'OCHA Burkina Faso', 'url': 'https://www.unocha.org/burkina-faso'},
        {'name': 'ACAPS Burkina Faso',
         'url': 'https://www.acaps.org/en/countries/burkina-faso'},
        {'name': 'ReliefWeb Burkina Faso', 'url': 'https://reliefweb.int/country/bfa'},
        {'name': 'UNICEF HAC 2026', 'url': 'https://www.unicef.org/appeals/burkina-faso'},
        {'name': 'IOM Crisis Response Plan 2026',
         'url': 'https://crisisresponse.iom.int/response/burkina-faso-crisis-response-plan-2026'},
        {'name': 'Crisis Group Burkina Faso',
         'url': 'https://www.crisisgroup.org/africa/sahel/burkina-faso'},
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
        print('[Burkina Humanitarian] redis get error: %s' % str(e)[:120])
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
        print('[Burkina Humanitarian] redis set error: %s' % str(e)[:120])


# ------------------------------------------------------------------
# LIVE SOURCE 1 - IOM DTM API v3
# ------------------------------------------------------------------
def fetch_dtm_burkina():
    """
    Country-level (Admin 0) IDP figures for Burkina Faso from IOM DTM API v3.
    Returns dict or None. Conservative: only overrides static when a parseable
    figure lands.
    """
    if not DTM_API_KEY:
        print('[Burkina DTM] No DTM_API_KEY configured')
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
    }
    try:
        print('[Burkina DTM] Fetching country-level IDP data...')
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
            print('[Burkina DTM] HTTP %s' % response.status_code)
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            print('[Burkina DTM] No data returned')
            return None
        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
        most_recent = latest[0]
        idps = most_recent.get('numPresentIdpInd', 0)
        if not idps:
            return None
        print('[Burkina DTM] Country-level: {:,} IDPs (Round {})'.format(
            idps, most_recent.get('roundNumber', '?')))
        return {
            'total_idps':      idps,
            'reporting_date':  most_recent.get('reportingDate', ''),
            'round_number':    most_recent.get('roundNumber', ''),
            'source':          'IOM DTM API v3',
            'fetched_at':      datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print('[Burkina DTM] error: %s' % str(e)[:150])
        return None


# ------------------------------------------------------------------
# LIVE SOURCE 2 - ReliefWeb reports
# ------------------------------------------------------------------
def fetch_reliefweb_burkina(limit=8):
    """Latest OCHA/UN/NGO reports for Burkina Faso from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/%s' % RELIEFWEB_ISO3,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
    }
    try:
        print('[Burkina ReliefWeb] Fetching reports...')
        params = {
            'appname': 'asifah-analytics',
            'query[value]': ('Burkina Faso displacement besieged blockade Djibo '
                             'humanitarian food security'),
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
        print('[Burkina ReliefWeb] Found %d reports' % len(result['reports']))
    except Exception as e:
        result['error'] = str(e)[:200]
        print('[Burkina ReliefWeb] Error: %s' % str(e)[:150])
    return result


# ------------------------------------------------------------------
# Sensor-voice so_what (the dial named, not diagnosed)
# ------------------------------------------------------------------
def _build_so_what(dtm_live, calendar):
    base = ('The dial that matters here is BESIEGED POPULATION, not displacement '
            'stock. Roughly 800,000 people live inside encirclements they cannot '
            'leave, across dozens of simultaneous sieges rather than one strangled '
            'capital -- which is what distinguishes Burkina Faso from Mali. The '
            'second dial is DIRECTION: 2.1 million displaced, 1.14 million recorded '
            'as returned, and tens of thousands leaving for Mali. A country moving '
            'in every direction at once is not described by any single figure.')
    if calendar.get('open_now'):
        base += (' Seasonal windows open this cycle: %s.'
                 % ', '.join(calendar['open_now']))
    if dtm_live:
        return (base + ' IDP figures reflect the latest IOM DTM round.')
    return (base + ' Live DTM round unavailable this cycle -- baseline figures '
            'shown with source dates (absence-honest).')


# ------------------------------------------------------------------
# Payload assembly
# ------------------------------------------------------------------
def build_burkina_humanitarian(force=False):
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            return cached

    with _hum_lock:
        payload = json.loads(json.dumps(STATIC_BASELINE))  # deep copy
        payload['country'] = COUNTRY_SLUG
        payload['country_display'] = COUNTRY_DISPLAY
        payload['module']  = 'burkina_faso_humanitarian'
        payload['version'] = MODULE_VERSION
        payload['live_dtm'] = False
        payload['cached'] = False
        payload['generated_at'] = datetime.now(timezone.utc).isoformat()

        dtm = fetch_dtm_burkina()
        if dtm and dtm.get('total_idps'):
            for stat in payload['headline_stats']:
                if stat['label'].startswith('Internally displaced'):
                    stat['value'] = dtm['total_idps']
                    stat['display'] = '{:,}'.format(dtm['total_idps'])
                    stat['source'] = ('IOM DTM API v3 (Round %s)'
                                      % dtm.get('round_number', '?'))
                    stat['as_of'] = (dtm.get('reporting_date', '') or '')[:10]
            payload['live_dtm'] = True
            payload['dtm_detail'] = dtm

        rw = fetch_reliefweb_burkina()
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
def register_burkina_faso_humanitarian_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/africa/humanitarian/burkina_faso', methods=['GET'])
    def burkina_faso_humanitarian():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        try:
            return jsonify(build_burkina_humanitarian(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200],
                            'fallback': STATIC_BASELINE}), 500

    @app.route('/debug/burkina-faso-humanitarian', methods=['GET'])
    def debug_burkina_faso_humanitarian():
        """Raw source statuses for deploy verification."""
        dtm = fetch_dtm_burkina()
        rw = fetch_reliefweb_burkina(limit=3)
        return jsonify({
            'module':          'burkina_faso_humanitarian v%s' % MODULE_VERSION,
            'cache_key':       CACHE_KEY,
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_live_pull':   dtm,
            'reliefweb_count': len(rw.get('reports', [])),
            'reliefweb_error': rw.get('error'),
            'redis_wired':     bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'static_as_of':    STATIC_BASELINE['data_as_of'],
            'calendar_now':    _calendar_state(),
        })

    print('[Africa Backend] ✅ Burkina Faso humanitarian endpoints registered')
