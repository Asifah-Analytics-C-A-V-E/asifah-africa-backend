"""
rhetoric_tracker_niger.py -- Asifah Analytics Africa Backend -- v1.0.0
21 November 2026

NIGER RHETORIC TRACKER. The analyst layer behind niger-stability.html.

WHAT NIGER IS, FOR THIS TRACKER
    Niger is a CROSSROADS and a SPOKE ON FIVE WHEELS AT ONCE. The same month can
    carry Russia's Africa Corps defending the government, Algeria sending
    troops, the United States financing a uranium mine, China's oil companies
    under a 45-day ultimatum and Turkey delivering drones. Most of our trackers
    have one patron to watch; Niger has a portfolio. So the external-alignment
    vector is built as a SET of spokes, each written to its hub's wheel
    (spoke:<hub>:niger), rather than one "who is Niger aligned with" number.

FIVE VECTORS
    regime_security      Tiani / CNSP consolidation, and the mutiny / coup-plot
                         channel (the 29-30 Aug 2026 mutiny is the precedent).
    insurgent_fronts     THREE FRONTS + unplaced attacks, each on a KINETIC
                         LADDER (see below), not on article volume.
    external_alignment   Russia, Algeria, US, Turkey, Iran (watch), France (the
                         antagonist), and the AES / ECOWAS bloc.
    resource_leverage    Uranium (SOMAIR / Orano / buyers) and oil (CNPC /
                         WAPCO / the Benin pipeline) -- the two things Niger
                         sells, and the two levers others pull.
    lifelines            The Benin border and the routes to the sea.

THE KINETIC LADDER -- L5 COMES ONLY FROM HERE
    Each front (Tillaberi, Diffa, the north) is scored by the WORST thing
    reported there this window, on the platform scale:
        L1 mention . L2 threat / claim . L3 attack / clash / killing
        L4 mass casualty (10+ killed, massacre, "dozens")
        L5 a town or base taken, or the capital attacked
    and the doctrine's evidence rule is enforced: L3 and above need TWO OR
    MORE distinct outlets reporting at that rung or worse. One outlet's
    massacre headline is held at L2 until a second outlet carries it.
    The theatre may only reach L5 through a front ladder at L5. Tripwires are
    red lines (they show as BREACHED) but cannot open L5 on their own;
    rhetoric volume never can.

    Tillaberi and Diffa are STANDING insurgencies (like Sudan's war in the
    Africa BLUF's STANDING_WARS): L3-L4 there is the condition, not news.
    The payload says so (front.standing = True) so the BLUF and GPI do not
    headline a standing front as new.

THE COUNTRY GATE -- "NIGER" IS THREE PLACES
    Niger the country, Niger STATE in Nigeria (Minna, Mariga, Shiroro, where
    Boko Haram and bandits also operate), and the Niger DELTA. A headline
    "Boko Haram attacks police camp in Niger" was a Niger STATE story (Premium
    Times, 2026). So an article passes only if it names a Nigerien place,
    person or institution, OR says "Niger" as a whole word without a Niger
    State / Delta context. Negative controls in the harness test this.

KEYWORD DISCIPLINE (inherited from the Burkina build)
    Every actor keyword traces to a verbatim 2026 headline, harvested
    21 Nov 2026 and quoted in source_headlines. Validation is MEASURED in the
    harness, and an actor whose list matched nothing reads UNREAD, never low.

COMMODITY SIGNALS ARE CONTEXT, NOT SCORE (as Burkina): uranium and oil prices
    are read for display; upstream commodity signal counts are not scored.

EMITS
    rhetoric:niger:latest            full payload (12h)  <- africa_regional_bluf
    rhetoric:niger:history           rolling snapshots
    crosstheater:niger:fingerprint   slice for BLUF / GPI / Burkina & Mali
    spoke:<hub>:niger                russia, china, us, turkey, iran wheels

ENDPOINTS
    GET /api/rhetoric/niger
    GET /api/rhetoric/niger?refresh=true      (no Claude calls; news fetch only)
    GET /api/rhetoric/niger/debug

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
    print('[NE Rhetoric] feedparser unavailable -- RSS disabled')

MODULE_VERSION = '1.0.4'   # Nov 27 2026 (b): outlet cap + URL-signed outlets shown as hostnames. 1.0.3 Nov 27 2026: recency gate + Brave freshness=pw + Google News when:7d. 1.0.2 Nov 22 2026: Google News outlet fix (real outlet from the title suffix). 1.0.1 Nov 21 2026: GPI-safe signals (explicit axis, numeric levels, standing)
_RECENCY_STATE = {'last': None}
OUTLET_CAP = 2   # max articles per outlet per actor that add to its score (Nov 27 2026)   # last recency-gate stats, shown on the debug route

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
NEWSAPI_KEY   = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY')

CACHE_TTL_HOURS            = 12
BACKGROUND_REFRESH_HOURS   = 12
INITIAL_SCAN_DELAY_SECONDS = 210   # staggered behind Burkina (150s) and the Niger sensors

REDIS_KEY_LATEST = 'rhetoric:niger:latest'
HISTORY_KEY      = 'rhetoric:niger:history'
FINGERPRINT_KEY  = 'crosstheater:niger:fingerprint'
HUMANITARIAN_KEY = 'africa:humanitarian:niger'
SPOKE_TTL_HOURS  = 30

GDELT_BASE_URL   = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI_BASE_URL = 'https://newsapi.org/v2/everything'
BRAVE_BASE_URL   = 'https://api.search.brave.com/res/v1/news/search'

CACHE_FILE = '/tmp/ne_rhetoric_cache.json'

_scan_running = False
_scan_lock = threading.Lock()
_last_scan_started_at = None


# ════════════════════════════════════════════════════════════
# ACTORS -- 15 actors / 5 vectors
#
# Every keyword traces to a verbatim 2026 headline (harvested 21 Nov 2026),
# quoted in source_headlines. French matters: Nigerien official communication
# and much of the regional press publish in French first.
# ════════════════════════════════════════════════════════════
ACTORS = {
    # ── VECTOR: regime_security ──────────────────────────────
    'junta_tiani': {
        'name': 'Tiani / CNSP', 'flag': '\U0001F1F3\U0001F1EA', 'icon': '\U0001F3DB️',
        'color': '#e2e8f0',
        'role': 'Junta consolidation -- decrees, demands, the transition',
        'description': (
            'General Abdourahamane Tiani and the CNSP: the five-year transition '
            'under the March 2025 charter, dissolved parties, nationality '
            'stripping, and the demands made of foreign companies (CNPC, Orano). '
            'Consolidation tempo measures how much the state is absorbing, not '
            'how secure it is.'),
        'vector': 'regime_security',
        'keywords': [
            'tiani', 'tchiani', 'abdourahamane', 'cnsp', 'niger junta', "niger's junta",
            'la junte', 'junte', 'military-led government', "military rulers",
            'military government', 'transition charter', 'refondation',
            'stripped of nationality', 'nationality', 'general tiani', 'général tiani',
        ],
        'source_headlines': [
            "2026-? Niger oil: China yields to General Tiani's demands",
            '2026-07-22 Niger: La junte de plus en plus sous pression des groupes armés rebelles',
            "2026-08-30 Niger's military-led government says it contained mutiny: What next?",
            "2026-06 Niger–Turquie : Tchiani révèle qu'Erdogan a autorisé la livraison d'armes avant paiement",
            '2026-02-17 Algérie: La visite à Alger du général Abdourahamane Tiani met fin à plusieurs mois de crise',
        ],
        'baseline_statements_per_week': 6,
    },
    'mutiny_plot': {
        'name': 'Mutiny / Coup-plot', 'flag': '⚔️', 'icon': '\U0001F5E1️',
        'color': '#f97316',
        'role': 'Regime security -- mutiny, coup attempts, arrests in the ranks',
        'description': (
            'The 29-30 August 2026 mutiny (an airbase and the presidential palace '
            'in Niamey, contained within 24 hours with Russian help) is the '
            'in-period precedent. READ WITH CARE: an announced foiled plot is '
            "evidence of the state's narrative as much as of a plot."),
        'vector': 'regime_security',
        'keywords': [
            'mutiny', 'mutinous', 'mutineers', 'mutinerie', 'mutins',
            'coup attempt', 'attempted coup', 'failed mutiny', 'foiled coup',
            'coup plot', 'tentative de coup', 'soldiers arrested', 'arrests dozens of soldiers',
            "junta's cohesion", 'back in control', 'palace guard', 'garde présidentielle',
        ],
        'source_headlines': [
            "2026-08-29 Niger's security forces battle mutinous soldiers in the capital",
            '2026-08-30 Niger crushes mutiny attempt at key airbase',
            "2026-08-30 Dozens of soldiers killed or arrested after an apparent mutiny in Niger's capital, state TV reports",
            '2026-09-06 Niger military accuses France of orchestrating failed mutiny: What to know',
            "2026-08 Niger mutiny suppressed, but questions remain over junta's cohesion",
            '2026-08-30 Niger Republic Arrests Dozens Of Soldiers Over Attempted Coup',
        ],
        'baseline_statements_per_week': 2,
    },

    # ── VECTOR: insurgent_fronts (levels come from the KINETIC LADDER) ──
    'front_tillaberi': {
        'name': 'Western front (Tillabéri)', 'flag': '\U0001F3F4', 'icon': '\U0001F4A5',
        'color': '#dc2626',
        'role': 'IS Sahel and JNIM on the Mali-Burkina border',
        'description': (
            'The deadliest front: IS Sahel (ISSP) and JNIM in the Tillabéri '
            'tri-border, where 1,032 schools were closed by insecurity. Standing '
            'insurgency: L3-L4 here is the condition, not news.'),
        'vector': 'insurgent_fronts', 'front': 'tillaberi', 'standing': True,
        'keywords': [
            'tillaberi', 'tillabéri', 'tillabery', 'issp', 'islamic state sahel',
            'islamic state in the sahel', 'is sahel', 'isgs', 'jnim', "jama'at nusrat",
            'nusrat al-islam', 'banibangou', 'ouallam', 'tera', 'téra', 'torodi',
            'makalondi', 'abala', 'ayorou', 'tri-border', 'trois frontières',
            'islamist armed group', 'in west', 'western niger', "ouest du pays",
            "l'ouest du niger",
        ],
        'source_headlines': [
            '2026-02-12 Niger: Islamist Armed Group Massacres Villagers in West',
            "2026-07-20 Niger: De nombreux militaires tués dans une attaque «terroriste» dans l'ouest du pays",
            '2026-04 Aumenta a violência contra civis na região de Tillabéri no Níger (ADF)',
        ],
        'baseline_statements_per_week': 4,
    },
    'front_diffa': {
        'name': 'Eastern front (Diffa / Lake Chad)', 'flag': '\U0001F3F4', 'icon': '\U0001F4A5',
        'color': '#b91c1c',
        'role': 'Boko Haram and ISWAP in the Lake Chad basin',
        'description': (
            'Boko Haram and ISWAP across the Diffa region and the Lake Chad '
            'shore. Standing insurgency; the read that matters is whether attack '
            'specificity and casualty counts rise together.'),
        'vector': 'insurgent_fronts', 'front': 'diffa', 'standing': True,
        'keywords': [
            'diffa', 'boko haram', 'iswap', 'islamic state west africa', 'lake chad',
            'lac tchad', 'bosso', 'toumour', "n'guigmi", 'nguigmi', 'mainé-soroa',
            'maine-soroa', 'southeastern niger', 'south-eastern niger', 'sud-est du niger',
        ],
        'source_headlines': [
            '2026-08-01 Niger: "une dizaine" de soldats tués dans une attaque de Boko Haram',
            '2026-08 Boko Haram ambush kills 10 soldiers in southeastern Niger',
        ],
        'baseline_statements_per_week': 3,
    },
    'front_north': {
        'name': 'Northern front (rebels / pipeline)', 'flag': '\U0001F3F4', 'icon': '\U0001F6E2️',
        'color': '#ea580c',
        'role': 'FPL and other armed groups; attacks on the oil pipeline',
        'description': (
            'Armed opposition in the north and east (the Front Patriotique de '
            'Libération and others) targeting the junta\'s oil revenue by '
            'attacking the China-built export pipeline. Distinct from the '
            'jihadist fronts: this is a rebellion with political demands.'),
        'vector': 'insurgent_fronts', 'front': 'north', 'standing': False,
        'keywords': [
            'fpl', 'front patriotique', 'patriotic liberation front', 'rebels', 'rebel group',
            'rebelles', 'groupes armés rebelles', 'armed group attacks', 'pipeline attack',
            'attacked the pipeline', 'sabotage', 'oléoduc', 'aïr mountains', 'air mountains',
            'tchirozerine', 'oil revenue', 'revenus pétroliers',
        ],
        'source_headlines': [
            "2026-02 Rebels target Niger junta's oil revenue (ADF)",
            '2026-07-22 Niger: La junte de plus en plus sous pression des groupes armés rebelles',
            'Rebel Group Attacks On China-Funded Oil Project In Niger Have Wide Implications',
            "Why Beijing's US$4.5 billion Niger-Benin oil pipeline is being attacked by rebels",
        ],
        'baseline_statements_per_week': 2,
    },
    'attacks_unplaced': {
        'name': 'Attacks (front not named)', 'flag': '\U0001F3F4', 'icon': '❓',
        'color': '#94a3b8',
        'role': 'Kinetic reporting that does not say where',
        'description': (
            'Attacks and casualties reported without a named front ("10 troops '
            'killed in Niger attack"). Kept separate so a vague headline is not '
            'silently credited to the wrong front. It still counts on the kinetic '
            'ladder.'),
        'vector': 'insurgent_fronts', 'front': 'unplaced', 'standing': False,
        'keywords': [
            'troops killed', 'soldiers killed', 'soldats tués', 'militaires tués',
            'jihadists', 'jihadistes', 'djihadistes', 'terroristes', 'terrorists killed',
            'ambush', 'embuscade', 'militants', 'armed groups', 'groupes armés',
        ],
        'source_headlines': [
            '2026-08 10 troops killed in Niger attack (Dawn)',
            '2026-07-24 Niger: Les militaires impuissants face aux djihadistes',
            '2026 Niger : Le harcèlement de la junte par les groupes armés s\'accentue…',
        ],
        'baseline_statements_per_week': 4,
    },

    # ── VECTOR: external_alignment ───────────────────────────
    'russia_axis_ne': {
        'name': 'Russia (Africa Corps)', 'flag': '\U0001F1F7\U0001F1FA', 'icon': '\U0001F43B',
        'color': '#0ea5e9',
        'role': "The guarantor -- Africa Corps at Air Base 101",
        'description': (
            'Africa Corps in Niamey helped repel the Islamic State attack on the '
            'airport (early 2026) and helped end the August mutiny; Niamey calls '
            'Russia its main partner. Reported uranium talks (~1,000 t) sit on '
            'the resource side.'),
        'vector': 'external_alignment', 'wheel': 'russia',
        'keywords': [
            'russia', 'russian', 'russie', 'russe', 'africa corps', 'wagner', 'moscow',
            'moscou', 'kremlin', 'putin', 'rosatom', 'lavrov',
        ],
        'source_headlines': [
            '2026-01-30 In Niamey, the nighttime attack that reveals Russian involvement',
            '2026-09-14 Niger mutiny exposes growing reliance on Russia',
            "Western Fears Arise of Iran's Access to Nigerien Uranium with Russian Support",
        ],
        'baseline_statements_per_week': 3,
    },
    'algeria_axis': {
        'name': 'Algeria', 'flag': '\U0001F1E9\U0001F1FF', 'icon': '\U0001F6E1️',
        'color': '#16a34a',
        'role': 'New security patron, gas-pipeline partner, deportations',
        'description': (
            'Ties rebuilt after Tiani\'s February 2026 visit to Algiers; '
            'helicopters, then Su-30s after the August mutiny, then a troop '
            'deployment ordered 26 October 2026 -- Algeria\'s first abroad since '
            '1973. Also the Trans-Saharan Gas Pipeline partner, and the state '
            'expelling tens of thousands of people into Niger at Assamaka.'),
        'vector': 'external_alignment', 'wheel': None,
        'keywords': [
            'algeria', 'algerian', 'algérie', 'algérien', 'algiers', 'alger', 'tebboune',
            'trans-saharan gas pipeline', 'tsgp', 'gas pipeline', 'gazoduc',
            'first foreign deployment since 1973', 'assamaka',
        ],
        'source_headlines': [
            "2026-10-26 Algeria's president orders troop deployment to neighbouring Niger",
            "2026-02 Niger, Algeria announce 'new dynamic' in ties, progress on pipeline",
            '2026 Algeria to send troops to Niger in first foreign deployment since 1973',
            'Niger and Algeria reaffirm ties through gas pipeline restart (30 bcm/year)',
        ],
        'baseline_statements_per_week': 2,
    },
    'us_axis': {
        'name': 'United States', 'flag': '\U0001F1FA\U0001F1F8', 'icon': '\U0001F985',
        'color': '#3b82f6',
        'role': 'Re-engaging -- uranium finance and equipment',
        'description': (
            'Two years after US troops left: ~$23M of military equipment (May '
            '2026) and up to $414M of DFC financing for Global Atomic\'s Dasa '
            'uranium project (September 2026).'),
        'vector': 'external_alignment', 'wheel': 'us',
        'keywords': [
            'united states', 'u.s.', 'us approves', 'us seals', 'us steps back',
            'washington', 'américain', 'americain', 'états-unis', 'etats-unis', 'dfc',
            'development finance corporation', 'global atomic', 'dasa', 'bald eagle', 'aigle',
        ],
        'source_headlines': [
            '2026-09-17 US approves $414M uranium investment in Niger, two years after troops left',
            '2026-09-17 Niger: Washington revient par la grande porte au pays',
            '2026-09-17 US seals big uranium investment in Niger, two years after troops left',
            'Is uranium bringing Washington back to Niger?',
        ],
        'baseline_statements_per_week': 2,
    },
    'turkey_axis': {
        'name': 'Türkiye', 'flag': '\U0001F1F9\U0001F1F7', 'icon': '\U0001F6E9️',
        'color': '#ef4444',
        'role': 'Drones, arms on credit, uranium interest',
        'description': (
            'Armed drones (Aksungur, Akinci, TB2), arms delivered before '
            'payment, Tiani\'s June 2026 visit to Ankara, and a Turkish envoy '
            'seeking uranium supplies.'),
        'vector': 'external_alignment', 'wheel': 'turkey',
        'keywords': [
            'turkey', 'türkiye', 'turkiye', 'turquie', 'turkish', 'turc', 'ankara',
            'erdogan', 'erdoğan', 'baykar', 'bayraktar', 'aksungur', 'akinci', 'akıncı',
        ],
        'source_headlines': [
            "Niger's turn to Türkiye signals new partnership model in Sahel",
            '2026-06-03 Niger: drones, army, terrorism: Tiani flies to Ankara to meet Erdogan',
            "Niger–Turquie : Tchiani révèle qu'Erdogan a autorisé la livraison d'armes avant paiement",
            "Türkiye expands military footprint in Niger's security landscape",
            'Turkish envoy visits Niger to secure uranium supplies',
        ],
        'baseline_statements_per_week': 1,
    },
    'iran_axis': {
        'name': 'Iran (watch)', 'flag': '\U0001F1EE\U0001F1F7', 'icon': '☢️',
        'color': '#a855f7',
        'role': 'Rumour tier -- reported uranium interest',
        'description': (
            'Reported Iranian interest in Nigerien uranium, unconfirmed. Watch '
            'spoke: any hit is reporting about a possibility, and the payload '
            'says so.'),
        'vector': 'external_alignment', 'wheel': 'iran',
        'keywords': ['iran', 'iranian', 'tehran', 'téhéran', 'iranien'],
        'source_headlines': [
            "Western Fears Arise of Iran's Access to Nigerien Uranium with Russian Support",
        ],
        'baseline_statements_per_week': 1,
    },
    'france_rupture': {
        'name': 'France (antagonist)', 'flag': '\U0001F1EB\U0001F1F7', 'icon': '\U0001F6AA',
        'color': '#a78bfa',
        'role': 'Accused sponsor; the Orano dispute',
        'description': (
            'Niamey has accused France of orchestrating the August mutiny, of '
            'sponsoring the airport attack (with Benin and Côte d\'Ivoire) and of '
            'funding JNIM; Paris denies it. The Orano / SOMAÏR dispute runs '
            'through courts and arbitration.'),
        'vector': 'external_alignment', 'wheel': None,
        'keywords': [
            'france', 'french', 'français', 'française', 'paris', 'macron', 'orano',
            'accuses france', 'accuse la france',
        ],
        'source_headlines': [
            "Niger accuses France, Benin and Cote d'Ivoire of sponsoring airport attack",
            '2026-09-06 Niger military accuses France of orchestrating failed mutiny',
            'A French mining company sues Niger after its director disappears and offices are raided',
            "2026-02-25 Niger: Entre le pays et Orano, le ton est à l'apaisement",
        ],
        'baseline_statements_per_week': 2,
    },
    'aes_ecowas': {
        'name': 'AES / ECOWAS', 'flag': '\U0001F91D', 'icon': '\U0001F310',
        'color': '#8b5cf6',
        'role': 'The bloc -- AES with Mali and Burkina; the ECOWAS exit',
        'description': (
            'The Alliance of Sahel States (Niger, Mali, Burkina Faso), its '
            'mutual-defence pact and joint force, and relations with ECOWAS '
            'after the January 2025 exit.'),
        'vector': 'external_alignment', 'wheel': None,
        'keywords': [
            'aes', 'alliance of sahel states', 'alliance des etats du sahel',
            'alliance des états du sahel', 'confédération', 'sahel confederation',
            'ecowas', 'cedeao', 'joint force', 'force unifiée',
        ],
        'source_headlines': [
            '2025-01 ECOWAS withdrawal effective with Mali and Burkina Faso (AES)',
        ],
        'baseline_statements_per_week': 2,
    },

    # ── VECTOR: resource_leverage ────────────────────────────
    'uranium_leverage': {
        'name': 'Uranium', 'flag': '☢️', 'icon': '⛏️',
        'color': '#eab308',
        'role': 'SOMAÏR, the stockpile, the buyers',
        'description': (
            'SOMAÏR nationalised (2025); its stockpile put on the international '
            'market; Orano suing and condemning "illegal" transfers; Russia, '
            'Türkiye, Iran (rumour) and the US all named as interested. WHO BUYS '
            'is the analytic payload.'),
        'vector': 'resource_leverage', 'axis_side': 'refusal',
        'keywords': [
            'uranium', 'somair', 'somaïr', 'yellowcake', 'arlit', 'imouraren',
            'uranium stockpile', 'uranium market', 'nationalised', 'nationalized',
            'nationalise', 'nationalisé', 'seized', 'filiale',
        ],
        'source_headlines': [
            "Niger Moves to Sell Uranium From Orano's Seized SOMAÏR Mine",
            'Niger Says Putting its Uranium on International Market',
            'Orano Condemns Illegal Uranium Transfer from Niger Mine',
            'Niger accuses Orano of radioactive pollution as uranium row deepens',
            "2026-05 Le Niger dit ne pas avoir vendu d'uranium depuis qu'il a nationalisé une filiale d'Orano",
        ],
        'baseline_statements_per_week': 3,
    },
    'oil_china': {
        'name': 'Oil and China (CNPC)', 'flag': '\U0001F1E8\U0001F1F3', 'icon': '\U0001F6E2️',
        'color': '#f59e0b',
        'role': 'CNPC / WAPCO / SORAZ -- the pipeline economy and its quarrels',
        'description': (
            'Agadem crude, the China-built pipeline to Sèmè (Benin), and a '
            'running fight over revenue: concessions won in May-June 2026, then '
            'a 45-day ultimatum on 16 October 2026 to repatriate ~3,000bn CFA '
            '(~$5bn) of export revenue. China\'s spoke in Niger runs almost '
            'entirely through this actor.'),
        'vector': 'resource_leverage', 'axis_side': 'capture', 'wheel': 'china',
        'keywords': [
            'cnpc', 'petrochina', 'wapco', 'soraz', 'chinese', 'chinoises', 'chinois',
            'china', 'chine', 'beijing', 'pékin', 'agadem', 'pipeline', 'oil', 'pétrole',
            'petrolier', 'pétrolières', 'crude', 'sèmè', 'seme', 'ultimatum',
        ],
        'source_headlines': [
            '2026-10-16 Niger-Chine : Ultimatum de 45 jours aux entreprises pétrolières',
            "2026-06-01 Niger Secures Concessions From China's CNPC As Oil Output Stabilizes",
            '2026-05-20 Niger: La fin du bras de fer actée avec les sociétés pétrolières chinoises',
            '2026-02-19 Niger: Chinese CNPC in the hot seat',
            "Niger oil: China yields to General Tiani's demands",
        ],
        'baseline_statements_per_week': 3,
    },

    # ── VECTOR: lifelines ────────────────────────────────────
    'benin_border': {
        'name': 'Benin border & routes', 'flag': '\U0001F1E7\U0001F1EF', 'icon': '\U0001F6E3️',
        'color': '#14b8a6',
        'role': 'The road to the sea -- shut since 2023, in talks since June',
        'description': (
            'The Benin land border, shut since the July 2023 crisis; Benin\'s new '
            'president visited Niamey in June 2026 and Niger set preconditions '
            '(a defence and non-aggression accord). Also the Nigeria crossings '
            'and cross-border trade. Niamey has accused Benin of hosting forces '
            'used against it.'),
        'vector': 'lifelines',
        'keywords': [
            'benin', 'bénin', 'cotonou', 'wadagni', 'talon', 'malanville', 'gaya',
            'shared border', 'frontière', 'border reopening', 'reopening of the border',
            'réouverture', 'cross-border trade', 'kebbi', 'reopens border',
        ],
        'source_headlines': [
            '2026-06-18 Benin and Niger formalise commitment to reopening shared border',
            '2026-06-20 Le Niger pose des conditions à la réouverture de sa frontière avec le Bénin',
            '2026-04-30 Nigeria, Niger, Benin cross-border trade resumes amid security risks',
            "Niger accuses France, Benin and Cote d'Ivoire of sponsoring airport attack",
        ],
        'baseline_statements_per_week': 2,
    },
}

VECTOR_GROUPS = {
    'regime_security':    ['junta_tiani', 'mutiny_plot'],
    'insurgent_fronts':   ['front_tillaberi', 'front_diffa', 'front_north', 'attacks_unplaced'],
    'external_alignment': ['russia_axis_ne', 'algeria_axis', 'us_axis', 'turkey_axis',
                           'iran_axis', 'france_rupture', 'aes_ecowas'],
    'resource_leverage':  ['uranium_leverage', 'oil_china'],
    'lifelines':          ['benin_border'],
}
VECTOR_LABELS = {
    'regime_security':    'Regime Security',
    'insurgent_fronts':   'Insurgent Fronts',
    'external_alignment': 'External Alignment',
    'resource_leverage':  'Resource Leverage',
    'lifelines':          'Lifelines',
}

# The wheels Niger sits on, and which actor carries each spoke.
# node_class strings follow spoke_wheel_reader (russia: expeditionary_client).
SPOKES = {
    'russia': {'actor': 'russia_axis_ne', 'node_class': 'expeditionary_client',
               'why': 'Africa Corps at Air Base 101; helped repel the airport attack and end the August 2026 mutiny.'},
    'china':  {'actor': 'oil_china', 'node_class': 'resource_client',
               'why': 'CNPC oil and the Benin pipeline; under a 45-day revenue ultimatum from 16 Oct 2026.'},
    'us':     {'actor': 'us_axis', 'node_class': 're_engaging',
               'why': 'US DFC up to $414M for Dasa uranium (Sep 2026) and ~$23M of equipment (May 2026).'},
    'turkey': {'actor': 'turkey_axis', 'node_class': 'arms_client',
               'why': 'Turkish armed drones and arms on credit; uranium interest.'},
    'iran':   {'actor': 'iran_axis', 'node_class': 'reported_interest',
               'why': 'Reported uranium interest, unconfirmed (rumour tier).'},
}


# ════════════════════════════════════════════════════════════
# COUNTRY GATE -- "Niger" is three places (country, Nigerian state, delta)
# ════════════════════════════════════════════════════════════
STRONG_TOKENS = [
    'niamey', 'nigerien', 'nigérien', 'nigerienne', 'nigérienne', 'tiani', 'tchiani',
    'cnsp', 'agadez', 'tillaberi', 'tillabéri', 'diffa', 'zinder', 'maradi', 'tahoua',
    'dosso', 'arlit', 'somair', 'somaïr', 'assamaka', 'agadem', 'bazoum', 'imouraren',
]
NIGERIA_CONTEXT = [
    'niger state', "niger state's", 'minna', 'mariga', 'shiroro', 'rafi lga', 'mashegu',
    'kontagora', 'niger delta', 'niger river delta', 'bayelsa', 'rivers state',
]
BLOC_GATE = [
    'alliance of sahel states', 'alliance des etats du sahel', 'alliance des états du sahel',
    'aes states', 'aes bloc', 'sahel confederation',
]
_NIGER_WORD = re.compile(r"(?<![a-z])niger(?![a-z])")


# ════════════════════════════════════════════════════════════
# KINETIC LADDER -- per front, platform scale, L5 only from here
# ════════════════════════════════════════════════════════════
_NUM = (r'(?:1[0-9]|[2-9][0-9]|[1-9][0-9]{2,}|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|'
        r'seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|a dozen|dozens of|hundreds of|'
        r'dix|douze|quinze|vingt|trente|quarante|cinquante)')
LADDER = [
    (5, [r'attack on niamey', r'niamey under attack', r'assault on niamey', r'stormed the capital',
         r'town (?:captured|seized|overrun|falls)', r'(?:base|garrison|camp) (?:overrun|captured|falls)',
         r'falls to (?:jihadists|militants|rebels)', r'capital (?:attacked|under attack)',
         r'(?:capture|captured|captures|seize|seizes|seized|take|takes|took|overrun|overruns|overran) '
         r'(?:the |a )?(?:town|base|garrison|military camp|army camp)',
         r'prennent le contr[oô]le', r'(?:ville|base|camp) (?:tombée?|prise?) ',
         r'seize[sd]? power', r'coup succeeds', r'tiani (?:killed|ousted|overthrown)']),
    (4, [r'massacre', r'dozens (?:of )?(?:soldiers|civilians|people|troops|villagers)? ?(?:killed|dead)?',
         r'\bdozens\b', r'des dizaines', r'une dizaine', r'nombreux (?:militaires|soldats|civils) tués',
         r'(?:kill(?:s|ed|ing)?|tués?) (?:at least )?' + _NUM,
         r'(?:at least |au moins )?' + _NUM + r' (?:soldiers|troops|civilians|people|villagers|militaires|soldats|civils|personnes)',
         r'(?:at least |au moins )?' + _NUM + r' (?:\w+ )?(?:killed|dead|tués|morts)',
         r'deadliest', r'mass casualty']),
    (3, [r'attack', r'attaque', r'ambush', r'embuscade', r'clash', r'affrontement', r'killed', r'tués?',
         r'sabotage', r'mutiny', r'mutinous', r'raid', r'kidnapp', r'enlev', r'massacres?']),
    (2, [r'threat', r'threaten', r'menace', r'warns', r'claims?', r'revendique', r'pressure', r'pression']),
]
_LADDER_RX = [(lv, [re.compile(p) for p in pats]) for lv, pats in LADDER]


# ════════════════════════════════════════════════════════════
# TRIPWIRES -- red lines. They show as BREACHED / APPROACHING; they do NOT
# open L5 on their own (only a front ladder at L5 can).
# ════════════════════════════════════════════════════════════
TRIPWIRES = {
    'capital_attacked': {
        'patterns': ['attack on niamey', 'niamey under attack', 'assault on niamey',
                     'battle mutinous soldiers in the capital', 'attack on niamey airport'],
        'severity': 'surge',
        'note': 'The early-2026 airport attack and the August mutiny are the in-period precedents.',
    },
    'regime_change_event': {
        'patterns': ['coup succeeds', 'seizes power', 'tiani ousted', 'tiani killed',
                     'tiani overthrown', 'new head of state'],
        'severity': 'surge',
        'note': 'An ACTUAL change of regime, not an announced foiled plot.',
    },
    'mutiny': {
        'patterns': ['mutiny', 'mutinous', 'mutinerie', 'attempted coup', 'coup attempt', 'tentative de coup'],
        'severity': 'high',
        'note': 'Regime-security red line. The Aug 2026 mutiny was contained in 24h with Russian help.',
    },
    'mass_casualty_event': {
        'patterns': ['massacre', 'deadliest', 'dozens of soldiers', 'dozens of civilians', 'des dizaines'],
        'severity': 'high',
        'note': 'Tillabéri massacres (Feb 2026) and Boko Haram ambushes (Aug 2026) are the class.',
    },
    'pipeline_sabotage': {
        'patterns': ['pipeline attack', 'attacked the pipeline', 'pipeline sabotage', 'sabotage of the pipeline',
                     'attaque de l\'oléoduc', 'oléoduc'],
        'severity': 'high',
        'note': 'Cuts the oil revenue the junta depends on; the FPL has claimed past attacks.',
    },
    'china_oil_rupture': {
        'patterns': ['ultimatum', 'expels cnpc', 'suspends cnpc', 'cnpc expelled', 'chinese executives expelled',
                     'revokes licence', 'revokes license'],
        'severity': 'high',
        'note': ('16 Oct 2026: a 45-day ultimatum to CNPC, WAPCO and SORAZ to repatriate ~$5bn of '
                 'export revenue, due around 30 Nov 2026.'),
    },
    'foreign_force_deployment': {
        'patterns': ['troop deployment to', 'deploys troops', 'send troops to niger', 'algerian troops',
                     'russian reinforcements', 'foreign deployment'],
        'severity': 'elevated',
        'note': 'Algeria ordered troops to Niger on 26 Oct 2026 -- its first deployment abroad since 1973.',
    },
    'uranium_sale': {
        'patterns': ['uranium sale', 'sells uranium', 'sold uranium', 'uranium transfer', 'uranium shipment',
                     'uranium convoy', 'buyer for its uranium'],
        'severity': 'elevated',
        'note': 'Who buys the SOMAÏR stockpile is a geopolitical bellwether.',
    },
    'diplomatic_rupture': {
        'patterns': ['breaks off diplomatic relations', 'severs diplomatic relations', 'expels ambassador',
                     'closes embassy', 'recalls its ambassador', 'persona non grata'],
        'severity': 'high',
        'note': 'Niamey has accused France, Benin and Côte d\'Ivoire of hostile acts in 2026.',
    },
    'aes_fracture': {
        'patterns': ['leaves the aes', 'quits the alliance', 'aes collapses', 'rejoins ecowas', 'returns to ecowas'],
        'severity': 'surge',
        'note': 'The bloc coming apart would re-price all three AES trackers.',
    },
    'benin_border_reopens': {
        'patterns': ['border reopens', 'reopens border', 'reopened the border', 'réouverture effective',
                     'frontière rouverte'],
        'severity': 'elevated',
        'note': 'A DE-escalation red line: the road to the sea reopening. Update the stability page when it fires.',
    },
}


# ════════════════════════════════════════════════════════════
# FEEDS -- EN + FR
# ════════════════════════════════════════════════════════════
RSS_FEEDS = {
    'gn_en': {'url': ('https://news.google.com/rss/search?q=Niger+(Niamey+OR+Tiani+OR+junta+OR+Tillaberi'
                      '+OR+Diffa+OR+Agadez)+when:7d&hl=en-US&gl=US&ceid=US:en'),
              'name': 'GoogleNews-EN', 'weight': 0.85, 'language': 'en'},
    'gn_fr': {'url': ('https://news.google.com/rss/search?q=Niger+(Niamey+OR+Tiani+OR+junte+OR+Tillab%C3%A9ri'
                      '+OR+Diffa)+when:7d&hl=fr&gl=FR&ceid=FR:fr'),
              'name': 'GoogleNews-FR', 'weight': 0.85, 'language': 'fr'},
    'gn_resources': {'url': ('https://news.google.com/rss/search?q=Niger+(uranium+OR+SOMAIR+OR+CNPC+OR+pipeline'
                             '+OR+Orano)+when:7d&hl=en-US&gl=US&ceid=US:en'),
                     'name': 'GoogleNews-Resources', 'weight': 0.85, 'language': 'en'},
    'gn_partners': {'url': ('https://news.google.com/rss/search?q=Niger+(Russia+OR+Algeria+OR+Turkey+OR+%22United'
                            '+States%22+OR+Benin)+Niamey+when:7d&hl=en-US&gl=US&ceid=US:en'),
                    'name': 'GoogleNews-Partners', 'weight': 0.85, 'language': 'en'},
    'rfi_af':   {'url': 'https://www.rfi.fr/fr/afrique/rss', 'name': 'RFI Afrique',
                 'weight': 0.95, 'language': 'fr'},
    'apa':      {'url': 'https://www.apanews.net/feed/', 'name': 'APA News',
                 'weight': 0.9, 'language': 'fr'},
    'reliefweb': {'url': 'https://reliefweb.int/country/ner/rss.xml',
                  'name': 'ReliefWeb NER', 'weight': 1.0, 'language': 'en'},
}
GDELT_QUERIES_EN = [
    '"Niger" AND ("Niamey" OR "Tiani" OR "junta")',
    '"Niger" AND ("Tillaberi" OR "Diffa" OR "Boko Haram" OR "JNIM")',
    '"Niger" AND ("uranium" OR "CNPC" OR "pipeline" OR "Orano")',
    '"Niger" AND ("Russia" OR "Algeria" OR "Turkey" OR "Benin")',
]
GDELT_QUERIES_FR = [
    '"Niger" ET ("Niamey" OU "Tiani" OU "junte")',
    '"Niger" ET ("attaque" OU "uranium" OU "pétrole")',
]
NEWSAPI_QUERIES = ['Niger Niamey junta', 'Niger Tillaberi attack', 'Niger uranium',
                   'Niger CNPC oil pipeline', 'Niger Algeria Russia']
BRAVE_QUERIES = ['Niger Niamey 2026', 'Niger junta Tiani', 'Niger uranium oil']


# ════════════════════════════════════════════════════════════
# VALIDATION -- MEASURED by the harness on the 21 Nov 2026 corpus
# (filled from test_niger_harness.py; see VALIDATION_CORPUS_NOTE)
# ════════════════════════════════════════════════════════════
# Measured 21 Nov 2026 by test_niger_harness.py: 52 verbatim 2026 headlines
# (EN + FR) and 10 negative controls. status: validated = 2+ real headlines
# matched; thin = 1; unvalidated = 0 (excluded from its vector, reads unread).
ACTOR_VALIDATION = {
    'junta_tiani':      {'status': 'validated', 'real_headlines_matched': 9},
    'mutiny_plot':      {'status': 'validated', 'real_headlines_matched': 9},
    'front_tillaberi':  {'status': 'validated', 'real_headlines_matched': 2,
                         'note': 'Western-front coverage often says "western Niger" or "l\'ouest du pays" '
                                 'rather than Tillabéri; both are in the list.'},
    'front_diffa':      {'status': 'validated', 'real_headlines_matched': 2},
    'front_north':      {'status': 'validated', 'real_headlines_matched': 4},
    'attacks_unplaced': {'status': 'validated', 'real_headlines_matched': 8},
    'russia_axis_ne':   {'status': 'validated', 'real_headlines_matched': 3},
    'algeria_axis':     {'status': 'validated', 'real_headlines_matched': 5},
    'us_axis':          {'status': 'validated', 'real_headlines_matched': 4},
    'turkey_axis':      {'status': 'validated', 'real_headlines_matched': 5},
    'iran_axis':        {'status': 'thin', 'real_headlines_matched': 1,
                         'note': 'Rumour-tier spoke by design; one real headline. A hit is reporting '
                                 'about a possibility.'},
    'france_rupture':   {'status': 'validated', 'real_headlines_matched': 8},
    'aes_ecowas':       {'status': 'unvalidated', 'real_headlines_matched': 0,
                         'note': 'No Niger-specific AES/ECOWAS headline in the 2026 harvest. UNTESTED: '
                                 'excluded from its vector and reads unread, never calm.'},
    'uranium_leverage': {'status': 'validated', 'real_headlines_matched': 10},
    'oil_china':        {'status': 'validated', 'real_headlines_matched': 10},
    'benin_border':     {'status': 'validated', 'real_headlines_matched': 5},
}
VALIDATION_AS_OF = '2026-11-21'
VALIDATION_CORPUS_NOTE = (
    '52 verbatim 2026 Niger headlines (EN and FR) + 10 negative controls, including '
    'Niger STATE (Nigeria) and Niger DELTA stories that share the word "Niger". '
    'Country gate: 52/52 passed, 0/10 negative-control leaks.')


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
        print('[NE Rhetoric] redis get %s: %s' % (key, str(e)[:100]))
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
        print('[NE Rhetoric] redis set %s: %s' % (key, str(e)[:100]))
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
        print('[NE Rhetoric] redis lpush %s: %s' % (key, str(e)[:100]))
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
            title, source = e.get('title', ''), cfg['name']
            # v1.0.2 OUTLET FIX (same as CAR v1.0.0): Google News carries many
            # outlets under one feed name. Read the real outlet from the
            # " - Outlet" title suffix, so the two-outlet rule counts newspapers,
            # not feeds -- before this, four Google News stories from four
            # papers counted as ONE outlet ("GoogleNews-EN").
            if 'news.google.com' in cfg.get('url', '') and ' - ' in title:
                title, source = title.rsplit(' - ', 1)
                source = source.strip() or cfg['name']
                # v-next (Nov 27 2026): some outlets sign with a bare URL
                # ("https://corbeaunews-centrafrique.org/"); show the hostname.
                if source.startswith('http'):
                    source = re.sub(r'^https?://(www\.)?', '', source).strip('/') or cfg['name']
            out.append({
                'title': title,
                'description': e.get('summary', '') or e.get('description', ''),
                'url': e.get('link', ''),
                'published': e.get('published', ''),
                'source': source, 'feed_id': feed_id, 'feed_type': 'rss',
                'language': cfg.get('language', 'en'),
                'feed_weight': cfg.get('weight', 1.0),
            })
    except Exception as e:
        print('[NE Rhetoric] RSS %s: %s' % (feed_id, str(e)[:100]))
    return out


def fetch_all_rss():
    out = []
    for fid, cfg in RSS_FEEDS.items():
        got = fetch_rss(fid, cfg)
        if got:
            print('[NE Rhetoric] RSS %s: %d' % (fid, len(got)))
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
    print('[NE Rhetoric] GDELT: %d' % len(out))
    return out




def fetch_newsapi(days=7):
    if not NEWSAPI_KEY:
        return []
    frm = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    out = []
    for q in NEWSAPI_QUERIES:
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
        print('[NE Rhetoric] NewsAPI: %d' % len(out))
    return out


def fetch_brave(gdelt_n=0, news_n=0):
    """Tertiary -- only when the primaries came back thin."""
    if not BRAVE_API_KEY or (gdelt_n + news_n) >= 10:
        return []
    out = []
    for q in BRAVE_QUERIES:
        try:
            r = requests.get(BRAVE_BASE_URL, params={'q': q, 'count': 20, 'freshness': 'pw'},
                             headers={'Accept': 'application/json',
                                      'X-Subscription-Token': BRAVE_API_KEY},
                             timeout=10)
            if r.status_code != 200:
                continue
            for i in r.json().get('results', []):
                out.append({
                    'title': i.get('title', ''), 'description': i.get('description', ''),
                    'url': i.get('url', ''), 'published': i.get('page_age') or i.get('age', ''),
                    'source': i.get('source') or 'Brave', 'feed_id': 'brave',
                    'feed_type': 'brave', 'language': 'en', 'feed_weight': 0.75,
                })
        except Exception:
            pass
        time.sleep(0.5)
    if out:
        print('[NE Rhetoric] Brave: %d' % len(out))
    return out


# ════════════════════════════════════════════════════════════
# GATE + CLASSIFY
# ════════════════════════════════════════════════════════════
def _body(article):
    return _norm(article.get('title', '')) + ' ' + _norm(article.get('description', ''))


def passes_country_gate(article):
    """True when the article is about Niger the COUNTRY.

    1. A Nigerien place, person or institution -> pass ('country').
    2. Otherwise the word "Niger" (not Nigeria/Nigerian) -> pass, UNLESS the
       article carries Niger-State / Niger-Delta context -> reject ('nigeria').
    3. Otherwise an AES-bloc story -> pass ('bloc').
    """
    body = _body(article)
    if any(_kw_in(t, body) for t in STRONG_TOKENS):
        return True, 'country'
    if _NIGER_WORD.search(body):
        if any(t in body for t in NIGERIA_CONTEXT):
            return False, 'nigeria'
        return True, 'country'
    if any(t in body for t in BLOC_GATE):
        return True, 'bloc'
    return False, None


def _classify_article(article):
    body = _body(article)
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
                fired.append((tw_id, tw['severity']))
                break
    return fired


def ladder_rung(text):
    """The worst rung a single article reports (platform scale, 1-5)."""
    body = _norm(text)
    for lv, rxs in _LADDER_RX:
        if any(rx.search(body) for rx in rxs):
            return lv
    return 1


def front_ladder(articles):
    """Front level from the KINETIC LADDER with the two-outlet rule.

    L3+ needs TWO OR MORE distinct outlets reporting at that rung or worse.
    The highest rung with two outlets wins; a single-outlet worst case is
    held at L2 (and reported as such, so the page can say 'one outlet only').
    """
    if not articles:
        return {'level': 0, 'raw_max': 0, 'outlets_at_level': 0, 'held_by_two_outlet_rule': False,
                'worst': None}
    rated = []
    for a in articles:
        r = ladder_rung('%s %s' % (a.get('title', ''), a.get('description', '')))
        rated.append((r, (a.get('source') or a.get('feed_id') or '?').lower(), a))
    raw_max = max(r for r, _, _ in rated)
    level = 1
    for lv in (5, 4, 3):
        outlets = {s for r, s, _ in rated if r >= lv}
        if len(outlets) >= 2:
            level = lv
            break
    else:
        level = min(raw_max, 2)
    worst = max(rated, key=lambda x: x[0])[2]
    return {
        'level': level, 'raw_max': raw_max,
        'outlets_at_level': len({s for r, s, _ in rated if r >= level}),
        'held_by_two_outlet_rule': raw_max >= 3 and level < raw_max,
        'worst': {'title': worst.get('title', ''), 'url': worst.get('url', ''),
                  'source': worst.get('source', '')},
    }


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
LEVEL_TO_PLATFORM = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
PLATFORM_LABELS = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning', 3: 'Confrontation',
                   4: 'Coercion', 5: 'Active Conflict'}


def _rank(lv):
    try:
        return _LEVEL_ORDER.index(lv)
    except ValueError:
        return 0


def _score_actor(articles):
    if not articles:
        return {'score': 0, 'article_count': 0, 'language_breakdown': {},
                'sources': [], 'top_articles': [], 'tripwires': [], 'outlets': 0}
    # OUTLET CAP (Nov 27 2026): one outlet counts for at most OUTLET_CAP
    # articles per actor. Before this, one prolific site (nine Wagner pieces
    # in a week from a single Bangui outlet) could push an actor to SURGE and
    # carry a whole country to L4 on its own. Volume now has to come from
    # several newsrooms, the same principle as the two-outlet rule for L3+.
    per_outlet = {}
    score = 0.0
    langs, srcs = {}, {}
    tw_seen = set()
    for a in articles:
        w = a.get('feed_weight', 1.0)
        hits = a.get('_hits', 1)
        _o = a.get('source', '?')
        per_outlet[_o] = per_outlet.get(_o, 0) + 1
        if per_outlet[_o] <= OUTLET_CAP:
            score += w * min(1.0 + (hits - 1) * 0.15, 2.0)
        langs[a.get('language', 'en')] = langs.get(a.get('language', 'en'), 0) + 1
        srcs[a.get('source', '?')] = srcs.get(a.get('source', '?'), 0) + 1
        for tw_id, sev in _check_tripwires('%s %s' % (a.get('title', ''), a.get('description', ''))):
            tw_seen.add((tw_id, sev))
    ranked = sorted(articles, key=lambda a: (ladder_rung('%s %s' % (a.get('title', ''), a.get('description', ''))),
                                             a.get('feed_weight', 1.0)), reverse=True)
    return {
        'score': round(score, 2),
        'article_count': len(articles),
        'outlets': len(srcs),
        'language_breakdown': langs,
        'sources': [{'source': s, 'count': c} for s, c in sorted(srcs.items(), key=lambda x: -x[1])[:6]],
        'top_articles': [{'title': a.get('title', ''), 'url': a.get('url', ''),
                          'source': a.get('source', ''), 'language': a.get('language', 'en'),
                          'published': a.get('published', '')} for a in ranked[:8]],
        'tripwires': [{'id': i, 'severity': s} for i, s in tw_seen],
    }


# ════════════════════════════════════════════════════════════
# SIBLING READS -- context, never re-fetched, never re-scored
# ════════════════════════════════════════════════════════════
def _read_humanitarian_context():
    h = _redis_get(HUMANITARIAN_KEY) or {}
    if not h:
        return {'available': False,
                'note': 'Humanitarian sensor key absent this cycle -- unread, not calm.'}
    stats = {}
    for s in (h.get('headline_stats') or []):
        lab = (s.get('label') or '').lower()
        if 'hosted' in lab:
            stats['refugees_hosted'] = s.get('value')
        elif lab.startswith('forcibly displaced'):
            stats['displaced'] = s.get('value')
        elif 'expelled' in lab:
            stats['expelled_from_algeria'] = s.get('value')
    cal = h.get('seasonal_calendar') or {}
    return {'available': True, **stats, 'seasonal_open': cal.get('open_now') or [],
            'data_as_of': h.get('data_as_of')}


def _read_commodity_context():
    """CONTEXT ONLY (not scored): uranium and oil prices for display."""
    try:
        from commodity_proxy_africa import get_africa_commodity_data
    except ImportError:
        return {'available': False, 'reason': 'commodity proxy not importable'}
    try:
        d = get_africa_commodity_data('niger') or {}
        out = {'available': False, 'scored': False}
        for t in (d.get('commodity_summaries') or []):
            if t.get('commodity') in ('uranium', 'oil'):
                sp = t.get('sparkline') or {}
                out[t['commodity']] = {'price': sp.get('price'),
                                       'change_pct_1d': sp.get('change_pct_1d'),
                                       'change_pct_30d': sp.get('change_pct_30d'),
                                       'note': t.get('note')}
                out['available'] = True
        return out
    except Exception as e:
        return {'available': False, 'reason': str(e)[:120]}


def _read_crosstheater_amplifiers():
    amps = {}
    for label, key in (('russia_fingerprint', 'crosstheater:russia:fingerprint'),
                       ('mali_fingerprint', 'crosstheater:mali:fingerprint'),
                       ('burkina_faso_fingerprint', 'crosstheater:burkina_faso:fingerprint'),
                       ('hormuz_chokepoint', 'military:chokepoint:hormuz')):
        v = _redis_get(key)
        if v:
            amps[label] = v
    return amps


# ════════════════════════════════════════════════════════════
# RESOURCE LEVERAGE -- three states, like Burkina's commercial axis
# ════════════════════════════════════════════════════════════
def _resource_axis(actor_summaries, tripwires):
    """refusal = the state taking control of its resources (uranium
    nationalisation and sale, demands and ultimatums to CNPC);
    capture = foreign positioning (new financing, offtake, concessions to a
    foreign company); unread = no reporting. Both scores are always carried."""
    ur = actor_summaries.get('uranium_leverage') or {}
    oil = actor_summaries.get('oil_china') or {}
    tw = {t.get('id') for t in tripwires}
    refusal = _rank(ur.get('level', 'low')) + (2 if 'china_oil_rupture' in tw else 0)
    # An oil level RAISED by the ultimatum red line is Niamey pulling control
    # back -- refusal, already counted above -- not foreign capture.
    oil_cap = 0 if oil.get('level_basis') == 'red_line:china_oil_rupture' else _rank(oil.get('level', 'low'))
    capture = oil_cap + (1 if 'uranium_sale' in tw else 0)
    us = actor_summaries.get('us_axis') or {}
    if us.get('level') in ('elevated', 'high', 'surge'):
        capture += 1   # foreign financing of a mine is positioning, whoever it is
    if refusal == 0 and capture == 0:
        state, reading = 'unread', ('No resource reporting this cycle: an UNREAD axis, not a settled one.')
    elif refusal > capture:
        state, reading = 'refusal', ('The state is pulling its resources toward itself faster than '
                                     'foreigners are positioning: nationalised uranium for sale on its '
                                     'own terms, demands on the Chinese oil companies.')
    elif capture > refusal:
        state, reading = 'capture', ('Foreign positioning on Niger\'s resources is outpacing state '
                                     'demands. Watch WHOSE: Russian, American, Turkish and Chinese '
                                     'interest read the same on volume and differently on everything else.')
    else:
        state, reading = ('refusal' if refusal else 'unread'), (
            'Refusal and capture are level this cycle: Niger is demanding more from its foreign '
            'partners while courting new ones. Read both scores.')
    return {'id': 'resource_axis_niger', 'state': state, 'refusal_score': refusal,
            'capture_score': capture, 'both_hot': refusal >= 2 and capture >= 2, 'reading': reading,
            'states_defined': ['capture', 'refusal', 'unread'],
            'watch': ['Expiry of the CNPC 45-day ultimatum (~30 Nov 2026) and what Niamey does next',
                      'Any confirmed buyer or shipment of SOMAÏR uranium',
                      'Dasa construction and offtake under the US DFC loan',
                      'Orano arbitration rulings']}


# ════════════════════════════════════════════════════════════
# PROSE -- estimative voice, builtin (no Claude call)
# ════════════════════════════════════════════════════════════
# GPI-SAFE SIGNALS (v1.0.1). The regional BLUF passes these straight to the
# GPI, which (a) coerces the WORD 'surge' to L5 and (b) guesses the axis from
# the category. So every signal carries:
#   * a NUMERIC platform level -- red lines map surge->4, high->3,
#     elevated->2, because L5 comes only from a front ladder;
#   * an explicit pressure_type (kinetic / economic / diplomatic / governance);
#   * standing=True on the standing fronts (Tillaberi, Diffa), so a standing
#     insurgency is not headlined as new.
TRIPWIRE_SIG_LEVEL = {'surge': 4, 'high': 3, 'elevated': 2}
TRIPWIRE_AXIS = {
    'capital_attacked': 'kinetic', 'regime_change_event': 'governance', 'mutiny': 'governance',
    'mass_casualty_event': 'kinetic', 'pipeline_sabotage': 'economic', 'china_oil_rupture': 'economic',
    'foreign_force_deployment': 'diplomatic', 'uranium_sale': 'economic',
    'diplomatic_rupture': 'diplomatic', 'aes_fracture': 'diplomatic', 'benin_border_reopens': 'economic',
}
ACTOR_AXIS = {
    'junta_tiani': 'governance', 'mutiny_plot': 'governance',
    'russia_axis_ne': 'diplomatic', 'algeria_axis': 'diplomatic', 'us_axis': 'diplomatic',
    'turkey_axis': 'diplomatic', 'iran_axis': 'diplomatic', 'france_rupture': 'diplomatic',
    'aes_ecowas': 'diplomatic', 'uranium_leverage': 'economic', 'oil_china': 'economic',
    'benin_border': 'economic',
}
SIG_COLOR = {0: '#6b7280', 1: '#3b82f6', 2: '#f59e0b', 3: '#f97316', 4: '#ef4444', 5: '#7c3aed'}


def _prose(theatre_level, fronts, actor_summaries, vector_levels, tripwires, resource_axis):
    sigs = []
    for t in tripwires[:4]:
        tid = t.get('id', 'tripwire')
        lv = TRIPWIRE_SIG_LEVEL.get(t.get('severity'), 2)
        sigs.append({'level': lv, 'severity': t.get('severity'), 'type': 'tripwire', 'priority': 10,
                     'category': 'tripwire', 'pressure_type': TRIPWIRE_AXIS.get(tid, 'kinetic'),
                     'theatre': 'niger', 'icon': '🚨', 'color': SIG_COLOR[lv],
                     'short_text': '🇳🇪 NIGER red line: %s' % tid.replace('_', ' '),
                     'long_text': (TRIPWIRES.get(tid) or {}).get('note', '')})
    for fid, f in fronts.items():
        if f['level'] >= 3:
            sigs.append({'level': f['level'], 'type': 'front', 'priority': 9,
                         'category': 'kinetic_front', 'pressure_type': 'kinetic',
                         'standing': bool(f.get('standing')), 'front': fid,
                         'theatre': 'niger', 'icon': '💥', 'color': SIG_COLOR.get(f['level'], '#6b7280'),
                         'short_text': '🇳🇪 NIGER %s at L%d%s' % (
                             f['name'], f['level'], ' (standing insurgency)' if f.get('standing') else ''),
                         'long_text': ('Worst report: "%s" (%s). %d outlets at this rung.%s'
                                       % ((f.get('worst') or {}).get('title', '')[:140],
                                          (f.get('worst') or {}).get('source', ''), f['outlets_at_level'],
                                          ' A standing insurgency: fighting here is the condition, not news.'
                                          if f.get('standing') else ''))})
    for aid in ('russia_axis_ne', 'algeria_axis', 'us_axis', 'oil_china', 'uranium_leverage',
                'turkey_axis', 'france_rupture', 'benin_border', 'mutiny_plot'):
        s = actor_summaries.get(aid) or {}
        if s.get('level') in ('elevated', 'high', 'surge'):
            ta = (s.get('top_articles') or [{}])[0]
            lv = LEVEL_TO_PLATFORM.get(s['level'], 2)
            sigs.append({'level': lv, 'type': 'actor_signal', 'priority': 7,
                         'category': 'actor_signal', 'pressure_type': ACTOR_AXIS.get(aid, 'diplomatic'),
                         'theatre': 'niger', 'icon': ACTORS[aid]['icon'], 'color': SIG_COLOR.get(lv, '#6b7280'),
                         'short_text': '🇳🇪 NIGER %s at %s' % (ACTORS[aid]['name'], s['level'].upper()),
                         'long_text': '"%s" (%s)' % (ta.get('title', '')[:160], ta.get('source', ''))})
    sigs.sort(key=lambda x: -x.get('priority', 0))

    hot_fronts = [f['name'] for f in fronts.values() if f['level'] >= 3]
    active_partners = [ACTORS[a]['name'] for a in ('russia_axis_ne', 'algeria_axis', 'us_axis',
                                                   'turkey_axis', 'oil_china')
                       if (actor_summaries.get(a) or {}).get('level') in ('elevated', 'high', 'surge')]
    parts = ['Niger reads L%d (%s).' % (theatre_level, PLATFORM_LABELS.get(theatre_level, ''))]
    parts.append(('Fronts at L3 or above: %s.' % ', '.join(hot_fronts)) if hot_fronts
                 else 'No front reached L3 on two outlets this window.')
    if active_partners:
        parts.append('Partners in the news above baseline: %s.' % ', '.join(active_partners))
    parts.append('Resource axis: %s.' % resource_axis['state'])
    parts.append('Convergence read, not prediction.')

    so_what = []
    if any(f['level'] >= 3 and f.get('standing') for f in fronts.values()):
        so_what.append({'weight': 0.8, 'bullet': (
            'Tillabéri and Diffa are standing insurgencies: fighting there is the condition, not news. '
            'What would be news is a front reaching L5 (a town or base taken), the fighting reaching '
            'Niamey again, or the northern rebels hitting the pipeline.')})
    if 'china_oil_rupture' in {t.get('id') for t in tripwires} or \
            (actor_summaries.get('oil_china') or {}).get('level') in ('high', 'surge'):
        _exp = datetime(2026, 11, 30, tzinfo=timezone.utc)
        _when = ('expires around 30 November' if datetime.now(timezone.utc) < _exp
                 else 'passed its deadline around 30 November')
        so_what.append({'weight': 0.95, 'bullet': (
            'The CNPC ultimatum (16 Oct, 45 days, ~$5bn of export revenue) %s. '
            'Oil is the revenue the junta depends on and China\'s main stake in Niger: watch whether '
            'Niamey escalates (suspensions, expulsions) or quietly extends.' % _when)})
    if (actor_summaries.get('algeria_axis') or {}).get('level') in ('elevated', 'high', 'surge'):
        so_what.append({'weight': 0.85, 'bullet': (
            'Algeria is now a security patron alongside Russia: aircraft after the August mutiny and '
            'troops ordered on 26 October. Two guarantors with different interests is new leverage -- '
            'and the same neighbour expels tens of thousands of people into Niger at Assamaka.')})
    if (actor_summaries.get('mutiny_plot') or {}).get('level') in ('elevated', 'high', 'surge'):
        so_what.append({'weight': 0.9, 'bullet': (
            'Regime-security reporting is above baseline. The August mutiny was contained only with '
            'Russian and Algerian help; read any new arrests or purges against that.')})
    if resource_axis.get('both_hot'):
        so_what.append({'weight': 0.85, 'bullet': (
            'Resource axis both-hot: Niger is squeezing one partner (CNPC) while courting others '
            '(US uranium finance, Russian and Turkish interest).')})
    if not so_what:
        so_what.append({'weight': 0.3, 'bullet': (
            'Nothing above baseline this scan. Baseline for Niger still means two standing '
            'insurgencies, a shut road to the sea and a government defended by foreign forces. '
            'A quiet scan is a quiet feed, not a quiet country.')})
    so_what.sort(key=lambda b: -b['weight'])
    return sigs[:10], ' '.join(parts), so_what[:6]


# ════════════════════════════════════════════════════════════
# MAIN SCAN
# ════════════════════════════════════════════════════════════
FRONT_ACTORS = ['front_tillaberi', 'front_diffa', 'front_north', 'attacks_unplaced']


def _gather(days):
    rss = fetch_all_rss()
    gdelt = fetch_all_gdelt(days)
    newsapi = fetch_newsapi(days)
    brave = fetch_brave(len(gdelt), len(newsapi))
    return rss, gdelt, newsapi, brave


def score_articles(articles):
    """Everything after fetching. Split out so the test harness can run the
    real scoring on a fixed corpus."""
    gated, rejected = [], 0
    gate_reasons = {'country': 0, 'bloc': 0, 'nigeria': 0}
    for a in articles:
        ok, why = passes_country_gate(a)
        if ok:
            gate_reasons[why] += 1
            gated.append(a)
        else:
            rejected += 1
            if why == 'nigeria':
                gate_reasons['nigeria'] += 1

    by_actor = {k: [] for k in ACTORS}
    _named_fronts = {'front_tillaberi', 'front_diffa', 'front_north'}
    for a in gated:
        cls = _classify_article(a)
        # An attack that names its front is not "unplaced" (v1.0.1): counting
        # it twice would put a second, non-standing L4 into the GPI.
        if any(aid in _named_fronts for aid, _ in cls):
            cls = [(aid, h) for aid, h in cls if aid != 'attacks_unplaced']
        for aid, hits in cls:
            c = dict(a)
            c['_hits'] = hits
            by_actor[aid].append(c)

    actor_summaries, tripwires = {}, []
    for aid, meta in ACTORS.items():
        sc = _score_actor(by_actor[aid])
        lvl = actor_alert_level(sc['score'], meta['baseline_statements_per_week'])
        actor_summaries[aid] = {
            'name': meta['name'], 'flag': meta['flag'], 'icon': meta['icon'],
            'color': meta['color'], 'role': meta['role'], 'description': meta['description'],
            'vector': meta['vector'], 'wheel': meta.get('wheel'), 'axis_side': meta.get('axis_side'),
            'level': lvl, 'score': sc['score'], 'baseline': meta['baseline_statements_per_week'],
            'article_count': sc['article_count'], 'outlets': sc['outlets'],
            'language_breakdown': sc['language_breakdown'], 'sources': sc['sources'],
            'top_articles': sc['top_articles'], 'tripwires': sc['tripwires'],
            'source_headlines': meta.get('source_headlines', []),
            'validation': ACTOR_VALIDATION.get(aid, {'status': 'unknown'}),
        }
        # A red line touching this actor sets a FLOOR under its level: a
        # breached red line is a confrontation however few outlets wrote it.
        _floor = {'surge': 'surge', 'high': 'high', 'elevated': 'elevated'}
        for tw in sc['tripwires']:
            f = _floor.get(tw.get('severity'))
            if f and _rank(f) > _rank(actor_summaries[aid]['level']):
                actor_summaries[aid]['level'] = f
                actor_summaries[aid]['level_basis'] = 'red_line:%s' % tw['id']
            if not any(t['id'] == tw['id'] for t in tripwires):
                tripwires.append({'actor': aid, **tw})

    # ── KINETIC LADDER per front ──
    fronts = {}
    for aid in FRONT_ACTORS:
        lad = front_ladder(by_actor[aid])
        fronts[ACTORS[aid]['front']] = {
            'actor': aid, 'name': ACTORS[aid]['name'], 'standing': ACTORS[aid].get('standing', False),
            **lad,
        }
        actor_summaries[aid]['ladder'] = lad
    kinetic_level = max([f['level'] for k, f in fronts.items()] + [0])

    # ── vectors: word levels for the page, platform ints for the rollup ──
    vector_levels, vector_levels_platform = {}, {}
    for vec, members in VECTOR_GROUPS.items():
        if vec == 'insurgent_fronts':
            vector_levels_platform[vec] = kinetic_level
            vector_levels[vec] = 'L%d' % kinetic_level
            continue
        measured = [m for m in members
                    if ACTOR_VALIDATION.get(m, {}).get('status') != 'unvalidated']
        lv = [actor_summaries[m]['level'] for m in measured]
        if not lv:
            vector_levels[vec] = 'unread'
            continue
        top = max(lv, key=_rank)
        vector_levels[vec] = top
        vector_levels_platform[vec] = LEVEL_TO_PLATFORM[top]   # caps at 4 by construction

    # ── theatre level: rhetoric vectors cap at L4; ONLY the ladder reaches L5 ──
    non_kinetic = max([v for k, v in vector_levels_platform.items() if k != 'insurgent_fronts'] + [0])
    theatre_level = max(min(non_kinetic, 4), kinetic_level)
    l5_gate = {'kinetic': kinetic_level >= 5, 'any': kinetic_level >= 5,
               'fired': [{'front': k, 'level': f['level']} for k, f in fronts.items() if f['level'] >= 5],
               'reason': ('A front ladder reached L5 on two or more outlets.' if kinetic_level >= 5 else
                          'No front ladder at L5. L5 needs a town or base taken, or the capital '
                          'attacked, reported by two or more outlets. Tripwires and rhetoric '
                          'volume cannot open it.')}
    return {
        'gated': gated, 'rejected': rejected, 'gate_reasons': gate_reasons,
        'actor_summaries': actor_summaries, 'tripwires': tripwires, 'fronts': fronts,
        'kinetic_level': kinetic_level, 'vector_levels': vector_levels,
        'vector_levels_platform': vector_levels_platform, 'theatre_level': theatre_level,
        'l5_gate': l5_gate,
    }


def _write_spokes(actor_summaries, theatre_level, ts):
    """spoke:<hub>:niger for each wheel Niger sits on. No 'trajectory' key:
    Niger has no directional sensor, and inventing 'holding' would be a
    reading out of nothing (the Burkina rule)."""
    written = []
    for hub, cfg in SPOKES.items():
        s = actor_summaries.get(cfg['actor']) or {}
        lvl_word = s.get('level', 'low')
        lvl = LEVEL_TO_PLATFORM.get(lvl_word, 0)
        ta = (s.get('top_articles') or [{}])[0]
        if lvl >= 2 and ta.get('title'):
            top = 'Niger: %s at L%d -- "%s"' % (ACTORS[cfg['actor']]['name'], lvl, ta['title'][:110])
        elif s.get('article_count'):
            top = 'Niger: %s -- background mentions only (L%d).' % (ACTORS[cfg['actor']]['name'], lvl)
        else:
            top = 'Niger: no %s reporting this window. Unread, not calm.' % ACTORS[cfg['actor']]['name']
        ok = _redis_set('spoke:%s:niger' % hub, {
            'ts': ts, 'hub': hub, 'country': 'niger', 'level': lvl,
            'node_class': cfg['node_class'], 'relationship': cfg['node_class'],
            'top_signal': top[:180], 'why': cfg['why'], 'items': s.get('article_count', 0),
            'theatre_level': theatre_level,
            'rumour_tier': hub == 'iran',
            'source': 'rhetoric_tracker_niger v%s' % MODULE_VERSION,
        }, ttl_hours=SPOKE_TTL_HOURS)
        if ok:
            written.append(hub)
    if written:
        print('[NE Rhetoric] spokes written: %s' % ', '.join(written))
    return written


def scan_niger_rhetoric(force=False, days=7):
    global _last_scan_started_at
    _last_scan_started_at = datetime.now(timezone.utc)
    t0 = time.time()
    print('[NE Rhetoric] === scan start (force=%s days=%s) ===' % (force, days))

    rss, gdelt, newsapi, brave = _gather(days)
    seen, articles = set(), []
    for a in (rss + gdelt + newsapi + brave):
        u = a.get('url', '')
        if u and u not in seen:
            seen.add(u)
            articles.append(a)

    # RECENCY GATE (Nov 27 2026). Google News search and Brave ignore the
    # 7-day window, so stale stories were scoring as this week's news. Drop
    # anything older than the window BEFORE the country gate and the ladders.
    try:
        from recency_gate import filter_recent
        articles, _recency = filter_recent(articles, days)
    except Exception as _e:
        _recency = {'error': 'recency gate failed open: %s' % str(_e)[:100]}
    _RECENCY_STATE['last'] = _recency
    print('[NE Rhetoric] recency gate: %s' % _recency)

    S = score_articles(articles)
    actor_summaries, tripwires, fronts = S['actor_summaries'], S['tripwires'], S['fronts']
    theatre_level = S['theatre_level']

    humanitarian = _read_humanitarian_context()
    commodity = _read_commodity_context()
    amplifiers = _read_crosstheater_amplifiers()
    resource_axis = _resource_axis(actor_summaries, tripwires)
    top_signals, executive_summary, so_what = _prose(
        theatre_level, fronts, actor_summaries, S['vector_levels'], tripwires, resource_axis)

    # BLUF dialect (as Burkina): tripwires ARE red lines.
    _rl = [{'id': t.get('id'), 'actor': t.get('actor'), 'severity': t.get('severity'),
            'status': 'BREACHED' if t.get('severity') in ('surge', 'high') else 'APPROACHING',
            'note': (TRIPWIRES.get(t.get('id')) or {}).get('note', '')} for t in tripwires]
    red_lines = {'triggered': _rl,
                 'breached_count': sum(1 for r in _rl if r['status'] == 'BREACHED'),
                 'approaching_count': sum(1 for r in _rl if r['status'] == 'APPROACHING')}

    composite_score = round(sum(s['score'] for s in actor_summaries.values()), 2)
    now = datetime.now(timezone.utc).isoformat()
    result = {
        'success': True, 'country': 'niger', 'country_display': 'Niger',
        'module': 'rhetoric_tracker_niger', 'version': MODULE_VERSION,
        'node_class': 'multi_wheel_spoke',

        'theatre_level': theatre_level,
        'theatre_score': min(100, int(composite_score)),
        'theatre_label': PLATFORM_LABELS.get(theatre_level, 'Monitoring'),
        'composite_score': composite_score,
        'kinetic_level': S['kinetic_level'],
        'l5_gate': S['l5_gate'],
        'fronts': fronts,
        'standing_fronts': [k for k, f in fronts.items() if f.get('standing')],

        'vector_levels': S['vector_levels'],
        'vector_levels_platform': S['vector_levels_platform'],
        'vector_labels': VECTOR_LABELS,
        'red_lines': red_lines,
        'scan_date': now,
        'article_count': len(S['gated']),
        'actor_summaries': actor_summaries,
        'actor_validation_as_of': VALIDATION_AS_OF,
        'validation_corpus_note': VALIDATION_CORPUS_NOTE,
        'tripwires_global': tripwires,
        'resource_axis': resource_axis,
        'spokes': {hub: {'actor': c['actor'], 'node_class': c['node_class'],
                         'level': LEVEL_TO_PLATFORM.get((actor_summaries.get(c['actor']) or {}).get('level', 'low'), 0)}
                   for hub, c in SPOKES.items()},

        'humanitarian_context': humanitarian,
        'commodity_context': commodity,
        'crosstheater_amplifiers': amplifiers,

        'top_signals': top_signals,
        'executive_summary': executive_summary,
        'so_what': so_what,

        'source_breakdown': {'rss': len(rss), 'gdelt': len(gdelt), 'newsapi': len(newsapi), 'brave': len(brave)},
        'articles_scanned': len(articles),
        'articles_passed_country_gate': len(S['gated']),
        'articles_rejected_by_gate': S['rejected'],
        'rejected_as_nigeria_state_or_delta': S['gate_reasons']['nigeria'],
        'gate_note': ('An article must name a Nigerien place, person or institution, or say "Niger" '
                      'without Niger-State / Niger-Delta context, before any actor keyword runs.'),
        'scan_time_seconds': round(time.time() - t0, 1),
        'days_analyzed': days, 'recency': _recency,
        'last_updated': now,
        'cached': False,
    }
    save_cache(result)

    _write_spokes(actor_summaries, theatre_level, now)
    _redis_set(FINGERPRINT_KEY, {
        'ts': now, 'theatre': 'niger', 'country': 'niger', 'node_class': 'multi_wheel_spoke',
        'theatre_level': theatre_level, 'kinetic_level': S['kinetic_level'],
        'fronts': {k: {'level': f['level'], 'standing': f.get('standing')} for k, f in fronts.items()},
        'spokes': result['spokes'], 'resource_axis_state': resource_axis['state'],
        'tripwires': tripwires[:6],
    }, ttl_hours=14)
    try:
        _redis_lpush_trim(HISTORY_KEY, {
            'scanned_at': now, 'theatre_level': theatre_level, 'kinetic_level': S['kinetic_level'],
            'red_lines_count': len(tripwires),
            **{k: v for k, v in S['vector_levels'].items()},
            'resource_axis_state': resource_axis['state'],
        }, max_len=336)
    except Exception as e:
        print('[NE Rhetoric] history write failed: %s' % str(e)[:100])

    print('[NE Rhetoric] done in %ss -- L%s (kinetic L%s), gate %d/%d (%d Niger-State/Delta rejected)'
          % (result['scan_time_seconds'], theatre_level, S['kinetic_level'], len(S['gated']),
             len(articles), S['gate_reasons']['nigeria']))
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
                scan_niger_rhetoric(force=True, days=7)
            finally:
                with _scan_lock:
                    _scan_running = False
            time.sleep(BACKGROUND_REFRESH_HOURS * 3600)
        except Exception as e:
            print('[NE Rhetoric] background error: %s' % str(e)[:150])
            time.sleep(600)


def start_background_refresh():
    threading.Thread(target=_background_loop, daemon=True, name='NERhetoricBG').start()
    print('[NE Rhetoric] background thread started (initial delay %ss)' % INITIAL_SCAN_DELAY_SECONDS)


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════
def register_niger_rhetoric_routes(app, start_background=True):
    from flask import jsonify, request

    @app.route('/api/rhetoric/niger', methods=['GET', 'OPTIONS'])
    def api_ne_rhetoric():
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
                    threading.Thread(target=lambda: scan_niger_rhetoric(force=True), daemon=True).start()
            return jsonify(cached)
        return jsonify(scan_niger_rhetoric(force=force, days=7))

    @app.route('/api/rhetoric/niger/debug', methods=['GET'])
    def api_ne_rhetoric_debug():
        cached = load_cache()
        return jsonify({
            'module': 'rhetoric_tracker_niger v%s' % MODULE_VERSION,
            'actors': list(ACTORS.keys()), 'vectors': list(VECTOR_GROUPS.keys()),
            'spokes': list(SPOKES.keys()), 'tripwires': list(TRIPWIRES.keys()),
            'l5_rule': 'Only a front kinetic ladder at L5 on two or more outlets.',
            'actor_validation': ACTOR_VALIDATION, 'validation_as_of': VALIDATION_AS_OF,
            'rss_feeds': len(RSS_FEEDS), 'redis_wired': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured': bool(NEWSAPI_KEY), 'brave_configured': bool(BRAVE_API_KEY),
            'recency_gate': _RECENCY_STATE['last'],
            'cache_present': cached is not None,
            'cache_fresh': is_cache_fresh(cached) if cached else False,
            'last_scan_started_at': _last_scan_started_at.isoformat() if _last_scan_started_at else None,
            'background_running': _scan_running,
        })

    print('[NE Rhetoric] endpoints registered: /api/rhetoric/niger, /api/rhetoric/niger/debug')
    if start_background:
        start_background_refresh()


print('[NE Rhetoric] module loaded -- v%s' % MODULE_VERSION)
