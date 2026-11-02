"""
Asifah Analytics -- Africa Signal Matcher v1.0.0
November 2, 2026   (Africa backend; used by the Mali, Somalia and Sudan rhetoric trackers)

WHY THIS EXISTS
  The Africa trackers scored articles with EXACT PHRASES: 'jnim attack',
  'embuscade mali', 'shabaab attack', 'uae drones rsf confirmed'. Real headlines
  almost never contain those strings word for word:
      "Mali : des terroristes neutralises par les FAMa dans le centre"
      "Ravitaillement massif a Bamako : un convoi de 596 citernes securise par les FAMa"
      "Al-Shabaab fighters attack army base near Mogadishu"
  Live read Nov 2 2026: Mali had a HEALTHY corpus (332 articles vs a 382
  baseline) and matched exactly one phrase ('aes'). Every vector read 0. That is
  a broken sensor reporting calm -- the failure the doctrine exists to prevent.
  Somalia's al-Shabaab and Sudan's UAE/Russia patron rows failed the same way.

WHAT IT DOES
  Two-part (co-occurrence) matching, the method that fixed Israel's outgoing
  reads in October: a rule fires when EVERY one of its term-groups is present in
  the same headline + summary. 'JNIM/GSIM/terroristes' + 'attaque/embuscade/tues'.
  English, French and Arabic in every ladder, plus a little Hausa where RFI
  Hausa carries Sahel news.

  * Text is normalised first: lowercase, accents stripped (securise = securise),
    curly apostrophes made straight. The tracker trigger lists used curly
    apostrophes; most feeds use straight ones, so those phrases never matched.
  * Latin terms match whole words; a term ending in '*' is a stem
    ('neutralis*' matches neutralise / neutralises / neutralisation).
    Acronym terms (FAMa, JNIM, GSIM, RSF, SAF, FLA...) also match whole words.
    Arabic terms match as substrings (Arabic attaches prefixes: wa-, bi-, al-).
  * CORROBORATION. A level of 3 or more needs at least two different outlets
    reporting at that level or higher. One outlet alone tops out at L2 (Warning),
    however dramatic its headline. Same 2+ source rule as the ME trackers.
  * This module ADDS a reading; it never lowers one. Each vector becomes
    max(old exact-phrase level, co-occurrence level). Every co-occurrence hit is
    recorded in matched_phrases as 'cooc:<vector>:L<n>:<rule>' so a reader can
    see why a level moved.
  * Actor credit: an article that fires a vector credits every actor the
    article names (tracker keywords + the extra aliases below), exactly as the
    trackers' own classifiers do. Malian state media call JNIM 'terroristes';
    that word lights the KINETIC vector but is never credited to JNIM as an
    actor -- 'terrorists' is not an attribution.

  Also here: corpus health for trackers that lack it (Somalia). A silence
  reading ("al-Shabaab is unusually quiet") is only meaningful if the corpus
  was healthy. On Nov 2 Somalia reported al-Shabaab 86% below baseline from a
  26-article corpus: the newsroom was quiet in our feeds, not al-Shabaab.
"""

import re
import unicodedata
from urllib.parse import urlparse

MATCHER_VERSION = '1.0.0'


# ----------------------------------------------------------------------------
# NORMALISATION + TERM MATCHING
# ----------------------------------------------------------------------------
def norm(text):
    t = str(text or '').replace('’', "'").replace('‘', "'").replace('ʼ', "'")
    t = unicodedata.normalize('NFKD', t)
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return t.lower()


_ARABIC = re.compile(r'[؀-ۿ]')
_RX_CACHE = {}


def _term_rx(term):
    rx = _RX_CACHE.get(term)
    if rx is None:
        t = norm(term)
        if _ARABIC.search(t):
            rx = re.compile(re.escape(t))
        elif t.endswith('*'):
            rx = re.compile(r"(?<![a-z0-9])" + re.escape(t[:-1]))
        else:
            rx = re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])")
        _RX_CACHE[term] = rx
    return rx


def has_any(ntext, terms):
    """ntext must already be norm()-ed."""
    for t in terms:
        if _term_rx(t).search(ntext):
            return t
    return None


def outlet_of(article):
    """Best-effort outlet name: Google News titles end ' - Outlet'."""
    title = str(article.get('title') or '')
    if ' - ' in title:
        tail = title.rsplit(' - ', 1)[1].strip()
        if 0 < len(tail) <= 60:
            return tail.lower()
    src = article.get('source')
    if isinstance(src, dict):
        src = src.get('name')
    src = str(src or '')
    if src and not src.lower().startswith(('googlenews', 'gdelt', 'rss')) and '%' not in src:
        return src.lower()
    host = urlparse(str(article.get('url') or '')).netloc.lower()
    return host.replace('www.', '') or 'unknown'


# ----------------------------------------------------------------------------
# SHARED TERM SETS
# ----------------------------------------------------------------------------
ATTACK = ['attack*', 'attaqu*', 'assault*', 'assaut*', 'raid*', 'incursion*', 'offensive*', 'stormed',
          'storm', 'overran', 'overrun*', 'hit', 'struck', 'targets', 'targeted', 'cibl*',
          'هجوم', 'هاجم', 'اقتحام', 'استهداف', 'hari', 'kai hari']
