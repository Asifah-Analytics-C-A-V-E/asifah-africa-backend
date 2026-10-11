"""
rhetoric_tracker_burkina_faso.py -- Asifah Analytics Africa Backend -- v1.0.0
11 October 2026

TIER-2 SPOKE TRACKER. Burkina Faso is not the main actor page for any wheel we
run. Rachel's ruling, 11 Oct 2026, verbatim:

    "Tier 2 is a 'back end label' not a front end -- but internally, it remains
     as such. B.Faso is not its main actor page, but we watch...."

So this module watches two wheels at reduced weight (Russia, and -- when it
exists -- China), and ONE channel at full weight that belongs to a hub we have
not built yet: the Gulf.

WHY THIS TRACKER IS SHAPED DIFFERENTLY FROM MALI'S
    Mali   A CONTRACT SPOKE. Africa Corps is there under a service agreement.
           "Is Russia gaining or losing" reads directly off deployments,
           casualties, payment disputes, withdrawal signals.
    Burkina NOT A CONTRACT SPOKE. Traore's Russian relationship runs through
           Rosatom and Nordgold more than through troops. A Mali-cloned vector
           set would read Burkina as a WEAK Russia spoke -- few deployments,
           little contract friction -- when the actual dependency is running
           through the mining code, the power sector and the gold corridor.
           Reading that silence as absence is the unread-zero error wearing a
           new hat.

THE THING THE WHEEL MODEL COULD NOT PREVIOUSLY SAY
    Burkina is Tier 2 on Russia, Tier 2 on China, and TIER 1 on a hub that does
    not exist in our architecture -- the UAE. Roughly 32% of Burkinabe gold was
    sold to the Emirates in 2024. Without a way to say "the dominant actor here
    is OFF-WHEEL", a wheel that only knows its own hubs will manufacture a
    Russia story out of a Gulf one, purely by elimination.

    Hence wheel_presence[].dominant_actor_on_wheel. When it reads False, the
    regional BLUF is being told: do not attribute this movement to us.

THE COMMERCIAL AXIS -- THREE STATES, NOT A SCALE
    capture   foreign commercial control INCREASING (acquisition, concession,
              loan-financed infrastructure, equity, operating agreements)
    refusal   the state DISPLACING foreign commercial control (nationalisation,
              state-company creation, self-financed build, local-processing
              mandate, mining-code revision)
    unread    no reporting this cycle

    refusal is NOT "low capture". A quiet quarter and an active nationalisation
    both produce few acquisition headlines; collapsing them into one low number
    is the same lie as an unread zero. Rachel's ruling 11 Oct 2026: proceed with
    three states, modify on what pulls.

    KNOWN PRESSURE POINT, FLAGGED NOT PAPERED OVER: capture and refusal can both
    be hot in the same window -- Nordgold stays while Endeavour and IAMGOLD
    divest. The label picks the dominant direction, but capture_score and
    refusal_score are BOTH carried in the payload so the both-hot case is
    visible in the numbers even when the word hides it. When that case starts
    firing regularly, it is the argument for a fourth state.

KEYWORD DISCIPLINE -- THE RULE THAT COST US TWICE
    Every keyword list in this file was written against VERBATIM published
    headlines (harvested 11 Oct 2026, corpus in the test harness), not against
    example copy invented by the author. Two earlier trackers had lists built
    backwards from imagined text; both matched almost nothing on real wire copy.
    If you add a keyword, add the headline it came from.

    The harness also runs NEGATIVE CONTROLS drawn from Rachel's own live
    commodity card, where global gold-market stories (Dakota Gold in South
    Dakota, a UBS price target) were being scored as Burkina country signals.
    This tracker must not score those.

COMMODITY SIGNALS ARE CONTEXT, NOT SCORE (v1)
    commodity_pressure is READ and DISPLAYED but never scored, because on
    11 Oct 2026 Burkina's commodity card reported 33 "country signals" that
    were 33 GLOBAL gold stories -- signal_count == global_signal_count, every
    one matched on the bare keyword "gold". Promote to scored input only once
    the upstream country filter exists.

EMITS
    rhetoric:burkina_faso:latest        full payload (12h TTL)
    rhetoric:burkina_faso:history       rolling snapshots (336)
    crosstheater:burkina_faso:fingerprint   tier-aware slice for BLUF/GPI

ENDPOINTS
    GET /api/rhetoric/burkina_faso
    GET /api/rhetoric/burkina_faso?refresh=true
    GET /api/rhetoric/burkina_faso/debug

Convergence, not prediction.
COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import threading
import traceback
from datetime import datetime, timezone, timedelta

import requests

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False
    print('[BF Rhetoric] feedparser unavailable -- RSS disabled')

try:
    from burkina_faso_signal_interpreter import (
        build_top_signals,
        build_executive_summary,
        build_so_what_factor,
        score_commercial_axis,
        build_commercial_axis_top_signal,
    )
    BF_INTERPRETER_AVAILABLE = True
    print('[BF Rhetoric] Signal interpreter loaded')
except ImportError:
    BF_INTERPRETER_AVAILABLE = False
    print('[BF Rhetoric] burkina_faso_signal_interpreter not yet deployed '
          '-- builtin fallback prose in use')

try:
    import severity_canon as CANON
    CANON_AVAILABLE = True
except ImportError:
    CANON = None
    CANON_AVAILABLE = False
    print('[BF Rhetoric] severity_canon not deployed on this backend '
          '-- local fallback table in use')

MODULE_VERSION = '1.0.0'

# ════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════
UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL') or '').rstrip('/')
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN') or '')
NEWSAPI_KEY   = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY')

CACHE_TTL_HOURS            = 12
BACKGROUND_REFRESH_HOURS   = 12
INITIAL_SCAN_DELAY_SECONDS = 150   # staggered behind humanitarian + financial

REDIS_KEY_LATEST = 'rhetoric:burkina_faso:latest'
HISTORY_KEY      = 'rhetoric:burkina_faso:history'
FINGERPRINT_KEY  = 'crosstheater:burkina_faso:fingerprint'

# Sibling sensors on THIS backend -- read, never re-fetched (one writer, many readers)
HUMANITARIAN_KEY = 'africa:humanitarian:burkina_faso'

GDELT_BASE_URL   = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI_BASE_URL = 'https://newsapi.org/v2/everything'
BRAVE_BASE_URL   = 'https://api.search.brave.com/res/v1/news/search'

CACHE_FILE = '/tmp/bf_rhetoric_cache.json'
_scan_running = False
_scan_lock = threading.Lock()
_last_scan_started_at = None


# ════════════════════════════════════════════════════════════
# TIER MODEL -- Rachel's ruling, 11 Oct 2026
#
# Tier is a BACKEND weight, never a front-end chip. The HTML must not render
# "TIER 2" anywhere; it changes how much a spoke's movement counts when the
# regional BLUF and the GPI roll it up, and nothing else.
# ════════════════════════════════════════════════════════════
TIER_WEIGHTS = {1: 1.00, 2: 0.60, 3: 0.35}
TIER_FRONT_END_VISIBLE = False

# Front-end-safe wheel descriptions. Say what the actor is DOING here; never
# say what tier it is. Kept separate from tier_rationale so tier language
# cannot leak onto a page through a fallback.
WHEEL_PAGE_NOTES = {
    'russia': ('Present through commercial and energy channels more than troops: '
               'Rosatom (construction agreement Oct 2024, comprehensive agreement '
               'SPIEF Jun 2025, nuclear-liability convention ratified Jan 2026) '
               'and Nordgold staying while Western operators divest. A '
               'troop-counting read scores this near zero and misses it.'),
    'china': ('Trade, health and agro-processing rather than infrastructure debt: '
              'bilateral trade passed $1bn in 2025 (+47.7%), but the flagship road '
              'is state-funded and the BRI loan book is thin. No dedicated actor '
              'in this tracker yet -- reads unread, never absent.'),
    'gulf':  ('The leading external commercial counterparty for Burkinabe gold, '
              'and it belongs to no wheel this platform runs. Roughly 32% of '
              'Burkinabe gold was sold to the UAE in 2024; around a third of '
              'artisanal output leaves via Togo and UAE routes.'),
}

WHEEL_TIERS = {
    # wheel        tier  why
    'russia': (2, 'Present and compounding, but Burkina is not Russia\'s main '
                  'actor page -- Mali is. Commercial and energy channels '
                  '(Rosatom, Nordgold) carry more of this relationship than '
                  'troops do.'),
    'china':  (2, 'BRI MOU signed Nov 2021 but thin hard debt; trade is 12.5:1 '
                  'in China\'s favour and the flagship road is state-funded. '
                  'Watch, do not anchor.'),
    'gulf':   (1, 'TIER 1 AND OFF-WHEEL. ~32% of Burkinabe gold sold to the UAE '
                  'in 2024. The dominant commercial counterparty belongs to a '
                  'hub we have not built. dominant_actor_on_wheel=False exists '
                  'so the BLUF does not attribute this to Russia by elimination.'),
}


# ════════════════════════════════════════════════════════════
# ACTORS -- 8 actors / 4 vectors
#
# Every keyword below is traceable to a verbatim 2026 headline. The headline is
# quoted in the actor's `source_headlines` list. If you add a keyword without a
# headline, you are guessing, and guessing is how the last two keyword lists
# matched nothing.
# ════════════════════════════════════════════════════════════
ACTORS = {
    # ── VECTOR: junta_consolidation ──────────────────────────
    'junta_traore': {
        'name': 'Traore / MPSR', 'flag': '\U0001F1E7\U0001F1EB', 'icon': '\U0001F3DB️',
        'color': '#e2e8f0',
        'role': 'Junta consolidation -- decrees, dissolutions, mobilisation',
        'description': (
            'Traore and the transitional government: party and association '
            'dissolutions, press bans, religious-practice regulation, mass '
            'reservist mobilisation. In 2026 the consolidation tempo has been '
            'the single most legible Burkinabe signal, and it is NOT a '
            'security indicator -- it measures how much of civil society the '
            'state is absorbing.'),
        'vector': 'junta_consolidation',
        'keywords': [
            'traore', 'ibrahim traore', 'captain traore', 'capitaine traore',
            'burkina junta', 'burkinabe junta', 'mpsr',
            'transitional national assembly', 'transitional government',
            'dissolves political parties', 'dissolution of political parties',
            'political parties dissolved', 'party assets',
            'dissolution of 118 associations', 'dissolved over 200 associations',
            'civil society groups', 'dissolution of associations',
            'military reserve', 'reservists',
            'bans tv5monde', 'tv5monde', 'glorifying terrorism',
            'regulating religious practices', 'religious practices',
            'bans us nationals', 'bans american',
            'ouagadougou', 'faso mebo', 'faso mêbo',
        ],
        'source_headlines': [
            '2026-01-29 Burkina Faso military government dissolves all political parties',
            '2026-04-15 dissolution of 118 associations and civil society groups',
            '2026-05-05 bans TV5Monde broadcasts ... glorifying terrorism',
            '2026-04-24 creates new military reserve ... 100,000 reservists',
            '2026-01-01 bans US nationals from entering the country',
        ],
        'baseline_statements_per_week': 7,
    },
    'coup_counterplot': {
        'name': 'Coup / Counter-plot', 'flag': '⚔️', 'icon': '\U0001F5E1️',
        'color': '#f97316',
        'role': 'Regime-security signals -- foiled plots, exile networks, arrests',
        'description': (
            'Announced coup plots, assassination plots, arrest waves and exile '
            'networks. READ WITH CARE: an ANNOUNCED foiled plot is evidence of '
            'the state\'s narrative as much as of a plot. The tracker counts '
            'the announcement; whether the plot was real is an analyst '
            'question this sensor does not answer.'),
        'vector': 'junta_consolidation',
        'keywords': [
            'coup plot', 'coup attempt', 'foiled coup', 'foils coup',
            'coup-plot charges', 'plot to oust', 'destabilization plot',
            'destabilisation plot', 'assassination plot', 'arrests underway',
            'led from exile', 'damiba', 'paul-henri sandaogo damiba',
            'extradited', 'veille citoyenne',
        ],
        'source_headlines': [
            '2026-01-05 authorities say new coup plot foiled, arrests underway',
            '2026-01-05 Foiled Major Destabilization Plot Led from Exile',
            '2026-01-05 Foils Alleged Assassination Plot Against President Ibrahim Traore',
            '2026-01-20 Damiba extradited from Togo to face coup-plot charges',
        ],
        'baseline_statements_per_week': 3,
    },

    # ── VECTOR: insurgent_contest ────────────────────────────
    'jnim_burkina': {
        'name': 'JNIM', 'flag': '\U0001F3F4', 'icon': '\U0001F4A5', 'color': '#dc2626',
        'role': 'Primary insurgency -- attacks, claims, sieges',
        'description': (
            'JNIM (al-Qaeda aligned) across the north, east and increasingly '
            'the centre. Claim tempo plus named-locality specificity moving '
            'together is the pattern worth watching. The siege ledger -- Djibo '
            'blockaded since February 2022, Sebba and Titao since 2022 -- is '
            'the territorial-control reading underneath the attack counts.'),
        'vector': 'insurgent_contest',
        'keywords': [
            'jnim', "jama'at nusrat", 'jama at nusrat', 'nusrat al-islam',
            'claims responsibility', 'suspected jihadists', 'suspected islamists',
            'militants attack', 'attack on a military base', 'military base',
            'soldiers and militiamen', 'soldiers killed', 'police detachment',
            'civilians killed', 'vdp', 'ansaroul islam',
            'djibo', 'sebba', 'titao', 'soum', 'gourma', 'koulpelogo',
            'centre-nord', 'liptako-gourma', 'liptako gourma',
            'besieged', 'blockade', 'encircle',
        ],
        'source_headlines': [
            '2026-01-17 Eleven police officers killed ... Balga, Gourma Province; JNIM claims responsibility',
            '2026-04-22 JNIM militants attack a military base in Bagmoussa, Koulpelogo, killing 28 soldiers and militiamen',
            '2026-03-12 At least 38 civilians killed in a wave of JNIM attacks',
            '2026-03-17 Suspected jihadists attack a village ... killing at least 12',
            '2026-02-16 seven Ghanaian traders killed by suspected Islamists',
        ],
        'baseline_statements_per_week': 8,
    },
    'isgs_burkina': {
        'name': 'ISGS / Inter-jihadist', 'flag': '\U0001F3F4', 'icon': '⚔️',
        'color': '#b91c1c',
        'role': 'Eastern tri-border actor and the JNIM rivalry',
        'description': (
            'Islamic State in the Greater Sahara in the eastern Liptako-Gourma '
            'tri-border. Its rivalry with JNIM produces inter-jihadist fighting '
            'that is a DISTINCT signal from state-insurgent contact -- two '
            'armed groups fighting each other can lower civilian casualties '
            'while territorial control still degrades.'),
        'vector': 'insurgent_contest',
        'keywords': [
            'isgs', 'issp', 'islamic state in the greater sahara',
            'islamic state sahel province', 'inter-jihadist', 'infighting',
            'rival jihadist', 'tri-border', 'tillaberi', 'est region',
        ],
        'source_headlines': [
            'Vocabulary set from Liptako-Gourma reporting; low base rate by '
            'design -- see absence note in _build_actor_summary.',
        ],
        'baseline_statements_per_week': 2,
    },

    # ── VECTOR: external_alignment ───────────────────────────
    'russia_axis_bf': {
        'name': 'Russia Axis', 'flag': '\U0001F1F7\U0001F1FA', 'icon': '\U0001F43B',
        'color': '#0ea5e9',
        'role': 'Africa Corps, Rosatom and Nordgold -- commercial and energy channels',
        'description': (
            'Russia in Burkina runs through THREE channels, and the security '
            'one is the quietest. (1) Africa Corps presence -- real but modest '
            'next to Mali. (2) ROSATOM: roadmap Mar 2023 -> Traore asks Putin '
            'Jul 2023 -> construction agreement Oct 2024 -> comprehensive '
            'cooperation agreement at SPIEF Jun 2025 -> Transitional Assembly '
            'ratifies the Vienna Convention on Civil Liability for Nuclear '
            'Damage Jan 2026. That last step is the LEGAL PRECONDITION for a '
            'build and reads as housekeeping unless you know the chain. '
            '(3) Nordgold stays while Western operators divest. '
            'A troop-counting vector set would score this spoke near zero.'),
        'vector': 'external_alignment',
        'wheel': 'russia',
        'keywords': [
            'africa corps', 'wagner', 'russian instructors',
            'russian military instructors', 'russian mercenaries',
            'nordgold', 'rosatom', 'atomexpo', 'likhachev',
            'russia-africa summit', 'spief',
            'nuclear cooperation agreement', 'nuclear pact', 'nuclear power plant',
            'vienna convention on civil liability', 'civil liability for nuclear damage',
            'moscow', 'kremlin', 'lavrov', 'putin',
        ],
        'source_headlines': [
            '2025-06-24 Russia and Burkina Faso ink comprehensive nuclear cooperation agreement at SPIEF',
            '2025-06-24 Rosatom CEO Alexey Likhachev and Burkina Faso Energy Minister sign nuclear pact',
            '2026-01-27 Transitional National Assembly ratifies the Vienna Convention on Civil Liability for Nuclear Damage',
            "2026-10-09 Central Africa's gold, diamonds and uranium feature in Russia's 30-point plan as Africa Corps maintains its foothold",
        ],
        'baseline_statements_per_week': 3,
    },
    'aes_rupture': {
        'name': 'AES / Western Rupture', 'flag': '\U0001F91D', 'icon': '\U0001F6AA',
        'color': '#a78bfa',
        'role': 'Bloc realignment -- AES, ECOWAS exit, Paris break, expulsions',
        'description': (
            'The Alliance des Etats du Sahel with Mali and Niger, the ECOWAS '
            'withdrawal effective Jan 2025, and the rupture track with Western '
            'capitals -- culminating in Burkina breaking off diplomatic '
            'relations with France in June 2026. Expulsions, ambassador '
            'recalls and broadcast bans ride this actor.'),
        'vector': 'external_alignment',
        'keywords': [
            'aes', 'alliance of sahel states', 'alliance des etats du sahel',
            'sahel confederation', 'ecowas', 'cedeao',
            'breaks off diplomatic relations', 'severs diplomatic relations',
            'cuts ties with france', 'expels', 'expelled', 'persona non grata',
            'ambassador recalled', 'recalls ambassador', 'withdraws from',
            'french troops', 'paris', 'france',
        ],
        'source_headlines': [
            '2026-06-26 Burkina Faso breaks off diplomatic relations with France',
            '2025-01 ECOWAS withdrawal effective with Mali and Niger (AES)',
            '2026-05-05 bans TV5Monde broadcasts (French state broadcaster)',
        ],
        'baseline_statements_per_week': 4,
    },

    # ── VECTOR: commercial_capture ───────────────────────────
    'resource_sovereignty': {
        'name': 'Resource Sovereignty', 'flag': '⛏️', 'icon': '\U0001F3F4',
        'color': '#22c55e',
        'role': 'THE REFUSAL SIDE -- nationalisation, state miner, self-build',
        'description': (
            'The state displacing foreign commercial control: SOPAMIB (created '
            '2024, took the Boungou and Wahgnion mines), the 2024 mining code '
            'raising free-carried state interest with local-ownership '
            'mandates, the first national gold refinery (28 Sep 2026, CFA 11bn, '
            '164 t/yr against ~55-60 t/yr national output), and the '
            'state-funded Faso Mebo expressway. '
            'THE REFINERY IS THE TEST CASE: under a capture-only vector it '
            'reads as nothing happening. It is a refusal event with regional '
            'reach -- 164 t/yr is built for Mali\'s and Niger\'s gold too.'),
        'vector': 'commercial_capture',
        'axis_side': 'refusal',
        'keywords': [
            'sopamib', 'state miner', 'state-owned miner', 'national mining company',
            'mining code', 'free-carried', 'local ownership', 'local-ownership',
            'nationalis', 'nationaliz', 'seizes mine', 'mine seizure',
            'takes over the', 'boungou', 'wahgnion', 'essakane', 'houndé', 'hounde',
            'mana mine', 'bombore', 'yaramoko',
            'gold refinery', 'refinery', 'refine', 'keep mining profits at home',
            'faso mebo', 'faso mêbo', 'expressway',
            'local processing', 'technology transfer', 'production units',
            'withdraws permit', 'revokes permit', 'permit revoked',
        ],
        'source_headlines': [
            "2026-09-28 Burkina Faso's junta leader opens major gold refinery to keep mining profits at home",
            '2026-09-29 inaugurates first gold refinery with 164 tonnes annual capacity',
            '2024-08 state miner SOPAMIB takes over Boungou and Wahgnion mines',
            '2024-07 new mining code raising state free-carried interest with local ownership mandates',
            '2025-12-16 Ouagadougou-Bobo-Dioulasso expressway under Faso Mebo initiative',
            '2026-09-09 seeks to shift China ties toward production and technology transfer',
        ],
        'baseline_statements_per_week': 3,
    },
    'gulf_gold_channel': {
        'name': 'Gulf Gold Channel', 'flag': '\U0001F1E6\U0001F1EA', 'icon': '\U0001F947',
        'color': '#f59e0b',
        'role': 'The gold corridor -- leading commercial counterparty, off-wheel',
        'description': (
            'The dominant external commercial counterparty for Burkinabe gold, '
            'and it belongs to a hub we have not built. Roughly 32% of '
            'Burkinabe gold was sold to the UAE in 2024; an estimated third of '
            'ARTISANAL output is smuggled out via Togo and UAE routes. '
            'The new refinery holds no LBMA Good Delivery accreditation -- only '
            'Rand Refinery in South Africa does, and the standard requires '
            '~$20m net worth, several years of operation and a responsible-'
            'sourcing audit in a country where JNIM taxes artisanal sites. '
            'So the bars have to go somewhere that does not require Good '
            'Delivery. WHO BUYS THE BARS is the whole analytic payload.'),
        'vector': 'commercial_capture',
        'axis_side': 'capture',
        'wheel': 'gulf',
        'keywords': [
            'uae', 'emirates', 'emirati', 'dubai', 'abu dhabi', 'dmcc',
            'gold smuggling', 'smuggled gold', 'artisanal gold', 'artisanal mining',
            'gold exports to', 'gold trafficking', 'togo route',
            'lbma', 'good delivery', 'accreditation', 'rand refinery',
            'zijin', 'allied gold', 'endeavour mining', 'iamgold',
            'divest', 'divesting', 'acquisition', 'acquires', 'stake in',
        ],
        'source_headlines': [
            '2025-12-14 Sahel: gold at the heart of relations with the United Arab Emirates',
            "2026-03-30 China's Zijin accelerates West Africa gold push with $2.6 billion acquisition",
            '2026-07-06 Why West African gold refineries still depend on a London institution (LBMA)',
        ],
        'baseline_statements_per_week': 2,
    },
}

# ════════════════════════════════════════════════════════════
# VALIDATION STATUS -- measured, not asserted
#
# Each actor's keyword list was run against the verbatim 2026 headline corpus
# on 11 Oct 2026. These are the MEASURED results, recorded here so the page and
# the BLUF can tell a tested silence from an untested one.
#
# An UNVALIDATED actor reading 'low' has not told you the actor is quiet. It
# has told you we never proved the list can match anything. That is an unread
# zero with better manners, and it gets labelled as such.
# ════════════════════════════════════════════════════════════
ACTOR_VALIDATION = {
    'junta_traore':         {'status': 'validated',   'real_headlines_matched': 12},
    'coup_counterplot':     {'status': 'validated',   'real_headlines_matched': 5},
    'jnim_burkina':         {'status': 'validated',   'real_headlines_matched': 5},
    'resource_sovereignty': {'status': 'validated',   'real_headlines_matched': 6},
    'russia_axis_bf':       {'status': 'validated',   'real_headlines_matched': 2},
    'gulf_gold_channel':    {'status': 'validated',   'real_headlines_matched': 2,
                             'note': 'Matches only via the conjunctive corridor '
                                     'gate -- its coverage is regional and often '
                                     'never says "Burkina".'},
    'aes_rupture':          {'status': 'thin',        'real_headlines_matched': 1,
                             'note': 'CORPUS-thin, not necessarily keyword-thin: '
                                     'the harvested chronology had an explicit gap '
                                     'on AES/ECOWAS. Needs a real AES headline '
                                     'harvest before its silence can be trusted.'},
    'isgs_burkina':         {'status': 'unvalidated', 'real_headlines_matched': 0,
                             'note': 'ZERO real headlines in the corpus. ISGS is '
                                     'genuinely lower-volume than JNIM in Burkinabe '
                                     'coverage, but zero matched means UNTESTED. '
                                     'Reads unread, never calm.'},
}
VALIDATION_AS_OF = '2026-10-11'
VALIDATION_CORPUS_NOTE = (
    '33 verbatim 2026 Burkina headlines + 10 negative controls, 7 of which were '
    'taken from the live commodity card where they were being mis-scored as '
    'Burkina country signals. Negative-control leaks at validation: 0/10.')


VECTOR_GROUPS = {
    'junta_consolidation': ['junta_traore', 'coup_counterplot'],
    'insurgent_contest':   ['jnim_burkina', 'isgs_burkina'],
    'external_alignment':  ['russia_axis_bf', 'aes_rupture'],
    'commercial_capture':  ['resource_sovereignty', 'gulf_gold_channel'],
}

VECTOR_LABELS = {
    'junta_consolidation': 'Junta Consolidation',
    'insurgent_contest':   'Insurgent Contest',
    'external_alignment':  'External Alignment',
    'commercial_capture':  'Commercial Capture',
}

# Which actors feed which side of the three-state commercial axis
AXIS_CAPTURE_ACTORS = ['gulf_gold_channel']
AXIS_REFUSAL_ACTORS = ['resource_sovereignty']


# ════════════════════════════════════════════════════════════
# COUNTRY GATE -- the fix for the bug we found on the live card
#
# On 11 Oct 2026 Burkina's commodity card reported 33 "country signals" that
# were 33 GLOBAL gold stories: Dakota Gold in South Dakota, a UBS price target,
# PBoC reserve purchases. Every one matched the bare keyword "gold".
#
# So: an article must pass this gate BEFORE any actor keyword is tested. A
# story about gold that is not about Burkina Faso or its immediate theatre is
# not a Burkina signal, however many times it says "gold".
# ════════════════════════════════════════════════════════════
COUNTRY_GATE = [
    'burkina', 'ouagadougou', 'ouaga', 'bobo-dioulasso', 'burkinabe',
    'burkinabè', 'traore', 'traoré', 'sopamib', 'djibo', 'sebba',
    'titao', 'soum', 'gourma', 'koulpelogo', 'bagmoussa', 'balga',
    'faso mebo', 'faso mêbo', 'damiba', 'boungou', 'wahgnion',
    'liptako-gourma', 'liptako gourma',
]

# A story may ALSO pass the gate when it is explicitly about the AES bloc
# acting as a bloc -- Burkina is a named member and bloc decisions bind it.
BLOC_GATE = [
    'alliance of sahel states', 'alliance des etats du sahel',
    'aes states', 'aes bloc', 'sahel confederation',
]

# ── THE CORRIDOR GATE -- CONJUNCTIVE, and it exists because of a real miss ──
#
# Validation on 11 Oct 2026 showed gulf_gold_channel matching ZERO real
# headlines. The reason was mine, not the feed's: the Gulf channel's defining
# coverage is REGIONAL and frequently never says the word "Burkina" --
# "Sahel: gold at the heart of relations with the United Arab Emirates" is
# exactly the story we most want, and the country gate was throwing it away.
#
# The fix is a gate that requires BOTH halves: a Sahel/regional context term
# AND a specific gold-corridor term. Conjunctive is the whole point. "Gold
# Outlook 2026" has the commodity and no region; "Sahel displacement snapshot"
# has the region and no corridor. Neither passes. Only a story that is about
# THIS commodity moving through THIS region does.
CORRIDOR_REGION = [
    'sahel', 'west africa', 'west african', 'afrique de l\'ouest',
    'uemoa', 'waemu', 'ecowas', 'cedeao', 'aes',
]
CORRIDOR_CHANNEL = [
    'uae', 'emirates', 'emirati', 'dubai', 'abu dhabi', 'dmcc',
    'gold smuggling', 'smuggled gold', 'gold trafficking', 'artisanal gold',
    'lbma', 'good delivery', 'rand refinery', 'gold refinery',
    'zijin', 'allied gold', 'endeavour mining', 'iamgold', 'nordgold',
]


# ════════════════════════════════════════════════════════════
# TRIPWIRES -- low-base-rate, high-impact. Severity 5 entries are the ONLY
# things that can open the L5 gate, and each names its axis.
# ════════════════════════════════════════════════════════════
TRIPWIRES = {
    'regime_change_event': {
        'patterns': ['coup succeeds', 'seizes power', 'ousted', 'overthrown',
                     'new transitional president', 'traore killed',
                     'traore assassinated'],
        'severity': 'surge', 'l5_axis': 'kinetic',
        'note': 'An ACTUAL change of regime, not an announced foiled plot.',
    },
    'capital_threatened': {
        'patterns': ['ouagadougou under attack', 'attack on ouagadougou',
                     'ouagadougou blockade', 'siege of ouagadougou',
                     'jnim reaches ouagadougou'],
        'severity': 'surge', 'l5_axis': 'kinetic',
        'note': 'The Bamako-blockade analogue arriving at the Burkinabe capital.',
    },
    'mass_casualty_event': {
        'patterns': ['killing 28 soldiers', 'massacre', 'mass casualty',
                     'dozens of civilians killed', 'hundreds killed',
                     'deadliest attack'],
        'severity': 'high', 'l5_axis': None,
        'note': 'Solhan (2021, 160+), Karma (2023, 100+), Barsalogho (2024, ~200+) class.',
    },
    'siege_breaks': {
        'patterns': ['djibo falls', 'djibo captured', 'besieged town falls',
                     'town overrun', 'garrison overrun'],
        'severity': 'surge', 'l5_axis': 'humanitarian',
        'note': 'A besieged town falling puts ~800K non-moveable people in play.',
    },
    'mine_nationalisation': {
        'patterns': ['nationalises mine', 'nationalizes mine', 'seizes mine',
                     'takes over the mine', 'withdraws mining permit',
                     'revokes mining permit', 'sopamib takes over'],
        'severity': 'elevated', 'l5_axis': None,
        'note': 'REFUSAL-side event. Swings the commercial axis hard.',
    },
    'foreign_operator_exit': {
        'patterns': ['divests from burkina', 'exits burkina', 'suspends operations',
                     'withdraws from burkina', 'sells its stake'],
        'severity': 'elevated', 'l5_axis': None,
        'note': 'Ambiguous by construction -- reads as refusal if pushed, '
                'capture if a non-Western buyer is named in the same window.',
    },
    'refinery_accreditation': {
        'patterns': ['lbma accreditation', 'good delivery list', 'accredited refinery',
                     'lbma approves'],
        'severity': 'elevated', 'l5_axis': None,
        'note': 'WATCH ITEM. Would let Burkinabe bars into the Western market '
                'and change who can buy them. Expected absent for years.',
    },
    'diplomatic_rupture': {
        'patterns': ['breaks off diplomatic relations', 'severs diplomatic relations',
                     'expels ambassador', 'closes embassy', 'recalls its ambassador'],
        'severity': 'high', 'l5_axis': 'diplomatic',
        'note': 'France, June 2026 is the precedent in-period.',
    },
    'aes_fracture': {
        'patterns': ['leaves the aes', 'quits the alliance', 'aes collapses',
                     'rejoins ecowas', 'returns to ecowas'],
        'severity': 'surge', 'l5_axis': 'diplomatic',
        'note': 'The bloc coming apart would re-price all three AES trackers.',
    },
    'corridor_closure': {
        'patterns': ['border closed', 'closes border', 'corridor closed',
                     'abidjan corridor', 'suspends transit', 'blocks transit'],
        'severity': 'high', 'l5_axis': 'economic',
        'note': 'Landlocked: gold out and fuel in cross four neighbours.',
    },
}


# ════════════════════════════════════════════════════════════
# FEEDS -- EN + FR. French matters here more than in most of our theatres:
# Burkinabe official communication, AIB and Sidwaya publish in French first.
# ════════════════════════════════════════════════════════════
RSS_FEEDS = {
    'gn_en': {
        'url': ('https://news.google.com/rss/search?q=%22Burkina+Faso%22+OR+Ouagadougou'
                '+OR+Traore&hl=en-US&gl=US&ceid=US:en'),
        'name': 'GoogleNews-EN', 'weight': 0.85, 'language': 'en'},
    'gn_fr': {
        'url': ('https://news.google.com/rss/search?q=%22Burkina+Faso%22+OR+Ouagadougou'
                '&hl=fr&gl=FR&ceid=FR:fr'),
        'name': 'GoogleNews-FR', 'weight': 0.85, 'language': 'fr'},
    'gn_mining': {
        'url': ('https://news.google.com/rss/search?q=%22Burkina+Faso%22+(mine+OR+gold'
                '+OR+SOPAMIB+OR+refinery)&hl=en-US&gl=US&ceid=US:en'),
        'name': 'GoogleNews-Mining', 'weight': 0.85, 'language': 'en'},
    'apa':      {'url': 'https://www.apanews.net/feed/', 'name': 'APA News',
                 'weight': 0.9, 'language': 'fr'},
    'rfi_af':   {'url': 'https://www.rfi.fr/fr/afrique/rss', 'name': 'RFI Afrique',
                 'weight': 0.95, 'language': 'fr'},
    'reliefweb': {'url': 'https://reliefweb.int/country/bfa/rss.xml',
                  'name': 'ReliefWeb BFA', 'weight': 1.0, 'language': 'en'},
}

GDELT_QUERIES_EN = [
    '"Burkina Faso" AND ("JNIM" OR "attack" OR "soldiers")',
    '"Burkina Faso" AND ("coup" OR "plot" OR "Traore")',
    '"Burkina Faso" AND ("SOPAMIB" OR "mining code" OR "refinery" OR "Nordgold")',
    '"Burkina Faso" AND ("Russia" OR "Rosatom" OR "Africa Corps" OR "AES")',
]
GDELT_QUERIES_FR = [
    '"Burkina Faso" ET ("putsch" OU "attaque" OU "Traoré")',
    '"Burkina Faso" ET ("mine" OU "or" OU "raffinerie")',
]


# ════════════════════════════════════════════════════════════
# REDIS
# ════════════════════════════════════════════════════════════
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        r = requests.get('%s/get/%s' % (UPSTASH_REDIS_URL, key),
                         headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
                         timeout=8)
        if r.status_code != 200:
            return None
        raw = r.json().get('result')
        return json.loads(raw) if raw else None
    except Exception as e:
        print('[BF Rhetoric] redis get %s: %s' % (key, str(e)[:100]))
        return None


def _redis_set(key, value, ttl_hours=CACHE_TTL_HOURS):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        r = requests.post(UPSTASH_REDIS_URL,
                          headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
                          json=['SET', key, json.dumps(value, default=str),
                                'EX', str(int(ttl_hours * 3600))],
                          timeout=8)
        return r.status_code == 200
    except Exception as e:
        print('[BF Rhetoric] redis set %s: %s' % (key, str(e)[:100]))
        return False


def _redis_lpush_trim(key, value, max_len=336):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        r = requests.post(UPSTASH_REDIS_URL,
                          headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
                          json=['LPUSH', key, json.dumps(value, default=str)],
                          timeout=8)
        requests.post(UPSTASH_REDIS_URL,
                      headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
                      json=['LTRIM', key, '0', str(max_len - 1)], timeout=8)
        return r.status_code == 200
    except Exception as e:
        print('[BF Rhetoric] redis lpush %s: %s' % (key, str(e)[:100]))
        return False


def load_cache():
    cached = _redis_get(REDIS_KEY_LATEST)
    if cached:
        return cached
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_cache(data):
    data['cached_at'] = datetime.now(timezone.utc).isoformat()
    _redis_set(REDIS_KEY_LATEST, data, ttl_hours=CACHE_TTL_HOURS)
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f, default=str)
    except Exception:
        pass


def is_cache_fresh(data):
    if not data or 'cached_at' not in data:
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(data['cached_at'])
        return age.total_seconds() < CACHE_TTL_HOURS * 3600
    except Exception:
        return False


# ════════════════════════════════════════════════════════════
# MATCHING
# ════════════════════════════════════════════════════════════
_WB_CACHE = {}


def _kw_in(kw, body):
    """Substring match, with a WORD-BOUNDARY rule for short keywords.

    Without this, 'aes' matches 'faeces' and 'or' (French for gold) matches
    every third word. Long or multi-word keywords use plain containment,
    which is what we want for 'coup plot' and 'gold refinery'.
    """
    if (' ' in kw) or ('-' in kw) or len(kw) > 4:
        return kw in body
    pat = _WB_CACHE.get(kw)
    if pat is None:
        pat = re.compile(r'(?<![a-z0-9à-ÿ])' + re.escape(kw)
                         + r'(?![a-z0-9à-ÿ])')
        _WB_CACHE[kw] = pat
    return pat.search(body) is not None


def _norm(text):
    return (text or '').lower()


def passes_country_gate(article):
    """True when the article is plausibly ABOUT Burkina Faso or the AES bloc.

    Runs BEFORE any actor keyword. This is the specific defence against the
    defect found on the live commodity card, where global gold-market stories
    were scored as Burkina country signals.
    """
    body = _norm(article.get('title', '')) + ' ' + _norm(article.get('description', ''))
    for kw in COUNTRY_GATE:
        if _kw_in(kw, body):
            return True, 'country'
    for kw in BLOC_GATE:
        if _kw_in(kw, body):
            return True, 'bloc'
    # Conjunctive corridor gate -- BOTH halves required.
    if (any(_kw_in(k, body) for k in CORRIDOR_REGION)
            and any(_kw_in(k, body) for k in CORRIDOR_CHANNEL)):
        return True, 'corridor'
    return False, None


def _classify_article(article):
    """Return [(actor_id, hit_count)] for a GATED article. Multi-actor allowed."""
    body = _norm(article.get('title', '')) + ' ' + _norm(article.get('description', ''))
    out = []
    for actor_id, a in ACTORS.items():
        hits = sum(1 for kw in a['keywords'] if _kw_in(kw.lower(), body))
        if hits:
            out.append((actor_id, hits))
    return out


def _check_tripwires(text):
    body = _norm(text)
    fired = []
    for tw_id, tw in TRIPWIRES.items():
        for p in tw['patterns']:
            if p.lower() in body:
                fired.append((tw_id, tw['severity'], tw.get('l5_axis')))
                break
    return fired


def actor_alert_level(score, baseline):
    if score < baseline * 0.5:
        return 'low'
    if score < baseline * 1.0:
        return 'normal'
    if score < baseline * 1.8:
        return 'elevated'
    if score < baseline * 2.8:
        return 'high'
    return 'surge'


_LEVEL_ORDER = ['low', 'normal', 'elevated', 'high', 'surge']


def _rank(lv):
    try:
        return _LEVEL_ORDER.index(lv)
    except ValueError:
        return 0


# ════════════════════════════════════════════════════════════
# FETCHERS
# ════════════════════════════════════════════════════════════
def fetch_rss(feed_id, cfg, max_items=30):
    if not FEEDPARSER_AVAILABLE:
        return []
    out = []
    try:
        feed = feedparser.parse(cfg['url'])
        for e in feed.entries[:max_items]:
            out.append({
                'title': e.get('title', ''),
                'description': e.get('summary', '') or e.get('description', ''),
                'url': e.get('link', ''),
                'published': e.get('published', ''),
                'source': cfg['name'], 'feed_id': feed_id, 'feed_type': 'rss',
                'language': cfg.get('language', 'en'),
                'feed_weight': cfg.get('weight', 1.0),
            })
    except Exception as e:
        print('[BF Rhetoric] RSS %s: %s' % (feed_id, str(e)[:100]))
    return out


def fetch_all_rss():
    out = []
    for fid, cfg in RSS_FEEDS.items():
        got = fetch_rss(fid, cfg)
        if got:
            print('[BF Rhetoric] RSS %s: %d' % (fid, len(got)))
        out.extend(got)
    return out


def fetch_gdelt(query, lang='eng', days=7, maxrec=50):
    try:
        r = requests.get(GDELT_BASE_URL, params={
            'query': '%s sourcelang:%s' % (query, lang), 'mode': 'artlist',
            'maxrecords': maxrec, 'format': 'json', 'timespan': '%dd' % days,
        }, timeout=(5, 12))
        if r.status_code != 200:
            return []
        return [{
            'title': i.get('title', ''), 'description': '',
            'url': i.get('url', ''), 'published': i.get('seendate', ''),
            'source': i.get('domain', 'GDELT'), 'feed_id': 'gdelt',
            'feed_type': 'gdelt',
            'language': 'fr' if lang == 'fra' else 'en', 'feed_weight': 0.85,
        } for i in r.json().get('articles', [])]
    except Exception:
        return []


def fetch_all_gdelt(days=7):
    out = []
    for q in GDELT_QUERIES_EN:
        out.extend(fetch_gdelt(q, 'eng', days))
        time.sleep(0.5)
    for q in GDELT_QUERIES_FR:
        out.extend(fetch_gdelt(q, 'fra', days))
        time.sleep(0.5)
    print('[BF Rhetoric] GDELT: %d' % len(out))
    return out


def fetch_newsapi(days=7):
    if not NEWSAPI_KEY:
        return []
    frm = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    out = []
    for q in ['Burkina Faso JNIM attack', 'Burkina Faso Traore junta',
              'Burkina Faso gold mining SOPAMIB', 'Burkina Faso Russia AES']:
        try:
            r = requests.get(NEWSAPI_BASE_URL, params={
                'q': q, 'from': frm, 'sortBy': 'publishedAt',
                'pageSize': 30, 'apiKey': NEWSAPI_KEY}, timeout=10)
            if r.status_code != 200:
                continue
            for i in r.json().get('articles', []):
                out.append({
                    'title': i.get('title', ''), 'description': i.get('description', ''),
                    'url': i.get('url', ''), 'published': i.get('publishedAt', ''),
                    'source': (i.get('source') or {}).get('name', 'NewsAPI'),
                    'feed_id': 'newsapi', 'feed_type': 'newsapi',
                    'language': 'en', 'feed_weight': 0.9,
                })
        except Exception:
            pass
        time.sleep(0.5)
    if out:
        print('[BF Rhetoric] NewsAPI: %d' % len(out))
    return out


def fetch_brave(gdelt_n=0, news_n=0):
    """Tertiary -- only when the primaries came back thin."""
    if not BRAVE_API_KEY or (gdelt_n + news_n) >= 10:
        return []
    out = []
    for q in ['Burkina Faso Traore 2026', 'Burkina Faso JNIM', 'Burkina Faso gold refinery']:
        try:
            r = requests.get(BRAVE_BASE_URL, params={'q': q, 'count': 20},
                             headers={'Accept': 'application/json',
                                      'X-Subscription-Token': BRAVE_API_KEY},
                             timeout=10)
            if r.status_code != 200:
                continue
            for i in r.json().get('results', []):
                out.append({
                    'title': i.get('title', ''), 'description': i.get('description', ''),
                    'url': i.get('url', ''), 'published': i.get('age', ''),
                    'source': i.get('source') or 'Brave', 'feed_id': 'brave',
                    'feed_type': 'brave', 'language': 'en', 'feed_weight': 0.75,
                })
        except Exception:
            pass
        time.sleep(0.5)
    if out:
        print('[BF Rhetoric] Brave: %d' % len(out))
    return out


# ════════════════════════════════════════════════════════════
# SIBLING SENSOR READS -- context, never re-fetched, never re-scored
# ════════════════════════════════════════════════════════════
def _read_humanitarian_context():
    """Read the humanitarian sensor's own output. ONE writer, many readers."""
    h = _redis_get(HUMANITARIAN_KEY) or {}
    if not h:
        return {'available': False,
                'note': 'Humanitarian sensor key absent this cycle -- unread, not calm.'}
    stats = {}
    for s in (h.get('headline_stats') or []):
        if 'besieged' in (s.get('label') or '').lower():
            stats['besieged'] = s.get('value')
        elif (s.get('label') or '').startswith('Internally displaced'):
            stats['idps'] = s.get('value')
    cal = h.get('seasonal_calendar') or {}
    return {
        'available': True,
        'besieged': stats.get('besieged'),
        'idps': stats.get('idps'),
        'live_dtm': h.get('live_dtm'),
        'seasonal_open': cal.get('open_now') or [],
        'data_as_of': h.get('data_as_of'),
    }


