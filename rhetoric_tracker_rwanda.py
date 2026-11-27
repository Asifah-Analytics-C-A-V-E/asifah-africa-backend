"""
rhetoric_tracker_rwanda.py -- Asifah Analytics Africa Backend -- v1.0.0
27 November 2026

RWANDA HUB TRACKER. The analyst layer behind rwanda-stability.html, and the
first Africa tracker built as a HUB first: its main question is not "what is
happening inside Rwanda" but "what does Rwanda do to its neighbours -- and
what happens to that when Washington turns against it?"

THE UNASKED QUESTION
    Rwanda sells security. Its army guards governments by invitation in the
    Central African Republic and in Mozambique, where Rwandan troops made the
    $20B Mozambique LNG restart possible (full restart 29 Jan 2026, first LNG
    targeted 2029). At the same time the US has sanctioned the army (Mar
    2026), a Kigali gold refinery (Jun 2026) and the Ministry of Defence (Oct
    2026), and excludes Rwanda from AGOA from Jan 2027, over what UN experts
    and the US say is support for M23 in the DRC (Kigali denies it). So:
    DOES THE SECURITY-EXPORT MODEL SURVIVE WESTERN PRESSURE? That is the
    signature axis (EXPORT VS PRESSURE) below.

THREE LENSES
    1. THE WHEEL (read, not re-scored). spoke_wheel_reader.read_wheel('rwanda')
       reads what the SPOKE trackers say: CAR (security_partner), the DRC
       (proxy_backing -- contested, attributed) and Mozambique (security_partner;
       NOT REPORTING until the Mozambique tracker ships). Convergence = two or
       more spokes lit.
    2. THE HUB LENS. This tracker's own actors read the same relationships from
       Kigali's side (car_mission, mozambique_mission, drc_file). Shown beside
       each spoke; NEVER counted toward convergence (that would let one
       newsroom light a spoke twice).
    3. KIGALI'S OWN SIGNALS. Posture, US pressure, Europe, China and the other
       partners, minerals and gold, the economy, the EU return hub, and home
       soil (the only kinetic ladder -- L5 can only come from here).

BURUNDI is a STRAND of the DRC file (Rachel, 27 Nov 2026): an actor of its own
so it can be read, but grouped with the DRC spoke, because Burundi's quarrel
with Rwanda is fought on Congolese soil.

RIPPLE CHAINS (Rachel's standing rule, 27 Nov 2026)
    Every actor carries what it touches at four scales -- the country, the
    region, the continent, the globe -- plus the follow-on questions. Static,
    dated, never scored. Surfaced for every LIT actor.

KIGALI-ALIGNED VOICES
    KT Press and Taarifa publish clean RSS and are close to the government's
    line. They are kept (they ARE how Kigali's posture is read) but tagged
    voice='kigali_aligned', weighted 0.8, and subject to the outlet cap like
    everyone else, so they can say what Kigali says but cannot by themselves
    make a signal. Attribution throughout: the Rwanda-M23 link is always what
    UN experts and the US say, with Kigali's denial.

DISCIPLINE CARRIED IN FROM DAY ONE
    Recency gate, outlet cap (2 per outlet per actor), the Google News outlet
    fix, the two-outlet rule for L3+, no Claude calls anywhere.

EMITS
    rhetoric:rwanda:latest            full payload (12h)  <- africa_regional_bluf
    rhetoric:rwanda:history           rolling snapshots
    crosstheater:rwanda:fingerprint   slice for BLUF / GPI (hub_declared)
    spoke:us:rwanda                   Rwanda on the US wheel (sanctions_target)
    spoke:china:rwanda                Rwanda on the China wheel (resource_client)

ENDPOINTS
    GET /api/rhetoric/rwanda
    GET /api/rhetoric/rwanda?refresh=true   (no Claude calls; news fetch only)
    GET /api/rhetoric/rwanda/debug

Convergence, not prediction.
COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import threading
from datetime import datetime, timezone, timedelta

import requests

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False
    print('[Rwanda Rhetoric] feedparser unavailable -- RSS disabled')

MODULE_VERSION = '1.0.0'
_RECENCY_STATE = {'last': None}
OUTLET_CAP = 2

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
NEWSAPI_KEY   = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY')

CACHE_TTL_HOURS            = 12
BACKGROUND_REFRESH_HOURS   = 12
INITIAL_SCAN_DELAY_SECONDS = 420   # behind the spokes: Burkina 150, Niger 210, CAR 270, DRC 330

REDIS_KEY_LATEST = 'rhetoric:rwanda:latest'
HISTORY_KEY      = 'rhetoric:rwanda:history'
FINGERPRINT_KEY  = 'crosstheater:rwanda:fingerprint'
HUMANITARIAN_KEY = 'africa:humanitarian:rwanda'
SPOKE_TTL_HOURS  = 30

GDELT_BASE_URL   = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI_BASE_URL = 'https://newsapi.org/v2/everything'
BRAVE_BASE_URL   = 'https://api.search.brave.com/res/v1/news/search'

CACHE_FILE = '/tmp/rwanda_rhetoric_cache.json'

_scan_running = False
_scan_lock = threading.Lock()
_last_scan_started_at = None

FLAG = '\U0001F1F7\U0001F1FC'


# ════════════════════════════════════════════════════════════
# ACTORS -- 14 actors / 6 vectors
# Keywords trace to 2025-26 headlines (harvested 27 Nov 2026). Rwanda-
# specific phrasings on purpose: every DRC story mentions Rwanda, so a
# generic word like "sanctions" would let the DRC news cycle light the
# whole board.
# ════════════════════════════════════════════════════════════
ACTORS = {
    # ── VECTOR: kigali_posture ───────────────────────────────
    'kagame_govt': {
        'name': 'Kigali (Kagame government)', 'flag': FLAG, 'icon': '\U0001F3DB️', 'color': '#38bdf8',
        'role': 'The presidency, the foreign ministry and the government spokesperson -- what Kigali says',
        'description': ('President Paul Kagame (in office since 2000; re-elected July 2024), Foreign Minister '
                        'Olivier Nduhungirehe and spokesperson Yolande Makolo. Read as Kigali\'s POSTURE: what it '
                        'denies, what it threatens, whom it courts. Kigali-aligned outlets are part of this '
                        'read and are labelled as such.'),
        'vector': 'kigali_posture',
        'keywords': ['kagame', 'nduhungirehe', 'makolo', 'government of rwanda', 'rwandan government',
                     'gouvernement rwandais', 'kigali says', 'kigali rejects', 'kigali denies', 'rwanda rejects',
                     'rwanda denies', 'rwanda dismisses', 'rwanda slams', 'rwanda responds', 'minaffet',
                     'rwandan foreign minister', 'rwanda says'],
        'source_headlines': [
            "2026-11-27 Why Global Recognition of Kagame's Health Leadership Resonates at Home and Beyond (KT Press)",
            '2026-04-03 Rwandan troops in Mozambique for solidarity, not money -- Makolo (New Times)',
            '2026-02-20 Nduhungirehe: Burundi should not get involved in AU mediation of DR Congo crisis (New Times)',
            '2026-06-02 Kagame and Macron inaugurate genocide memorial archive in Paris (Wikipedia: 2026 in Rwanda)',
            'Rwanda, Oman: Kagame state visit 2026 (Rio Times)',
        ],
        'baseline_statements_per_week': 5,
    },
    'rdf_posture': {
        'name': 'The RDF (army)', 'flag': FLAG, 'icon': '\U0001F396️', 'color': '#0ea5e9',
        'role': 'The Rwanda Defence Force as an institution -- commanders, deployments, training missions',
        'description': ('A small, disciplined army that other governments invite: CAR, Mozambique, South Sudan '
                        '(UNMISS). Sanctioned by the US in March 2026 (army and four officers), with the '
                        'Ministry of Defence added in October 2026. Kigali rejects the allegations.'),
        'vector': 'kigali_posture',
        'keywords': ['rwanda defence force', 'rwanda defense force', 'rwandan army', 'rwandan troops',
                     'rwandan forces', 'rwandan soldiers', 'armée rwandaise', 'troupes rwandaises', 'rdf',
                     'rwanda security forces', 'nyakarundi', 'mubarakh muganga', 'rwandan military'],
        'source_headlines': [
            'Gen Nyakarundi briefs RDF, Police contingent ahead of Mozambique deployment (New Times)',
            '2026-02-27 Rwanda: RDF Army Chief On Official Visit to Mozambique (allAfrica)',
            '2026-03-03 US sanctions Rwandan army and top officials for supporting M23 in DRC (Al Jazeera)',
        ],
        'baseline_statements_per_week': 3,
    },

    # ── VECTOR: wheel_spokes (the HUB LENS on each spoke) ────
    'car_mission': {
        'name': 'CAR mission', 'flag': '\U0001F1E8\U0001F1EB', 'icon': '\U0001F6E1️', 'color': '#22c55e',
        'role': 'Rwandan troops in the Central African Republic -- MINUSCA and the bilateral guard',
        'description': ('Rwandan troops serve under MINUSCA and, bilaterally, guard the presidency alongside the '
                        'Russians; RDF instructors graduated nearly 700 CAR soldiers in August 2026. The CAR '
                        'tracker reads this from Bangui\'s side; this actor reads it from Kigali\'s.'),
        'vector': 'wheel_spokes', 'spoke': 'car',
        'keywords': ['central african republic', 'centrafrique', 'centrafricain', 'bangui', 'touadéra', 'touadera',
                     'minusca', 'car soldiers', 'faca'],
        'source_headlines': [
            '2026-08-11 Central African Republic: Nearly 700 CAR Soldiers Graduate From RDF-Led Training (allAfrica)',
            'Rwanda, CAR military chiefs discuss cooperation (New Times)',
            '2025-11-25 Central Africa: Kagame, Touadéra Discuss Security Ahead of CAR Elections (allAfrica)',
            'Rwandan army chief visits troops in Central African Republic (New Times)',
        ],
        'baseline_statements_per_week': 1,
    },
    'mozambique_mission': {
        'name': 'Mozambique mission', 'flag': '\U0001F1F2\U0001F1FF', 'icon': '\U0001F6E1️', 'color': '#16a34a',
        'role': 'Rwandan troops and police in Cabo Delgado -- the guard on the LNG restart',
        'description': ('Deployed at Maputo\'s request since July 2021; credited with the security that let '
                        'TotalEnergies lift force majeure (Nov 2025) and fully restart the $20B Mozambique LNG '
                        'project (29 Jan 2026). Rwanda threatened to withdraw over funding in early 2026; '
                        'Mozambique secured funds in May. Until the Mozambique tracker ships, this is the ONLY '
                        'read of this spoke -- and it is the hub\'s lens, not the spoke\'s.'),
        'vector': 'wheel_spokes', 'spoke': 'mozambique',
        'keywords': ['mozambique', 'moçambique', 'mozambican', 'cabo delgado', 'mocímboa', 'mocimboa', 'palma',
                     'afungi', 'chapo', 'mozambique lng', 'ansar al-sunna', 'al-shabaab mozambique'],
        'source_headlines': [
            '2026-02 Rwanda extends military presence in insurgent-hit Cabo Delgado (ADF Magazine)',
            '2026-05-20 Rwanda says Mozambique has secured funds for it to continue Cabo Delgado mission (Engineering News)',
            'Rwanda-Mozambique security cooperation to continue under bilateral arrangement (New Times)',
            'Rwanda responds to reports of possible halt to EU support for troops in Mozambique (New Times)',
            'Mozambique relies on Rwanda\'s troops to fight terrorism. What happens if they leave? (The Conversation)',
            'Lessons from Rwanda\'s threat to withdraw from Cabo Delgado (ISS Today)',
            'Mozambique: Rwanda hints troop withdrawal if military deployment not appreciated (Stratfor)',
        ],
        'baseline_statements_per_week': 2,
    },
    'drc_file': {
        'name': 'The DRC file', 'flag': '\U0001F1E8\U0001F1E9', 'icon': '\U0001F5C2️', 'color': '#ef4444',
        'role': 'M23 / the FRN, the FDLR, the Washington Accords -- the relationship that drives the pressure',
        'description': ('UN experts and the US government say Rwanda backs M23, now inside Joseph Kabila\'s FRN; '
                        'Kigali denies it and cites "defensive measures" against the FDLR. This is the HUB LENS on '
                        'the DRC spoke -- Kigali-side reporting of the file -- not the DRC tracker\'s own read. '
                        'High baseline on purpose: almost every eastern-Congo story names Rwanda.'),
        'vector': 'wheel_spokes', 'spoke': 'drc',
        'keywords': ['m23', 'afc/m23', 'fdlr', 'frn', 'kabila', 'washington accords', 'washington agreement',
                     'goma', 'bukavu', 'kivu', 'tshisekedi', 'defensive measures', 'mesures défensives',
                     'rwanda-backed', 'soutenus par le rwanda', 'group of experts', "groupe d'experts",
                     'rwanda and dr congo', 'rwanda-drc', 'rdc et le rwanda', 'dr congo and rwanda'],
        'source_headlines': [
            '2026-03-03 US sanctions Rwandan army and top officials for supporting M23 in DRC (Al Jazeera)',
            'Peace deal at risk as DR Congo, Burundi slam Rwanda (The Star)',
            'Why Burundi and DR Congo keep invoking Rwanda (New Times)',
            "2026-10-14 Ex-DRC President Kabila's alliance with M23 rebels: Why it matters (Al Jazeera)",
            "Kabila's war: rebels push west in Congo as Washington turns on Rwanda (SOFREP)",
        ],
        'baseline_statements_per_week': 10,
    },
    'burundi_strand': {
        'name': 'Burundi (DRC strand)', 'flag': '\U0001F1E7\U0001F1EE', 'icon': '🧵', 'color': '#f97316',
        'role': 'No relations since Jan 2024; Burundian troops fight on Kinshasa\'s side in South Kivu',
        'description': ('Burundi closed the border and cut ties in January 2024, accusing Rwanda of backing the '
                        'RED-Tabara rebels (Kigali denies it). Burundian troops defend Uvira and the Ruzizi Plain. '
                        'A strand of the DRC file, read separately because a direct Rwanda-Burundi clash would '
                        'turn the eastern war interstate.'),
        'vector': 'wheel_spokes', 'spoke': 'drc',
        'keywords': ['burundi', 'burundian', 'burundais', 'burundaise', 'ndayishimiye', 'gitega', 'bujumbura',
                     'red-tabara', 'red tabara', 'fdnb'],
        'source_headlines': [
            'Burundi says Rwanda has a plan to attack it, Rwanda calls for calm (Reuters via Yahoo)',
            'Against a backdrop of rebel attacks and border closures, Rwanda and Burundi trade accusations (AP via AOL)',
            'Burundi-Rwanda : la main tendue de Ndayishimiye, entre appel au dialogue et exigence sécuritaire (Afrik)',
            'Crisis Group warns of fully blown inter-state conflict risk between Burundi and Rwanda (Burundi Times)',
            'Analysts criticize Burundi\'s latest attempt to link Rwanda with RED-Tabara (New Times)',
            "Rwanda slams Burundi's border closure as tensions rise over rebel attacks (The Standard)",
        ],
        'baseline_statements_per_week': 2,
    },

    # ── VECTOR: external_pressure ────────────────────────────
    'us_pressure': {
        'name': 'US pressure', 'flag': '\U0001F1FA\U0001F1F8', 'icon': '⚖️', 'color': '#3b82f6',
        'role': 'Sanctions, AGOA, the UN demand to withdraw -- Washington turning on Kigali',
        'description': ('OFAC sanctioned the RDF and four officers (2 Mar 2026), the Gasabo Gold Refinery (25-26 '
                        'Jun 2026) and the Ministry of Defence and Zigama Credit (28 Oct 2026); the US excludes '
                        'Rwanda from AGOA from 1 Jan 2027. Kigali calls the measures one-sided. Read as the '
                        'pressure side of the signature axis.'),
        'vector': 'external_pressure',
        'keywords': ['sanctions on rwanda', 'sanctions against rwanda', 'sanctions rwanda', 'sanctionne le rwanda',
                     'sanctions contre le rwanda', 'rwandan defence ministry', 'rwanda defence ministry',
                     "rwanda's ministry of defence", 'rwandan ministry of defence', 'zigama', 'ofac', 'treasury sanctions', 'us treasury', 'agoa',
                     'gasabo gold refinery', 'gasabo', 'bartos', 'washington turns on rwanda',
                     'us sanctions rwanda', 'us sanctions rwandan', 'withdraw its troops immediately'],
        'source_headlines': [
            '2026-10-29 US imposes sanctions on Rwandan defence ministry over links to Congo rebels (Africanews)',
            '2026-03-03 US sanctions Rwandan army and top officials for supporting M23 in DRC (Al Jazeera)',
            '2026-11-03 Rwanda: AGOA - Washington veut éclipser le pays (allAfrica)',
            '2026-11-09 Rwanda: Turning the Threat of Agoa Withdrawal Into an Opportunity for Trade Diversification (allAfrica)',
            '2026-06-26 US sanctions Gasabo Gold Refinery over gold smuggled from rebel-held eastern DRC (reconstructed)',
        ],
        'baseline_statements_per_week': 3,
    },
    'europe_track': {
        'name': 'Europe', 'flag': '\U0001F1EA\U0001F1FA', 'icon': '\U0001F3F0', 'color': '#6366f1',
        'role': 'The EU, the UK, Belgium -- minerals MoU, Mozambique funding, sanctions, restored ties',
        'description': ('A 2024 EU raw-materials memorandum; EU funding for the Mozambique mission that wavered in '
                        '2026; Belgium-Rwanda ties cut in March 2025 and restored in September 2026; the UK asylum '
                        'deal scrapped (Rwanda lost its arbitration claim, June 2026). Migration has its own actor '
                        '(the return hub).'),
        'vector': 'external_pressure',
        'keywords': ['european union', 'eu sanctions', "l'union européenne", 'brussels', 'belgium', 'belgique',
                     'european peace facility', 'eu support', 'eu funding', 'raw materials memorandum',
                     'minerals deal with the eu', 'eu-rwanda', 'macron', 'france and rwanda', 'uk and rwanda',
                     'permanent court of arbitration'],
        'source_headlines': [
            'Rwanda responds to reports of possible halt to EU support for troops in Mozambique (New Times)',
            '2026-09 Belgium and Rwanda restore ties (Al Jazeera)',
            '2026-01-27 Rwanda sues the UK at the Permanent Court of Arbitration over the scrapped asylum plan (Wikipedia)',
        ],
        'baseline_statements_per_week': 2,
    },
    'china_axis': {
        'name': 'China', 'flag': '\U0001F1E8\U0001F1F3', 'icon': '\U0001F409', 'color': '#dc2626',
        'role': 'Buyer of Rwandan minerals; tariff-free access from May 2026; grants and roads',
        'description': ('China took about a quarter of Rwanda\'s domestic exports in Q1 2026 and gave Rwandan '
                        'ores, coffee and essential oils tariff-free access from 1 May 2026. The obvious '
                        'beneficiary if Washington\'s pressure pushes Kigali to look east.'),
        'vector': 'external_pressure',
        'keywords': ['china', 'chinese', 'chine', 'chinois', 'beijing', 'pékin', 'gao wenqi', 'focac',
                     'tariff-free'],
        'source_headlines': [
            '2026-09-22 China-Rwanda trade hit a record US$849 million in 2025, Chinese ambassador says (Rio Times, reconstructed)',
            '2026-05 Rwandan ores, coffee and essential oils gain tariff-free access to China (KT Press, reconstructed)',
        ],
        'baseline_statements_per_week': 2,
    },
    'other_partners': {
        'name': 'Other partners (Gulf, Russia, Turkey, India)', 'flag': '\U0001F310', 'icon': '\U0001F91D',
        'color': '#a855f7',
        'role': 'The hedge -- where Kigali goes if the West narrows',
        'description': ('Qatar (60% of the $1.3B Bugesera airport; mediator in Doha), the UAE (main gold '
                        'destination; contested origin), Oman, Turkey, India -- and Russia (nuclear cooperation '
                        'agreement, 19 May 2026). Read as diversification, the hedge against AGOA and sanctions.'),
        'vector': 'external_pressure',
        # PHRASES, not bare country names: CAR stories name the Russians and DRC
        # stories name Doha, and neither is Kigali hedging.
        'keywords': ['qatar airways', 'bugesera', 'qatar investment', 'qatari investment', 'rwanda-qatar',
                     'qatar and rwanda', 'rwanda and qatar', 'rwanda-uae', 'uae and rwanda', 'rwanda and the uae',
                     'emirati investment', 'abu dhabi', 'oman', 'saudi', 'turkey and rwanda', 'türkiye',
                     'rwanda-india', 'india and rwanda', 'russia and rwanda', 'rwanda and russia', 'russia-rwanda',
                     'rwanda-russia', 'rosatom', 'nuclear cooperation', 'nuclear agreement', 'nuclear deal',
                     'trade diversification', 'diversify', 'state visit'],
        'source_headlines': [
            '2026-05-19 Rwanda signs nuclear cooperation agreement with Russia (Wikipedia: 2026 in Rwanda)',
            'Rwanda, Oman: Kagame state visit 2026 (Rio Times)',
            '2025-11-20 Qatar and Rwanda: strategic integration toward sustainable future (QNA)',
            '2026-11-09 Rwanda: Turning the Threat of Agoa Withdrawal Into an Opportunity for Trade Diversification (allAfrica)',
        ],
        'baseline_statements_per_week': 2,
    },

    # ── VECTOR: economy_minerals ─────────────────────────────
    'minerals_gold': {
        'name': '3T minerals & gold', 'flag': FLAG, 'icon': '⛏️', 'color': '#eab308',
        'role': 'Tin, tantalum, tungsten and gold -- the export boom and the contested-origin question',
        'description': ('Mineral exports earned about $1.75B in 2024; 3T shipments rose 46% in 2025; Nyakabingo '
                        'tungsten has been reported at up to 20% of US primary concentrate use. UN experts, '
                        'Global Witness and Amnesty say part of Rwanda\'s coltan and gold is Congolese, including '
                        'from M23-held Rubaya; Kigali denies it.'),
        'vector': 'economy_minerals',
        'keywords': ['coltan', 'tantalum', 'tungsten', 'wolfram', 'cassiterite', ' tin ', '3t minerals',
                     'mineral exports', 'minerals exports', 'gold refinery', 'gold exports', 'smuggled gold',
                     'nyakabingo', 'itsci', 'rubaya', 'mining board', 'rmb', 'conflict minerals',
                     'or et coltan', 'minerais'],
        'source_headlines': [
            "2026-11-26 Prices for Rwanda's Tungsten Rise Over 360%, While Coffee and Tea Shrink (KT Press)",
            '2026-08 Mineral exports drive 51% surge in goods exports (KT Press)',
            "As Rwanda's mineral exports surge, trade deficit narrows (Zawya)",
            '2026-09 DRC: M23 fighters abused miners and trafficked gold and coltan to Rwanda (Amnesty)',
        ],
        'baseline_statements_per_week': 3,
    },
    'economy': {
        'name': 'The economy', 'flag': FLAG, 'icon': '\U0001F4C8', 'color': '#14b8a6',
        'role': 'Inflation, the franc, the central bank, the IMF -- what pressure costs at home',
        'description': ('Growth of 9.7% in H1 2026 alongside 15.7% inflation in August (target 5%); the central '
                        'bank raised its rate to 8.75%. An IMF Extended Credit Facility approved June 2026, first '
                        'review agreed October. Read as the home-front cost of external pressure.'),
        'vector': 'economy_minerals',
        'keywords': ['national bank of rwanda', 'bnr', 'rwandan franc', 'rwf', 'inflation', 'policy rate',
                     'central bank rate', 'imf', 'extended credit facility', 'nisr', 'gdp growth',
                     'trade deficit', 'budget', 'eurobond', 'investment agreement', 'cabinet approves'],
        'source_headlines': [
            '2026-11-26 Cabinet Approves BRALIRWA Investment Agreement for Proposed Rwamagana Plant (KT Press)',
            '2026-10-05 IMF staff and Rwanda reach agreement on first ECF review (IMF, reconstructed)',
            '2026-08 Rwanda central bank raises rate to 8.75% as inflation hits 15.7% (reconstructed)',
        ],
        'baseline_statements_per_week': 3,
    },

    # ── VECTOR: migration ────────────────────────────────────
    'return_hub': {
        'name': 'Migration deals (EU return hub)', 'flag': '\U0001F1EA\U0001F1FA', 'icon': '\U0001F6EB',
        'color': '#8b5cf6',
        'role': 'Austria, Denmark, Germany, Greece and the Netherlands want a return hub in Rwanda',
        'description': ('Announced 16 Nov 2026; transfers would begin in 2027. Precedents: the UK scheme (ruled '
                        'unlawful 2023, scrapped 2024, about £290M paid and four people relocated) and a 2025 deal '
                        'to accept up to 250 migrants deported from the US. Rights groups object; Kigali frames it '
                        'as partnership. A deal with Europe while Washington sanctions it is itself a signal.'),
        'vector': 'migration',
        'keywords': ['return hub', 'return hubs', 'deportation centre', 'deportation center', 'deport migrants',
                     'deport refugees', 'asylum seekers', 'asylum plan', 'asylum deal', 'migrants to rwanda',
                     'migration partnership', 'centre de retour', 'demandeurs d\'asile', 'rwanda plan',
                     'rwanda scheme', 'deportees'],
        'source_headlines': [
            '2026-11-16 EU: Countries Plan Rwanda Deportation Centers (HRW)',
            '2026-11-16 Rwanda and five EU Member States are jointly exploring the possibility of establishing a return hub in Rwanda (MINAFFET)',
            '2026-11-17 Why are five EU countries reviving plans to deport migrants to Rwanda? (Al Jazeera)',
            '2026-11-27 When Rwanda Offers to Help Migrants, European Humanity Comes Out of Retirement (KT Press)',
            '2026-11-24 Europe wants to deport refugees to Rwanda (WSWS)',
        ],
        'baseline_statements_per_week': 2,
    },

    # ── VECTOR: home_soil (the ONLY kinetic ladder; L5 only from here) ──
    'home_soil': {
        'name': 'Home soil & borders', 'flag': FLAG, 'icon': '\U0001F3E0', 'color': '#b91c1c',
        'role': 'Fire across the border, incursions, attacks inside Rwanda -- on a kinetic ladder',
        'description': ('Shells from the Goma fighting fell on Rubavu in January 2025; the FDLR has raided across '
                        'the border before; the Goma and Bukavu crossings are also where Ebola restrictions bite. '
                        'Rwanda is calm at home, so anything here is news, not condition.'),
        'vector': 'home_soil', 'front': 'home_soil', 'standing': False,
        'keywords': ['rubavu', 'gisenyi', 'rusizi', 'cyangugu', 'musanze', 'nyamasheke', 'cross-border fire',
                     'shells fell', 'shelling of rwanda', 'rwandan territory', 'rwandan soil', 'inside rwanda',
                     'border incursion', 'incursion into rwanda', 'attack on rwanda', 'territoire rwandais',
                     'grenade attack in kigali', 'grenade in kigali', 'border post'],
        'source_headlines': [
            '2025-01-27 Shells from Goma fighting kill civilians in Rwanda\'s Rubavu (reconstructed)',
            '2026-05-17 Rwanda closes Goma-Gisenyi border crossing amid Ebola epidemic (Wikipedia: 2026 in Rwanda)',
        ],
        'baseline_statements_per_week': 1,
    },
}

VECTOR_GROUPS = {
    'kigali_posture':    ['kagame_govt', 'rdf_posture'],
    'wheel_spokes':      ['car_mission', 'mozambique_mission', 'drc_file', 'burundi_strand'],
    'external_pressure': ['us_pressure', 'europe_track', 'china_axis', 'other_partners'],
    'economy_minerals':  ['minerals_gold', 'economy'],
    'migration':         ['return_hub'],
    'home_soil':         ['home_soil'],
}
VECTOR_LABELS = {
    'kigali_posture':    "Kigali's Posture",
    'wheel_spokes':      'The Wheel (hub lens)',
    'external_pressure': 'External Pressure & Partners',
    'economy_minerals':  'Minerals & Economy',
    'migration':         'Migration Deals',
    'home_soil':         'Home Soil (kinetic ladder)',
}

# Spoke -> the hub-lens actor that reads the same relationship from Kigali's side.
WHEEL_LENS = {'car': 'car_mission', 'mozambique': 'mozambique_mission', 'drc': 'drc_file'}
EXPECTED_SPOKES = ['car', 'drc', 'mozambique']

# OUTBOUND: the wheels RWANDA sits on. node_class strings are read by
# spoke_wheel_reader (registry first, else this self-label).
SPOKES_OUT = {
    'us':    {'actor': 'us_pressure', 'node_class': 'sanctions_target',
              'why': ('US sanctions on the Rwandan army (Mar 2026), a Kigali gold refinery (Jun 2026) and the '
                      'Ministry of Defence (Oct 2026); AGOA exclusion from Jan 2027. Kigali rejects the '
                      'allegations.')},
    'china': {'actor': 'china_axis', 'node_class': 'resource_client',
              'why': ('China buys about a quarter of Rwanda\'s domestic exports and gave Rwandan ores tariff-free '
                      'access from May 2026.')},
}


# ════════════════════════════════════════════════════════════
# RIPPLE CHAINS -- Rachel's standing rule (27 Nov 2026)
# What each actor TOUCHES at four scales, and the follow-on questions.
# Static, dated knowledge: never scored. Surfaced when the actor is LIT.
# ════════════════════════════════════════════════════════════
RIPPLES_AS_OF = '2026-11-27'
RIPPLES = {
    'us_pressure': {
        'country': ('Sanctions on the army, the defence ministry and its bank, plus the AGOA exit, hit the two '
                    'things Kigali sells -- security and a clean investment brand -- at the same time.'),
        'region': ('Washington is betting that pressure on Kigali buys movement in the eastern DRC; if it does '
                   'not, Kinshasa and Bujumbura read US leverage as spent.'),
        'continent': ('The RDF guards governments in CAR and Mozambique. If sanctions make that service harder to '
                      'pay for or to supply, other African states lose the one army they could hire quickly.'),
        'globe': ('Mozambique LNG (TotalEnergies, $20B, first gas targeted 2029) restarted under Rwandan '
                  'protection, and Europe is still replacing Russian gas. A sanctions policy aimed at the DRC '
                  'reaches the European gas balance through Cabo Delgado.'),
        'questions': [
            'Do US sanctions change Rwanda\'s deployments in Mozambique and CAR -- the spokes Washington is not aiming at?',
            'Who pays for the Mozambique mission if Western donors step back, and what do they get for it?',
            'Does the AGOA exit push Rwandan exports (and its minerals) toward China and the Gulf?',
            'If Kigali gives ground in the DRC, is it because of sanctions -- or because the FRN no longer needs it?',
        ],
    },
    'mozambique_mission': {
        'country': ('The Mozambique mission is Rwanda\'s proof of concept: the reason its army is invited, '
                    'funded and praised even while it is sanctioned.'),
        'region': ('Cabo Delgado borders Tanzania; the insurgency there has crossed before. A Rwandan drawdown '
                   'shifts the burden to Mozambique\'s army and SADC states.'),
        'continent': ('Islamic State\'s Mozambique province is one of its most active in Africa. Who holds the '
                      'perimeter decides whether that remains contained.'),
        'globe': ('Mozambique LNG restarted in January 2026 with first LNG targeted for 2029; Coral Sul already '
                  'exports offshore and ExxonMobil\'s Rovuma LNG waits behind Total. A security gap at Afungi '
                  'reprices a future gas supply Europe and Asia are counting on.'),
        'questions': [
            'If Rwanda reduced its contingent, would TotalEnergies keep building -- and would insurers keep covering?',
            'What does Kigali gain from Maputo and Total that sanctions cannot take away?',
            'Does ExxonMobil\'s Rovuma decision move with Rwandan force posture?',
        ],
    },
    'car_mission': {
        'country': 'A second showcase deployment, and a source of political capital with the UN.',
        'region': ('Rwandan and Russian forces guard the same president in Bangui; Rwanda\'s position there '
                   'shifts as Russia\'s Africa Corps reorganises.'),
        'continent': 'Part of the same security-export model as Mozambique; a test of whether it survives sanctions.',
        'globe': 'A rare case of a Western-sanctioned army and Russia\'s forces guarding the same government.',
        'questions': [
            'Does MINUSCA\'s budget squeeze move Rwandan troops from the UN flag to the bilateral deal?',
            'Is Rwanda gaining ground in Bangui as Russia\'s role changes, or competing with it?',
        ],
    },
    'drc_file': {
        'country': ('The DRC file is the source of every sanction Rwanda faces; how Kigali plays it decides its '
                    'relations with the West.'),
        'region': ('UN experts and the US say Rwanda backs M23 (Kigali denies it); with Kabila\'s FRN now leading '
                   'the movement, Kigali\'s posture shapes whether the war stays in the east.'),
        'continent': ('The Washington Accords are a US-brokered African peace tied to minerals; their failure '
                      'or success sets a model for other deals.'),
        'globe': ('Coltan and gold from the war zone reach global electronics and refining chains; '
                  'due-diligence regimes in the US and EU are tested here.'),
        'questions': [
            'Is there an agreed standard for FDLR neutralisation and Rwanda\'s "defensive measures"?',
            'Does pressure on Kigali change what happens on the ground, or only what is said in Washington?',
        ],
    },
    'burundi_strand': {
        'country': 'The southern border is shut; trade and families on both sides pay for it.',
        'region': ('Burundian troops fight in South Kivu on Kinshasa\'s side; a direct clash with Rwanda would '
                   'turn a civil war into an interstate one.'),
        'continent': 'Burundi held the AU chair in 2026; its quarrel with Rwanda colours the AU\'s mediation.',
        'globe': 'Limited direct reach; the risk is regional escalation that drags in larger patrons.',
        'questions': [
            'What happens to Uvira if Burundi has to bring troops home?',
            'Does either side move troops to the shared border -- the step before a clash?',
        ],
    },
    'china_axis': {
        'country': ('Tariff-free access and grants give Kigali an economic cushion against the AGOA exit -- and '
                    'a partner that does not attach conditions about the DRC.'),
        'region': ('China is the biggest buyer of the region\'s minerals, Congolese and Rwandan alike; a Kigali '
                   'tilt changes who refines eastern Congo\'s tantalum.'),
        'continent': ('A test of whether US pressure on an African partner simply hands Beijing the relationship.'),
        'globe': ('Tantalum goes into capacitors for phones, cars, servers and defence electronics; tungsten into '
                  'tooling and munitions. More Rwandan 3T flowing to China tightens Western supply chains that '
                  'Washington is trying to diversify.'),
        'questions': [
            'If China moves on Rwandan tantalum and tungsten, which other minerals does it already restrict -- and is tungsten next?',
            'Does the US keep buying Nyakabingo tungsten while sanctioning the state that exports it?',
            'Which Western smelters depend on Rwandan 3T, and how quickly could they switch?',
        ],
    },
    'other_partners': {
        'country': 'Gulf money (Qatar\'s airport stake) and a Russian nuclear deal are the hedge against the West.',
        'region': ('Qatar mediates the DRC track in Doha while investing in Rwanda; the UAE is where the region\'s '
                   'gold is reported to end up.'),
        'continent': 'Rwanda is a template for African states diversifying away from Western conditionality.',
        'globe': 'A Western-sanctioned partner drifting toward the Gulf and Russia shifts who sets the terms in Central Africa.',
        'questions': [
            'Does Qatar\'s mediator role conflict with its investments in Kigali?',
            'Does the Russia nuclear agreement move from paper to project -- and what does Washington do about it?',
        ],
    },
    'europe_track': {
        'country': 'Europe is a buyer, a donor and now a migration partner -- the relationship sanctions have not touched.',
        'region': 'EU funding for the Mozambique mission has wavered; its return decides who carries the cost.',
        'continent': 'The EU\'s minerals memorandum with Rwanda is part of its wider Africa critical-minerals push.',
        'globe': ('Europe and the US diverging on Rwanda (Washington sanctions; Brussels capitals court it) is a '
                  'transatlantic split worth watching.'),
        'questions': [
            'Does the EU suspend its minerals memorandum, or deepen it?',
            'Does European funding for Cabo Delgado return, now that LNG has restarted?',
        ],
    },
    'return_hub': {
        'country': ('Migration deals bring money and political cover; Kigali presents them as partnership. Rights '
                    'groups question the conditions.'),
        'region': 'Rwanda already hosts about 140,000 refugees from the DRC and Burundi.',
        'continent': 'Sets a template for European "return hubs" elsewhere in Africa.',
        'globe': ('Five EU states seeking a deal with Rwanda while the US sanctions it shows the West using Kigali '
                  'for different things at once.'),
        'questions': [
            'Does the return-hub deal soften European positions on the DRC file?',
            'Does it survive court challenges in the five member states (the UK plan did not)?',
        ],
    },
    'minerals_gold': {
        'country': ('Minerals are now Rwanda\'s top export earner; a tungsten price surge helps, a due-diligence '
                    'crackdown hurts.'),
        'region': ('Where the minerals come from is the heart of the DRC dispute: UN experts, Global Witness and '
                   'Amnesty say part is Congolese (Kigali denies it).'),
        'continent': 'The same route economy moves gold out of Sudan, CAR and the Sahel to Gulf refiners.',
        'globe': ('Tantalum (from coltan) is in capacitors for phones, computers, cars and AI hardware; tungsten '
                  'is in cutting tools and munitions. Traceability failures here reach brand supply chains.'),
        'questions': [
            'Does rising tungsten and tantalum demand raise the value of controlling Rubaya?',
            'Which refiners and brands are exposed if traceability schemes fail?',
        ],
    },
    'economy': {
        'country': 'Inflation near 16% and a rate hike: the cost of pressure lands on households first.',
        'region': 'Rwanda trades through Uganda, Kenya and Tanzania; border closures with Burundi and the DRC narrow its routes.',
        'continent': 'One of Africa\'s fastest-growing economies under sanctions is a test of the model.',
        'globe': 'IMF support and Eurobond pricing are where international confidence shows first.',
        'questions': ['Does the AGOA exit show up in export data in Q1 2027?'],
    },
    'kagame_govt': {
        'country': 'Kagame has led since 2000; succession is not on the public agenda.',
        'region': 'Kigali\'s posture toward Kinshasa and Bujumbura is the region\'s most watched variable.',
        'continent': 'Kagame is an influential voice on African self-reliance and on AU reform.',
        'globe': 'A Western-favoured development model now under Western sanctions.',
        'questions': ['Does Kigali\'s language shift from denial to bargaining with Washington?'],
    },
    'rdf_posture': {
        'country': 'The army is the regime\'s core institution and its main export.',
        'region': 'RDF positions along the DRC border are what the Washington Accords measure.',
        'continent': 'One of the few African armies other governments invite to fight for them.',
        'globe': 'Peacekeeping contributions give Rwanda standing at the UN that sanctions erode.',
        'questions': ['Do sanctions limit the RDF\'s ability to buy equipment for its foreign missions?'],
    },
    'home_soil': {
        'country': 'Fire or raids into Rwanda are the trigger Kigali cites for "defensive measures".',
        'region': 'An incident at Rubavu or Rusizi is the step from a war next door to a war across the border.',
        'continent': 'Interstate escalation in the Great Lakes has drawn in up to nine armies before (1998-2003).',
        'globe': 'Limited direct reach until it escalates.',
        'questions': ['Does Kigali answer an incident with words, a border closure, or troops?'],
    },
}


# ════════════════════════════════════════════════════════════
# EXPORT VS PRESSURE -- the signature axis
# The security-export deployments (CAR, Mozambique) read against the
# Western pressure (US, Europe). Patterns trace to the 2026 headlines
# quoted on mozambique_mission and car_mission.
# ════════════════════════════════════════════════════════════
EXPORT_PATTERNS = {
    'expanding':   ['deploys additional', 'additional troops', 'more troops', 'fresh contingent', 'new contingent',
                    'extends military presence', 'expands its mission', 'reinforce', 'reinforcement', 'renfort',
                    'new deployment', 'deploy to'],
    'holding':     ['to continue', 'continue under', 'continues its mission', 'secured funds', 'bilateral arrangement',
                    'rotation', 'ahead of deployment', 'ahead of mozambique deployment', 'graduate', 'trained by',
                    'training', 'solidarity, not money', 'cooperation', 'official visit', 'visits troops'],
    'wavering':    ['threat to withdraw', 'threatens to withdraw', 'may withdraw', 'could withdraw',
                    'hints troop withdrawal', 'possible halt', 'halt to eu support', 'funding gap',
                    'funding shortfall', 'what happens if they leave', 'reconsider', 'review its deployment',
                    'menace de retirer', 'retrait envisagé', 'if they leave', 'not appreciated'],
    'withdrawing': ['withdraws troops', 'withdraws its troops', 'pulls out', 'pull out its troops', 'troops leave',
                    'begins withdrawal', 'ends its mission', 'ends mission', 'troops withdrawn'],
}
_DEPLOYMENT_ACTORS = ('mozambique_mission', 'car_mission')
_PRESSURE_ACTORS = ('us_pressure', 'europe_track')


# ════════════════════════════════════════════════════════════
# COUNTRY GATE
# ════════════════════════════════════════════════════════════
STRONG_TOKENS = ['rwanda', 'rwandan', 'rwandans', 'rwandais', 'rwandaise', 'rwandaises', 'kigali', 'kagame',
                 'nduhungirehe', 'makolo', 'rwandair', 'rubavu', 'gisenyi', 'rusizi', 'nyakabingo', 'minema',
                 'zigama', 'gasabo', 'nyakarundi', 'bralirwa', 'musanze', 'huye', 'nyagatare', 'rwamagana',
                 'bugesera', 'nyamasheke', 'cyangugu']
# Stripped before the gate: they contain a strong token but are not about Rwanda.
GATE_STRIP = ['kigali amendment', 'kigali protocol']
# "RDF" alone is also the Resource Description Framework (and other armies'
# Rapid Deployment Forces). Uppercase RDF passes only beside military words.
_RDF = re.compile(r'(?<![A-Za-z])RDF(?![A-Za-z])')
RDF_CONTEXT = ['troops', 'army', 'soldiers', 'training', 'contingent', 'military', 'deployment', 'police',
               'gen ', 'general', 'officers', 'peacekeep']


# ════════════════════════════════════════════════════════════
# KINETIC LADDER -- home soil only; L5 only from here
# ════════════════════════════════════════════════════════════
_NUM = (r'(?:1[0-9]|[2-9][0-9]|[1-9][0-9]{2,}|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|'
        r'a dozen|dozens of|hundreds of|dix|douze|quinze|vingt|trente)')
LADDER = [
    (5, [r'attack on kigali', r'kigali (?:attacked|under attack|shelled)', r'attaque (?:de|contre) kigali',
         r'rwanda invades', r'invasion of (?:burundi|rwanda)', r'rwandan troops (?:cross|crossed) into burundi',
         r'rwanda declares war', r'(?:rubavu|gisenyi|rusizi) (?:captured|seized|overrun|falls)']),
    (4, [r'massacre', r'(?:kill(?:s|ed|ing)?|tués?) (?:at least )?' + _NUM,
         r'(?:at least |au moins )?' + _NUM + r' (?:\w+ )?(?:killed|dead|tués|morts)', r'mass casualty']),
    (3, [r'shell(?:s|ed|ing)', r'bomb(?:s|ed|ing)', r'grenade', r'cross-border fire', r'incursion', r'raid',
         r'attack(?:ed)?', r'attaque', r'killed', r'tués?', r'drone strike', r'gunfire', r'clash']),
    (2, [r'threat', r'threaten', r'menace', r'warns', r'tension', r'troop build-?up', r'mass(?:es|ing) troops',
         r'closes? (?:the )?border', r'ferme la frontière']),
]
_LADDER_RX = [(lv, [re.compile(p) for p in pats]) for lv, pats in LADDER]


# ════════════════════════════════════════════════════════════
# TRIPWIRES -- red lines. BREACHED / APPROACHING; they do NOT open L5.
# ════════════════════════════════════════════════════════════
TRIPWIRES = {
    'deployment_withdrawal': {
        # Specific on purpose: "withdraw from Cabo Delgado" also appears in THREAT stories
        # ("Rwanda's threat to withdraw from Cabo Delgado"), and "withdrawal of Rwandan troops"
        # is what Washington and Kinshasa demand in the DRC -- neither is a deployment ending.
        'patterns': ['withdraws troops from mozambique', 'withdraws its troops from mozambique',
                     'pulls out of mozambique', 'pulls troops out of mozambique', 'rwandan troops leave cabo delgado',
                     'rwanda ends mission in mozambique', 'ends its mission in mozambique',
                     'withdraws troops from central african', 'pulls out of central african',
                     'quitte le mozambique', 'retrait du mozambique'],
        'severity': 'high',
        'note': ('A Rwandan withdrawal from Mozambique or CAR is the security-export model breaking -- and, in '
                 'Mozambique, a direct risk to the LNG restart.'),
    },
    'withdrawal_threat': {
        'patterns': ['threatens to withdraw', 'threat to withdraw', 'may withdraw its troops',
                     'hints troop withdrawal', 'menace de retirer'],
        'severity': 'elevated',
        'note': 'Kigali threatened to leave Cabo Delgado over funding in early 2026; Mozambique found the money in May.',
    },
    'new_us_sanctions': {
        'patterns': ['new sanctions on rwanda', 'sanctions rwandan', 'treasury sanctions', 'ofac designates',
                     'sanctionne le rwanda', 'imposes sanctions on rwanda'],
        'severity': 'elevated',
        'note': 'Army (Mar 2026), Gasabo gold refinery (Jun 2026), Ministry of Defence and Zigama (Oct 2026).',
    },
    'agoa_exit': {
        'patterns': ['agoa'],
        'severity': 'elevated',
        'note': 'Rwanda is excluded from AGOA from 1 Jan 2027.',
    },
    'eu_sanctions': {
        'patterns': ['eu sanctions on rwanda', 'eu sanctions rwandan', "sanctions de l'ue contre le rwanda",
                     'suspends minerals memorandum', 'suspend the minerals deal'],
        'severity': 'high',
        'note': 'Europe has so far courted Kigali while Washington sanctions it; EU sanctions would close that gap.',
    },
    'interstate_clash_burundi': {
        'patterns': ['rwanda attacks burundi', 'burundi attacks rwanda', 'clash between rwandan and burundian',
                     'burundian and rwandan troops clash', 'troupes rwandaises et burundaises',
                     'rwanda-burundi border clash'],
        'severity': 'high',
        'note': 'Direct fighting between national armies would turn the eastern war interstate.',
    },
    'fire_on_rwandan_soil': {
        'patterns': ['shells fell in rwanda', 'shells landed in rwanda', 'shelling of rubavu', 'bombs fell in rubavu',
                     'cross-border fire', 'incursion into rwanda', 'attack on rwandan soil', 'fdlr attack in rwanda'],
        'severity': 'high',
        'note': 'Rubavu was hit in January 2025; Kigali cites such fire as grounds for its "defensive measures".',
    },
    'un_experts_report': {
        'patterns': ['group of experts report', "rapport du groupe d'experts", 'un experts report', 'un experts say rwanda'],
        'severity': 'elevated',
        'note': 'The UN Group of Experts on the DRC reports twice a year; each report renews the case for sanctions.',
    },
    'return_hub_signed': {
        'patterns': ['return hub agreement signed', 'signs return hub', 'first transfers to rwanda',
                     'first deportation flight to rwanda', 'first migrants arrive in rwanda'],
        'severity': 'elevated',
        'note': 'Five EU states announced the plan on 16 Nov 2026; transfers would begin in 2027.',
    },
    'mineral_traceability_shock': {
        'patterns': ['suspends rwandan minerals', 'bans rwandan coltan', 'rwandan gold refinery sanctioned',
                     'apple suspends', 'itsci suspends', 'boycott of rwandan minerals'],
        'severity': 'elevated',
        'note': 'A buyer, refiner or scheme cutting off Rwandan 3T or gold hits the main export earner.',
    },
}


# ════════════════════════════════════════════════════════════
# FEEDS -- EN + FR; Kigali-aligned outlets tagged
# ════════════════════════════════════════════════════════════
RSS_FEEDS = {
    'gn_en': {'url': 'https://news.google.com/rss/search?q=Rwanda+when:7d&hl=en-US&gl=US&ceid=US:en',
              'name': 'GoogleNews-EN', 'weight': 0.85, 'language': 'en', 'aggregator': True},
    'gn_fr': {'url': 'https://news.google.com/rss/search?q=Rwanda+when:7d&hl=fr&gl=FR&ceid=FR:fr',
              'name': 'GoogleNews-FR', 'weight': 0.85, 'language': 'fr', 'aggregator': True},
    'gn_wheel': {'url': ('https://news.google.com/rss/search?q=Rwanda+(Mozambique+OR+%22Cabo+Delgado%22+OR+'
                         '%22Central+African%22+OR+Burundi)+when:7d&hl=en-US&gl=US&ceid=US:en'),
                 'name': 'GoogleNews-Wheel', 'weight': 0.85, 'language': 'en', 'aggregator': True},
    'gn_pressure': {'url': ('https://news.google.com/rss/search?q=Rwanda+(sanctions+OR+AGOA+OR+%22return+hub%22+'
                            'OR+Qatar+OR+China)+when:7d&hl=en-US&gl=US&ceid=US:en'),
                    'name': 'GoogleNews-Pressure', 'weight': 0.85, 'language': 'en', 'aggregator': True},
    'ktpress':  {'url': 'https://www.ktpress.rw/feed/', 'name': 'KT Press', 'weight': 0.8, 'language': 'en',
                 'voice': 'kigali_aligned'},
    'taarifa':  {'url': 'https://taarifa.rw/feed/', 'name': 'Taarifa', 'weight': 0.8, 'language': 'en',
                 'voice': 'kigali_aligned'},
    'rfi_af':   {'url': 'https://www.rfi.fr/fr/afrique/rss', 'name': 'RFI Afrique', 'weight': 0.95, 'language': 'fr'},
    'reliefweb': {'url': 'https://reliefweb.int/country/rwa/rss.xml', 'name': 'ReliefWeb RWA',
                  'weight': 1.0, 'language': 'en'},
}
GDELT_QUERIES_EN = [
    '"Rwanda" AND ("sanctions" OR "AGOA" OR "Treasury")',
    '"Rwanda" AND ("Mozambique" OR "Cabo Delgado" OR "Central African Republic")',
    '"Rwanda" AND ("Burundi" OR "FDLR" OR "M23")',
    '"Rwanda" AND ("coltan" OR "tungsten" OR "gold refinery" OR "return hub")',
]
GDELT_QUERIES_FR = ['"Rwanda" ET ("sanctions" OU "Burundi" OU "Mozambique")']
NEWSAPI_QUERIES = ['Rwanda sanctions', 'Rwanda Mozambique troops', 'Rwanda Burundi', 'Rwanda return hub',
                   'Kagame']
BRAVE_QUERIES = ['Rwanda sanctions AGOA 2026', 'Rwanda troops Mozambique Cabo Delgado', 'Rwanda Burundi border']


# ════════════════════════════════════════════════════════════
# VALIDATION -- MEASURED by the harness on the 27 Nov 2026 corpus
# ════════════════════════════════════════════════════════════
ACTOR_VALIDATION = {
    'kagame_govt':        {'status': 'validated', 'real_headlines_matched': 8},
    'rdf_posture':        {'status': 'validated', 'real_headlines_matched': 6},
    'car_mission':        {'status': 'validated', 'real_headlines_matched': 3},
    'mozambique_mission': {'status': 'validated', 'real_headlines_matched': 10},
    'drc_file':           {'status': 'validated', 'real_headlines_matched': 6},
    'burundi_strand':     {'status': 'validated', 'real_headlines_matched': 9},
    'us_pressure':        {'status': 'validated', 'real_headlines_matched': 6},
    'europe_track':       {'status': 'validated', 'real_headlines_matched': 3},
    'china_axis':         {'status': 'provisional', 'real_headlines_matched': 2,
                           'note': ('Both matching headlines are reconstructed from article text, not verbatim '
                                    'titles. Scored, but watch for DRC stories that name Chinese mines.')},
    'other_partners':     {'status': 'validated', 'real_headlines_matched': 4},
    'minerals_gold':      {'status': 'validated', 'real_headlines_matched': 5},
    'economy':            {'status': 'validated', 'real_headlines_matched': 4},
    'return_hub':         {'status': 'validated', 'real_headlines_matched': 5},
    'home_soil':          {'status': 'provisional', 'real_headlines_matched': 2,
                           'note': ('Rwanda is calm at home: one reconstructed shelling headline (Jan 2025) and one '
                                    'Ebola border closure (correctly L1). The two-outlet rule carries the weight.')},
}
VALIDATION_AS_OF = '2026-11-27'
VALIDATION_CORPUS_NOTE = (
    '53 2025-26 Rwanda headlines (EN and FR; 8 reconstructed from article text) + 7 negative controls (the '
    'Kigali Amendment, RDF graph databases, Uganda-only Ebola, Burundi-only inflation, a DRC-only Ituri story, '
    'Mozambique LNG without Rwanda, a CAR-only story). Country gate: 53/53 passed, 0/7 negative-control leaks. '
    'Export vs pressure on the year\'s Mozambique/CAR corpus with US pressure lit: wavering (4 outlets on the '
    'early-2026 withdrawal threat) -- correct for the year, and a reminder that the axis reads THIS WEEK only.')


# ════════════════════════════════════════════════════════════
# REDIS
# ════════════════════════════════════════════════════════════
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        r = requests.get('%s/get/%s' % (UPSTASH_REDIS_URL, key),
                         headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN}, timeout=8)
        if r.status_code != 200:
            return None
        raw = r.json().get('result')
        return json.loads(raw) if raw else None
    except Exception as e:
        print('[Rwanda Rhetoric] redis get %s: %s' % (key, str(e)[:100]))
        return None


def _redis_set(key, value, ttl_hours=CACHE_TTL_HOURS):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        r = requests.post(UPSTASH_REDIS_URL,
                          headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
                          json=['SET', key, json.dumps(value, default=str), 'EX', str(int(ttl_hours * 3600))],
                          timeout=8)
        return r.status_code == 200
    except Exception as e:
        print('[Rwanda Rhetoric] redis set %s: %s' % (key, str(e)[:100]))
        return False


def _redis_lpush_trim(key, value, max_len=336):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        r = requests.post(UPSTASH_REDIS_URL,
                          headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
                          json=['LPUSH', key, json.dumps(value, default=str)], timeout=8)
        requests.post(UPSTASH_REDIS_URL,
                      headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
                      json=['LTRIM', key, '0', str(max_len - 1)], timeout=8)
        return r.status_code == 200
    except Exception as e:
        print('[Rwanda Rhetoric] redis lpush %s: %s' % (key, str(e)[:100]))
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
    """Substring match, with a WORD-BOUNDARY rule for short keywords
    (so 'rdf' does not match inside another word and 'imf' stays the IMF)."""
    if (' ' in kw) or ('-' in kw) or len(kw) > 4:
        return kw in body
    pat = _WB_CACHE.get(kw)
    if pat is None:
        pat = re.compile(r'(?<![a-z0-9à-ÿ])' + re.escape(kw) + r'(?![a-z0-9à-ÿ])')
        _WB_CACHE[kw] = pat
    return pat.search(body) is not None


def _norm(text):
    return ' %s ' % (text or '').lower()


def _body(article):
    return _norm('%s %s' % (article.get('title', ''), article.get('description', '')))


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
            if cfg.get('aggregator') and ' - ' in title:
                title, source = title.rsplit(' - ', 1)
                source = source.strip() or cfg['name']
                if source.startswith('http'):
                    source = re.sub(r'^https?://(www\.)?', '', source).strip('/') or cfg['name']
            out.append({
                'title': title,
                'description': re.sub(r'<[^>]+>', ' ', e.get('summary', '') or e.get('description', ''))[:600],
                'url': e.get('link', ''), 'published': e.get('published', ''),
                'source': source, 'feed_id': feed_id, 'feed_type': 'rss',
                'language': cfg.get('language', 'en'), 'feed_weight': cfg.get('weight', 1.0),
                'voice': cfg.get('voice', ''),
            })
    except Exception as e:
        print('[Rwanda Rhetoric] RSS %s: %s' % (feed_id, str(e)[:100]))
    return out


def fetch_all_rss():
    out = []
    for fid, cfg in RSS_FEEDS.items():
        got = fetch_rss(fid, cfg)
        if got:
            print('[Rwanda Rhetoric] RSS %s: %d' % (fid, len(got)))
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
        return [{'title': i.get('title', ''), 'description': '', 'url': i.get('url', ''),
                 'published': i.get('seendate', ''), 'source': i.get('domain', 'GDELT'),
                 'feed_id': 'gdelt', 'feed_type': 'gdelt',
                 'language': 'fr' if lang == 'fra' else 'en', 'feed_weight': 0.85}
                for i in r.json().get('articles', [])]
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
    print('[Rwanda Rhetoric] GDELT: %d' % len(out))
    return out


def fetch_newsapi(days=7):
    if not NEWSAPI_KEY:
        return []
    frm = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    out = []
    for q in NEWSAPI_QUERIES:
        try:
            r = requests.get(NEWSAPI_BASE_URL, params={'q': q, 'from': frm, 'sortBy': 'publishedAt',
                                                       'pageSize': 30, 'apiKey': NEWSAPI_KEY}, timeout=10)
            if r.status_code != 200:
                continue
            for i in r.json().get('articles', []):
                out.append({'title': i.get('title', ''), 'description': i.get('description', ''),
                            'url': i.get('url', ''), 'published': i.get('publishedAt', ''),
                            'source': (i.get('source') or {}).get('name', 'NewsAPI'),
                            'feed_id': 'newsapi', 'feed_type': 'newsapi', 'language': 'en', 'feed_weight': 0.9})
        except Exception:
            pass
        time.sleep(0.5)
    if out:
        print('[Rwanda Rhetoric] NewsAPI: %d' % len(out))
    return out


def fetch_brave(gdelt_n=0, news_n=0):
    """Tertiary -- only when the primaries came back thin."""
    if not BRAVE_API_KEY or (gdelt_n + news_n) >= 10:
        return []
    out = []
    for q in BRAVE_QUERIES:
        try:
            r = requests.get(BRAVE_BASE_URL, params={'q': q, 'count': 20, 'freshness': 'pw'},
                             headers={'Accept': 'application/json', 'X-Subscription-Token': BRAVE_API_KEY},
                             timeout=10)
            if r.status_code != 200:
                continue
            for i in r.json().get('results', []):
                out.append({'title': i.get('title', ''), 'description': i.get('description', ''),
                            'url': i.get('url', ''), 'published': i.get('page_age') or i.get('age', ''),
                            'source': i.get('source') or 'Brave', 'feed_id': 'brave', 'feed_type': 'brave',
                            'language': 'en', 'feed_weight': 0.75})
        except Exception:
            pass
        time.sleep(0.5)
    if out:
        print('[Rwanda Rhetoric] Brave: %d' % len(out))
    return out


# ════════════════════════════════════════════════════════════
# GATE + CLASSIFY
# ════════════════════════════════════════════════════════════
def passes_country_gate(article):
    """True when the article names Rwanda or a Rwandan place, person or
    institution. 'Kigali Amendment' (the Montreal Protocol) is stripped
    first: it contains 'kigali' and is about refrigerants."""
    body = _body(article)
    for s in GATE_STRIP:
        body = body.replace(s, ' ')
    if any(_kw_in(t, body) for t in STRONG_TOKENS):
        return True, 'country'
    if _RDF.search('%s %s' % (article.get('title', ''), article.get('description', ''))) \
            and any(t in body for t in RDF_CONTEXT):
        return True, 'rdf'
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
    body = _norm(text)
    for lv, rxs in _LADDER_RX:
        if any(rx.search(body) for rx in rxs):
            return lv
    return 1


def front_ladder(articles):
    """Home-soil level from the KINETIC LADDER with the two-outlet rule."""
    if not articles:
        return {'level': 0, 'raw_max': 0, 'outlets_at_level': 0, 'held_by_two_outlet_rule': False, 'worst': None}
    rated = []
    for a in articles:
        r = ladder_rung('%s %s' % (a.get('title', ''), a.get('description', '')))
        rated.append((r, (a.get('source') or a.get('feed_id') or '?').lower(), a))
    raw_max = max(r for r, _, _ in rated)
    for lv in (5, 4, 3):
        if len({s for r, s, _ in rated if r >= lv}) >= 2:
            level = lv
            break
    else:
        level = min(raw_max, 2)
    worst = max(rated, key=lambda x: x[0])[2]
    return {'level': level, 'raw_max': raw_max,
            'outlets_at_level': len({s for r, s, _ in rated if r >= level}),
            'held_by_two_outlet_rule': raw_max >= 3 and level < raw_max,
            'worst': {'title': worst.get('title', ''), 'url': worst.get('url', ''), 'source': worst.get('source', '')}}


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
PLATFORM_LABELS = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning', 3: 'Confrontation', 4: 'Coercion',
                   5: 'Active Conflict'}


def _rank(lv):
    try:
        return _LEVEL_ORDER.index(lv)
    except ValueError:
        return 0


def _score_actor(articles):
    if not articles:
        return {'score': 0, 'article_count': 0, 'language_breakdown': {}, 'sources': [], 'top_articles': [],
                'tripwires': [], 'outlets': 0, 'kigali_aligned_share': 0}
    per_outlet, score = {}, 0.0
    langs, srcs, tw_seen, aligned = {}, {}, set(), 0
    for a in articles:
        w = a.get('feed_weight', 1.0)
        hits = a.get('_hits', 1)
        _o = a.get('source', '?')
        per_outlet[_o] = per_outlet.get(_o, 0) + 1
        if per_outlet[_o] <= OUTLET_CAP:
            score += w * min(1.0 + (hits - 1) * 0.15, 2.0)
        langs[a.get('language', 'en')] = langs.get(a.get('language', 'en'), 0) + 1
        srcs[_o] = srcs.get(_o, 0) + 1
        if a.get('voice') == 'kigali_aligned':
            aligned += 1
        for tw_id, sev in _check_tripwires('%s %s' % (a.get('title', ''), a.get('description', ''))):
            tw_seen.add((tw_id, sev))
    ranked = sorted(articles, key=lambda a: (a.get('voice') != 'kigali_aligned', a.get('feed_weight', 1.0)),
                    reverse=True)
    return {
        'score': round(score, 2), 'article_count': len(articles), 'outlets': len(srcs),
        'language_breakdown': langs,
        'sources': [{'source': s, 'count': c} for s, c in sorted(srcs.items(), key=lambda x: -x[1])[:6]],
        'top_articles': [{'title': a.get('title', ''), 'url': a.get('url', ''), 'source': a.get('source', ''),
                          'language': a.get('language', 'en'), 'published': a.get('published', ''),
                          'voice': a.get('voice', '')} for a in ranked[:8]],
        'tripwires': [{'id': i, 'severity': s} for i, s in tw_seen],
        'kigali_aligned_share': round(aligned / len(articles), 2),
    }


# ════════════════════════════════════════════════════════════
# SIBLING READS -- context, never re-fetched, never re-scored
# ════════════════════════════════════════════════════════════
def _read_humanitarian_context():
    h = _redis_get(HUMANITARIAN_KEY) or {}
    if not h:
        return {'available': False, 'note': 'Humanitarian sensor key absent this cycle -- unread, not calm.'}
    out = {'available': True, 'data_as_of': h.get('data_as_of')}
    for s in (h.get('headline_stats') or []):
        if (s.get('label') or '').lower().startswith('refugees and others'):
            out['refugees_hosted'] = s.get('value')
    return out


def _read_commodity_context():
    """CONTEXT ONLY (not scored)."""
    try:
        from commodity_proxy_africa import get_africa_commodity_data
    except ImportError:
        return {'available': False, 'reason': 'commodity proxy not importable'}
    try:
        d = get_africa_commodity_data('rwanda') or {}
        out = {'available': False, 'scored': False}
        for t in (d.get('commodity_summaries') or []):
            if t.get('commodity') in ('tantalum', 'gold', 'coffee', 'oil'):
                sp = t.get('sparkline') or {}
                out[t['commodity']] = {'price': sp.get('price'), 'change_pct_1d': sp.get('change_pct_1d'),
                                       'change_pct_30d': sp.get('change_pct_30d')}
                out['available'] = True
        return out
    except Exception as e:
        return {'available': False, 'reason': str(e)[:120]}


def _read_spoke_fingerprints():
    """The spokes' own country fingerprints (CAR, DRC) -- context for the page."""
    out = {}
    for c in ('car', 'drc', 'mozambique'):
        v = _redis_get('crosstheater:%s:fingerprint' % c)
        if v:
            out[c] = {'theatre_level': v.get('theatre_level'), 'kinetic_level': v.get('kinetic_level'),
                      'deal_state': v.get('deal_state'), 'ts': v.get('ts')}
    return out


