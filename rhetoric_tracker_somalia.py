"""
Somalia Rhetoric & Pressure Tracker — Asifah Analytics
version: 1.0.0 — July 20, 2026  |  Africa backend (asifah-africa-backend.onrender.com)

Somalia is a JUNCTION, not a country tracker: a crossing-point where three
existing wheels intersect (Turkey / Russia / Bab-el-Mandeb-Houthi) plus an
Israel-Somaliland recognition wildcard. It does two jobs at once:

  JOB 1 — country sensor (front page):
    al-Shabaab tempo, ISIS-Puntland, the federal fracture (expired mandate),
    AUSSOM funding collapse, US/AFRICOM strike cadence.

  JOB 2 — wheel junction (feeds Africa BLUF -> GPI):
    Emits spoke sub-reads for THREE hubs simultaneously —
      * turkey_spoke      — TURKSOM base, drones, naval/hydrocarbon projection
      * russia_spoke      — Horn/Red Sea base ambition (AFRICOM inverse)
      * bab_el_mandeb     — piracy resurgence, Gulf of Aden tempo (Yemen coupling)
      * israel_somaliland — recognition wildcard (Berbera, Turkey angle)

FIRING LOGIC: each spoke emits independently (a lone signal still rides to GPI);
a convergence detector fires LOUD when >=2 wheels light at once (Turkey AND
Russia, or either AND Bab-el-Mandeb) — that's the Africa BLUF headline.

ACTOR MODES:
  al_shabaab + isis_somalia = mode='actor'  (claiming actors; SILENCE is signal)
  everyone else             = mode='tape'   (measure attribution/amplification tempo)

POLARITY: higher = worse, EXCEPT AUSSOM mandate-extension = de-escalatory and
AUSSOM/US withdrawal = escalatory-by-absence. al-Shabaab silence = escalatory.

LANGUAGE: front page English-only (Africa firm rule). Backend detection net is
multilingual (Somali + Arabic keywords, r/Somalia). Net reads what it reads;
page displays English.

EMISSION (emit once, consume many) — writes THREE keys:
  1. rhetoric:somalia:latest                        (own scan cache; front page)
  2. rhetoric:crosstheater:fingerprints['somalia']  (collective; Africa BLUF)
  3. crosstheater:somalia:fingerprint               (canonical; Turkey/Russia hubs)

Endpoint: GET /api/rhetoric/somalia
"""

import os
import json
import threading
import time
import requests
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

# ── Signal interpreter (so_what, red_lines, historical, build_top_signals) ──
# Optional — tracker continues to function if import fails (graceful degradation).
try:
    from somalia_signal_interpreter import (
        interpret_signals as _somalia_interpret_signals,
        build_top_signals as _somalia_build_top_signals,
    )
    _INTERPRETER_AVAILABLE = True
    print("[Somalia Rhetoric] Signal interpreter loaded (incl. build_top_signals v1.0)")
except ImportError as _e:
    print(f"[Somalia Rhetoric] \u26a0\ufe0f  Signal interpreter not available: {_e}")
    _somalia_interpret_signals = None
    _somalia_build_top_signals = None
    _INTERPRETER_AVAILABLE = False

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

# Telegram integration — shared Africa channels via the widened v2.1 gate.
try:
    from telegram_signals_africa import fetch_telegram_for_target
    TELEGRAM_AVAILABLE = True
    print("[Somalia Rhetoric] \u2705 Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Somalia Rhetoric] \u26a0\ufe0f Telegram signals not available — RSS only")

# Bluesky integration — optional
try:
    from bluesky_signals_africa import fetch_bluesky_for_target
    BLUESKY_AVAILABLE = True
    print("[Somalia Rhetoric] \u2705 Bluesky signals available")
except ImportError:
    BLUESKY_AVAILABLE = False

RHETORIC_CACHE_KEY  = 'rhetoric:somalia:latest'
RHETORIC_CACHE_TTL  = 13 * 3600  # 13h -- covers 12h scan cycle + 1h buffer
LASTGOOD_KEY        = 'rhetoric:somalia:lastgood'
LASTGOOD_TTL        = 7 * 24 * 3600  # 7d ceiling (BLUF cold-start resilience)
HISTORY_KEY         = 'rhetoric:somalia:history'

# Cross-worker scan lock (gunicorn --workers 2 double-fire fix)
SCAN_LOCK_KEY       = 'rhetoric:somalia:scanlock'
SCAN_LOCK_TTL       = 600  # 10 min

REDDIT_USER_AGENT = 'AsifahAnalytics/1.0 (OSINT research; asifahanalytics.com)'

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ACTORS  (7 — the junction model)
# ============================================
ACTORS = {
    'federal_govt': {
        'name': 'Federal Government (Villa Somalia)',
        'flag': '\U0001F1F8\U0001F1F4',  # 🇸🇴
        'color': '#2563eb',
        'role': 'Governing Authority',
        'mode': 'tape',
    },
    'member_states': {
        'name': 'Federal Member States (Puntland / Jubaland)',
        'flag': '\U0001F3DB\uFE0F',  # 🏛️
        'color': '#0891b2',
        'role': 'Federal Fracture',
        'mode': 'tape',
    },
    'al_shabaab': {
        'name': 'Al-Shabaab',
        'flag': '\U0001F7E9',  # 🟩
        'color': '#166534',
        'role': 'Insurgency (claiming)',
        'mode': 'actor',   # SILENCE IS THE SIGNAL
    },
    'isis_somalia': {
        'name': 'ISIS-Somalia',
        'flag': '\U0001F3F4',  # 🏴
        'color': '#111827',
        'role': 'Insurgency / IS finance node',
        'mode': 'actor',
    },
    'aussom': {
        'name': 'AUSSOM / AU Mission',
        'flag': '\U0001F535',  # 🔵
        'color': '#1d4ed8',
        'role': 'Security Floor',
        'mode': 'tape',   # polarity-inverted: withdrawal = escalation
    },
    'us_africom': {
        'name': 'US / AFRICOM',
        'flag': '\U0001F1FA\U0001F1F8',  # 🇺🇸
        'color': '#1e40af',
        'role': 'Counter-terror / Russia-wheel inverse',
        'mode': 'tape',
    },
    'foreign_patrons': {
        'name': 'Foreign Patrons (Turkey / UAE / Ethiopia / Egypt)',
        'flag': '\U0001F30D',  # 🌍
        'color': '#b45309',
        'role': 'Wheel Junction',
        'mode': 'tape',   # Turkey + Russia spoke fingerprints computed here
    },
}


# ============================================
# ESCALATION LADDER (canonical 0-5 palette)
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Monitoring',      'color': '#6b7280'},
    1: {'label': 'Rhetoric',        'color': '#3b82f6'},
    2: {'label': 'Tension',         'color': '#f59e0b'},
    3: {'label': 'Confrontation',   'color': '#f97316'},
    4: {'label': 'Incident',        'color': '#ef4444'},
    5: {'label': 'Active Conflict', 'color': '#7c3aed'},
}