MASS = ['ambush*', 'embuscad*', 'convoy', 'convoi*', 'military camp', 'camp militaire', 'army base',
        'military base', 'base militaire', 'garrison', 'garnison', 'shot down', 'abattu', 'downed',
        'coordinated', 'coordonn*', 'simultan*', 'massacre*', 'suicide', 'car bomb', 'vbied',
        'كمين', 'مجزرة', 'انتحاري', 'سيارة مفخخة']
KILLED = ['killed', 'kills', 'kill', 'dead', 'death toll', 'tues', 'tuee', 'tuees', 'tue', 'morts', 'mort',
          'victimes', 'bilan', 'massacr*', 'executed', 'executes', 'beheaded',
          'قتل', 'قتلى', 'مقتل', 'مصرع', 'kashe', 'an kashe']
CLASH = ['clash*', 'fighting', 'fought', 'combats', 'combat', 'affrontement*', 'accrochage*', 'heurts',
         'gunfire', 'gunmen', 'firefight', 'اشتباك*', 'معارك', 'اشتباكات']
THREAT = ['threat*', 'menace*', 'warn*', 'vow*', 'ultimatum', 'kidnap*', 'enlev*', 'abduct*', 'hostage*',
          'otage*', 'تهديد', 'اختطاف', 'خطف']
STATE_OPS = ['neutralis*', 'neutraliz*', 'airstrike*', 'air strike*', 'frappe*', 'drone strike*',
             'operation*', 'ratissage*', 'offensive*', 'clearance', 'recaptur*', 'reprise', 'repris',
             'liberat*', 'killed', 'tues', 'destroy*', 'detruit*', 'kashe', 'غارة', 'غارات', 'عملية', 'تحييد']
SEIZE = ['captur*', 'seiz*', 'overran', 'overrun*', 'took control', 'takes control', 'take control',
         'falls', 'fell', 'fallen', 'tombe', 'tombee', 'chute', 'prise de', 'pris le controle',
         'sous le controle', 'سيطر*', 'سقوط', 'سيطرة']
ARMS = ['weapons', 'arms', 'armes', 'drones', 'drone', 'ammunition', 'munitions', 'airlift*', 'cargo',
        'supply', 'supplies', 'supplying', 'supplied', 'shipment*', 'deliver*', 'livraison*', 'livre',
        'equipment', 'equipement*', 'materiel', 'jets', 'aircraft',
        'أسلحة', 'سلاح', 'طائرات مسيرة', 'مسيرات', 'ذخيرة', 'إمداد', 'شحنات']
BASE = ['base', 'naval base', 'base navale', 'port', 'troops', 'troupes', 'soldiers', 'deploy*',
        'deploie*', 'instructors', 'instructeurs', 'military agreement', 'defence agreement',
        'defense agreement', 'accord de defense', 'accord militaire', 'قاعدة', 'قوات', 'نشر']


def _R(name, level, groups):
    return {'name': name, 'level': level, 'groups': groups}


# ----------------------------------------------------------------------------
# TRACKER PROFILES
#   ladders: vector -> [rules]; every group in a rule must be present.
#   actor_aliases: added to the tracker's own ACTOR_KEYWORDS for crediting.
#   escalatory: vectors that may raise an actor's escalation_level.
# ----------------------------------------------------------------------------
# ======================= MALI =======================
ML_INSURGENT = ['jnim', 'gsim', "jama'at nusrat*", 'jamaat nusrat*', 'nusrat al-islam', 'katiba*', 'macina',
                'jihadist*', 'djihadist*', 'terroristes', 'terroriste', 'terrorists', 'terrorist',
                'groupes armes', 'groupe arme', 'hommes armes', 'armed men', 'gunmen', 'insurg*',
                'fla', 'rebels', 'rebelles', 'separatist*', 'separatiste*', 'eigs', 'issp', 'isgs',
                'etat islamique', 'islamic state', 'daech', 'daesh',
                'جماعة نصرة الإسلام', 'نصرة الإسلام', 'إرهابي', 'الإرهابيين', 'مسلحين', 'مسلحون',
                'جهادي', 'داعش', 'أزواد', 'yan ta\'adda', "'yan ta'adda", 'masu ikirarin jihadi']
ML_PLACE = ['mali', 'malien*', 'bamako', 'kati', 'gao', 'kidal', 'mopti', 'sevare', 'segou', 'kayes',
            'tombouctou', 'timbuktu', 'menaka', 'nioro', 'koulikoro', 'sikasso', 'douentza', 'bandiagara',
            'tessalit', 'anefis', 'aguelhok', 'ber', 'diafarabe', 'macina', 'boni', 'hombori', 'ansongo',
            'boulkessi', 'nampala', 'dioura', 'niono', 'tenenkou', 'djenne', 'koutiala', 'bougouni', 'kolokani',
            'nara', 'lere', 'goundam', 'dire', 'tinzaouaten', 'tessit', 'intahaka', 'inekar', 'labbezanga',
            'ouatagouna', 'kidira', 'diboli', 'kita', 'kolondieba', 'yelimane', 'bafoulabe', 'diema',
            'مالي', 'باماكو', 'غاو', 'كيدال', 'تمبكتو']
