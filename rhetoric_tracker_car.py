"""
rhetoric_tracker_car.py -- Asifah Analytics Africa Backend -- v1.0.0
22 November 2026

CENTRAL AFRICAN REPUBLIC RHETORIC TRACKER. The analyst layer behind
car-stability.html.

WHAT CAR IS, FOR THIS TRACKER
    CAR is where Russia's African model began (2018): a security guarantee for
    the president, paid in mining concessions, with political advisers
    attached. In 2026 the model is being NATIONALISED (Moscow's Africa Corps)
    and CONTESTED (Wagner's heirs) at the same time, and the reporting
    contradicts itself about who actually guards Touadera. So the tracker's
    signature read is not "how much Russia" but WHO GUARDS THE PRESIDENT:
        wagner_held . contested . handover_reported . thinning . unread
    Rachel (22 Nov 2026): ONE Russia spoke, with Wagner / Africa Corps built
    inside it -- two spokes would make Russia look twice as present when the
    story is that it is divided.

    CAR also sits on more wheels than Russia's: Rwanda (troops under MINUSCA and
    a bilateral deal; a NEW hub started with this build), the UAE (where nearly
    all declared gold goes), China (Chinese-run gold sites) and the US
    (Africom's return). Each is written as spoke:<hub>:car.

FIVE VECTORS
    regime_security      Touadera's third term; opposition repression.
    insurgent_fronts     THREE STANDING FRONTS + unplaced attacks, each on a
                         KINETIC LADDER: the north-west (CPC / ex-3R,
                         transhumance), the south-east (Haut-Mbomou, the AAKG)
                         and the north-east (Vakaga, the Sudan border).
    external_alignment   Russia (Wagner / Africa Corps), Rwanda, the UAE, the
                         US, China, France, MINUSCA, Chad.
    resource_leverage    Gold, diamonds and timber -- the money behind the guns.
    lifelines            The Douala road and fuel.

THE KINETIC LADDER -- L5 COMES ONLY FROM HERE (Niger doctrine, unchanged)
        L1 mention . L2 threat / claim . L3 attack / clash / killing
        L4 mass casualty (10+ killed, massacre, "dozens")
        L5 a town or base taken, or the capital attacked
    L3 and above need TWO OR MORE distinct outlets. All three fronts are
    STANDING (CAR's war has run since 2013): L3-L4 is the condition, not news,
    and the payload says so.

OUTLETS (v1.0.0 fix, also owed to Niger): Google News RSS items carry the
    feed's name as their source, so every Google News article used to count
    as ONE outlet for the two-outlet rule. Here the real outlet is read from
    the headline's " - Outlet" suffix.

THE COUNTRY GATE -- "Central Africa" is a region, "Bangui" is also a town in
    the Philippines, and "CAR" is a car. An article passes only if it names
    the Central African Republic, a CAR place, person or institution.

KEYWORD DISCIPLINE: every actor keyword traces to a verbatim 2026 headline,
    harvested 22 Nov 2026 and quoted in source_headlines; validation is
    MEASURED by test_car_harness.py, and an actor whose list matched nothing
    reads UNREAD, never low.

EMITS
    rhetoric:car:latest            full payload (12h)  <- africa_regional_bluf
    rhetoric:car:history           rolling snapshots
    crosstheater:car:fingerprint   slice for BLUF / GPI
    spoke:<hub>:car                russia, rwanda, uae, china, us wheels

ENDPOINTS
    GET /api/rhetoric/car
    GET /api/rhetoric/car?refresh=true      (no Claude calls; news fetch only)
    GET /api/rhetoric/car/debug

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
    print('[CAR Rhetoric] feedparser unavailable -- RSS disabled')

MODULE_VERSION = '1.0.2'   # Nov 27 2026 (b): outlet cap (one site counts for 2 articles per actor max) + URL-signed outlets shown as hostnames. 1.0.1 Nov 27 2026: recency gate (old Google News / Brave stories no longer score) + Brave freshness=pw + Google News when:7d
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
INITIAL_SCAN_DELAY_SECONDS = 270   # staggered behind Burkina (150s), Niger (210s)

REDIS_KEY_LATEST = 'rhetoric:car:latest'
HISTORY_KEY      = 'rhetoric:car:history'
FINGERPRINT_KEY  = 'crosstheater:car:fingerprint'
HUMANITARIAN_KEY = 'africa:humanitarian:car'
SPOKE_TTL_HOURS  = 30

GDELT_BASE_URL   = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI_BASE_URL = 'https://newsapi.org/v2/everything'
BRAVE_BASE_URL   = 'https://api.search.brave.com/res/v1/news/search'

CACHE_FILE = '/tmp/car_rhetoric_cache.json'

_scan_running = False
_scan_lock = threading.Lock()
_last_scan_started_at = None

FLAG = '\U0001F1E8\U0001F1EB'


# ════════════════════════════════════════════════════════════
# ACTORS -- 16 actors / 5 vectors
# Every keyword traces to a verbatim 2026 headline (harvested 22 Nov 2026).
# French matters: Bangui's press (Radio Ndeke Luka, Corbeau News, Oubangui
# Médias) and RFI publish in French first.
# ════════════════════════════════════════════════════════════
ACTORS = {
    # ── VECTOR: regime_security ──────────────────────────────
    'touadera_govt': {
        'name': 'Touadéra government', 'flag': FLAG, 'icon': '\U0001F3DB️', 'color': '#e2e8f0',
        'role': 'The presidency -- third term, decrees, the security file',
        'description': ('Faustin-Archange Touadéra, sworn in for a third term on 30 March 2026 after a '
                        '2023 referendum removed term limits. Consolidation tempo measures how much the '
                        'presidency is absorbing, not how secure it is.'),
        'vector': 'regime_security',
        'keywords': ['touadéra', 'touadera', 'troisième mandat', 'third term', 'investiture',
                     'gouvernement centrafricain', 'central african government', 'président centrafricain',
                     'central african president', 'bangui government'],
        'source_headlines': [
            '2026-01-08 Centrafrique: La milice AAKG, premier défi du troisième mandat du président Touadéra (allAfrica)',
            "2026-01-12 Fresh Violence Tests Touadéra's New Mandate in Central African Republic (allAfrica)",
            '2026-03 Centrafrique : investiture de Touadéra ce lundi à Bangui (APA)',
            '2026-01-07 Centrafrique: Archange sur un troisième nuage (allAfrica)',
        ],
        'baseline_statements_per_week': 4,
    },
    'opposition_repression': {
        'name': 'Opposition & repression', 'flag': FLAG, 'icon': '\U0001F5F3️', 'color': '#f97316',
        'role': 'Opposition leaders, travel bans, nationality, banned meetings',
        'description': ('Anicet-Georges Dologuélé claimed fraud in the December 2025 vote; in May 2026 '
                        'he was stopped at Bangui airport and his passport seized. Read as the regime\'s '
                        'pressure on its rivals, not as a measure of opposition strength.'),
        'vector': 'regime_security',
        'keywords': ['dologuélé', 'dologuele', 'opposant', 'opposition leader', "chef de l'opposition",
                     'passeport', 'passport', 'empêché de voyager', 'privé de sa nationalité',
                     'fraude', 'meeting interdit', "interdiction d'un meeting"],
        'source_headlines': [
            "2026-05-07 Centrafrique: L'opposant Anicet-Georges Dologuélé, empêché de voyager à l'aéroport de Bangui (allAfrica)",
            '2026-05 Central African Republic opposition leader denounces seizure of his passport (ABC News)',
            '2026-01-03 Centrafrique: Présidentielle - Anicet-Georges Dologuélé dénonce des fraude et revendique la victoire (allAfrica)',
            "2025-12-24 Centrafrique: Le chef de l'opposition Anicet-Georges Dologuélé dénonce l'interdiction d'un meeting de campagne (allAfrica)",
        ],
        'baseline_statements_per_week': 1,
    },

    # ── VECTOR: insurgent_fronts (levels come from the KINETIC LADDER) ──
    'front_northwest': {
        'name': 'North-west front', 'flag': '\U0001F3F4', 'icon': '\U0001F4A5', 'color': '#dc2626',
        'role': 'CPC remnants, ex-3R fighters, transhumance corridors from Chad',
        'description': ('Ouham, Ouham-Pendé and Nana-Mambéré: the CPC coalition and ex-3R fighters who '
                        'allege ceasefire violations by Russian fighters; herds from Chad pass through '
                        'December-April. Standing insurgency.'),
        'vector': 'insurgent_fronts', 'front': 'northwest', 'standing': True,
        'keywords': ['ouham', 'ouham-pendé', 'ouham pende', 'nana-mambéré', 'nana-mambere', 'bocaranga',
                     'paoua', 'koui', 'bozoum', 'batangafo', 'markounda', 'kabo', 'ex-3r', '3r',
                     'retour, réclamation', 'cpc', 'coalition des patriotes', 'nord-ouest', 'north-west',
                     'northwest', 'transhumance', 'berbérati', 'berberati'],
        'source_headlines': [
            "2025-08-21 Centrafrique: Les ex-rebelles des 3R dénoncent des attaques et la violation de l'accord de paix (allAfrica)",
            '2026 C.Africa rebel attack leaves five dead (Modern Ghana)',
        ],
        'baseline_statements_per_week': 2,
    },
    'front_southeast': {
        'name': 'South-east front (Haut-Mbomou)', 'flag': '\U0001F3F4', 'icon': '\U0001F4A5', 'color': '#b91c1c',
        'role': 'The AAKG Zande militia against the army and its Russian partners',
        'description': ('Haut-Mbomou: the Azande Ani Kpi Gbe militia, armed by Wagner in 2024, broke with '
                        'it and now fights the army and the Russians -- Bambouti seized on election day, '
                        "Zémio's hospital attacked on 4 Jan 2026. Standing insurgency."),
        'vector': 'insurgent_fronts', 'front': 'southeast', 'standing': True,
        'keywords': ['haut-mbomou', 'haut mbomou', 'zémio', 'zemio', 'mboki', 'obo', 'djema', 'bambouti',
                     'aakg', 'azandé', 'azande', 'zandé', 'zande', 'ani kpi gbe', 'mbomou', 'bangassou',
                     'rafaï', 'rafai', 'sud-est', 'south-east', 'southeast'],
        'source_headlines': [
            "2026-01-06 Centrafrique: La ville de Zémio, dans le Haut-Mbomou, cible d'une nouvelle attaque (allAfrica)",
            "2026-01-04 Centrafrique: Combats entre l'armée et la milice AAKG dans le sud-est du pays (allAfrica)",
            '2026-01-14 Centrafrique: Retour progressif au calme dans le sud-est, situation humanitaire toujours difficile (allAfrica)',
            '2026-02-10 Fears of rebellion rising in southeast CAR (ADF)',
            'MINUSCA condemns attack against peacekeepers in Haut-Mbomou (MINUSCA)',
        ],
        'baseline_statements_per_week': 2,
    },
    'front_northeast': {
        'name': 'North-east front (Vakaga, Sudan border)', 'flag': '\U0001F3F4', 'icon': '\U0001F4A5', 'color': '#ef4444',
        'role': "The tri-border with Chad and Sudan -- Sudan's war economy and its spillover",
        'description': ('Vakaga and Bamingui-Bangoran: gold, fuel and arms routes of the Sudan war; an '
                        'attack on Am Dafok on the border displaced more than 16,000 people (July 2026); '
                        '~40,000 Sudanese refugees at Korsi near Birao. Standing insurgency.'),
        'vector': 'insurgent_fronts', 'front': 'northeast', 'standing': True,
        'keywords': ['vakaga', 'birao', 'am dafok', 'am dafock', 'korsi', 'ndélé', 'ndele', 'bamingui',
                     'haute-kotto', 'bria', 'sam ouandja', 'tiringoulou', 'nord-est', 'north-east',
                     'northeast', 'nord du pays', 'frontière avec le soudan', 'border with sudan',
                     'guerre au soudan', 'war in sudan'],
        'source_headlines': [
            "2026-07-01 Centrafrique: Frontalière du Soudan, la localité d'Am Dafok visée par une violente attaque (allAfrica)",
            "2026-07-02 Centrafrique: «Les groupes armés mis hors d'état de nuire» suite à l'attaque de la localité d'Am Dafok au nord-est (allAfrica)",
            '2026-11-09 Centrafrique: La guerre au Soudan menace de déstabiliser le nord du pays (allAfrica)',
            "2026-01-22 Afrique: Aux confins de la guerre - Tensions à la frontière centrafricaine avec le Soudan (allAfrica)",
            "2026-01 At the edge of war: the Central African Republic's uneasy border with Sudan (UN News)",
            'Central African Republic: More than 16,000 displaced after an attack in Am Dafock (Seneweb)',
        ],
        'baseline_statements_per_week': 2,
    },
    'attacks_unplaced': {
        'name': 'Attacks (front not named)', 'flag': '\U0001F3F4', 'icon': '❓', 'color': '#94a3b8',
        'role': 'Kinetic reporting that does not say where',
        'description': ('Attacks and casualties reported without a named front. Kept separate so a vague '
                        'headline is not silently credited to the wrong front; it still counts on the '
                        'kinetic ladder.'),
        'vector': 'insurgent_fronts', 'front': 'unplaced', 'standing': False,
        'keywords': ['rebel attack', 'attaque rebelle', 'rebelles', 'rebels', 'armed group', 'armed groups',
                     'groupe armé', 'groupes armés', 'hommes armés', 'milice', 'militia', 'ambush',
                     'embuscade', 'soldiers killed', 'soldats tués', 'civils tués', 'civilians killed'],
        'source_headlines': [
            '2026 C.Africa rebel attack leaves five dead (Modern Ghana)',
            "2026-07-02 «Les groupes armés mis hors d'état de nuire» (allAfrica)",
        ],
        'baseline_statements_per_week': 3,
    },

    # ── VECTOR: external_alignment ───────────────────────────
    'russia_axis_car': {
        'name': 'Russia (Wagner / Africa Corps)', 'flag': '\U0001F1F7\U0001F1FA', 'icon': '\U0001F43B', 'color': '#0ea5e9',
        'role': 'The guarantor -- and the open question of WHICH Russia guards the president',
        'description': ('Wagner since 2018; Africa Corps (Russian MoD) pushing to replace it and asking '
                        'Bangui to pay in cash; WSJ (Oct 2026): ~500 Wagner men still guard Touadéra under '
                        "Prigozhin's son. One spoke, with the Wagner / Africa Corps split read inside it "
                        '(see guard_axis).'),
        'vector': 'external_alignment', 'wheel': 'russia',
        'keywords': ['wagner', 'africa corps', 'russia', 'russian', 'russie', 'russe', 'russes', 'moscow',
                     'moscou', 'kremlin', 'prigozhin', 'prigojine', 'mercenaires', 'mercenaries',
                     'instructeurs russes', 'russian instructors'],
        'source_headlines': [
            '2026-07-17 Russia\'s Shadow Army Wins Again: Wagner Stronghold In CAR Holds The Line Despite Kremlin Shakeup (EurAsian Times)',
            "2026-03-31 Centrafrique: L'Africa Corps semble prendre le relais de Wagner à Bangui (allAfrica)",
            '2026-08-04 How Russia Lost the Ability to Leave the Central African Republic (African Arguments)',
            'Russia asks Central African Republic to replace Wagner with Moscow\'s Africa Corps (PBS)',
            'Russia demands Central African Republic replace Wagner with Africa Corps and pay in cash (intellinews)',
            '2026-10-22 Central Africa: Wood for War - How Wagner Was Paid in Central African Forest (allAfrica)',
            'Central African Republic: Another defeat for the Africa Corps (Modern Ghana)',
            '2026-10-19 500 Wagner Fighters, $400M a Year (Kyiv Post)',
        ],
        'baseline_statements_per_week': 3,
    },
    'rwanda_axis': {
        'name': 'Rwanda', 'flag': '\U0001F1F7\U0001F1FC', 'icon': '\U0001F6E1️', 'color': '#22c55e',
        'role': 'Co-guarantor -- troops under MINUSCA and a bilateral deal; trains the army',
        'description': ('Rwandan troops serve under MINUSCA and under a separate bilateral agreement; RDF '
                        'instructors graduated 670 CAR soldiers in August 2026. The same security-for-access '
                        'model Rwanda runs in Mozambique; the first spoke on the new Rwanda wheel.'),
        'vector': 'external_alignment', 'wheel': 'rwanda',
        'keywords': ['rwanda', 'rwandan', 'rwandais', 'rwandaise', 'rwandaises', 'rdf', 'kagame'],
        'source_headlines': [
            '2026-08-11 Central African Republic: Nearly 700 CAR Soldiers Graduate From RDF-Led Training (allAfrica)',
            'Rwanda, CAR military chiefs discuss cooperation (New Times)',
            '2025-11-25 Central Africa: Kagame, Touadéra Discuss Security Ahead of CAR Elections (allAfrica)',
            'Rwandan army chief visits troops in Central African Republic (New Times)',
        ],
        'baseline_statements_per_week': 1,
    },
    'uae_gold': {
        'name': 'UAE (the gold channel)', 'flag': '\U0001F1E6\U0001F1EA', 'icon': '\U0001F4B0', 'color': '#eab308',
        'role': 'Where the gold goes -- Dubai, Emirati traders and refiners',
        'description': ("Nearly all of CAR's declared gold exports since 2023 went to the UAE (GI-TOC); "
                        'Emirati Sigma Mining and SML Gold have positioned in the trade and refining.'),
        'vector': 'external_alignment', 'wheel': 'uae',
        'keywords': ['emirati', 'émirati', 'émiratie', 'uae', 'dubai', 'dubaï', 'émirats', 'emirates',
                     'sigma mining', 'sml gold'],
        'source_headlines': [
            "2026-06-12 Dubai is Central African Republic's conflict-gold hub (Semafor)",
            "2026-05-18 Emirati Firm Sigma Mining Emerges as Key Player in Central African Republic's Gold Trade (Mining Focus Africa)",
            "RCA : l'Émirati SML Gold investit 10 millions de dollars pour une raffinerie d'or à Bangui (Ecomatin)",
            'Investigation links UAE to illicit gold trade (africa.com)',
        ],
        'baseline_statements_per_week': 1,
    },
    'us_axis': {
        'name': 'United States', 'flag': '\U0001F1FA\U0001F1F8', 'icon': '\U0001F985', 'color': '#3b82f6',
        'role': 'Re-engaging -- Africom assessments, Treasury sanctions on Wagner-linked firms',
        'description': ('Africom completed a second joint assessment with the CAR army and did not rule out '
                        'a permanent office (Feb 2026); Treasury has repeatedly sanctioned Wagner-linked '
                        'CAR companies.'),
        'vector': 'external_alignment', 'wheel': 'us',
        'keywords': ['united states', 'états-unis', 'etats-unis', 'washington', 'africom', 'américain',
                     'américaine', 'american', 'us treasury', 'treasury', 'bancroft'],
        'source_headlines': [
            '2026-02-16 Centrafrique: La Russie et les Occidentaux rivalisent au pays (DW / allAfrica)',
            'The US-Russia battle for influence in Africa plays out in Central African Republic (ABC News)',
            'US targets Wagner-linked firms in Central African Republic, says Treasury Dept (Yahoo)',
        ],
        'baseline_statements_per_week': 1,
    },
    'china_axis': {
        'name': 'China', 'flag': '\U0001F1E8\U0001F1F3', 'icon': '⛏️', 'color': '#ef4444',
        'role': 'Chinese-run gold sites and traders',
        'description': ('Chinese-run artisanal and semi-industrial gold sites operate in the west; workers '
                        'have been killed in attacks on them.'),
        'vector': 'external_alignment', 'wheel': 'china',
        'keywords': ['chinese', 'chinois', 'chinoise', 'chinoises', 'china', 'chine', 'beijing', 'pékin'],
        'source_headlines': [],
        'baseline_statements_per_week': 1,
    },
    'france_axis': {
        'name': 'France', 'flag': '\U0001F1EB\U0001F1F7', 'icon': '\U0001F5FC', 'color': '#a855f7',
        'role': 'The former guarantor -- troops gone (2022), the currency tie remains',
        'description': ('France drafted the MINUSCA renewal (Nov 2026) and remains in the CFA franc '
                        'arrangement; its troops left in 2022.'),
        'vector': 'external_alignment', 'wheel': None,
        'keywords': ['france', 'français', 'française', 'french', 'paris', 'macron'],
        'source_headlines': [
            '2026-11-13 UN security council extends Central African Republic peacekeeping mission until 2027 (Africanews: France drafted the text)',
        ],
        'baseline_statements_per_week': 1,
    },
    'minusca': {
        'name': 'MINUSCA (UN)', 'flag': '\U0001F1FA\U0001F1F3', 'icon': '\U0001FA96', 'color': '#38bdf8',
        'role': 'The UN mission -- mandate, drawdown, attacks on peacekeepers',
        'description': ('Renewed unanimously to 15 Nov 2027 with troop levels reduced, amid the UN\'s cash '
                        'crisis; the UN warned in October against a premature exit. Three peacekeepers were '
                        'wounded in a July 2026 attack.'),
        'vector': 'external_alignment', 'wheel': None,
        'keywords': ['minusca', 'casques bleus', 'casque bleu', 'peacekeepers', 'peacekeeper',
                     'peacekeeping', 'blue helmets', 'security council', 'conseil de sécurité'],
        'source_headlines': [
            '2026-07-02 Centrafrique: Trois Casques bleus blessés dans une attaque contre la MINUSCA (allAfrica)',
            '2026-11-13 Centrafrique : l\'ONU prolonge la MINUSCA mais réduit ses effectifs militaires (Koaci)',
            '2026-10-21 UN warns against premature exit of peacekeepers from Central African Republic (Africanews)',
            '2026-11-13 UN security council extends Central African Republic peacekeeping mission until 2027 (Africanews)',
        ],
        'baseline_statements_per_week': 2,
    },
    'chad_axis': {
        'name': 'Chad', 'flag': '\U0001F1F9\U0001F1E9', 'icon': '\U0001F91D', 'color': '#f59e0b',
        'role': 'The neighbour and mediator -- N\'Djamena hosted the 2025 3R/UPC ceasefire',
        'description': ("Chad mediated the 2025 ceasefire with 3R and UPC and borders the north-west and "
                        "north-east fronts; its own Sudan border crisis limits its bandwidth."),
        'vector': 'external_alignment', 'wheel': None,
        'keywords': ['tchad', 'chad', "n'djamena", 'ndjamena', 'tchadien', 'tchadienne', 'chadian'],
        'source_headlines': [],
        'baseline_statements_per_week': 1,
    },

    # ── VECTOR: resource_leverage ───────────────────────────
    'mineral_economy': {
        'name': 'Gold, diamonds & timber', 'flag': FLAG, 'icon': '\U0001F947', 'color': '#facc15',
        'role': 'The money behind the guns',
        'description': ('Ndassima gold (Wagner-linked Midas Ressources), Diamville diamonds, timber paid '
                        'to Wagner, artisanal mines -- one collapse killed at least 49 in August 2026.'),
        'vector': 'resource_leverage', 'wheel': None,
        'keywords': ['gold', "d'or", 'mine d\'or', 'gold mine', 'ndassima', 'midas', 'mining', 'minier',
                     'minière', 'orpaillage', 'artisanal', 'mine collapse', 'éboulement', 'diamond',
                     'diamonds', 'diamant', 'diamants', 'diamville', 'kimberley', 'timber', 'forest',
                     'forêt', 'uranium', 'mining permits', 'permis miniers'],
        'source_headlines': [
            "2026-06-12 Dubai is Central African Republic's conflict-gold hub (Semafor)",
            '2026-08-20 Central African Republic closes informal gold mine after collapse kills at least 49 (Engineering News)',
            '2026-10-22 Wood for War - How Wagner Was Paid in Central African Forest (allAfrica)',
            'Ndassima Gold Mine: Observed Industrial Expansion in CAR (Satellogic)',
            'Mapping mining permits in the Central African Republic (IPIS)',
        ],
        'baseline_statements_per_week': 2,
    },

    # ── VECTOR: lifelines ────────────────────────────────────
    'fuel_corridor': {
        'name': 'The Douala road & fuel', 'flag': FLAG, 'icon': '⛽', 'color': '#fb923c',
        'role': 'One road to the sea -- trucks, fuel, prices',
        'description': ('~1,450 km from Douala; one licensed fuel importer; ten days of fuel queues in July '
                        '2026; 100+ trucks stranded at Garoua-Boulaï in October 2026.'),
        'vector': 'lifelines', 'wheel': None,
        'keywords': ['fuel', 'carburant', 'carburants', 'pénurie', 'neptune oil', 'garoua-boulaï',
                     'garoua-boulai', 'douala', 'corridor', 'camionneurs', 'truckers', 'trucks', 'camions',
                     'prix des carburants', 'fuel prices', 'truck blockade'],
        'source_headlines': [
            '2026-07-14 Centrafrique: À Bangui, la pénurie de carburant persiste et inquiète les consommateurs (allAfrica)',
            '2026-10-15 Central African Republic truck blockade (Rio Times)',
            'Centrafrique: le bras de fer autour de la hausse des prix des carburants se poursuit (Le360 / AFP)',
            'Corridor Douala-Bangui: Reprise des activités à Garoua-Boulaï (Cameroon Tribune)',
        ],
        'baseline_statements_per_week': 1,
    },
}

VECTOR_GROUPS = {
    'regime_security':    ['touadera_govt', 'opposition_repression'],
    'insurgent_fronts':   ['front_northwest', 'front_southeast', 'front_northeast', 'attacks_unplaced'],
    'external_alignment': ['russia_axis_car', 'rwanda_axis', 'uae_gold', 'us_axis', 'china_axis',
                           'france_axis', 'minusca', 'chad_axis'],
    'resource_leverage':  ['mineral_economy'],
    'lifelines':          ['fuel_corridor'],
}
VECTOR_LABELS = {
    'regime_security':    'Regime Security',
    'insurgent_fronts':   'Insurgent Fronts',
    'external_alignment': 'External Alignment',
    'resource_leverage':  'Resource Leverage',
    'lifelines':          'Lifelines',
}

# The wheels CAR sits on. node_class strings follow spoke_wheel_reader.
SPOKES = {
    'russia': {'actor': 'russia_axis_car', 'node_class': 'expeditionary_client',
               'why': "Wagner since 2018 and Africa Corps alongside it; who actually guards Touadéra is contested."},
    'rwanda': {'actor': 'rwanda_axis', 'node_class': 'security_partner',
               'why': 'Troops under MINUSCA and a bilateral deal; RDF instructors train the CAR army.'},
    'uae':    {'actor': 'uae_gold', 'node_class': 'resource_client',
               'why': "Nearly all of CAR's declared gold exports since 2023 go to the UAE."},
    'china':  {'actor': 'china_axis', 'node_class': 'resource_client',
               'why': 'Chinese-run gold sites in the west.'},
    'us':     {'actor': 'us_axis', 'node_class': 're_engaging',
               'why': 'Africom assessments with the CAR army (Feb 2026); Treasury sanctions on Wagner-linked firms.'},
}


# ════════════════════════════════════════════════════════════
# WHO GUARDS THE PRESIDENT -- the signature axis (Russia, read inside one spoke)
# Patterns trace to the 2026 headlines quoted on russia_axis_car.
# ════════════════════════════════════════════════════════════
GUARD_PATTERNS = {
    'wagner_held': ['holds the line', 'wagner stronghold', 'wagner remains', 'wagner still', 'still guard',
                    'resists', 'resisted', 'refuses to replace', 'prigozhin', 'prigojine', 'pavel prigozhin'],
    'handover':    ['prendre le relais', 'take over from wagner', 'takes over from wagner',
                    'replace wagner', 'remplacer wagner', 'absorbed', 'succède à wagner',
                    'africa corps takes', 'pay in cash', 'payer cash', 'en espèces'],
    'thinning':    ['withdraw', 'withdrawal', 'withdraws', 'pull out', 'pulls out', 'retrait des russes',
                    'retrait de wagner', 'quittent la centrafrique', 'drawdown of russian'],
    'friction':    ['defeat for the africa corps', 'between wagner and africa corps', 'wagner and the africa corps',
                    'rivalry', 'rivalité', 'shakeup', 'shake-up', 'family dispute'],
}


# ════════════════════════════════════════════════════════════
# COUNTRY GATE -- "Central Africa" is a region; Bangui is also a Philippine town
# ════════════════════════════════════════════════════════════
STRONG_TOKENS = [
    'central african republic', 'centrafrique', 'centrafricain', 'centrafricaine', 'centrafricains',
    'république centrafricaine', 'c.africa', 'touadéra', 'touadera', 'minusca', 'faca',
    'zémio', 'zemio', 'haut-mbomou', 'vakaga', 'birao', 'ouham', 'bambari', 'bangassou', 'berbérati',
    'berberati', 'am dafok', 'am dafock', 'ndassima', 'bossangoa', 'bria', 'ndélé', 'kaga-bandoro',
]
BANGUI_ONLY_REJECT = ['ilocos', 'philippines', 'philippine', 'wind farm', 'windmills']
_BANGUI = re.compile(r'(?<![a-z])bangui(?![a-z])')
PHILIPPINES_CONTEXT = ['ilocos', 'philippines', 'philippine']
# Headlines often say just "CAR". Accepted only as an UPPERCASE standalone word
# in the original text, and never as CAR-T (the cancer therapy) or "CAR T-cell".
_CAR_ACRONYM = re.compile(r'(?<![A-Za-z])CAR(?![A-Za-z\-])(?! T[- ]cell)')


# ════════════════════════════════════════════════════════════
# KINETIC LADDER -- per front, platform scale, L5 only from here
# ════════════════════════════════════════════════════════════
_NUM = (r'(?:1[0-9]|[2-9][0-9]|[1-9][0-9]{2,}|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|'
        r'seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|a dozen|dozens of|hundreds of|'
        r'dix|douze|quinze|vingt|trente|quarante|cinquante)')
LADDER = [
    (5, [r'attack on bangui', r'bangui under attack', r'assault on bangui', r'march on bangui',
         r'marchent sur bangui', r'attaque (?:de|contre) bangui', r'stormed the capital',
         r'town (?:captured|seized|overrun|falls)', r'(?:base|garrison|camp) (?:overrun|captured|falls)',
         r'falls to (?:rebels|militia|armed groups)', r'capital (?:attacked|under attack)',
         r'(?:seize|seizes|seized|capture|captures|captured|take|takes|took|overrun|overruns|overran) '
         r'(?:the |a )?(?:town|base|garrison|military camp|army camp)',
         r'prennent le contr[oô]le', r'(?:ville|base|camp|localité) (?:tombée?|prise?) ',
         r'seize[sd]? power', r'coup succeeds', r'touad[ée]ra (?:killed|ousted|overthrown|renversé)']),
    (4, [r'massacre', r'dozens (?:of )?(?:soldiers|civilians|people|troops|villagers)? ?(?:killed|dead)?',
         r'\bdozens\b', r'des dizaines', r'une dizaine', r'nombreux (?:militaires|soldats|civils) tués',
         r'(?:kill(?:s|ed|ing)?|tués?) (?:at least )?' + _NUM,
         r'(?:at least |au moins )?' + _NUM + r' (?:soldiers|troops|civilians|people|villagers|militaires|soldats|civils|personnes)',
         r'(?:at least |au moins )?' + _NUM + r' (?:\w+ )?(?:killed|dead|tués|morts)',
         r'deadliest', r'mass casualty']),
    (3, [r'attack', r'attaque', r'ambush', r'embuscade', r'clash', r'affrontement', r'combats', r'killed',
         r'tués?', r'raid', r'kidnapp', r'enlev', r'massacres?', r'violente', r'violence']),
    (2, [r'threat', r'threaten', r'menace', r'warns', r'claims?', r'revendique', r'pressure', r'pression',
         r'tension', r'craintes', r'fears']),
]
_LADDER_RX = [(lv, [re.compile(p) for p in pats]) for lv, pats in LADDER]


# ════════════════════════════════════════════════════════════
# TRIPWIRES -- red lines. BREACHED / APPROACHING; they do NOT open L5.
# ════════════════════════════════════════════════════════════
TRIPWIRES = {
    'capital_attacked': {
        'patterns': ['attack on bangui', 'bangui under attack', 'march on bangui', 'marchent sur bangui',
                     'attaque de bangui', 'attaque contre bangui'],
        'severity': 'surge',
        'note': 'The CPC offensive on Bangui in January 2021 is the precedent.',
    },
    'regime_change_event': {
        'patterns': ['touadéra ousted', 'touadera ousted', 'touadéra renversé', 'coup in bangui',
                     "coup d'état à bangui", 'seizes power in bangui', 'touadera killed'],
        'severity': 'surge',
        'note': 'An ACTUAL change of regime, not a rumour or an announced plot.',
    },
    'mass_casualty_event': {
        'patterns': ['massacre', 'deadliest', 'dozens of civilians', 'dozens of soldiers', 'des dizaines de'],
        'severity': 'high',
        'note': 'Massacres in the south-east and north-west are the class.',
    },
    'peacekeepers_attacked': {
        'patterns': ['casques bleus blessés', 'casque bleu tué', 'casques bleus tués', 'peacekeeper killed',
                     'peacekeepers killed', 'peacekeepers wounded', 'attack against peacekeepers',
                     'attaque contre la minusca'],
        'severity': 'high',
        'note': 'Three peacekeepers were wounded in a July 2026 attack; Haut-Mbomou is the usual setting.',
    },
    'russian_guard_change': {
        'patterns': ['prendre le relais de wagner', 'take over from wagner', 'takes over from wagner',
                     'replace wagner', 'remplacer wagner', 'wagner withdraw', 'retrait de wagner',
                     'wagner leaves', 'wagner quitte'],
        'severity': 'elevated',
        'note': 'A change in WHO guards the president. Read the guard axis: the reporting conflicts.',
    },
    'russian_withdrawal': {
        'patterns': ['russian forces withdraw', 'russia withdraws', 'retrait des forces russes',
                     'russia pulls out', 'russian troops leave'],
        'severity': 'high',
        'note': 'Russia leaving CAR would end the model where it began.',
    },
    'minusca_drawdown': {
        'patterns': ['réduit ses effectifs', 'reduces its troops', 'troop cuts', 'premature exit',
                     'retrait de la minusca', 'minusca drawdown', 'drawdown'],
        'severity': 'elevated',
        'note': 'Renewed to 15 Nov 2027 with troop levels reduced; each base closure shifts security to FACA and the Russians.',
    },
    'mine_disaster': {
        'patterns': ['mine collapse', 'collapse kills', 'éboulement', "effondrement d'une mine",
                     'gold mine collapses'],
        'severity': 'elevated',
        'note': 'An artisanal gold-mine collapse killed at least 49 in August 2026.',
    },
    'corridor_blocked': {
        'patterns': ['truck blockade', 'trucks stranded', 'camions bloqués', 'grève des camionneurs',
                     'pénurie de carburant', 'fuel shortage', 'corridor bloqué'],
        'severity': 'elevated',
        'note': 'The Douala road is the lifeline: 100+ trucks stranded at Garoua-Boulaï in October 2026.',
    },
    'sudan_spillover': {
        'patterns': ['rapid support forces', 'forces de soutien rapide', 'fsr', 'janjaweed',
                     'incursion soudanaise', 'sudanese incursion'],
        'severity': 'high',
        'note': "Sudan's war reaching into Vakaga; Am Dafok was attacked on 1 July 2026.",
    },
    'opposition_crackdown': {
        'patterns': ['passport seized', 'seizure of his passport', 'empêché de voyager', 'privé de sa nationalité',
                     'opposition leader arrested', "arrestation de l'opposant", 'meeting interdit'],
        'severity': 'elevated',
        'note': "Dologuélé's passport was seized at Bangui airport in May 2026.",
    },
    'sanctions_designation': {
        'patterns': ['sanctions wagner', 'treasury sanctions', 'sanctions two', 'targets wagner-linked',
                     'ofac', 'sanctionne'],
        'severity': 'elevated',
        'note': 'US and EU designations of Wagner-linked CAR firms (gold, diamonds, timber).',
    },
}


# ════════════════════════════════════════════════════════════
# FEEDS -- EN + FR
# ════════════════════════════════════════════════════════════
RSS_FEEDS = {
    'gn_en': {'url': ('https://news.google.com/rss/search?q=%22Central+African+Republic%22+when:7d&hl=en-US&gl=US&ceid=US:en'),
              'name': 'GoogleNews-EN', 'weight': 0.85, 'language': 'en', 'aggregator': True},
    'gn_fr': {'url': ('https://news.google.com/rss/search?q=Centrafrique+when:7d&hl=fr&gl=FR&ceid=FR:fr'),
              'name': 'GoogleNews-FR', 'weight': 0.85, 'language': 'fr', 'aggregator': True},
    'gn_russia': {'url': ('https://news.google.com/rss/search?q=Centrafrique+(Wagner+OR+%22Africa+Corps%22+OR+Russie)'
                          '+when:7d&hl=fr&gl=FR&ceid=FR:fr'),
                  'name': 'GoogleNews-Russia', 'weight': 0.85, 'language': 'fr', 'aggregator': True},
    'gn_fronts': {'url': ('https://news.google.com/rss/search?q=Centrafrique+(attaque+OR+Zemio+OR+Vakaga+OR+Ouham+OR+MINUSCA)'
                          '+when:7d&hl=fr&gl=FR&ceid=FR:fr'),
                  'name': 'GoogleNews-Fronts', 'weight': 0.85, 'language': 'fr', 'aggregator': True},
    'gn_resources': {'url': ('https://news.google.com/rss/search?q=%22Central+African+Republic%22+(gold+OR+diamonds+OR+Rwanda+OR+UAE)'
                             '+when:7d&hl=en-US&gl=US&ceid=US:en'),
                     'name': 'GoogleNews-Resources', 'weight': 0.85, 'language': 'en', 'aggregator': True},
    'rfi_af':   {'url': 'https://www.rfi.fr/fr/afrique/rss', 'name': 'RFI Afrique',
                 'weight': 0.95, 'language': 'fr'},
    'apa':      {'url': 'https://www.apanews.net/feed/', 'name': 'APA News', 'weight': 0.9, 'language': 'fr'},
    'reliefweb': {'url': 'https://reliefweb.int/country/caf/rss.xml', 'name': 'ReliefWeb CAF',
                  'weight': 1.0, 'language': 'en'},
}
GDELT_QUERIES_EN = [
    '"Central African Republic" AND ("Touadera" OR "Bangui")',
    '"Central African Republic" AND ("Wagner" OR "Africa Corps" OR "Russia")',
    '"Central African Republic" AND ("rebels" OR "attack" OR "MINUSCA")',
    '"Central African Republic" AND ("gold" OR "diamonds" OR "Rwanda")',
]
GDELT_QUERIES_FR = [
    '"Centrafrique" ET ("Touadéra" OU "Bangui" OU "Wagner")',
    '"Centrafrique" ET ("attaque" OU "MINUSCA" OU "or")',
]
NEWSAPI_QUERIES = ['"Central African Republic" Touadera', '"Central African Republic" Wagner',
                   '"Central African Republic" rebels attack', '"Central African Republic" gold',
                   'Centrafrique Bangui']
BRAVE_QUERIES = ['Central African Republic Bangui 2026', 'Centrafrique Touadéra', 'Central African Republic Wagner Africa Corps']


# ════════════════════════════════════════════════════════════
# VALIDATION -- MEASURED by test_car_harness.py on the 22 Nov 2026 corpus
# ════════════════════════════════════════════════════════════
# Measured 22 Nov 2026 by test_car_harness.py: 53 verbatim 2026 headlines (EN + FR)
# and 10 negative controls. validated = 2+ real headlines matched; thin = 1;
# unvalidated = 0 (excluded from its vector, reads unread, never calm).
ACTOR_VALIDATION = {
    'touadera_govt':         {'status': 'validated', 'real_headlines_matched': 5},
    'opposition_repression': {'status': 'validated', 'real_headlines_matched': 3},
    'front_northwest':       {'status': 'thin', 'real_headlines_matched': 1,
                              'note': 'North-west coverage in 2026 was sparse and tends to name towns '
                                      '(Bocaranga, Paoua, Bozoum); those are in the list. Thin, not quiet.'},
    'front_southeast':       {'status': 'validated', 'real_headlines_matched': 6},
    'front_northeast':       {'status': 'validated', 'real_headlines_matched': 6},
    'attacks_unplaced':      {'status': 'validated', 'real_headlines_matched': 5},
    'russia_axis_car':       {'status': 'validated', 'real_headlines_matched': 11},
    'rwanda_axis':           {'status': 'validated', 'real_headlines_matched': 5},
    'uae_gold':              {'status': 'validated', 'real_headlines_matched': 4},
    'us_axis':               {'status': 'validated', 'real_headlines_matched': 2},
    'china_axis':            {'status': 'unvalidated', 'real_headlines_matched': 0,
                              'note': 'No CAR-specific China headline in the 2026 harvest. UNTESTED: the China '
                                      'spoke reads unread until real coverage validates it.'},
    'france_axis':           {'status': 'unvalidated', 'real_headlines_matched': 0,
                              'note': 'France appears in CAR coverage mostly as the MINUSCA penholder; no '
                                      'France-led headline in the harvest.'},
    'minusca':               {'status': 'validated', 'real_headlines_matched': 5},
    'chad_axis':             {'status': 'unvalidated', 'real_headlines_matched': 0,
                              'note': 'No Chad-led CAR headline in the 2026 harvest.'},
    'mineral_economy':       {'status': 'validated', 'real_headlines_matched': 7},
    'fuel_corridor':         {'status': 'validated', 'real_headlines_matched': 3},
}
VALIDATION_AS_OF = '2026-11-22'
VALIDATION_CORPUS_NOTE = (
    '53 verbatim 2026 CAR headlines (EN and FR) + 10 negative controls (Bangui in the Philippines, '
    '"Central Africa" the region, the CFA franc, CAR-T cell therapy, Wagner in Mali, Sudan and DRC '
    'stories). Country gate: 52/53 passed, 0/10 negative-control leaks. Guard axis on the year: '
    'contested (2 outlets Wagner-held, 3 handover).')


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
        print('[CAR Rhetoric] redis get %s: %s' % (key, str(e)[:100]))
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
        print('[CAR Rhetoric] redis set %s: %s' % (key, str(e)[:100]))
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
        print('[CAR Rhetoric] redis lpush %s: %s' % (key, str(e)[:100]))
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
            # v1.0.0 OUTLET FIX: Google News carries many outlets under one feed
            # name; read the real outlet from the " - Outlet" suffix so the
            # two-outlet rule counts newspapers, not feeds.
            if cfg.get('aggregator') and ' - ' in title:
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
        print('[CAR Rhetoric] RSS %s: %s' % (feed_id, str(e)[:100]))
    return out


def fetch_all_rss():
    out = []
    for fid, cfg in RSS_FEEDS.items():
        got = fetch_rss(fid, cfg)
        if got:
            print('[CAR Rhetoric] RSS %s: %d' % (fid, len(got)))
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
    print('[CAR Rhetoric] GDELT: %d' % len(out))
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
        print('[CAR Rhetoric] NewsAPI: %d' % len(out))
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
        print('[CAR Rhetoric] Brave: %d' % len(out))
    return out


# ════════════════════════════════════════════════════════════
# GATE + CLASSIFY
# ════════════════════════════════════════════════════════════
def _body(article):
    return _norm(article.get('title', '')) + ' ' + _norm(article.get('description', ''))


def passes_country_gate(article):
    """True when the article is about the Central African REPUBLIC.

    1. A CAR place, person or institution, or the country's name -> pass.
    2. "Bangui" alone passes only without Philippine context (Bangui, Ilocos
       Norte, has a famous wind farm).
    3. "Central Africa" / "Central African" alone (the region, the CFA franc,
       CEMAC) does NOT pass.
    """
    body = _body(article)
    if any(_kw_in(t, body) for t in STRONG_TOKENS):
        return True, 'country'
    if _CAR_ACRONYM.search('%s %s' % (article.get('title', ''), article.get('description', ''))):
        return True, 'country'
    if _BANGUI.search(body):
        if any(t in body for t in PHILIPPINES_CONTEXT):
            return False, 'philippines'
        return True, 'country'
    if 'central africa' in body:
        return False, 'region'
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
        return {'available': False, 'note': 'Humanitarian sensor key absent this cycle -- unread, not calm.'}
    stats = {}
    for s in (h.get('headline_stats') or []):
        lab = (s.get('label') or '').lower()
        if 'abroad' in lab:
            stats['refugees_abroad'] = s.get('value')
        elif lab.startswith('internally displaced'):
            stats['idps'] = s.get('value')
        elif 'sudanese' in lab:
            stats['sudanese_hosted'] = s.get('value')
        elif 'need' in lab:
            stats['people_in_need'] = s.get('value')
    cal = h.get('seasonal_calendar') or {}
    return {'available': True, **stats, 'seasonal_open': cal.get('open_now') or [],
            'data_as_of': h.get('data_as_of')}


def _read_commodity_context():
    """CONTEXT ONLY (not scored): gold price for display."""
    try:
        from commodity_proxy_africa import get_africa_commodity_data
    except ImportError:
        return {'available': False, 'reason': 'commodity proxy not importable'}
    try:
        d = get_africa_commodity_data('car') or {}
        out = {'available': False, 'scored': False}
        for t in (d.get('commodity_summaries') or []):
            if t.get('commodity') in ('gold', 'diamonds'):
                sp = t.get('sparkline') or {}
                out[t['commodity']] = {'price': sp.get('price'), 'change_pct_1d': sp.get('change_pct_1d'),
                                       'change_pct_30d': sp.get('change_pct_30d')}
                out['available'] = True
        return out
    except Exception as e:
        return {'available': False, 'reason': str(e)[:120]}


def _read_crosstheater_amplifiers():
    amps = {}
    for label, key in (('russia_fingerprint', 'crosstheater:russia:fingerprint'),
                       ('sudan_fingerprint', 'crosstheater:sudan:fingerprint'),
                       ('niger_fingerprint', 'crosstheater:niger:fingerprint')):
        v = _redis_get(key)
        if v:
            amps[label] = v
    return amps


# ════════════════════════════════════════════════════════════
# WHO GUARDS THE PRESIDENT
# ════════════════════════════════════════════════════════════
def _guard_axis(russia_articles):
    """Reads the Russia articles for WHICH Russia guards Touadéra.

    Each state counts DISTINCT OUTLETS whose headline/summary matches it.
    wagner_held and handover both reported -> 'contested' (the 2026 norm).
    Nothing matched -> 'unread' (never 'stable')."""
    hits = {k: {} for k in GUARD_PATTERNS}
    for a in russia_articles:
        body = _norm('%s %s' % (a.get('title', ''), a.get('description', '')))
        for state, pats in GUARD_PATTERNS.items():
            if any(p in body for p in pats):
                hits[state].setdefault((a.get('source') or '?').lower(), a)
    n = {k: len(v) for k, v in hits.items()}
    ev = {k: [{'title': a.get('title', '')[:160], 'source': a.get('source', ''), 'url': a.get('url', '')}
              for a in list(v.values())[:3]] for k, v in hits.items()}
    if n['thinning'] >= 2:
        state = 'thinning'
        reading = ('Two or more outlets report Russian forces withdrawing or pulling out. If it holds, the model '
                   'that began in CAR in 2018 is ending where it started.')
    elif n['wagner_held'] and n['handover']:
        state = 'contested'
        reading = ('Reporting conflicts: some outlets say Wagner still holds the guard, others that Africa Corps '
                   'is taking over. Contested is itself the finding -- Moscow has not yet brought its own '
                   'mercenaries to heel in its oldest African client.')
    elif n['handover'] >= 2:
        state = 'handover_reported'
        reading = ('Two or more outlets report Africa Corps taking over from Wagner. The guarantee is being '
                   'nationalised: Moscow, not a private network, would hold the presidency\'s security -- '
                   'and has asked to be paid in cash rather than concessions.')
    elif n['wagner_held'] >= 2:
        state = 'wagner_held'
        reading = ('Two or more outlets report Wagner (the Prigozhin network) still guarding the president and '
                   'resisting replacement by Africa Corps.')
    elif sum(n.values()):
        state = 'thin'
        reading = 'One outlet only on who guards the president this window: held as thin, not as a finding.'
    else:
        state = 'unread'
        reading = 'No reporting this window on who guards the president. Unread, not stable.'
    return {'id': 'guard_axis_car', 'state': state, 'outlets': n, 'evidence': ev, 'reading': reading,
            'friction_reported': n['friction'] > 0,
            'states_defined': ['wagner_held', 'contested', 'handover_reported', 'thinning', 'thin', 'unread'],
            'watch': ['Any change in the presidential guard (who stands behind Touadéra in public)',
                      'Whether Bangui pays Africa Corps in cash (reported ask: ~$15M a month)',
                      'Concessions (gold, timber) moving between Wagner-linked and state-linked companies',
                      'Wagner–Africa Corps friction in the field (the Haut-Mbomou campaign)']}


# ════════════════════════════════════════════════════════════
# PROSE -- estimative voice, builtin (no Claude call). GPI-safe signals.
# ════════════════════════════════════════════════════════════
TRIPWIRE_SIG_LEVEL = {'surge': 4, 'high': 3, 'elevated': 2}
TRIPWIRE_AXIS = {
    'capital_attacked': 'kinetic', 'regime_change_event': 'governance', 'mass_casualty_event': 'kinetic',
    'peacekeepers_attacked': 'kinetic', 'russian_guard_change': 'diplomatic', 'russian_withdrawal': 'diplomatic',
    'minusca_drawdown': 'diplomatic', 'mine_disaster': 'humanitarian', 'corridor_blocked': 'economic',
    'sudan_spillover': 'kinetic', 'opposition_crackdown': 'governance', 'sanctions_designation': 'economic',
}
ACTOR_AXIS = {
    'touadera_govt': 'governance', 'opposition_repression': 'governance',
    'russia_axis_car': 'diplomatic', 'rwanda_axis': 'diplomatic', 'uae_gold': 'economic',
    'us_axis': 'diplomatic', 'china_axis': 'economic', 'france_axis': 'diplomatic', 'minusca': 'diplomatic',
    'chad_axis': 'diplomatic', 'mineral_economy': 'economic', 'fuel_corridor': 'economic',
}
SIG_COLOR = {0: '#6b7280', 1: '#3b82f6', 2: '#f59e0b', 3: '#f97316', 4: '#ef4444', 5: '#7c3aed'}


def _prose(theatre_level, fronts, actor_summaries, tripwires, guard):
    sigs = []
    for t in tripwires[:4]:
        tid = t.get('id', 'tripwire')
        lv = TRIPWIRE_SIG_LEVEL.get(t.get('severity'), 2)
        sigs.append({'level': lv, 'severity': t.get('severity'), 'type': 'tripwire', 'priority': 10,
                     'category': 'tripwire', 'pressure_type': TRIPWIRE_AXIS.get(tid, 'kinetic'),
                     'theatre': 'car', 'icon': '🚨', 'color': SIG_COLOR[lv],
                     'short_text': '%s CAR red line: %s' % (FLAG, tid.replace('_', ' ')),
                     'long_text': (TRIPWIRES.get(tid) or {}).get('note', '')})
    for fid, f in fronts.items():
        if f['level'] >= 3:
            sigs.append({'level': f['level'], 'type': 'front', 'priority': 9,
                         'category': 'kinetic_front', 'pressure_type': 'kinetic',
                         'standing': bool(f.get('standing')), 'front': fid,
                         'theatre': 'car', 'icon': '💥', 'color': SIG_COLOR.get(f['level'], '#6b7280'),
                         'short_text': '%s CAR %s at L%d%s' % (
                             FLAG, f['name'], f['level'], ' (standing insurgency)' if f.get('standing') else ''),
                         'long_text': ('Worst report: "%s" (%s). %d outlets at this rung.%s'
                                       % ((f.get('worst') or {}).get('title', '')[:140],
                                          (f.get('worst') or {}).get('source', ''), f['outlets_at_level'],
                                          ' A standing insurgency: fighting here is the condition, not news.'
                                          if f.get('standing') else ''))})
    for aid in ('russia_axis_car', 'rwanda_axis', 'uae_gold', 'minusca', 'mineral_economy', 'fuel_corridor',
                'opposition_repression', 'us_axis', 'china_axis'):
        s = actor_summaries.get(aid) or {}
        if s.get('level') in ('elevated', 'high', 'surge'):
            ta = (s.get('top_articles') or [{}])[0]
            lv = LEVEL_TO_PLATFORM.get(s['level'], 2)
            sigs.append({'level': lv, 'type': 'actor_signal', 'priority': 7,
                         'category': 'actor_signal', 'pressure_type': ACTOR_AXIS.get(aid, 'diplomatic'),
                         'theatre': 'car', 'icon': ACTORS[aid]['icon'], 'color': SIG_COLOR.get(lv, '#6b7280'),
                         'short_text': '%s CAR %s at %s' % (FLAG, ACTORS[aid]['name'], s['level'].upper()),
                         'long_text': '"%s" (%s)' % (ta.get('title', '')[:160], ta.get('source', ''))})
    if guard['state'] in ('contested', 'handover_reported', 'thinning', 'wagner_held'):
        sigs.append({'level': 3 if guard['state'] == 'thinning' else 2, 'type': 'guard_axis', 'priority': 8,
                     'category': 'actor_signal', 'pressure_type': 'diplomatic', 'theatre': 'car',
                     'icon': '🐻', 'color': SIG_COLOR[2],
                     'short_text': '%s CAR who guards the president: %s' % (FLAG, guard['state'].replace('_', ' ')),
                     'long_text': guard['reading']})
    sigs.sort(key=lambda x: -x.get('priority', 0))

    hot_fronts = [f['name'] for f in fronts.values() if f['level'] >= 3]
    parts = ['The Central African Republic reads L%d (%s).' % (theatre_level, PLATFORM_LABELS.get(theatre_level, ''))]
    parts.append(('Fronts at L3 or above: %s.' % ', '.join(hot_fronts)) if hot_fronts
                 else 'No front reached L3 on two outlets this window.')
    parts.append('Who guards the president: %s.' % guard['state'].replace('_', ' '))
    parts.append('Convergence read, not prediction.')

    so_what = []
    if guard['state'] in ('contested', 'handover_reported', 'thinning'):
        so_what.append({'weight': 0.95, 'bullet': guard['reading'] + (
            ' Why it matters beyond CAR: Bangui is the template Russia exports across the Sahel; '
            'if Moscow cannot nationalise its guard here, it cannot be sure of it in Mali or Niger.')})
    if any(f['level'] >= 3 and f.get('standing') for f in fronts.values()):
        so_what.append({'weight': 0.8, 'bullet': (
            'All three fronts are standing insurgencies: fighting there is the condition, not news. What would '
            'be news is a town or base taken (L5), the fighting reaching Bangui, or the Sudan war spilling into '
            'Vakaga in force.')})
    if (actor_summaries.get('rwanda_axis') or {}).get('level') in ('elevated', 'high', 'surge'):
        so_what.append({'weight': 0.8, 'bullet': (
            'Rwanda is above baseline. Kigali is a second, smaller security guarantor beside Russia -- the same '
            'model it runs in Mozambique, from a state that UN experts say backs M23 in the DRC (Kigali denies it).')})
    if (actor_summaries.get('minusca') or {}).get('level') in ('elevated', 'high', 'surge') or \
            'minusca_drawdown' in {t.get('id') for t in tripwires}:
        so_what.append({'weight': 0.85, 'bullet': (
            'MINUSCA is in the news: renewed to Nov 2027 but with fewer troops and the UN short of cash. Every base '
            'that closes shifts security to FACA and the Russians -- watch the south-east, where peacekeepers guard '
            "Zémio's hospital.")})
    if (actor_summaries.get('uae_gold') or {}).get('level') in ('elevated', 'high', 'surge') or \
            (actor_summaries.get('mineral_economy') or {}).get('level') in ('high', 'surge'):
        so_what.append({'weight': 0.8, 'bullet': (
            'The gold economy is above baseline. CAR\'s gold mostly leaves through Dubai and pays for the guards '
            'rather than the state: a move in gold is a move in who can afford to protect the president.')})
    if 'corridor_blocked' in {t.get('id') for t in tripwires}:
        so_what.append({'weight': 0.75, 'bullet': (
            'The Douala road is disrupted. CAR imports nearly everything up that one road; a strike or ambush '
            'there reaches Bangui as fuel queues within days.')})
    if not so_what:
        so_what.append({'weight': 0.3, 'bullet': (
            'Nothing above baseline this scan. Baseline for CAR still means three standing insurgencies, a '
            'president guarded by foreigners and a single road to the sea. A quiet scan is a quiet feed, not a '
            'quiet country.')})
    so_what.sort(key=lambda b: -b['weight'])
    return sigs[:10], ' '.join(parts), so_what[:6]


# ════════════════════════════════════════════════════════════
# SCORING (fixed-corpus testable)
# ════════════════════════════════════════════════════════════
FRONT_ACTORS = ['front_northwest', 'front_southeast', 'front_northeast', 'attacks_unplaced']
_NAMED_FRONTS = {'front_northwest', 'front_southeast', 'front_northeast'}


def _gather(days):
    rss = fetch_all_rss()
    gdelt = fetch_all_gdelt(days)
    newsapi = fetch_newsapi(days)
    brave = fetch_brave(len(gdelt), len(newsapi))
    return rss, gdelt, newsapi, brave


def score_articles(articles):
    gated, rejected = [], 0
    gate_reasons = {'country': 0, 'philippines': 0, 'region': 0}
    for a in articles:
        ok, why = passes_country_gate(a)
        if ok:
            gate_reasons['country'] += 1
            gated.append(a)
        else:
            rejected += 1
            if why in gate_reasons:
                gate_reasons[why] += 1

    by_actor = {k: [] for k in ACTORS}
    for a in gated:
        cls = _classify_article(a)
        if any(aid in _NAMED_FRONTS for aid, _ in cls):
            cls = [(aid, h) for aid, h in cls if aid != 'attacks_unplaced']
        for aid, hits in cls:
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
            'wheel': meta.get('wheel'),
            'level': lvl, 'score': sc['score'], 'baseline': meta['baseline_statements_per_week'],
            'article_count': sc['article_count'], 'outlets': sc['outlets'],
            'language_breakdown': sc['language_breakdown'], 'sources': sc['sources'],
            'top_articles': sc['top_articles'], 'tripwires': sc['tripwires'],
            'source_headlines': meta.get('source_headlines', []),
            'validation': ACTOR_VALIDATION.get(aid, {'status': 'unknown'}),
        }
        for tw in sc['tripwires']:
            f = _floor.get(tw.get('severity'))
            if f and _rank(f) > _rank(actor_summaries[aid]['level']):
                actor_summaries[aid]['level'] = f
                actor_summaries[aid]['level_basis'] = 'red_line:%s' % tw['id']
            if not any(t['id'] == tw['id'] for t in tripwires):
                tripwires.append({'actor': aid, **tw})

    fronts = {}
    for aid in FRONT_ACTORS:
        lad = front_ladder(by_actor[aid])
        fronts[ACTORS[aid]['front']] = {'actor': aid, 'name': ACTORS[aid]['name'],
                                        'standing': ACTORS[aid].get('standing', False), **lad}
        actor_summaries[aid]['ladder'] = lad
    kinetic_level = max([f['level'] for f in fronts.values()] + [0])

    guard = _guard_axis(by_actor['russia_axis_car'])

    vector_levels, vector_levels_platform = {}, {}
    for vec, members in VECTOR_GROUPS.items():
        if vec == 'insurgent_fronts':
            vector_levels_platform[vec] = kinetic_level
            vector_levels[vec] = 'L%d' % kinetic_level
            continue
        measured = [m for m in members if ACTOR_VALIDATION.get(m, {}).get('status') != 'unvalidated']
        lv = [actor_summaries[m]['level'] for m in measured]
        if not lv:
            vector_levels[vec] = 'unread'
            continue
        top = max(lv, key=_rank)
        vector_levels[vec] = top
        vector_levels_platform[vec] = LEVEL_TO_PLATFORM[top]

    non_kinetic = max([v for k, v in vector_levels_platform.items() if k != 'insurgent_fronts'] + [0])
    theatre_level = max(min(non_kinetic, 4), kinetic_level)
    l5_gate = {'kinetic': kinetic_level >= 5, 'any': kinetic_level >= 5,
               'fired': [{'front': k, 'level': f['level']} for k, f in fronts.items() if f['level'] >= 5],
               'reason': ('A front ladder reached L5 on two or more outlets.' if kinetic_level >= 5 else
                          'No front ladder at L5. L5 needs a town or base taken, or Bangui attacked, reported '
                          'by two or more outlets. Tripwires and rhetoric volume cannot open it.')}
    return {'gated': gated, 'rejected': rejected, 'gate_reasons': gate_reasons,
            'actor_summaries': actor_summaries, 'tripwires': tripwires, 'fronts': fronts,
            'kinetic_level': kinetic_level, 'vector_levels': vector_levels,
            'vector_levels_platform': vector_levels_platform, 'theatre_level': theatre_level,
            'l5_gate': l5_gate, 'guard_axis': guard}


def _write_spokes(actor_summaries, theatre_level, guard, ts):
    """spoke:<hub>:car for each wheel CAR sits on."""
    written = []
    for hub, cfg in SPOKES.items():
        s = actor_summaries.get(cfg['actor']) or {}
        lvl = LEVEL_TO_PLATFORM.get(s.get('level', 'low'), 0)
        ta = (s.get('top_articles') or [{}])[0]
        if lvl >= 2 and ta.get('title'):
            top = 'CAR: %s at L%d -- "%s"' % (ACTORS[cfg['actor']]['name'], lvl, ta['title'][:110])
        elif s.get('article_count'):
            top = 'CAR: %s -- background mentions only (L%d).' % (ACTORS[cfg['actor']]['name'], lvl)
        else:
            top = 'CAR: no %s reporting this window. Unread, not calm.' % ACTORS[cfg['actor']]['name']
        payload = {'ts': ts, 'hub': hub, 'country': 'car', 'level': lvl,
                   'node_class': cfg['node_class'], 'relationship': cfg['node_class'],
                   'top_signal': top[:180], 'why': cfg['why'], 'items': s.get('article_count', 0),
                   'theatre_level': theatre_level, 'source': 'rhetoric_tracker_car v%s' % MODULE_VERSION}
        if hub == 'russia':
            payload['guard_state'] = guard['state']
            payload['guard_reading'] = guard['reading']
        if _redis_set('spoke:%s:car' % hub, payload, ttl_hours=SPOKE_TTL_HOURS):
            written.append(hub)
    if written:
        print('[CAR Rhetoric] spokes written: %s' % ', '.join(written))
    return written


def scan_car_rhetoric(force=False, days=7):
    global _last_scan_started_at
    _last_scan_started_at = datetime.now(timezone.utc)
    t0 = time.time()
    print('[CAR Rhetoric] === scan start (force=%s days=%s) ===' % (force, days))
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
    print('[CAR Rhetoric] recency gate: %s' % _recency)

    S = score_articles(articles)
    actor_summaries, tripwires, fronts = S['actor_summaries'], S['tripwires'], S['fronts']
    theatre_level, guard = S['theatre_level'], S['guard_axis']
    humanitarian = _read_humanitarian_context()
    commodity = _read_commodity_context()
    amplifiers = _read_crosstheater_amplifiers()
    top_signals, executive_summary, so_what = _prose(theatre_level, fronts, actor_summaries, tripwires, guard)

    _rl = [{'id': t.get('id'), 'actor': t.get('actor'), 'severity': t.get('severity'),
            'status': 'BREACHED' if t.get('severity') in ('surge', 'high') else 'APPROACHING',
            'note': (TRIPWIRES.get(t.get('id')) or {}).get('note', '')} for t in tripwires]
    red_lines = {'triggered': _rl,
                 'breached_count': sum(1 for r in _rl if r['status'] == 'BREACHED'),
                 'approaching_count': sum(1 for r in _rl if r['status'] == 'APPROACHING')}
    composite_score = round(sum(s['score'] for s in actor_summaries.values()), 2)
    now = datetime.now(timezone.utc).isoformat()
    spokes = {hub: {'actor': c['actor'], 'node_class': c['node_class'],
                    'level': LEVEL_TO_PLATFORM.get((actor_summaries.get(c['actor']) or {}).get('level', 'low'), 0)}
              for hub, c in SPOKES.items()}
    result = {
        'success': True, 'country': 'car', 'country_display': 'Central African Republic',
        'module': 'rhetoric_tracker_car', 'version': MODULE_VERSION, 'node_class': 'multi_wheel_spoke',
        'theatre_level': theatre_level, 'theatre_score': min(100, int(composite_score)),
        'theatre_label': PLATFORM_LABELS.get(theatre_level, 'Monitoring'),
        'composite_score': composite_score, 'kinetic_level': S['kinetic_level'], 'l5_gate': S['l5_gate'],
        'fronts': fronts, 'standing_fronts': [k for k, f in fronts.items() if f.get('standing')],
        'guard_axis': guard,
        'vector_levels': S['vector_levels'], 'vector_levels_platform': S['vector_levels_platform'],
        'vector_labels': VECTOR_LABELS, 'red_lines': red_lines, 'scan_date': now,
        'article_count': len(S['gated']), 'actor_summaries': actor_summaries,
        'actor_validation_as_of': VALIDATION_AS_OF, 'validation_corpus_note': VALIDATION_CORPUS_NOTE,
        'tripwires_global': tripwires, 'spokes': spokes,
        'humanitarian_context': humanitarian, 'commodity_context': commodity,
        'crosstheater_amplifiers': amplifiers,
        'top_signals': top_signals, 'executive_summary': executive_summary, 'so_what': so_what,
        'source_breakdown': {'rss': len(rss), 'gdelt': len(gdelt), 'newsapi': len(newsapi), 'brave': len(brave)},
        'articles_scanned': len(articles), 'articles_passed_country_gate': len(S['gated']),
        'articles_rejected_by_gate': S['rejected'], 'gate_reasons': S['gate_reasons'],
        'gate_note': ('An article must name the Central African Republic or a CAR place, person or institution. '
                      '"Central Africa" (the region) and Bangui in the Philippines do not pass.'),
        'scan_time_seconds': round(time.time() - t0, 1), 'days_analyzed': days, 'recency': _recency,
        'last_updated': now, 'cached': False,
    }
    save_cache(result)
    _write_spokes(actor_summaries, theatre_level, guard, now)
    _redis_set(FINGERPRINT_KEY, {
        'ts': now, 'theatre': 'car', 'country': 'car', 'node_class': 'multi_wheel_spoke',
        'theatre_level': theatre_level, 'kinetic_level': S['kinetic_level'],
        'fronts': {k: {'level': f['level'], 'standing': f.get('standing')} for k, f in fronts.items()},
        'spokes': spokes, 'guard_state': guard['state'], 'tripwires': tripwires[:6],
    }, ttl_hours=14)
    try:
        _redis_lpush_trim(HISTORY_KEY, {
            'scanned_at': now, 'theatre_level': theatre_level, 'kinetic_level': S['kinetic_level'],
            'red_lines_count': len(tripwires), 'guard_state': guard['state'],
            **{k: v for k, v in S['vector_levels'].items()},
        }, max_len=336)
    except Exception as e:
        print('[CAR Rhetoric] history write failed: %s' % str(e)[:100])
    print('[CAR Rhetoric] done in %ss -- L%s (kinetic L%s), guard %s, gate %d/%d'
          % (result['scan_time_seconds'], theatre_level, S['kinetic_level'], guard['state'],
             len(S['gated']), len(articles)))
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
                scan_car_rhetoric(force=True, days=7)
            finally:
                with _scan_lock:
                    _scan_running = False
            time.sleep(BACKGROUND_REFRESH_HOURS * 3600)
        except Exception as e:
            print('[CAR Rhetoric] background error: %s' % str(e)[:150])
            time.sleep(600)


def start_background_refresh():
    threading.Thread(target=_background_loop, daemon=True, name='CARRhetoricBG').start()
    print('[CAR Rhetoric] background thread started (initial delay %ss)' % INITIAL_SCAN_DELAY_SECONDS)


def register_car_rhetoric_routes(app, start_background=True):
    from flask import jsonify, request

    @app.route('/api/rhetoric/car', methods=['GET', 'OPTIONS'])
    def api_car_rhetoric():
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
                    threading.Thread(target=lambda: scan_car_rhetoric(force=True), daemon=True).start()
            return jsonify(cached)
        return jsonify(scan_car_rhetoric(force=force, days=7))

    @app.route('/api/rhetoric/car/debug', methods=['GET'])
    def api_car_rhetoric_debug():
        cached = load_cache()
        return jsonify({
            'module': 'rhetoric_tracker_car v%s' % MODULE_VERSION,
            'actors': list(ACTORS.keys()), 'vectors': list(VECTOR_GROUPS.keys()),
            'spokes': list(SPOKES.keys()), 'tripwires': list(TRIPWIRES.keys()),
            'guard_states': list(GUARD_PATTERNS.keys()),
            'l5_rule': 'Only a front kinetic ladder at L5 on two or more outlets.',
            'actor_validation': ACTOR_VALIDATION, 'validation_as_of': VALIDATION_AS_OF,
            'rss_feeds': len(RSS_FEEDS), 'redis_wired': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured': bool(NEWSAPI_KEY), 'brave_configured': bool(BRAVE_API_KEY),
            'recency_gate': _RECENCY_STATE['last'],
            'cache_present': cached is not None,
            'cache_fresh': is_cache_fresh(cached) if cached else False,
            'last_guard_state': (cached or {}).get('guard_axis', {}).get('state'),
            'last_scan_started_at': _last_scan_started_at.isoformat() if _last_scan_started_at else None,
            'background_running': _scan_running,
        })

    print('[CAR Rhetoric] endpoints registered: /api/rhetoric/car, /api/rhetoric/car/debug')
    if start_background:
        start_background_refresh()


print('[CAR Rhetoric] module loaded -- v%s' % MODULE_VERSION)