# ============================================
# ACTOR KEYWORDS  (multilingual detection net)
# ============================================
ACTOR_KEYWORDS = {
    'federal_govt': [
        'villa somalia', 'federal government of somalia', 'hassan sheikh',
        'hassan sheikh mohamud', 'somali president', 'somalia president',
        'somali prime minister', 'hamza abdi barre', 'mogadishu government',
        'somali national army', 'sna somalia', 'nisa somalia',
        'somali federal', 'ministry of defence somalia', 'somali cabinet',
        'dowladda federaalka', 'madaxweynaha soomaaliya',  # Somali
        'الحكومة الصومالية', 'مقديشو',  # Arabic
    ],
    'member_states': [
        'puntland', 'jubaland', 'galmudug', 'hirshabelle', 'south west state',
        'said deni', 'ahmed madobe', 'puntland forces', 'jubaland forces',
        'federal member state', 'member states somalia', 'somali federalism',
        'garowe', 'kismayo', 'baidoa', 'dhusamareb',
        'puntland darawish', 'jubbaland',  # variants
        'بونتلاند', 'جوبالاند',  # Arabic
    ],
    'al_shabaab': [
        'al-shabaab', 'al shabaab', 'shabaab', 'harakat al-shabaab',
        'al-shabab', 'shabab somalia', 'amniyat', 'al-shabaab claimed',
        'al-shabaab attack', 'al-shabaab fighters', 'al-shabaab militants',
        'mahad karate', 'fuad shongole', 'shabaab commander',
        'shabaab statement', 'shabaab spokesman', 'shabaab media',
        'خارجی', 'الشباب', 'حركة الشباب',  # Arabic
        'shabaab oo qaaday',  # Somali "shabaab carried out"
    ],
    'isis_somalia': [
        'isis somalia', 'islamic state somalia', 'is somalia', 'isis-somalia',
        'daesh somalia', 'cal miskaad', 'cal-miskaad', 'al-miskaad',
        'bari region', 'puntland isis', 'islamic state puntland',
        'al-karrar', 'is finance', 'isis finance hub',
        'abdiqadir mumin', 'mumin isis',
        'داعش الصومال', 'الدولة الإسلامية الصومال',  # Arabic
    ],
    'aussom': [
        'aussom', 'au support and stabilization mission', 'african union mission somalia',
        'au mission somalia', 'atmis', 'amisom', 'african union somalia',
        'unsos', 'un support office somalia', 'peacekeepers somalia',
        'au troops somalia', 'resolution 2719', 'aussom funding',
        'aussom withdrawal', 'aussom mandate', 'burundi troops somalia',
        'uganda troops somalia', 'au peacekeeping somalia',
    ],
    'us_africom': [
        'africom', 'us africa command', 'us airstrike somalia', 'us strike somalia',
        'us forces somalia', 'us military somalia', 'mq-9 somalia', 'reaper somalia',
        'us drone somalia', 'jsoc somalia', 'us special operations somalia',
        'danab', 'danab brigade', 'us somalia', 'american airstrike somalia',
        'pentagon somalia', 'us troops somalia', 'us counterterrorism somalia',
    ],
    'foreign_patrons': [
        # Turkey
        'turkey somalia', 'turkish somalia', 'turksom', 'turkey base somalia',
        'turkish drones somalia', 'bayraktar somalia', 'tika somalia',
        'turkey somalia defense', 'turkish military somalia', 'erdogan somalia',
        'turkey offshore somalia', 'turkish petroleum somalia', 'oruc reis somalia',
        # UAE / Gulf
        'uae somalia', 'emirates somalia', 'abu dhabi somalia', 'dp world berbera',
        'uae berbera', 'gulf states somalia', 'qatar somalia',
        # Ethiopia
        'ethiopia somalia', 'ethiopian troops somalia', 'ethiopia somaliland',
        'abiy somalia', 'addis ababa somalia', 'ethiopia berbera',
        # Egypt
        'egypt somalia', 'egyptian troops somalia', 'egypt deploy somalia',
        'cairo somalia', 'egypt somalia military',
        # Russia (thin — watch-tier; Sudan is thicker)
        'russia somalia', 'russian somalia', 'moscow somalia', 'wagner somalia',
        'russia red sea base', 'russia horn of africa',
        'تركيا الصومال', 'الإمارات الصومال', 'إثيوبيا الصومال',  # Arabic
    ],
}


# ============================================
# KEYWORD TRIGGERS — vectors
# ============================================

# Vector 1: SHABAAB — insurgency tempo. mode='actor': high level = loud claim;
# the SILENCE detector separately flags unusual quiet.
SHABAAB_TRIGGERS = {
    5: [  # Active Conflict — major operation / Mogadishu penetration
        'mogadishu siege', 'shabaab enters mogadishu', 'shabaab overruns',
        'shabaab captures town', 'shabaab seizes', 'shabaab takes control',
        'complex attack mogadishu', 'shabaab offensive', 'shabaab advance',
        'presidential palace attack', 'villa somalia attack',
        'قصر الرئاسة',  # Arabic "presidential palace"
    ],
    4: [  # Incident — confirmed attack claimed
        'shabaab claimed', 'al-shabaab claimed responsibility', 'shabaab car bomb',
        'shabaab vbied', 'shabaab suicide', 'shabaab ied', 'shabaab ambush',
        'shabaab killed', 'shabaab attack', 'shabaab raid', 'shabaab stormed',
        'hotel attack mogadishu', 'checkpoint attack',
        'تبنى الهجوم',  # "claimed the attack"
    ],
    3: [  # Confrontation — direct threat / massing
        'shabaab threatens', 'shabaab vows', 'shabaab warns', 'shabaab massing',
        'shabaab regroup', 'shabaab counteroffensive', 'shabaab tax',
        'shabaab checkpoint', 'shabaab controls', 'shabaab stronghold',
    ],
    2: [  # Tension — activity / propaganda uptick
        'shabaab propaganda', 'shabaab statement', 'shabaab video',
        'shabaab recruitment', 'shabaab finance', 'shabaab extortion',
        'shabaab presence', 'shabaab territory',
    ],
    1: [  # Rhetoric — baseline mention
        'shabaab', 'al-shabaab', 'al shabaab',
    ],
}

# Vector 2: ISIS-Somalia — Puntland/Cal-Miskaad node, IS finance hub
ISIS_TRIGGERS = {
    5: [
        'isis offensive somalia', 'islamic state seizes', 'isis captures somalia',
    ],
    4: [
        'isis claimed somalia', 'isis attack somalia', 'isis killed somalia',
        'islamic state attack somalia', 'isis fighters somalia',
    ],
    3: [
        'isis threatens somalia', 'isis expands somalia', 'isis finance hub',
        'al-karrar', 'isis foreign fighters somalia', 'cal miskaad operation',
    ],
    2: [
        'isis presence somalia', 'isis puntland', 'islamic state puntland',
        'isis recruitment somalia', 'isis media somalia',
    ],
    1: [
        'isis somalia', 'islamic state somalia', 'daesh somalia',
    ],
}

# Vector 3: FEDERAL FRACTURE — the mandate/federalism rupture (Villa Somalia
# vs member states). Higher = deeper rupture.
FRACTURE_TRIGGERS = {
    5: [  # Active Conflict — armed federal confrontation / collapse
        'federal forces clash', 'puntland jubaland clash', 'armed standoff somalia',
        'state collapse somalia', 'somalia constitutional crisis', 'parallel government',
        'jubaland federal clash', 'somalia fragmentation',
    ],
    4: [  # Incident — recognition withdrawn / boycott
        'puntland withdraws recognition', 'jubaland breaks', 'boycott election somalia',
        'member states reject', 'puntland rejects federal', 'jubaland rejects',
        'somalia election standoff', 'mandate expired', 'term extension somalia',
    ],
    3: [  # Confrontation — open dispute
        'puntland federal dispute', 'jubaland tension', 'federal member states reject',
        'somalia electoral dispute', 'constitutional amendment dispute',
        'one person one vote dispute', 'niebc dispute',
    ],
    2: [  # Tension — friction
        'federal tension somalia', 'member state friction', 'somalia power struggle',
        'clan tension somalia', 'electoral tension somalia',
    ],
    1: [
        'somali federalism', 'federal member state', 'somalia election',
    ],
}

# Vector 4: AUSSOM — POLARITY INVERTED. Withdrawal/funding-collapse = ESCALATION.
# Mandate extension / funding secured = de-escalation (handled in DIPLOMATIC).
AUSSOM_TRIGGERS = {
    5: [  # Active Conflict — collapse / abrupt withdrawal
        'aussom collapse', 'aussom withdrawal', 'au troops withdraw somalia',
        'peacekeepers withdraw somalia', 'aussom pullout', 'mission collapse somalia',
        'security vacuum somalia',
    ],
    4: [  # Incident — funding crisis acute
        'aussom funding crisis', 'aussom unfunded', 'us blocks aussom',
        'us blocks un funding somalia', 'aussom faces collapse', 'unsos closure',
        'aussom cannot pay', 'troops unpaid somalia',
    ],
    3: [  # Confrontation — drawdown pressure
        'aussom drawdown', 'aussom reduction', 'atmis drawdown', 'troop reduction somalia',
        'aussom mandate expiry', 'aussom uncertainty',
    ],
    2: [  # Tension
        'aussom funding debate', 'aussom review', 'peacekeeping funding somalia',
    ],
    1: [
        'aussom', 'au mission somalia', 'peacekeepers somalia',
    ],
}

# Vector 5: AFRICOM / US strike tempo. High cadence = elevated kinetic environment.
AFRICOM_TRIGGERS = {
    5: [
        'major us operation somalia', 'us ground operation somalia',
        'us raid somalia', 'us special forces raid somalia',
    ],
    4: [
        'us airstrike somalia', 'africom airstrike', 'us strike killed',
        'us drone strike somalia', 'africom conducts strike', 'us bombing somalia',
    ],
    3: [
        'us forces target', 'africom targets', 'us military operation somalia',
        'us counterterrorism strike',
    ],
    2: [
        'us military somalia', 'africom somalia', 'us support somalia forces',
    ],
    1: [
        'us somalia', 'africom', 'american forces somalia',
    ],
}