def _read_commodity_context():
    """CONTEXT ONLY -- explicitly NOT scored. See module docstring.

    The upstream country filter does not exist yet: on 11 Oct 2026 this payload
    reported signal_count == global_signal_count == 33 for Burkina, and the
    signals were global gold-market stories. We display the price and the
    structural note; we discard the signal counts rather than score noise.
    """
    try:
        from commodity_proxy_africa import get_africa_commodity_data
    except ImportError:
        return {'available': False, 'reason': 'commodity proxy not importable'}
    try:
        d = get_africa_commodity_data('burkina_faso') or {}
        for t in (d.get('commodity_summaries') or []):
            if t.get('commodity') != 'gold':
                continue
            sp = t.get('sparkline') or {}
            return {
                'available': True,
                'scored': False,
                'gold_price': sp.get('price'),
                'gold_change_pct_1d': sp.get('change_pct_1d'),
                'gold_change_pct_30d': sp.get('change_pct_30d'),
                'structural_note': t.get('note'),
                'upstream_signal_count_DISCARDED': t.get('signal_count'),
                'discard_reason': (
                    'Upstream has no country filter: signal_count equals '
                    'global_signal_count, and sampled signals were global '
                    'gold-market stories unrelated to Burkina Faso. Promote to '
                    'scored input only once upstream filters by country.'),
            }
    except Exception as e:
        return {'available': False, 'reason': str(e)[:120]}
    return {'available': False, 'reason': 'no gold tile in commodity payload'}