ML_FAMA = ['fama', 'armee malienne', 'forces armees maliennes', 'malian army', 'malian armed forces',
           'malian troops', 'malian soldiers', 'soldats maliens', 'militaires maliens', 'military of mali',
           'الجيش المالي', 'القوات المالية', 'dakarun mali', 'sojojin mali']
ML_CAPITAL = ['bamako', 'kati', 'senou', 'kenieroba', 'باماكو']
ML_FUEL = ['carburant', 'fuel', 'citerne*', 'camion-citerne*', 'camions-citernes', 'tanker*', 'essence',
           'gasoil', 'gazole', 'hydrocarbure*', 'الوقود', 'صهاريج', 'محروقات']
ML_BLOCKADE = ['blocus', 'blockade', 'siege', 'encercl*', 'asphyxi*', 'routes coupees', 'axes coupes',
               'حصار']

MALI = {
    'ladders': {
        'kinetic': [
            _R('capital_attacked', 5, [ML_CAPITAL, ML_INSURGENT, ATTACK + SEIZE]),
            _R('garrison_lost', 5, [ML_INSURGENT, SEIZE, ['kidal', 'gao', 'tombouctou', 'timbuktu', 'mopti',
                                                         'sevare', 'menaka', 'segou', 'كيدال', 'غاو']]),
            _R('mass_attack', 4, [ML_INSURGENT, MASS + KILLED, ML_PLACE + ML_FAMA]),
            _R('aircraft_down', 4, [['helicoptere', 'helicopter', 'mi-24', 'mi-35', 'mi-8', 'avion', 'aircraft',
                                     'drone', 'hélicoptère', 'مروحية'],
                                    ['abattu', 'shot down', 'downed', 'crash*', 'ecrase', 'أسقط', 'اسقاط'],
                                    ML_PLACE + ML_FAMA]),
            _R('insurgent_attack', 3, [ML_INSURGENT, ATTACK, ML_PLACE + ML_FAMA]),
            _R('state_ops', 3, [ML_FAMA + ['africa corps', 'wagner'], STATE_OPS]),
            _R('clashes', 2, [CLASH, ML_PLACE + ML_FAMA + ML_INSURGENT]),
            _R('threat_kidnap', 2, [ML_INSURGENT, THREAT, ML_PLACE]),
            _R('insurgent_mention', 1, [ML_INSURGENT, ML_PLACE + ML_FAMA]),
        ],
        'blockade': [
            _R('capital_fuel_exhausted', 5, [ML_CAPITAL, ML_FUEL, ['epuise*', 'exhausted', 'run out', 'ran out',
                                                                  'rupture totale', 'paralys*', 'نفاد']]),
            _R('fuel_convoy_attacked', 4, [ML_FUEL, ATTACK + ['ambush*', 'embuscad*', 'كمين', 'incendi*', 'brule*', 'burn*', 'torched', 'detruit*',
                                                              'destroyed', 'احراق', 'حرق']]),
            _R('capital_fuel_shortage', 4, [ML_CAPITAL, ML_FUEL, ['penurie*', 'shortage*', 'pénurie', 'queues',
                                                                  'files d\'attente', 'rationn*', 'أزمة', 'نقص']]),
            _R('blockade_named', 3, [ML_BLOCKADE, ML_PLACE + ML_INSURGENT + ML_FUEL]),
            _R('escorted_fuel_convoys', 3, [ML_FUEL, ['convoi*', 'convoy*', 'escort*', 'securise*', 'secured',
                                                      'ravitaillement'], ML_FAMA + ML_CAPITAL]),
            _R('supply_strain', 2, [ML_FUEL + ['ravitaillement', 'approvisionnement', 'supply', 'supplies',
                                                'vivres', 'food'],
                                    ['penurie*', 'shortage*', 'hausse des prix', 'price*', 'prix', 'difficult*',
                                     'perturb*', 'disrupt*'], ML_PLACE]),
            _R('fuel_mention', 1, [ML_FUEL, ML_PLACE]),
        ],
        'insurgent_convergence': [
            _R('joint_operation', 4, [['fla', 'azawad', 'rebelles', 'rebels', 'أزواد'],
                                      ['jnim', 'gsim', 'jihadist*', 'djihadist*', 'نصرة الإسلام'],
                                      ['conjoint*', 'joint', 'ensemble', 'coordonn*', 'coordinat*', 'alliance',
                                       'allies', 'allied', 'together', 'تحالف', 'مشترك']]),
            _R('both_named', 3, [['fla', 'azawad', 'أزواد'], ['jnim', 'gsim', 'نصرة الإسلام']]),
        ],
        'hedging': [
            _R('alt_supplier_delivery', 4, [['turquie', 'turkey', 'turkish', 'turc*', 'bayraktar', 'akinci',
                                             'chine', 'china', 'chinese', 'emirats', 'uae', 'emirati*', 'maroc',
                                             'morocco', 'تركيا', 'الصين', 'الإمارات'],
                                            ['livraison*', 'livre', 'delivered', 'delivery', 'received', 'recoit',
                                             'recu*', 'signe*', 'signed', 'accord', 'agreement', 'تسليم', 'اتفاق'],
                                            ML_PLACE + ML_FAMA]),
            _R('alt_supplier_talks', 3, [['turquie', 'turkey', 'turkish', 'chine', 'china', 'emirats', 'uae',
                                          'maroc', 'morocco', 'algerie', 'algeria'],
                                         ['drones', 'armement', 'arms', 'weapons', 'cooperation militaire',
                                          'military cooperation', 'defense', 'defence', 'securite', 'security'],
                                         ML_PLACE + ML_FAMA]),
        ],
        'aes_cohesion': [
            _R('aes_rift', 4, [['aes', 'alliance des etats du sahel', 'alliance of sahel states',
                                'confederation'],
                               ['rupture', 'retrait', 'withdraw*', 'quitte', 'leaves', 'tension*', 'differend',
                                'dispute', 'crise', 'crisis', 'rift', 'split']]),
            _R('aes_joint_force', 3, [['aes', 'alliance des etats du sahel', 'alliance of sahel states',
                                       'confederation'],
                                      ['force unifiee', 'force conjointe', 'joint force', 'unified force',
                                       'operation conjointe', 'joint operation', 'deploy*', 'deploie*']]),
            _R('aes_summit', 2, [['aes', 'alliance des etats du sahel', 'alliance of sahel states'],
                                 ['sommet', 'summit', 'front uni', 'united front', 'reunion', 'meeting']]),
        ],
        'libya_corridor': [
            _R('corridor_logistics', 3, [['libye', 'libya', 'libyan', 'benghazi', 'haftar', 'maaten', 'kufra',
                                          'ليبيا', 'حفتر', 'بنغازي'],
                                         ['africa corps', 'wagner', 'russe*', 'russian', 'russia', 'روسيا', 'فاغنر'],
                                         ['sahel', 'mali', 'niger', 'burkina', 'ravitaillement', 'logisti*',
                                          'supply', 'flights', 'vols', 'الساحل', 'مالي']]),
            _R('corridor_mention', 2, [['libye', 'libya', 'haftar', 'ليبيا', 'حفتر'], ['sahel', 'mali', 'الساحل', 'مالي']]),
        ],
        'china_commercial': [
            _R('china_mining', 3, [['chine', 'china', 'chinese', 'chinois*', 'الصين'],
                                   ['mine*', 'mining', 'minier*', 'or', 'gold', 'lithium', 'concession*', 'تعدين'],
                                   ML_PLACE]),
        ],
    },
    'actor_aliases': {
        'jnim': ['gsim', "jama'at nusrat*", 'jamaat nusrat*', 'nusrat al-islam', 'katiba macina',
                 'groupe de soutien a l\'islam et aux musulmans', 'جماعة نصرة الإسلام', 'نصرة الإسلام والمسلمين'],
        'mali_junta': ML_FAMA + ['goita', 'transition malienne', 'gouvernement de transition', 'junte',
                                 'junta', 'bamako authorities', 'autorites maliennes', 'المجلس العسكري'],
        'africa_corps': ['africa corps', 'wagner', 'instructeurs russes', 'mercenaires russes', 'paramilitaires russes',
                         'russian mercenaries', 'russian paramilitar*', 'الفيلق الأفريقي', 'فاغنر'],
        'fla': ['fla', 'front de liberation de l\'azawad', 'azawad liberation front', 'rebelles touaregs',
                'tuareg rebels', 'جبهة تحرير أزواد'],
        'issp': ['eigs', 'etat islamique au sahel', 'etat islamique au grand sahara', 'islamic state sahel',
                 'is sahel', 'daech', 'daesh', 'داعش', 'الدولة الإسلامية'],
        'turkey_hedge': ['bayraktar', 'akinci', 'drones turcs', 'turkish drones', 'turquie'],
        'aes_bloc': ['aes', 'alliance des etats du sahel', 'alliance of sahel states', 'confederation des etats du sahel'],
        'libya_corridor': ['haftar', 'benghazi', 'kufra', 'maaten al-sarra'],
        'china_commercial': ['chine', 'chinois*', 'china', 'chinese'],
    },
    'escalatory': ['kinetic', 'blockade', 'insurgent_convergence', 'hedging', 'aes_cohesion',
                   'libya_corridor', 'china_commercial'],
}

