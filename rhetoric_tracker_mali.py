"""
Mali Rhetoric & Pressure Tracker — Asifah Analytics
version: 1.0.0 — July 25, 2026  |  Africa backend (asifah-africa-backend.onrender.com)

Mali is a RUSSIA SPOKE and, more importantly, the TEST CASE for whether the
Africa Corps model works at all. Alongside CAR and Libya it is the largest
Russian deployment on the continent, and it is the one taking losses.

  JOB 1 — country sensor (front page):
    FAMa + Africa Corps vs a coalition of FLA (secular Tuareg separatists) and
    JNIM (al-Qaeda affiliate); the JNIM fuel blockade strangling Bamako; the
    AES bloc; junta hedging toward alternative suppliers.

  JOB 2 — Russia-wheel TRAJECTORY (feeds Africa BLUF -> GPI):
    Not just "is Russia present here" but "is Russia GAINING OR LOSING here."
    That is the new read this tracker is born with.

────────────────────────────────────────────────────────────────────────────
THE TRAJECTORY VECTOR (new, Jul 25 2026)
────────────────────────────────────────────────────────────────────────────
Every wheel panel to date answers ONE question: is a spoke LIT. It cannot tell
Port Sudan (a hub EXPANDING) from Kidal (a hub CONTRACTING) -- opposite reads
rendered identically.

This tracker emits `trajectory`: direction + magnitude + EVIDENCE CLASS, so a
hub's gain and a hub's bleed are distinguishable. Evidence classes:

  CONTRACTING  territory_lost · materiel_loss · casualties · withdrawal ·
               client_hedging · agreement_lapsed · expulsion · partner_defection
  EXPANDING    agreement_signed · new_basing · rival_expelled ·
               concession_granted · dependency_deepening
  HOLDING      present, nothing moving

The read only becomes interesting when it CONVERGES. One spoke contracting is
a coda on a country page. Russia contracting across Mali AND Sudan AND CAR AND
Libya is a regional question that demands a WHY. Add Ukraine and it stops being
regional -- that is the altitude at which the pattern earns a NAME.

WHY THE HUB IS HERE AT ALL (framing for the analyst layer):
The product Russia sells is REGIME SURVIVAL, not counterterrorism -- insulation
for a junta against its own army and its own population. Payment is resource
concessions that convert to cash outside the dollar system, which keeps the
operation off the Russian budget. Commodities are the payment MECHANISM, not the
objective. So a trajectory read has to watch the payment stream (gold, mining)
and the dependency (does the junta still need them) as well as the battlefield.

────────────────────────────────────────────────────────────────────────────
CLAIM DISCIPLINE — load-bearing for this theatre
────────────────────────────────────────────────────────────────────────────
Much of the Mali corpus is FLA/JNIM claims amplified through pro-Ukraine OSINT
accounts, unconfirmed by Russia or Bamako. Trajectory built on unverified claims
from an interested party will read whatever that party wants it to read.

So: insurgent actors run mode='tape' -- we measure CLAIM TEMPO and ATTRIBUTION,
never event counts. Every trajectory emission carries a `confidence` field
(claim_sourced / multi_source / confirmed) so the consumer can weight it.

KNOWN LIMIT, stated rather than hidden: a hub that loses ground with NOBODY
reporting it reads as 'holding'. Quiet is not the same as stable, and this
tracker cannot tell them apart. Surfaced in the payload as `trajectory_caveat`.

────────────────────────────────────────────────────────────────────────────
CLONE NOTE — Burkina Faso / Niger (tier-two Russia spokes)
────────────────────────────────────────────────────────────────────────────
The AES juntas share vocabulary. ACTORS, the trigger ladders and TRAJECTORY_
EVIDENCE are deliberately generic where they can be: swap the geography lists,
the junta names and the insurgent roster and Burkina/Niger are a transform.
The blockade, hedging and trajectory frames all generalise.

EMISSION (emit once, consume many) — writes THREE keys:
  1. rhetoric:mali:latest                       (own cache; front page)
  2. rhetoric:crosstheater:fingerprints['mali'] (collective; Africa BLUF)
  3. crosstheater:mali:fingerprint              (canonical; Russia hub reads)

CROSS-TRACKER READS:
  * africa:humanitarian:mali   (mali_humanitarian.py -- blockade/IDP)
  * africa:commodity:mali      (commodity_proxy_africa -- gold/lithium)
  * crosstheater:russia:fingerprint  (Russia hub, for wheel parity)

Endpoint: GET /api/rhetoric/mali
"""

import os
import json
import threading
import time
import requests
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

try:
    from mali_signal_interpreter import (
        interpret_signals as _mali_interpret_signals,
        build_top_signals as _mali_build_top_signals,
    )
    _INTERPRETER_AVAILABLE = True
    print("[Mali Rhetoric] Signal interpreter loaded")
except ImportError as _e:
    print(f"[Mali Rhetoric] \u26a0\ufe0f  Signal interpreter not available: {_e}")
    _mali_interpret_signals = None
    _mali_build_top_signals = None
    _INTERPRETER_AVAILABLE = False


# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

try:
    from telegram_signals_africa import fetch_telegram_for_target
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Mali Rhetoric] \u26a0\ufe0f Telegram signals not available")

try:
    from bluesky_signals_africa import fetch_bluesky_for_target
    BLUESKY_AVAILABLE = True
except ImportError:
    BLUESKY_AVAILABLE = False

# ── Shared trajectory reader (v1.0.0, Jul 25 2026) ────────────────────
# Mali shipped with an inline reader; it now defers to the SHARED module so
# all four spokes score direction against ONE vocabulary. A phrase counting as
# 'territory_lost' in Mali must count as 'territory_lost' in Syria, or the
# cross-spoke rollup compares nothing to nothing.
try:
    from trajectory_reader import read_trajectory as _shared_read_trajectory
    _TRAJECTORY_SHARED = True
except ImportError:
    _TRAJECTORY_SHARED = False
    print("[Mali Rhetoric] trajectory_reader not available -- using inline reader")

# Standing rule (Jul 24 2026): wire the gateway at birth in every NEW tracker.
try:
    from gdelt_gateway import gdelt_fetch as _gw_gdelt_fetch
    GDELT_AVAILABLE = True
    print("[Mali Rhetoric] \u2705 GDELT gateway available")
except ImportError:
    GDELT_AVAILABLE = False
    print("[Mali Rhetoric] \u26a0\ufe0f GDELT gateway not available — no GDELT lane")

MALI_GDELT_QUERIES = [
    ('Mali Africa Corps Wagner',            'eng'),
    ('Mali JNIM blockade Bamako',           'eng'),
    ('Azawad Liberation Front Mali Kidal',  'eng'),
    ('Mali junta Goita AES',                'eng'),
    # French: Mali's primary media language
    ('Mali Africa Corps arm\u00e9e russe',  'fra'),
    ('Mali blocus carburant Bamako JNIM',   'fra'),
    ('Mali FLA Azawad Kidal offensive',     'fra'),
    # Arabic: Sahel coverage in Arabic media carries northern-Mali and
    # Azawad reporting that francophone outlets underweight.
    ('\u0645\u0627\u0644\u064a \u0627\u0644\u0633\u0627\u062d\u0644', 'ara'),
    ('\u0623\u0632\u0648\u0627\u062f \u0645\u0627\u0644\u064a',      'ara'),
]