def read_rwanda_wheel(actor_summaries):
    """INBOUND: the Rwanda wheel as the SPOKE trackers report it, with the
    hub lens (this tracker's own actor for the same relationship) attached
    beside each spoke. The hub lens is NEVER counted toward convergence."""
    try:
        from spoke_wheel_reader import read_wheel
        w = read_wheel('rwanda', extra_spokes=EXPECTED_SPOKES)
    except Exception as e:
        return {'readable': False, 'note': 'Wheel read unavailable: %s' % str(e)[:120], 'spokes': [],
                'lit_count': 0, 'spoke_count': len(EXPECTED_SPOKES), 'converged': False}
    for s in w.get('spokes', []):
        aid = WHEEL_LENS.get(s.get('country'))
        if aid:
            a = actor_summaries.get(aid) or {}
            s['hub_lens'] = {'actor': aid, 'name': ACTORS[aid]['name'], 'level': a.get('level'),
                             'platform_level': LEVEL_TO_PLATFORM.get(a.get('level', 'low'), 0),
                             'article_count': a.get('article_count', 0)}
            if s.get('country') == 'drc':
                b = actor_summaries.get('burundi_strand') or {}
                s['strands'] = [{'actor': 'burundi_strand', 'name': ACTORS['burundi_strand']['name'],
                                 'level': b.get('level'), 'article_count': b.get('article_count', 0)}]
    w['spoke_count'] = len(w.get('spokes', [])) or len(EXPECTED_SPOKES)
    w['lens_note'] = ('Spoke levels come from each spoke\'s own tracker. The hub lens beside each is Kigali-side '
                      'reporting of the same relationship, shown for comparison and never counted toward '
                      'convergence.')
    return w