# ======================= SOMALIA =======================
SO_SHABAAB = ['al-shabaab', 'al shabaab', 'shabaab', 'al-shabab', 'shabab', 'harakat al-shabaab', 'amniyat',
              'الشباب', 'حركة الشباب', 'الشباب المجاهدين']
SO_ISIS = ['isis', 'is-somalia', 'isis-somalia', 'islamic state', 'daesh', 'isis somalia', 'داعش',
           'الدولة الإسلامية']
SO_PLACE = ['somalia', 'somali', 'mogadishu', 'puntland', 'jubaland', 'kismayo', 'baidoa', 'beledweyne',
            'galmudug', 'hirshabelle', 'lower shabelle', 'middle shabelle', 'bakool', 'hiraan', 'gedo', 'bari',
            'bosaso', 'garowe', 'afgooye', 'afgoye', 'balcad', 'el baraf', 'mahaday', 'cal miskaad',
            'الصومال', 'مقديشو', 'بونتلاند', 'soomaaliya', 'muqdisho']
SO_GOV = ['somali army', 'somali national army', 'sna', 'somali forces', 'government forces', 'federal government',
          'villa somalia', 'somali government', 'hassan sheikh', 'danab', 'الجيش الصومالي', 'الحكومة الصومالية',
          'ciidamada']