# Vector 6: FOREIGN PATRONS — the wheel junction. Sub-tagged by hub in the
# classifier so turkey_spoke / russia_spoke fingerprints can be computed.
PATRON_TRIGGERS = {
    5: [  # Active — base established / direct military projection
        'establishes base', 'establish base somalia', 'russia base somalia',
        'foreign base somalia', 'troops deploy somalia', 'deploy somalia',
        'turksom base', 'base in somalia',
    ],
    4: [  # Incident — major agreement / deployment
        'defense pact', 'defence pact', 'drones somalia', 'drones to somalia',
        'bayraktar', 'berbera deal', 'berbera base', 'somaliland mou',
        'offshore somalia', 'turkish petroleum', 'petroleum somalia',
        'red sea base', 'wagner', 'naval base', 'military agreement somalia',
    ],
    3: [  # Confrontation — competition / friction
        'turkey ethiopia rivalry', 'uae ethiopia somalia', 'gulf rivalry somalia',
        'turkey egypt somalia', 'foreign competition somalia', 'proxy competition somalia',
    ],
    2: [  # Tension — presence / investment
        'turkey investment somalia', 'uae investment somalia', 'foreign influence somalia',
        'turksom', 'tika somalia', 'gulf states somalia',
    ],
    1: [
        'turkey somalia', 'uae somalia', 'ethiopia somalia', 'egypt somalia',
    ],
}

# Vector 7: SOMALILAND RECOGNITION — the Israel wildcard + Berbera + Turkey angle.
SOMALILAND_TRIGGERS = {
    5: [  # Active — formal recognition / basing
        'recognizes somaliland', 'somaliland recognition', 'israel recognizes somaliland',
        'us recognizes somaliland', 'somaliland statehood recognized',
    ],
    4: [  # Incident — recognition move / base deal
        'israel somaliland', 'somaliland israel', 'berbera base', 'somaliland base deal',
        'somaliland ethiopia port', 'ethiopia somaliland recognition',
        'us somaliland recognition debate', 'somaliland sea access',
    ],
    3: [  # Confrontation — recognition push
        'somaliland recognition push', 'somaliland independence push',
        'somaliland diplomatic', 'somaliland lobbying', 'somaliland sovereignty',
    ],
    2: [  # Tension
        'somaliland talks', 'somaliland status', 'somaliland autonomy',
        'somaliland election', 'hargeisa',
    ],
    1: [
        'somaliland', 'somaliland government',
    ],
}

# Vector 8: MARITIME / BAB-EL-MANDEB — piracy resurgence + Gulf of Aden tempo.
# Couples to the Yemen maritime vector (dual-chokepoint).
MARITIME_TRIGGERS = {
    5: [
        'ship hijacked somalia', 'vessel seized somalia', 'tanker seized gulf of aden',
        'pirates seize', 'hijacked off somalia',
    ],
    4: [
        'somali pirates attack', 'piracy attack gulf of aden', 'vessel attacked somalia',
        'pirates board', 'attempted hijacking somalia',
    ],
    3: [
        'piracy resurgence', 'somali piracy return', 'gulf of aden risk',
        'shipping threat somalia', 'pirates active',
    ],
    2: [
        'maritime security somalia', 'gulf of aden patrol', 'eunavfor atalanta',
        'shipping advisory somalia', 'red sea somalia',
    ],
    1: [
        'somali coast', 'gulf of aden', 'somali waters',
    ],
}

# Vector 9: DIPLOMATIC / DE-ESCALATION — REDUCES pressure (downward modifier).
# Includes AUSSOM funding SECURED (the inverse of the AUSSOM escalation vector).
DIPLOMATIC_TRIGGERS = {
    5: [  # Major breakthrough
        'somalia peace deal', 'shabaab ceasefire', 'shabaab negotiations',
        'aussom fully funded', 'aussom funding secured',
    ],
    4: [
        'aussom mandate extended', 'aussom mandate renewed', 'un funds aussom',
        'somalia reconciliation', 'puntland rejoins', 'jubaland agreement',
        'somalia election agreement', 'electoral model agreed',
    ],
    3: [
        'somalia talks', 'somalia dialogue', 'federal state dialogue',
        'ankara declaration', 'ethiopia somalia talks', 'turkey mediation somalia',
    ],
    2: [
        'somalia negotiations', 'somalia mediation', 'confidence building somalia',
    ],
    1: [
        'somalia diplomacy', 'somalia cooperation',
    ],
}

# Conditional threats (tripwire framework) — "if X then Y" language
CONDITIONAL_TRIGGERS = {
    3: [
        'if aussom withdraws', 'once peacekeepers leave', 'if funding is cut',
        'should the mission collapse', 'if the mandate expires',
    ],
    2: [
        'if the government', 'should mogadishu', 'unless the international community',
        'if recognition',
    ],
    1: [
        'if ', 'should ', 'unless ', 'in the event',
    ],
}


# ============================================
# SPECIFICITY SCORER
# ============================================
SPECIFIC_GEOGRAPHIES = [
    'mogadishu', 'kismayo', 'baidoa', 'garowe', 'dhusamareb', 'jowhar',
    'beledweyne', 'bosaso', 'galkayo', 'hargeisa', 'berbera',
    'lower shabelle', 'middle shabelle', 'hiiraan', 'hiran', 'gedo',
    'bari region', 'cal miskaad', 'jilib', 'sablaale', 'buulo marer',
    'gulf of aden', 'indian ocean somalia', 'somali coast',
    'villa somalia', 'aden adde airport', 'halane',
]

SPECIFIC_ASSETS = [
    'presidential palace', 'villa somalia', 'parliament building',
    'aden adde', 'halane base', 'un compound', 'au base', 'forward operating base',
    'police academy', 'sna base', 'danab base', 'military convoy',
    'hotel', 'checkpoint', 'district headquarters', 'peacekeeper base',
    'cargo ship', 'oil tanker', 'container ship', 'bulk carrier',
]

TIME_BOUNDED = [
    'within 24 hours', 'within 48 hours', 'within 72 hours',
    'by friday', 'by tomorrow', 'before the end of', 'in the coming hours',
    'imminent', 'within days', 'tonight', 'this week',
]

OPERATIONAL_FRAMING = [
    'preparing to launch', 'positioned to strike', 'coordinated attack',
    'complex attack', 'multi-pronged', 'simultaneous', 'massing forces',
    'encirclement', 'siege', 'infiltration', 'sleeper cell',
]


def _score_specificity(text):
    """Score 0-10 how operationally specific the rhetoric is."""
    score = 0
    breakdown = {
        'named_geographies': [],
        'named_assets': [],
        'time_bounded': [],
        'operational_framing': [],
        'conditional_threats': [],
    }
    for geo in SPECIFIC_GEOGRAPHIES:
        if geo in text:
            breakdown['named_geographies'].append(geo)
            score += 1
    for asset in SPECIFIC_ASSETS:
        if asset in text:
            breakdown['named_assets'].append(asset)
            score += 1
    for tb in TIME_BOUNDED:
        if tb in text:
            breakdown['time_bounded'].append(tb)
            score += 2
    for op in OPERATIONAL_FRAMING:
        if op in text:
            breakdown['operational_framing'].append(op)
            score += 2
    for kw in CONDITIONAL_TRIGGERS.get(3, []):
        if kw in text:
            breakdown['conditional_threats'].append(kw)
            score += 2
    return min(score, 10), breakdown


# ============================================
# TEMPO BASELINE EMITTER (shared Redis bus)
# ============================================
try:
    from tempo_baseline import emit_counts as _tempo_emit
    TEMPO_EMIT_AVAILABLE = True
except ImportError:
    TEMPO_EMIT_AVAILABLE = False
    _tempo_emit = None


# ============================================
# REDIS HELPERS  (command-array pattern — PROVEN on the Africa backend;
# the /set/{key} raw-body variant fails silently here)
# ============================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5
        )
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
    except Exception as e:
        print(f"[Somalia Rhetoric Redis] GET error: {str(e)[:100]}")
    return None


def _redis_set(key, value, ttl=RHETORIC_CACHE_TTL):
    """Upstash REST SET (command-array to base URL).

    v1.0.1 (Jul 23 2026) -- DIAGNOSTIC UPGRADE. Writes were failing silently:
    the scan ran and returned data on ?force=true, but nothing persisted, so a
    normal page load found an empty cache. The old version returned a bare
    False with no reason. This logs the actual HTTP status + response body (and
    catches the classic env-var trap: UPSTASH_REDIS_URL holding a redis://
    connection string instead of the https:// REST URL, which makes
    requests.post raise before it ever reaches Upstash).
    """
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        print("[Somalia Rhetoric Redis] SET skipped -- URL or TOKEN not set")
        return False
    if not UPSTASH_REDIS_URL.startswith('http'):
        print(f"[Somalia Rhetoric Redis] SET ABORT -- UPSTASH_REDIS_URL is not an "
              f"https REST URL (starts with '{UPSTASH_REDIS_URL[:10]}...'). "
              f"Upstash REST needs the https:// endpoint, not a redis:// string.")
        return False
    try:
        payload = ['SET', key, json.dumps(value, default=str)]
        if ttl:
            payload.extend(['EX', str(ttl)])
        resp = requests.post(
            UPSTASH_REDIS_URL,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            json=payload,
            timeout=8,
        )
        if resp.status_code != 200:
            print(f"[Somalia Rhetoric Redis] SET FAILED ({key}): "
                  f"HTTP {resp.status_code} body={resp.text[:160]}")
            return False
        return True
    except Exception as e:
        print(f"[Somalia Rhetoric Redis] SET EXCEPTION ({key}): "
              f"{type(e).__name__}: {str(e)[:140]}")
    return False