def _read_crosstheater_amplifiers():
    """Sibling wheel fingerprints. Absence-honest: missing means unread."""
    amps = {}
    for label, key in (('russia_fingerprint', 'crosstheater:russia:fingerprint'),
                       ('mali_fingerprint',   'crosstheater:mali:fingerprint'),
                       ('niger_fingerprint',  'crosstheater:niger:fingerprint'),
                       ('uae_fingerprint',    'crosstheater:uae:fingerprint')):
        v = _redis_get(key)
        if v:
            amps[label] = v
    return amps


# ════════════════════════════════════════════════════════════
# THE THREE-STATE COMMERCIAL AXIS
# ════════════════════════════════════════════════════════════
def _score_commercial_axis_builtin(actor_summaries, tripwires):
    """capture / refusal / unread -- Rachel's ruling, 11 Oct 2026.

    Both side-scores are returned whatever the label says, because the
    interesting case is BOTH hot (Nordgold stays while Endeavour divests) and a
    single word cannot carry that.
    """
    cap = sum(_rank((actor_summaries.get(a) or {}).get('level', 'low'))
              for a in AXIS_CAPTURE_ACTORS)
    ref = sum(_rank((actor_summaries.get(a) or {}).get('level', 'low'))
              for a in AXIS_REFUSAL_ACTORS)

    tw_ids = {t.get('id') for t in (tripwires or []) if isinstance(t, dict)}
    if 'mine_nationalisation' in tw_ids:
        ref += 2
    if 'refinery_accreditation' in tw_ids:
        ref += 1
    if 'foreign_operator_exit' in tw_ids:
        # Genuinely ambiguous -- counts to BOTH, which keeps it from silently
        # tipping the label in either direction on its own.
        cap += 1
        ref += 1

    both_hot = cap >= 2 and ref >= 2

    if cap == 0 and ref == 0:
        state = 'unread'
        reading = ('No commercial-direction reporting this cycle. This is an '
                   'UNREAD axis, not a settled one -- Burkina\'s gold '
                   'relationships do not go quiet, our feeds do.')
    elif ref > cap:
        state = 'refusal'
        reading = ('State displacement of foreign commercial control is '
                   'outpacing foreign acquisition. The refinery, SOPAMIB and '
                   'the self-funded expressway are the shape of this: a '
                   'producer building its own exit rather than selling access '
                   'to one.')
    elif cap > ref:
        state = 'capture'
        reading = ('Foreign commercial positioning is outpacing state '
                   'displacement. Watch WHOSE -- the Gulf channel and a '
                   'Chinese acquisition read identically on volume and '
                   'differently on everything else.')
    else:
        # Tie with both sides live -- report the tie rather than coin-flip it.
        state = 'refusal' if ref else 'unread'
        reading = ('Capture and refusal are scoring level this cycle. The label '
                   'picks a side; the scores below do not. Read both.')

    return {
        'id': 'commercial_axis_burkina_faso',
        'state': state,
        'capture_score': cap,
        'refusal_score': ref,
        'both_hot': both_hot,
        'both_hot_note': (
            'Capture AND refusal are both live. This is the Nordgold-stays-'
            'while-Endeavour-divests case. If this keeps firing it is the '
            'argument for a fourth state; logged, not papered over.'
        ) if both_hot else None,
        'reading': reading,
        'states_defined': ['capture', 'refusal', 'unread'],
        'disclaimer': (
            'A CONVERGENCE read on commercial direction, not a prediction. '
            'refusal is not low capture: a quiet quarter and an active '
            'nationalisation both produce few acquisition headlines.'),
        'leading_indicators': [
            'SOPAMIB portfolio changes and further mine seizures',
            'Nordgold footprint vs Western operator divestment announcements',
            'Any LBMA Good Delivery application or accreditation',
            'Refinery throughput vs the ~55-60 t/yr national production figure',
            'UAE import statistics against Burkinabe declared exports',
            'Rosatom build milestones after the Jan 2026 Vienna Convention ratification',
        ],
    }