SO_US = ['africom', 'u.s.', 'us military', 'us forces', 'american', 'united states', 'pentagon', 'us airstrike',
         'us strike', 'الأمريكي', 'أفريكوم']

SOMALIA = {
    'ladders': {
        'shabaab': [
            _R('capital_penetration', 5, [SO_SHABAAB, ['mogadishu', 'villa somalia', 'presidential palace',
                                                       'مقديشو', 'muqdisho'],
                                          ['siege', 'storm*', 'overran', 'captur*', 'seiz*', 'complex attack',
                                           'اقتحام', 'سيطرة']]),
            _R('town_captured', 5, [SO_SHABAAB, SEIZE, ['town', 'district', 'base', 'city', 'village*', 'مدينة',
                                                        'بلدة', 'قاعدة']]),
            _R('attack_casualties', 4, [SO_SHABAAB, ATTACK + MASS + ['bomb*', 'blast*', 'explosion*', 'ied',
                                                                     'mortar*', 'shell*', 'تفجير', 'انفجار',
                                                                     'قذائف'], KILLED + SO_PLACE]),
            _R('attack', 3, [SO_SHABAAB, ATTACK + ['bomb*', 'blast*', 'explosion*', 'mortar*', 'تفجير', 'انفجار']]),
            _R('state_ops_vs_shabaab', 3, [SO_SHABAAB, SO_GOV + SO_US + ['forces', 'troops', 'army'],
                                           STATE_OPS + CLASH]),
            _R('threat_or_massing', 3, [SO_SHABAAB, THREAT + ['massing', 'regroup*', 'mobilis*', 'mobiliz*',
                                                              'tax*', 'checkpoint*', 'حشد']]),
            _R('activity', 2, [SO_SHABAAB, ['statement', 'video', 'propaganda', 'recruit*', 'extort*', 'presence',
                                            'territory', 'claims', 'claimed', 'بيان', 'تبنى', 'تبنت']]),
            _R('mention', 1, [SO_SHABAAB]),
        ],
        'isis': [
            _R('isis_attack', 4, [SO_ISIS, ATTACK + MASS + KILLED, SO_PLACE]),
            _R('ops_vs_isis', 3, [SO_ISIS, STATE_OPS + CLASH, SO_PLACE + SO_US]),
            _R('isis_mention', 1, [SO_ISIS, SO_PLACE]),
        ],
        'africom': [
            _R('us_strike', 4, [SO_US, ['airstrike*', 'air strike*', 'strike*', 'drone strike*', 'bomb*',
                                        'غارة', 'غارات'], SO_SHABAAB + SO_ISIS + SO_PLACE]),
            _R('us_posture', 2, [SO_US, ['troops', 'deploy*', 'withdraw*', 'drawdown', 'base', 'baledogle',
                                         'قوات'], SO_PLACE]),
        ],
        'fracture': [
            _R('federal_fighting', 4, [['puntland', 'jubaland', 'gedo', 'ras kamboni', 'galmudug', 'khatumo',
                                        'sool', 'بونتلاند', 'جوبالاند'],
                                       ['federal', 'mogadishu', 'government forces', 'villa somalia', 'مقديشو'],
                                       CLASH + KILLED]),
            _R('federal_rupture', 3, [['puntland', 'jubaland', 'galmudug', 'hirshabelle', 'south west state',
                                       'بونتلاند', 'جوبالاند'],
                                      ['cut ties', 'severs', 'sever*', 'suspends cooperation', 'withdraws recognition',
                                       'rejects', 'standoff', 'parallel election', 'boycott*', 'troops', 'mobilis*',
                                       'mobiliz*', 'قطع', 'رفض']]),
            _R('election_dispute', 2, [['election*', 'mandate', 'term extension', 'one person one vote', 'انتخابات'],
                                       ['dispute*', 'crisis', 'opposition', 'protest*', 'boycott*', 'أزمة']]),
        ],
        'aussom': [
            _R('mission_collapse', 4, [['aussom', 'atmis', 'au mission', 'african union mission', 'peacekeep*'],
                                       ['withdraw*', 'exit', 'pull out', 'pulls out', 'collapse', 'unpaid',
                                        'no funding', 'funding gap', 'shortfall']]),
            _R('mission_strain', 3, [['aussom', 'atmis', 'au mission', 'african union mission'],
                                     ['funding', 'budget', 'drawdown', 'reduce*', 'gap', 'troop contribut*']]),
        ],
        'patron': [
            _R('foreign_military', 3, [['turkey', 'turkish', 'egypt', 'egyptian', 'uae', 'emirati', 'ethiopia',
                                        'ethiopian', 'qatar', 'russia', 'تركيا', 'مصر', 'الإمارات', 'إثيوبيا'],
                                       BASE + ARMS, SO_PLACE + ['somaliland', 'berbera']]),
            _R('foreign_diplomatic', 2, [['turkey', 'turkish', 'egypt', 'uae', 'ethiopia', 'qatar'],
                                         ['agreement', 'deal', 'visit*', 'talks', 'mou', 'اتفاق'], SO_PLACE]),
        ],
        'somaliland': [
            _R('recognition_move', 3, [['somaliland', 'أرض الصومال'],
                                       ['recogni*', 'recognition', 'الاعتراف', 'اعتراف'],
                                       ['israel', 'united states', 'u.s.', 'washington', 'ethiopia', 'taiwan',
                                        'uk', 'britain', 'إسرائيل', 'إثيوبيا']]),
            _R('recognition_talk', 2, [['somaliland', 'أرض الصومال'], ['recogni*', 'independence', 'sovereign*',
                                                                        'الاعتراف']]),
        ],
        'maritime': [
            _R('hijacking', 4, [['pirat*', 'hijack*', 'قراصنة', 'قرصنة', 'اختطاف'],
                                ['ship', 'vessel', 'tanker', 'dhow', 'bulk carrier', 'merchant', 'fishing boat',
                                 'سفينة'],
                                ['somali*', 'gulf of aden', 'puntland', 'eyl', 'horn of africa', 'خليج عدن']]),
            _R('piracy_risk', 3, [['pirat*', 'قرصنة'], ['somali*', 'gulf of aden', 'خليج عدن']]),
            _R('maritime_security', 2, [['atalanta', 'eunavfor', 'maritime security', 'naval patrol', 'coast guard'],
                                        ['somali*', 'gulf of aden']]),
        ],
    },
    'actor_aliases': {
        'al_shabaab': SO_SHABAAB,
        'isis_somalia': SO_ISIS,
        'us_africom': ['africom', 'us airstrike', 'us strike', 'us military', 'u.s. military', 'u.s. forces',
                       'pentagon', 'أفريكوم'],
        'federal_govt': SO_GOV,
        'member_states': ['puntland', 'jubaland', 'galmudug', 'hirshabelle', 'south west state', 'بونتلاند'],
        'aussom': ['aussom', 'atmis', 'au mission', 'african union mission'],
        'foreign_patrons': ['turkish', 'turkey', 'egyptian troops', 'emirati', 'ethiopian troops', 'تركيا'],
    },
    'escalatory': ['shabaab', 'isis', 'fracture', 'aussom', 'africom', 'patron', 'somaliland', 'maritime'],
}