def _acquire_scan_lock():
    """Cross-worker lock (Redis SET NX EX) — gunicorn --workers 2 double-fire fix."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return True  # no redis -> single-process assumption, allow
    try:
        resp = requests.post(
            UPSTASH_REDIS_URL,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            json=['SET', SCAN_LOCK_KEY, datetime.now(timezone.utc).isoformat(),
                  'NX', 'EX', str(SCAN_LOCK_TTL)],
            timeout=8,
        )
        return resp.json().get('result') == 'OK'
    except Exception:
        return True  # fail-open: better a double scan than no scan


# ============================================
# RSS SOURCES  (English + Somali-language + recognition/junction feeds)
# ============================================
RHETORIC_RSS_FEEDS = [
    # Core Somalia security
    ("https://news.google.com/rss/search?q=Somalia+al-Shabaab+attack&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Somalia+Mogadishu+government&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Somalia+AUSSOM+funding&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Somalia+election+standoff&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Puntland+Jubaland+federal&hl=en&gl=US&ceid=US:en", 0.85),
    ("https://news.google.com/rss/search?q=ISIS+Somalia+Puntland&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=US+airstrike+Somalia+AFRICOM&hl=en&gl=US&ceid=US:en", 0.95),
    # Junction: Turkey / recognition / maritime
    ("https://news.google.com/rss/search?q=Turkey+Somalia+base+drones&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Somaliland+Israel+recognition&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Somaliland+Ethiopia+Berbera&hl=en&gl=US&ceid=US:en", 0.85),
    ("https://news.google.com/rss/search?q=Somali+piracy+Gulf+of+Aden&hl=en&gl=US&ceid=US:en", 0.9),
    # Somali-language site proxies (Garowe / Hiiraan)
    ("https://news.google.com/rss/search?q=Soomaaliya+Shabaab+OR+dowlad&hl=en&gl=US&ceid=US:en", 0.8),
    # Arabic
    ("https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B5%D9%88%D9%85%D8%A7%D9%84+%D8%A7%D9%84%D8%B4%D8%A8%D8%A7%D8%A8&hl=ar&gl=SA&ceid=SA:ar", 0.85),
]

SOMALIA_SUBREDDITS = ['Somalia', 'HornOfAfrica', 'geopolitics', 'CredibleDefense']
SOMALIA_REDDIT_KEYWORDS = [
    'somalia', 'somaliland', 'shabaab', 'mogadishu', 'puntland', 'jubaland',
    'aussom', 'turksom', 'berbera',
]


def fetch_reddit_somalia(days=3):
    """Fetch Reddit posts from Somalia-relevant subreddits (gated by keyword)."""
    time_filter = 'day' if days <= 1 else ('week' if days <= 7 else 'month')
    query = ' OR '.join(SOMALIA_REDDIT_KEYWORDS[:4])
    posts = []
    for subreddit in SOMALIA_SUBREDDITS:
        try:
            time.sleep(2)
            url = f'https://www.reddit.com/r/{subreddit}/search.json'
            params = {'q': query, 'restrict_sr': 'true', 'sort': 'new',
                      't': time_filter, 'limit': 25}
            resp = requests.get(url, params=params,
                                headers={'User-Agent': REDDIT_USER_AGENT}, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            children = data.get('data', {}).get('children', [])
            count = 0
            for post in children:
                pd = post.get('data', {})
                title = pd.get('title', '')
                text_lower = f"{title} {pd.get('selftext','')}".lower()
                if not any(kw in text_lower for kw in SOMALIA_REDDIT_KEYWORDS):
                    continue
                posts.append({
                    'title': title[:200],
                    'url': f"https://www.reddit.com{pd.get('permalink','')}",
                    'published': datetime.fromtimestamp(
                        pd.get('created_utc', 0), tz=timezone.utc).isoformat(),
                    'description': pd.get('selftext', '')[:300],
                    'source': f'r/{subreddit}',
                    'source_type': 'reddit',
                    'weight': 0.8,
                })
                count += 1
            print(f"[Somalia Rhetoric/Reddit] r/{subreddit}: {count} posts")
        except Exception as e:
            print(f"[Somalia Rhetoric/Reddit] r/{subreddit} error: {str(e)[:80]}")
            continue
    return posts


# ============================================
# ARTICLE FETCHING
# ============================================
def fetch_rhetoric_articles(days=3):
    """Fetch articles from RSS + Reddit + Telegram + Bluesky."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # ── RSS feeds ──
    for feed_url, weight in RHETORIC_RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item'):
                title = item.findtext('title', '')
                url   = item.findtext('link', '')
                pub   = item.findtext('pubDate', '')
                desc  = item.findtext('description', '')
                try:
                    pub_dt = parsedate_to_datetime(pub)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt < since:
                        continue
                    pub_str = pub_dt.isoformat()
                except Exception:
                    pub_str = pub
                articles.append({
                    'title': title,
                    'url': url,
                    'published': pub_str if isinstance(pub_str, str) else '',
                    'description': desc[:300],
                    'source': feed_url.split('q=')[1].split('&')[0] if 'q=' in feed_url else 'RSS',
                    'source_type': 'rss',
                    'weight': weight,
                })
        except Exception as e:
            print(f"[Somalia Rhetoric RSS] Error: {str(e)[:80]}")

    rss_count = len(articles)
    print(f"[Somalia Rhetoric] RSS: {rss_count} articles")

    # ── Reddit ──
    try:
        reddit_posts = fetch_reddit_somalia(days=days)
        articles.extend(reddit_posts)
        print(f"[Somalia Rhetoric] Reddit: {len(reddit_posts)} posts")
    except Exception as e:
        print(f"[Somalia Rhetoric] Reddit error: {str(e)[:80]}")

    # ── Telegram (shared Africa channels via widened gate) ──
    if TELEGRAM_AVAILABLE:
        try:
            tg_messages = fetch_telegram_for_target('somalia', hours_back=days * 24)
            tg_count = 0
            for msg in (tg_messages or []):
                articles.append({
                    'title': (msg.get('text') or msg.get('message') or '')[:200],
                    'url': msg.get('url', ''),
                    'published': msg.get('published', '') or msg.get('date', ''),
                    'description': (msg.get('text') or msg.get('message') or '')[:500],
                    'source': f"Telegram/{msg.get('channel', 'africa')}",
                    'source_type': 'telegram',
                    'weight': 0.75,
                })
                tg_count += 1
            print(f"[Somalia Rhetoric] Telegram: {tg_count} messages")
        except Exception as e:
            print(f"[Somalia Rhetoric] Telegram error: {str(e)[:80]}")

    # ── Bluesky (optional) ──
    if BLUESKY_AVAILABLE:
        try:
            bs_posts = fetch_bluesky_for_target('somalia', hours_back=days * 24)
            bs_count = 0
            for p in (bs_posts or []):
                articles.append({
                    'title': (p.get('text') or '')[:200],
                    'url': p.get('url', ''),
                    'published': p.get('published', '') or p.get('date', ''),
                    'description': (p.get('text') or '')[:500],
                    'source': f"Bluesky/{p.get('handle', 'somalia')}",
                    'source_type': 'bluesky',
                    'weight': 0.7,
                })
                bs_count += 1
            print(f"[Somalia Rhetoric] Bluesky: {bs_count} posts")
        except Exception as e:
            print(f"[Somalia Rhetoric] Bluesky error: {str(e)[:80]}")

    print(f"[Somalia Rhetoric] Total articles: {len(articles)}")
    return articles


