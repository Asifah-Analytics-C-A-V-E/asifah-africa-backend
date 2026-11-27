"""
rhetoric_tracker_drc.py -- Asifah Analytics Africa Backend -- v1.0.0
27 November 2026

DEMOCRATIC REPUBLIC OF THE CONGO RHETORIC TRACKER. The analyst layer behind
drc-stability.html.

WHAT THE DRC IS, FOR THIS TRACKER
    The DRC is where the most wheels on the platform meet in one country:
    Rwanda (UN experts and the US say Kigali backs M23; Kigali denies it),
    Uganda (troops fighting the ADF by invitation), Burundi (troops in South
    Kivu), the US (broker of the Washington Accords AND partner in a
    minerals-for-security deal), China (most of the cobalt and copper mines)
    and the UAE (where the region's gold is reported to end up).

    Two peace tracks run at once -- Washington (DRC-Rwanda) and Doha (DRC-M23,
    now the FRN) -- while the fighting continues. So the tracker's signature
    read is not "how much fighting" but DEAL VS GROUND:
        holding . paper_only . fraying . collapsing . thin . unread
    "paper_only" is the 2026 norm: the deals are reported as alive while two
    or more outlets report L3+ fighting on a front the deals cover.

FIVE VECTORS (+ the epidemic)
    regime_security      Tshisekedi and the constitution; opposition and
                         repression; the FRN (Kabila's coalition, M23 inside).
    insurgent_fronts     THREE STANDING FRONTS + unplaced attacks, each on a
                         KINETIC LADDER: South Kivu, North Kivu, Ituri.
    peace_tracks         Washington, Doha, MONUSCO.
    external_alignment   Rwanda, Uganda, Burundi, the US, China, the UAE.
    resource_leverage    Cobalt and copper (Katanga); conflict gold and coltan
                         (the east).
    epidemic             Bundibugyo Ebola -- a war and an epidemic in the same
                         provinces.

RIPPLE CHAINS (Rachel's standing rule, 27 Nov 2026)
    Every actor carries a RIPPLE CHAIN: what it touches at four scales --
    the country, the region, the continent, the globe -- plus the follow-on
    questions a reader should be asking ("if China moves on cobalt: what
    else is it used in, which other minerals follow, whose supply chain
    breaks?"). Ripples are STATIC, DATED KNOWLEDGE -- they never score. They
    surface in the payload for every LIT actor (elevated or above), so the
    page answers the unasked question exactly when the actor moves. Framed
    as "what this touches", never "what will happen".

THE KINETIC LADDER -- L5 COMES ONLY FROM HERE (Niger doctrine, unchanged)
        L1 mention . L2 threat / claim . L3 attack / clash / killing
        L4 mass casualty (10+ killed, massacre, "dozens")
        L5 a town or base taken, or Kinshasa attacked
    L3 and above need TWO OR MORE distinct outlets. All three fronts are
    STANDING: L3-L4 is the condition, not news.

DISCIPLINE CARRIED IN FROM DAY ONE
    Recency gate (old Google News / Brave stories never score), outlet cap
    (one site counts for at most 2 articles per actor), the Google News
    outlet fix, and attribution: the Rwanda-M23 link is ALWAYS written as
    what UN experts and the US say, with Kigali's denial.

THE COUNTRY GATE -- "Congo" is also the Republic of the Congo (Brazzaville);
    "ADF" is also the Australian Defence Force; "DRC" can be a dispute-
    resolution centre. An article passes only if it names the DRC or a DRC
    place, person or institution.

EMITS
    rhetoric:drc:latest            full payload (12h)  <- africa_regional_bluf
    rhetoric:drc:history           rolling snapshots
    crosstheater:drc:fingerprint   slice for BLUF / GPI
    spoke:<hub>:drc                rwanda, uganda, us, china, uae wheels

ENDPOINTS
    GET /api/rhetoric/drc
    GET /api/rhetoric/drc?refresh=true      (no Claude calls; news fetch only)
    GET /api/rhetoric/drc/debug

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
    print('[DRC Rhetoric] feedparser unavailable -- RSS disabled')

MODULE_VERSION = '1.0.0'
_RECENCY_STATE = {'last': None}   # last recency-gate stats, shown on the debug route
OUTLET_CAP = 2                    # max articles per outlet per actor that add to its score

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
NEWSAPI_KEY   = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY')

CACHE_TTL_HOURS            = 12
BACKGROUND_REFRESH_HOURS   = 12
INITIAL_SCAN_DELAY_SECONDS = 330   # staggered behind Burkina (150s), Niger (210s), CAR (270s)

REDIS_KEY_LATEST = 'rhetoric:drc:latest'
HISTORY_KEY      = 'rhetoric:drc:history'
FINGERPRINT_KEY  = 'crosstheater:drc:fingerprint'
HUMANITARIAN_KEY = 'africa:humanitarian:drc'
SPOKE_TTL_HOURS  = 30

GDELT_BASE_URL   = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI_BASE_URL = 'https://newsapi.org/v2/everything'
BRAVE_BASE_URL   = 'https://api.search.brave.com/res/v1/news/search'

CACHE_FILE = '/tmp/drc_rhetoric_cache.json'

_scan_running = False
_scan_lock = threading.Lock()
_last_scan_started_at = None

FLAG = '\U0001F1E8\U0001F1E9'


# ════════════════════════════════════════════════════════════
# ACTORS -- 19 actors / 6 vectors
# Every keyword traces to a verbatim 2025-26 headline (harvested 27 Nov 2026).
# French matters: Kinshasa's press (Actualite.cd, Radio Okapi, 7sur7) and
# allAfrica's francophone wire publish in French first.
# ════════════════════════════════════════════════════════════
ACTORS = {
    # ── VECTOR: regime_security ──────────────────────────────
    'tshisekedi_govt': {
        'name': 'Tshisekedi government', 'flag': FLAG, 'icon': '\U0001F3DB️', 'color': '#e2e8f0',
        'role': 'The presidency -- the constitution, the referendum law, the war file',
        'description': ('Félix Tshisekedi, in his second and constitutionally last term (to 2028). A new '
                        'referendum law (No. 26/045, promulgated 9-10 Nov 2026) widens who can call a '
                        'referendum; the opposition says it opens the way to a third term, which he has '
                        'not declared.'),
        'vector': 'regime_security',
        'keywords': ['tshisekedi', 'gouvernement congolais', 'congolese government', 'kinshasa government',
                     'révision constitutionnelle', 'revision de la constitution', 'constitutional change',
                     'constitutional changes', 'third term', 'troisième mandat', '3e mandat', 'référendum',
                     'referendum law', 'new constitution'],
        'source_headlines': [
            '2026-11-13 Process for changing constitution officially starts in DR Congo amid criticism (New Times)',
            'DR Congo leader opens way for third term under new constitution (Ahram Online)',
            'RDC: le référendum, une voie incertaine vers un 3e mandat de Tshisekedi (Le360)',
            'Tshisekedi faces uncertain path to a third term (The Standard)',
            "2026-08-25 DRC's constitutional battle: The fight over the 2028 vote (Al Jazeera)",
        ],
        'baseline_statements_per_week': 4,
    },
    'opposition_repression': {
        'name': 'Opposition & repression', 'flag': FLAG, 'icon': '\U0001F5F3️', 'color': '#f97316',
        'role': 'The C64 coalition, protests, arrests, banned marches',
        'description': ('The Article 64 Coalition (Fayulu, Katumbi and others) rejects both a third term and '
                        'armed rebellion; protests in June and September 2026 ended in arrests and deaths. '
                        "Read as the state's pressure on its rivals, not as opposition strength."),
        'vector': 'regime_security',
        'keywords': ["l'opposition", 'opposition leaders', 'opposition congolaise', 'congolese opposition',
                     'c64', 'katumbi', 'fayulu', 'manifestation', 'mobilisation', 'réprimée',
                     'protesters', 'opposition rejette', 'coup d\'état constitutionnel', 'constitutional coup'],
        'source_headlines': [
            "2026-10-28 Congolese opposition leaders condemn Tshisekedi's push for constitutional changes (New Times)",
            "2026-06-12 À Kinshasa, une manifestation de l'opposition réprimée dans le sang (La Libre)",
            "2026-07-09 RDC : l'opposition promet une \"mobilisation\" contre une révision de la Constitution (DH / AFP)",
            "2026-10-28 RDC: l'opposition rejette tout changement constitutionnel et réclame un dialogue avec Tshisekedi et Kabila (Koaci)",
        ],
        'baseline_statements_per_week': 2,
    },
    'frn_m23': {
        'name': 'FRN (Kabila) & M23', 'flag': '\U0001F3F4', 'icon': '⚔️', 'color': '#dc2626',
        'role': "The armed challenge to the state -- Kabila's coalition with M23/AFC inside it",
        'description': ('The Front for the Refoundation of the Nation, launched by Joseph Kabila in Goma on '
                        '12 Oct 2026, absorbed the AFC/M23 political-military structure and says it inherits '
                        'its Doha commitments. Kabila was sentenced to death in absentia in September 2025. '
                        'This actor reads the movement\'s POLITICS (statements, leadership, defections); its '
                        'fighting is read on the front ladders.'),
        'vector': 'regime_security',
        'keywords': ['frn', 'front pour la refondation', 'refoundation of the nation', 'kabila', 'm23', 'afc/m23',
                     'afc-m23', 'nangaa', 'bisimwa', 'willy ngoma', 'rebel coalition'],
        'source_headlines': [
            '2026-10-13 Former DR Congo President Kabila joins M23 rebels in a new coalition (Al Jazeera)',
            "2026-10-14 Ex-DRC President Kabila's alliance with M23 rebels: Why it matters (Al Jazeera)",
            "2026-11-11 Congo-Kinshasa: Offensive armée du FRN - Kabila passe de la menace à l'acte (allAfrica)",
            "Kabila's war: rebels push west in Congo as Washington turns on Rwanda (SOFREP)",
            "Fierce fighting in Kivu after reported death of M23's Willy Ngoma (Daily Monitor)",
        ],
        'baseline_statements_per_week': 5,
    },

    # ── VECTOR: insurgent_fronts (levels come from the KINETIC LADDER) ──
    'front_south_kivu': {
        'name': 'South Kivu front', 'flag': '\U0001F3F4', 'icon': '\U0001F4A5', 'color': '#dc2626',
        'role': 'The FRN offensive (Kalehe), the highlands (Minembwe), the Ruzizi Plain and Uvira',
        'description': ('The FRN opened an offensive in Kalehe on 6 Nov 2026 through Kahuzi-Biega park and '
                        'along the RN3 (Bunyakiri taken 8-9 Nov). The FRN-aligned Twirwaneho fight the army '
                        'and Wazalendo around Minembwe; Burundian troops hold Uvira. Standing insurgency.'),
        'vector': 'insurgent_fronts', 'front': 'south_kivu', 'standing': True,
        'keywords': ['sud-kivu', 'south kivu', 'kalehe', 'bunyakiri', 'bulambika', 'bitale', 'kahuzi-biega',
                     'minembwe', 'twirwaneho', 'uvira', 'ruzizi', 'fizi', 'walungu', 'mwenga', 'kabare',
                     'shabunda', 'bukavu', 'kamanyola', 'baraka'],
        'source_headlines': [
            '2026-11-10 Congo-Kinshasa: Offensive des combattants du FRN au Sud-Kivu, plusieurs localités tombent sous leur contrôle (allAfrica)',
            'RDC : le FRN de Joseph Kabila gagne du terrain au Sud-Kivu, les FARDC préparent la riposte (Afrik)',
            "Sud-Kivu : l'offensive du FRN chasse les malades de l'hôpital de Bunyakiri (Afrik)",
            "RDC: offensive du FRN qui progresse de plusieurs dizaines de kilomètres dans l'est (Le360)",
            "2025-12 Congo-Kinshasa: Après la prise d'Uvira, le M23 poursuit son avancée vers le sud (allAfrica)",
            'Twirwaneho denounces Burundian forces over hostage-taking, bombings in South Kivu (New Times)',
        ],
        'baseline_statements_per_week': 4,
    },
    'front_north_kivu': {
        'name': 'North Kivu front', 'flag': '\U0001F3F4', 'icon': '\U0001F4A5', 'color': '#ef4444',
        'role': 'Goma (FRN-held), Masisi, Rutshuru, Walikale, Lubero, Beni',
        'description': ('Goma has been held by M23, now inside the FRN, since January 2025. Masisi, Rutshuru '
                        'and Walikale are contested between the FRN and the army, Wazalendo and the FDLR; in '
                        'the north (Beni, Lubero) the ADF attacks civilians. Ebola\'s second province. '
                        'Standing insurgency.'),
        'vector': 'insurgent_fronts', 'front': 'north_kivu', 'standing': True,
        'keywords': ['nord-kivu', 'north kivu', 'masisi', 'rutshuru', 'walikale', 'goma', 'sake', 'kibati',
                     'kashebere', 'rubaya', 'ngungu', 'lubero', 'butembo', 'beni', 'bwito', 'kitshanga',
                     'nyiragongo', 'wazalendo'],
        'source_headlines': [
            '2026-10-07 Congo-Kinshasa: Poursuite des combats AFC/M23-FARDC/Wazalendo à Masisi (allAfrica)',
            "2026-11-06 Congo-Kinshasa: Les combats s'intensifient entre les FARDC et le FRN sur l'axe Kashebere-Kibati au Nord-Kivu (allAfrica)",
            "2026-09-28 Congo-Kinshasa: Des frappes aériennes attribuées à l'AFC/M23 visent des positions des Wazalendo à Masisi (allAfrica)",
            '2026-09-08 Congo-Kinshasa: Nouvelles vagues des déplacés après des combats M23-FARDC à Masisi et Walikale (allAfrica)',
            'Walikale: FRN attack on Luola-Kisimba, Congo army (Rio Times)',
            '2026-06-29 Nord-Kivu - La coalition FARDC-Wazalendo progresse vers Ngungu et Rubaya (allAfrica)',
        ],
        'baseline_statements_per_week': 4,
    },
    'front_ituri': {
        'name': 'Ituri front', 'flag': '\U0001F3F4', 'icon': '\U0001F4A5', 'color': '#b91c1c',
        'role': 'The ADF and CODECO against civilians; the Ebola epicentre',
        'description': ('The ADF (pledged to Islamic State) and the CODECO militia attack villages and '
                        'displacement sites; Ugandan troops fight the ADF alongside the Congolese army. Ituri '
                        'holds 7,946 of the 11,613 confirmed Ebola cases (WHO, 17 Nov 2026). Standing insurgency.'),
        'vector': 'insurgent_fronts', 'front': 'ituri', 'standing': True,
        'keywords': ['ituri', 'bunia', 'djugu', 'irumu', 'mambasa', 'biakato', 'mahagi', 'codeco', 'urdpc',
                     'crp', 'walese vonkutu', 'komanda'],
        'source_headlines': [
            '2026-04-02 At least 43 people killed in ADF attack in northeast DR Congo, army says (Al Jazeera)',
            '2026-07-24 Congo-Kinshasa: Est du pays - Au moins 18 civils tués dans une nouvelle attaque du groupe ADF en Ituri (allAfrica)',
            '2026-11-14 DR Congo: At least 44 dead in attack by Islamic State-linked gunmen (Africanews)',
            '2026-10-11 Congo-Kinshasa: 11 civils tués dans une attaque attribuée à la CODECO à Djugu (allAfrica)',
            "2026-05-09 RDC: 69 morts en Ituri après une attaque sanglante de la milice CODECO (Koaci)",
            "2026-05-08 Congo-Kinshasa: Environ 15 civils tués lors d'une attaque des ADF à Biakato (Ituri) (allAfrica)",
        ],
        'baseline_statements_per_week': 4,
    },
    'attacks_unplaced': {
        'name': 'Attacks (front not named)', 'flag': '\U0001F3F4', 'icon': '❓', 'color': '#94a3b8',
        'role': 'Kinetic reporting that does not say where',
        'description': ('Attacks and casualties reported without a named front. Kept separate so a vague '
                        'headline is not silently credited to the wrong front; it still counts on the '
                        'kinetic ladder.'),
        'vector': 'insurgent_fronts', 'front': 'unplaced', 'standing': False,
        'keywords': ['islamic state-linked', 'is-linked', 'adf rebels', 'allied democratic forces', 'fardc',
                     'congolese army', 'armée congolaise', 'attack', 'attaque', 'killed', 'tués', 'clashes',
                     'affrontements', 'combats', 'drone strike', 'frappes'],
        'source_headlines': [
            '2026-11-14 DR Congo: At least 44 dead in attack by Islamic State-linked gunmen (Africanews)',
            'Islamic State group-affiliated rebels kill at least 22 in eastern region (Gleaner / AP, 12 Nov 2026)',
            "2026-06-04 Plus de 300 civils tués en cinq mois à la suite des attaques des ADF en Ituri et au Nord-Kivu (allAfrica)",
        ],
        'baseline_statements_per_week': 3,
    },

    # ── VECTOR: peace_tracks ──────────────────────────────────
    'washington_track': {
        'name': 'Washington Accords (DRC–Rwanda)', 'flag': '\U0001F1FA\U0001F1F8', 'icon': '\U0001F58A️', 'color': '#60a5fa',
        'role': 'The US-brokered state-to-state track -- FDLR vs "defensive measures"',
        'description': ('Peace agreement 27 Jun 2025; Washington Accords signed 4 Dec 2025. Stuck on two '
                        'commitments: neutralising the FDLR and Rwanda lifting its "defensive measures", with '
                        'no shared standard for compliance. Joint security mechanism met in Jul, Aug and Sep '
                        '2026; Geneva talks reported for 19 Nov 2026.'),
        'vector': 'peace_tracks',
        'keywords': ['washington accords', 'washington peace', 'accord de washington', 'accords de washington',
                     'peace deal', 'accord de paix', 'joint security coordination', 'mécanisme conjoint',
                     'defensive measures', 'mesures défensives', 'fdlr', 'peace process'],
        'source_headlines': [
            '2026-11-18 Rwanda and DRC: What is holding up the Washington peace process? (Al Jazeera)',
            'Rwanda, DR Congo agree on new mechanisms to monitor Washington Accords (New Times)',
            '2026-09 US commends Rwanda for delivering as Kinshasa dodges peace deal (KT Press)',
            '2026-09-05 Signing DR Congo peace one thing, delivery another (eNCA)',
            '2026-04-08 Accord de paix de Washington - Un bilan mitigé neuf mois après la signature entre la RDC et le Rwanda (allAfrica)',
        ],
        'baseline_statements_per_week': 3,
    },
    'doha_track': {
        'name': 'Doha track (DRC–FRN/M23)', 'flag': '\U0001F1F6\U0001F1E6', 'icon': '\U0001F91D', 'color': '#a78bfa',
        'role': 'The Qatar-facilitated government-rebel track',
        'description': ('Framework signed 15 Nov 2025; a road map and review mechanism agreed in Aug 2026 with '
                        'Qatar, the US, Togo, the AU Commission and Switzerland. The FRN says it inherits the '
                        'AFC/M23 commitments and wants the constitutional question on the agenda.'),
        'vector': 'peace_tracks',
        'keywords': ['doha', 'qatar', 'qatari', 'accord-cadre', 'framework agreement', 'roadmap',
                     'feuille de route', 'peace talks', 'pourparlers', 'négociations', 'ceasefire',
                     'cessez-le-feu'],
        'source_headlines': [
            '2026-08-23 DR Congo, M23 rebels agree on roadmap for peace talks (Al Jazeera)',
            '2026-09-18 Congo-Kinshasa: Les promesses déçues du processus de paix de Doha (allAfrica)',
            "2026-11-18 DR Congo's rival peace efforts fail to halt violence in the east (Al Jazeera)",
            'AFC/M23, Kinshasa agree on roadmap to move peace talks forward (New Times)',
            '2025-11 Congo-Kinshasa: DR Congo and M23 Rebels Sign Framework for Peace in Qatar (allAfrica)',
        ],
        'baseline_statements_per_week': 3,
    },
    'monusco': {
        'name': 'MONUSCO (UN)', 'flag': '\U0001F1FA\U0001F1F3', 'icon': '\U0001FA96', 'color': '#38bdf8',
        'role': 'The UN mission -- mandate to 20 Dec 2026, ceasefire verification, Ituri protection',
        'description': ('Renewed to 20 Dec 2026 by Resolution 2808 (unanimous), with a role supporting Doha '
                        'ceasefire verification. The FRN opposes renewal; Kinshasa has long wanted it gone but '
                        'relies on it in Ituri. The December renewal is the next decision point.'),
        'vector': 'peace_tracks',
        'keywords': ['monusco', 'casques bleus', 'peacekeepers', 'peacekeeping mission', 'mission de l\'onu',
                     'un mission', 'mandat de la monusco'],
        'source_headlines': [
            '2025-12-19 Security Council Renews DR Congo Peacekeeping Mission Amid Renewed M23 Offensives in the East (allAfrica)',
            'UN urges Rwanda to leave eastern Congo and extends peacekeeping mission for a year (Ahram Online)',
            'Ituri: MONUSCO force prevents CODECO attack on displaced persons site in Rhoe (MONUSCO)',
        ],
        'baseline_statements_per_week': 2,
    },

    # ── VECTOR: external_alignment ────────────────────────────
    'rwanda_axis': {
        'name': 'Rwanda', 'flag': '\U0001F1F7\U0001F1FC', 'icon': '\U0001F6E1️', 'color': '#22c55e',
        'role': 'The contested patron -- UN experts and the US say it backs M23; Kigali denies it',
        'description': ('The US sanctioned the Rwandan army and senior officials (3 Mar 2026), then the Ministry '
                        'of Defence and Zigama Credit (28 Oct 2026), and is excluding Rwanda from AGOA from '
                        'January 2027. Kigali rejects the allegations and points to the FDLR. The DRC node on the '
                        'Rwanda wheel.'),
        'vector': 'external_alignment', 'wheel': 'rwanda',
        'keywords': ['rwanda', 'rwandan', 'rwandais', 'rwandaise', 'kigali', 'kagame', 'rdf', 'nduhungirehe',
                     'zigama', 'agoa'],
        'source_headlines': [
            '2026-10-29 US imposes sanctions on Rwandan defence ministry over links to Congo rebels (Africanews)',
            'Rwanda hits back at US sanctions over M23 support in DR Congo (The Standard)',
            '2026-03-03 US sanctions Rwandan army and top officials for supporting M23 in DRC (Al Jazeera)',
            '2026-03 Rwanda: Kigali Slams Washington Over RDF Sanctions Amid Eastern Congo Crisis (allAfrica)',
            'Kagame: Over 20,000 Burundi troops fuelling eastern DR Congo crisis (New Times)',
        ],
        'baseline_statements_per_week': 4,
    },
    'uganda_axis': {
        'name': 'Uganda', 'flag': '\U0001F1FA\U0001F1EC', 'icon': '\U0001F6E1️', 'color': '#f59e0b',
        'role': 'Troops by invitation against the ADF -- and the reported route for Ituri gold',
        'description': ('The UPDF fights the ADF with the Congolese army under Operation Shujaa (since 2021); '
                        'Kinshasa supplied it vehicles in August 2026. The UN reports gold smuggling from Ituri '
                        'to Uganda on the rise (Jul 2026). The DRC node on the new Uganda wheel.'),
        'vector': 'external_alignment', 'wheel': 'uganda',
        'keywords': ['uganda', 'ugandan', 'ougandais', 'ougandaise', 'ouganda', 'updf', 'museveni', 'muhoozi',
                     'kampala', 'operation shujaa', 'opération shujaa'],
        'source_headlines': [
            '2026-04-20 Congo-Kinshasa: Over 200 Civilians Rescued As UPDF and FARDC Raid Major ADF Stronghold in Eastern DR Congo (allAfrica)',
            '2026-08-03 Congo-Kinshasa: Tshisekedi Bolsters UPDF Operations in DRC With 10 Toyota Land Cruisers (allAfrica)',
            '2026-03-26 Uganda to Withdraw Troops From Some Positions in Eastern DR Congo, Says Gen Muhoozi (allAfrica)',
            'Joint UPDF-FARDC operation kills 27 ADF rebels, rescues 40 civilians in eastern DRC (Daily Monitor)',
            "2026-07-02 Gold smuggling from DRC's Ituri province to Uganda on the rise, says UN (Africanews)",
        ],
        'baseline_statements_per_week': 2,
    },
    'burundi_axis': {
        'name': 'Burundi', 'flag': '\U0001F1E7\U0001F1EE', 'icon': '\U0001F6E1️', 'color': '#ef4444',
        'role': "Kinshasa's ally in South Kivu -- and Rwanda's open rival",
        'description': ('More than 6,000 troops back in South Kivu (Uvira, the Ruzizi Plain, the highlands) '
                        'after withdrawing when M23 entered Uvira in December 2025. Burundi and Rwanda have had '
                        'no diplomatic relations since January 2024. An actor card, not a hub: Burundi fights in '
                        'the DRC but does not project across the region.'),
        'vector': 'external_alignment',
        'keywords': ['burundi', 'burundais', 'burundaise', 'burundian', 'bujumbura', 'ndayishimiye', 'fdnb',
                     'gatumba'],
        'source_headlines': [
            "2026-04-05 RDC: comment la chute d'Uvira avait mis hors jeu le Burundi (Actualite.cd)",
            'Twirwaneho denounces Burundian forces over hostage-taking, bombings in South Kivu (New Times)',
            '2025-12 Afrique Centrale: Des soldats burundais quittent Uvira par la frontière de Gatumba (allAfrica)',
            "Analysts: Burundi's role in DR Congo conflict taints Ndayishimiye's tenure at AU (New Times)",
        ],
        'baseline_statements_per_week': 2,
    },
    'us_axis': {
        'name': 'United States', 'flag': '\U0001F1FA\U0001F1F8', 'icon': '\U0001F985', 'color': '#3b82f6',
        'role': 'Peace broker AND minerals partner -- sanctions on Rwanda, offtake from Katanga',
        'description': ('Brokered the Washington Accords and signed a minerals-for-security partnership with '
                        'Kinshasa (4 Dec 2025): the first deal (Virtus Minerals) in Apr 2026, copper sales to '
                        'the US up sharply, a steering committee in Paris on 6 Nov 2026. Kinshasa says the deal '
                        'should be judged by projects, not signatures.'),
        'vector': 'external_alignment', 'wheel': 'us',
        'keywords': ['united states', 'états-unis', 'etats-unis', 'washington turns', 'us minerals', 'u.s.',
                     'us sanctions', 'us-drc', 'rdc-états-unis', 'us imposes',
                     'trump', 'boulos', 'treasury', 'minerals deal', 'minerals pact', 'strategic partnership',
                     'partenariat stratégique', 'dfc', 'virtus'],
        'source_headlines': [
            '2026-11-06 Congo says US minerals deal should be judged by projects, not signed deals (Kitco / Reuters)',
            'Partenariat RDC-États-Unis : 9 mois après, Kinshasa et Washington font le point à Paris (Afrik)',
            '2026-01-20 Congo offers manganese, copper-cobalt and lithium assets to US investors under minerals pact (BNN Bloomberg)',
            '2026-04 Virtus Minerals signs first major deal under US-DRC critical minerals partnership (Mongabay)',
            'DRC boosts US copper sales fivefold to 500,000 tonnes (Mining.com)',
        ],
        'baseline_statements_per_week': 3,
    },
    'china_axis': {
        'name': 'China', 'flag': '\U0001F1E8\U0001F1F3', 'icon': '⛏️', 'color': '#ef4444',
        'role': 'The incumbent in the mines -- CMOC, Zijin and the cobalt refining chain',
        'description': ('Chinese companies control most of the major copper-cobalt mines (CMOC at Tenke '
                        'Fungurume and Kisanfu among them) and nearly all cobalt refining happens in China. '
                        'Kinshasa deepened mining ties with Beijing in March 2026 even as the US pushed its rival pact.'),
        'vector': 'external_alignment', 'wheel': 'china',
        'keywords': ['china', 'chinese', 'chine', 'chinois', 'chinoise', 'beijing', 'pékin', 'cmoc', 'zijin',
                     'sicomines', 'tenke fungurume', 'kisanfu', 'huayou'],
        'source_headlines': [
            '2026-03-27 Congo, China deepen mining ties as US pushes rival minerals pact (Engineering News)',
            "2026-01-16 China's CMOC bets on copper growth, maintains cobalt target (Bloomberg)",
            'DR Congo-China agreement deepens minerals ties amid US supply chain push (Intellinews)',
            "CMOC's cobalt production sees robust growth under Congo's export controls (SMM)",
        ],
        'baseline_statements_per_week': 2,
    },
    'uae_gold': {
        'name': 'UAE (the gold channel)', 'flag': '\U0001F1E6\U0001F1EA', 'icon': '\U0001F4B0', 'color': '#eab308',
        'role': "Where eastern Congo's gold is reported to end up",
        'description': ('Investigations and UN experts report eastern Congo gold leaving through Uganda, '
                        'Rwanda and Burundi toward UAE refiners; a Nov 2026 report says war-zone gold still '
                        'entered the UAE despite new rules.'),
        'vector': 'external_alignment', 'wheel': 'uae',
        'keywords': ['uae', 'emirates', 'émirats', 'dubai', 'dubaï', 'emirati', 'émirati'],
        'source_headlines': [
            '2026-11 Gold smuggled from war zones entered the UAE despite new regulations, report says (AP via AJC)',
            'Billions in African gold smuggled to UAE each year -- report (Mining.com)',
            'DRC gold worth billions being smuggled out, says UN (Mining.com)',
        ],
        'baseline_statements_per_week': 1,
    },

    # ── VECTOR: resource_leverage ─────────────────────────────
    'cobalt_copper': {
        'name': 'Cobalt & copper (Katanga)', 'flag': FLAG, 'icon': '\U0001F50B', 'color': '#06b6d4',
        'role': "The world's battery metal -- quotas, prices, offtake",
        'description': ('About 70% of world cobalt and a top-five copper producer. Cobalt exports rationed by '
                        'ARECOMS quota since 2025; cobalt metal fell about a third between July and October 2026 '
                        'as delayed shipments reached China.'),
        'vector': 'resource_leverage',
        'keywords': ['cobalt', 'copper', 'cuivre', 'arecoms', 'export quota', "quota d'exportation", 'katanga',
                     'kolwezi', 'lubumbashi', 'gécamines', 'gecamines', 'glencore', 'kamoto', 'mutanda',
                     'lobito', 'hydroxide'],
        'source_headlines': [
            '2026-10-13 Trade review: Asian cobalt market to remain pressured in Q4 amid lackluster demand (S&P Global)',
            'DRC may reduce cobalt quota if market needs rebalancing, ARECOMS says (Fastmarkets)',
            'Musonoi ramp-up and Mutanda feed to drive DRC cobalt output in 2026 (Fastmarkets via Yahoo)',
            "China's CMOC to boost Congo copper output after ending row with Gecamines (Mining.com)",
            "DR Congo's cobalt miners pivot to copper amid price crash (Yahoo Finance)",
        ],
        'baseline_statements_per_week': 3,
    },
    'conflict_minerals': {
        'name': 'Conflict gold & coltan (the east)', 'flag': FLAG, 'icon': '⛏️', 'color': '#facc15',
        'role': 'The money behind the guns -- Rubaya coltan, artisanal gold',
        'description': ('M23 has held the Rubaya coltan area in Masisi; Amnesty (Sep 2026) and Global Witness '
                        'report M23 abuses at artisanal mines and coltan and gold trafficked to Rwanda (Kigali '
                        'denies it). Coltan becomes tantalum for capacitors in phones, computers and AI hardware.'),
        'vector': 'resource_leverage',
        'keywords': ['coltan', 'tantalum', 'tantale', 'rubaya', 'conflict minerals', 'minerais de conflit',
                     'artisanal', 'gold smuggling', "contrebande d'or", 'smuggled', 'mines artisanales', 'gold'],
        'source_headlines': [
            '2026-09-21 Amnesty: M23 rebels committed war crime abuses against DRC miners, trafficked gold, coltan to Rwanda (TimesLive)',
            '2026-02-12 Rubaya mine collapse and the tantalum supply chain (Argus Media)',
            "2026-06-10 Africa: Who Buys Rwanda's Smuggled Coltan? The Global Journey of Conflict Coltan From DRC (allAfrica / Global Witness)",
            "Inside the mine that feeds the tech world -- and funds Congo's rebels (Mining.com)",
            '2026-09-22 Africa: Conflict Coltan, AI Demand and the Risk of Runaway Harm (allAfrica)',
        ],
        'baseline_statements_per_week': 2,
    },

    # ── VECTOR: epidemic ──────────────────────────────────────
    'ebola': {
        'name': 'Ebola (Bundibugyo)', 'flag': FLAG, 'icon': '\U0001F9A0', 'color': '#a855f7',
        'role': 'A war and an epidemic in the same provinces -- spread, response, attacks on responders',
        'description': ('A WHO global health emergency since 17 May 2026 (confirmed again 18 Nov): 11,613 '
                        'confirmed cases and 5,678 deaths by 17 Nov, worst in Ituri and North Kivu. No licensed '
                        'vaccine for this strain. More than 12 attacks on health facilities and workers were '
                        'recorded by July.'),
        'vector': 'epidemic',
        'keywords': ['ebola', 'bundibugyo', 'fièvre hémorragique', 'haemorrhagic fever', 'hemorrhagic fever',
                     'riposte contre ebola', 'contact tracing', 'centre de traitement', 'treatment centre', 'pheic',
                     'urgence de santé publique'],
        'source_headlines': [
            '2026-07-18 Safety fears limit Ebola response in Congo, with more than 12 attacks recorded (AP)',
            '2026-05 Ebola outbreak in DR Congo collides with conflict and hunger, WHO warns (UN Geneva)',
            'WHO keeps Bundibugyo Ebola a global health emergency as DR Congo cases pass 11,600 (Casrai)',
            'Ebola outbreak climbs to 11,645 cases as deaths near 5,700 (Contagion Live)',
            "2026-08-26 Congo-Kinshasa: 100 jours d'Ebola Bundibugyo - La course pour enrayer la transmission (allAfrica)",
        ],
        'baseline_statements_per_week': 5,
    },
}

VECTOR_GROUPS = {
    'regime_security':    ['tshisekedi_govt', 'opposition_repression', 'frn_m23'],
    'insurgent_fronts':   ['front_south_kivu', 'front_north_kivu', 'front_ituri', 'attacks_unplaced'],
    'peace_tracks':       ['washington_track', 'doha_track', 'monusco'],
    'external_alignment': ['rwanda_axis', 'uganda_axis', 'burundi_axis', 'us_axis', 'china_axis', 'uae_gold'],
    'resource_leverage':  ['cobalt_copper', 'conflict_minerals'],
    'epidemic':           ['ebola'],
}
VECTOR_LABELS = {
    'regime_security':    'Regime Security',
    'insurgent_fronts':   'Insurgent Fronts',
    'peace_tracks':       'Peace Tracks',
    'external_alignment': 'External Alignment',
    'resource_leverage':  'Resource Leverage',
    'epidemic':           'Epidemic',
}

# The wheels the DRC sits on. node_class strings follow spoke_wheel_reader v1.6.4.
SPOKES = {
    'rwanda': {'actor': 'rwanda_axis', 'node_class': 'proxy_backing',
               'why': ('UN experts and the US government say Rwanda backs M23 (US sanctions on the Rwandan army, '
                       'Mar 2026, and the Ministry of Defence, Oct 2026); Kigali denies it and cites the FDLR.')},
    'uganda': {'actor': 'uganda_axis', 'node_class': 'security_partner',
               'why': 'UPDF troops fight the ADF alongside the Congolese army (Operation Shujaa, since 2021).'},
    'us':     {'actor': 'us_axis', 'node_class': 'minerals_partner',
               'why': 'Broker of the Washington Accords and partner in a minerals-for-security deal (4 Dec 2025).'},
    'china':  {'actor': 'china_axis', 'node_class': 'resource_client',
               'why': 'Chinese companies control most major copper-cobalt mines; China refines most of the cobalt.'},
    'uae':    {'actor': 'uae_gold', 'node_class': 'resource_client',
               'why': "Reported destination of eastern Congo's smuggled gold, via neighbouring states."},
}


# ════════════════════════════════════════════════════════════
# RIPPLE CHAINS -- Rachel's standing rule (27 Nov 2026)
# What each actor TOUCHES at four scales, and the follow-on questions.
# Static, dated knowledge: never scored. Surfaced when the actor is LIT.
# Framed as "what this touches", never "what will happen".
# ════════════════════════════════════════════════════════════
RIPPLES_AS_OF = '2026-11-27'
RIPPLES = {
    'cobalt_copper': {
        'country': ('Copper and cobalt are the state\'s main revenue; a price fall or quota change moves the '
                    'budget, the franc and Katanga\'s politics -- far from the eastern war.'),
        'region': ('Zambia shares the copper belt and the export routes (Lobito, Dar es Salaam, Durban); '
                   'what Kinshasa does to quotas changes their ports\' and railways\' traffic.'),
        'continent': ('Africa\'s largest test of "resource nationalism with leverage": if quotas hold prices '
                      'up, Zimbabwe (lithium), Guinea (bauxite) and others have a template.'),
        'globe': ('Cobalt goes into lithium-ion battery cathodes (EVs, phones, grid storage), superalloys for '
                  'jet engines and missiles, and hard metals for tooling. About 70% is mined in the DRC and '
                  'most is refined in China: a squeeze here is felt in car plants and defence supply chains.'),
        'questions': [
            'What does a quota change do to battery makers who have already shifted to cobalt-free (LFP) chemistry -- and to those who cannot?',
            'Does a price spike push Indonesia\'s nickel-cobalt output up and Congo\'s market share down?',
            'Which defence programmes depend on cobalt superalloys, and how deep are Western stockpiles?',
            'If the US offtake grows, does Chinese refining capacity still sit in the middle of the chain?',
        ],
    },
    'china_axis': {
        'country': ('Chinese operators run most of the major mines; Kinshasa renegotiates with them while '
                    'courting Washington -- leverage it uses in both directions.'),
        'region': ('Chinese capital also runs Zambian copper and Zimbabwean lithium; a move in Kinshasa is '
                   'read across the copper belt.'),
        'continent': ('The DRC is the centrepiece of China\'s African minerals strategy; a Chinese retreat or '
                      'advance here signals its posture continent-wide.'),
        'globe': ('China already controls most cobalt refining and has used export controls on gallium, '
                  'germanium, graphite and rare earths. A Chinese move on Congolese cobalt raises the question '
                  'of whether cobalt joins that list -- and which battery and defence supply chains outside '
                  'China would feel it first.'),
        'questions': [
            'If China moves on cobalt, which other critical minerals has it already restricted, and what was the market response then?',
            'Does a Chinese move push the US-DRC partnership from signatures to projects faster -- or stall it?',
            'Which non-Chinese refiners (Finland, Morocco, the US) could absorb Congolese hydroxide, and how quickly?',
        ],
    },
    'us_axis': {
        'country': ('Washington is both peace broker and minerals customer; Kinshasa reads US pressure on Rwanda '
                    'as the return on the minerals deal.'),
        'region': ('US sanctions on Rwanda (army, Mar 2026; defence ministry, Oct 2026; AGOA exclusion from '
                   'Jan 2027) reorder the Great Lakes: Kigali\'s economy and its peacekeeping brand are exposed.'),
        'continent': ('The minerals-for-security model is being offered to other African states; whether it '
                      'delivers here decides whether it spreads.'),
        'globe': ('The deal is a front in the US-China contest over critical-mineral supply chains; a US '
                  'project that actually ships changes where cobalt and copper are refined.'),
        'questions': [
            'Does US leverage on Rwanda produce movement on the ground, or only in Washington?',
            'If the partnership stalls, does Kinshasa tilt back toward Beijing?',
            'How does the AGOA exclusion change Rwanda\'s calculus in the east?',
        ],
    },
    'rwanda_axis': {
        'country': ('Whatever the truth of the UN experts\' findings (Kigali denies them), Rwanda\'s posture is '
                    'the variable the eastern front tracks most closely.'),
        'region': ('Rwanda-Burundi hostility (no relations since Jan 2024) and Rwanda-Uganda rivalry play out '
                   'on Congolese soil; sanctions on Kigali shift that balance.'),
        'continent': ('Rwanda sells security to other governments (CAR, Mozambique). Sanctions on its '
                      'military test whether that model survives Western censure.'),
        'globe': ('Coltan and gold reported to transit Rwanda reach global electronics supply chains; '
                  'due-diligence regimes (US, EU) are tested here.'),
        'questions': [
            'Do US sanctions change Rwanda\'s deployments in CAR and Mozambique -- the other spokes on its wheel?',
            'Does pressure on Kigali open space for Kinshasa to stall on the FDLR, or for a deal?',
        ],
    },
    'uganda_axis': {
        'country': ('Ugandan troops are the main force against the ADF in Ituri and North Kivu -- the provinces '
                    'with the most Ebola.'),
        'region': ('Kampala has its own interests in Ituri (the ADF, which has attacked Kampala; trade; gold) '
                   'and its own rivalry with Kigali.'),
        'continent': ('Uganda is also leaving Somalia (2027 exit); where its army is spent is a continental '
                      'question.'),
        'globe': ('The ADF is an Islamic State province (ISCAP); its fate is part of the global IS picture.'),
        'questions': [
            'If the UPDF pulls back from positions (as signalled in March 2026), who fills the space -- the ADF, CODECO, or no one?',
            'Does Ituri gold flowing to Uganda fund anyone on the battlefield?',
        ],
    },
    'burundi_axis': {
        'country': 'Burundian troops are the backbone of the defence of Uvira and the Ruzizi Plain.',
        'region': ('Burundi and Rwanda have no diplomatic relations; a clash between their forces in South Kivu '
                   'would turn a civil war into an interstate one.'),
        'continent': 'Burundi\'s president chairs the AU; its role in the DRC colours the AU\'s mediation.',
        'globe': 'Limited direct reach; the risk is regional escalation that drags in larger patrons.',
        'questions': ['What happens to Uvira if Burundi has to pull troops home?'],
    },
    'frn_m23': {
        'country': ('A former president leading an armed coalition with M23 inside it turns a rebellion in the '
                    'east into a contest for the state itself.'),
        'region': ('The FRN\'s territory borders Rwanda, Uganda and Burundi; its supply and recruitment cross '
                   'those borders.'),
        'continent': 'A precedent for ex-heads of state taking up arms against successors.',
        'globe': 'Whoever holds the east holds Rubaya coltan and the gold routes into global supply chains.',
        'questions': [
            'Does the FRN aim at Kinshasa\'s politics (the constitution) or at territory -- and does the Doha track survive that?',
            'Do army defections continue (one general reported in October 2026)?',
        ],
    },
    'conflict_minerals': {
        'country': 'Mine revenue pays fighters on every side; whoever holds Rubaya holds a cash flow.',
        'region': 'Smuggling routes run through Rwanda, Uganda and Burundi to UAE refiners.',
        'continent': 'The same route economy moves gold out of Sudan, CAR and the Sahel.',
        'globe': ('Coltan becomes tantalum for capacitors in phones, computers, cars and AI data-centre '
                  'hardware; tin and tungsten from the same mines go into electronics solder and munitions.'),
        'questions': [
            'Does rising AI hardware demand for tantalum raise the price armed groups can extract?',
            'Which smelters and brands are exposed if traceability schemes fail here?',
        ],
    },
    'ebola': {
        'country': ('The epidemic is worst where the fighting is; insecurity blocks contact tracing, and '
                    'displacement moves the virus.'),
        'region': ('Uganda ended its outbreak in August 2026; Kenya has had 9 cases. Every border closure or '
                   'reopening is also an economic decision.'),
        'continent': ('One imported case reached Nigeria (Abuja). A case in a major transit hub -- Kampala, '
                      'Nairobi, Kigali, Kinshasa -- changes the continental risk.'),
        'globe': ('A WHO global health emergency with no licensed vaccine for this strain; airline routes, '
                  'medical evacuations and vaccine research funding all key off it.'),
        'questions': [
            'Does fighting near Ebola zones (Ituri, North Kivu) push cases into new provinces or across borders?',
            'Do airlines or neighbours impose travel restrictions -- and what do they cost the region?',
        ],
    },
    'monusco': {
        'country': 'MONUSCO protects displacement sites in Ituri and verifies the Doha ceasefire.',
        'region': 'A drawdown shifts protection to the army, Uganda and Burundi.',
        'continent': 'A test of UN peacekeeping under the UN\'s cash crisis (as in CAR).',
        'globe': 'The December renewal is a Security Council vote where the US, China and Russia all have stakes.',
        'questions': ['Is the mandate renewed on 20 Dec 2026, and with what ceiling and tasks?'],
    },
    'washington_track': {
        'country': 'The state-to-state track; it cannot end the war without Doha.',
        'region': 'It is the only framework that binds Rwanda; its failure removes the main brake on escalation.',
        'continent': 'A US-brokered African peace tied to minerals -- a model others are watching.',
        'globe': 'The diplomatic wrapper around the US minerals partnership.',
        'questions': ['Is there an agreed standard for FDLR neutralisation and Rwandan "defensive measures"?'],
    },
    'doha_track': {
        'country': 'The government-rebel track; the FRN\'s arrival changes who sits across the table.',
        'region': 'Qatar\'s mediation competes and coordinates with Washington\'s.',
        'continent': 'The AU has called implementation "limited" and asked for better coordination.',
        'globe': 'Qatar\'s mediation brand (Gaza, Afghanistan, Congo) is tested here.',
        'questions': ['Does the FRN keep AFC/M23\'s Doha commitments while fighting in Kalehe?'],
    },
    'tshisekedi_govt': {
        'country': ('A referendum law the opposition says opens a third term, during a war, with a former '
                    'president in armed rebellion.'),
        'region': 'Neighbours read Kinshasa\'s political crisis as weakness or opportunity.',
        'continent': 'Another test of term-limit erosion (CAR, Togo, others).',
        'globe': 'Western partners weigh minerals access against democratic backsliding.',
        'questions': ['Is a referendum date set -- and does it become the FRN\'s rallying cry?'],
    },
    'opposition_repression': {
        'country': 'Protests in June and September 2026 ended in arrests and deaths.',
        'region': 'Limited direct reach.',
        'continent': 'Part of the continental term-limits pattern.',
        'globe': 'Shapes Western partners\' willingness to deepen the minerals partnership.',
        'questions': ['Does the C64 meet Kabila in Goma, as Katumbi said it would?'],
    },
}


# ════════════════════════════════════════════════════════════
# DEAL VS GROUND -- the signature axis
# The peace tracks are read against the fronts. Patterns trace to the
# 2026 headlines quoted on washington_track and doha_track.
# ════════════════════════════════════════════════════════════
DEAL_PATTERNS = {
    'holding':    ['agree on new mechanisms', 'agree on roadmap', 'agreed a roadmap', 'feuille de route',
                   'sign framework', 'signent', 'signed', 'commends rwanda for delivering', 'progress',
                   'avancée', 'withdrawal completed', 'troops withdraw', 'disengagement', 'désengagement',
                   'prisoner exchange', 'échange de prisonniers', 'ceasefire holds', 'cessez-le-feu respecté'],
    'stalled':    ['holding up', 'stalled', 'stalls', 'stagne', 'impasse', 'blocked', 'bloqué',
                   'failed to deliver', 'fail to deliver', 'fail to halt', 'promesses déçues', 'bilan mitigé',
                   'dodges', 'skips signing', 'delivery another', 'limited implementation', 'mise en œuvre limitée'],
    'fraying':    ['ceasefire violation', 'violation du cessez-le-feu', 'violations du cessez-le-feu',
                   'violates', 'violé', 'accuses kinshasa', 'accuses kigali', 'accuse kinshasa', 'accuse kigali',
                   'suspends talks', 'suspend les pourparlers', 'boycott', 'walks out'],
    'collapsing': ['talks collapse', 'collapse of talks', 'withdraws from talks', 'se retire des pourparlers',
                   'se retire des négociations', 'peace deal collapses', "abandon de l'accord", 'pulls out of the',
                   'declares war', 'déclare la guerre', 'rupture des négociations'],
}


# ════════════════════════════════════════════════════════════
# COUNTRY GATE -- Brazzaville is also "Congo"; ADF is also Australia's army
# ════════════════════════════════════════════════════════════
STRONG_TOKENS = [
    'democratic republic of congo', 'democratic republic of the congo', 'dr congo', 'd.r. congo',
    'république démocratique du congo', 'congo-kinshasa', 'tshisekedi', 'kabila', 'fardc',
    'monusco', 'wazalendo', 'twirwaneho', 'codeco', 'kivu', 'ituri', 'goma', 'bukavu', 'uvira', 'bunia',
    'butembo', 'masisi', 'rutshuru', 'walikale', 'kalehe', 'minembwe', 'djugu', 'irumu', 'mambasa',
    'kolwezi', 'lubumbashi', 'katanga', 'gécamines', 'gecamines', 'arecoms', 'rubaya', 'bunyakiri',
    'kahuzi-biega', 'ruzizi', 'fizi', 'lubero', 'sicomines', 'tenke fungurume', 'm23', 'afc/m23',
    'refoundation of the nation', 'front pour la refondation',
]
# WEAK tokens pass only when the text is NOT about Brazzaville (the Republic of
# the Congo shares the name, the demonym and the river with Kinshasa).
WEAK_TOKENS = ['kinshasa', 'congolese', 'congolais', 'congolaise']
# "DRC" / "RDC" only as UPPERCASE standalone words in the original text.
_DRC_ACRONYM = re.compile(r'(?<![A-Za-z])(?:DRC|RDC)(?![A-Za-z])')
DRC_ACRONYM_REJECT = ['dispute resolution', 'design rule', 'drc colour', 'drc color']
# "Congo" alone is the DRC in most wire copy (AP style) -- unless the text is about Brazzaville.
_CONGO = re.compile(r'(?<![a-z])congo(?![a-z])')
BRAZZAVILLE_CONTEXT = ['brazzaville', 'sassou', 'nguesso', 'republic of the congo (brazzaville)',
                       'congo-brazzaville', 'pointe-noire', 'congo brazzaville']


# ════════════════════════════════════════════════════════════
# KINETIC LADDER -- per front, platform scale, L5 only from here
# ════════════════════════════════════════════════════════════
_NUM = (r'(?:1[0-9]|[2-9][0-9]|[1-9][0-9]{2,}|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|'
        r'seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|a dozen|dozens of|hundreds of|'
        r'dix|douze|quinze|vingt|trente|quarante|cinquante)')
LADDER = [
    (5, [r'attack on kinshasa', r'kinshasa under attack', r'march on kinshasa', r'marcher sur kinshasa',
         r'marchent sur kinshasa', r'attaque (?:de|contre) kinshasa',
         r'(?:goma|bukavu|uvira|bunia|kisangani|butembo|beni|kalemie) (?:falls|has fallen|captured|seized|overrun)',
         r'(?:fall|capture|seizure|prise|chute) (?:of|de|d\') ?(?:goma|bukavu|uvira|bunia|kisangani|butembo|beni|kalemie)',
         r'town (?:captured|seized|overrun|falls)', r'(?:base|garrison|camp) (?:overrun|captured|falls)',
         r'falls to (?:rebels|the frn|m23|militia|armed groups)',
         r'(?:seize|seizes|seized|capture|captures|captured|take|takes|took|overrun|overruns|overran) '
         r'(?:the |a )?(?:town|city|base|garrison|military camp|army camp)',
         r'tombent? sous (?:leur|le|son) contr[oô]le', r'tombe(?:nt)? aux mains',
         r'prennent le contr[oô]le', r"s'empare(?:nt)? de", r'(?:ville|base|camp|localit[ée]s?) (?:tombée?s?|prises?) ',
         r'seize[sd]? power', r'coup succeeds', r'tshisekedi (?:killed|ousted|overthrown|renversé)']),
    (4, [r'massacre', r'dozens (?:of )?(?:soldiers|civilians|people|troops|villagers)? ?(?:killed|dead)?',
         r'\bdozens\b', r'des dizaines', r'une dizaine', r'nombreux (?:militaires|soldats|civils) tués',
         r'(?:kill(?:s|ed|ing)?|tués?) (?:at least )?' + _NUM,
         r'(?:at least |au moins )?' + _NUM + r' (?:soldiers|troops|civilians|people|villagers|militaires|soldats|civils|personnes|morts)',
         r'(?:at least |au moins )?' + _NUM + r' (?:\w+ )?(?:killed|dead|tués|morts)',
         r'deadliest', r'mass casualty']),
    (3, [r'attack', r'attaque', r'ambush', r'embuscade', r'clash', r'affrontement', r'combats', r'killed',
         r'tués?', r'raid', r'kidnapp', r'enlev', r'massacres?', r'violente', r'violence', r'offensive',
         r'drone strike', r'frappes?', r'bombard']),
    (2, [r'threat', r'threaten', r'menace', r'warns', r'claims?', r'revendique', r'pressure', r'pression',
         r'tension', r'craintes', r'fears', r'riposte']),
]
_LADDER_RX = [(lv, [re.compile(p) for p in pats]) for lv, pats in LADDER]


# ════════════════════════════════════════════════════════════
# TRIPWIRES -- red lines. BREACHED / APPROACHING; they do NOT open L5.
# ════════════════════════════════════════════════════════════
TRIPWIRES = {
    'capital_threatened': {
        'patterns': ['attack on kinshasa', 'march on kinshasa', 'marcher sur kinshasa', 'marchent sur kinshasa',
                     'attaque de kinshasa', 'attaque contre kinshasa'],
        'severity': 'surge',
        'note': 'The FRN says it seeks to refound the state; fighting reaching Kinshasa would be a new war.',
    },
    'major_city_falls': {
        'patterns': ['uvira falls', 'fall of uvira', "prise d'uvira", 'chute d\'uvira', 'bunia falls',
                     'prise de bunia', 'kisangani falls', 'prise de kisangani', 'butembo falls', 'beni falls',
                     'kalemie falls'],
        'severity': 'surge',
        'note': 'Goma (Jan 2025) and Bukavu (Feb 2025) are the precedents; Uvira was entered in Dec 2025 and given back.',
    },
    'mass_casualty_event': {
        'patterns': ['massacre', 'deadliest', 'dozens of civilians', 'dozens of soldiers', 'des dizaines de'],
        'severity': 'high',
        'note': 'ADF and CODECO massacres in Ituri and North Kivu are the class (69 killed in Djugu, May 2026).',
    },
    'ebola_new_frontier': {
        'patterns': ['ebola case in kinshasa', "cas d'ebola à kinshasa", 'ebola reaches', 'ebola spreads to',
                     'first ebola case', "premier cas d'ebola", 'ebola in goma', 'ebola à goma', 'new province',
                     'nouvelle province'],
        'severity': 'high',
        'note': 'Ebola reaching a new province, a capital or a new country (Kenya, Nigeria in Oct 2026) changes the risk beyond the east.',
    },
    'health_response_attacked': {
        'patterns': ['attack on health workers', 'health workers attacked', 'agents de santé attaqués',
                     'treatment centre attacked', 'centre de traitement attaqué', 'attaque contre un centre',
                     'health facility attacked', 'attacks on health facilities', 'riposte attaquée'],
        'severity': 'high',
        'note': 'More than 12 attacks on health facilities and workers by July 2026; each one slows contact tracing.',
    },
    'peacekeepers_attacked': {
        'patterns': ['casques bleus blessés', 'casque bleu tué', 'casques bleus tués', 'peacekeeper killed',
                     'peacekeepers killed', 'peacekeepers wounded', 'attack against peacekeepers',
                     'attaque contre la monusco', 'monusco attacked'],
        'severity': 'high',
        'note': 'MONUSCO protects displacement sites in Ituri; attacks on it are attacks on the protection model.',
    },
    'monusco_mandate': {
        'patterns': ['monusco mandate', 'mandat de la monusco', 'retrait de la monusco', 'monusco withdrawal',
                     'monusco drawdown', 'renouvellement du mandat', 'mandate renewal'],
        'severity': 'elevated',
        'note': 'Mandate ends 20 Dec 2026; the FRN opposes renewal.',
    },
    'rwanda_sanctions': {
        'patterns': ['sanctions on rwanda', 'sanctions rwanda', 'sanctionne le rwanda', 'rwandan defence ministry',
                     'rwandan army and top officials', 'sanctions against rwanda', 'agoa'],
        'severity': 'elevated',
        'note': 'US sanctions on the Rwandan army (Mar 2026) and Ministry of Defence (Oct 2026); AGOA exclusion from Jan 2027.',
    },
    'interstate_clash': {
        'patterns': ['clash with rwandan', 'rwandan troops clash', 'affrontements entre les fardc et la rdf',
                     'burundian and rwandan', 'burundi and rwanda clash', 'rwanda attacks burundi',
                     'troupes rwandaises et burundaises'],
        'severity': 'high',
        'note': 'Direct fighting between national armies (Rwanda, Burundi, the DRC) would turn the war interstate.',
    },
    'talks_collapse': {
        'patterns': ['talks collapse', 'withdraws from talks', 'se retire des pourparlers', 'se retire des négociations',
                     'suspends talks', 'suspend les pourparlers', 'peace deal collapses'],
        'severity': 'high',
        'note': 'A party leaving Doha or Washington removes the only frameworks in play.',
    },
    'constitutional_crisis': {
        'patterns': ['référendum constitutionnel', 'constitutional referendum', 'date du référendum',
                     'referendum date', 'third term', 'troisième mandat', 'constitutional coup',
                     "coup d'état constitutionnel"],
        'severity': 'elevated',
        'note': 'The referendum law of Nov 2026; the FRN says it will "mobilise all means" against a constitutional change.',
    },
    'protest_repression': {
        'patterns': ['réprimée dans le sang', 'protesters killed', 'manifestants tués', 'opposition leader arrested',
                     "arrestation de l'opposant", 'marche interdite', 'banned march'],
        'severity': 'elevated',
        'note': 'Opposition protests in June and September 2026 ended in arrests and deaths.',
    },
    'cobalt_export_shock': {
        'patterns': ['cobalt export ban', 'suspends cobalt exports', "interdiction d'exportation", 'quota cut',
                     'cuts cobalt quota', 'réduit le quota', 'new export quota'],
        'severity': 'elevated',
        'note': 'The 2025 export ban and quotas moved world cobalt prices; a new cut is felt in battery and defence supply chains.',
    },
}


# ════════════════════════════════════════════════════════════
# FEEDS -- EN + FR
# ════════════════════════════════════════════════════════════
RSS_FEEDS = {
    'gn_en': {'url': ('https://news.google.com/rss/search?q=%22DR+Congo%22+OR+%22Democratic+Republic+of+Congo%22'
                      '+when:7d&hl=en-US&gl=US&ceid=US:en'),
              'name': 'GoogleNews-EN', 'weight': 0.85, 'language': 'en', 'aggregator': True},
    'gn_fr': {'url': ('https://news.google.com/rss/search?q=RDC+OR+%22Congo-Kinshasa%22+when:7d&hl=fr&gl=FR&ceid=FR:fr'),
              'name': 'GoogleNews-FR', 'weight': 0.85, 'language': 'fr', 'aggregator': True},
    'gn_east': {'url': ('https://news.google.com/rss/search?q=(Kivu+OR+Ituri+OR+Goma+OR+FRN+OR+M23+OR+Wazalendo)'
                        '+when:7d&hl=fr&gl=FR&ceid=FR:fr'),
                'name': 'GoogleNews-East', 'weight': 0.85, 'language': 'fr', 'aggregator': True},
    'gn_peace': {'url': ('https://news.google.com/rss/search?q=Congo+(Rwanda+OR+Doha+OR+%22Washington+Accords%22+OR+MONUSCO)'
                         '+when:7d&hl=en-US&gl=US&ceid=US:en'),
                 'name': 'GoogleNews-Peace', 'weight': 0.85, 'language': 'en', 'aggregator': True},
    'gn_minerals': {'url': ('https://news.google.com/rss/search?q=Congo+(cobalt+OR+copper+OR+coltan+OR+gold)'
                            '+when:7d&hl=en-US&gl=US&ceid=US:en'),
                    'name': 'GoogleNews-Minerals', 'weight': 0.85, 'language': 'en', 'aggregator': True},
    'gn_ebola': {'url': ('https://news.google.com/rss/search?q=Ebola+Congo+when:7d&hl=en-US&gl=US&ceid=US:en'),
                 'name': 'GoogleNews-Ebola', 'weight': 0.85, 'language': 'en', 'aggregator': True},
    'rfi_af':   {'url': 'https://www.rfi.fr/fr/afrique/rss', 'name': 'RFI Afrique',
                 'weight': 0.95, 'language': 'fr'},
    'reliefweb': {'url': 'https://reliefweb.int/country/cod/rss.xml', 'name': 'ReliefWeb COD',
                  'weight': 1.0, 'language': 'en'},
}
GDELT_QUERIES_EN = [
    '"DR Congo" AND ("M23" OR "FRN" OR "Kabila")',
    '"Congo" AND ("Rwanda" OR "Washington Accords" OR "Doha")',
    '"Congo" AND ("Ituri" OR "ADF" OR "CODECO")',
    '"Congo" AND ("cobalt" OR "copper" OR "coltan")',
    '"Congo" AND "Ebola"',
]
GDELT_QUERIES_FR = [
    '"RDC" ET ("FRN" OU "M23" OU "Wazalendo")',
    '"RDC" ET ("Ituri" OU "Kivu" OU "Ebola")',
]
NEWSAPI_QUERIES = ['"DR Congo" M23', '"DR Congo" Rwanda', '"DR Congo" cobalt', '"DR Congo" Ebola',
                   'Tshisekedi Kabila']
BRAVE_QUERIES = ['DR Congo FRN M23 2026', 'RDC Kivu Ituri', 'Congo cobalt China US minerals']


# ════════════════════════════════════════════════════════════
# VALIDATION -- MEASURED by test_drc_harness.py on the 27 Nov 2026 corpus
# (filled in from the harness run; see VALIDATION_CORPUS_NOTE)
# ════════════════════════════════════════════════════════════
ACTOR_VALIDATION = {
    'tshisekedi_govt':       {'status': 'validated', 'real_headlines_matched': 6},
    'opposition_repression': {'status': 'validated', 'real_headlines_matched': 4},
    'frn_m23':               {'status': 'validated', 'real_headlines_matched': 23},
    'front_south_kivu':      {'status': 'validated', 'real_headlines_matched': 7},
    'front_north_kivu':      {'status': 'validated', 'real_headlines_matched': 8},
    'front_ituri':           {'status': 'validated', 'real_headlines_matched': 7},
    'attacks_unplaced':      {'status': 'validated', 'real_headlines_matched': 18},
    'washington_track':      {'status': 'validated', 'real_headlines_matched': 4},
    'doha_track':            {'status': 'validated', 'real_headlines_matched': 4},
    'monusco':               {'status': 'validated', 'real_headlines_matched': 3},
    'rwanda_axis':           {'status': 'validated', 'real_headlines_matched': 13},
    'uganda_axis':           {'status': 'validated', 'real_headlines_matched': 5},
    'burundi_axis':          {'status': 'validated', 'real_headlines_matched': 5},
    'us_axis':               {'status': 'validated', 'real_headlines_matched': 9},
    'china_axis':            {'status': 'validated', 'real_headlines_matched': 4},
    'uae_gold':              {'status': 'unvalidated', 'real_headlines_matched': 0,
                             'note': ('The UAE gold headlines in the harvest do not name the DRC in the title. UNTESTED: '
                                      'the UAE spoke reads unread until DRC-specific coverage validates it.')},
    'cobalt_copper':         {'status': 'validated', 'real_headlines_matched': 7},
    'conflict_minerals':     {'status': 'validated', 'real_headlines_matched': 6},
    'ebola':                 {'status': 'validated', 'real_headlines_matched': 4},
}
VALIDATION_AS_OF = '2026-11-27'
VALIDATION_CORPUS_NOTE = (
    '87 2025-26 DRC headlines (EN and FR; a few reconstructed from article URL slugs) + 10 negative controls '
    '(Brazzaville stories, the Australian Defence Force, Uganda-only Ebola, Rwanda-only and Burundi-only news, '
    'a CAR story, "DRC" as a dispute-resolution centre, cobalt-blue paint). Country gate: 80/87 passed (the 7 '
    'misses name no country in the headline), 0/10 negative-control leaks. Deal vs ground on the year: '
    'paper_only (4 outlets holding, 3 stalled, while three fronts sat at L3+).')


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
        print('[DRC Rhetoric] redis get %s: %s' % (key, str(e)[:100]))
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
        print('[DRC Rhetoric] redis set %s: %s' % (key, str(e)[:100]))
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
        print('[DRC Rhetoric] redis lpush %s: %s' % (key, str(e)[:100]))
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
        print('[DRC Rhetoric] RSS %s: %s' % (feed_id, str(e)[:100]))
    return out


def fetch_all_rss():
    out = []
    for fid, cfg in RSS_FEEDS.items():
        got = fetch_rss(fid, cfg)
        if got:
            print('[DRC Rhetoric] RSS %s: %d' % (fid, len(got)))
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
    print('[DRC Rhetoric] GDELT: %d' % len(out))
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
        print('[DRC Rhetoric] NewsAPI: %d' % len(out))
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
        print('[DRC Rhetoric] Brave: %d' % len(out))
    return out


# ════════════════════════════════════════════════════════════
# GATE + CLASSIFY
# ════════════════════════════════════════════════════════════
def _body(article):
    return _norm(article.get('title', '')) + ' ' + _norm(article.get('description', ''))


def passes_country_gate(article):
    """True when the article is about the DEMOCRATIC Republic of the Congo.

    1. A DRC-specific place, person or institution, or the country's full
       name -> pass (even if Brazzaville is also mentioned).
    2. "DRC" / "RDC" as an UPPERCASE standalone word -> pass.
    3. Otherwise "Congo", "Congolese" or "Kinshasa" pass only when the text
       is NOT about Brazzaville (the Republic of the Congo).
    """
    body = _body(article)
    if any(_kw_in(t, body) for t in STRONG_TOKENS):
        return True, 'country'
    if _DRC_ACRONYM.search('%s %s' % (article.get('title', ''), article.get('description', ''))) \
            and not any(t in body for t in DRC_ACRONYM_REJECT):
        return True, 'country'
    weak = any(_kw_in(t, body) for t in WEAK_TOKENS) or bool(_CONGO.search(body))
    if weak:
        if any(t in body for t in BRAZZAVILLE_CONTEXT):
            return False, 'brazzaville'
        return True, 'country'
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
        if lab.startswith('ebola') and 'case' in lab:
            stats['ebola_cases'] = s.get('value')
            stats['ebola_as_of'] = s.get('as_of')
        elif lab.startswith('ebola') and 'death' in lab:
            stats['ebola_deaths'] = s.get('value')
        elif lab.startswith('internally displaced'):
            stats['idps'] = s.get('value')
        elif 'ipc' in lab or 'hunger' in lab:
            stats['ipc3_plus'] = s.get('value')
    cal = h.get('seasonal_calendar') or {}
    return {'available': True, **stats, 'seasonal_open': cal.get('open_now') or [],
            'data_as_of': h.get('data_as_of')}


def _read_commodity_context():
    """CONTEXT ONLY (not scored): copper, cobalt and gold for display."""
    try:
        from commodity_proxy_africa import get_africa_commodity_data
    except ImportError:
        return {'available': False, 'reason': 'commodity proxy not importable'}
    try:
        d = get_africa_commodity_data('drc') or {}
        out = {'available': False, 'scored': False}
        for t in (d.get('commodity_summaries') or []):
            if t.get('commodity') in ('copper', 'cobalt', 'gold', 'tantalum'):
                sp = t.get('sparkline') or {}
                out[t['commodity']] = {'price': sp.get('price'), 'change_pct_1d': sp.get('change_pct_1d'),
                                       'change_pct_30d': sp.get('change_pct_30d')}
                out['available'] = True
        return out
    except Exception as e:
        return {'available': False, 'reason': str(e)[:120]}


def _read_crosstheater_amplifiers():
    amps = {}
    for label, key in (('car_fingerprint', 'crosstheater:car:fingerprint'),
                       ('sudan_fingerprint', 'crosstheater:sudan:fingerprint')):
        v = _redis_get(key)
        if v:
            amps[label] = v
    return amps


# ════════════════════════════════════════════════════════════
# DEAL VS GROUND
# ════════════════════════════════════════════════════════════
def _deal_axis(track_articles, fronts):
    """Reads the peace-track articles against the front ladders.

    Each pattern family counts DISTINCT OUTLETS. The ground is the worst
    STANDING front this window. 'paper_only' -- the 2026 norm -- is when the
    deals are reported alive (holding or stalled, not collapsing) while two
    or more outlets report L3+ fighting on a front the deals cover.
    Nothing matched -> 'unread' (never 'holding')."""
    hits = {k: {} for k in DEAL_PATTERNS}
    for a in track_articles:
        body = _norm('%s %s' % (a.get('title', ''), a.get('description', '')))
        for state, pats in DEAL_PATTERNS.items():
            if any(p in body for p in pats):
                hits[state].setdefault((a.get('source') or '?').lower(), a)
    n = {k: len(v) for k, v in hits.items()}
    ev = {k: [{'title': a.get('title', '')[:160], 'source': a.get('source', ''), 'url': a.get('url', '')}
              for a in list(v.values())[:3]] for k, v in hits.items()}
    hot = [f for f in fronts.values() if f.get('standing') and f['level'] >= 3]
    ground = max([f['level'] for f in fronts.values() if f.get('standing')] + [0])
    hot_names = ', '.join(f['name'] for f in hot)
    talked = n['holding'] + n['stalled']

    if n['collapsing'] >= 2:
        state = 'collapsing'
        reading = ('Two or more outlets report a peace track collapsing or a party walking out. With the fronts at '
                   'L%d, the frameworks that bind Rwanda and the FRN are what is at stake.' % ground)
    elif n['fraying'] >= 2:
        state = 'fraying'
        reading = ('Two or more outlets report ceasefire violations, accusations or suspended talks. The deals '
                   'still exist; the parties are using them as weapons.')
    elif talked >= 2 and hot:
        state = 'paper_only'
        reading = ('The deals are reported alive (%d outlets on Washington or Doha) while the ground says otherwise: '
                   '%s at L3 or above on two or more outlets. Paper and ground disagree -- that gap is the finding.'
                   % (talked, hot_names))
    elif n['holding'] >= 2 and not hot:
        state = 'holding'
        reading = ('Two or more outlets report progress on the peace tracks and no standing front is above L2 this '
                   'window. Holding on paper AND on the ground -- rare, and worth checking again next scan.')
    elif n['stalled'] >= 2:
        state = 'stalled'
        reading = ('Two or more outlets report the peace tracks stalled or failing to deliver, without a front '
                   'above L2 this window.')
    elif sum(n.values()):
        state = 'thin'
        reading = 'One outlet only on the peace tracks this window: held as thin, not as a finding.'
    else:
        state = 'unread'
        reading = 'No reporting this window on the Washington or Doha tracks. Unread, not holding.'
    return {'id': 'deal_axis_drc', 'state': state, 'outlets': n, 'evidence': ev, 'reading': reading,
            'ground_level': ground, 'hot_fronts': [f['name'] for f in hot],
            'states_defined': ['holding', 'paper_only', 'stalled', 'fraying', 'collapsing', 'thin', 'unread'],
            'watch': ['An agreed standard for FDLR neutralisation and Rwanda\'s "defensive measures"',
                      'Whether the FRN keeps AFC/M23\'s Doha commitments while fighting in Kalehe',
                      'The MONUSCO renewal vote (mandate ends 20 Dec 2026)',
                      'US enforcement: more sanctions on Kigali, or on Kinshasa\'s side for the FDLR']}


# ════════════════════════════════════════════════════════════
# PROSE -- estimative voice, builtin (no Claude call). GPI-safe signals.
# ════════════════════════════════════════════════════════════
TRIPWIRE_SIG_LEVEL = {'surge': 4, 'high': 3, 'elevated': 2}
TRIPWIRE_AXIS = {
    'capital_threatened': 'kinetic', 'major_city_falls': 'kinetic', 'mass_casualty_event': 'kinetic',
    'ebola_new_frontier': 'humanitarian', 'health_response_attacked': 'humanitarian',
    'peacekeepers_attacked': 'kinetic', 'monusco_mandate': 'diplomatic', 'rwanda_sanctions': 'diplomatic',
    'interstate_clash': 'kinetic', 'talks_collapse': 'diplomatic', 'constitutional_crisis': 'governance',
    'protest_repression': 'governance', 'cobalt_export_shock': 'economic',
}
ACTOR_AXIS = {
    'tshisekedi_govt': 'governance', 'opposition_repression': 'governance', 'frn_m23': 'governance',
    'washington_track': 'diplomatic', 'doha_track': 'diplomatic', 'monusco': 'diplomatic',
    'rwanda_axis': 'diplomatic', 'uganda_axis': 'diplomatic', 'burundi_axis': 'diplomatic',
    'us_axis': 'diplomatic', 'china_axis': 'economic', 'uae_gold': 'economic',
    'cobalt_copper': 'economic', 'conflict_minerals': 'economic', 'ebola': 'humanitarian',
}
SIG_COLOR = {0: '#6b7280', 1: '#3b82f6', 2: '#f59e0b', 3: '#f97316', 4: '#ef4444', 5: '#7c3aed'}
_LIT = ('elevated', 'high', 'surge')


def _lit_ripples(actor_summaries):
    """The ripple chain of every LIT actor (elevated or above), strongest first."""
    out = []
    for aid, rp in RIPPLES.items():
        s = actor_summaries.get(aid) or {}
        if s.get('level') in _LIT and ACTOR_VALIDATION.get(aid, {}).get('status') != 'unvalidated':
            out.append({'actor': aid, 'name': ACTORS[aid]['name'], 'level': s['level'],
                        'platform_level': LEVEL_TO_PLATFORM.get(s['level'], 2), **rp})
    out.sort(key=lambda r: -r['platform_level'])
    return out


def _prose(theatre_level, fronts, actor_summaries, tripwires, deal):
    sigs = []
    for t in tripwires[:4]:
        tid = t.get('id', 'tripwire')
        lv = TRIPWIRE_SIG_LEVEL.get(t.get('severity'), 2)
        sigs.append({'level': lv, 'severity': t.get('severity'), 'type': 'tripwire', 'priority': 10,
                     'category': 'tripwire', 'pressure_type': TRIPWIRE_AXIS.get(tid, 'kinetic'),
                     'theatre': 'drc', 'icon': '🚨', 'color': SIG_COLOR[lv],
                     'short_text': '%s DRC red line: %s' % (FLAG, tid.replace('_', ' ')),
                     'long_text': (TRIPWIRES.get(tid) or {}).get('note', '')})
    for fid, f in fronts.items():
        if f['level'] >= 3:
            sigs.append({'level': f['level'], 'type': 'front', 'priority': 9,
                         'category': 'kinetic_front', 'pressure_type': 'kinetic',
                         'standing': bool(f.get('standing')), 'front': fid,
                         'theatre': 'drc', 'icon': '💥', 'color': SIG_COLOR.get(f['level'], '#6b7280'),
                         'short_text': '%s DRC %s at L%d%s' % (
                             FLAG, f['name'], f['level'], ' (standing insurgency)' if f.get('standing') else ''),
                         'long_text': ('Worst report: "%s" (%s). %d outlets at this rung.%s'
                                       % ((f.get('worst') or {}).get('title', '')[:140],
                                          (f.get('worst') or {}).get('source', ''), f['outlets_at_level'],
                                          ' A standing insurgency: fighting here is the condition, not news.'
                                          if f.get('standing') else ''))})
    for aid in ('frn_m23', 'rwanda_axis', 'ebola', 'cobalt_copper', 'china_axis', 'us_axis', 'uganda_axis',
                'burundi_axis', 'monusco', 'conflict_minerals', 'uae_gold', 'tshisekedi_govt',
                'opposition_repression'):
        s = actor_summaries.get(aid) or {}
        if s.get('level') in _LIT and ACTOR_VALIDATION.get(aid, {}).get('status') != 'unvalidated':
            ta = (s.get('top_articles') or [{}])[0]
            lv = LEVEL_TO_PLATFORM.get(s['level'], 2)
            sigs.append({'level': lv, 'type': 'actor_signal', 'priority': 7,
                         'category': 'actor_signal', 'pressure_type': ACTOR_AXIS.get(aid, 'diplomatic'),
                         'theatre': 'drc', 'icon': ACTORS[aid]['icon'], 'color': SIG_COLOR.get(lv, '#6b7280'),
                         'short_text': '%s DRC %s at %s' % (FLAG, ACTORS[aid]['name'], s['level'].upper()),
                         'long_text': '"%s" (%s)' % (ta.get('title', '')[:160], ta.get('source', ''))})
    if deal['state'] in ('paper_only', 'fraying', 'collapsing', 'stalled'):
        sigs.append({'level': {'collapsing': 4, 'fraying': 3}.get(deal['state'], 2), 'type': 'deal_axis',
                     'priority': 8, 'category': 'actor_signal', 'pressure_type': 'diplomatic', 'theatre': 'drc',
                     'icon': '🖊️', 'color': SIG_COLOR[3 if deal['state'] in ('fraying', 'collapsing') else 2],
                     'short_text': '%s DRC deal vs ground: %s' % (FLAG, deal['state'].replace('_', ' ')),
                     'long_text': deal['reading']})
    sigs.sort(key=lambda x: -x.get('priority', 0))

    hot_fronts = [f['name'] for f in fronts.values() if f['level'] >= 3]
    parts = ['The DR Congo reads L%d (%s).' % (theatre_level, PLATFORM_LABELS.get(theatre_level, ''))]
    parts.append(('Fronts at L3 or above: %s.' % ', '.join(hot_fronts)) if hot_fronts
                 else 'No front reached L3 on two outlets this window.')
    parts.append('Deal vs ground: %s.' % deal['state'].replace('_', ' '))
    parts.append('Convergence read, not prediction.')

    lvl = lambda a: (actor_summaries.get(a) or {}).get('level')
    tw_ids = {t.get('id') for t in tripwires}
    so_what = []
    if deal['state'] in ('paper_only', 'fraying', 'collapsing'):
        so_what.append({'weight': 0.95, 'actor': 'washington_track', 'bullet': deal['reading'] + (
            ' Why it matters beyond the DRC: the Washington Accords are the only framework that binds Rwanda, and '
            'the wrapper around the US minerals partnership; if paper and ground keep diverging, both lose '
            'credibility at once.')})
    if any(f['level'] >= 3 and f.get('standing') for f in fronts.values()):
        so_what.append({'weight': 0.8, 'bullet': (
            'All three fronts are standing insurgencies: fighting there is the condition, not news. What would be '
            'news is a city taken (Uvira, Bunia, Butembo -- L5), the fighting reaching Kinshasa, or Rwandan and '
            'Burundian troops clashing directly.')})
    if lvl('ebola') in _LIT or tw_ids & {'ebola_new_frontier', 'health_response_attacked'}:
        so_what.append({'weight': 0.9, 'actor': 'ebola', 'bullet': (
            'Ebola is above baseline in a war zone. The provinces with the most cases (Ituri, North Kivu) are the '
            'provinces with the most fighting; every displacement is also a transmission route, and there is no '
            'licensed vaccine for this strain.')})
    if lvl('cobalt_copper') in _LIT or lvl('china_axis') in _LIT or 'cobalt_export_shock' in tw_ids:
        so_what.append({'weight': 0.85, 'actor': 'cobalt_copper', 'bullet': (
            'The minerals file is moving. Cobalt from Katanga goes into battery cathodes, jet-engine superalloys '
            'and hard metals, and most of it is refined in China: a move on quotas, prices or ownership here is '
            'felt in car plants and defence supply chains far from the eastern war.')})
    if lvl('us_axis') in _LIT or 'rwanda_sanctions' in tw_ids:
        so_what.append({'weight': 0.8, 'actor': 'us_axis', 'bullet': (
            'The US is above baseline. Washington is both the peace broker and a minerals customer: sanctions on '
            'Kigali and offtake from Katanga are two halves of one bet -- that pressure on Rwanda buys access to '
            'Congolese minerals that would otherwise flow to China.')})
    if lvl('rwanda_axis') in _LIT:
        so_what.append({'weight': 0.8, 'actor': 'rwanda_axis', 'bullet': (
            'Rwanda is above baseline. UN experts and the US government say Kigali backs M23 (Kigali denies it); '
            'the same state guards presidents in CAR and Mozambique -- pressure on it here is felt on its other '
            'spokes.')})
    if lvl('frn_m23') in _LIT:
        so_what.append({'weight': 0.8, 'actor': 'frn_m23', 'bullet': (
            'The FRN is above baseline. A former president leading an armed coalition turns a war over the east '
            'into a contest for the state -- read it alongside the constitutional fight in Kinshasa.')})
    if lvl('uganda_axis') in _LIT or lvl('burundi_axis') in _LIT or 'interstate_clash' in tw_ids:
        so_what.append({'weight': 0.75, 'actor': 'uganda_axis', 'bullet': (
            'Neighbours\' armies are in the news. Uganda (against the ADF) and Burundi (in South Kivu) both fight '
            'inside the DRC, and neither has relations with Rwanda it would call good: three armies, one '
            'battlefield.')})
    if lvl('monusco') in _LIT or 'monusco_mandate' in tw_ids:
        so_what.append({'weight': 0.75, 'actor': 'monusco', 'bullet': (
            'MONUSCO is in the news ahead of its 20 Dec 2026 mandate expiry. The FRN opposes renewal; the mission '
            'protects displacement sites in Ituri and verifies the Doha ceasefire.')})
    if lvl('tshisekedi_govt') in _LIT or tw_ids & {'constitutional_crisis', 'protest_repression'}:
        so_what.append({'weight': 0.7, 'actor': 'tshisekedi_govt', 'bullet': (
            'The constitutional fight is in the news: a referendum law the opposition reads as a path to a third '
            'term, during a war, with the FRN promising to resist it by "all means".')})
    if not so_what:
        so_what.append({'weight': 0.3, 'bullet': (
            'Nothing above baseline this scan. Baseline for the DRC still means three standing fronts, an Ebola '
            'emergency and two stalled peace tracks. A quiet scan is a quiet feed, not a quiet country.')})
    so_what.sort(key=lambda b: -b['weight'])
    return sigs[:10], ' '.join(parts), so_what[:6]


# ════════════════════════════════════════════════════════════
# SCORING (fixed-corpus testable)
# ════════════════════════════════════════════════════════════
FRONT_ACTORS = ['front_south_kivu', 'front_north_kivu', 'front_ituri', 'attacks_unplaced']
_NAMED_FRONTS = {'front_south_kivu', 'front_north_kivu', 'front_ituri'}
_TRACK_ACTORS = ('washington_track', 'doha_track')


def _gather(days):
    rss = fetch_all_rss()
    gdelt = fetch_all_gdelt(days)
    newsapi = fetch_newsapi(days)
    brave = fetch_brave(len(gdelt), len(newsapi))
    return rss, gdelt, newsapi, brave


def score_articles(articles):
    gated, rejected = [], 0
    gate_reasons = {'country': 0, 'brazzaville': 0, 'none': 0}
    for a in articles:
        ok, why = passes_country_gate(a)
        if ok:
            gate_reasons['country'] += 1
            gated.append(a)
        else:
            rejected += 1
            gate_reasons[why or 'none'] = gate_reasons.get(why or 'none', 0) + 1

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
            'ripple': RIPPLES.get(aid),
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

    track_arts, seen_u = [], set()
    for aid in _TRACK_ACTORS:
        for a in by_actor[aid]:
            if a.get('url') not in seen_u:
                seen_u.add(a.get('url'))
                track_arts.append(a)
    deal = _deal_axis(track_arts, fronts)

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
                          'No front ladder at L5. L5 needs a town, city or base taken, or Kinshasa attacked, '
                          'reported by two or more outlets. Tripwires and rhetoric volume cannot open it.')}
    return {'gated': gated, 'rejected': rejected, 'gate_reasons': gate_reasons,
            'actor_summaries': actor_summaries, 'tripwires': tripwires, 'fronts': fronts,
            'kinetic_level': kinetic_level, 'vector_levels': vector_levels,
            'vector_levels_platform': vector_levels_platform, 'theatre_level': theatre_level,
            'l5_gate': l5_gate, 'deal_axis': deal}


def _write_spokes(actor_summaries, theatre_level, deal, ts):
    """spoke:<hub>:drc for each wheel the DRC sits on."""
    written = []
    for hub, cfg in SPOKES.items():
        s = actor_summaries.get(cfg['actor']) or {}
        lvl = LEVEL_TO_PLATFORM.get(s.get('level', 'low'), 0)
        if ACTOR_VALIDATION.get(cfg['actor'], {}).get('status') == 'unvalidated':
            lvl = 0
        ta = (s.get('top_articles') or [{}])[0]
        if lvl >= 2 and ta.get('title'):
            top = 'DRC: %s at L%d -- "%s"' % (ACTORS[cfg['actor']]['name'], lvl, ta['title'][:110])
        elif s.get('article_count'):
            top = 'DRC: %s -- background mentions only (L%d).' % (ACTORS[cfg['actor']]['name'], lvl)
        else:
            top = 'DRC: no %s reporting this window. Unread, not calm.' % ACTORS[cfg['actor']]['name']
        payload = {'ts': ts, 'hub': hub, 'country': 'drc', 'level': lvl,
                   'node_class': cfg['node_class'], 'relationship': cfg['node_class'],
                   'top_signal': top[:180], 'why': cfg['why'], 'items': s.get('article_count', 0),
                   'theatre_level': theatre_level, 'deal_state': deal['state'],
                   'ripple_globe': (RIPPLES.get(cfg['actor']) or {}).get('globe'),
                   'source': 'rhetoric_tracker_drc v%s' % MODULE_VERSION}
        if _redis_set('spoke:%s:drc' % hub, payload, ttl_hours=SPOKE_TTL_HOURS):
            written.append(hub)
    if written:
        print('[DRC Rhetoric] spokes written: %s' % ', '.join(written))
    return written


def scan_drc_rhetoric(force=False, days=7):
    global _last_scan_started_at
    _last_scan_started_at = datetime.now(timezone.utc)
    t0 = time.time()
    print('[DRC Rhetoric] === scan start (force=%s days=%s) ===' % (force, days))
    rss, gdelt, newsapi, brave = _gather(days)
    seen, articles = set(), []
    for a in (rss + gdelt + newsapi + brave):
        u = a.get('url', '')
        if u and u not in seen:
            seen.add(u)
            articles.append(a)

    # RECENCY GATE: Google News search and Brave ignore the window; drop
    # anything older BEFORE the country gate and the ladders.
    try:
        from recency_gate import filter_recent
        articles, _recency = filter_recent(articles, days)
    except Exception as _e:
        _recency = {'error': 'recency gate failed open: %s' % str(_e)[:100]}
    _RECENCY_STATE['last'] = _recency
    print('[DRC Rhetoric] recency gate: %s' % _recency)

    S = score_articles(articles)
    actor_summaries, tripwires, fronts = S['actor_summaries'], S['tripwires'], S['fronts']
    theatre_level, deal = S['theatre_level'], S['deal_axis']
    humanitarian = _read_humanitarian_context()
    commodity = _read_commodity_context()
    amplifiers = _read_crosstheater_amplifiers()
    top_signals, executive_summary, so_what = _prose(theatre_level, fronts, actor_summaries, tripwires, deal)
    ripples_lit = _lit_ripples(actor_summaries)

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
        'success': True, 'country': 'drc', 'country_display': 'DR Congo',
        'module': 'rhetoric_tracker_drc', 'version': MODULE_VERSION, 'node_class': 'multi_wheel_spoke',
        'theatre_level': theatre_level, 'theatre_score': min(100, int(composite_score)),
        'theatre_label': PLATFORM_LABELS.get(theatre_level, 'Monitoring'),
        'composite_score': composite_score, 'kinetic_level': S['kinetic_level'], 'l5_gate': S['l5_gate'],
        'fronts': fronts, 'standing_fronts': [k for k, f in fronts.items() if f.get('standing')],
        'deal_axis': deal,
        'ripples_lit': ripples_lit, 'ripple_map': RIPPLES, 'ripples_as_of': RIPPLES_AS_OF,
        'ripple_note': ('Ripple chains are dated reference knowledge: what each actor TOUCHES at the scale of '
                        'the country, the region, the continent and the globe. They never score, and they say '
                        'what a move touches, not what will happen.'),
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
        'gate_note': ('An article must name the DR Congo or a DRC place, person or institution. "Congo" alone '
                      'passes only when the text is not about Brazzaville (the Republic of the Congo).'),
        'scan_time_seconds': round(time.time() - t0, 1), 'days_analyzed': days, 'recency': _recency,
        'last_updated': now, 'cached': False,
    }
    save_cache(result)
    _write_spokes(actor_summaries, theatre_level, deal, now)
    _redis_set(FINGERPRINT_KEY, {
        'ts': now, 'theatre': 'drc', 'country': 'drc', 'node_class': 'multi_wheel_spoke',
        'theatre_level': theatre_level, 'kinetic_level': S['kinetic_level'],
        'fronts': {k: {'level': f['level'], 'standing': f.get('standing')} for k, f in fronts.items()},
        'spokes': spokes, 'deal_state': deal['state'], 'tripwires': tripwires[:6],
    }, ttl_hours=14)
    try:
        _redis_lpush_trim(HISTORY_KEY, {
            'scanned_at': now, 'theatre_level': theatre_level, 'kinetic_level': S['kinetic_level'],
            'red_lines_count': len(tripwires), 'deal_state': deal['state'],
            **{k: v for k, v in S['vector_levels'].items()},
        }, max_len=336)
    except Exception as e:
        print('[DRC Rhetoric] history write failed: %s' % str(e)[:100])
    print('[DRC Rhetoric] done in %ss -- L%s (kinetic L%s), deal %s, gate %d/%d'
          % (result['scan_time_seconds'], theatre_level, S['kinetic_level'], deal['state'],
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
                scan_drc_rhetoric(force=True, days=7)
            finally:
                with _scan_lock:
                    _scan_running = False
            time.sleep(BACKGROUND_REFRESH_HOURS * 3600)
        except Exception as e:
            print('[DRC Rhetoric] background error: %s' % str(e)[:150])
            time.sleep(600)


def start_background_refresh():
    threading.Thread(target=_background_loop, daemon=True, name='DRCRhetoricBG').start()
    print('[DRC Rhetoric] background thread started (initial delay %ss)' % INITIAL_SCAN_DELAY_SECONDS)


def register_drc_rhetoric_routes(app, start_background=True):
    from flask import jsonify, request

    @app.route('/api/rhetoric/drc', methods=['GET', 'OPTIONS'])
    def api_drc_rhetoric():
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
                    threading.Thread(target=lambda: scan_drc_rhetoric(force=True), daemon=True).start()
            return jsonify(cached)
        return jsonify(scan_drc_rhetoric(force=force, days=7))

    @app.route('/api/rhetoric/drc/debug', methods=['GET'])
    def api_drc_rhetoric_debug():
        cached = load_cache()
        return jsonify({
            'module': 'rhetoric_tracker_drc v%s' % MODULE_VERSION,
            'actors': list(ACTORS.keys()), 'vectors': list(VECTOR_GROUPS.keys()),
            'spokes': list(SPOKES.keys()), 'tripwires': list(TRIPWIRES.keys()),
            'deal_states': list(DEAL_PATTERNS.keys()), 'ripples_for': list(RIPPLES.keys()),
            'l5_rule': 'Only a front kinetic ladder at L5 on two or more outlets.',
            'actor_validation': ACTOR_VALIDATION, 'validation_as_of': VALIDATION_AS_OF,
            'rss_feeds': len(RSS_FEEDS), 'redis_wired': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured': bool(NEWSAPI_KEY), 'brave_configured': bool(BRAVE_API_KEY),
            'recency_gate': _RECENCY_STATE['last'],
            'cache_present': cached is not None,
            'cache_fresh': is_cache_fresh(cached) if cached else False,
            'last_deal_state': (cached or {}).get('deal_axis', {}).get('state'),
            'last_scan_started_at': _last_scan_started_at.isoformat() if _last_scan_started_at else None,
            'background_running': _scan_running,
        })

    print('[DRC Rhetoric] endpoints registered: /api/rhetoric/drc, /api/rhetoric/drc/debug')
    if start_background:
        start_background_refresh()
