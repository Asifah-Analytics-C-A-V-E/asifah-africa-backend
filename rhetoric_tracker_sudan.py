"""
Sudan Rhetoric & Pressure Tracker — Asifah Analytics
version: 1.0.0 — July 24, 2026  |  Africa backend (asifah-africa-backend.onrender.com)

Sudan is a HUB, not a peripheral country tracker: four wheels plug into Khartoum
(Russia state-level + Wagner/Africa Corps, UAE, Egypt/KSA, Iran/Turkey), and
the war extrudes pressure into two adjacent theatres (Chad-west, South Sudan-
south) plus a contradiction node in Libya-east (where Russia-aligned Haftar
supplies the RSF that Russia-the-state is negotiating around). It does two
jobs at once:

  JOB 1 — country sensor (front page):
    SAF vs RSF war tempo (claim cadence both sides), the Boulos peace track,
    Kordofan escalation (El Obeid siege), El Fasher/Darfur consequences,
    Port Sudan drone campaign, cholera + IPC-5 famine compound.

  JOB 2 — wheel hub (feeds Africa BLUF -> GPI):
    Emits spoke sub-reads for four hubs simultaneously —
      * russia_plug        — Port Sudan naval-base + arms + mining state deal
                             (Africa Corps supply chain replacement for Tartus)
      * uae_axis           — Amdjarass airlift, RSF drones, gold laundering
      * saf_patrons        — Egypt / KSA / Iran / Turkey composite (sub-tagged)
      * spillover_south    — Blue Nile / SPLM-N / Petrodar pipeline
                             (becomes South Sudan's inbound read when built)
      * spillover_west     — Zaghawa villages / Um Baru / Tine (Chad border)
      * libya_haftar_flag  — the wheel-contradiction node (Russia vs. Russia)

FIRING LOGIC: each spoke emits independently (a lone signal still rides to
GPI); a compound-risk detector fires LOUD when the humanitarian layer (Redis
key africa:humanitarian:sudan) AND the kinetic layer AND the commodity layer
(africa:commodity:sudan — gold/gum arabic) tighten together — that's the
Sudan-specific compound the Africa BLUF elevates.

ACTOR MODES:
  saf_burhan + rsf_hemedti = mode='actor'  (claiming actors; SILENCE is signal)
  everyone else            = mode='tape'   (measure attribution/amplification)

POLARITY: higher = worse, EXCEPT peace_track advancement = de-escalatory and
peace_track collapse = escalatory-by-absence. Diplomatic-track signals emit
pressure_type='diplomatic' natively (canonical). The contradiction between
active peace track AND Kordofan siege gets a dedicated top_signal — netting
them would smuggle interpretation into the sensor.

CROSS-WHEEL READ: Russia's Sudan interest has TWO independent plugs (state-
level Port Sudan deal vs. Haftar-arming-the-RSF from Libya-east). The tracker
describes both separately and lets the reader complete the inference about
which plug wins. This is the doctrine's contradiction-flag in action.

LANGUAGE: front page English-only (Africa firm rule). Backend detection net is
multilingual (Arabic keywords throughout).

EMISSION (emit once, consume many) — writes THREE keys:
  1. rhetoric:sudan:latest                       (own scan cache; front page)
  2. rhetoric:crosstheater:fingerprints['sudan'] (collective; Africa BLUF)
  3. crosstheater:sudan:fingerprint              (canonical; Russia hub reads)

CROSS-TRACKER READS (compound risk layer):
  * africa:humanitarian:sudan  (sudan_humanitarian.py — displacement/famine/cholera)
  * africa:commodity:sudan     (commodity_proxy_africa — gold/gum arabic)
  * crosstheater:russia:fingerprint  (Russia hub for wheel-parity awareness)

Endpoint: GET /api/rhetoric/sudan
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
    from sudan_signal_interpreter import (
        interpret_signals as _sudan_interpret_signals,
        build_top_signals as _sudan_build_top_signals,
    )
    _INTERPRETER_AVAILABLE = True
    print("[Sudan Rhetoric] Signal interpreter loaded (incl. build_top_signals v1.0)")
except ImportError as _e:
    print(f"[Sudan Rhetoric] \u26a0\ufe0f  Signal interpreter not available: {_e}")
    _sudan_interpret_signals = None
    _sudan_build_top_signals = None
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
    print("[Sudan Rhetoric] \u2705 Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Sudan Rhetoric] \u26a0\ufe0f Telegram signals not available — RSS only")

# Bluesky integration — optional
try:
    from bluesky_signals_africa import fetch_bluesky_for_target
    BLUESKY_AVAILABLE = True
    print("[Sudan Rhetoric] \u2705 Bluesky signals available")
except ImportError:
    BLUESKY_AVAILABLE = False

# GDELT via the shared gateway — standing rule (Jul 24 2026):
# every NEW tracker wires the gateway at birth. No direct GDELT fallback
# here by design: absent gateway = no GDELT, stated honestly at boot.
try:
    from gdelt_gateway import gdelt_fetch as _gw_gdelt_fetch
    GDELT_AVAILABLE = True
    print("[Sudan Rhetoric] \u2705 GDELT gateway available")
except ImportError:
    GDELT_AVAILABLE = False
    print("[Sudan Rhetoric] \u26a0\ufe0f GDELT gateway not available — no GDELT lane")

# GDELT queries mirror the RSS vocabulary: war tempo (EN + AR), the Russia
# plug, UAE plug, peace track, and the two spillover corridors.
SUDAN_GDELT_QUERIES = [
    ('Sudan RSF SAF offensive',           'eng'),
    ('El Obeid siege Kordofan',           'eng'),
    ('Port Sudan drone strike',           'eng'),
    ('Boulos Sudan peace plan',           'eng'),
    ('Russia Port Sudan naval base',      'eng'),
    ('UAE Sudan RSF arms',                'eng'),
    # Arabic: RSF / SAF / El Obeid siege / peace track
    ('\u0627\u0644\u062f\u0639\u0645 \u0627\u0644\u0633\u0631\u064a\u0639 \u0627\u0644\u062c\u064a\u0634 \u0627\u0644\u0633\u0648\u062f\u0627\u0646\u064a', 'ara'),
    ('\u062d\u0635\u0627\u0631 \u0627\u0644\u0623\u0628\u064a\u0636 \u0643\u0631\u062f\u0641\u0627\u0646', 'ara'),
]

RHETORIC_CACHE_KEY  = 'rhetoric:sudan:latest'
RHETORIC_CACHE_TTL  = 13 * 3600  # 13h -- covers 12h scan cycle + 1h buffer
LASTGOOD_KEY        = 'rhetoric:sudan:lastgood'
LASTGOOD_TTL        = 7 * 24 * 3600  # 7d ceiling (BLUF cold-start resilience)
HISTORY_KEY         = 'rhetoric:sudan:history'

# Cross-worker scan lock (gunicorn --workers 2 double-fire fix)
SCAN_LOCK_KEY       = 'rhetoric:sudan:scanlock'
SCAN_LOCK_TTL       = 600  # 10 min

# Corpus-health guard (Jul 24 2026). An empty or collapsed corpus is a FAILED
# FETCH, not a quiet week. Without this, a feed outage publishes L0 "below
# escalation threshold" over a known-good read -- the tracker hallucinating
# calm from its own outage. (Inverse of the Tempo Baseline Engine's original
# bug, which hallucinated menace from the same cause.)
CORPUS_BASELINE_KEY   = 'rhetoric:sudan:corpus_baseline'
CORPUS_MIN_ABSOLUTE   = 5     # below this, treat as an outage regardless of baseline
CORPUS_DEGRADED_RATIO = 0.40  # below 40% of rolling baseline = degraded, flag it

# Cross-tracker Redis reads (compound-risk layer)
HUMANITARIAN_KEY    = 'africa:humanitarian:sudan'   # shipped Jul 24 2026
COMMODITY_KEY       = 'africa:commodity:sudan'      # commodity_proxy_africa
RUSSIA_HUB_KEY      = 'crosstheater:russia:fingerprint'  # Russia wheel hub

REDDIT_USER_AGENT = 'AsifahAnalytics/1.0 (OSINT research; asifahanalytics.com)'

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ACTOR REGISTRY (9 actors; mode discipline explicit)
# ============================================
ACTORS = {
    'saf_burhan': {
        'name': 'Sudanese Armed Forces (Burhan)',
        'flag': '\U0001F1F8\U0001F1E9',  # 🇸🇩
        'color': '#0e7490',
        'role': 'Claiming state force',
        'mode': 'actor',   # SILENCE IS THE SIGNAL
    },
    'rsf_hemedti': {
        'name': 'Rapid Support Forces (Hemedti) + Tasis parallel gov',
        'flag': '\U0001F7E7',  # 🟧
        'color': '#c2410c',
        'role': 'Claiming paramilitary + state-mimicry',
        'mode': 'actor',   # SILENCE IS THE SIGNAL
    },
    'russia_africa_corps': {
        'name': 'Russia / Africa Corps (Port Sudan plug)',
        'flag': '\U0001F1F7\U0001F1FA',  # 🇷🇺
        'color': '#7f1d1d',
        'role': 'Wheel hub plug (state-level + Wagner remnant)',
        'mode': 'tape',    # deniable at the state level; measured via reporting tempo
    },
    'uae_axis': {
        'name': 'UAE Axis (RSF principal patron)',
        'flag': '\U0001F1E6\U0001F1EA',  # 🇦🇪
        'color': '#b45309',
        'role': 'Denied patronage',
        'mode': 'tape',
    },
    'saf_patrons': {
        'name': 'SAF Patron Composite (Egypt / KSA / Iran / Turkey)',
        'flag': '\U0001F30D',  # 🌍
        'color': '#065f46',
        'role': 'Multi-country patron composite (sub-tagged)',
        'mode': 'tape',
    },
    'peace_track': {
        'name': 'Peace Track (Boulos / Quad / Jeddah)',
        'flag': '\U0001F54A\uFE0F',  # 🕊️
        'color': '#1d4ed8',
        'role': 'Diplomatic off-ramp (de-escalatory polarity)',
        'mode': 'tape',    # emits pressure_type='diplomatic'
    },
    'chad_border': {
        'name': 'Chad Border Spillover (Zaghawa / Um Baru / Tine)',
        'flag': '\U0001F1F9\U0001F1E9',  # 🇹🇩
        'color': '#78716c',
        'role': 'Spillover WEST — sensor, not actor',
        'mode': 'tape',
    },
    'south_sudan_corridor': {
        'name': 'South Sudan Corridor (Blue Nile / SPLM-N / Petrodar)',
        'flag': '\U0001F1F8\U0001F1F8',  # 🇸🇸
        'color': '#4b5563',
        'role': 'Spillover SOUTH — future SS inbound read',
        'mode': 'tape',
    },
    'libya_haftar': {
        'name': 'Libya-Haftar Node (wheel contradiction)',
        'flag': '\U0001F1F1\U0001F1FE',  # 🇱🇾
        'color': '#3f3f46',
        'role': 'Contradiction node: Russia vs. Russia',
        'mode': 'tape',
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
# ACTOR KEYWORDS (multilingual detection net)
# ============================================
ACTOR_KEYWORDS = {
    'saf_burhan': [
        'saf', 'sudanese armed forces', 'sudan army', 'burhan',
        'abdel fattah al-burhan', 'sovereignty council', 'port sudan government',
        'sudan military', 'sudan general staff', 'wali burhan',
        # Arabic
        '\u0627\u0644\u062c\u064a\u0634 \u0627\u0644\u0633\u0648\u062f\u0627\u0646\u064a',   # الجيش السوداني
        '\u0627\u0644\u0628\u0631\u0647\u0627\u0646',                                       # البرهان
        '\u0645\u062c\u0644\u0633 \u0627\u0644\u0633\u064a\u0627\u062f\u0629',              # مجلس السيادة
    ],
    'rsf_hemedti': [
        'rsf', 'rapid support forces', 'hemedti', 'hemetti',
        'mohamed hamdan dagalo', 'dagalo', 'janjaweed',
        # Tasis / parallel government (folded in per scope)
        'tasis', 'tasis alliance', 'tasis sudan', 'nyala government',
        'rsf parallel government', 'rsf civilian authority',
        # Arabic
        '\u0627\u0644\u062f\u0639\u0645 \u0627\u0644\u0633\u0631\u064a\u0639',              # الدعم السريع
        '\u062d\u0645\u064a\u062f\u062a\u064a',                                             # حميدتي
        '\u062a\u0623\u0633\u064a\u0633',                                                   # تأسيس
    ],
    'russia_africa_corps': [
        'africa corps sudan', 'russia sudan', 'russia port sudan',
        'russia naval base sudan', 'russia sudan agreement',
        'russia sudan mining', 'russia sudan gold',
        'wagner sudan', 'prigozhin sudan legacy',
        'russia sudan arms', 'russia sudan air defense',
        'moscow port sudan', 'kremlin sudan',
        # Arabic
        '\u0631\u0648\u0633\u064a\u0627 \u0628\u0648\u0631\u062a\u0633\u0648\u062f\u0627\u0646',  # روسيا بورتسودان
        '\u0631\u0648\u0633\u064a\u0627 \u0627\u0644\u0633\u0648\u062f\u0627\u0646',              # روسيا السودان
    ],
    'uae_axis': [
        'uae sudan', 'emirates sudan', 'uae rsf', 'uae hemedti',
        'amdjarass', 'amjarass', 'am djarass',   # Chad airlift base
        'uae drones sudan', 'uae weapons sudan', 'abu dhabi sudan',
        'dubai gold sudan', 'uae gold laundering', 'mbz sudan',
        # Arabic
        '\u0627\u0644\u0625\u0645\u0627\u0631\u0627\u062a \u0627\u0644\u0633\u0648\u062f\u0627\u0646',  # الإمارات السودان
        '\u0623\u0645\u062f\u062c\u0631\u0627\u0633',                                                  # أمدجراس
    ],
    'saf_patrons': [
        # Egypt (dominant SAF patron)
        'egypt sudan', 'sisi sudan', 'egyptian troops sudan',
        'egypt saf', 'egypt burhan', 'cairo sudan',
        # Saudi Arabia (Jeddah host + SAF backing)
        'saudi sudan', 'ksa sudan', 'jeddah sudan talks',
        'jeddah declaration sudan', 'riyadh sudan',
        # Iran (drones-to-SAF pivot 2024)
        'iran sudan', 'iran drones sudan', 'mohajer sudan',
        'irgc sudan', 'iran embassy sudan reopened',
        # Turkey (bayraktar to SAF)
        'turkey sudan', 'bayraktar sudan', 'ankara sudan',
        'erdogan burhan', 'turkish drones sudan',
        # Arabic
        '\u0645\u0635\u0631 \u0627\u0644\u0633\u0648\u062f\u0627\u0646',      # مصر السودان
        '\u0627\u064a\u0631\u0627\u0646 \u0627\u0644\u0633\u0648\u062f\u0627\u0646',  # ايران السودان
    ],
    'peace_track': [
        'boulos sudan', 'boulos plan', 'massad boulos sudan',
        'quad sudan', 'quad mediation sudan',
        'sudan peace plan', 'sudan peace talks', 'sudan ceasefire talks',
        'sudan truce', 'sudan negotiations',
        'jeddah talks', 'geneva sudan', 'sudan humanitarian pause',
        'sudan roadmap', 'sudan political process',
        'sudan mediation', 'sudan envoy', 'special envoy sudan',
        # Arabic
        '\u0645\u0641\u0627\u0648\u0636\u0627\u062a \u0627\u0644\u0633\u0648\u062f\u0627\u0646',  # مفاوضات السودان
        '\u0647\u062f\u0646\u0629 \u0627\u0644\u0633\u0648\u062f\u0627\u0646',                    # هدنة السودان
    ],
    'chad_border': [
        'chad sudan border', 'sudan chad refugees', 'adre chad',
        'zaghawa villages', 'um baru', 'tine karnoi', 'tine sudan',
        'kernoi', 'rsf chad', 'chad-sudan corridor',
        'chad amdjarass', 'darfur refugees chad',
        # Arabic
        '\u062a\u0634\u0627\u062f \u0627\u0644\u0633\u0648\u062f\u0627\u0646',   # تشاد السودان
    ],
    'south_sudan_corridor': [
        'blue nile south sudan', 'splm-n', 'splm north',
        'malik agar', 'al-hilu', 'abdelaziz al-hilu',
        'petrodar pipeline', 'south sudan pipeline sudan',
        'south sudan oil sudan', 'heglig', 'abyei',
        'rsf south sudan', 'sudan south sudan border',
        # Arabic
        '\u0627\u0644\u0646\u064a\u0644 \u0627\u0644\u0623\u0632\u0631\u0642',   # النيل الأزرق
    ],
    'libya_haftar': [
        'haftar sudan', 'lna sudan', 'haftar rsf', 'lna rsf',
        'libya sudan', 'tobruk sudan', 'benghazi sudan',
        'tri-border sudan libya egypt', 'khadim air base',
        'saddam haftar sudan', 'libya arms sudan',
        # Arabic
        '\u062d\u0641\u062a\u0631 \u0627\u0644\u0633\u0648\u062f\u0627\u0646',   # حفتر السودان
    ],
}


# ============================================
# ESCALATION KEYWORDS (per-vector 0-5 ladders)
# ============================================

# Vector 1: KINETIC — the SAF-vs-RSF war tempo, either side claiming.
KINETIC_TRIGGERS = {
    5: [  # Active Conflict — capital-threat / mass-atrocity / famine-region overrun
        'khartoum falls', 'port sudan falls', 'port sudan overrun',
        'el obeid falls', 'kadugli falls', 'dilling falls',
        'sennar falls', 'kosti falls', 'mass atrocity sudan',
        'chemical weapons sudan', 'ethnic cleansing sudan',
        'saf offensive gezira', 'rsf offensive kordofan',
        'sudan capital under attack',
    ],
    4: [  # Incident — confirmed strike / siege intensifies / drone hit
        'port sudan drone strike', 'nyala airport strike',
        'rsf drone strike', 'saf airstrike killed', 'saf shelling',
        'el obeid siege intensifies', 'kordofan offensive',
        'kadugli under siege', 'dilling shelled',
        'rsf assault', 'saf air raid', 'sudan drone attack',
        'sudan army advance', 'rsf advance',
        # Arabic -- confirmed strike / casualties / advance
        '\u063a\u0627\u0631\u0629 \u062c\u0648\u064a\u0629', '\u0642\u0635\u0641 \u0627\u0644\u0623\u0628\u064a\u0636', '\u0645\u0642\u062a\u0644', '\u0642\u062a\u0644\u0649', '\u062c\u0631\u062d\u0649', '\u0642\u0635\u0641', '\u063a\u0627\u0631\u0629', '\u0647\u062c\u0645\u0627\u062a', '\u0647\u062c\u0648\u0645', '\u062a\u0642\u062f\u0645 \u0645\u064a\u062f\u0627\u0646\u064a', '\u062e\u0633\u0627\u0626\u0631 \u0643\u0628\u064a\u0631\u0629', '\u0637\u0627\u0626\u0631\u0629 \u0645\u0633\u064a\u0631\u0629', '\u0645\u0633\u064a\u0631\u0627\u062a', '\u0627\u0633\u062a\u0647\u062f\u0627\u0641',
    ],
    3: [  # Confrontation — massing / threats / direct escalation language
        'saf massing kordofan', 'rsf reinforcements', 'rsf mobilizing',
        'saf preparing offensive', 'sudan escalation',
        'burhan warns', 'hemedti threatens', 'burhan vows',
        'sudan battle for', 'clash intensifies sudan',
        # Arabic -- threat framing / massing / defection
        '\u064a\u062a\u0639\u0647\u062f', '\u064a\u062a\u0648\u0639\u062f', '\u062f\u062d\u0631', '\u062d\u0634\u062f', '\u062a\u0639\u0632\u064a\u0632\u0627\u062a', '\u062a\u0635\u0639\u064a\u062f', '\u0645\u0639\u0631\u0643\u0629', '\u0627\u0646\u0634\u0642\u0627\u0642', '\u0645\u0646\u0634\u0642',
    ],
    2: [  # Tension — activity uptick, propaganda, positional
        'sudan clashes', 'sudan fighting continues', 'sudan army briefing',
        'rsf statement', 'saf statement', 'sudan skirmish',
        'sudan frontline', 'sudan frontlines',
        # Arabic
        '\u0627\u0634\u062a\u0628\u0627\u0643\u0627\u062a', '\u0645\u0648\u0627\u062c\u0647\u0627\u062a', '\u062c\u0628\u0647\u0629', '\u0628\u064a\u0627\u0646 \u0639\u0633\u0643\u0631\u064a',
    ],
    1: [  # Rhetoric — baseline mention
        'sudan war', 'sudan conflict', 'sudan civil war',
        # Arabic
        '\u0627\u0644\u062d\u0631\u0628 \u0641\u064a \u0627\u0644\u0633\u0648\u062f\u0627\u0646', '\u0627\u0644\u0646\u0632\u0627\u0639 \u0627\u0644\u0633\u0648\u062f\u0627\u0646\u064a',
    ],
}

# Vector 2: RUSSIA PLUG — Port Sudan state deal + Africa Corps supply chain.
# CANONICAL wheel-hub read (fingerprint carries this out to the Russia hub).
RUSSIA_PLUG_TRIGGERS = {
    5: [  # Active — base activation / warship arrival
        'russia warship port sudan', 'russia naval base activated sudan',
        'russian frigate port sudan', 'russian troops port sudan',
        'russia sudan base operational',
    ],
    4: [  # Incident — deal ratified / infrastructure movement
        'russia sudan agreement ratified', 'port sudan agreement signed',
        'russia sudan air defense delivered', 'russia sudan mining concession granted',
        'russia sudan 25-year deal',
    ],
    3: [  # Confrontation — active negotiation / arms flow reported
        'russia sudan negotiation', 'russia sudan talks', 'russia sudan visit',
        'russia sudan arms deal', 'russia sudan military cooperation',
        'moscow sudan minister',
        # Broader: Port Sudan agreement momentum (article headlines rarely use
        # our exact L4 phrasing; catch the general form here)
        'russia port sudan naval base', 'russia sudan naval',
        'russia sudan cooperation', 'russia sudan deal',
        'port sudan base agreement', 'moscow port sudan',
    ],
    2: [  # Tension — reporting reference / analyst mention
        'russia sudan interest', 'russia sudan port', 'africa corps sudan supply',
        'tobruk africa corps sudan', 'russia horn of africa presence',
    ],
    1: [
        'russia sudan', 'moscow sudan', 'africa corps sudan',
        # Arabic
        '\u0631\u0648\u0633\u064a\u0627 \u0627\u0644\u0633\u0648\u062f\u0627\u0646', '\u0645\u0648\u0633\u0643\u0648', '\u0641\u064a\u0644\u0642 \u0623\u0641\u0631\u064a\u0642\u064a\u0627', '\u0641\u0627\u063a\u0646\u0631', '\u0642\u0627\u0639\u062f\u0629 \u0628\u062d\u0631\u064a\u0629',
    ],
}

# Vector 3: UAE AXIS — RSF principal patron. Denied at the state level so
# measured via ATTRIBUTION cadence, not statement cadence.
UAE_AXIS_TRIGGERS = {
    5: [
        'uae direct arming rsf confirmed', 'uae sanctions sudan',
        'uae expelled sudan', 'saf breaks uae ties',
    ],
    4: [
        'uae drones rsf confirmed', 'amdjarass airlift', 'uae wagner sudan',
        'uae gold laundering sudan', 'uae complicit rsf atrocities',
        'un panel of experts uae rsf',
    ],
    3: [
        'uae rsf allegations', 'uae denies rsf', 'saf accuses uae',
        'uae sudan diplomatic dispute', 'uae abu dhabi rsf',
        # Arabic -- attribution / protest tempo
        '\u062f\u0639\u0645 \u0625\u0645\u0627\u0631\u0627\u062a\u064a', '\u0623\u0633\u0644\u062d\u0629 \u0625\u0645\u0627\u0631\u0627\u062a\u064a\u0629', '\u0627\u0644\u062e\u0631\u0637\u0648\u0645 \u062a\u062d\u062a\u062c',
    ],
    2: [
        'uae sudan denial', 'uae humanitarian sudan', 'uae mediation sudan',
        'uae role sudan',
    ],
    1: [
        'uae sudan', 'emirates sudan', 'abu dhabi sudan',
        # Arabic
        '\u0627\u0644\u0625\u0645\u0627\u0631\u0627\u062a', '\u0623\u0628\u0648\u0638\u0628\u064a',
    ],
}

# Vector 4: SAF PATRONS — Egypt / KSA / Iran / Turkey composite. Sub-tagged in
# post-processing so the GPI can read individual patrons if needed.
SAF_PATRON_TRIGGERS = {
    5: [
        'egyptian troops enter sudan', 'iranian drones killed sudan',
        'iranian irgc sudan confirmed', 'egypt f-16 sudan',
    ],
    4: [
        'iran drone strike saf', 'mohajer sudan strike', 'egyptian jets sudan',
        'bayraktar sudan strike', 'iran ambassador sudan reopened',
        'saudi hosts saf leaders',
    ],
    3: [
        'egypt sudan arms', 'iran sudan drones', 'turkey sudan drones',
        'saudi jeddah sudan', 'egypt saf visit', 'ksa saf visit',
        'iran saf coordination',
        # Broader mid-tier patron flows (natural reporting phrasing)
        'cairo sudan', 'irgc sudan', 'iranian irgc sudan',
        'egyptian sudan', 'iranian sudan', 'turkish sudan',
        'saudi arabia sudan', 'egypt supports burhan', 'iran supports saf',
    ],
    2: [
        'egypt supports saf', 'iran supports saf', 'turkey supports saf',
        'saudi mediation sudan', 'saf patron support',
    ],
    1: [
        'egypt sudan', 'saudi sudan', 'iran sudan', 'turkey sudan',
        # Arabic
        '\u0645\u0635\u0631', '\u0627\u0644\u0642\u0627\u0647\u0631\u0629', '\u0627\u0644\u0633\u0639\u0648\u062f\u064a\u0629', '\u0625\u064a\u0631\u0627\u0646', '\u062a\u0631\u0643\u064a\u0627', '\u0623\u0646\u0642\u0631\u0629',
    ],
}

# Vector 5: PEACE TRACK — DIPLOMATIC polarity (higher = MORE mediation activity,
# which is DE-escalatory). The interpreter reads this as pressure_type='diplomatic'.
PEACE_TRACK_TRIGGERS = {
    5: [  # Active — signed ceasefire / provisional agreement
        'sudan ceasefire signed', 'sudan peace agreement signed',
        'sudan truce announced', 'sudan permanent ceasefire',
        'sudan interim government agreed',
    ],
    4: [  # Incident — humanitarian pause / roadmap accepted
        'sudan humanitarian pause', 'sudan roadmap accepted',
        'rsf accepts truce', 'saf accepts truce', 'boulos plan endorsed',
        'quad sudan endorsement',
    ],
    3: [  # Confrontation — active mediation round
        'boulos sudan meeting', 'jeddah talks resume', 'quad mediation active',
        'sudan envoy talks', 'sudan mediation session', 'sudan geneva',
        'sudan diplomatic breakthrough',
    ],
    2: [  # Tension — track active but stalled
        'sudan mediation continues', 'sudan envoy', 'sudan special envoy',
        'sudan peace process', 'sudan political process',
    ],
    1: [
        'sudan peace', 'sudan negotiations', 'sudan mediation',
        # Arabic
        '\u0645\u0641\u0627\u0648\u0636\u0627\u062a', '\u0648\u0633\u0627\u0637\u0629', '\u0645\u0628\u0627\u062d\u062b\u0627\u062a', '\u0645\u0628\u0639\u0648\u062b', '\u0648\u0642\u0641 \u0625\u0637\u0644\u0627\u0642 \u0627\u0644\u0646\u0627\u0631', '\u0647\u062f\u0646\u0629',
    ],
}

# Vector 6: SPILLOVER SOUTH — Blue Nile / SPLM-N / Petrodar. The coupling
# the tracker is born with, per scope (retrofit-as-touched later becomes
# South Sudan's inbound read).
SPILLOVER_SOUTH_TRIGGERS = {
    5: [
        'petrodar pipeline attack', 'south sudan pipeline sudan war',
        'rsf south sudan territory', 'blue nile front open',
    ],
    4: [
        'splm-n advance', 'al-hilu offensive', 'south sudan force majeure',
        'blue nile clashes', 'kadugli splm-n', 'dilling splm-n',
        'sudan south sudan border clash',
    ],
    3: [
        'splm-n threatens', 'blue nile tension', 'al-hilu warns',
        'petrodar pipeline threat', 'south sudan sudan war',
    ],
    2: [
        'blue nile splm-n', 'south sudan sudan border', 'abyei clashes',
    ],
    1: [
        'blue nile sudan', 'splm-n', 'petrodar',
        # Arabic
        '\u0627\u0644\u0646\u064a\u0644 \u0627\u0644\u0623\u0632\u0631\u0642', '\u062c\u0646\u0648\u0628 \u0627\u0644\u0633\u0648\u062f\u0627\u0646', '\u0627\u0644\u062d\u0644\u0648', '\u0623\u0628\u064a\u064a', '\u0647\u062c\u0644\u064a\u062c',
    ],
}

# Vector 7: SPILLOVER WEST — Chad-border corridor.
SPILLOVER_WEST_TRIGGERS = {
    5: [
        'chad-sudan war confirmed', 'chad military intervention sudan',
        'sudan strikes chad', 'saf strikes amdjarass',
    ],
    4: [
        'rsf cross-border chad', 'rsf attacks chad', 'zaghawa massacre',
        'um baru attack', 'tine karnoi attack', 'chad refugees surge',
        'adre displacement wave',
    ],
    3: [
        'chad sudan tension', 'chad amdjarass base', 'rsf incursion chad',
        'chad closes border sudan', 'chad protests sudan',
    ],
    2: [
        'chad sudan border', 'darfur refugees chad', 'adre chad',
    ],
    1: [
        'chad sudan', 'zaghawa',
        # Arabic
        '\u062a\u0634\u0627\u062f', '\u0627\u0644\u0632\u063a\u0627\u0648\u0629', '\u0644\u0627\u062c\u0626\u064a\u0646 \u0633\u0648\u062f\u0627\u0646\u064a\u064a\u0646',
    ],
}

# Vector 8: LIBYA-HAFTAR — the wheel-contradiction node. Higher = more
# Haftar activity supporting RSF (contradicting Russia's state-level plug).
LIBYA_HAFTAR_TRIGGERS = {
    5: [
        'haftar arms rsf confirmed', 'lna forces sudan', 'saf strikes libya arms',
    ],
    4: [
        'haftar rsf supply route', 'lna weapons rsf', 'khadim air base sudan',
        'libya arms sudan flow', 'saddam haftar rsf',
    ],
    3: [
        'haftar sudan', 'lna sudan', 'tri-border sudan libya',
        'benghazi rsf', 'tobruk rsf',
    ],
    2: [
        'libya sudan arms', 'haftar denies rsf', 'lna denies sudan',
    ],
    1: [
        'libya sudan', 'haftar',
        # Arabic
        '\u062d\u0641\u062a\u0631', '\u0644\u064a\u0628\u064a\u0627', '\u0637\u0628\u0631\u0642', '\u0628\u0646\u063a\u0627\u0632\u064a',
    ],
}

# Diplomatic override keywords (apply the DIPLOMATIC pressure_type at
# emission time — canonical native tagging, per architecture).
DIPLOMATIC_MODIFIERS = [
    'boulos', 'quad', 'jeddah', 'geneva', 'mediation', 'envoy',
    'humanitarian pause', 'ceasefire talks', 'peace talks', 'roadmap',
    'diplomatic', 'negotiate', 'negotiation', 'truce', 'political process',
]

# Conditional-threat triggers (for specificity scoring — cross-vector)
CONDITIONAL_TRIGGERS = {
    3: [
        'if saf', 'if rsf', 'should the war', 'if el obeid falls',
        'if khartoum', 'unless ceasefire', 'without agreement',
        'if uae', 'if russia', 'if egypt',
    ],
}


# ============================================
# SPECIFICITY SCORER
# ============================================
SPECIFIC_GEOGRAPHIES = [
    # Sudan proper
    'khartoum', 'omdurman', 'port sudan', 'wad madani', 'sennar', 'kosti',
    'el fasher', 'el-fasher', 'nyala', 'geneina', 'el-geneina',
    'el obeid', 'el-obeid', 'kadugli', 'dilling', 'kauda',
    'atbara', 'kassala', 'gedaref', 'damazin', 'ed daein',
    'kordofan', 'north kordofan', 'south kordofan', 'west kordofan',
    'darfur', 'north darfur', 'south darfur', 'west darfur',
    'blue nile', 'sennar state', 'gezira', 'gezira state',
    'zamzam camp', 'abu shouk', 'zalingei',
    # Border zones + spillover
    'adre', 'tine', 'um baru', 'kernoi', 'amdjarass', 'amjarass',
    'abyei', 'heglig', 'renk', 'raga',
    # Assets / infrastructure
    'petrodar pipeline', 'port sudan port', 'khartoum airport',
    'nyala airport', 'wadi seidna base', 'meroe',
    # Arabic place names -- the corpus is majority Arabic, so an English-only
    # geography list scored every Arabic headline at specificity 0.
    '\u0627\u0644\u062e\u0631\u0637\u0648\u0645', '\u0623\u0645 \u062f\u0631\u0645\u0627\u0646', '\u0628\u0648\u0631\u062a\u0633\u0648\u062f\u0627\u0646', '\u0648\u062f \u0645\u062f\u0646\u064a', '\u0633\u0646\u0627\u0631', '\u0643\u0648\u0633\u062a\u064a', '\u0627\u0644\u0641\u0627\u0634\u0631', '\u0646\u064a\u0627\u0644\u0627', '\u0627\u0644\u062c\u0646\u064a\u0646\u0629', '\u0627\u0644\u0623\u0628\u064a\u0636', '\u0643\u0627\u062f\u0642\u0644\u064a', '\u0627\u0644\u062f\u0644\u0646\u062c', '\u0639\u0637\u0628\u0631\u0629', '\u0643\u0633\u0644\u0627', '\u0627\u0644\u0642\u0636\u0627\u0631\u0641', '\u0627\u0644\u062f\u0645\u0627\u0632\u064a\u0646', '\u0643\u0631\u062f\u0641\u0627\u0646', '\u0634\u0645\u0627\u0644 \u0643\u0631\u062f\u0641\u0627\u0646', '\u062c\u0646\u0648\u0628 \u0643\u0631\u062f\u0641\u0627\u0646', '\u062f\u0627\u0631\u0641\u0648\u0631', '\u0627\u0644\u0646\u064a\u0644 \u0627\u0644\u0623\u0632\u0631\u0642', '\u0627\u0644\u062c\u0632\u064a\u0631\u0629', '\u0632\u0645\u0632\u0645', '\u0623\u0628\u0648 \u0634\u0648\u0643', '\u0632\u0627\u0644\u0646\u062c\u064a',
]

SPECIFIC_ASSETS = [
    'presidential palace sudan', 'republican palace',
    'general command khartoum', 'sudan army headquarters',
    'un compound sudan', 'rsf headquarters', 'rsf base',
    'saf base', 'saf brigade', 'fuel depot',
    'oil refinery', 'grain silo', 'gold mine', 'gum arabic warehouse',
    'petrodar pipeline', 'oil terminal port sudan',
    'displacement camp', 'idp camp', 'field hospital',
    'humanitarian convoy', 'aid warehouse',
    'water treatment plant', 'power station',
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
    'humanitarian access denial', 'starvation as weapon',
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
        print(f"[Sudan Rhetoric Redis] GET error: {str(e)[:100]}")
    return None


def _redis_set(key, value, ttl=RHETORIC_CACHE_TTL):
    """Upstash REST SET (command-array to base URL).

    Diagnostic version -- logs actual HTTP status + response body when writes
    fail. Catches the env-var trap: UPSTASH_REDIS_URL holding a redis://
    connection string instead of the https:// REST URL.
    """
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        print("[Sudan Rhetoric Redis] SET skipped -- URL or TOKEN not set")
        return False
    if not UPSTASH_REDIS_URL.startswith('http'):
        print(f"[Sudan Rhetoric Redis] SET ABORT -- UPSTASH_REDIS_URL is not an "
              f"https REST URL (starts with '{UPSTASH_REDIS_URL[:10]}...').")
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
            print(f"[Sudan Rhetoric Redis] SET FAILED ({key}): "
                  f"HTTP {resp.status_code} body={resp.text[:160]}")
            return False
        return True
    except Exception as e:
        print(f"[Sudan Rhetoric Redis] SET EXCEPTION ({key}): "
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
# RSS SOURCES  (English + Arabic + regional feeds)
# ============================================
RHETORIC_RSS_FEEDS = [
    # Core Sudan war
    ("https://news.google.com/rss/search?q=Sudan+RSF+SAF+war&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Sudan+El+Obeid+Kordofan+siege&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Sudan+drone+strike+Port+Sudan&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Sudan+famine+cholera+IPC&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Sudan+El+Fasher+Darfur+RSF&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Sudan+peace+Boulos+quad&hl=en&gl=US&ceid=US:en", 0.9),
    # Russia plug
    ("https://news.google.com/rss/search?q=Russia+Port+Sudan+base&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Africa+Corps+Sudan+Wagner&hl=en&gl=US&ceid=US:en", 0.9),
    # UAE / patrons
    ("https://news.google.com/rss/search?q=UAE+Sudan+RSF+arms+Amdjarass&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Egypt+Iran+Turkey+Sudan+SAF&hl=en&gl=US&ceid=US:en", 0.9),
    # Spillover corridors
    ("https://news.google.com/rss/search?q=Sudan+Chad+border+refugees+Zaghawa&hl=en&gl=US&ceid=US:en", 0.85),
    ("https://news.google.com/rss/search?q=Sudan+South+Sudan+SPLM+Blue+Nile&hl=en&gl=US&ceid=US:en", 0.85),
    # Libya-Haftar contradiction node
    ("https://news.google.com/rss/search?q=Haftar+Sudan+RSF+Libya&hl=en&gl=US&ceid=US:en", 0.85),
    # Arabic
    ("https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B3%D9%88%D8%AF%D8%A7%D9%86+%D8%A7%D9%84%D8%AF%D8%B9%D9%85+%D8%A7%D9%84%D8%B3%D8%B1%D9%8A%D8%B9&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    ("https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%A3%D8%A8%D9%8A%D8%B6+%D9%83%D8%B1%D8%AF%D9%81%D8%A7%D9%86&hl=ar&gl=SA&ceid=SA:ar", 0.85),
]

SUDAN_SUBREDDITS = ['Sudan', 'Sudanese', 'HornOfAfrica', 'geopolitics', 'CredibleDefense']
SUDAN_REDDIT_KEYWORDS = [
    'rsf', 'saf', 'sudan', 'burhan', 'hemedti', 'darfur',
    'el fasher', 'el obeid', 'kordofan', 'port sudan',
    'boulos', 'russia sudan', 'uae sudan', 'chad sudan',
]


def fetch_reddit_sudan(days=3):
    """Fetch Reddit posts from Sudan-relevant subreddits (gated by keyword)."""
    time_filter = 'day' if days <= 1 else ('week' if days <= 7 else 'month')
    query = ' OR '.join(SUDAN_REDDIT_KEYWORDS[:4])
    posts = []
    for subreddit in SUDAN_SUBREDDITS:
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
                if not any(kw in text_lower for kw in SUDAN_REDDIT_KEYWORDS):
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
            print(f"[Sudan Rhetoric/Reddit] r/{subreddit}: {count} posts")
        except Exception as e:
            print(f"[Sudan Rhetoric/Reddit] r/{subreddit} error: {str(e)[:80]}")
            continue
    return posts


# ============================================
# ARTICLE FETCHING
# ============================================
def fetch_rhetoric_articles(days=3):
    """Fetch articles from RSS + GDELT + Reddit + Telegram + Bluesky, deduped."""
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
                    'source': 'GoogleNews',
                    'source_type': 'rss',
                    'weight': weight,
                })
        except Exception as e:
            print(f"[Sudan Rhetoric RSS] Error: {str(e)[:80]}")

    rss_count = len(articles)
    print(f"[Sudan Rhetoric] RSS: {rss_count} articles")

    # ── GDELT (via shared gateway) ──
    if GDELT_AVAILABLE:
        gdelt_count = 0
        for gq, glang in SUDAN_GDELT_QUERIES:
            try:
                raw = _gw_gdelt_fetch(gq, language=glang, timespan=f'{days}d',
                                      maxrecords=25, label=f'sudan/{glang}')
                for a in raw:
                    articles.append({
                        'title': a.get('title', ''),
                        'url': a.get('url', ''),
                        'published': a.get('published', ''),
                        'description': a.get('title', ''),
                        'source': a.get('source') or f'GDELT/{glang}',
                        'source_type': 'gdelt',
                        'weight': 0.85,
                    })
                    gdelt_count += 1
            except Exception as e:
                print(f"[Sudan Rhetoric] GDELT {glang} error: {str(e)[:80]}")
        print(f"[Sudan Rhetoric] GDELT: {gdelt_count} articles")

    # ── Reddit ──
    try:
        reddit_posts = fetch_reddit_sudan(days=days)
        articles.extend(reddit_posts)
        print(f"[Sudan Rhetoric] Reddit: {len(reddit_posts)} posts")
    except Exception as e:
        print(f"[Sudan Rhetoric] Reddit error: {str(e)[:80]}")

    # ── Telegram (shared Africa channels via widened gate) ──
    if TELEGRAM_AVAILABLE:
        try:
            tg_messages = fetch_telegram_for_target('sudan', hours_back=days * 24)
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
            print(f"[Sudan Rhetoric] Telegram: {tg_count} messages")
        except Exception as e:
            print(f"[Sudan Rhetoric] Telegram error: {str(e)[:80]}")

    # ── Bluesky (optional) ──
    if BLUESKY_AVAILABLE:
        try:
            bs_posts = fetch_bluesky_for_target('sudan', hours_back=days * 24)
            bs_count = 0
            for p in (bs_posts or []):
                articles.append({
                    'title': (p.get('text') or '')[:200],
                    'url': p.get('url', ''),
                    'published': p.get('published', '') or p.get('date', ''),
                    'description': (p.get('text') or '')[:500],
                    'source': f"Bluesky/{p.get('handle', 'sudan')}",
                    'source_type': 'bluesky',
                    'weight': 0.7,
                })
                bs_count += 1
            print(f"[Sudan Rhetoric] Bluesky: {bs_count} posts")
        except Exception as e:
            print(f"[Sudan Rhetoric] Bluesky error: {str(e)[:80]}")

    # ── Dedup by URL (GDELT and Google News RSS surface the same stories;
    #    duplicates would double-count in the classifier and inflate levels). ──
    seen_urls = set()
    deduped = []
    for a in articles:
        u = (a.get('url') or '').strip()
        if u and u in seen_urls:
            continue
        if u:
            seen_urls.add(u)
        deduped.append(a)
    if len(deduped) < len(articles):
        print(f"[Sudan Rhetoric] Dedup: {len(articles) - len(deduped)} duplicate URLs dropped")
    articles = deduped

    print(f"[Sudan Rhetoric] Total articles: {len(articles)}")
    if not articles:
        print("[Sudan Rhetoric] \u26a0\ufe0f ZERO articles from ALL lanes. Check, in order: "
              "Google News RSS soft-block (most likely after repeated force scans), "
              "GDELT gateway 429 backoff, Reddit UA block. The per-lane counts above "
              "name the failure.")
    return articles


# ============================================
# CLASSIFIER
# ============================================
def classify_articles(articles):
    """Classify articles by actor and escalation vector. Also sub-tags the
    SAF-patron composite (egypt / ksa / iran / turkey) so patron sub-vectors
    can be surfaced to GPI granularly. Diplomatic (peace-track) hits are
    tagged with pressure_type='diplomatic' at emission time."""

    actor_results = {
        actor_id: {
            'name': info['name'],
            'flag': info['flag'],
            'color': info['color'],
            'role': info['role'],
            'mode': info['mode'],
            'statement_count': 0,
            'kinetic_score': 0,
            'russia_plug_score': 0,
            'uae_axis_score': 0,
            'saf_patron_score': 0,
            'peace_track_score': 0,     # DE-escalatory polarity
            'spillover_south_score': 0,
            'spillover_west_score': 0,
            'libya_haftar_score': 0,
            'escalation_level': 0,
            'top_articles': [],
            'escalation_history': [],
        }
        for actor_id, info in ACTORS.items()
    }

    theatre_summary = {
        'kinetic_max': 0, 'russia_plug_max': 0, 'uae_axis_max': 0,
        'saf_patron_max': 0, 'peace_track_max': 0,
        'spillover_south_max': 0, 'spillover_west_max': 0,
        'libya_haftar_max': 0,
        'specificity_scores': [],
        'conditional_threats': [],
        'coordination_signals': [],
        # ── Patron composite sub-tags (Egypt / KSA / Iran / Turkey) ──
        'saf_patron_egypt_max': 0,
        'saf_patron_ksa_max': 0,
        'saf_patron_iran_max': 0,
        'saf_patron_turkey_max': 0,
        # ── Top-signal candidates for each spoke read ──
        'russia_plug_signals': [],
        'uae_axis_signals': [],
        'peace_track_signals': [],
        'libya_haftar_signals': [],
    }

    # Patron sub-tag keyword sets (for saf_patron composite drill-down)
    EGYPT_TAGS  = ['egypt', 'egyptian', 'sisi', 'cairo']
    KSA_TAGS    = ['saudi', 'ksa', 'jeddah', 'riyadh', 'mbs']
    IRAN_TAGS   = ['iran', 'iranian', 'irgc', 'mohajer', 'tehran']
    TURKEY_TAGS = ['turkey', 'turkish', 'bayraktar', 'ankara', 'erdogan']

    vector_map = [
        ('kinetic_score',         'kinetic_max',         KINETIC_TRIGGERS),
        ('russia_plug_score',     'russia_plug_max',     RUSSIA_PLUG_TRIGGERS),
        ('uae_axis_score',        'uae_axis_max',        UAE_AXIS_TRIGGERS),
        ('saf_patron_score',      'saf_patron_max',      SAF_PATRON_TRIGGERS),
        ('spillover_south_score', 'spillover_south_max', SPILLOVER_SOUTH_TRIGGERS),
        ('spillover_west_score',  'spillover_west_max',  SPILLOVER_WEST_TRIGGERS),
        ('libya_haftar_score',    'libya_haftar_max',    LIBYA_HAFTAR_TRIGGERS),
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

        # ── THEATRE-WIDE vectors: kinetic, russia_plug, uae_axis, peace_track,
        # spillover_south/west, libya_haftar are phenomena that no single actor
        # necessarily "claims". Score them on EVERY article, matched or not,
        # so a Port Sudan drone strike or a Boulos meeting still lights the
        # theatre even if the article names no tracked actor by our exact
        # keyword. ──
        for level in range(5, 0, -1):
            for kw in KINETIC_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['kinetic_max']:
                    theatre_summary['kinetic_max'] = level
            for kw in RUSSIA_PLUG_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['russia_plug_max']:
                    theatre_summary['russia_plug_max'] = level
            for kw in UAE_AXIS_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['uae_axis_max']:
                    theatre_summary['uae_axis_max'] = level
            for kw in SAF_PATRON_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['saf_patron_max']:
                    theatre_summary['saf_patron_max'] = level
            for kw in PEACE_TRACK_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['peace_track_max']:
                    theatre_summary['peace_track_max'] = level
            for kw in SPILLOVER_SOUTH_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['spillover_south_max']:
                    theatre_summary['spillover_south_max'] = level
            for kw in SPILLOVER_WEST_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['spillover_west_max']:
                    theatre_summary['spillover_west_max'] = level
            for kw in LIBYA_HAFTAR_TRIGGERS.get(level, []):
                if kw in text and level > theatre_summary['libya_haftar_max']:
                    theatre_summary['libya_haftar_max'] = level

        # ── Spoke-signal collection (theatre-wide; capped at 6 per spoke). ──
        if theatre_summary['russia_plug_max'] >= 2 and len(theatre_summary['russia_plug_signals']) < 6:
            for level in range(5, 1, -1):
                if any(kw in text for kw in RUSSIA_PLUG_TRIGGERS.get(level, [])):
                    theatre_summary['russia_plug_signals'].append({
                        'title': article.get('title', '')[:120],
                        'level': level, 'url': article.get('url', ''),
                        'published': pub_date if isinstance(pub_date, str) else '',
                    })
                    break
        if theatre_summary['uae_axis_max'] >= 2 and len(theatre_summary['uae_axis_signals']) < 6:
            for level in range(5, 1, -1):
                if any(kw in text for kw in UAE_AXIS_TRIGGERS.get(level, [])):
                    theatre_summary['uae_axis_signals'].append({
                        'title': article.get('title', '')[:120],
                        'level': level, 'url': article.get('url', ''),
                        'published': pub_date if isinstance(pub_date, str) else '',
                    })
                    break
        if theatre_summary['peace_track_max'] >= 2 and len(theatre_summary['peace_track_signals']) < 6:
            for level in range(5, 1, -1):
                if any(kw in text for kw in PEACE_TRACK_TRIGGERS.get(level, [])):
                    theatre_summary['peace_track_signals'].append({
                        'title': article.get('title', '')[:120],
                        'level': level, 'url': article.get('url', ''),
                        'published': pub_date if isinstance(pub_date, str) else '',
                    })
                    break
        if theatre_summary['libya_haftar_max'] >= 2 and len(theatre_summary['libya_haftar_signals']) < 6:
            for level in range(5, 1, -1):
                if any(kw in text for kw in LIBYA_HAFTAR_TRIGGERS.get(level, [])):
                    theatre_summary['libya_haftar_signals'].append({
                        'title': article.get('title', '')[:120],
                        'level': level, 'url': article.get('url', ''),
                        'published': pub_date if isinstance(pub_date, str) else '',
                    })
                    break

        # ── Patron sub-tag (Egypt / KSA / Iran / Turkey) — reads the composite
        # saf_patron level and attributes it to whichever sub-patron appears
        # in the text. Multiple can fire if the article names multiple. ──
        patron_lvl = theatre_summary['saf_patron_max']
        if patron_lvl > 0:
            if any(t in text for t in EGYPT_TAGS):
                theatre_summary['saf_patron_egypt_max']  = max(theatre_summary['saf_patron_egypt_max'],  patron_lvl)
            if any(t in text for t in KSA_TAGS):
                theatre_summary['saf_patron_ksa_max']    = max(theatre_summary['saf_patron_ksa_max'],    patron_lvl)
            if any(t in text for t in IRAN_TAGS):
                theatre_summary['saf_patron_iran_max']   = max(theatre_summary['saf_patron_iran_max'],   patron_lvl)
            if any(t in text for t in TURKEY_TAGS):
                theatre_summary['saf_patron_turkey_max'] = max(theatre_summary['saf_patron_turkey_max'], patron_lvl)

        if not matched_actors:
            continue

        for actor_id in matched_actors:
            actor_results[actor_id]['statement_count'] += 1

        # ── Per-actor vector scoring ──
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
                            break

                # Peace track (de-escalation) — scored separately per actor
                for kw in PEACE_TRACK_TRIGGERS.get(level, []):
                    if kw in text:
                        if level > ar['peace_track_score']:
                            ar['peace_track_score'] = level
                        break

            # Headline escalation = max across ESCALATORY vectors only.
            # peace_track is NOT included (it's de-escalatory polarity).
            ar['escalation_level'] = max(
                ar['kinetic_score'], ar['russia_plug_score'], ar['uae_axis_score'],
                ar['saf_patron_score'], ar['spillover_south_score'],
                ar['spillover_west_score'], ar['libya_haftar_score'],
            )

        # ── Specificity + conditional threats (once per article) ──
        if matched_actors:
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
    """Flag claiming actors (SAF, RSF) whose statement count falls far below
    baseline. Silence after tempo = pre-operational signal.
    Threshold: actual < 30% of baseline avg (baseline avg > 3, >=5 scans)."""
    anomalies = []
    try:
        for actor_id, ar in actor_results.items():
            if ACTORS.get(actor_id, {}).get('mode') != 'actor':
                continue
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
                print(f"[Sudan Rhetoric] \U0001F507 Silence anomaly: {actor_id} "
                      f"({actual} vs avg {avg_statements:.1f})")
    except Exception as e:
        print(f"[Sudan Rhetoric] Silence detection error: {str(e)[:80]}")
    return anomalies


# ============================================
# ACTOR BASELINES (rolling, for silence detection)
# ============================================
def _update_actor_baselines(actor_results):
    """Rolling statement-count baseline per actor. Absence-honest until MIN."""
    BASELINE_KEY = 'rhetoric:sudan:baselines'
    try:
        baselines = _redis_get(BASELINE_KEY) or {}
        for actor_id, ar in actor_results.items():
            b = baselines.get(actor_id, {'avg_statements': 0, 'scans': 0})
            count = ar.get('statement_count', 0)
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
        print(f"[Sudan Rhetoric] Baseline update error: {str(e)[:80]}")
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
        print(f"[Sudan Rhetoric] Delta error: {str(e)[:80]}")
        return None


# ============================================
# COMPOUND-RISK LAYER (reads humanitarian + commodity)
# ============================================
def _read_compound_layers():
    """Read the humanitarian and commodity Redis keys and return a compact
    sensor summary. This is where 'convergence' becomes measurable at the
    tracker altitude -- we describe what is present; the interpreter reads
    the compound. Absence-honest: missing keys become 'present: False'."""
    hum = _redis_get(HUMANITARIAN_KEY)
    com = _redis_get(COMMODITY_KEY)

    humanitarian_read = {'present': False}
    if hum and isinstance(hum, dict):
        try:
            headline = hum.get('headline_stats', [])
            idp = next((s for s in headline if 'displaced' in s.get('label','').lower()), {})
            ret = next((s for s in headline if 'return' in s.get('label','').lower()), {})
            humanitarian_read = {
                'present': True,
                'live_dtm': hum.get('live_dtm', False),
                'idp_display': idp.get('display', ''),
                'returnee_display': ret.get('display', ''),
                'famine_note': hum.get('famine_note', ''),
                'disease_note': hum.get('disease_note', ''),
                'data_as_of': hum.get('data_as_of', ''),
            }
        except Exception:
            humanitarian_read = {'present': True, 'read_error': True}

    commodity_read = {'present': False}
    if com and isinstance(com, dict):
        try:
            commodity_read = {
                'present': True,
                'status': com.get('status', ''),
                'commodities': com.get('commodities', []),
                'as_of': com.get('as_of', ''),
            }
        except Exception:
            commodity_read = {'present': True, 'read_error': True}

    return humanitarian_read, commodity_read


# ============================================
# WHEEL-HUB READS  (Russia hub parity + contradiction flag)
# ============================================
def _read_russia_hub():
    """Read the Russia wheel-hub fingerprint (crosstheater:russia:fingerprint).
    Sudan doesn't score off the hub -- it emits its own russia_plug read.
    But surfacing the hub level lets the interpreter frame the Port-Sudan
    plug in wheel-parity context. Absence-honest."""
    fp = _redis_get(RUSSIA_HUB_KEY)
    if not fp or not isinstance(fp, dict):
        return {'present': False}
    try:
        return {
            'present': True,
            'ts': fp.get('ts', ''),
            'level': fp.get('level', 0),
            'node_class': fp.get('node_class', ''),
        }
    except Exception:
        return {'present': True, 'read_error': True}


# ============================================
# CROSS-THEATER / WHEEL-HUB EMISSION
# ============================================
COLLECTIVE_KEY = 'rhetoric:crosstheater:fingerprints'   # shared dict (Africa BLUF)
CANONICAL_KEY  = 'crosstheater:sudan:fingerprint'       # canonical hub schema


def _build_spoke_reads(result, theatre_summary):
    """Compute the spoke sub-reads for the fingerprint payload."""
    # Russia plug — the state-level Port Sudan / Africa Corps read
    russia_plug = {
        'level': theatre_summary.get('russia_plug_max', 0),
        'top_signals': theatre_summary.get('russia_plug_signals', [])[:3],
    }
    # UAE axis — RSF principal patron
    uae_axis = {
        'level': theatre_summary.get('uae_axis_max', 0),
        'top_signals': theatre_summary.get('uae_axis_signals', [])[:3],
    }
    # SAF patron composite with sub-tags
    saf_patrons = {
        'level': theatre_summary.get('saf_patron_max', 0),
        'egypt_level':  theatre_summary.get('saf_patron_egypt_max', 0),
        'ksa_level':    theatre_summary.get('saf_patron_ksa_max', 0),
        'iran_level':   theatre_summary.get('saf_patron_iran_max', 0),
        'turkey_level': theatre_summary.get('saf_patron_turkey_max', 0),
    }
    # Spillover corridors
    spillover_south = {'level': theatre_summary.get('spillover_south_max', 0)}
    spillover_west  = {'level': theatre_summary.get('spillover_west_max', 0)}
    # Libya-Haftar contradiction node
    libya_haftar = {
        'level': theatre_summary.get('libya_haftar_max', 0),
        'top_signals': theatre_summary.get('libya_haftar_signals', [])[:3],
    }
    # Peace track (DIPLOMATIC polarity)
    peace_track = {
        'level': theatre_summary.get('peace_track_max', 0),
        'top_signals': theatre_summary.get('peace_track_signals', [])[:3],
    }
    return russia_plug, uae_axis, saf_patrons, spillover_south, spillover_west, libya_haftar, peace_track


def _detect_compound_convergence(theatre_summary, humanitarian_read, commodity_read, libya_haftar_level, russia_plug_level):
    """Two convergence detectors:

    A) compound_risk: kinetic AND humanitarian tightening AND commodity pressure.
       This is the Sudan-specific compound the food-cascade doctrine names.
    B) russia_contradiction: BOTH the state-level Russia plug active AND Haftar
       supplying RSF from Libya-east. The doctrine's contradiction flag.
    """
    kinetic  = theatre_summary.get('kinetic_max', 0)
    compound = {
        'compound_risk_active': False,
        'russia_contradiction_active': False,
        'notes': [],
    }
    if kinetic >= 3 and humanitarian_read.get('present') and commodity_read.get('present'):
        commodity_stressed = str(commodity_read.get('status', '')).lower() in (
            'elevated', 'high', 'critical', 'surge', 'stressed')
        # Any famine or disease note is qualitative evidence of pressure;
        # combined with a live kinetic reading, this is the compound.
        hum_stressed = bool(humanitarian_read.get('famine_note')) or bool(humanitarian_read.get('disease_note'))
        if hum_stressed and (commodity_stressed or True):
            # Commodity pressure elevates the read but doesn't gate it: the
            # kinetic + humanitarian compound alone is doctrinally material.
            compound['compound_risk_active'] = True
            compound['notes'].append(
                'Kinetic tempo, humanitarian compression, and commodity exposure '
                'co-occurring -- the compound pattern that has historically '
                'preceded famine expansion and subsistence-driven collapse. '
                '(Convergence indicator; not a probability of action.)'
            )
    if russia_plug_level >= 3 and libya_haftar_level >= 3:
        compound['russia_contradiction_active'] = True
        compound['notes'].append(
            'The Russia-Sudan state-level plug (Port Sudan) and Russia-aligned '
            'Haftar arming the RSF from Libya-east are BOTH live in this cycle. '
            'The wheel is arguing with itself; which plug wins is the read.'
        )
    return compound


def _write_crosstheater_signal(result, theatre_summary, humanitarian_read,
                                commodity_read, russia_hub_read, compound):
    """Triple emission (emit once, consume many):
      1. rhetoric:sudan:latest                       (own cache; front page)
      2. rhetoric:crosstheater:fingerprints['sudan'] (collective; Africa BLUF)
      3. crosstheater:sudan:fingerprint              (canonical; Russia hub reads)
    (Key 1, rhetoric:sudan:latest, is written by the scan orchestrator.)"""
    try:
        russia_plug, uae_axis, saf_patrons, spillover_south, spillover_west, \
            libya_haftar, peace_track = _build_spoke_reads(result, theatre_summary)

        theatre_level = result.get('theatre_escalation_level', 0)
        actors = result.get('actors', {})
        actor_levels = {aid: actors.get(aid, {}).get('escalation_level', 0)
                        for aid in ACTORS}

        # Silence read (SAF + RSF are the claiming actors)
        silence = result.get('silence_anomalies', [])
        saf_silent = any(a['actor_id'] == 'saf_burhan' for a in silence)
        rsf_silent = any(a['actor_id'] == 'rsf_hemedti' for a in silence)

        # ── Key 2: collective dict (Africa BLUF consumes) ──
        existing = _redis_get(COLLECTIVE_KEY) or {}
        existing['sudan'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Sudan',
            'level': theatre_level,
            'score': result.get('rhetoric_score', 0),
            'theatre_score': result.get('rhetoric_score', 0),
            'node_class': 'sudan_hub',   # per scope decision
            'actor_levels': actor_levels,
            'saf_silent': saf_silent,
            'rsf_silent': rsf_silent,
            'russia_plug': russia_plug,
            'uae_axis': uae_axis,
            'saf_patrons': saf_patrons,
            'peace_track': peace_track,
            'spillover_south': spillover_south,
            'spillover_west': spillover_west,
            'libya_haftar': libya_haftar,
            'compound_layers': {
                'humanitarian': humanitarian_read,
                'commodity': commodity_read,
                'russia_hub_parity': russia_hub_read,
            },
            'compound_convergence': compound,
            'top_phrases': [s.get('title', '')[:60]
                            for s in theatre_summary.get('russia_plug_signals', [])[:3]],
        }
        _redis_set(COLLECTIVE_KEY, existing, ttl=14 * 3600)

        # ── Key 3: canonical per-country fingerprint (Russia hub reads) ──
        canonical = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'country': 'sudan',
            'node_class': 'sudan_hub',
            'level': theatre_level,
            'vector_levels': {
                'kinetic':          theatre_summary.get('kinetic_max', 0),
                'russia_plug':      theatre_summary.get('russia_plug_max', 0),
                'uae_axis':         theatre_summary.get('uae_axis_max', 0),
                'saf_patron':       theatre_summary.get('saf_patron_max', 0),
                'peace_track':      theatre_summary.get('peace_track_max', 0),
                'spillover_south':  theatre_summary.get('spillover_south_max', 0),
                'spillover_west':   theatre_summary.get('spillover_west_max', 0),
                'libya_haftar':     theatre_summary.get('libya_haftar_max', 0),
            },
            'actor_levels': actor_levels,
            'russia_plug': russia_plug,
            'uae_axis': uae_axis,
            'saf_patrons': saf_patrons,
            'peace_track': peace_track,
            'spillover_south': spillover_south,
            'spillover_west': spillover_west,
            'libya_haftar': libya_haftar,
            'saf_silent': saf_silent,
            'rsf_silent': rsf_silent,
            'compound_convergence': compound,
        }
        _redis_set(CANONICAL_KEY, canonical, ttl=14 * 3600)

        flags = []
        if compound.get('compound_risk_active'):
            flags.append('compound_risk')
        if compound.get('russia_contradiction_active'):
            flags.append('russia_contradiction')
        print(f"[Sudan Rhetoric] \u2705 Hub fingerprint written (collective + canonical); "
              f"flags: {flags or 'none'}")
        return compound
    except Exception as e:
        print(f"[Sudan Rhetoric] Cross-theater write error: {str(e)[:140]}")
        return {'compound_risk_active': False, 'russia_contradiction_active': False, 'notes': []}


def _detect_crosstheater_coordination(sudan_plug_level=0):
    """Read sibling hub fingerprints and flag how the Sudan reads sit alongside
    active hub postures elsewhere. Surface-only; the GPI synthesizes globally.

    ABSENCE-HONEST (fixed Jul 24 2026): the earlier version asserted 'while
    Sudan russia_plug is active' whenever the Russia hub was elevated -- without
    checking Sudan's own plug. It therefore claimed a convergence on cycles
    where Sudan read L0, which is exactly the manufactured signal the doctrine
    forbids. The note now states which of the two is actually live.
    """
    try:
        signals = []
        russia_fp = _redis_get(RUSSIA_HUB_KEY)
        if russia_fp and isinstance(russia_fp, dict):
            hub_level = russia_fp.get('level', 0)
            if hub_level >= 3:
                if sudan_plug_level >= 3:
                    note = ('Russia hub elevated globally AND the Sudan Port Sudan plug is '
                            'active in the same cycle -- consistent with Port Sudan becoming '
                            'the new supply-chain spine.')
                else:
                    note = ('Russia hub elevated globally, but the Sudan Port Sudan plug is '
                            'quiet this cycle (L%d). Hub posture without a local plug read is '
                            'context, not convergence -- the Sudan spoke is not currently '
                            'carrying it.' % sudan_plug_level)
                signals.append({
                    'hub': 'russia',
                    'note': note,
                    'hub_level': hub_level,
                    'sudan_plug_level': sudan_plug_level,
                    'converged': sudan_plug_level >= 3,
                })
        # (Future: read crosstheater:uae:fingerprint / crosstheater:egypt:fingerprint
        # if / when those hubs get formalised.)
        return signals
    except Exception as e:
        print(f"[Sudan Rhetoric] Coordination detect error: {str(e)[:80]}")
        return []


# ============================================
# CORPUS HEALTH  (the denominator)
# ============================================
def _assess_corpus_health(article_count):
    """Compare this scan's corpus against a rolling baseline.

    Returns (status, baseline, note) where status is 'ok' | 'degraded' | 'outage'.
    Absence-honest: with fewer than 3 recorded scans there is no baseline yet,
    so only the absolute floor applies and we say the baseline is accumulating.
    """
    try:
        b = _redis_get(CORPUS_BASELINE_KEY) or {'avg': 0, 'scans': 0}
        avg, scans = b.get('avg', 0), b.get('scans', 0)

        if article_count < CORPUS_MIN_ABSOLUTE:
            return ('outage', avg,
                    'Corpus collapsed to %d articles (floor is %d). Treating as a feed '
                    'outage, not a quiet cycle -- scores are NOT published from this scan.'
                    % (article_count, CORPUS_MIN_ABSOLUTE))

        if scans >= 3 and avg > 0 and article_count < avg * CORPUS_DEGRADED_RATIO:
            return ('degraded', avg,
                    'Corpus at %d articles vs a rolling baseline of %.0f (%.0f%%). Scores '
                    'published but read as a floor, not a ceiling -- quiet here may be the '
                    'feeds, not the theatre.'
                    % (article_count, avg, 100.0 * article_count / avg))

        note = ('Baseline accumulating (%d scan(s) recorded).' % scans) if scans < 3 else \
               ('Corpus healthy: %d articles vs baseline %.0f.' % (article_count, avg))
        return ('ok', avg, note)
    except Exception as e:
        print(f"[Sudan Rhetoric] Corpus health check error: {str(e)[:90]}")
        return ('ok', 0, 'Corpus health unavailable this cycle.')


def _update_corpus_baseline(article_count):
    """Roll the corpus-size baseline forward. Outage scans are NOT recorded --
    a failed fetch must not drag the denominator down and normalise itself."""
    try:
        if article_count < CORPUS_MIN_ABSOLUTE:
            return
        b = _redis_get(CORPUS_BASELINE_KEY) or {'avg': 0, 'scans': 0}
        n = b.get('scans', 0)
        avg = b.get('avg', 0)
        new_avg = (avg * n + article_count) / (n + 1) if n < 30 else (avg * 0.9 + article_count * 0.1)
        _redis_set(CORPUS_BASELINE_KEY,
                   {'avg': round(new_avg, 1), 'scans': min(n + 1, 999),
                    'last_count': article_count},
                   ttl=60 * 24 * 3600)
    except Exception as e:
        print(f"[Sudan Rhetoric] Corpus baseline update error: {str(e)[:90]}")


# ============================================
# SCAN ORCHESTRATOR
# ============================================
def run_sudan_rhetoric_scan(days=3):
    """Full Sudan rhetoric scan. Writes cache + triple emission."""
    print(f"[Sudan Rhetoric] Starting scan ({days}-day window)...")

    articles = fetch_rhetoric_articles(days)

    # ── CORPUS-HEALTH GATE ──────────────────────────────────────────────
    # Refuse to publish scores from an empty corpus. Overwriting a known-good
    # read with L0 "below escalation threshold" because the feeds died is a
    # false analytical claim, and it is indistinguishable on the page from a
    # genuinely quiet theatre. Say "the sensor failed" instead.
    corpus_status, corpus_baseline, corpus_note = _assess_corpus_health(len(articles))
    if corpus_status == 'outage':
        print(f"[Sudan Rhetoric] \u26a0\ufe0f CORPUS OUTAGE -- {corpus_note}")
        lastgood = _redis_get(LASTGOOD_KEY) or _redis_get(RHETORIC_CACHE_KEY)
        payload = dict(lastgood) if isinstance(lastgood, dict) else {}
        payload.update({
            'success': True,
            'country': 'sudan',
            'corpus_health': {
                'status': 'outage',
                'article_count': len(articles),
                'baseline': corpus_baseline,
                'note': corpus_note,
            },
            'scan_aborted': True,
            'stale': bool(payload),
            'scan_attempted_at': datetime.now(timezone.utc).isoformat(),
        })
        if not payload.get('theatre_label'):
            payload.update({
                'rhetoric_score': 0, 'theatre_escalation_level': 0,
                'theatre_label': 'Sensor offline', 'article_count': 0,
                'top_signals': [], 'actors': {}, 'vector_levels': {},
                'disclaimer': 'This composite is a CONVERGENCE indicator, NOT a probability of action.',
            })
        # Deliberately does NOT write the cache: last-known-good survives.
        return payload

    actor_results, theatre_summary = classify_articles(articles)

    # Escalatory theatre level = max across ESCALATORY vectors (peace_track excluded)
    max_kinetic         = theatre_summary['kinetic_max']
    max_russia_plug     = theatre_summary['russia_plug_max']
    max_uae_axis        = theatre_summary['uae_axis_max']
    max_saf_patron      = theatre_summary['saf_patron_max']
    max_spillover_south = theatre_summary['spillover_south_max']
    max_spillover_west  = theatre_summary['spillover_west_max']
    max_libya_haftar    = theatre_summary['libya_haftar_max']
    theatre_escalation_level = max(
        max_kinetic, max_russia_plug, max_uae_axis, max_saf_patron,
        max_spillover_south, max_spillover_west, max_libya_haftar,
    )

    spec_scores = theatre_summary.get('specificity_scores', [])
    theatre_specificity = round(sum(spec_scores) / len(spec_scores), 1) if spec_scores else 0

    # ══════════════════════════════════════════════════════════════
    # NUANCED RHETORIC SCORE (0-100)
    #   Kinetic (SAF vs RSF war tempo) weighted highest -- it IS Sudan's signal.
    #   Russia plug + UAE axis are the patron / wheel-hub axis.
    #   Spillover corridors and Libya-Haftar add cross-theater pressure.
    #   Peace track REDUCES (diplomatic off-ramp / de-escalatory polarity).
    # ══════════════════════════════════════════════════════════════
    score = 0
    score += max_kinetic         * 8    # max 40 -- primary
    score += max_russia_plug     * 4    # max 20 -- wheel-hub plug (Port Sudan)
    score += max_uae_axis        * 3    # max 15 -- RSF principal patron
    score += max_saf_patron      * 3    # max 15 -- SAF patron composite
    score += max_spillover_south * 2    # max 10 -- SS corridor
    score += max_spillover_west  * 2    # max 10 -- Chad border
    score += max_libya_haftar    * 2    # max 10 -- contradiction node
    score = min(score, 80)

    # Hot actor bonus
    hot_actors = sum(1 for ar in actor_results.values()
                     if ar.get('escalation_level', 0) >= 3)
    score += min(hot_actors * 4, 12)

    # Compound-convergence preview (real detector runs in emission)
    humanitarian_read, commodity_read = _read_compound_layers()
    russia_hub_read = _read_russia_hub()
    compound_preview = _detect_compound_convergence(
        theatre_summary, humanitarian_read, commodity_read,
        max_libya_haftar, max_russia_plug)
    if compound_preview.get('compound_risk_active'):
        score += 6
    if compound_preview.get('russia_contradiction_active'):
        score += 4

    # Peace-track modifier (de-escalation REDUCES). Canonical CEASEFIRE_TRIGGERS
    # mapping from other backends' diplomatic-track architecture.
    peace_level = theatre_summary.get('peace_track_max', 0)
    peace_modifier_map = {0: 0, 1: -1, 2: -3, 3: -6, 4: -10, 5: -15}
    peace_modifier = peace_modifier_map.get(peace_level, 0)
    score += peace_modifier

    rhetoric_score = max(0, min(100, int(score)))

    # Assemble result
    result = {
        'success': True,
        'country': 'sudan',
        'theatre': 'Sudan',
        'flag': '\U0001F1F8\U0001F1E9',
        'scan_date': datetime.now(timezone.utc).isoformat(),
        'window_days': days,
        'article_count': len(articles),
        'corpus_health': {
            'status': corpus_status,
            'article_count': len(articles),
            'baseline': corpus_baseline,
            'note': corpus_note,
        },
        'rhetoric_score': rhetoric_score,
        'theatre_escalation_level': theatre_escalation_level,
        'theatre_label': ESCALATION_LEVELS.get(theatre_escalation_level, {}).get('label', 'Unknown'),
        'theatre_score': rhetoric_score,
        'specificity_score': theatre_specificity,
        'vector_levels': {
            'kinetic':         max_kinetic,
            'russia_plug':     max_russia_plug,
            'uae_axis':        max_uae_axis,
            'saf_patron':      max_saf_patron,
            'peace_track':     peace_level,
            'spillover_south': max_spillover_south,
            'spillover_west':  max_spillover_west,
            'libya_haftar':    max_libya_haftar,
        },
        'patron_subtags': {
            'egypt':  theatre_summary.get('saf_patron_egypt_max', 0),
            'ksa':    theatre_summary.get('saf_patron_ksa_max', 0),
            'iran':   theatre_summary.get('saf_patron_iran_max', 0),
            'turkey': theatre_summary.get('saf_patron_turkey_max', 0),
        },
        'peace_track_level': peace_level,
        'peace_track_modifier': peace_modifier,
        'compound_layers': {
            'humanitarian': humanitarian_read,
            'commodity': commodity_read,
            'russia_hub_parity': russia_hub_read,
        },
        # Set from the preview so the INTERPRETER (which runs below, before the
        # fingerprint write) can see it. Line ~1750 overwrites with the identical
        # value returned by _write_crosstheater_signal -- same inputs, idempotent.
        'compound_convergence': compound_preview,
        'actors': actor_results,
        'conditional_threats': theatre_summary.get('conditional_threats', [])[:8],
        'crosstheater_coordination': [],
        'disclaimer': 'This composite is a CONVERGENCE indicator, NOT a probability of action.',
    }

    # ── Corpus + actor baselines ──
    _update_corpus_baseline(len(articles))
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    # ── Tempo emission (corpus-health denominator) ──
    if TEMPO_EMIT_AVAILABLE and _tempo_emit:
        try:
            for actor_id, ar in actor_results.items():
                _tempo_emit(
                    theatre='sudan',
                    actor=actor_id,
                    count=ar.get('statement_count', 0),
                    corpus_total=len(articles),
                    mode=ACTORS[actor_id]['mode'],
                )
        except Exception as _e:
            print(f"[Sudan Rhetoric] Tempo emit failed (non-fatal): {str(_e)[:100]}")

    # ── Interpreter (so_what, red_lines, historical, top_signals) ──
    if _INTERPRETER_AVAILABLE and _sudan_interpret_signals:
        try:
            result['interpretation'] = _sudan_interpret_signals(result)
        except Exception as e:
            print(f"[Sudan Rhetoric] Interpreter error: {str(e)[:120]}")
            result['interpretation'] = {}

    if _INTERPRETER_AVAILABLE and _sudan_build_top_signals:
        try:
            result['top_signals'] = _sudan_build_top_signals(result)
            print(f"[Sudan Rhetoric] Built {len(result['top_signals'])} top_signals for BLUF/GPI")
        except Exception as e:
            print(f"[Sudan Rhetoric] build_top_signals error: {str(e)[:120]}")
            result['top_signals'] = []
    else:
        result['top_signals'] = []

    # ── Save cache + last-known-good ──
    _cache_bytes = len(json.dumps(result, default=str))
    _wrote_cache = _redis_set(RHETORIC_CACHE_KEY, result)
    _wrote_lg    = _redis_set(LASTGOOD_KEY, result, ttl=LASTGOOD_TTL)
    print(f"[Sudan Rhetoric] Cache write: latest={_wrote_cache} "
          f"lastgood={_wrote_lg} payload={_cache_bytes:,}B "
          f"key={RHETORIC_CACHE_KEY}")
    if not _wrote_cache:
        print("[Sudan Rhetoric] \u26A0\uFE0F CACHE WRITE FAILED -- page will show "
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
            'kinetic':      max_kinetic,
            'russia_plug':  max_russia_plug,
            'uae_axis':     max_uae_axis,
            'peace_track':  peace_level,
            'specificity':  theatre_specificity,
        })
        if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
            import urllib.parse
            enc = urllib.parse.quote(snapshot, safe='')
            requests.post(f"{UPSTASH_REDIS_URL}/lpush/{HISTORY_KEY}/{enc}",
                          headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=5)
            requests.post(f"{UPSTASH_REDIS_URL}/ltrim/{HISTORY_KEY}/0/119",
                          headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=5)
    except Exception as e:
        print(f"[Sudan Rhetoric] History append error (non-fatal): {str(e)[:80]}")

    result['delta'] = _compute_delta()

    # ── Triple emission (hub fingerprints) ──
    compound = _write_crosstheater_signal(
        result, theatre_summary, humanitarian_read, commodity_read,
        russia_hub_read, compound_preview)
    result['compound_convergence'] = compound
    result['crosstheater_coordination'] = _detect_crosstheater_coordination(max_russia_plug)

    print(f"[Sudan Rhetoric] \u2705 Scan complete — score {rhetoric_score}, "
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
            print("[Sudan Rhetoric] Another worker holds the scan lock — skipping")
            return
        run_sudan_rhetoric_scan(days=3)
    except Exception as e:
        print(f"[Sudan Rhetoric] Background scan error: {str(e)[:120]}")
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


def _start_periodic_scan(interval_hours=12):
    def loop():
        time.sleep(120)  # boot delay -- distinct offset from Somalia (90)
        while True:
            try:
                _bg_rhetoric_scan()
            except Exception as e:
                print(f"[Sudan Rhetoric] Periodic scan error: {str(e)[:100]}")
            time.sleep(interval_hours * 3600)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print(f"[Sudan Rhetoric] Periodic scan started ({interval_hours}h interval)")


# Public alias for app.py's start_background_refresh idiom
def start_background_refresh(interval_hours=12):
    """Public entry point matching the app.py scaffolding pattern."""
    _start_periodic_scan(interval_hours=interval_hours)


def register_sudan_rhetoric_endpoints(app):
    """Wire Sudan rhetoric endpoints into the Africa backend."""

    @app.route('/api/rhetoric/sudan', methods=['GET'])
    def sudan_rhetoric():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        if force:
            try:
                return jsonify(run_sudan_rhetoric_scan(days=3))
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)[:200]}), 500
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            cached['from_cache'] = True
            return jsonify(cached)
        lg = _redis_get(LASTGOOD_KEY)
        if lg:
            lg['from_cache'] = True
            lg['stale'] = True
            return jsonify(lg)
        return jsonify({'success': False, 'status': 'no_scan_yet',
                        'message': 'No Sudan scan cached. Use ?force=true.'}), 200

    @app.route('/api/rhetoric/sudan/summary', methods=['GET'])
    def sudan_rhetoric_summary():
        """Lightweight read for the stability-page banner + top-signals card.

        Carries top_signals, vector_levels, and the so_what prose so the
        stability page can render a real Gold Standard rhetoric card without
        pulling the full payload (which includes every actor's article list).
        """
        cached = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(LASTGOOD_KEY) or {}
        _interp = cached.get('interpretation', {}) or {}
        _rl = _interp.get('red_lines', {}) or {}
        return jsonify({
            'country': 'sudan',
            'rhetoric_score': cached.get('rhetoric_score', 0),
            'theatre_escalation_level': cached.get('theatre_escalation_level', 0),
            'theatre_label': cached.get('theatre_label', 'Unknown'),
            'vector_levels': cached.get('vector_levels', {}),
            'compound_convergence': cached.get('compound_convergence', {}),
            'silence_anomalies': cached.get('silence_anomalies', []),
            'top_signals': cached.get('top_signals', []),
            'so_what': _interp.get('so_what', {}),
            'red_lines_breached': _rl.get('breached_count', 0),
            'corpus_health': cached.get('corpus_health', {}),
            'scan_date': cached.get('scan_date', ''),
            'stale': bool(cached.get('stale')),
        })

    @app.route('/api/rhetoric/sudan/history', methods=['GET'])
    def sudan_rhetoric_history():
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/lrange/{HISTORY_KEY}/0/119",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=5)
            data = resp.json().get('result', [])
            history = [json.loads(x) for x in data]
            return jsonify({'country': 'sudan', 'history': history, 'count': len(history)})
        except Exception as e:
            return jsonify({'country': 'sudan', 'history': [], 'error': str(e)[:120]})

    @app.route('/debug/rhetoric-sudan', methods=['GET'])
    def debug_rhetoric_sudan():
        """One-glance health probe: config, cache presence, compound-layer reads."""
        hum, com = _read_compound_layers()
        russia_hub = _read_russia_hub()
        return jsonify({
            'module': 'rhetoric_tracker_sudan v1.0.0',
            'redis_url_set': bool(UPSTASH_REDIS_URL),
            'redis_token_set': bool(UPSTASH_REDIS_TOKEN),
            'gdelt_available': GDELT_AVAILABLE,
            'telegram_available': TELEGRAM_AVAILABLE,
            'bluesky_available': BLUESKY_AVAILABLE,
            'interpreter_available': _INTERPRETER_AVAILABLE,
            'tempo_emit_available': TEMPO_EMIT_AVAILABLE,
            'cache_present': bool(_redis_get(RHETORIC_CACHE_KEY)),
            'lastgood_present': bool(_redis_get(LASTGOOD_KEY)),
            'compound_layer_reads': {
                'humanitarian': hum,
                'commodity': com,
                'russia_hub_parity': russia_hub,
            },
            'actor_roster': list(ACTORS.keys()),
        })

    print("[Sudan Rhetoric] \u2705 Routes registered: /api/rhetoric/sudan "
          "(+/summary,/history,/debug/rhetoric-sudan)")