# ════════════════════════════════════════════════════════════
# EXPORT VS PRESSURE
# ════════════════════════════════════════════════════════════
def _export_axis(deploy_articles, actor_summaries):
    """Reads the deployment reporting (CAR, Mozambique) against Western
    pressure. Each pattern family counts DISTINCT OUTLETS. The 2026 norm is
    'pressured_holding': sanctioned, yet still deployed. Nothing matched ->
    'unread' (never 'holding')."""
    hits = {k: {} for k in EXPORT_PATTERNS}
    for a in deploy_articles:
        body = _norm('%s %s' % (a.get('title', ''), a.get('description', '')))
        for state, pats in EXPORT_PATTERNS.items():
            if any(p in body for p in pats):
                hits[state].setdefault((a.get('source') or '?').lower(), a)
    n = {k: len(v) for k, v in hits.items()}
    ev = {k: [{'title': a.get('title', '')[:160], 'source': a.get('source', ''), 'url': a.get('url', '')}
              for a in list(v.values())[:3]] for k, v in hits.items()}
    pressure = [aid for aid in _PRESSURE_ACTORS
                if (actor_summaries.get(aid) or {}).get('level') in ('elevated', 'high', 'surge')]
    p_names = ' and '.join(ACTORS[a]['name'] for a in pressure)
    steady = n['holding'] + n['expanding']

    if n['withdrawing'] >= 2:
        state = 'withdrawing'
        reading = ('Two or more outlets report Rwandan troops leaving a deployment. The security-export model is '
                   'contracting -- check which spoke, and who fills the gap.')
    elif n['wavering'] >= 2:
        state = 'wavering'
        reading = ('Two or more outlets report a withdrawal threat, a funding gap or a halt in support for a '
                   'Rwandan deployment. The model is under strain; the deployments have not moved yet.')
    elif pressure and steady >= 1:
        state = 'pressured_holding'
        reading = ('%s above baseline while the deployments are reported steady (%d outlets). Sanctioned and still '
                   'deployed: the 2026 norm, and the finding is that the pressure has not reached the spokes.'
                   % (p_names, steady))
    elif n['expanding'] >= 2:
        state = 'expanding'
        reading = 'Two or more outlets report Rwandan deployments growing or extending. The model is expanding.'
    elif steady >= 2:
        state = 'holding'
        reading = ('Two or more outlets report the deployments continuing, with Western pressure at or below '
                   'baseline this window.')
    elif sum(n.values()):
        state = 'thin'
        reading = 'One outlet only on the deployments this window: held as thin, not as a finding.'
    else:
        state = 'unread'
        reading = ('No reporting this window on the CAR or Mozambique deployments.%s Unread, not holding.'
                   % ((' %s is above baseline.' % p_names) if pressure else ''))
    return {'id': 'export_axis_rwanda', 'state': state, 'outlets': n, 'evidence': ev, 'reading': reading,
            'pressure_lit': pressure,
            'states_defined': ['expanding', 'holding', 'pressured_holding', 'wavering', 'withdrawing', 'thin',
                               'unread'],
            'watch': ['Who pays for the Mozambique mission in 2027 -- Maputo, the EU, or TotalEnergies indirectly',
                      'Whether US sanctions reach RDF procurement for the foreign missions',
                      'MINUSCA\'s budget and the bilateral guard in Bangui',
                      'A second funding scare in Cabo Delgado before first LNG (targeted 2029)']}