RHETORIC_CACHE_KEY  = 'rhetoric:mali:latest'
RHETORIC_CACHE_TTL  = 13 * 3600
LASTGOOD_KEY        = 'rhetoric:mali:lastgood'
LASTGOOD_TTL        = 7 * 24 * 3600
HISTORY_KEY         = 'rhetoric:mali:history'
SCAN_LOCK_KEY       = 'rhetoric:mali:scanlock'
SCAN_LOCK_TTL       = 600
CORPUS_BASELINE_KEY = 'rhetoric:mali:corpus_baseline'
CORPUS_MIN_ABSOLUTE = 5

HUMANITARIAN_KEY    = 'africa:humanitarian:mali'
COMMODITY_KEY       = 'africa:commodity:mali'
RUSSIA_HUB_KEY      = 'crosstheater:russia:fingerprint'

COLLECTIVE_KEY = 'rhetoric:crosstheater:fingerprints'
CANONICAL_KEY  = 'crosstheater:mali:fingerprint'

REDDIT_USER_AGENT = 'AsifahAnalytics/1.0 (OSINT research; asifahanalytics.com)'

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ACTOR REGISTRY (9 actors; mode discipline explicit)
# ============================================
ACTORS = {
    'mali_junta': {
        'name': 'Mali Junta / FAMa (Go\u00efta, CNSP)',
        'flag': '\U0001F1F2\U0001F1F1',
        'color': '#0e7490',
        'role': 'Claiming state force + coup regime',
        'mode': 'actor',
    },
    'africa_corps': {
        'name': 'Russia / Africa Corps (the hub plug)',
        'flag': '\U0001F1F7\U0001F1FA',
        'color': '#7f1d1d',
        'role': 'Hub spoke — regime-survival contractor',
        'mode': 'tape',
    },
    'fla': {
        'name': 'FLA — Azawad Liberation Front (Tuareg, SECULAR)',
        'flag': '\U0001F3F4',
        'color': '#0891b2',
        'role': 'Claiming separatist — NOT jihadist',
        'mode': 'actor',
    },
    'jnim': {
        'name': 'JNIM (al-Qaeda affiliate)',
        'flag': '\u2620\uFE0F',
        'color': '#c2410c',
        'role': 'Claiming jihadist — runs the Bamako blockade',
        'mode': 'actor',
    },
    'issp': {
        'name': 'ISSP / Islamic State Sahel',
        'flag': '\U0001F5A4',
        'color': '#450a0a',
        'role': 'Claiming jihadist — JNIM RIVAL, they fight each other',
        'mode': 'actor',
    },
    'turkey_hedge': {
        'name': 'Turkey (alternative supplier — hedging watch)',
        'flag': '\U0001F1F9\U0001F1F7',
        'color': '#b45309',
        'role': 'Hedge vector — is Bamako shopping?',
        'mode': 'tape',
    },
    'china_commercial': {
        'name': 'China (commercial / BRI — light read)',
        'flag': '\U0001F1E8\U0001F1F3',
        'color': '#065f46',
        'role': 'Commercial, NOT a competing security patron',
        'mode': 'tape',
    },
    'aes_bloc': {
        'name': 'AES Bloc (Mali \u00b7 Niger \u00b7 Burkina Faso)',
        'flag': '\U0001F91D',
        'color': '#4b5563',
        'role': 'Confederation cohesion — tier-two clone anchor',
        'mode': 'tape',
    },
    'libya_corridor': {
        'name': 'Libya Corridor (Benghazi \u2192 Maaten al-Sarra \u2192 Sahel)',
        'flag': '\U0001F1F1\U0001F1FE',
        'color': '#3f3f46',
        'role': 'Logistics spine — SAME corridor that feeds Sudan',
        'mode': 'tape',
    },
}

ESCALATION_LEVELS = {
    0: {'label': 'Monitoring',      'color': '#6b7280'},
    1: {'label': 'Rhetoric',        'color': '#3b82f6'},
    2: {'label': 'Tension',         'color': '#f59e0b'},
    3: {'label': 'Confrontation',   'color': '#f97316'},
    4: {'label': 'Incident',        'color': '#ef4444'},
    5: {'label': 'Active Conflict', 'color': '#7c3aed'},
}


# ============================================
# ACTOR KEYWORDS (EN + FR — Mali's media is francophone)
# ============================================
ACTORS_KEYWORDS = ACTOR_KEYWORDS = {
    'mali_junta': [
        'mali junta', 'fama', 'malian armed forces', 'assimi goita', 'goita',
        'cnsp mali', 'bamako government', 'malian army', 'mali transition',
        'arm\u00e9e malienne', 'junte malienne', 'gouvernement malien',
        'forces arm\u00e9es maliennes',
    ],
    'africa_corps': [
        'africa corps mali', 'wagner mali', 'russian mali', 'russia mali',
        'russian instructors mali', 'africa corps', 'afrika korps mali',
        'yevkurov', 'averyanov', 'russian mercenaries mali',
        'corps africain', 'instructeurs russes', 'mercenaires russes',
        'russes au mali',
    ],
    'fla': [
        'azawad liberation front', 'fla azawad', 'fla mali', 'azawad',
        'tuareg rebels mali', 'tuareg separatist', 'cma mali', 'csp-dpa',
        'front de lib\u00e9ration de l\u2019azawad', 'rebelles touaregs',
        'ind\u00e9pendantistes touaregs',
    ],
    'jnim': [
        'jnim', 'jama\u2019at nusrat', 'jamaat nusrat al-islam',
        'nusrat al-islam', 'iyad ag ghaly', 'amadou kouffa', 'macina katiba',
        'katiba macina', 'al-qaeda mali', 'groupe de soutien \u00e0 l\u2019islam',
    ],
    'issp': [
        'islamic state sahel', 'issp', 'isgs', 'is sahel province',
        'daesh sahel', 'etat islamique sahel', '\u00e9tat islamique au grand sahara',
    ],
    'turkey_hedge': [
        'turkey mali', 'bayraktar mali', 'turkish drones mali', 'tb2 mali',
        'akinci mali', 'ankara mali', 'turkish military mali',
        'turquie mali', 'drones turcs mali',
    ],
    'china_commercial': [
        'china mali', 'chinese mali', 'bri mali', 'belt and road mali',
        'chinese mining mali', 'china gold mali', 'chine mali',
    ],
    'aes_bloc': [
        'alliance of sahel states', 'aes sahel', 'sahel alliance',
        'liptako-gourma charter', 'aes confederation', 'aes joint force',
        'mali niger burkina', 'alliance des \u00e9tats du sahel',
        'confederation aes',
    ],
    'libya_corridor': [
        'libya mali', 'haftar sahel', 'benghazi sahel', 'maaten al-sarra',
        'libya sahel corridor', 'lna sahel', 'libya supply sahel',
        'libye sahel',
    ],
}


# ============================================
# ESCALATION KEYWORDS (per-vector 0-5 ladders, EN + FR)
# ============================================
KINETIC_TRIGGERS = {
    5: ['bamako falls', 'gao falls', 'mopti falls', 'junta overthrown',
        'coup in mali', 'mass atrocity mali', 'moura massacre',
        'chute de bamako', 'massacre mali'],
    4: ['kidal falls', 'anefis falls', 'aguelhok falls', 'convoy ambushed mali',
        'helicopter shot down mali', 'mi-24 shot down', 'defence minister killed',
        'coordinated attacks mali', 'simultaneous attacks mali',
        'africa corps casualties', 'wagner casualties mali',
        'embuscade mali', 'h\u00e9licopt\u00e8re abattu', 'attaques coordonn\u00e9es',
        'convoi attaqu\u00e9'],
    3: ['mali offensive', 'fama offensive', 'jnim attack', 'fla offensive',
        'mali army advance', 'siege mali', 'encircled mali',
        'offensive au mali', 'attaque jnim', 'assaut mali'],
    2: ['mali clashes', 'mali fighting', 'mali skirmish', 'mali frontline',
        'affrontements mali', 'combats mali'],
    1: ['mali conflict', 'mali insurgency', 'mali violence',
        'conflit malien', 'insurrection mali'],
}