# ============================================
# CLASSIFIER
# ============================================
def classify_articles(articles):
    """Classify articles by actor and escalation vector. Also sub-tags the
    foreign-patron hub (turkey / russia / other) so junction fingerprints
    can be computed downstream."""

    actor_results = {
        actor_id: {
            'name': info['name'],
            'flag': info['flag'],
            'color': info['color'],
            'role': info['role'],
            'mode': info['mode'],
            'statement_count': 0,
            'shabaab_score': 0,
            'isis_score': 0,
            'fracture_score': 0,
            'aussom_score': 0,
            'africom_score': 0,
            'patron_score': 0,
            'somaliland_score': 0,
            'maritime_score': 0,
            'diplomatic_score': 0,
            'escalation_level': 0,
            'top_articles': [],
            'escalation_history': [],
        }
        for actor_id, info in ACTORS.items()
    }

    theatre_summary = {
        'shabaab_max': 0, 'isis_max': 0, 'fracture_max': 0,
        'aussom_max': 0, 'africom_max': 0, 'patron_max': 0,
        'somaliland_max': 0, 'maritime_max': 0, 'diplomatic_max': 0,
        'specificity_scores': [],
        'conditional_threats': [],
        'coordination_signals': [],
        # ── Junction hub sub-reads (computed at classify time) ──
        'turkey_signals': [],      # foreign-patron articles tagged Turkey
        'russia_signals': [],      # foreign-patron articles tagged Russia
        'turkey_max': 0,
        'russia_max': 0,
    }

    # Hub sub-tag keyword sets (for junction fingerprint)
    TURKEY_TAGS = ['turkey', 'turkish', 'turksom', 'bayraktar', 'erdogan',
                   'tika', 'ankara', 'oruc reis', 'turkish petroleum']
    RUSSIA_TAGS = ['russia', 'russian', 'moscow', 'wagner', 'kremlin']

    vector_map = [
        ('shabaab_score',    'shabaab_max',    SHABAAB_TRIGGERS),
        ('isis_score',       'isis_max',       ISIS_TRIGGERS),
        ('fracture_score',   'fracture_max',   FRACTURE_TRIGGERS),
        ('aussom_score',     'aussom_max',     AUSSOM_TRIGGERS),
        ('africom_score',    'africom_max',    AFRICOM_TRIGGERS),
        ('patron_score',     'patron_max',     PATRON_TRIGGERS),
        ('somaliland_score', 'somaliland_max', SOMALILAND_TRIGGERS),
        ('maritime_score',   'maritime_max',   MARITIME_TRIGGERS),
    ]

    for article in articles:
        text = f"{article.get('title','')} {article.get('description','')}".lower()
        pub_date = article.get('published', '')

        # Multi-actor match
        matched_actors = []
        for aid in ACTORS:
            for kw in ACTOR_KEYWORDS.get(aid, []):
                if kw.lower() in text:
                    matched_actors.append(aid)
                    break

        # ── THEATRE-WIDE vectors: maritime (piracy), Somaliland (recognition),
        # patron (foreign projection), and diplomatic are phenomena that no
        # single actor "claims" -- score them on EVERY article, matched or not,
        # so a Gulf-of-Aden hijacking or a recognition move still lights the
        # junction even when it names no tracked actor. ──
        for level in range(5, 0, -1):
            for kw in MARITIME_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['maritime_max']:
                    theatre_summary['maritime_max'] = level
            for kw in SOMALILAND_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['somaliland_max']:
                    theatre_summary['somaliland_max'] = level
            for kw in PATRON_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['patron_max']:
                    theatre_summary['patron_max'] = level
            for kw in DIPLOMATIC_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['diplomatic_max']:
                    theatre_summary['diplomatic_max'] = level

        if not matched_actors:
            # No tracked actor, but theatre vectors above may still have fired
            # (piracy/recognition). Continue to the next article -- the
            # junction sub-tagging below needs a matched patron actor.
            continue

        for actor_id in matched_actors:
            actor_results[actor_id]['statement_count'] += 1

        # Score each vector against each matched actor
        for actor_id in matched_actors:
            ar = actor_results[actor_id]
            for level in range(5, 0, -1):
                for score_field, max_field, triggers in vector_map:
                    for kw in triggers.get(level, []):
                        if kw in text:
                            if level > ar[score_field]:
                                ar[score_field] = level
                                ar['escalation_history'].append({
                                    'timestamp': pub_date if isinstance(pub_date, str) else '',
                                    'level': level,
                                    'vector': score_field.replace('_score', ''),
                                    'phrase': kw,
                                })
                            if level > theatre_summary[max_field]:
                                theatre_summary[max_field] = level
                            break

                # Diplomatic (de-escalation) — tracked separately
                for kw in DIPLOMATIC_TRIGGERS.get(level, []):
                    if kw in text:
                        if level > ar['diplomatic_score']:
                            ar['diplomatic_score'] = level
                        if level > theatre_summary['diplomatic_max']:
                            theatre_summary['diplomatic_max'] = level
                        break

            # Actor's headline escalation level = max across escalatory vectors
            ar['escalation_level'] = max(
                ar['shabaab_score'], ar['isis_score'], ar['fracture_score'],
                ar['aussom_score'], ar['africom_score'], ar['patron_score'],
                ar['somaliland_score'], ar['maritime_score'],
            )

        # ── Junction hub sub-tagging (theatre-wide; patron_max already scored
        # above regardless of actor match) ──
        patron_lvl = theatre_summary['patron_max']
        if any(t in text for t in TURKEY_TAGS):
            theatre_summary['turkey_max'] = max(theatre_summary['turkey_max'], patron_lvl)
            if len(theatre_summary['turkey_signals']) < 6:
                theatre_summary['turkey_signals'].append({
                    'title': article.get('title', '')[:120],
                    'level': patron_lvl,
                    'published': pub_date if isinstance(pub_date, str) else '',
                })
        if any(t in text for t in RUSSIA_TAGS):
            theatre_summary['russia_max'] = max(theatre_summary['russia_max'], patron_lvl)
            if len(theatre_summary['russia_signals']) < 6:
                theatre_summary['russia_signals'].append({
                    'title': article.get('title', '')[:120],
                    'level': patron_lvl,
                    'published': pub_date if isinstance(pub_date, str) else '',
                })

        # ── Specificity + conditional threats (once per article) ──
        if matched_actors and actor_results[matched_actors[0]]['statement_count'] >= 0:
            spec_score, spec_breakdown = _score_specificity(text)
            article['_specificity_score'] = spec_score
            if spec_score > 0:
                theatre_summary['specificity_scores'].append(spec_score)
            for level in range(3, 0, -1):
                for kw in CONDITIONAL_TRIGGERS.get(level, []):
                    if kw in text:
                        theatre_summary['conditional_threats'].append({
                            'phrase': kw, 'level': level,
                            'article': article.get('title', '')[:100],
                            'published': pub_date if isinstance(pub_date, str) else '',
                            'specificity': spec_score,
                        })
                        break
                else:
                    continue
                break

        # Top articles per actor
        for actor_id in matched_actors:
            ar = actor_results[actor_id]
            if len(ar['top_articles']) < 6 or ar['escalation_level'] >= 3:
                ar['top_articles'].append({
                    'title': article.get('title', '')[:120],
                    'url': article.get('url', ''),
                    'source': article.get('source', 'Unknown'),
                    'source_type': article.get('source_type', 'news'),
                    'published': pub_date if isinstance(pub_date, str) else '',
                    'escalation_level': ar['escalation_level'],
                    'specificity_score': article.get('_specificity_score', 0),
                })

    return actor_results, theatre_summary


# ============================================
# SILENCE ANOMALY DETECTION (mode='actor' only)
# ============================================
def _detect_silence_anomalies(actor_results, baselines):
    """Flag claiming actors (al-Shabaab, ISIS) whose statement count falls
    far below baseline. Silence after tempo = pre-operational signal.
    Threshold: actual < 30% of baseline avg (baseline avg > 3, >=5 scans)."""
    anomalies = []
    try:
        for actor_id, ar in actor_results.items():
            if ACTORS.get(actor_id, {}).get('mode') != 'actor':
                continue  # silence only meaningful for claiming actors
            baseline = baselines.get(actor_id, {})
            avg_statements = baseline.get('avg_statements', 0)
            scans = baseline.get('scans', 0)
            if scans < 5 or avg_statements < 3:
                continue
            actual = ar.get('statement_count', 0)
            if actual < avg_statements * 0.30:
                pct_below = round((1 - actual / avg_statements) * 100)
                info = ACTORS.get(actor_id, {})
                anomalies.append({
                    'actor_id': actor_id,
                    'actor_name': info.get('name', actor_id),
                    'actor_flag': info.get('flag', ''),
                    'expected_statements': round(avg_statements),
                    'actual_statements': actual,
                    'deviation': f'{pct_below}% below baseline',
                    'signal': 'Unusual quiet from a claiming actor — consistent with '
                              'operational security ahead of activity (silence-is-signal)',
                })
                print(f"[Somalia Rhetoric] \U0001F507 Silence anomaly: {actor_id} "
                      f"({actual} vs avg {avg_statements:.1f})")
    except Exception as e:
        print(f"[Somalia Rhetoric] Silence detection error: {str(e)[:80]}")
    return anomalies