# ════════════════════════════════════════════════════════════
# WHEEL PRESENCE -- tier-aware, and able to say "not us"
# ════════════════════════════════════════════════════════════
def _build_wheel_presence(actor_summaries, commercial_axis):
    """Per-wheel slice with tier weight and the off-wheel flag.

    dominant_actor_on_wheel=False is the field that stops the BLUF from
    manufacturing a Russia story out of a Gulf one by elimination.
    """
    def slice_for(wheel, actor_key, role):
        tier, why = WHEEL_TIERS[wheel]
        lvl = (actor_summaries.get(actor_key) or {}).get('level', 'low')
        raw = _rank(lvl)
        return {
            'wheel': wheel,
            'tier': tier,
            'tier_weight': TIER_WEIGHTS.get(tier, 1.0),
            'tier_rationale': why,
            # page_note is the FRONT-END-SAFE string. tier_rationale is the
            # back-end explanation and contains tier language by design -- the
            # Gulf one literally opens "TIER 1 AND OFF-WHEEL". A page that
            # falls back to tier_rationale therefore renders a tier chip in
            # prose, which is exactly what the 11 Oct ruling forbids. Caught in
            # render validation the same day. The page reads page_note and
            # never tier_rationale; this field is why it can.
            'page_note': WHEEL_PAGE_NOTES.get(wheel, ''),
            'front_end_visible': TIER_FRONT_END_VISIBLE,
            'level': lvl,
            'role': role,
            'active': lvl in ('elevated', 'high', 'surge'),
            'raw_rank': raw,
            'weighted_rank': round(raw * TIER_WEIGHTS.get(tier, 1.0), 2),
        }

    russia = slice_for('russia', 'russia_axis_bf', 'commercial_and_energy_more_than_kinetic')
    gulf = slice_for('gulf', 'gulf_gold_channel', 'dominant_commercial_counterparty')

    # China: no dedicated actor yet. Declared DARK rather than omitted, so the
    # absence is visible instead of being read as "no Chinese presence".
    china = {
        'wheel': 'china', 'tier': WHEEL_TIERS['china'][0],
        'tier_weight': TIER_WEIGHTS[WHEEL_TIERS['china'][0]],
        'tier_rationale': WHEEL_TIERS['china'][1],
        'front_end_visible': TIER_FRONT_END_VISIBLE,
        'level': 'unread', 'role': 'trade_and_agro_processing',
        'active': False, 'raw_rank': None, 'weighted_rank': None,
        'page_note': WHEEL_PAGE_NOTES['china'],
        'instrumentation': 'DARK -- NO DEDICATED ACTOR',
        'note': ('China is present (trade >$1bn in 2025, +47.7% YoY; hospital '
                 'and solar projects; May 2026 agro-processing agreements) but '
                 'has no actor in this tracker yet. Reads as unread, never as '
                 'absent.'),
    }

    return {
        'russia': russia,
        'china': china,
        'gulf': gulf,
        # THE FIELD THAT MATTERS. Gulf is tier 1 and off-wheel.
        'dominant_actor_on_wheel': not gulf['active'],
        'dominant_actor_note': (
            'Gulf channel is active and belongs to a hub we have not built. '
            'Do NOT attribute this movement to Russia or China by elimination.'
        ) if gulf['active'] else (
            'No off-wheel dominant actor firing this cycle.'),
        'commercial_axis_state': commercial_axis.get('state'),
    }