# ════════════════════════════════════════════════════════════
# PROSE -- estimative voice, builtin (no Claude call)
# ════════════════════════════════════════════════════════════
TRIPWIRE_SIG_LEVEL = {'surge': 4, 'high': 3, 'elevated': 2}
TRIPWIRE_AXIS = {
    'deployment_withdrawal': 'kinetic', 'withdrawal_threat': 'diplomatic', 'new_us_sanctions': 'diplomatic',
    'agoa_exit': 'economic', 'eu_sanctions': 'diplomatic', 'interstate_clash_burundi': 'kinetic',
    'fire_on_rwandan_soil': 'kinetic', 'un_experts_report': 'diplomatic', 'return_hub_signed': 'diplomatic',
    'mineral_traceability_shock': 'economic',
}
ACTOR_AXIS = {
    'kagame_govt': 'governance', 'rdf_posture': 'diplomatic', 'car_mission': 'diplomatic',
    'mozambique_mission': 'diplomatic', 'drc_file': 'diplomatic', 'burundi_strand': 'diplomatic',
    'us_pressure': 'diplomatic', 'europe_track': 'diplomatic', 'china_axis': 'economic',
    'other_partners': 'economic', 'minerals_gold': 'economic', 'economy': 'economic', 'return_hub': 'diplomatic',
    'home_soil': 'kinetic',
}
SIG_COLOR = {0: '#6b7280', 1: '#3b82f6', 2: '#f59e0b', 3: '#f97316', 4: '#ef4444', 5: '#7c3aed'}
_LIT = ('elevated', 'high', 'surge')