# ============================================
# ACTOR BASELINES (rolling, for silence detection)
# ============================================
def _update_actor_baselines(actor_results):
    """Maintain a rolling statement-count baseline per actor for silence
    detection. Absence-honest: accumulates until MIN scans reached."""
    BASELINE_KEY = 'rhetoric:somalia:baselines'
    try:
        baselines = _redis_get(BASELINE_KEY) or {}
        for actor_id, ar in actor_results.items():
            b = baselines.get(actor_id, {'avg_statements': 0, 'scans': 0})
            count = ar.get('statement_count', 0)
            # Exponential-ish rolling mean over scans
            n = b['scans']
            new_avg = (b['avg_statements'] * n + count) / (n + 1) if n < 30 else \
                      (b['avg_statements'] * 0.9 + count * 0.1)
            baselines[actor_id] = {
                'avg_statements': round(new_avg, 2),
                'scans': min(n + 1, 999),
                'last_count': count,
            }
        _redis_set(BASELINE_KEY, baselines, ttl=60 * 24 * 3600)  # 60d
        return baselines
    except Exception as e:
        print(f"[Somalia Rhetoric] Baseline update error: {str(e)[:80]}")
        return {}


# ============================================
# DELTA CALCULATION
# ============================================
def _compute_delta():
    """Compute score/level delta vs the previous history snapshot."""
    try:
        if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
            return None
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/lrange/{HISTORY_KEY}/0/1",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5)
        data = resp.json().get('result', [])
        if not data or len(data) < 2:
            return None
        current = json.loads(data[0])
        previous = json.loads(data[1])
        return {
            'score_delta': current.get('score', 0) - previous.get('score', 0),
            'level_delta': current.get('level', 0) - previous.get('level', 0),
            'previous_score': previous.get('score', 0),
            'previous_ts': previous.get('ts', ''),
        }
    except Exception as e:
        print(f"[Somalia Rhetoric] Delta error: {str(e)[:80]}")
        return None


# ============================================
# CROSS-THEATER / WHEEL-JUNCTION EMISSION
# ============================================
COLLECTIVE_KEY = 'rhetoric:crosstheater:fingerprints'   # Yemen-style shared dict
CANONICAL_KEY  = 'crosstheater:somalia:fingerprint'     # Russia/Turkey hub schema


def _build_junction_reads(result, theatre_summary):
    """Compute the four hub sub-reads that make Somalia a junction."""
    turkey_lvl = theatre_summary.get('turkey_max', 0)
    russia_lvl = theatre_summary.get('russia_max', 0)
    maritime_lvl = theatre_summary.get('maritime_max', 0)
    somaliland_lvl = theatre_summary.get('somaliland_max', 0)

    turkey_signals = theatre_summary.get('turkey_signals', [])
    text_blob = ' '.join(s.get('title', '').lower() for s in turkey_signals)

    turkey_spoke = {
        'level': turkey_lvl,
        'active': turkey_lvl >= 3,
        'channels': {
            'turksom_base':      'turksom' in text_blob or 'base' in text_blob,
            'drones':            'drone' in text_blob or 'bayraktar' in text_blob,
            'naval_hydrocarbon': 'offshore' in text_blob or 'petroleum' in text_blob
                                 or 'oruc reis' in text_blob or 'naval' in text_blob,
        },
        'note': 'Turkey projecting ME->Africa->Gulf via TURKSOM; feeds Turkey wheel',
    }
    russia_spoke = {
        'level': russia_lvl,
        'active': russia_lvl >= 3,
        'channels': {
            'red_sea_base':          'red sea' in text_blob or 'base' in text_blob,
            'africa_corps_adjacency': 'wagner' in text_blob or 'africa corps' in text_blob,
        },
        'note': 'Horn/Red Sea ambition; AFRICOM inverse; feeds Russia wheel (watch-tier, thin)',
    }
    bab_el_mandeb = {
        'level': maritime_lvl,
        'active': maritime_lvl >= 3,
        'note': 'Piracy resurgence + Gulf of Aden tempo; couples to Yemen maritime vector',
    }
    israel_somaliland = {
        'level': somaliland_lvl,
        'recognition_signal': somaliland_lvl >= 4,
        'note': 'Recognition wildcard; Berbera; Turkey mediation angle',
    }
    return turkey_spoke, russia_spoke, bab_el_mandeb, israel_somaliland


def _detect_wheel_convergence(turkey_spoke, russia_spoke, bab_el_mandeb, israel_somaliland):
    """LOUD signal when >=2 wheels light at once. This is the Africa BLUF
    headline case (convergence, not prediction)."""
    active = []
    if turkey_spoke['active']:
        active.append('Turkey')
    if russia_spoke['active']:
        active.append('Russia')
    if bab_el_mandeb['active']:
        active.append('Bab-el-Mandeb')
    if israel_somaliland.get('recognition_signal'):
        active.append('Israel-Somaliland')

    converged = len(active) >= 2
    return {
        'converged': converged,
        'active_wheels': active,
        'wheel_count': len(active),
        'headline': (
            f"Multi-wheel convergence at the Somalia junction: {', '.join(active)} "
            f"pressure co-occurring — the pattern that historically precedes "
            f"a Horn realignment window."
            if converged else ''
        ),
        'disclaimer': 'This is a CONVERGENCE indicator, NOT a probability of action.',
    }


def _write_crosstheater_signal(result, theatre_summary):
    """Triple emission (emit once, consume many):
      1. collective dict  rhetoric:crosstheater:fingerprints['somalia']  (Africa BLUF)
      2. canonical key    crosstheater:somalia:fingerprint               (hubs)
    (Key 0, rhetoric:somalia:latest, is written by the scan orchestrator.)"""
    try:
        turkey_spoke, russia_spoke, bab_el_mandeb, israel_somaliland = \
            _build_junction_reads(result, theatre_summary)
        convergence = _detect_wheel_convergence(
            turkey_spoke, russia_spoke, bab_el_mandeb, israel_somaliland)

        theatre_level = result.get('theatre_escalation_level', 0)
        actors = result.get('actors', {})
        actor_levels = {aid: actors.get(aid, {}).get('escalation_level', 0)
                        for aid in ACTORS}

        # Silence read (al-Shabaab is the marquee)
        silence = result.get('silence_anomalies', [])
        shabaab_silent = any(a['actor_id'] == 'al_shabaab' for a in silence)

        # ── Key 1: collective dict (Africa BLUF consumes) ──
        existing = _redis_get(COLLECTIVE_KEY) or {}
        existing['somalia'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Somalia / Horn of Africa',
            'level': theatre_level,
            'score': result.get('rhetoric_score', 0),
            'theatre_score': result.get('rhetoric_score', 0),
            'node_class': 'junction',
            'actor_levels': actor_levels,
            'shabaab_silent': shabaab_silent,
            'turkey_spoke': turkey_spoke,
            'russia_spoke': russia_spoke,
            'bab_el_mandeb': bab_el_mandeb,
            'israel_somaliland': israel_somaliland,
            'wheel_convergence': convergence,
            'top_phrases': [s.get('title', '')[:60]
                            for s in theatre_summary.get('turkey_signals', [])[:3]],
        }
        _redis_set(COLLECTIVE_KEY, existing, ttl=14 * 3600)

        # ── Key 2: canonical per-country fingerprint (Turkey/Russia hubs read) ──
        canonical = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'country': 'somalia',
            'node_class': 'junction',
            'level': theatre_level,
            'vector_levels': {
                'shabaab':    theatre_summary.get('shabaab_max', 0),
                'isis':       theatre_summary.get('isis_max', 0),
                'fracture':   theatre_summary.get('fracture_max', 0),
                'aussom':     theatre_summary.get('aussom_max', 0),
                'patron':     theatre_summary.get('patron_max', 0),
                'maritime':   theatre_summary.get('maritime_max', 0),
                'somaliland': theatre_summary.get('somaliland_max', 0),
            },
            'actor_levels': actor_levels,
            'turkey_spoke': turkey_spoke,
            'russia_spoke': russia_spoke,
            'bab_el_mandeb': bab_el_mandeb,
            'israel_somaliland': israel_somaliland,
            'wheel_convergence': convergence,
            'shabaab_silent': shabaab_silent,
        }
        _redis_set(CANONICAL_KEY, canonical, ttl=14 * 3600)

        print(f"[Somalia Rhetoric] \u2705 Junction fingerprint written "
              f"(collective + canonical); wheels active: "
              f"{convergence['active_wheels'] or 'none'}")
        return convergence
    except Exception as e:
        print(f"[Somalia Rhetoric] Cross-theater write error: {str(e)[:120]}")
        return {'converged': False, 'active_wheels': [], 'wheel_count': 0}