# ════════════════════════════════════════════════════════════
# L5 GATE -- and it can actually fire
#
# The UAE tracker's gate is dead twice over: every axis is hardcoded False, AND
# its level map caps surge at 4 so the `raw >= 5` branch is unreachable. Here
# the map runs to 5 and the axes read real severity-5 tripwires.
# ════════════════════════════════════════════════════════════
LEVEL_TO_PLATFORM = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3,
                     'surge': 4, 'rupture': 5}


def _compute_l5_gate(tripwires):
    gate = {'kinetic': False, 'humanitarian': False, 'economic': False,
            'diplomatic': False, 'any': False, 'reason': '', 'fired': []}
    reasons = []
    for t in (tripwires or []):
        if not isinstance(t, dict):
            continue
        tw = TRIPWIRES.get(t.get('id')) or {}
        axis = tw.get('l5_axis')
        if axis and tw.get('severity') == 'surge':
            gate[axis] = True
            gate['fired'].append({'tripwire': t.get('id'), 'axis': axis})
            reasons.append('%s -> %s' % (t.get('id'), axis))
    gate['any'] = any(gate[k] for k in ('kinetic', 'humanitarian',
                                        'economic', 'diplomatic'))
    gate['reason'] = ('; '.join(reasons) if reasons else
                      'No L5 axis trigger fired. L5 is reserved for an actual '
                      'regime-change event, the capital under attack, a '
                      'besieged town falling, or AES fracture.')
    return gate