def _measured(aid):
    return ACTOR_VALIDATION.get(aid, {}).get('status') != 'unvalidated'


def _lit_ripples(actor_summaries):
    out = []
    for aid, rp in RIPPLES.items():
        s = actor_summaries.get(aid) or {}
        if s.get('level') in _LIT and _measured(aid):
            out.append({'actor': aid, 'name': ACTORS[aid]['name'], 'level': s['level'],
                        'platform_level': LEVEL_TO_PLATFORM.get(s['level'], 2), **rp})
    out.sort(key=lambda r: -r['platform_level'])
    return out


def _prose(theatre_level, home, actor_summaries, tripwires, export, wheel):
    sigs = []
    for t in tripwires[:4]:
        tid = t.get('id', 'tripwire')
        lv = TRIPWIRE_SIG_LEVEL.get(t.get('severity'), 2)
        sigs.append({'level': lv, 'severity': t.get('severity'), 'type': 'tripwire', 'priority': 10,
                     'category': 'tripwire', 'pressure_type': TRIPWIRE_AXIS.get(tid, 'diplomatic'),
                     'theatre': 'rwanda', 'icon': '🚨', 'color': SIG_COLOR[lv],
                     'short_text': '%s Rwanda red line: %s' % (FLAG, tid.replace('_', ' ')),
                     'long_text': (TRIPWIRES.get(tid) or {}).get('note', '')})
    if home['level'] >= 3:
        sigs.append({'level': home['level'], 'type': 'front', 'priority': 9, 'category': 'kinetic_front',
                     'pressure_type': 'kinetic', 'standing': False, 'front': 'home_soil', 'theatre': 'rwanda',
                     'icon': '💥', 'color': SIG_COLOR.get(home['level'], '#6b7280'),
                     'short_text': '%s Rwanda home soil at L%d' % (FLAG, home['level']),
                     'long_text': 'Worst report: "%s" (%s). %d outlets at this rung.'
                                  % ((home.get('worst') or {}).get('title', '')[:140],
                                     (home.get('worst') or {}).get('source', ''), home['outlets_at_level'])})
    for aid in ('us_pressure', 'mozambique_mission', 'drc_file', 'burundi_strand', 'car_mission', 'china_axis',
                'europe_track', 'return_hub', 'minerals_gold', 'other_partners', 'rdf_posture', 'kagame_govt',
                'economy'):
        s = actor_summaries.get(aid) or {}
        if s.get('level') in _LIT and _measured(aid):
            ta = (s.get('top_articles') or [{}])[0]
            lv = LEVEL_TO_PLATFORM.get(s['level'], 2)
            sigs.append({'level': lv, 'type': 'actor_signal', 'priority': 7, 'category': 'actor_signal',
                         'pressure_type': ACTOR_AXIS.get(aid, 'diplomatic'), 'theatre': 'rwanda',
                         'icon': ACTORS[aid]['icon'], 'color': SIG_COLOR.get(lv, '#6b7280'),
                         'short_text': '%s Rwanda %s at %s' % (FLAG, ACTORS[aid]['name'], s['level'].upper()),
                         'long_text': '"%s" (%s)' % (ta.get('title', '')[:160], ta.get('source', ''))})
    if export['state'] in ('wavering', 'withdrawing', 'pressured_holding'):
        sigs.append({'level': {'withdrawing': 4, 'wavering': 3}.get(export['state'], 2), 'type': 'export_axis',
                     'priority': 8, 'category': 'actor_signal', 'pressure_type': 'diplomatic', 'theatre': 'rwanda',
                     'icon': '🛡️', 'color': SIG_COLOR[3 if export['state'] in ('wavering', 'withdrawing') else 2],
                     'short_text': '%s Rwanda export vs pressure: %s' % (FLAG, export['state'].replace('_', ' ')),
                     'long_text': export['reading']})
    if wheel.get('converged'):
        sigs.append({'level': 3, 'type': 'wheel', 'priority': 9, 'category': 'wheel_convergence',
                     'pressure_type': 'diplomatic', 'theatre': 'rwanda', 'icon': '☸️', 'color': SIG_COLOR[3],
                     'short_text': '%s Rwanda wheel converged: %d of %d spokes lit'
                                   % (FLAG, wheel.get('lit_count', 0), wheel.get('spoke_count', 3)),
                     'long_text': wheel.get('headline', '')})
    sigs.sort(key=lambda x: -x.get('priority', 0))

    parts = ['Rwanda reads L%d (%s).' % (theatre_level, PLATFORM_LABELS.get(theatre_level, ''))]
    parts.append('The Rwanda wheel: %d of %d spokes lit%s.' % (
        wheel.get('lit_count', 0), wheel.get('spoke_count', 3), ' -- CONVERGED' if wheel.get('converged') else ''))
    parts.append('Export vs pressure: %s.' % export['state'].replace('_', ' '))
    parts.append('Convergence read, not prediction.')

    lvl = lambda a: (actor_summaries.get(a) or {}).get('level')
    tw_ids = {t.get('id') for t in tripwires}
    so_what = []
    if export['state'] in ('wavering', 'withdrawing'):
        so_what.append({'weight': 0.95, 'actor': 'mozambique_mission', 'bullet': export['reading'] + (
            ' Why it matters beyond Rwanda: Rwandan troops are the security behind the Mozambique LNG restart '
            '(first LNG targeted 2029) and part of the guard on CAR\'s president. A gap there is a gas-supply '
            'question for Europe and Asia and a security question for Bangui.')})
    elif export['state'] == 'pressured_holding':
        so_what.append({'weight': 0.85, 'actor': 'us_pressure', 'bullet': export['reading'] + (
            ' The unasked question: how long the deployments Washington is NOT aiming at -- Mozambique and CAR -- '
            'can be insulated from the sanctions it IS aiming at the DRC file.')})
    if wheel.get('converged'):
        so_what.append({'weight': 0.9, 'bullet': (
            'The Rwanda wheel has converged: %d spokes lit at once (%s). One army, several theatres: when more than '
            'one Rwandan spoke lights together, the common factor is Kigali -- read the pressure and the '
            'deployments together, not country by country.' % (
                wheel.get('lit_count', 0),
                ', '.join(s['display'] for s in wheel.get('spokes', []) if s.get('state') == 'lit')))})
    if lvl('us_pressure') in _LIT or tw_ids & {'new_us_sanctions', 'agoa_exit'}:
        so_what.append({'weight': 0.85, 'actor': 'us_pressure', 'bullet': (
            'US pressure is above baseline. Sanctions aimed at the DRC file land on the same army that guards the '
            'Mozambique LNG restart and CAR\'s president: Washington\'s Great Lakes policy and Europe\'s gas supply '
            'meet in Cabo Delgado. Kigali rejects the allegations.')})
    if lvl('mozambique_mission') in _LIT:
        so_what.append({'weight': 0.85, 'actor': 'mozambique_mission', 'bullet': (
            'The Mozambique mission is in the news. It is the spoke that pays Rwanda\'s way -- political capital in '
            'Maputo, with TotalEnergies and with donors -- and the one the Mozambique tracker will read from the '
            'other side once it ships. Until then this is the hub\'s lens only.')})
    if lvl('burundi_strand') in _LIT or 'interstate_clash_burundi' in tw_ids:
        so_what.append({'weight': 0.8, 'actor': 'burundi_strand', 'bullet': (
            'Burundi is above baseline. No relations since January 2024, Burundian troops on Kinshasa\'s side in '
            'South Kivu, mutual accusations of backing rebels: a direct Rwanda-Burundi clash is the step that would '
            'turn the eastern war interstate.')})
    if lvl('china_axis') in _LIT or lvl('other_partners') in _LIT:
        so_what.append({'weight': 0.75, 'actor': 'china_axis', 'bullet': (
            'The hedge is in the news: China, the Gulf or Russia. If Western pressure pushes Kigali east, Rwandan '
            'tantalum and tungsten -- capacitors, tooling, munitions -- follow, into supply chains Washington is '
            'trying to diversify away from China.')})
    if lvl('return_hub') in _LIT or 'return_hub_signed' in tw_ids:
        so_what.append({'weight': 0.7, 'actor': 'return_hub', 'bullet': (
            'The EU return hub is in the news. Five European states seeking a migration deal with Kigali while the '
            'US sanctions it: the West is using Rwanda for different things at once, and Kigali knows it.')})
    if lvl('minerals_gold') in _LIT or 'mineral_traceability_shock' in tw_ids:
        so_what.append({'weight': 0.7, 'actor': 'minerals_gold', 'bullet': (
            'The minerals file is moving. Rwanda\'s top export earner is also the heart of the DRC dispute (UN '
            'experts say part of it is Congolese; Kigali denies it). A price surge raises the value of Rubaya; a '
            'traceability crackdown hits Kigali\'s budget.')})
    if home['level'] >= 3 or 'fire_on_rwandan_soil' in tw_ids:
        so_what.append({'weight': 0.9, 'actor': 'home_soil', 'bullet': (
            'Fire or raids reported on Rwandan soil, on two or more outlets. Rwanda is calm at home, so this is '
            'news, not condition -- and it is what Kigali cites as grounds for "defensive measures".')})
    if not so_what:
        so_what.append({'weight': 0.3, 'bullet': (
            'Nothing above baseline this scan. Baseline for Rwanda still means a sanctioned army deployed in two '
            'foreign missions, an AGOA exit on 1 January, and a contested role in the eastern DRC. A quiet scan is a '
            'quiet feed, not a quiet hub.')})
    so_what.sort(key=lambda b: -b['weight'])
    return sigs[:10], ' '.join(parts), so_what[:6]