def _detect_crosstheater_coordination():
    """Read sibling hub fingerprints and flag if Somalia's junction wheels are
    ALSO lit elsewhere (e.g. Turkey firing in ME + Africa simultaneously).
    Surface-only; the GPI synthesizes globally."""
    try:
        signals = []
        # Turkey global read
        turkey_fp = _redis_get('crosstheater:turkey:fingerprint')
        if turkey_fp and isinstance(turkey_fp, dict):
            if turkey_fp.get('level', 0) >= 3:
                signals.append({
                    'hub': 'turkey',
                    'note': 'Turkey hub elevated globally while Somalia Turkey-spoke active '
                            '— consistent with coordinated ME->Africa projection',
                    'hub_level': turkey_fp.get('level', 0),
                })
        # Russia global read
        russia_fp = _redis_get('crosstheater:russia:fingerprint')
        if russia_fp and isinstance(russia_fp, dict):
            if russia_fp.get('level', 0) >= 3:
                signals.append({
                    'hub': 'russia',
                    'note': 'Russia hub elevated globally; Somalia Horn ambition reads as '
                            'one rim of a wider posture',
                    'hub_level': russia_fp.get('level', 0),
                })
        return signals
    except Exception as e:
        print(f"[Somalia Rhetoric] Coordination detect error: {str(e)[:80]}")
        return []


# ============================================
# SCAN ORCHESTRATOR
# ============================================
def run_somalia_rhetoric_scan(days=3):
    """Full Somalia rhetoric scan. Writes cache + triple emission."""
    print(f"[Somalia Rhetoric] Starting scan ({days}-day window)...")

    articles = fetch_rhetoric_articles(days)
    actor_results, theatre_summary = classify_articles(articles)

    # Escalatory theatre level = max across escalatory vectors (diplomacy excluded)
    max_shabaab    = theatre_summary['shabaab_max']
    max_isis       = theatre_summary['isis_max']
    max_fracture   = theatre_summary['fracture_max']
    max_aussom     = theatre_summary['aussom_max']
    max_africom    = theatre_summary['africom_max']
    max_patron     = theatre_summary['patron_max']
    max_somaliland = theatre_summary['somaliland_max']
    max_maritime   = theatre_summary['maritime_max']
    theatre_escalation_level = max(
        max_shabaab, max_isis, max_fracture, max_aussom,
        max_africom, max_patron, max_somaliland, max_maritime,
    )

    spec_scores = theatre_summary.get('specificity_scores', [])
    theatre_specificity = round(sum(spec_scores) / len(spec_scores), 1) if spec_scores else 0

    # ══════════════════════════════════════════════════════════════
    # NUANCED RHETORIC SCORE (0-100)
    #   Insurgency (Shabaab) weighted highest — it IS Somalia's signal.
    #   Fracture + AUSSOM-collapse are the state-fragility axis.
    #   Patron/junction adds cross-theater pressure.
    #   Diplomatic track REDUCES (AUSSOM funded, reconciliation, ceasefire).
    # ══════════════════════════════════════════════════════════════
    score = 0
    score += max_shabaab    * 8    # max 40 — primary
    score += max_fracture   * 4    # max 20 — state fragmentation
    score += max_aussom     * 4    # max 20 — security-floor collapse (inverted vector)
    score += max_isis       * 3    # max 15
    score += max_maritime   * 2    # max 10 — chokepoint coupling
    score += max_patron     * 2    # max 10 — junction pressure
    score += max_africom    * 1    # max 5  — kinetic environment
    score += max_somaliland * 1    # max 5  — recognition wildcard
    score = min(score, 80)

    # Hot actor bonus
    hot_actors = sum(1 for ar in actor_results.values()
                     if ar.get('escalation_level', 0) >= 3)
    score += min(hot_actors * 4, 12)

    # Wheel-convergence bonus (computed in emission, previewed here)
    turkey_spoke, russia_spoke, bab_el_mandeb, israel_somaliland = \
        _build_junction_reads({'actors': actor_results}, theatre_summary)
    convergence_preview = _detect_wheel_convergence(
        turkey_spoke, russia_spoke, bab_el_mandeb, israel_somaliland)
    if convergence_preview['converged']:
        score += min(convergence_preview['wheel_count'] * 4, 12)

    # Diplomatic modifier (de-escalation REDUCES)
    diplomatic_level = theatre_summary.get('diplomatic_max', 0)
    diplomatic_modifier_map = {0: 0, 1: -1, 2: -3, 3: -6, 4: -10, 5: -15}
    diplomatic_modifier = diplomatic_modifier_map.get(diplomatic_level, 0)
    score += diplomatic_modifier

    rhetoric_score = max(0, min(100, int(score)))

    # Assemble result
    result = {
        'success': True,
        'country': 'somalia',
        'theatre': 'Somalia / Horn of Africa',
        'flag': '\U0001F1F8\U0001F1F4',
        'scan_date': datetime.now(timezone.utc).isoformat(),
        'window_days': days,
        'article_count': len(articles),
        'rhetoric_score': rhetoric_score,
        'theatre_escalation_level': theatre_escalation_level,
        'theatre_label': ESCALATION_LEVELS.get(theatre_escalation_level, {}).get('label', 'Unknown'),
        'theatre_score': rhetoric_score,
        'specificity_score': theatre_specificity,
        'vector_levels': {
            'shabaab': max_shabaab, 'isis': max_isis, 'fracture': max_fracture,
            'aussom': max_aussom, 'africom': max_africom, 'patron': max_patron,
            'somaliland': max_somaliland, 'maritime': max_maritime,
            'diplomatic': diplomatic_level,
        },
        'diplomatic_level': diplomatic_level,
        'diplomatic_modifier': diplomatic_modifier,
        'actors': actor_results,
        'conditional_threats': theatre_summary.get('conditional_threats', [])[:8],
        'crosstheater_coordination': [],
        'disclaimer': 'This composite is a CONVERGENCE indicator, NOT a probability of action.',
    }

    # ── Actor baselines + silence anomalies (mode='actor') ──
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    # ── Tempo emission (corpus-health denominator) ──
    if TEMPO_EMIT_AVAILABLE and _tempo_emit:
        try:
            # mode='actor' for the claiming insurgencies; tape actors emit tempo too
            for actor_id, ar in actor_results.items():
                _tempo_emit(
                    theatre='somalia',
                    actor=actor_id,
                    count=ar.get('statement_count', 0),
                    corpus_total=len(articles),
                    mode=ACTORS[actor_id]['mode'],
                )
        except Exception as _e:
            print(f"[Somalia Rhetoric] Tempo emit failed (non-fatal): {str(_e)[:100]}")

    # ── Interpreter (so_what, red_lines, historical, top_signals) ──
    if _INTERPRETER_AVAILABLE and _somalia_interpret_signals:
        try:
            result['interpretation'] = _somalia_interpret_signals(result)
        except Exception as e:
            print(f"[Somalia Rhetoric] Interpreter error: {str(e)[:120]}")
            result['interpretation'] = {}

    if _INTERPRETER_AVAILABLE and _somalia_build_top_signals:
        try:
            result['top_signals'] = _somalia_build_top_signals(result)
            print(f"[Somalia Rhetoric] Built {len(result['top_signals'])} top_signals for BLUF/GPI")
        except Exception as e:
            print(f"[Somalia Rhetoric] build_top_signals error: {str(e)[:120]}")
            result['top_signals'] = []
    else:
        result['top_signals'] = []

    # ── Save cache + last-known-good ──
    # v1.0.1 (Jul 23 2026): report the write outcome. Scans were returning data
    # to the browser while the cache stayed empty, so a normal (non-force) load
    # found nothing. Redis itself round-trips fine, so the failure is specific
    # to THIS write -- surface it instead of discarding the return value.
    _cache_bytes = len(json.dumps(result, default=str))
    _wrote_cache = _redis_set(RHETORIC_CACHE_KEY, result)
    _wrote_lg    = _redis_set(LASTGOOD_KEY, result, ttl=LASTGOOD_TTL)
    print(f"[Somalia Rhetoric] Cache write: latest={_wrote_cache} "
          f"lastgood={_wrote_lg} payload={_cache_bytes:,}B "
          f"key={RHETORIC_CACHE_KEY}")
    if not _wrote_cache:
        print("[Somalia Rhetoric] \u26A0\uFE0F CACHE WRITE FAILED -- page will show "
              "empty on non-force loads. See the SET FAILED line above for the "
              "HTTP status/body.")
    result['cache_written'] = bool(_wrote_cache)
    result['cache_payload_bytes'] = _cache_bytes

    # ── History snapshot (lpush + ltrim 0/119) ──
    try:
        snapshot = json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(),
            'score': rhetoric_score,
            'level': theatre_escalation_level,
            'label': ESCALATION_LEVELS.get(theatre_escalation_level, {}).get('label', 'Unknown'),
            'shabaab': max_shabaab,
            'fracture': max_fracture,
            'aussom': max_aussom,
            'patron': max_patron,
            'specificity': theatre_specificity,
        })
        if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
            import urllib.parse
            enc = urllib.parse.quote(snapshot, safe='')
            requests.post(f"{UPSTASH_REDIS_URL}/lpush/{HISTORY_KEY}/{enc}",
                          headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=5)
            requests.post(f"{UPSTASH_REDIS_URL}/ltrim/{HISTORY_KEY}/0/119",
                          headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=5)
    except Exception as e:
        print(f"[Somalia Rhetoric] History append error (non-fatal): {str(e)[:80]}")

    result['delta'] = _compute_delta()

    # ── Triple emission (junction fingerprints) ──
    convergence = _write_crosstheater_signal(result, theatre_summary)
    result['wheel_convergence'] = convergence
    result['crosstheater_coordination'] = _detect_crosstheater_coordination()

    print(f"[Somalia Rhetoric] \u2705 Scan complete — score {rhetoric_score}, "
          f"L{theatre_escalation_level} ({result['theatre_label']}), "
          f"{len(articles)} articles")
    return result