def _to_platform(level, l5_gate):
    """Local level -> platform level, with the L5 assertion rule applied.

    Platform L5 is ACTIVE CONFLICT. A high rhetoric tempo is not active
    conflict; a surge without an L5 axis trigger caps at 4.
    """
    raw = LEVEL_TO_PLATFORM.get(level)
    if raw is None:
        return None, 'unknown_level', False
    if raw >= 5 and not l5_gate['any']:
        return 4, 'l5_gate_not_fired', True
    if raw == 4 and l5_gate['any']:
        return 5, 'l5_gate_fired:%s' % l5_gate['reason'][:60], False
    basis = 'severity_canon' if CANON_AVAILABLE else 'local_fallback_table'
    return raw, basis, False


# ════════════════════════════════════════════════════════════
# SCORING
# ════════════════════════════════════════════════════════════
def _score_actor(articles, actor_id):
    if not articles:
        return {'score': 0, 'article_count': 0, 'language_breakdown': {},
                'sources': [], 'top_articles': [], 'tripwires': []}
    score = 0.0
    langs, srcs = {}, {}
    tw_seen = set()
    for a in articles:
        w = a.get('feed_weight', 1.0)
        hits = a.get('_hits', 1)
        score += w * min(1.0 + (hits - 1) * 0.15, 2.0)
        langs[a.get('language', 'en')] = langs.get(a.get('language', 'en'), 0) + 1
        srcs[a.get('source', '?')] = srcs.get(a.get('source', '?'), 0) + 1
        for tw_id, sev, axis in _check_tripwires(
                '%s %s' % (a.get('title', ''), a.get('description', ''))):
            tw_seen.add((tw_id, sev))
    ranked = sorted(articles, key=lambda a: a.get('feed_weight', 1.0)
                    * min(1.0 + (a.get('_hits', 1) - 1) * 0.15, 2.0), reverse=True)
    return {
        'score': round(score, 2),
        'article_count': len(articles),
        'language_breakdown': langs,
        'sources': [{'source': s, 'count': c}
                    for s, c in sorted(srcs.items(), key=lambda x: -x[1])[:6]],
        'top_articles': [{'title': a.get('title', ''), 'url': a.get('url', ''),
                          'source': a.get('source', ''),
                          'language': a.get('language', 'en'),
                          'published': a.get('published', '')} for a in ranked[:8]],
        'tripwires': [{'id': i, 'severity': s} for i, s in tw_seen],
    }