# THE BLOCKADE — Mali's signature vector. Economic strangulation of a capital.
BLOCKADE_TRIGGERS = {
    5: ['bamako fuel exhausted', 'bamako cut off', 'capital besieged mali',
        'bamako encircled', 'bamako assi\u00e9g\u00e9'],
    4: ['fuel blockade bamako', 'fuel convoy attacked mali', 'fuel tanker attacked',
        'bamako fuel shortage', 'blocus carburant', 'p\u00e9nurie carburant bamako',
        'camion-citerne attaqu\u00e9'],
    3: ['supply route interdiction mali', 'road blockade mali', 'convoy interdiction',
        'jnim blockade', 'blocus jnim', 'routes coup\u00e9es mali'],
    2: ['fuel shortage mali', 'supply disruption mali', 'market closure mali',
        'p\u00e9nurie mali', 'ravitaillement mali'],
    1: ['mali supply', 'mali fuel', 'carburant mali'],
}

# THE CONVERGENCE — FLA (secular separatist) + JNIM (al-Qaeda) coordinating.
# A coalition of convenience and a force multiplier. A SPLIT would be as
# significant as the alliance, so this vector reads both directions.
INSURGENT_CONVERGENCE_TRIGGERS = {
    5: ['fla jnim joint offensive', 'unified insurgent command mali',
        'coalition azawad jnim'],
    4: ['fla and jnim', 'jnim and fla', 'coordinated fla jnim',
        'tuareg jihadist alliance', 'joint attack fla jnim',
        'alliance fla jnim', 'attaque conjointe'],
    3: ['simultaneous attacks fla jnim', 'insurgent coordination mali',
        'coordination rebelle mali'],
    2: ['fla jnim', 'separatists and jihadists mali',
        's\u00e9paratistes et djihadistes'],
    1: ['mali rebels', 'rebelles maliens'],
}

# JUNTA HEDGING — is Bamako shopping for alternatives? The leading indicator
# that the Russia dependency is loosening.
HEDGING_TRIGGERS = {
    5: ['mali expels russia', 'africa corps expelled mali', 'mali ends russia deal',
        'mali russie rupture'],
    4: ['mali turkish drones delivered', 'bayraktar delivered mali',
        'mali diversifies partners', 'mali new security partner',
        'mali signs turkey', 'mali uae deal', 'livraison drones turcs'],
    3: ['mali turkey talks', 'mali seeks alternatives', 'mali defence diversification',
        'mali morocco', 'mali algeria talks',
        'mali cherche partenaires', 'diversification mali'],
    2: ['turkey mali cooperation', 'china mali investment', 'mali partnership talks',
        'coop\u00e9ration turquie mali'],
    1: ['mali foreign partners', 'partenaires mali'],
}

AES_TRIGGERS = {
    5: ['aes collapse', 'mali leaves aes', 'aes dissolved', 'dissolution aes'],
    4: ['aes rift', 'aes dispute', 'niger mali tension', 'burkina mali tension',
        'tension aes'],
    3: ['aes joint force deployment', 'aes summit', 'aes confederation',
        'sommet aes', 'force conjointe aes'],
    2: ['aes cooperation', 'sahel alliance meeting', 'coop\u00e9ration aes'],
    1: ['aes', 'alliance of sahel states', 'alliance sahel'],
}

LIBYA_CORRIDOR_TRIGGERS = {
    5: ['libya sahel corridor severed', 'maaten al-sarra strike'],
    4: ['russian transfers benghazi sahel', 'libya supply route mali',
        'africa corps libya logistics', 'maaten al-sarra deployment'],
    3: ['haftar sahel', 'libya sahel supply', 'benghazi mali flights',
        'libye sahel ravitaillement'],
    2: ['libya sahel', 'libya mali', 'libye mali'],
    1: ['libya corridor', 'corridor libyen'],
}

CHINA_COMMERCIAL_TRIGGERS = {
    5: ['china security mali', 'chinese forces mali'],
    4: ['china mali mining deal', 'chinese gold concession mali',
        'bri agreement mali', 'accord minier chine mali'],
    3: ['chinese investment mali', 'china mali infrastructure',
        'investissement chinois mali'],
    2: ['china mali trade', 'chinese company mali', 'commerce chine mali'],
    1: ['china mali', 'chine mali'],
}

# ══════════════════════════════════════════════════════════════════════
# TRAJECTORY EVIDENCE  — the new vector
# ══════════════════════════════════════════════════════════════════════
# Direction is not inferred from a level. It is read from EVIDENCE CLASSES,
# because "Russia is lit in Mali" is true whether Russia is winning or bleeding
# there, and those are opposite analytical reads.
TRAJECTORY_EVIDENCE = {
    'contracting': {
        'territory_lost': [
            'kidal falls', 'kidal seized', 'anefis seized', 'aguelhok seized',
            'withdrew from', 'abandoned position', 'lost control of',
            'rebels entered', 'rebels control',
            'perte de', 'abandonn\u00e9 la position', 'rebelles contr\u00f4lent',
        ],
        'materiel_loss': [
            'helicopter shot down', 'mi-24 shot down', 'mi-35 shot down',
            'aircraft downed', 'vehicles destroyed', 'convoy destroyed',
            'equipment lost', 'h\u00e9licopt\u00e8re abattu', 'v\u00e9hicules d\u00e9truits',
        ],
        'casualties': [
            'russian casualties', 'africa corps killed', 'wagner killed',
            'russian soldiers killed', 'russian prisoners', 'pow russian',
            'pertes russes', 'soldats russes tu\u00e9s',
        ],
        'withdrawal': [
            'russia withdraws', 'africa corps withdraws', 'drawdown',
            'russia reduces presence', 'pulled back', 'retrait russe',
            'r\u00e9duction des effectifs',
        ],
        'client_hedging': [
            'mali seeks alternatives', 'mali turkish drones', 'mali diversifies',
            'mali new security partner', 'mali uae deal',
            'diversification mali', 'mali cherche partenaires',
        ],
        'agreement_lapsed': [
            'agreement not renewed', 'deal expired', 'contract lapsed',
            'accord non renouvel\u00e9',
        ],
        'expulsion': [
            'expels russia', 'russia expelled', 'orders russia to leave',
            'expulsion des russes',
        ],
        'partner_defection': [
            'defects from', 'switches allegiance', 'breaks with russia',
            'rompt avec la russie',
        ],
    },
    'expanding': {
        'agreement_signed': [
            'russia mali agreement signed', 'new russia deal mali',
            'military cooperation signed', 'accord sign\u00e9 russie mali',
        ],
        'new_basing': [
            'russian base mali', 'new russian facility', 'base russe',
            'nouvelle installation russe',
        ],
        'rival_expelled': [
            'france expelled', 'us troops leave', 'minusma withdrawal',
            'western forces expelled', 'expulsion fran\u00e7aise',
            'd\u00e9part des forces occidentales',
        ],
        'concession_granted': [
            'mining concession russia', 'gold concession granted',
            'russia granted mining', 'concession mini\u00e8re russe',
        ],
        'dependency_deepening': [
            'more russian troops', 'russian reinforcements mali',
            'expanded russian presence', 'renforts russes',
            'pr\u00e9sence russe accrue',
        ],
    },
}