# ============================================
# BACKGROUND SCAN + FLASK REGISTRATION
# ============================================
def _bg_rhetoric_scan():
    global _rhetoric_running
    with _rhetoric_lock:
        if _rhetoric_running:
            return
        _rhetoric_running = True
    try:
        if not _acquire_scan_lock():
            print("[Somalia Rhetoric] Another worker holds the scan lock — skipping")
            return
        run_somalia_rhetoric_scan(days=3)
    except Exception as e:
        print(f"[Somalia Rhetoric] Background scan error: {str(e)[:120]}")
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


def _start_periodic_scan(interval_hours=12):
    def loop():
        time.sleep(90)  # boot delay
        while True:
            try:
                _bg_rhetoric_scan()
            except Exception as e:
                print(f"[Somalia Rhetoric] Periodic scan error: {str(e)[:100]}")
            time.sleep(interval_hours * 3600)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print(f"[Somalia Rhetoric] Periodic scan started ({interval_hours}h interval)")


def register_somalia_rhetoric_routes(app, start_background=True):
    """Wire Somalia rhetoric endpoints into the Africa backend."""

    @app.route('/api/rhetoric/somalia', methods=['GET'])
    def somalia_rhetoric():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        if force:
            try:
                return jsonify(run_somalia_rhetoric_scan(days=3))
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)[:200]}), 500
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            cached['from_cache'] = True
            return jsonify(cached)
        # cold: last-known-good, else honest empty
        lg = _redis_get(LASTGOOD_KEY)
        if lg:
            lg['from_cache'] = True
            lg['stale'] = True
            return jsonify(lg)
        return jsonify({'success': False, 'status': 'no_scan_yet',
                        'message': 'No Somalia scan cached. Use ?force=true.'}), 200

    @app.route('/api/rhetoric/somalia/summary', methods=['GET'])
    def somalia_rhetoric_summary():
        cached = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(LASTGOOD_KEY) or {}
        return jsonify({
            'country': 'somalia',
            'rhetoric_score': cached.get('rhetoric_score', 0),
            'theatre_escalation_level': cached.get('theatre_escalation_level', 0),
            'theatre_label': cached.get('theatre_label', 'Unknown'),
            'wheel_convergence': cached.get('wheel_convergence', {}),
            'silence_anomalies': cached.get('silence_anomalies', []),
            'scan_date': cached.get('scan_date', ''),
        })

    @app.route('/api/rhetoric/somalia/history', methods=['GET'])
    def somalia_rhetoric_history():
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/lrange/{HISTORY_KEY}/0/119",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=5)
            data = resp.json().get('result', [])
            history = [json.loads(x) for x in data]
            return jsonify({'country': 'somalia', 'history': history, 'count': len(history)})
        except Exception as e:
            return jsonify({'country': 'somalia', 'history': [], 'error': str(e)[:120]})

    @app.route('/debug/redis-somalia', methods=['GET'])
    def debug_redis_somalia():
        """Definitive Redis round-trip test for the Africa backend.

        Answers, in one call: is the URL a valid https REST endpoint? Does a
        SET actually succeed (status + body)? Does a GET read it back? This
        exists because writes were failing silently across every Africa module
        while the humanitarian card still rendered (it falls back to a static
        baseline, which masked the failure).
        """
        out = {
            'module': 'rhetoric_tracker_somalia',
            'url_set': bool(UPSTASH_REDIS_URL),
            'token_set': bool(UPSTASH_REDIS_TOKEN),
            'url_scheme': (UPSTASH_REDIS_URL.split('://')[0] + '://')
                          if '://' in (UPSTASH_REDIS_URL or '') else 'MISSING/INVALID',
            'url_is_https_rest': bool(UPSTASH_REDIS_URL
                                      and UPSTASH_REDIS_URL.startswith('https')),
            'url_host_masked': (UPSTASH_REDIS_URL.split('://')[-1][:18] + '...')
                               if '://' in (UPSTASH_REDIS_URL or '') else None,
            'token_len': len(UPSTASH_REDIS_TOKEN or ''),
            'cache_key': RHETORIC_CACHE_KEY,
        }
        test_key = 'africa:debug:roundtrip'
        test_val = {'ping': datetime.now(timezone.utc).isoformat()}

        # 1) raw SET
        try:
            r = requests.post(
                UPSTASH_REDIS_URL,
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                json=['SET', test_key, json.dumps(test_val), 'EX', '120'],
                timeout=8,
            )
            out['set_status'] = r.status_code
            out['set_body'] = r.text[:200]
            out['set_ok'] = (r.status_code == 200)
        except Exception as e:
            out['set_status'] = None
            out['set_error'] = f"{type(e).__name__}: {str(e)[:160]}"
            out['set_ok'] = False

        # 2) raw GET back
        try:
            g = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{test_key}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=8,
            )
            out['get_status'] = g.status_code
            out['get_body'] = g.text[:200]
            out['roundtrip_ok'] = (g.status_code == 200
                                   and bool((g.json() or {}).get('result')))
        except Exception as e:
            out['get_status'] = None
            out['get_error'] = f"{type(e).__name__}: {str(e)[:160]}"
            out['roundtrip_ok'] = False

        # 3) LARGE-payload test -- the small ping above proves Redis is healthy,
        #    but the real rhetoric result is a big object. If big writes fail
        #    where small ones succeed, that is the bug.
        try:
            big_val = {'blob': 'x' * 120000, 'note': 'large-payload write test'}
            big_bytes = len(json.dumps(big_val))
            rb = requests.post(
                UPSTASH_REDIS_URL,
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                json=['SET', 'africa:debug:bigblob', json.dumps(big_val), 'EX', '120'],
                timeout=12,
            )
            out['large_write_bytes'] = big_bytes
            out['large_write_status'] = rb.status_code
            out['large_write_body'] = rb.text[:200]
            out['large_write_ok'] = (rb.status_code == 200)
        except Exception as e:
            out['large_write_ok'] = False
            out['large_write_error'] = f"{type(e).__name__}: {str(e)[:160]}"

        # 4) is the real rhetoric cache actually present?
        out['rhetoric_cache_present'] = bool(_redis_get(RHETORIC_CACHE_KEY))
        out['lastgood_present'] = bool(_redis_get(LASTGOOD_KEY))

        if out.get('roundtrip_ok') and not out.get('large_write_ok'):
            out['verdict'] = ('SMALL writes succeed but LARGE writes FAIL -- the '
                              'rhetoric result is too big for this Upstash plan/'
                              'request limit. See large_write_status/body. Fix: '
                              'trim the cached payload (drop full article bodies) '
                              'or raise the Upstash limit.')
            return jsonify(out)

        out['verdict'] = (
            'Redis round-trip OK (small AND large) -- if rhetoric_cache_present is '
            'still false, run ?force=true and read the "[Somalia Rhetoric] Cache '
            'write:" line in the Render log for the real reason'
            if out.get('roundtrip_ok') else
            'Redis WRITE/READ FAILING -- see set_status/set_body/set_error above. '
            'If url_is_https_rest is false, the env var holds a redis:// string '
            'instead of the Upstash https REST URL. If set_status is 401, the '
            'token is wrong or belongs to a different database.'
        )
        return jsonify(out)

    if start_background:
        _start_periodic_scan(interval_hours=12)

    print("[Somalia Rhetoric] \u2705 Routes registered: /api/rhetoric/somalia (+/summary,/history,/debug/redis-somalia)")