def _builtin_prose(composite_level, vector_levels, actor_summaries,
                   commercial_axis, wheel_presence, tripwires):
    """Fallback prose for when the interpreter is not deployed. Estimative voice."""
    sigs = []
    for tw in (tripwires or [])[:3]:
        tid = tw.get('id', 'tripwire')
        sigs.append({
            'level': tw.get('severity', 'high'), 'type': 'tripwire', 'priority': 10,
            'category': 'tripwire', 'theatre': 'burkina_faso',
            'short_text': '\U0001F1E7\U0001F1EB Tripwire: %s' % tid.replace('_', ' '),
            'long_text': '%s %s' % (tid.replace('_', ' ').capitalize() + '.',
                                    (TRIPWIRES.get(tid) or {}).get('note', '')),
        })

    if commercial_axis['state'] != 'unread':
        sigs.append({
            'level': 'elevated', 'type': 'commercial_axis', 'priority': 9,
            'category': 'commercial_axis', 'theatre': 'burkina_faso',
            'short_text': '\U0001F1E7\U0001F1EB Commercial axis: %s'
                          % commercial_axis['state'].upper(),
            'long_text': commercial_axis['reading'] + ' ' + commercial_axis['disclaimer'],
        })

    if wheel_presence.get('gulf', {}).get('active'):
        sigs.append({
            'level': 'elevated', 'type': 'off_wheel_actor', 'priority': 9,
            'category': 'off_wheel_actor', 'theatre': 'burkina_faso',
            'short_text': '\U0001F1E6\U0001F1EA Gulf channel active -- OFF-WHEEL',
            'long_text': wheel_presence['dominant_actor_note'],
        })

    for aid, s in (actor_summaries or {}).items():
        if s.get('level') in ('high', 'surge'):
            sigs.append({
                'level': s['level'], 'type': 'actor_signal', 'priority': 7,
                'category': 'actor_signal', 'theatre': 'burkina_faso',
                'short_text': '\U0001F1E7\U0001F1EB %s at %s'
                              % (ACTORS[aid]['name'], s['level'].upper()),
                'long_text': ACTORS[aid]['description'],
            })
    sigs.sort(key=lambda x: -x.get('priority', 0))

    hot = [VECTOR_LABELS.get(k, k) for k, v in (vector_levels or {}).items()
           if v in ('elevated', 'high', 'surge')]
    parts = ['Burkina Faso composite reads %s.' % composite_level.upper()]
    parts.append('Active vectors: %s.' % ', '.join(hot).lower() if hot
                 else 'All four vectors at baseline this scan.')
    parts.append('Commercial axis: %s.' % commercial_axis['state'])
    parts.append('Tier-2 spoke on Russia and China; the dominant commercial '
                 'counterparty is the Gulf, which is off-wheel. '
                 'Convergence read, not prediction.')

    so_what = []
    SW = {
        'junta_consolidation': (
            'Junta consolidation at {lvl}. What it means: party dissolutions, '
            'association bans and mass reservist mobilisation measure how much '
            'of civil society the state is absorbing -- not how secure it is. '
            'An announced foiled plot is evidence about the state\'s narrative '
            'as much as about a plot. Confirmation gauges: decree tempo, arrest '
            'waves, whether dissolutions now reach religious bodies.'),
        'insurgent_contest': (
            'Insurgent contest at {lvl}. What it means: Burkina\'s is a '
            'DISTRIBUTED siege -- dozens of simultaneous encirclements, not one '
            'strangled capital. ~40% of territory sits outside effective '
            'government control and ~800,000 people live in towns they cannot '
            'leave. Confirmation gauges: named-locality specificity, school '
            'closure counts, whether any besieged town changes hands.'),
        'external_alignment': (
            'External alignment at {lvl}. What it means: the Paris break (Jun '
            '2026) and the AES bloc are the visible half; the Rosatom chain is '
            'the quiet half, and the Jan 2026 Vienna Convention ratification '
            'was its legal precondition. Confirmation gauges: Rosatom build '
            'milestones, Africa Corps footprint reporting, any further embassy '
            'or broadcaster expulsion.'),
        'commercial_capture': (
            'Commercial capture at {lvl}. What it means: Burkina built a '
            '164 t/yr refinery in a country producing 55-60 t/yr, and it holds '
            'no LBMA accreditation -- so the bars must go to buyers who do not '
            'require Good Delivery. Who buys them is the whole question. '
            'Confirmation gauges: UAE import statistics vs Burkinabe declared '
            'exports, any accreditation application, refinery throughput.'),
    }
    for vec, lvl in (vector_levels or {}).items():
        if lvl in ('elevated', 'high', 'surge') and vec in SW:
            so_what.append({'weight': 0.9,
                            'bullet': SW[vec].format(lvl=str(lvl).upper())})
    if commercial_axis.get('both_hot'):
        so_what.append({'weight': 0.95, 'bullet':
                        'Commercial axis BOTH-HOT: ' + commercial_axis['both_hot_note']})
    if not so_what:
        so_what.append({'weight': 0.3, 'bullet':
                        'All four vectors at baseline this scan. Baseline for a '
                        'distributed siege still means ~800,000 people inside '
                        'encirclements and ~40% of territory contested. A quiet '
                        'scan is a quiet FEED, not a quiet country.'})
    so_what.sort(key=lambda b: -b['weight'])
    return sigs[:8], ' '.join(parts), so_what[:6]