# Confidence: who is making the claim. Trajectory built on an interested
# party's unverified claims will read whatever that party wants.
CONFIRMING_SOURCE_HINTS = [
    'reuters', 'afp', 'associated press', 'bbc', 'le monde', 'rfi',
    'jeune afrique', 'crisis group', 'acled', 'un panel', 'human rights watch',
]
CLAIM_SOURCE_HINTS = [
    'fla claim', 'claimed', 'rebels say', 'according to the fla',
    'osint', 'telegram', 'unconfirmed', 'revendiqu\u00e9', 'selon les rebelles',
]

CONDITIONAL_TRIGGERS = {
    3: ['if bamako', 'if kidal', 'should the junta', 'unless russia',
        'if africa corps', 'si bamako', 'si la junte'],
}


# ============================================
# SPECIFICITY SCORER
# ============================================
SPECIFIC_GEOGRAPHIES = [
    # Mali — north
    'kidal', 'gao', 'anefis', 'aguelhok', 'tessalit', 'tinzaouaten',
    'menaka', 'ménaka', 'timbuktu', 'tombouctou', 'bourem', 'ansongo',
    'taoudenit', 'tabrichat', 'tlemsi', 'in-khalil',
    # Mali — centre / south
    'bamako', 'kati', 'mopti', 'sevare', 'sévaré', 'segou', 'ségou',
    'sikasso', 'koulikoro', 'kayes', 'nioro', 'douentza', 'bandiagara',
    'san mali', 'koro', 'niono', 'kenieroba', 'kéniéroba', 'moura',
    # Tri-border / corridors
    'liptako-gourma', 'liptako', 'in-tillit', 'labbezanga',
    # Assets
    'modibo keita airport', 'senou', 'sénou', 'niamana', 'faladie', 'faladié',
    'loulo-gounkoto', 'syama', 'fekola', 'goulamina',
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
        print(f"[Mali Rhetoric Redis] GET error: {str(e)[:100]}")
    return None


def _redis_set(key, value, ttl=RHETORIC_CACHE_TTL):
    """Upstash REST SET (command-array to base URL).

    Diagnostic version -- logs actual HTTP status + response body when writes
    fail. Catches the env-var trap: UPSTASH_REDIS_URL holding a redis://
    connection string instead of the https:// REST URL.
    """
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        print("[Mali Rhetoric Redis] SET skipped -- URL or TOKEN not set")
        return False
    if not UPSTASH_REDIS_URL.startswith('http'):
        print(f"[Mali Rhetoric Redis] SET ABORT -- UPSTASH_REDIS_URL is not an "
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
            print(f"[Mali Rhetoric Redis] SET FAILED ({key}): "
                  f"HTTP {resp.status_code} body={resp.text[:160]}")
            return False
        return True
    except Exception as e:
        print(f"[Mali Rhetoric Redis] SET EXCEPTION ({key}): "
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
# RSS SOURCES (EN + FR — Mali's media is francophone)
# ============================================
RHETORIC_RSS_FEEDS = [
    # ── WIDENED Jul 26 2026 ────────────────────────────────────────────
    # First production cycle returned 5 RSS articles. The queries were too
    # narrow: multi-term Google News searches match almost nothing on a
    # theatre this underreported. Broad country terms plus LOCAL outlets is
    # what actually fills the corpus here.
    ("https://news.google.com/rss/search?q=Mali&hl=fr&gl=FR&ceid=FR:fr", 0.85),
    ("https://news.google.com/rss/search?q=Mali+s%C3%A9curit%C3%A9&hl=fr&gl=FR&ceid=FR:fr", 0.95),
    ("https://news.google.com/rss/search?q=Mali+arm%C3%A9e&hl=fr&gl=FR&ceid=FR:fr", 0.95),
    ("https://news.google.com/rss/search?q=Bamako&hl=fr&gl=FR&ceid=FR:fr", 0.9),
    ("https://news.google.com/rss/search?q=Sahel&hl=fr&gl=FR&ceid=FR:fr", 0.8),

    # ── LOCAL MALIAN PRESS ─────────────────────────────────────────────
    # Studio Tamani (Fondation Hirondelle) is the strongest single Mali
    # source: independent, broadcasts in French AND Bambara, and covers
    # security incidents the national outlets skip.
    ("https://news.google.com/rss/search?q=site:studiotamani.org&hl=fr&gl=FR&ceid=FR:fr", 1.0),
    ("https://news.google.com/rss/search?q=site:maliweb.net&hl=fr&gl=FR&ceid=FR:fr", 0.95),
    ("https://news.google.com/rss/search?q=site:malijet.com&hl=fr&gl=FR&ceid=FR:fr", 0.9),
    ("https://news.google.com/rss/search?q=site:bamada.net&hl=fr&gl=FR&ceid=FR:fr", 0.9),
    ("https://news.google.com/rss/search?q=site:journaldumali.com&hl=fr&gl=FR&ceid=FR:fr", 0.9),
    ("https://news.google.com/rss/search?q=site:sahelien.com&hl=fr&gl=FR&ceid=FR:fr", 0.95),
    ("https://news.google.com/rss/search?q=site:lessormali.com&hl=fr&gl=FR&ceid=FR:fr", 0.85),

    # ── Regional / specialist ──────────────────────────────────────────
    ("https://news.google.com/rss/search?q=site:rfi.fr+Mali&hl=fr&gl=FR&ceid=FR:fr", 1.0),
    ("https://news.google.com/rss/search?q=site:jeuneafrique.com+Mali&hl=fr&gl=FR&ceid=FR:fr", 0.95),
    ("https://news.google.com/rss/search?q=site:apanews.net+Mali&hl=fr&gl=FR&ceid=FR:fr", 0.85),

    # ── ARABIC LANE (new) ──────────────────────────────────────────────
    # A genuine gap. Anadolu, Al Jazeera and Sahara Media cover the Sahel
    # substantially, and carry northern-Mali/Azawad reporting francophone
    # outlets underweight.
    ("https://news.google.com/rss/search?q=%D9%85%D8%A7%D9%84%D9%8A&hl=ar&gl=EG&ceid=EG:ar", 0.9),
    ("https://news.google.com/rss/search?q=%D9%85%D8%A7%D9%84%D9%8A+%D8%A7%D9%84%D8%B3%D8%A7%D8%AD%D9%84&hl=ar&gl=EG&ceid=EG:ar", 0.9),
    ("https://news.google.com/rss/search?q=%D8%A3%D8%B2%D9%88%D8%A7%D8%AF&hl=ar&gl=EG&ceid=EG:ar", 0.85),

    # ── English thematic (the original narrow set, retained) ────────────
    ("https://news.google.com/rss/search?q=Mali+Africa+Corps+Wagner&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Mali+JNIM+blockade+Bamako&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Mali+FLA+Azawad+Kidal&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Mali+Turkey+drones+Bayraktar&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Sahel+Russia+Africa+Corps&hl=en&gl=US&ceid=US:en", 0.85),
]

MALI_SUBREDDITS = ['Mali', 'Africa', 'geopolitics', 'CredibleDefense',
                   'LessCredibleDefence', 'worldnews', 'anime_titties']
# r/anime_titties is (genuinely) reddit's high-volume world-politics sub --
# non-obvious, but a real Sahel source. Keyword gating below keeps it clean.
MALI_REDDIT_KEYWORDS = [
    'mali', 'bamako', 'kidal', 'gao', 'jnim', 'azawad', 'fla',
    'africa corps', 'wagner', 'sahel', 'goita', 'malian', 'timbuktu',
    'mopti', 'tuareg', 'aes ', 'liptako',
]


def fetch_reddit_mali(days=3):
    """Reddit posts from Mali-relevant subreddits (keyword-gated)."""
    time_filter = 'day' if days <= 1 else ('week' if days <= 7 else 'month')
    query = ' OR '.join(MALI_REDDIT_KEYWORDS[:4])
    posts = []
    for subreddit in MALI_SUBREDDITS:
        try:
            time.sleep(2)
            resp = requests.get(
                f'https://www.reddit.com/r/{subreddit}/search.json',
                params={'q': query, 'restrict_sr': 'true', 'sort': 'new',
                        't': time_filter, 'limit': 25},
                headers={'User-Agent': REDDIT_USER_AGENT}, timeout=10)
            if resp.status_code != 200:
                continue
            for post in resp.json().get('data', {}).get('children', []):
                pd = post.get('data', {})
                title = pd.get('title', '')
                text_lower = f"{title} {pd.get('selftext','')}".lower()
                if not any(kw in text_lower for kw in MALI_REDDIT_KEYWORDS):
                    continue
                posts.append({
                    'title': title[:200],
                    'url': f"https://www.reddit.com{pd.get('permalink','')}",
                    'published': datetime.fromtimestamp(
                        pd.get('created_utc', 0), tz=timezone.utc).isoformat(),
                    'description': pd.get('selftext', '')[:300],
                    'source': f'r/{subreddit}', 'source_type': 'reddit', 'weight': 0.8,
                })
        except Exception as e:
            print(f"[Mali Rhetoric/Reddit] r/{subreddit} error: {str(e)[:80]}")
    return posts


def fetch_rhetoric_articles(days=3):
    """RSS + GDELT + Reddit + Telegram + Bluesky, deduped by URL."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    for feed_url, weight in RHETORIC_RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item'):
                pub = item.findtext('pubDate', '')
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
                    'title': item.findtext('title', ''),
                    'url': item.findtext('link', ''),
                    'published': pub_str if isinstance(pub_str, str) else '',
                    'description': (item.findtext('description', '') or '')[:300],
                    'source': 'GoogleNews', 'source_type': 'rss', 'weight': weight,
                })
        except Exception as e:
            print(f"[Mali Rhetoric RSS] Error: {str(e)[:80]}")
    print(f"[Mali Rhetoric] RSS: {len(articles)} articles")

    if GDELT_AVAILABLE:
        n = 0
        for gq, glang in MALI_GDELT_QUERIES:
            try:
                for a in _gw_gdelt_fetch(gq, language=glang, timespan=f'{days}d',
                                         maxrecords=25, label=f'mali/{glang}'):
                    articles.append({
                        'title': a.get('title', ''), 'url': a.get('url', ''),
                        'published': a.get('published', ''),
                        'description': a.get('title', ''),
                        'source': a.get('source') or f'GDELT/{glang}',
                        'source_type': 'gdelt', 'weight': 0.85,
                    })
                    n += 1
            except Exception as e:
                print(f"[Mali Rhetoric] GDELT {glang} error: {str(e)[:80]}")
        print(f"[Mali Rhetoric] GDELT: {n} articles")

    try:
        r = fetch_reddit_mali(days=days)
        articles.extend(r)
        print(f"[Mali Rhetoric] Reddit: {len(r)} posts")
    except Exception as e:
        print(f"[Mali Rhetoric] Reddit error: {str(e)[:80]}")

    if TELEGRAM_AVAILABLE:
        try:
            for msg in (fetch_telegram_for_target('mali', hours_back=days * 24) or []):
                articles.append({
                    'title': (msg.get('text') or msg.get('message') or '')[:200],
                    'url': msg.get('url', ''),
                    'published': msg.get('published', '') or msg.get('date', ''),
                    'description': (msg.get('text') or msg.get('message') or '')[:500],
                    'source': f"Telegram/{msg.get('channel', 'africa')}",
                    'source_type': 'telegram', 'weight': 0.75,
                })
        except Exception as e:
            print(f"[Mali Rhetoric] Telegram error: {str(e)[:80]}")

    if BLUESKY_AVAILABLE:
        try:
            # Signature is (target, days=7, max_posts_per_account=20) -- calling
            # it with hours_back raised TypeError and silently discarded ~20
            # posts per cycle. Same bug exists in rhetoric_tracker_somalia.py.
            for p in (fetch_bluesky_for_target('mali', days=max(1, days)) or []):
                articles.append({
                    'title': (p.get('text') or '')[:200], 'url': p.get('url', ''),
                    'published': p.get('published', '') or p.get('date', ''),
                    'description': (p.get('text') or '')[:500],
                    'source': f"Bluesky/{p.get('handle', 'mali')}",
                    'source_type': 'bluesky', 'weight': 0.7,
                })
        except Exception as e:
            print(f"[Mali Rhetoric] Bluesky error: {str(e)[:80]}")

    seen, deduped = set(), []
    for a in articles:
        u = (a.get('url') or '').strip()
        if u and u in seen:
            continue
        if u:
            seen.add(u)
        deduped.append(a)
    if len(deduped) < len(articles):
        print(f"[Mali Rhetoric] Dedup: {len(articles) - len(deduped)} duplicates dropped")
    print(f"[Mali Rhetoric] Total articles: {len(deduped)}")
    return deduped




# ============================================
# CORPUS HEALTH / BASELINES / DELTA
# ============================================
# Reused verbatim from the proven Sudan tracker (localised). These were
# missed in the initial block extraction -- section-header slicing dropped
# them, which is why the first force scan raised NameError instead of
# failing at import. Extracted by AST function name this time.

CORPUS_DEGRADED_RATIO = 0.40  # below 40% of rolling baseline = degraded, flag it


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
                print(f"[Mali Rhetoric] \U0001F507 Silence anomaly: {actor_id} "
                      f"({actual} vs avg {avg_statements:.1f})")
    except Exception as e:
        print(f"[Mali Rhetoric] Silence detection error: {str(e)[:80]}")
    return anomalies


def _update_actor_baselines(actor_results):
    """Rolling statement-count baseline per actor. Absence-honest until MIN."""
    BASELINE_KEY = 'rhetoric:mali:baselines'
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
        print(f"[Mali Rhetoric] Baseline update error: {str(e)[:80]}")
        return {}


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
        print(f"[Mali Rhetoric] Delta error: {str(e)[:80]}")
        return None


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
        print(f"[Mali Rhetoric] Corpus health check error: {str(e)[:90]}")
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
        print(f"[Mali Rhetoric] Corpus baseline update error: {str(e)[:90]}")


# ============================================
# CLASSIFIER
# ============================================
_VECTOR_MAP = [
    ('kinetic',               KINETIC_TRIGGERS),
    ('blockade',              BLOCKADE_TRIGGERS),
    ('insurgent_convergence', INSURGENT_CONVERGENCE_TRIGGERS),
    ('hedging',               HEDGING_TRIGGERS),
    ('aes_cohesion',          AES_TRIGGERS),
    ('libya_corridor',        LIBYA_CORRIDOR_TRIGGERS),
    ('china_commercial',      CHINA_COMMERCIAL_TRIGGERS),
]


def _read_trajectory(articles):
    """Defers to the shared reader when present; the inline implementation
    below is the fallback so Mali still works on a backend that has not yet
    received trajectory_reader.py."""
    if _TRAJECTORY_SHARED:
        try:
            return _shared_read_trajectory(
                articles, hub='russia', country='mali',
                extra_evidence={'contracting': {'territory_lost': [
                                    'kidal falls', 'kidal seized', 'anefis seized',
                                    'aguelhok seized']},
                                'expanding': {'rival_expelled': [
                                    'minusma withdrawal', 'france expelled']}})
        except Exception as _e:
            print(f"[Mali Rhetoric] Shared trajectory failed, using inline: {str(_e)[:90]}")
    return _read_trajectory_inline(articles)


def _read_trajectory_inline(articles):
    """THE NEW VECTOR. Is the hub gaining, holding, or losing ground here?

    Read from EVIDENCE CLASSES, never inferred from a level -- "Russia is lit
    in Mali" is true whether Russia is winning or bleeding, and those are
    opposite analytical reads.

    Confidence is tracked separately because this corpus is claim-heavy: FLA
    and JNIM assertions amplified through partisan OSINT accounts. A trajectory
    built on an interested party's unverified claims will read whatever that
    party wants it to read.
    """
    found = {'contracting': {}, 'expanding': {}}
    confirming = claim_only = 0

    for a in articles:
        text = f"{a.get('title','')} {a.get('description','')}".lower()
        src = str(a.get('source', '')).lower()
        hit = False
        for direction, classes in TRAJECTORY_EVIDENCE.items():
            for cls, phrases in classes.items():
                for p in phrases:
                    if p in text:
                        found[direction].setdefault(cls, [])
                        if len(found[direction][cls]) < 4:
                            found[direction][cls].append({
                                'phrase': p,
                                'title': a.get('title', '')[:120],
                                'url': a.get('url', ''),
                                'source': a.get('source', ''),
                            })
                        hit = True
                        break
        if hit:
            blob = text + ' ' + src
            if any(h in blob for h in CONFIRMING_SOURCE_HINTS):
                confirming += 1
            elif any(h in blob for h in CLAIM_SOURCE_HINTS):
                claim_only += 1

    n_contract = sum(len(v) for v in found['contracting'].values())
    n_expand   = sum(len(v) for v in found['expanding'].values())
    c_classes  = len(found['contracting'])
    e_classes  = len(found['expanding'])

    # Direction is decided by CLASS BREADTH first, volume second. Four
    # mentions of one lost convoy is one event; four different evidence
    # classes is a trend.
    if c_classes > e_classes or (c_classes == e_classes and n_contract > n_expand):
        direction = 'contracting' if c_classes else 'holding'
        magnitude = min(5, c_classes + (1 if n_contract >= 4 else 0))
    elif e_classes > c_classes or n_expand > n_contract:
        direction = 'expanding'
        magnitude = min(5, e_classes + (1 if n_expand >= 4 else 0))
    else:
        direction, magnitude = 'holding', 0

    if confirming >= 2:
        confidence = 'multi_source'
    elif confirming >= 1:
        confidence = 'confirmed_partial'
    elif claim_only or n_contract or n_expand:
        confidence = 'claim_sourced'
    else:
        confidence = 'no_evidence'

    return {
        'hub': 'russia',
        'country': 'mali',
        'direction': direction,
        'level': magnitude if direction != 'holding' else 0,
        'confidence': confidence,
        'evidence': {d: {c: v for c, v in cls.items()} for d, cls in found.items()},
        'evidence_classes': {'contracting': sorted(found['contracting']),
                             'expanding': sorted(found['expanding'])},
        'confirming_sources': confirming,
        'claim_only_sources': claim_only,
        # Stated rather than hidden: a hub that loses ground with nobody
        # reporting it reads as 'holding'. Quiet is not stable.
        'caveat': ('Trajectory reads reporting, not ground truth. A hub losing '
                   'ground unreported registers as HOLDING -- quiet is not the '
                   'same as stable, and this sensor cannot tell them apart.'),
        'ts': datetime.now(timezone.utc).isoformat(),
    }


def classify_articles(articles):
    """Classify by actor and vector. Insurgent actors are mode='actor' but
    their kinetic CLAIMS feed trajectory only via _read_trajectory, which
    tracks source confidence separately."""
    actor_results = {
        aid: {
            'name': info['name'], 'flag': info['flag'], 'color': info['color'],
            'role': info['role'], 'mode': info['mode'],
            'statement_count': 0, 'escalation_level': 0,
            'top_articles': [], 'escalation_history': [],
            **{f'{v}_score': 0 for v, _ in _VECTOR_MAP},
        }
        for aid, info in ACTORS.items()
    }
    ts = {f'{v}_max': 0 for v, _ in _VECTOR_MAP}
    ts.update({'specificity_scores': [], 'conditional_threats': [],
               'matched_phrases': set(), 'vector_signals': {v: [] for v, _ in _VECTOR_MAP}})

    for article in articles:
        text = f"{article.get('title','')} {article.get('description','')}".lower()
        pub = article.get('published', '')

        matched = []
        for aid in ACTORS:
            if any(kw.lower() in text for kw in ACTOR_KEYWORDS.get(aid, [])):
                matched.append(aid)

        # Theatre-wide vector scoring — runs on EVERY article, matched or not.
        # A blockade report naming no tracked actor still lights the blockade.
        for level in range(5, 0, -1):
            for vname, trig in _VECTOR_MAP:
                for kw in trig.get(level, []):
                    if kw in text:
                        ts['matched_phrases'].add(kw)
                        if level > ts[f'{vname}_max']:
                            ts[f'{vname}_max'] = level
                        if len(ts['vector_signals'][vname]) < 5:
                            ts['vector_signals'][vname].append({
                                'title': article.get('title', '')[:120],
                                'level': level, 'url': article.get('url', ''),
                                'published': pub if isinstance(pub, str) else '',
                            })
                        break

        for aid in matched:
            actor_results[aid]['statement_count'] += 1

        for aid in matched:
            ar = actor_results[aid]
            for level in range(5, 0, -1):
                for vname, trig in _VECTOR_MAP:
                    for kw in trig.get(level, []):
                        if kw in text and level > ar[f'{vname}_score']:
                            ar[f'{vname}_score'] = level
                            ar['escalation_history'].append({
                                'timestamp': pub if isinstance(pub, str) else '',
                                'level': level, 'vector': vname, 'phrase': kw,
                            })
                            break
            ar['escalation_level'] = max(ar[f'{v}_score'] for v, _ in _VECTOR_MAP)

        if matched:
            spec, _ = _score_specificity(text)
            article['_specificity_score'] = spec
            if spec:
                ts['specificity_scores'].append(spec)
            for kw in CONDITIONAL_TRIGGERS.get(3, []):
                if kw in text:
                    ts['conditional_threats'].append({
                        'phrase': kw, 'level': 3,
                        'article': article.get('title', '')[:100],
                        'published': pub if isinstance(pub, str) else '',
                        'specificity': spec,
                    })
                    break

        for aid in matched:
            ar = actor_results[aid]
            if len(ar['top_articles']) < 6 or ar['escalation_level'] >= 3:
                ar['top_articles'].append({
                    'title': article.get('title', '')[:120],
                    'url': article.get('url', ''),
                    'source': article.get('source', 'Unknown'),
                    'source_type': article.get('source_type', 'news'),
                    'published': pub if isinstance(pub, str) else '',
                    'escalation_level': ar['escalation_level'],
                    'specificity_score': article.get('_specificity_score', 0),
                })

    return actor_results, ts


# ============================================
# CROSS-TRACKER + EMISSION
# ============================================
def _read_compound_layers():
    """Humanitarian + commodity reads. Absence-honest."""
    hum = _redis_get(HUMANITARIAN_KEY)
    com = _redis_get(COMMODITY_KEY)
    h_read = {'present': False}
    if isinstance(hum, dict) and hum:
        headline = hum.get('headline_stats', [])
        def pick(frag):
            return next((s for s in headline if frag in s.get('label', '').lower()), {})
        h_read = {
            'present': True, 'live_dtm': hum.get('live_dtm', False),
            'idp_display': pick('displaced').get('display', ''),
            'in_need_display': pick('need').get('display', ''),
            'blockade_display': pick('blockade').get('display', ''),
            'blockade_note': hum.get('blockade_note', ''),
            'famine_note': hum.get('famine_note', ''),
            'data_as_of': hum.get('data_as_of', ''),
        }
    c_read = {'present': False}
    if isinstance(com, dict) and com:
        c_read = {'present': True, 'status': com.get('status', ''),
                  'commodities': com.get('commodities', []),
                  'as_of': com.get('as_of', '')}
    return h_read, c_read


def _read_russia_hub():
    fp = _redis_get(RUSSIA_HUB_KEY)
    if not isinstance(fp, dict) or not fp:
        return {'present': False}
    return {'present': True, 'ts': fp.get('ts', ''), 'level': fp.get('level', 0),
            'node_class': fp.get('node_class', '')}


def _write_crosstheater_signal(result, ts, trajectory, hum, com, hub):
    """Triple emission. The TRAJECTORY block is the new payload -- it rides on
    both the collective dict and the canonical fingerprint so the Africa BLUF
    and the Russia hub can each read direction, not just presence."""
    try:
        vl = result.get('vector_levels', {})
        actors = result.get('actors', {})
        actor_levels = {aid: actors.get(aid, {}).get('escalation_level', 0) for aid in ACTORS}
        silence = result.get('silence_anomalies', [])

        slice_ = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Mali', 'country': 'mali',
            'node_class': 'expeditionary_client',
            'level': result.get('theatre_escalation_level', 0),
            'score': result.get('rhetoric_score', 0),
            'theatre_score': result.get('rhetoric_score', 0),
            'actor_levels': actor_levels,
            'vector_levels': vl,
            # ── the hub read, with DIRECTION ──
            'russia_spoke': {
                'level': vl.get('kinetic', 0),
                'trajectory': trajectory['direction'],
                'trajectory_level': trajectory['level'],
                'confidence': trajectory['confidence'],
                'evidence_classes': trajectory['evidence_classes'],
            },
            'trajectory': trajectory,
            'hedging': {'level': vl.get('hedging', 0)},
            'blockade': {'level': vl.get('blockade', 0)},
            'insurgent_convergence': {'level': vl.get('insurgent_convergence', 0)},
            'libya_corridor': {'level': vl.get('libya_corridor', 0)},
            'aes_cohesion': {'level': vl.get('aes_cohesion', 0)},
            'china_touch': {'level': vl.get('china_commercial', 0)},
            'turkey_touch': {'level': vl.get('hedging', 0)},
            'compound_layers': {'humanitarian': hum, 'commodity': com,
                                'russia_hub_parity': hub},
            'silence_anomalies': silence,
        }

        existing = _redis_get(COLLECTIVE_KEY) or {}
        existing['mali'] = slice_
        _redis_set(COLLECTIVE_KEY, existing, ttl=14 * 3600)
        _redis_set(CANONICAL_KEY, slice_, ttl=14 * 3600)
        print(f"[Mali Rhetoric] \u2705 Fingerprint written \u2014 Russia trajectory: "
              f"{trajectory['direction'].upper()} L{trajectory['level']} "
              f"({trajectory['confidence']})")
    except Exception as e:
        print(f"[Mali Rhetoric] Cross-theater write error: {str(e)[:140]}")


# ============================================
# SCAN ORCHESTRATOR
# ============================================
def run_mali_rhetoric_scan(days=3):
    print(f"[Mali Rhetoric] Starting scan ({days}-day window)...")
    articles = fetch_rhetoric_articles(days)

    status, baseline, note = _assess_corpus_health(len(articles))
    if status == 'outage':
        print(f"[Mali Rhetoric] \u26a0\ufe0f CORPUS OUTAGE -- {note}")
        lg = _redis_get(LASTGOOD_KEY) or _redis_get(RHETORIC_CACHE_KEY)
        payload = dict(lg) if isinstance(lg, dict) else {}
        payload.update({'success': True, 'country': 'mali', 'scan_aborted': True,
                        'corpus_health': {'status': 'outage', 'article_count': len(articles),
                                          'baseline': baseline, 'note': note},
                        'stale': bool(payload),
                        'scan_attempted_at': datetime.now(timezone.utc).isoformat()})
        if not payload.get('theatre_label'):
            payload.update({'rhetoric_score': 0, 'theatre_escalation_level': 0,
                            'theatre_label': 'Sensor offline', 'article_count': 0,
                            'top_signals': [], 'actors': {}, 'vector_levels': {}})
        return payload

    actor_results, ts = classify_articles(articles)
    trajectory = _read_trajectory(articles)

    vl = {v: ts[f'{v}_max'] for v, _ in _VECTOR_MAP}
    theatre_level = max(vl.values()) if vl else 0
    spec = ts.get('specificity_scores', [])
    specificity = round(sum(spec) / len(spec), 1) if spec else 0

    # Weighting: kinetic and the blockade lead — the blockade IS Mali's
    # signature mechanism, not a footnote. Hedging is weighted because it is
    # the leading indicator that the Russia dependency is loosening.
    score = min(80,
        vl.get('kinetic', 0) * 7 +
        vl.get('blockade', 0) * 6 +
        vl.get('insurgent_convergence', 0) * 5 +
        vl.get('hedging', 0) * 4 +
        vl.get('libya_corridor', 0) * 3 +
        vl.get('aes_cohesion', 0) * 2 +
        vl.get('china_commercial', 0) * 2)
    hot = sum(1 for a in actor_results.values() if a.get('escalation_level', 0) >= 3)
    score += min(hot * 4, 12)
    if trajectory['direction'] != 'holding' and trajectory['confidence'] != 'claim_sourced':
        score += 4          # a CORROBORATED directional move is itself pressure
    rhetoric_score = max(0, min(100, int(score)))

    hum, com = _read_compound_layers()
    hub = _read_russia_hub()

    result = {
        'success': True, 'country': 'mali', 'theatre': 'Mali',
        'flag': '\U0001F1F2\U0001F1F1',
        'scan_date': datetime.now(timezone.utc).isoformat(),
        'window_days': days, 'article_count': len(articles),
        'corpus_health': {'status': status, 'article_count': len(articles),
                          'baseline': baseline, 'note': note},
        'rhetoric_score': rhetoric_score, 'theatre_score': rhetoric_score,
        'theatre_escalation_level': theatre_level,
        'theatre_label': ESCALATION_LEVELS.get(theatre_level, {}).get('label', 'Unknown'),
        'specificity_score': specificity,
        'vector_levels': vl,
        'trajectory': trajectory,
        'trajectory_caveat': trajectory['caveat'],
        'matched_phrases': sorted(ts.get('matched_phrases', set())),
        'compound_layers': {'humanitarian': hum, 'commodity': com,
                            'russia_hub_parity': hub},
        'actors': actor_results,
        'conditional_threats': ts.get('conditional_threats', [])[:8],
        'disclaimer': 'This composite is a CONVERGENCE indicator, NOT a probability of action.',
    }

    _update_corpus_baseline(len(articles))
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    if TEMPO_EMIT_AVAILABLE and _tempo_emit:
        try:
            for aid, ar in actor_results.items():
                _tempo_emit(theatre='mali', actor=aid,
                            count=ar.get('statement_count', 0),
                            corpus_total=len(articles), mode=ACTORS[aid]['mode'])
        except Exception as e:
            print(f"[Mali Rhetoric] Tempo emit failed (non-fatal): {str(e)[:100]}")

    if _INTERPRETER_AVAILABLE and _mali_interpret_signals:
        try:
            result['interpretation'] = _mali_interpret_signals(result)
        except Exception as e:
            print(f"[Mali Rhetoric] Interpreter error: {str(e)[:120]}")
            result['interpretation'] = {}
    if _INTERPRETER_AVAILABLE and _mali_build_top_signals:
        try:
            result['top_signals'] = _mali_build_top_signals(result)
        except Exception as e:
            print(f"[Mali Rhetoric] build_top_signals error: {str(e)[:120]}")
            result['top_signals'] = []
    else:
        result['top_signals'] = []

    wrote = _redis_set(RHETORIC_CACHE_KEY, result)
    _redis_set(LASTGOOD_KEY, result, ttl=LASTGOOD_TTL)
    result['cache_written'] = bool(wrote)
    if not wrote:
        print("[Mali Rhetoric] \u26a0\ufe0f CACHE WRITE FAILED")

    try:
        snap = json.dumps({'ts': datetime.now(timezone.utc).isoformat(),
                           'score': rhetoric_score, 'level': theatre_level,
                           'trajectory': trajectory['direction'],
                           'trajectory_level': trajectory['level'],
                           **vl})
        if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
            import urllib.parse
            enc = urllib.parse.quote(snap, safe='')
            hdr = {"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}
            requests.post(f"{UPSTASH_REDIS_URL}/lpush/{HISTORY_KEY}/{enc}", headers=hdr, timeout=5)
            requests.post(f"{UPSTASH_REDIS_URL}/ltrim/{HISTORY_KEY}/0/119", headers=hdr, timeout=5)
    except Exception as e:
        print(f"[Mali Rhetoric] History append error (non-fatal): {str(e)[:80]}")

    result['delta'] = _compute_delta()
    _write_crosstheater_signal(result, ts, trajectory, hum, com, hub)

    print(f"[Mali Rhetoric] \u2705 Scan complete \u2014 score {rhetoric_score}, "
          f"L{theatre_level}, Russia {trajectory['direction']}, {len(articles)} articles")
    return result


# ============================================
# BACKGROUND + FLASK
# ============================================
def _bg_rhetoric_scan():
    global _rhetoric_running
    with _rhetoric_lock:
        if _rhetoric_running:
            return
        _rhetoric_running = True
    try:
        if not _acquire_scan_lock():
            print("[Mali Rhetoric] Another worker holds the scan lock — skipping")
            return
        run_mali_rhetoric_scan(days=3)
    except Exception as e:
        print(f"[Mali Rhetoric] Background scan error: {str(e)[:120]}")
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


def start_background_refresh(interval_hours=12):
    """Public entry point matching the app.py scaffolding pattern."""
    def loop():
        time.sleep(150)   # boot delay — distinct from Somalia (90) and Sudan (120)
        while True:
            try:
                _bg_rhetoric_scan()
            except Exception as e:
                print(f"[Mali Rhetoric] Periodic scan error: {str(e)[:100]}")
            time.sleep(interval_hours * 3600)
    threading.Thread(target=loop, daemon=True).start()
    print(f"[Mali Rhetoric] Periodic scan started ({interval_hours}h interval)")


def register_mali_rhetoric_endpoints(app):
    @app.route('/api/rhetoric/mali', methods=['GET'])
    def mali_rhetoric():
        if request.args.get('force', '').lower() in ('true', '1', 'yes'):
            try:
                return jsonify(run_mali_rhetoric_scan(days=3))
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)[:200]}), 500
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            cached['from_cache'] = True
            return jsonify(cached)
        lg = _redis_get(LASTGOOD_KEY)
        if lg:
            lg['from_cache'] = True; lg['stale'] = True
            return jsonify(lg)
        return jsonify({'success': False, 'status': 'no_scan_yet',
                        'message': 'No Mali scan cached. Use ?force=true.'}), 200

    @app.route('/api/rhetoric/mali/summary', methods=['GET'])
    def mali_rhetoric_summary():
        c = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(LASTGOOD_KEY) or {}
        interp = c.get('interpretation', {}) or {}
        return jsonify({
            'country': 'mali',
            'rhetoric_score': c.get('rhetoric_score', 0),
            'theatre_escalation_level': c.get('theatre_escalation_level', 0),
            'theatre_label': c.get('theatre_label', 'Unknown'),
            'vector_levels': c.get('vector_levels', {}),
            'article_count': c.get('article_count', 0),
            'trajectory': c.get('trajectory', {}),
            'top_signals': c.get('top_signals', []),
            'so_what': (interp.get('so_what', {}) or {}),
            'silence_anomalies': c.get('silence_anomalies', []),
            'corpus_health': c.get('corpus_health', {}),
            'scan_date': c.get('scan_date', ''),
            'stale': bool(c.get('stale')),
        })

    @app.route('/api/rhetoric/mali/history', methods=['GET'])
    def mali_rhetoric_history():
        try:
            resp = requests.get(f"{UPSTASH_REDIS_URL}/lrange/{HISTORY_KEY}/0/119",
                                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                                timeout=5)
            hist = [json.loads(x) for x in resp.json().get('result', [])]
            return jsonify({'country': 'mali', 'history': hist, 'count': len(hist)})
        except Exception as e:
            return jsonify({'country': 'mali', 'history': [], 'error': str(e)[:120]})

    @app.route('/debug/rhetoric-mali', methods=['GET'])
    def debug_rhetoric_mali():
        hum, com = _read_compound_layers()
        cached = _redis_get(RHETORIC_CACHE_KEY) or {}
        return jsonify({
            'module': 'rhetoric_tracker_mali v1.0.0',
            'redis_url_set': bool(UPSTASH_REDIS_URL),
            'gdelt_available': GDELT_AVAILABLE,
            'telegram_available': TELEGRAM_AVAILABLE,
            'bluesky_available': BLUESKY_AVAILABLE,
            'interpreter_available': _INTERPRETER_AVAILABLE,
            'tempo_emit_available': TEMPO_EMIT_AVAILABLE,
            'cache_present': bool(cached),
            'last_trajectory': cached.get('trajectory', {}),
            'compound_layer_reads': {'humanitarian': hum, 'commodity': com,
                                     'russia_hub_parity': _read_russia_hub()},
            'actor_roster': list(ACTORS.keys()),
        })

    print("[Mali Rhetoric] \u2705 Routes registered: /api/rhetoric/mali "
          "(+/summary,/history,/debug/rhetoric-mali)")