# ════════════════════════════════════════════════════════════
# SCORING (fixed-corpus testable)
# ════════════════════════════════════════════════════════════
def _gather(days):
    rss = fetch_all_rss()
    gdelt = fetch_all_gdelt(days)
    newsapi = fetch_newsapi(days)
    brave = fetch_brave(len(gdelt), len(newsapi))
    return rss, gdelt, newsapi, brave


def score_articles(articles):
    gated, rejected = [], 0
    gate_reasons = {'country': 0, 'rdf': 0, 'none': 0}
    for a in articles:
        ok, why = passes_country_gate(a)
        if ok:
            gate_reasons[why] += 1
            gated.append(a)
        else:
            rejected += 1
            gate_reasons['none'] += 1

    by_actor = {k: [] for k in ACTORS}
    for a in gated:
        for aid, hits in _classify_article(a):
            c = dict(a)
            c['_hits'] = hits
            by_actor[aid].append(c)

    actor_summaries, tripwires = {}, []
    _floor = {'surge': 'surge', 'high': 'high', 'elevated': 'elevated'}
    for aid, meta in ACTORS.items():
        sc = _score_actor(by_actor[aid])
        lvl = actor_alert_level(sc['score'], meta['baseline_statements_per_week'])
        actor_summaries[aid] = {
            'name': meta['name'], 'flag': meta['flag'], 'icon': meta['icon'], 'color': meta['color'],
            'role': meta['role'], 'description': meta['description'], 'vector': meta['vector'],
            'spoke': meta.get('spoke'),
            'level': lvl, 'score': sc['score'], 'baseline': meta['baseline_statements_per_week'],
            'article_count': sc['article_count'], 'outlets': sc['outlets'],
            'language_breakdown': sc['language_breakdown'], 'sources': sc['sources'],
            'top_articles': sc['top_articles'], 'tripwires': sc['tripwires'],
            'kigali_aligned_share': sc['kigali_aligned_share'],
            'source_headlines': meta.get('source_headlines', []),
            'validation': ACTOR_VALIDATION.get(aid, {'status': 'unknown'}),
            'ripple': RIPPLES.get(aid),
        }
        for tw in sc['tripwires']:
            f = _floor.get(tw.get('severity'))
            if f and _rank(f) > _rank(actor_summaries[aid]['level']):
                actor_summaries[aid]['level'] = f
                actor_summaries[aid]['level_basis'] = 'red_line:%s' % tw['id']
            if not any(t['id'] == tw['id'] for t in tripwires):
                tripwires.append({'actor': aid, **tw})

    home = front_ladder(by_actor['home_soil'])
    actor_summaries['home_soil']['ladder'] = home
    kinetic_level = home['level']

    deploy, seen_u = [], set()
    for aid in _DEPLOYMENT_ACTORS:
        for a in by_actor[aid]:
            if a.get('url') not in seen_u:
                seen_u.add(a.get('url'))
                deploy.append(a)
    export = _export_axis(deploy, actor_summaries)

    vector_levels, vector_levels_platform = {}, {}
    for vec, members in VECTOR_GROUPS.items():
        if vec == 'home_soil':
            vector_levels_platform[vec] = kinetic_level
            vector_levels[vec] = 'L%d' % kinetic_level
            continue
        lv = [actor_summaries[m]['level'] for m in members if _measured(m)]
        if not lv:
            vector_levels[vec] = 'unread'
            continue
        top = max(lv, key=_rank)
        vector_levels[vec] = top
        vector_levels_platform[vec] = LEVEL_TO_PLATFORM[top]

    non_kinetic = max([v for k, v in vector_levels_platform.items() if k != 'home_soil'] + [0])
    theatre_level = max(min(non_kinetic, 4), kinetic_level)
    l5_gate = {'kinetic': kinetic_level >= 5, 'any': kinetic_level >= 5,
               'reason': ('The home-soil ladder reached L5 on two or more outlets.' if kinetic_level >= 5 else
                          'No L5. For Rwanda, L5 needs Kigali attacked, a border town taken, or Rwandan troops '
                          'invading a neighbour, reported by two or more outlets. Sanctions, rhetoric volume and '
                          'tripwires cannot open it.')}
    return {'gated': gated, 'rejected': rejected, 'gate_reasons': gate_reasons, 'by_actor_counts':
            {k: len(v) for k, v in by_actor.items()},
            'actor_summaries': actor_summaries, 'tripwires': tripwires, 'home': home,
            'kinetic_level': kinetic_level, 'vector_levels': vector_levels,
            'vector_levels_platform': vector_levels_platform, 'theatre_level': theatre_level,
            'l5_gate': l5_gate, 'export_axis': export}