# ════════════════════════════════════════════════════════════
# MAIN SCAN
# ════════════════════════════════════════════════════════════
def scan_burkina_faso_rhetoric(force=False, days=7):
    global _last_scan_started_at
    _last_scan_started_at = datetime.now(timezone.utc)
    t0 = time.time()
    print('[BF Rhetoric] === scan start (force=%s days=%s) ===' % (force, days))

    rss = fetch_all_rss()
    gdelt = fetch_all_gdelt(days)
    newsapi = fetch_newsapi(days)
    brave = fetch_brave(len(gdelt), len(newsapi))

    seen, articles = set(), []
    for a in (rss + gdelt + newsapi + brave):
        u = a.get('url', '')
        if u and u not in seen:
            seen.add(u)
            articles.append(a)
    print('[BF Rhetoric] after dedup: %d' % len(articles))

    # ── COUNTRY GATE before any actor keyword ──
    gated, rejected = [], 0
    gate_reasons = {'country': 0, 'bloc': 0, 'corridor': 0}
    for a in articles:
        ok, why = passes_country_gate(a)
        if ok:
            gate_reasons[why] += 1
            gated.append(a)
        else:
            rejected += 1
    print('[BF Rhetoric] gate: %d passed (%d country, %d bloc, %d corridor), '
          '%d rejected'
          % (len(gated), gate_reasons['country'], gate_reasons['bloc'],
             gate_reasons['corridor'], rejected))

    by_actor = {k: [] for k in ACTORS}
    for a in gated:
        for aid, hits in _classify_article(a):
            c = dict(a)
            c['_hits'] = hits
            by_actor[aid].append(c)

    actor_summaries, actor_levels, tripwires = {}, {}, []
    for aid, meta in ACTORS.items():
        sc = _score_actor(by_actor[aid], aid)
        lvl = actor_alert_level(sc['score'], meta['baseline_statements_per_week'])
        actor_levels[aid] = lvl
        actor_summaries[aid] = {
            'name': meta['name'], 'flag': meta['flag'], 'icon': meta['icon'],
            'color': meta['color'], 'role': meta['role'],
            'description': meta['description'], 'vector': meta['vector'],
            'wheel': meta.get('wheel'), 'axis_side': meta.get('axis_side'),
            'level': lvl, 'score': sc['score'],
            'baseline': meta['baseline_statements_per_week'],
            'article_count': sc['article_count'],
            'language_breakdown': sc['language_breakdown'],
            'sources': sc['sources'], 'top_articles': sc['top_articles'],
            'tripwires': sc['tripwires'],
            'source_headlines': meta.get('source_headlines', []),
            'validation': ACTOR_VALIDATION.get(aid, {'status': 'unknown'}),
        }
        for tw in sc['tripwires']:
            tripwires.append({'actor': aid, **tw})

    vector_scores, vector_levels, vector_validation = {}, {}, {}
    for vec, members in VECTOR_GROUPS.items():
        vector_scores[vec] = round(
            sum(actor_summaries[m]['score'] for m in members), 2)
        # A vector's level is the max of its MEASURED members. An unvalidated
        # member contributing 'low' is not evidence of low -- it is evidence of
        # nothing -- so it is excluded from the max and declared separately.
        measured = [m for m in members
                    if ACTOR_VALIDATION.get(m, {}).get('status') != 'unvalidated']
        unmeasured = [m for m in members if m not in measured]
        lv = [actor_summaries[m]['level'] for m in measured]
        vector_levels[vec] = max(lv, key=_rank) if lv else 'unread'
        vector_validation[vec] = {
            'measured_actors': measured,
            'unvalidated_actors': unmeasured,
            'partial': bool(unmeasured),
            'note': ('Level reflects %s only; %s has no validated keyword list '
                     'and is excluded rather than counted as low.'
                     % (', '.join(measured) or 'nothing',
                        ', '.join(unmeasured))) if unmeasured else None,
        }

    humanitarian = _read_humanitarian_context()
    commodity = _read_commodity_context()
    amplifiers = _read_crosstheater_amplifiers()

    if BF_INTERPRETER_AVAILABLE:
        try:
            commercial_axis = score_commercial_axis(actor_summaries, tripwires)
        except Exception as e:
            print('[BF Rhetoric] interpreter axis error: %s' % str(e)[:120])
            commercial_axis = _score_commercial_axis_builtin(actor_summaries, tripwires)
    else:
        commercial_axis = _score_commercial_axis_builtin(actor_summaries, tripwires)

    wheel_presence = _build_wheel_presence(actor_summaries, commercial_axis)

    composite_score = round(sum(vector_scores.values()), 2)
    composite_level = max(actor_levels.values(), key=_rank) if actor_levels else 'low'

    l5_gate = _compute_l5_gate(tripwires)
    platform_level, level_basis, l5_capped = _to_platform(composite_level, l5_gate)

    if BF_INTERPRETER_AVAILABLE:
        try:
            top_signals = build_top_signals(actor_summaries, tripwires,
                                            commercial_axis, wheel_presence,
                                            humanitarian, amplifiers)
            executive_summary = build_executive_summary(
                actor_summaries, vector_scores, vector_levels, tripwires,
                commercial_axis, wheel_presence)
            so_what = build_so_what_factor(actor_summaries, vector_levels,
                                           tripwires, commercial_axis,
                                           wheel_presence, humanitarian)
            axis_sig = build_commercial_axis_top_signal(commercial_axis)
            if axis_sig and not any(s.get('category') == 'commercial_axis'
                                    for s in top_signals):
                top_signals = [axis_sig] + list(top_signals)
        except Exception as e:
            print('[BF Rhetoric] interpreter error: %s' % str(e)[:200])
            traceback.print_exc()
            top_signals, executive_summary, so_what = _builtin_prose(
                composite_level, vector_levels, actor_summaries,
                commercial_axis, wheel_presence, tripwires)
    else:
        top_signals, executive_summary, so_what = _builtin_prose(
            composite_level, vector_levels, actor_summaries,
            commercial_axis, wheel_presence, tripwires)

    PLATFORM_LABELS = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning',
                       3: 'Confrontation', 4: 'Coercion', 5: 'Active Conflict'}

    # ── BLUF COMPATIBILITY ALIASES ──────────────────────────────────
    # africa_regional_bluf's _normalize_tracker_data reads a specific set of
    # key names. Probed 11 Oct 2026 with a real BF payload: theatre_level and
    # theatre_score land, but red_lines, scan_date and article_count all read
    # empty because this module names them differently. Rather than widen the
    # BLUF for one tracker's spelling, the tracker speaks the BLUF's dialect.
    #
    # red_lines: the BLUF counts entries whose status == 'BREACHED' to build
    # the regional breach count. Our tripwires ARE red lines, so they are
    # mapped rather than left on the floor -- surge/high read as BREACHED,
    # elevated as APPROACHING.
    _rl_triggered = []
    for _t in tripwires:
        _sev = _t.get('severity', 'elevated')
        _rl_triggered.append({
            'id': _t.get('id'),
            'actor': _t.get('actor'),
            'severity': _sev,
            'status': 'BREACHED' if _sev in ('surge', 'high') else 'APPROACHING',
            'note': (TRIPWIRES.get(_t.get('id')) or {}).get('note', ''),
        })
    red_lines = {
        'triggered': _rl_triggered,
        'breached_count': sum(1 for r in _rl_triggered if r['status'] == 'BREACHED'),
        'approaching_count': sum(1 for r in _rl_triggered if r['status'] == 'APPROACHING'),
    }

    # The BLUF's vector backstop does _safe_int() on vector_levels.values() to
    # find the hottest single vector. Ours are WORDS, so that read silently
    # returns 0 and the backstop is dead for this tracker. Emit both: words for
    # the page, platform integers for the rollup.
    vector_levels_platform = {
        k: LEVEL_TO_PLATFORM.get(v, 0) for k, v in vector_levels.items()
    }

    result = {
        'success': True,
        'country': 'burkina_faso',
        'country_display': 'Burkina Faso',
        'module': 'rhetoric_tracker_burkina_faso',
        'version': MODULE_VERSION,
        'node_class': 'tier2_spoke',
        'tier_note': ("Rachel's ruling 11 Oct 2026: Tier 2 is a back-end "
                      "label, not a front-end chip. Burkina Faso is not its "
                      "main actor page, but we watch."),

        'composite_score': composite_score,
        'composite_level': composite_level,
        'theatre_level': platform_level,
        'theatre_score': min(100, int(composite_score)),
        'theatre_label': PLATFORM_LABELS.get(platform_level, 'Monitoring'),
        'platform_level_basis': level_basis,
        'l5_capped': l5_capped,
        'l5_gate': l5_gate,

        'vector_scores': vector_scores,
        'vector_levels': vector_levels,
        'vector_levels_platform': vector_levels_platform,
        'vector_labels': VECTOR_LABELS,
        # BLUF dialect -- see the alias block above
        'red_lines': red_lines,
        'scan_date': datetime.now(timezone.utc).isoformat(),
        'article_count': len(gated),
        'vector_validation': vector_validation,
        'actor_validation_as_of': VALIDATION_AS_OF,
        'validation_corpus_note': VALIDATION_CORPUS_NOTE,
        'actor_summaries': actor_summaries,
        'tripwires_global': tripwires,

        'commercial_axis': commercial_axis,
        'wheel_presence': wheel_presence,

        'humanitarian_context': humanitarian,
        'commodity_context': commodity,
        'crosstheater_amplifiers': amplifiers,

        'top_signals': top_signals,
        'executive_summary': executive_summary,
        'so_what': so_what,

        'source_breakdown': {'rss': len(rss), 'gdelt': len(gdelt),
                             'newsapi': len(newsapi), 'brave': len(brave)},
        'articles_scanned': len(articles),
        'articles_passed_country_gate': len(gated),
        'articles_rejected_by_gate': rejected,
        'gate_note': ('Articles must name Burkina Faso, a Burkinabe place or '
                      'figure, or the AES bloc BEFORE any actor keyword runs. '
                      'This is the defence against scoring global commodity '
                      'chatter as country signal.'),
        'scan_time_seconds': round(time.time() - t0, 1),
        'days_analyzed': days,
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'cached': False,
    }

    save_cache(result)

    # ── Crosstheater fingerprint -- tier-aware ──
    _redis_set(FINGERPRINT_KEY, {
        'ts': result['last_updated'],
        'theatre': 'burkina_faso',
        'node_class': 'tier2_spoke',
        'theatre_level': platform_level,
        'wheel_presence': wheel_presence,
        'commercial_axis_state': commercial_axis['state'],
        'dominant_actor_on_wheel': wheel_presence['dominant_actor_on_wheel'],
        'tripwires': tripwires[:5],
    }, ttl_hours=14)

    # ── History snapshot -- BURKINA'S OWN VECTOR NAMES.
    # The UAE tracker writes kinetic_afpak / repression_rights / etc, which are
    # not UAE vectors, so every UAE history row stores four nulls. Not here.
    try:
        _redis_lpush_trim(HISTORY_KEY, {
            'scanned_at': result['last_updated'],
            'theatre_level': platform_level,
            'theatre_score': result['theatre_score'],
            'red_lines_count': len(tripwires),
            'junta_consolidation': vector_levels.get('junta_consolidation'),
            'insurgent_contest':   vector_levels.get('insurgent_contest'),
            'external_alignment':  vector_levels.get('external_alignment'),
            'commercial_capture':  vector_levels.get('commercial_capture'),
            'commercial_axis_state': commercial_axis['state'],
        }, max_len=336)
    except Exception as e:
        print('[BF Rhetoric] history write failed: %s' % str(e)[:100])

    print('[BF Rhetoric] done in %ss -- L%s %s, axis=%s, gate %d/%d'
          % (result['scan_time_seconds'], platform_level, composite_level,
             commercial_axis['state'], len(gated), len(articles)))
    return result


# ════════════════════════════════════════════════════════════
# BACKGROUND
# ════════════════════════════════════════════════════════════
def _background_loop():
    global _scan_running
    time.sleep(INITIAL_SCAN_DELAY_SECONDS)
    while True:
        try:
            with _scan_lock:
                if _scan_running:
                    time.sleep(60)
                    continue
                _scan_running = True
            try:
                scan_burkina_faso_rhetoric(force=True, days=7)
            finally:
                with _scan_lock:
                    _scan_running = False
            time.sleep(BACKGROUND_REFRESH_HOURS * 3600)
        except Exception as e:
            print('[BF Rhetoric] background error: %s' % str(e)[:150])
            time.sleep(600)


def start_background_refresh():
    threading.Thread(target=_background_loop, daemon=True,
                     name='BFRhetoricBG').start()
    print('[BF Rhetoric] background thread started (initial delay %ss)'
          % INITIAL_SCAN_DELAY_SECONDS)


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════
def register_burkina_faso_rhetoric_routes(app, start_background=True):
    from flask import jsonify, request

    @app.route('/api/rhetoric/burkina_faso', methods=['GET', 'OPTIONS'])
    def api_bf_rhetoric():
        if request.method == 'OPTIONS':
            return ('', 204)
        force = request.args.get('refresh', '').lower() in ('true', '1', 'yes')
        cached = load_cache()
        if cached and is_cache_fresh(cached) and not force:
            cached['cached'] = True
            return jsonify(cached)
        if cached and not force:
            cached['cached'] = True
            cached['stale'] = True
            with _scan_lock:
                if not _scan_running:
                    threading.Thread(
                        target=lambda: scan_burkina_faso_rhetoric(force=True),
                        daemon=True).start()
            return jsonify(cached)
        return jsonify(scan_burkina_faso_rhetoric(force=force, days=7))

    @app.route('/api/rhetoric/burkina_faso/debug', methods=['GET'])
    def api_bf_rhetoric_debug():
        cached = load_cache()
        return jsonify({
            'module': 'rhetoric_tracker_burkina_faso v%s' % MODULE_VERSION,
            'node_class': 'tier2_spoke',
            'actor_count': len(ACTORS),
            'actors': list(ACTORS.keys()),
            'vectors': list(VECTOR_GROUPS.keys()),
            'country_gate_terms': len(COUNTRY_GATE),
            'bloc_gate_terms': len(BLOC_GATE),
            'tripwires': len(TRIPWIRES),
            'l5_capable_tripwires': [k for k, v in TRIPWIRES.items()
                                     if v.get('l5_axis') and v['severity'] == 'surge'],
            'rss_feeds': len(RSS_FEEDS),
            'wheel_tiers': {k: v[0] for k, v in WHEEL_TIERS.items()},
            'tier_front_end_visible': TIER_FRONT_END_VISIBLE,
            'actor_validation': ACTOR_VALIDATION,
            'validation_as_of': VALIDATION_AS_OF,
            'commodity_scored': False,
            'commodity_scored_reason': (
                'Upstream has no country filter as of 11 Oct 2026 -- context only.'),
            'interpreter_available': BF_INTERPRETER_AVAILABLE,
            'canon_available': CANON_AVAILABLE,
            'redis_wired': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured': bool(NEWSAPI_KEY),
            'brave_configured': bool(BRAVE_API_KEY),
            'cache_present': cached is not None,
            'cache_fresh': is_cache_fresh(cached) if cached else False,
            'last_scan_started_at': (_last_scan_started_at.isoformat()
                                     if _last_scan_started_at else None),
            'background_running': _scan_running,
        })

    print('[BF Rhetoric] endpoints registered:')
    print('  GET /api/rhetoric/burkina_faso')
    print('  GET /api/rhetoric/burkina_faso/debug')
    if start_background:
        start_background_refresh()


print('[BF Rhetoric] module loaded -- v%s' % MODULE_VERSION)
