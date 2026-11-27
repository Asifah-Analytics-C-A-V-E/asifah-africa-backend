"""
Asifah Analytics - Mozambique Humanitarian Pulse (Sensor)
v1.0.0 - November 2026  |  Africa backend

SENSOR module (doctrine: stability pages are dials, not analysts). Cloned from
rwanda_humanitarian.py.

WHY MOZAMBIQUE'S CARD IS SHAPED THIS WAY
    DRC        A war and an epidemic in the same provinces.
    Rwanda     A host and a gateway.
    Mozambique AN INSURGENCY THAT MOVES PEOPLE, ON A CYCLONE COAST. The Islamic
               State insurgency in Cabo Delgado (since 2017) has displaced about
               1.3 million people; about 660,000 remain displaced. Each new wave
               of attacks (Muidumbe, Macomia, Montepuez in late 2026) moves a few
               thousand more, while cyclones, floods and cholera hit the same
               coast every rainy season.

The headline dial is STILL DISPLACED BY THE INSURGENCY. The notes record the
latest wave, the LNG-and-security geography, the rainy-season stack (cyclones,
floods, cholera) and the funding cliff. The sensor reports; the reading
belongs to the analyst layer.

DATA SOURCES:
  * Live   - IOM DTM API v3 (Mozambique has regular DTM rounds; a parseable
             national IDP figure is shown BESIDE the static dial, never over it,
             because DTM and UNHCR count differently).
  * Live   - ReliefWeb API.
  * Static - attributed baseline so the card ALWAYS renders.

REDIS:   africa:humanitarian:mozambique  (12h TTL)
ENDPOINTS:
  GET /api/africa/humanitarian/mozambique            (cache-first)
  GET /api/africa/humanitarian/mozambique?force=true (bypass cache; no Claude calls)
  GET /debug/mozambique-humanitarian

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
COUNTRY_SLUG    = 'mozambique'
COUNTRY_DISPLAY = 'Mozambique'
DTM_COUNTRY     = 'Mozambique'
RELIEFWEB_ISO3  = 'moz'

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
        'id': 'rains_cyclones',
        'label': 'Rainy and cyclone season',
        'months': [11, 12, 1, 2, 3, 4],
        'window': 'November - April',
        'note': ('Cyclones and floods hit the coast most years (Idai and Kenneth, 2019; Freddy, 2023; three '
                 'cyclones and floods in early 2026). Roads to the north close and displacement sites flood.'),
        'source': 'INAM / INGD / OCHA',
    },
    {
        'id': 'cholera',
        'label': 'Cholera season',
        'months': [12, 1, 2, 3, 4],
        'window': 'December - April',
        'note': ('Cases rose above 100 a day in early 2026 during the floods; 9,092 cases and 86 deaths from '
                 'September 2025 to June 2026, mostly in Nampula, Tete and Cabo Delgado.'),
        'source': 'Ministry of Health via Club of Mozambique (10 Jun 2026)',
    },
    {
        'id': 'dry_season',
        'label': 'Dry season (road access)',
        'months': [5, 6, 7, 8, 9, 10],
        'window': 'May - October',
        'note': ('Roads in Cabo Delgado are passable; troops and insurgents both move more freely. The June 2026 '
                 'battle for the Catupa base in Macomia fell in this window.'),
        'source': 'Zitamar News / ACLED Cabo Ligado',
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
        # THE headline dial.
        {'label': 'Still displaced by the insurgency',
         'value': 661532, 'display': '661.5K',
         'source': 'UNHCR operational report, Jan-Jun 2026 (about 1.3M displaced since 2017; 721,691 returned)',
         'as_of': '2026-06-30'},
        {'label': 'Newly displaced, latest wave (21 Sep - 27 Oct 2026)',
         'value': 7029, 'display': '7,029',
         'source': 'IOM, via Lusa (Muidumbe attacks)', 'as_of': '2026-10-27'},
        {'label': 'In displacement sites, Cabo Delgado',
         'value': 205000, 'display': '205K+',
         'source': 'IOM (84 resettlement and host sites; over half children)', 'as_of': '2026-10-27'},
        {'label': 'Cholera cases (Sep 2025 - Jun 2026)',
         'value': 9092, 'display': '9,092',
         'source': 'Ministry of Health (86 deaths)', 'as_of': '2026-06-06'},
    ],
    'insurgency_note': ('Since the June 2026 battle for the Catupa base in Macomia, the defence forces have looked '
                        'increasingly passive and the insurgents have spread south and west: at least 22 people '
                        'killed in Muidumbe and Mueda in late October and early November (Islamic State claimed '
                        '14, calling them Christians), raids around Chai and Litamanda on the N380, and a group that '
                        'roamed Montepuez for two months and reached Niassa. The Local Force militia reports '
                        'ammunition shortages and late pay. (Zitamar News, 10 Nov 2026)'),
    'security_note': ('More than 6,300 Rwandan troops are in Cabo Delgado (Rwanda, Apr 2026), three times the '
                      '2021 deployment, guarding the Palma-Mocímboa coast where the LNG projects sit. EU European '
                      'Peace Facility money (about €40M) ran out in May 2026; Mozambique secured funds to keep '
                      'them. Tanzania signed new joint defence protocols in October 2026. Attacks are moving away '
                      'from the guarded coast -- "the war outside the fence". (allAfrica, 8 Apr 2026; Zitamar)'),
    'climate_health_note': ('Three cyclones and floods in early 2026 damaged homes and harvests across the centre '
                            'and north; cholera passed 100 cases a day at the peak. A new rainy season begins in '
                            'November. (OCHA; Ministry of Health)'),
    'funding_note': ('Food aid reached only about 40% of people in need during the 2025 wave; UNHCR\'s 2025 '
                     'appeal was about half funded and it asks $38.2M for 2026. Some families return to unsafe '
                     'districts because support runs out. (OCHA / UNHCR)'),
    'sources': [
        {'name': 'UNHCR Mozambique data portal', 'url': 'https://data.unhcr.org/en/country/moz'},
        {'name': 'RTP / Lusa: 1.3 million displaced since 2017 (30 Oct 2026)', 'url': 'https://www.rtp.pt/noticias/mundo/mocambique-violencia-armada-provocou-13-milhoes-de-deslocados-desde-2017_n1775536'},
        {'name': 'RTP / Lusa: 7,000+ fled new attacks in a month (Oct 2026)', 'url': 'https://www.rtp.pt/noticias/mundo/mocambique-mais-de-7-000-pessoas-fugiram-de-novos-ataques-num-mes_n1777017'},
        {'name': 'Zitamar News: The war outside the fence (10 Nov 2026)', 'url': 'https://www.zitamar.com/the-war-outside-the-fence/'},
        {'name': 'allAfrica: Over 6,300 Rwandan troops in northern Mozambique (Apr 2026)', 'url': 'https://allafrica.com/stories/202604090027.html'},
        {'name': 'Club of Mozambique: cholera cases declining (Jun 2026)', 'url': 'https://clubofmozambique.com/news/mozambique-cholera-cases-declining-but-transmission-persists-in-16-regions/'},
        {'name': 'ACLED Mozambique Conflict Monitor (Cabo Ligado)', 'url': 'https://acleddata.com/monitor/mozambique-conflict-monitor-cabo-ligado'},
        {'name': 'ReliefWeb Mozambique', 'url': 'https://reliefweb.int/country/moz'},
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
        print('[Mozambique Humanitarian] redis get error: %s' % str(e)[:120])
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
        print('[Mozambique Humanitarian] redis set error: %s' % str(e)[:120])


# ------------------------------------------------------------------
# LIVE SOURCE 1 - IOM DTM API v3
# ------------------------------------------------------------------
def fetch_dtm_mozambique():
    """
    Country-level (Admin 0) figures for Mozambique from IOM DTM API v3.
    Returns dict or None. Conservative: only overrides static when a parseable
    figure lands.
    """
    if not DTM_API_KEY:
        print('[Mozambique DTM] No DTM_API_KEY configured')
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
    }
    try:
        print('[Mozambique DTM] Fetching country-level IDP data...')
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
            print('[Mozambique DTM] HTTP %s' % response.status_code)
            return None
        data = response.json()
        if not data or not isinstance(data, list):
            print('[Mozambique DTM] No data returned')
            return None
        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
        most_recent = latest[0]
        idps = most_recent.get('numPresentIdpInd', 0)
        if not idps:
            return None
        print('[Mozambique DTM] Country-level: {:,} IDPs (Round {})'.format(
            idps, most_recent.get('roundNumber', '?')))
        return {
            'total_idps':      idps,
            'reporting_date':  most_recent.get('reportingDate', ''),
            'round_number':    most_recent.get('roundNumber', ''),
            'source':          'IOM DTM API v3',
            'fetched_at':      datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print('[Mozambique DTM] error: %s' % str(e)[:150])
        return None


# ------------------------------------------------------------------
# LIVE SOURCE 2 - ReliefWeb reports
# ------------------------------------------------------------------
def fetch_reliefweb_mozambique(limit=8):
    """Latest OCHA/UN/NGO reports for Mozambique from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/%s' % RELIEFWEB_ISO3,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
    }
    try:
        print('[Mozambique ReliefWeb] Fetching reports...')
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Mozambique',
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
        print('[Mozambique ReliefWeb] Found %d reports' % len(result['reports']))
    except Exception as e:
        result['error'] = str(e)[:200]
        print('[Mozambique ReliefWeb] Error: %s' % str(e)[:150])
    return result