def _write_spokes(actor_summaries, theatre_level, export, ts):
    """spoke:<hub>:rwanda for each wheel RWANDA sits on (US, China)."""
    written = []
    for hub, cfg in SPOKES_OUT.items():
        s = actor_summaries.get(cfg['actor']) or {}
        lvl = LEVEL_TO_PLATFORM.get(s.get('level', 'low'), 0) if _measured(cfg['actor']) else 0
        ta = (s.get('top_articles') or [{}])[0]
        if lvl >= 2 and ta.get('title'):
            top = 'Rwanda: %s at L%d -- "%s"' % (ACTORS[cfg['actor']]['name'], lvl, ta['title'][:110])
        elif s.get('article_count'):
            top = 'Rwanda: %s -- background mentions only (L%d).' % (ACTORS[cfg['actor']]['name'], lvl)
        else:
            top = 'Rwanda: no %s reporting this window. Unread, not calm.' % ACTORS[cfg['actor']]['name']
        payload = {'ts': ts, 'hub': hub, 'country': 'rwanda', 'level': lvl,
                   'node_class': cfg['node_class'], 'relationship': cfg['node_class'],
                   'top_signal': top[:180], 'why': cfg['why'], 'items': s.get('article_count', 0),
                   'theatre_level': theatre_level, 'export_state': export['state'],
                   'ripple_globe': (RIPPLES.get(cfg['actor']) or {}).get('globe'),
                   'source': 'rhetoric_tracker_rwanda v%s' % MODULE_VERSION}
        if _redis_set('spoke:%s:rwanda' % hub, payload, ttl_hours=SPOKE_TTL_HOURS):
            written.append(hub)
    if written:
        print('[Rwanda Rhetoric] outbound spokes written: %s' % ', '.join(written))
    return written