# ======================= SUDAN =======================
SD_RSF = ['rsf', 'rapid support forces', 'rapid support force', 'hemedti', 'hemeti', 'dagalo', 'tasis', 'janjaweed',
          'forces de soutien rapide', 'fsr', 'الدعم السريع', 'حميدتي', 'الجنجويد', 'تأسيس']
SD_SAF = ['saf', 'sudanese armed forces', 'sudanese army', 'sudan army', 'burhan', 'port sudan government',
          'armee soudanaise', 'الجيش السوداني', 'القوات المسلحة', 'البرهان']
SD_PLACE = ['sudan', 'sudanese', 'darfur', 'kordofan', 'khartoum', 'omdurman', 'el fasher', 'el-fasher', 'al-fashir',
            'el obeid', 'babanusa', 'kadugli', 'dilling', 'port sudan', 'wad madani', 'sennar', 'nyala', 'zalingei',
            'السودان', 'دارفور', 'كردفان', 'الخرطوم', 'الفاشر', 'الأبيض', 'بورتسودان', 'نيالا']
SD_UAE = ['uae', 'emirat*', 'emirati*', 'abu dhabi', 'united arab emirates', 'الإمارات', 'إماراتي*', 'أبوظبي']
SD_RU = ['russia', 'russian', 'moscow', 'kremlin', 'africa corps', 'wagner', 'روسيا', 'روسي*', 'موسكو', 'فاغنر']
SD_PATRONS = ['egypt', 'egyptian', 'saudi', 'turkey', 'turkish', 'iran', 'iranian', 'qatar',
              'مصر', 'المصري', 'السعودية', 'تركيا', 'التركي', 'إيران', 'الإيراني']