# ------------------------------------------------------------------
# Sensor-voice so_what (the dial named, not diagnosed)
# ------------------------------------------------------------------
def _build_so_what(dtm_live, calendar):
    base = ('An insurgency that moves people, on a cyclone coast: about 661,500 people remain displaced by the '
            'Cabo Delgado war (UNHCR, mid-2026), and each new wave of attacks -- 7,029 people in five weeks to 27 '
            'October 2026 -- adds more, now away from the guarded LNG coast.')
    if calendar.get('open_now'):
        base += ' Seasonal windows open this cycle: %s.' % ', '.join(calendar['open_now'])
    return base + ' Figures are the latest published, shown with their dates (absence-honest).'


def build_mozambique_humanitarian(force=False):
    if not force:
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            return cached
    with _hum_lock:
        payload = json.loads(json.dumps(STATIC_BASELINE))
        payload.update(country=COUNTRY_SLUG, country_display=COUNTRY_DISPLAY,
                       module='mozambique_humanitarian', version=MODULE_VERSION, live_dtm=False,
                       cached=False, generated_at=datetime.now(timezone.utc).isoformat())
        # DTM shown BESIDE the static UNHCR dial, never over it: the two count differently.
        dtm = fetch_dtm_mozambique()
        if dtm and dtm.get('total_idps'):
            payload['headline_stats'].insert(1, {
                'label': 'Internally displaced, national (IOM DTM)',
                'value': dtm['total_idps'], 'display': '{:,}'.format(dtm['total_idps']),
                'source': 'IOM DTM API v3 (Round %s)' % dtm.get('round_number', '?'),
                'as_of': (dtm.get('reporting_date', '') or '')[:10]})
            payload['live_dtm'] = True
            payload['dtm_detail'] = dtm
        rw = fetch_reliefweb_mozambique()
        payload['reliefweb_reports'] = rw.get('reports', [])
        payload['reliefweb_error'] = rw.get('error')
        payload['seasonal_calendar'] = _calendar_state()
        payload['so_what'] = _build_so_what(payload['live_dtm'], payload['seasonal_calendar'])
        _redis_set(CACHE_KEY, payload)
        return payload


def register_mozambique_humanitarian_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/africa/humanitarian/mozambique', methods=['GET'])
    def mozambique_humanitarian():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        try:
            return jsonify(build_mozambique_humanitarian(force=force))
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200], 'fallback': STATIC_BASELINE}), 500

    @app.route('/debug/mozambique-humanitarian', methods=['GET'])
    def debug_mozambique_humanitarian():
        dtm = fetch_dtm_mozambique()
        rw = fetch_reliefweb_mozambique(limit=3)
        return jsonify({'module': 'mozambique_humanitarian v%s' % MODULE_VERSION, 'cache_key': CACHE_KEY,
                        'dtm_api_key_set': bool(DTM_API_KEY), 'dtm_live_pull': dtm,
                        'reliefweb_count': len(rw.get('reports', [])), 'reliefweb_error': rw.get('error'),
                        'redis_wired': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
                        'static_as_of': STATIC_BASELINE['data_as_of'], 'calendar_now': _calendar_state()})

    print('[Africa Backend] ✅ Mozambique humanitarian endpoints registered')