def scan_rwanda_rhetoric(force=False, days=7):
    global _last_scan_started_at
    _last_scan_started_at = datetime.now(timezone.utc)
    t0 = time.time()
    print('[Rwanda Rhetoric] === scan start (force=%s days=%s) ===' % (force, days))
    rss, gdelt, newsapi, brave = _gather(days)
    seen, articles = set(), []
    for a in (rss + gdelt + newsapi + brave):
        u = a.get('url', '')
        if u and u not in seen:
            seen.add(u)
            articles.append(a)

    try:
        from recency_gate import filter_recent
        articles, _recency = filter_recent(articles, days)
    except Exception as _e:
        _recency = {'error': 'recency gate failed open: %s' % str(_e)[:100]}
    _RECENCY_STATE['last'] = _recency
    print('[Rwanda Rhetoric] recency gate: %s' % _recency)

    S = score_articles(articles)
    actor_summaries, tripwires = S['actor_summaries'], S['tripwires']
    theatre_level, export, home = S['theatre_level'], S['export_axis'], S['home']
    wheel = read_rwanda_wheel(actor_summaries)
    humanitarian = _read_humanitarian_context()
    commodity = _read_commodity_context()
    spoke_fps = _read_spoke_fingerprints()
    top_signals, executive_summary, so_what = _prose(theatre_level, home, actor_summaries, tripwires, export, wheel)
    ripples_lit = _lit_ripples(actor_summaries)

    _rl = [{'id': t.get('id'), 'actor': t.get('actor'), 'severity': t.get('severity'),
            'status': 'BREACHED' if t.get('severity') in ('surge', 'high') else 'APPROACHING',
            'note': (TRIPWIRES.get(t.get('id')) or {}).get('note', '')} for t in tripwires]
    red_lines = {'triggered': _rl, 'breached_count': sum(1 for r in _rl if r['status'] == 'BREACHED'),
                 'approaching_count': sum(1 for r in _rl if r['status'] == 'APPROACHING')}
    composite_score = round(sum(s['score'] for s in actor_summaries.values()), 2)
    now = datetime.now(timezone.utc).isoformat()
    outbound = {hub: {'actor': c['actor'], 'node_class': c['node_class'],
                      'level': LEVEL_TO_PLATFORM.get((actor_summaries.get(c['actor']) or {}).get('level', 'low'), 0)}
                for hub, c in SPOKES_OUT.items()}
    aligned_n = sum(1 for a in S['gated'] if a.get('voice') == 'kigali_aligned')
    result = {
        'success': True, 'country': 'rwanda', 'country_display': 'Rwanda',
        'module': 'rhetoric_tracker_rwanda', 'version': MODULE_VERSION, 'node_class': 'hub',
        'hub_declared': True,
        'theatre_level': theatre_level, 'theatre_score': min(100, int(composite_score)),
        'theatre_label': PLATFORM_LABELS.get(theatre_level, 'Monitoring'),
        'composite_score': composite_score, 'kinetic_level': S['kinetic_level'], 'l5_gate': S['l5_gate'],
        'home_soil': home, 'export_axis': export,
        'wheel': wheel, 'spoke_fingerprints': spoke_fps, 'outbound_spokes': outbound,
        'ripples_lit': ripples_lit, 'ripple_map': RIPPLES, 'ripples_as_of': RIPPLES_AS_OF,
        'ripple_note': ('Ripple chains are dated reference knowledge: what each actor TOUCHES at the scale of the '
                        'country, the region, the continent and the globe. They never score, and they say what a '
                        'move touches, not what will happen.'),
        'vector_levels': S['vector_levels'], 'vector_levels_platform': S['vector_levels_platform'],
        'vector_labels': VECTOR_LABELS, 'vector_groups': VECTOR_GROUPS, 'red_lines': red_lines, 'scan_date': now,
        'article_count': len(S['gated']), 'actor_summaries': actor_summaries,
        'actor_validation_as_of': VALIDATION_AS_OF, 'validation_corpus_note': VALIDATION_CORPUS_NOTE,
        'tripwires_global': tripwires,
        'humanitarian_context': humanitarian, 'commodity_context': commodity,
        'top_signals': top_signals, 'executive_summary': executive_summary, 'so_what': so_what,
        'voices': {'kigali_aligned_articles': aligned_n,
                   'kigali_aligned_feeds': [c['name'] for c in RSS_FEEDS.values() if c.get('voice') == 'kigali_aligned'],
                   'note': ('KT Press and Taarifa are read as Kigali\'s voice: weighted 0.8, outlet-capped, and '
                            'labelled wherever their headlines appear.')},
        'source_breakdown': {'rss': len(rss), 'gdelt': len(gdelt), 'newsapi': len(newsapi), 'brave': len(brave)},
        'articles_scanned': len(articles), 'articles_passed_country_gate': len(S['gated']),
        'articles_rejected_by_gate': S['rejected'], 'gate_reasons': S['gate_reasons'],
        'gate_note': ('An article must name Rwanda or a Rwandan place, person or institution. "Kigali Amendment" '
                      '(the Montreal Protocol) is ignored.'),
        'scan_time_seconds': round(time.time() - t0, 1), 'days_analyzed': days, 'recency': _recency,
        'last_updated': now, 'cached': False,
    }
    save_cache(result)
    _write_spokes(actor_summaries, theatre_level, export, now)
    # Fingerprint: NO keys named after other hubs (us_*, china_*) -- the wheel
    # reader infers spoke membership from key names, and the outbound spokes
    # are already written explicitly above.
    _redis_set(FINGERPRINT_KEY, {
        'ts': now, 'theatre': 'rwanda', 'country': 'rwanda', 'node_class': 'hub', 'hub_declared': True,
        'theatre_level': theatre_level, 'kinetic_level': S['kinetic_level'],
        'export_state': export['state'],
        'own_wheel': {'lit': wheel.get('lit_count', 0), 'of': wheel.get('spoke_count', 3),
                      'converged': bool(wheel.get('converged'))},
        'tripwires': tripwires[:6],
    }, ttl_hours=14)
    try:
        _redis_lpush_trim(HISTORY_KEY, {
            'scanned_at': now, 'theatre_level': theatre_level, 'kinetic_level': S['kinetic_level'],
            'red_lines_count': len(tripwires), 'export_state': export['state'],
            'wheel_lit': wheel.get('lit_count', 0), **{k: v for k, v in S['vector_levels'].items()},
        }, max_len=336)
    except Exception as e:
        print('[Rwanda Rhetoric] history write failed: %s' % str(e)[:100])
    print('[Rwanda Rhetoric] done in %ss -- L%s, export %s, wheel %s/%s, gate %d/%d'
          % (result['scan_time_seconds'], theatre_level, export['state'], wheel.get('lit_count', 0),
             wheel.get('spoke_count', 3), len(S['gated']), len(articles)))
    return result


# ════════════════════════════════════════════════════════════
# BACKGROUND + ENDPOINTS
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
                scan_rwanda_rhetoric(force=True, days=7)
            finally:
                with _scan_lock:
                    _scan_running = False
            time.sleep(BACKGROUND_REFRESH_HOURS * 3600)
        except Exception as e:
            print('[Rwanda Rhetoric] background error: %s' % str(e)[:150])
            time.sleep(600)


def start_background_refresh():
    threading.Thread(target=_background_loop, daemon=True, name='RwandaRhetoricBG').start()
    print('[Rwanda Rhetoric] background thread started (initial delay %ss)' % INITIAL_SCAN_DELAY_SECONDS)


def register_rwanda_rhetoric_routes(app, start_background=True):
    from flask import jsonify, request

    @app.route('/api/rhetoric/rwanda', methods=['GET', 'OPTIONS'])
    def api_rwanda_rhetoric():
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
                    threading.Thread(target=lambda: scan_rwanda_rhetoric(force=True), daemon=True).start()
            return jsonify(cached)
        return jsonify(scan_rwanda_rhetoric(force=force, days=7))

    @app.route('/api/rhetoric/rwanda/debug', methods=['GET'])
    def api_rwanda_rhetoric_debug():
        cached = load_cache()
        return jsonify({
            'module': 'rhetoric_tracker_rwanda v%s' % MODULE_VERSION,
            'actors': list(ACTORS.keys()), 'vectors': list(VECTOR_GROUPS.keys()),
            'wheel_lens': WHEEL_LENS, 'outbound_spokes': list(SPOKES_OUT.keys()),
            'tripwires': list(TRIPWIRES.keys()), 'export_states': list(EXPORT_PATTERNS.keys()),
            'ripples_for': list(RIPPLES.keys()),
            'l5_rule': 'Only the home-soil kinetic ladder at L5 on two or more outlets.',
            'actor_validation': ACTOR_VALIDATION, 'validation_as_of': VALIDATION_AS_OF,
            'validation_corpus_note': VALIDATION_CORPUS_NOTE,
            'rss_feeds': {k: v['name'] for k, v in RSS_FEEDS.items()},
            'redis_wired': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured': bool(NEWSAPI_KEY), 'brave_configured': bool(BRAVE_API_KEY),
            'recency_gate': _RECENCY_STATE['last'],
            'cache_present': cached is not None,
            'cache_fresh': is_cache_fresh(cached) if cached else False,
            'last_export_state': (cached or {}).get('export_axis', {}).get('state'),
            'last_wheel': {k: (cached or {}).get('wheel', {}).get(k) for k in ('lit_count', 'spoke_count', 'converged')},
            'last_scan_started_at': _last_scan_started_at.isoformat() if _last_scan_started_at else None,
            'background_running': _scan_running,
        })

    print('[Rwanda Rhetoric] endpoints registered: /api/rhetoric/rwanda, /api/rhetoric/rwanda/debug')
    if start_background:
        start_background_refresh()