SUDAN = {
    'ladders': {
        'kinetic': [
            _R('city_falls', 5, [['el fasher', 'el-fasher', 'al-fashir', 'el obeid', 'babanusa', 'kadugli', 'dilling',
                                  'omdurman', 'khartoum', 'wad madani', 'الفاشر', 'الأبيض', 'بابنوسة', 'كادقلي'],
                                 SEIZE + ['massacre*', 'مجزرة']]),
            _R('mass_atrocity', 5, [SD_RSF + SD_SAF, ['massacre*', 'genocide', 'ethnic cleansing', 'mass killing*',
                                                      'مجزرة', 'إبادة'], SD_PLACE]),
            _R('attack_casualties', 4, [SD_RSF + SD_SAF, ATTACK + MASS + ['drone*', 'shell*', 'bombard*', 'مسيرة',
                                                                           'قصف'], KILLED]),
            _R('attack', 3, [SD_RSF + SD_SAF, ATTACK + ['drone strike*', 'shell*', 'bombard*', 'قصف', 'مسيرة']]),
            _R('clashes', 2, [CLASH, SD_RSF + SD_SAF + SD_PLACE]),
        ],
        'uae_axis': [
            _R('uae_arms_rsf', 4, [SD_UAE, SD_RSF, ARMS]),
            _R('uae_rsf_link', 3, [SD_UAE, SD_RSF]),
            _R('uae_sudan', 2, [SD_UAE, SD_PLACE + SD_SAF]),
        ],
        'russia_plug': [
            _R('russia_base_or_arms', 4, [SD_RU, ['naval base', 'base navale', 'port sudan', 'red sea', 'بورتسودان',
                                                  'قاعدة', 'البحر الأحمر'] + ARMS, SD_PLACE + SD_SAF]),
            _R('russia_sudan_deal', 3, [SD_RU, ['agreement', 'accord', 'deal', 'treaty', 'cooperation', 'اتفاق'],
                                        SD_PLACE + SD_SAF]),
            _R('russia_sudan', 2, [SD_RU, SD_PLACE + SD_SAF]),
        ],
        'saf_patron': [
            _R('patron_arms_saf', 4, [SD_PATRONS, SD_SAF, ARMS + ['airstrike*', 'jets', 'bayraktar', 'akinci']]),
            _R('patron_support_saf', 3, [SD_PATRONS, SD_SAF, ['support*', 'backing', 'backs', 'ally', 'allies',
                                                               'دعم', 'يدعم']]),
        ],
        'spillover_west': [
            _R('chad_fighting', 3, [['chad', 'chadian', 'tchad', 'tine', 'adre', 'تشاد'],
                                    CLASH + ATTACK + ['incursion', 'cross-border', 'transfrontal*']]),
            _R('chad_border', 2, [['chad', 'chadian', 'tchad', 'تشاد'],
                                  ['border', 'frontiere', 'refugee*', 'refugie*', 'rsf', 'darfur', 'الحدود', 'لاجئين']]),
        ],
        'spillover_south': [
            _R('south_fighting', 3, [['south sudan', 'juba', 'heglig', 'abyei', 'جنوب السودان', 'هجليج'],
                                     CLASH + ATTACK + ['pipeline', 'oil field*', 'خط أنابيب']]),
            _R('south_link', 2, [['south sudan', 'juba', 'abyei', 'جنوب السودان'],
                                 ['oil', 'pipeline', 'border', 'refugee*', 'rsf', 'نفط']]),
        ],
        'libya_haftar': [
            _R('haftar_supply', 4, [['haftar', 'libya', 'libyan', 'kufra', 'حفتر', 'ليبيا', 'الكفرة'], SD_RSF, ARMS +
                                    ['fuel', 'corridor', 'route', 'وقود']]),
            _R('haftar_rsf', 3, [['haftar', 'kufra', 'حفتر', 'الكفرة'], SD_RSF]),
        ],
    },
    'actor_aliases': {
        'rsf_hemedti': SD_RSF,
        'saf_burhan': ['saf', 'sudanese armed forces', 'sudanese army', 'burhan', 'الجيش السوداني', 'البرهان'],
        'uae_axis': SD_UAE,
        'russia_africa_corps': SD_RU,
        'saf_patrons': SD_PATRONS,
        'libya_haftar': ['haftar', 'kufra', 'حفتر', 'الكفرة'],
        'chad_border': ['chad', 'tchad', 'تشاد'],
        'south_sudan_corridor': ['south sudan', 'juba', 'heglig', 'جنوب السودان'],
    },
    'escalatory': ['kinetic', 'russia_plug', 'uae_axis', 'saf_patron', 'spillover_south', 'spillover_west',
                   'libya_haftar'],
}

PROFILES = {'mali': MALI, 'somalia': SOMALIA, 'sudan': SUDAN}


# ----------------------------------------------------------------------------
# CORE
# ----------------------------------------------------------------------------
def fire_rules(ntext, rules):
    """-> (level, rule_name, evidence terms) for the highest rule that fires, else (0, None, None)."""
    for r in sorted(rules, key=lambda x: -x['level']):
        hits = []
        for g in r['groups']:
            h = has_any(ntext, g)
            if not h:
                break
            hits.append(h)
        else:
            return r['level'], r['name'], hits
    return 0, None, None


def corroborated_level(levels_by_outlet):
    """levels_by_outlet: {outlet: max level}. L3+ needs 2 outlets at >= L; one outlet tops out at L2."""
    for L in range(5, 0, -1):
        n = sum(1 for v in levels_by_outlet.values() if v >= L)
        if n >= (2 if L >= 3 else 1):
            return L
    return 0


def apply_cooccurrence(tracker, articles, actor_results, summary, actor_keywords):
    """Raise vector maxima and actor levels with co-occurrence reads. Mutates in place.

    summary:        the tracker's theatre summary dict ({vector}_max, matched_phrases?, vector_signals?)
    actor_results:  {actor_id: {..., '{vector}_score', 'escalation_level', 'statement_count', 'top_articles'}}
    actor_keywords: the tracker's own ACTOR_KEYWORDS (plain lowercase substrings)
    Returns a report dict for the payload (`cooccurrence`).
    """
    prof = PROFILES[tracker]
    ladders = prof['ladders']
    escal = set(prof['escalatory'])
    aliases = prof['actor_aliases']
    per_vec_outlets = {v: {} for v in ladders}
    per_vec_rule = {v: {} for v in ladders}
    examples = {v: [] for v in ladders}
    added_statements = 0
    actor_hits = {}

    for a in articles:
        raw = f"{a.get('title', '')} {a.get('description', '')}"
        low = raw.lower()
        nt = norm(raw)
        outlet = outlet_of(a)
        fired = {}
        for v, rules in ladders.items():
            lvl, rname, ev = fire_rules(nt, rules)
            if lvl:
                fired[v] = lvl
                prev = per_vec_outlets[v].get(outlet, 0)
                if lvl > prev:
                    per_vec_outlets[v][outlet] = lvl
                per_vec_rule[v][lvl] = per_vec_rule[v].get(lvl) or rname
                if len(examples[v]) < 5 and lvl >= 2:
                    examples[v].append({'level': lvl, 'rule': rname, 'evidence': ev,
                                        'title': str(a.get('title', ''))[:140], 'outlet': outlet,
                                        'url': a.get('url', ''), 'published': a.get('published', '')})
        # actors named in this article (tracker keywords OR extra aliases)
        named = []
        for aid in actor_results:
            own = any(str(kw).lower() in low for kw in (actor_keywords.get(aid) or []))
            extra = bool(has_any(nt, aliases.get(aid, [])))
            if own or extra:
                named.append(aid)
                if extra and not own:
                    actor_results[aid]['statement_count'] = actor_results[aid].get('statement_count', 0) + 1
                    added_statements += 1
        for aid in named:
            for v, lvl in fired.items():
                actor_hits.setdefault(aid, {}).setdefault(v, {})
                d = actor_hits[aid][v]
                d[outlet] = max(d.get(outlet, 0), lvl)
            if fired and len(actor_results[aid].get('top_articles', [])) < 8:
                actor_results[aid].setdefault('top_articles', []).append({
                    'title': str(a.get('title', ''))[:120], 'url': a.get('url', ''),
                    'source': a.get('source', 'Unknown') if not isinstance(a.get('source'), dict) else
                    a['source'].get('name', 'Unknown'),
                    'source_type': a.get('source_type', 'news'),
                    'published': a.get('published', '') if isinstance(a.get('published', ''), str) else '',
                    'escalation_level': max(fired.values()), 'via': 'cooccurrence'})

    report = {'version': MATCHER_VERSION, 'vectors': {}, 'added_actor_statements': added_statements}
    matched = summary.get('matched_phrases')
    for v in ladders:
        L = corroborated_level(per_vec_outlets[v])
        raw_peak = max(per_vec_outlets[v].values()) if per_vec_outlets[v] else 0
        key = f'{v}_max'
        before = summary.get(key, 0) or 0
        if L > before:
            summary[key] = L
        report['vectors'][v] = {'cooc_level': L, 'raw_peak': raw_peak, 'outlets': len(per_vec_outlets[v]),
                                'before': before, 'after': summary.get(key, 0), 'examples': examples[v],
                                'held_back_for_corroboration': raw_peak > L}
        if L and isinstance(matched, (set, list)):
            tag = f"cooc:{v}:L{L}:{per_vec_rule[v].get(L) or per_vec_rule[v].get(raw_peak) or 'rule'}"
            matched.add(tag) if isinstance(matched, set) else matched.append(tag)
        vs = summary.get('vector_signals')
        if isinstance(vs, dict) and v in vs and isinstance(vs[v], list):
            for ex in examples[v]:
                if len(vs[v]) < 5:
                    vs[v].append({'title': ex['title'], 'level': ex['level'], 'url': ex['url'],
                                  'published': ex['published']})

    for aid, vecs in actor_hits.items():
        ar = actor_results[aid]
        for v, outlets in vecs.items():
            L = corroborated_level(outlets)
            f = f'{v}_score'
            if f in ar and L > (ar.get(f) or 0):
                ar[f] = L
            if v in escal and L > (ar.get('escalation_level') or 0):
                ar['escalation_level'] = L
    return report


# ----------------------------------------------------------------------------
# CORPUS HEALTH (for trackers that lack it -- Somalia)
# ----------------------------------------------------------------------------
CORPUS_FLOOR = 40          # absolute: below this a 3-day corpus cannot carry a silence read
CORPUS_DEGRADED_RATIO = 0.40


def assess_corpus(tracker, n, redis_get, redis_set):
    """-> {'status': ok|degraded|accumulating, 'article_count', 'baseline', 'note'}; rolls the baseline."""
    key = f'rhetoric:{tracker}:corpus_baseline'
    try:
        b = redis_get(key) or {'avg': 0, 'scans': 0}
    except Exception:
        b = {'avg': 0, 'scans': 0}
    avg, scans = float(b.get('avg') or 0), int(b.get('scans') or 0)
    if n < CORPUS_FLOOR:
        status = 'degraded'
        note = (f'Corpus at {n} articles -- below the {CORPUS_FLOOR}-article floor. Silence reads are suppressed: '
                'a thin corpus makes every actor look quiet.')
    elif scans >= 3 and avg and n < avg * CORPUS_DEGRADED_RATIO:
        status = 'degraded'
        note = (f'Corpus at {n} articles vs a rolling baseline of {avg:.0f} ({n / avg:.0%}). '
                'Silence reads are suppressed.')
    elif scans < 3:
        status = 'accumulating'
        note = f'Corpus {n} articles; baseline still accumulating ({scans}/3 scans).'
    else:
        status = 'ok'
        note = f'Corpus healthy: {n} articles vs baseline {avg:.0f}.'
    if status != 'degraded' or scans < 3:
        try:
            new_avg = n if not scans else (avg * min(scans, 20) + n) / (min(scans, 20) + 1)
            redis_set(key, {'avg': round(new_avg, 1), 'scans': scans + 1})
        except Exception:
            pass
    return {'status': status, 'article_count': n, 'baseline': round(avg, 1), 'note': note}
