"""
africa_article_gatherer.py
Asifah Analytics -- Africa Backend Module
v1.0.0 -- May 25, 2026

AFRICA-SPECIFIC ARTICLE GATHERER

Mirrors the canonical ME humanitarian_article_gatherer.py writer/reader pattern,
adapted for Africa stability pages. Builds PER-COUNTRY article pools every 12h.

Per-country Redis keys allow the stability pages to fetch their own articles
directly without filtering a shared pool downstream.

SOURCES PER COUNTRY:
  RSS (Tier 1: Africa-canonical aggregators)
    - ReliefWeb (UN OCHA) - country-filtered
    - The New Humanitarian (Africa beat)
    - Al Jazeera Africa
    - Reuters Africa
    - WHO Regional Office for Africa (DRC Ebola, Marburg, cholera, etc.)
  RSS (Tier 2: country-specific Google News)
    - Per-country news + military + politics + humanitarian queries
  RSS (Tier 3: regional NGO/think-tank feeds)
    - ISS Africa (Institute for Security Studies)
    - ACSS (Africa Center for Strategic Studies)
    - Crisis Group Africa
  GDELT (medium cost, broad reach):
    - Per-country English + French (where applicable) queries
  Brave Search (last-resort, quota-managed):
    - Per-country supplemental sub-region queries
    - Cached 12h to preserve 2000/mo quota

ARTICLE BUCKETING (for the 3-tab stability page UI):
  - news     -> RSS + GDELT + Brave (mainstream news)
  - socials  -> Bluesky + Reddit + Telegram (PLACEHOLDER for v1.0; wire in v1.1)
  - ngos     -> ReliefWeb + ISS + Crisis Group + WHO (humanitarian/policy)

COUNTRIES COVERED (14 Tier-1 alphabetical):
  burkina_faso, drc, ethiopia, kenya, mali, niger, nigeria, rwanda, somalia,
  south_africa, south_sudan, sudan, tanzania, uganda

REDIS KEYS:
  africa:articles:<country>     -- canonical per-country article pool (12h TTL)
  africa:articles:lastrun       -- last run timestamp (for diagnostics)
  africa:articles:metrics       -- last run metrics (article counts per country)
  africa:articles:brave:<query> -- per-query Brave cache (12h TTL)

ENDPOINTS:
  GET /api/africa/articles/<country>          Per-country bucketed articles
  GET /api/africa/articles/scan?force=true    Manually trigger fresh scan
  GET /api/africa/articles/health             Health + last run + per-country counts

SCHEDULE:
  Auto-runs every 12 hours via threading (matches Asifah canonical pattern).

Author: RCGG / Asifah Analytics
"""

import os
import json
import time
import threading
import traceback
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests


# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
BRAVE_API_KEY       = os.environ.get('BRAVE_API_KEY', '')
GDELT_BASE_URL      = 'https://api.gdeltproject.org/api/v2/doc/doc'
BRAVE_BASE_URL      = 'https://api.search.brave.com/res/v1/news/search'

# Redis cache keys
ARTICLES_KEY_PREFIX = 'africa:articles:'      # africa:articles:<country>
LASTRUN_KEY         = 'africa:articles:lastrun'
METRICS_KEY         = 'africa:articles:metrics'
BRAVE_CACHE_PREFIX  = 'africa:articles:brave:'

# Cache TTLs
ARTICLES_CACHE_TTL  = 12 * 3600     # 12 hours
BRAVE_CACHE_TTL     = 12 * 3600     # 12 hours
SCAN_INTERVAL_HOURS = 12

# Scan tuning
RSS_TIMEOUT         = 12
GDELT_TIMEOUT       = 25
BRAVE_TIMEOUT       = 10
GDELT_MIN_RESULTS   = 3             # threshold below which Brave fallback kicks in
GDELT_INTER_QUERY_DELAY = 0.5       # 429-defense pacing between GDELT calls
MAX_ARTICLES_PER_COUNTRY = 60       # cap to keep payloads manageable
ARTICLE_AGE_DAYS_KEEP = 14          # discard articles older than 14 days

# Global state for scheduler
_gatherer_running = False
_gatherer_lock    = threading.Lock()


# ============================================================
# REDIS HELPERS (canonical Asifah Upstash REST pattern)
# ============================================================
def _redis_get(key):
    """Direct Upstash REST GET."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        if not resp.ok:
            return None
        data = resp.json()
        raw = data.get('result')
        if raw is None:
            return None
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return raw
    except Exception as e:
        print(f"[africa_articles] Redis GET error ({key}): {str(e)[:80]}")
        return None


def _redis_set(key, value, ttl=ARTICLES_CACHE_TTL):
    """Direct Upstash REST SET with EX param."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str) if not isinstance(value, str) else value
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/set/{key}",
            headers={
                "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                "Content-Type":  "application/json",
            },
            data=payload,
            params={"EX": ttl} if ttl else {},
            timeout=5,
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f"[africa_articles] Redis SET error ({key}): {str(e)[:80]}")
        return False


# ============================================================
# COUNTRY ROSTER + METADATA
# ============================================================
# Each country gets:
#   - display_name (for log readability)
#   - gdelt_terms  (canonical search expressions; OR-joined)
#   - sub_themes   (for Google News + Brave fallback supplemental queries)
#   - capital      (helps disambiguate Niger/Nigeria, Sudan/South Sudan, etc.)
#   - franco       (True if French is a relevant search language)

COUNTRY_CONFIG = {
    'burkina_faso': {
        'display_name': 'Burkina Faso',
        'gdelt_terms':  '"Burkina Faso" OR Ouagadougou OR Burkinabe',
        'sub_themes':   ['JNIM', 'VDP', 'Sahel jihadist', 'Russia Africa Corps Burkina', 'Traore'],
        'capital':      'Ouagadougou',
        'franco':       True,
    },
    'drc': {
        'display_name': 'DR Congo',
        'gdelt_terms':  '"DR Congo" OR "Democratic Republic of Congo" OR Kinshasa OR FARDC',
        'sub_themes':   ['M23 Goma', 'AFC Nangaa', 'Ituri ADF', 'Tshisekedi', 'cobalt Congo', 'Ebola DRC'],
        'capital':      'Kinshasa',
        'franco':       True,
    },
    'ethiopia': {
        'display_name': 'Ethiopia',
        'gdelt_terms':  'Ethiopia OR "Addis Ababa" OR ENDF',
        'sub_themes':   ['Tigray Pretoria', 'Amhara Fano', 'Oromia OLA', 'Abiy Ahmed', 'GERD dam'],
        'capital':      'Addis Ababa',
        'franco':       False,
    },
    'kenya': {
        'display_name': 'Kenya',
        'gdelt_terms':  'Kenya OR Nairobi OR KDF',
        'sub_themes':   ['Al-Shabaab Kenya', 'Garissa', 'KDF Somalia', 'KDF DRC', 'Haiti MSS', 'Ruto'],
        'capital':      'Nairobi',
        'franco':       False,
    },
    'mali': {
        'display_name': 'Mali',
        'gdelt_terms':  'Mali OR Bamako OR FAMa',
        'sub_themes':   ['Wagner Mali', 'JNIM Mali', 'Tinzaouaten', 'AES Sahel', 'Goita junta'],
        'capital':      'Bamako',
        'franco':       True,
    },
    'niger': {
        'display_name': 'Niger',
        'gdelt_terms':  'Niger OR Niamey OR "Air Base 201"',
        'sub_themes':   ['Tchiani junta', 'JNIM Tillaberi', 'Russia Africa Corps Niger', 'CNSP Niger', 'AES Niger'],
        'capital':      'Niamey',
        'franco':       True,
    },
    'nigeria': {
        'display_name': 'Nigeria',
        'gdelt_terms':  'Nigeria OR Abuja OR "Nigerian Army"',
        'sub_themes':   ['Boko Haram', 'ISWAP', 'Lakurawa', 'Tinubu Nigeria', 'Plateau attack', 'bandit Nigeria'],
        'capital':      'Abuja',
        'franco':       False,
    },
    'rwanda': {
        'display_name': 'Rwanda',
        'gdelt_terms':  'Rwanda OR Kigali OR RDF',
        'sub_themes':   ['Kagame Rwanda', 'M23 Rwanda', 'Rwanda DRC tension', 'Rwanda UN tribunal'],
        'capital':      'Kigali',
        'franco':       True,
    },
    'somalia': {
        'display_name': 'Somalia',
        'gdelt_terms':  'Somalia OR Mogadishu OR "Al-Shabaab"',
        'sub_themes':   ['ATMIS AUSSOM', 'ISIS Somalia Puntland', 'Hassan Sheikh Mohamud', 'Turkey Somalia', 'piracy Somalia'],
        'capital':      'Mogadishu',
        'franco':       False,
    },
    'south_africa': {
        'display_name': 'South Africa',
        'gdelt_terms':  '"South Africa" OR Johannesburg OR Pretoria OR SANDF',
        'sub_themes':   ['ANC Ramaphosa', 'SAMIDRC withdrawal', 'load shedding', 'BRICS South Africa'],
        'capital':      'Pretoria',
        'franco':       False,
    },
    'south_sudan': {
        'display_name': 'South Sudan',
        'gdelt_terms':  '"South Sudan" OR Juba OR Kiir OR Machar',
        'sub_themes':   ['South Sudan elections', 'R-ARCSS', 'Riek Machar', 'UNMISS', 'South Sudan oil'],
        'capital':      'Juba',
        'franco':       False,
    },
    'sudan': {
        'display_name': 'Sudan',
        'gdelt_terms':  'Sudan OR Khartoum OR "RSF Sudan" OR "Sudanese Armed Forces"',
        'sub_themes':   ['Darfur famine', 'El Fasher siege', 'Hemedti Burhan', 'RSF Sudan', 'Sudan UAE', 'Sennar Wad Madani'],
        'capital':      'Khartoum',
        'franco':       False,
    },
    'tanzania': {
        'display_name': 'Tanzania',
        'gdelt_terms':  'Tanzania OR "Dar es Salaam" OR Dodoma OR TPDF',
        'sub_themes':   ['Suluhu Hassan', 'CCM Tanzania', 'Tanzania Mozambique gas', 'Tanzania Kenya port'],
        'capital':      'Dodoma',
        'franco':       False,
    },
    'uganda': {
        'display_name': 'Uganda',
        'gdelt_terms':  'Uganda OR Kampala OR UPDF',
        'sub_themes':   ['Museveni Uganda', 'ADF Uganda', 'UPDF DRC', 'Uganda anti-LGBTQ law'],
        'capital':      'Kampala',
        'franco':       False,
    },
}


# ============================================================
# CONTINENT-WIDE RSS FEEDS (humanitarian + Africa-focused)
# These are scanned ONCE per cycle, then articles are matched to
# countries by keyword presence in title/description.
# ============================================================
AFRICA_WIDE_RSS_FEEDS = [
    # Tier 1: humanitarian aggregators (country-filterable)
    ("https://reliefweb.int/updates/rss.xml",                              1.2, "ngos"),
    ("https://www.thenewhumanitarian.org/rss/all",                         1.1, "ngos"),
    # Tier 2: UN agency specialists (Africa-relevant)
    ("https://www.wfp.org/rss/news",                                       1.05, "ngos"),
    ("https://www.unicef.org/press-releases/rss.xml",                      1.0,  "ngos"),
    ("https://www.unhcr.org/rss/news.xml",                                 1.0,  "ngos"),
    # Tier 3: Africa generalist outlets
    ("https://www.aljazeera.com/xml/rss/all.xml",                          0.95, "news"),
    ("https://feeds.reuters.com/reuters/africaNews",                       0.95, "news"),
    # Tier 4: ISS Africa + ACSS think-tank feeds
    ("https://issafrica.org/rss/topics/southern-africa.xml",               0.9,  "ngos"),
    ("https://issafrica.org/rss/topics/east-africa.xml",                   0.9,  "ngos"),
    ("https://issafrica.org/rss/topics/west-africa.xml",                   0.9,  "ngos"),
    ("https://issafrica.org/rss/topics/horn-of-africa.xml",                0.9,  "ngos"),
    # Tier 5: WHO Africa region health feeds
    ("https://news.google.com/rss/search?q=%22WHO+Africa%22+OR+%22WHO+AFRO%22+outbreak&hl=en&gl=US&ceid=US:en",  1.0, "ngos"),
    # Tier 6: ICG (International Crisis Group) Africa
    ("https://www.crisisgroup.org/crisiswatch/feed.xml",                   0.95, "ngos"),
]


# ============================================================
# GDELT QUERY BUILDERS (per-country)
# ============================================================
def build_gdelt_queries(country_id):
    """Build GDELT queries for one country, in English + French if applicable."""
    cfg = COUNTRY_CONFIG[country_id]
    queries = []
    # English: main + capital + military
    queries.append((cfg['gdelt_terms'], 'eng'))
    queries.append((f'{cfg["capital"]} attack OR military OR election OR crisis', 'eng'))
    # French where applicable
    if cfg['franco']:
        # GDELT lang param: 'fre' (not 'fra')
        franco_query = cfg['gdelt_terms'].replace('"', '')
        queries.append((franco_query, 'fre'))
    return queries


def build_brave_queries(country_id):
    """Build Brave Search fallback queries for one country (sub-themes)."""
    cfg = COUNTRY_CONFIG[country_id]
    queries = []
    for theme in cfg['sub_themes']:
        queries.append(f'{cfg["display_name"]} {theme} 2026')
    return queries


# ============================================================
# RSS FETCH
# ============================================================
def _parse_rss_date(date_str):
    """Parse common RSS date formats into ISO. Returns None on failure."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def _fetch_rss_feed(url, weight=1.0, bucket='news'):
    """Fetch one RSS feed, return list of article dicts."""
    articles = []
    try:
        headers = {
            'User-Agent': 'Asifah-Analytics/1.0 (+https://asifahanalytics.com)',
            'Accept':     'application/rss+xml, application/xml, text/xml, */*',
        }
        resp = requests.get(url, headers=headers, timeout=RSS_TIMEOUT)
        if resp.status_code != 200:
            print(f"[africa_articles] RSS HTTP {resp.status_code} on {url[:60]}")
            return articles

        # Parse XML
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            print(f"[africa_articles] RSS parse error on {url[:60]}: {str(e)[:80]}")
            return articles

        # Handle both RSS 2.0 and Atom
        items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
        for item in items[:50]:   # cap per feed
            # Title
            title_el = item.find('title') or item.find('{http://www.w3.org/2005/Atom}title')
            title = title_el.text.strip() if (title_el is not None and title_el.text) else ''
            # Link
            link_el = item.find('link') or item.find('{http://www.w3.org/2005/Atom}link')
            if link_el is not None:
                link = link_el.text or link_el.get('href') or ''
                link = link.strip()
            else:
                link = ''
            # Description / summary
            desc_el = (item.find('description')
                       or item.find('{http://www.w3.org/2005/Atom}summary')
                       or item.find('{http://www.w3.org/2005/Atom}content'))
            description = (desc_el.text or '').strip() if desc_el is not None else ''
            # Strip basic HTML tags
            description = description.replace('<![CDATA[', '').replace(']]>', '')
            for tag in ['<p>', '</p>', '<br>', '<br/>', '<br />', '<strong>', '</strong>']:
                description = description.replace(tag, ' ')
            description = ' '.join(description.split())[:500]
            # Published date
            pub_el = (item.find('pubDate')
                      or item.find('{http://www.w3.org/2005/Atom}published')
                      or item.find('{http://www.w3.org/2005/Atom}updated'))
            published = _parse_rss_date(pub_el.text if pub_el is not None else None)

            if title and link:
                articles.append({
                    'title':       title[:300],
                    'url':         link,
                    'published':   published or '',
                    'description': description,
                    'source':      url.split('/')[2] if '://' in url else url[:30],
                    'weight':      weight,
                    'bucket':      bucket,
                })
    except Exception as e:
        print(f"[africa_articles] RSS error on {url[:60]}: {str(e)[:80]}")
    return articles


def fetch_all_africa_wide_rss():
    """Fetch all continent-wide RSS feeds."""
    all_articles = []
    for url, weight, bucket in AFRICA_WIDE_RSS_FEEDS:
        articles = _fetch_rss_feed(url, weight=weight, bucket=bucket)
        all_articles.extend(articles)
        print(f"[africa_articles] RSS '{url[:50]}': {len(articles)} articles")
    print(f"[africa_articles] Total Africa-wide RSS: {len(all_articles)} articles")
    return all_articles


# ============================================================
# GDELT FETCH (per-country)
# ============================================================
def _fetch_gdelt_query(query, lang='eng', country_id=None):
    """Fetch one GDELT query in one language. Returns list of article dicts."""
    articles = []
    try:
        params = {
            'query':      f'{query} sourcelang:{lang}',
            'mode':       'artlist',
            'maxrecords': 30,
            'format':     'json',
            'timespan':   '14d',
            'sort':       'datedesc',
        }
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=GDELT_TIMEOUT)
        if resp.status_code != 200:
            print(f"[africa_articles] GDELT HTTP {resp.status_code} '{query[:30]}'")
            return articles

        payload = resp.json() if resp.content else {}
        for art in payload.get('articles', []):
            articles.append({
                'title':       (art.get('title') or '')[:300],
                'url':         art.get('url') or '',
                'published':   art.get('seendate') or '',
                'description': (art.get('snippet') or art.get('title') or '')[:500],
                'source':      f"GDELT/{lang}",
                'weight':      0.95,
                'bucket':      'news',
                'country':     country_id,
            })
    except Exception as e:
        print(f"[africa_articles] GDELT error '{query[:30]}': {str(e)[:80]}")
    return articles


def fetch_gdelt_for_country(country_id):
    """Fetch all GDELT queries for one country."""
    all_articles = []
    fallback_needed = False
    for query, lang in build_gdelt_queries(country_id):
        articles = _fetch_gdelt_query(query, lang=lang, country_id=country_id)
        all_articles.extend(articles)
        if len(articles) < GDELT_MIN_RESULTS:
            fallback_needed = True
        time.sleep(GDELT_INTER_QUERY_DELAY)   # 429-defense pacing
    return all_articles, fallback_needed


# ============================================================
# BRAVE SEARCH FETCH (last-resort, cached)
# ============================================================
def _fetch_brave_query(query, country_id=None, force_refresh=False):
    """Fetch one Brave Search news query, cached for 12h."""
    if not BRAVE_API_KEY:
        return []

    cache_key = BRAVE_CACHE_PREFIX + query.replace(' ', '_').replace('"', '')[:120]
    if not force_refresh:
        cached = _redis_get(cache_key)
        if cached and isinstance(cached, list):
            return cached

    articles = []
    try:
        resp = requests.get(
            BRAVE_BASE_URL,
            params={'q': query, 'count': 15, 'spellcheck': '0'},
            headers={
                'Accept':              'application/json',
                'X-Subscription-Token': BRAVE_API_KEY,
            },
            timeout=BRAVE_TIMEOUT,
        )
        if resp.status_code == 429:
            print(f"[africa_articles] Brave 429 on '{query[:40]}'")
            return articles
        if resp.status_code != 200:
            print(f"[africa_articles] Brave HTTP {resp.status_code} on '{query[:40]}'")
            return articles

        payload = resp.json()
        for art in (payload.get('results', []) or []):
            articles.append({
                'title':       (art.get('title') or '')[:300],
                'url':         art.get('url') or '',
                'published':   art.get('age') or '',
                'description': (art.get('description') or '')[:500],
                'source':      'Brave Search',
                'weight':      0.9,
                'bucket':      'news',
                'country':     country_id,
            })

        if articles:
            _redis_set(cache_key, articles, ttl=BRAVE_CACHE_TTL)

    except Exception as e:
        print(f"[africa_articles] Brave error '{query[:40]}': {str(e)[:80]}")

    return articles


def fetch_brave_for_country(country_id):
    """Fetch Brave fallback queries for one country."""
    all_articles = []
    for query in build_brave_queries(country_id):
        articles = _fetch_brave_query(query, country_id=country_id)
        all_articles.extend(articles)
        time.sleep(1.1)  # Brave is 1 req/sec
    return all_articles


# ============================================================
# COUNTRY MATCHING (for continent-wide RSS articles)
# ============================================================
def _build_match_terms(country_id):
    """Lowercase keyword set to match continent-wide articles to a country."""
    cfg = COUNTRY_CONFIG[country_id]
    terms = set()
    # Display name parts
    for part in cfg['display_name'].lower().split():
        if len(part) > 3:
            terms.add(part)
    # Country ID variants
    terms.add(country_id.lower().replace('_', ' '))
    # Capital
    terms.add(cfg['capital'].lower())
    # Common variations
    if country_id == 'drc':
        terms.update(['congo', 'kinshasa', 'fardc', 'goma', 'bukavu', 'kivu'])
    elif country_id == 'south_africa':
        terms.update(['south africa', 'johannesburg', 'pretoria', 'sandf'])
    elif country_id == 'south_sudan':
        terms.update(['south sudan', 'juba', 'unmiss'])
        # exclude plain "sudan" matches that aren't south sudan
    elif country_id == 'sudan':
        terms.update(['sudan', 'khartoum', 'darfur', 'rsf'])
    elif country_id == 'burkina_faso':
        terms.update(['burkina', 'ouagadougou', 'burkinabe'])
    return terms


def filter_articles_for_country(articles, country_id):
    """Filter a pool of articles down to those matching a country's keywords."""
    terms = _build_match_terms(country_id)
    matched = []
    for art in articles:
        haystack = (art.get('title', '') + ' ' + art.get('description', '')).lower()
        # Special case: don't let "south sudan" articles match "sudan"
        if country_id == 'sudan' and 'south sudan' in haystack and 'sudan' not in haystack.replace('south sudan', ''):
            continue
        for term in terms:
            if term in haystack:
                # Tag with country
                art_copy = dict(art)
                art_copy['country'] = country_id
                matched.append(art_copy)
                break
    return matched


# ============================================================
# DEDUPLICATION
# ============================================================
def dedupe_articles(articles):
    """Dedupe by URL (canonical), then by title prefix similarity."""
    seen_urls = set()
    seen_title_prefixes = set()
    out = []
    for art in articles:
        url = (art.get('url') or '').strip().lower()
        title = (art.get('title') or '').strip().lower()
        title_prefix = ' '.join(title.split()[:8])   # first 8 words

        if url and url in seen_urls:
            continue
        if title_prefix and title_prefix in seen_title_prefixes:
            continue
        if url:
            seen_urls.add(url)
        if title_prefix:
            seen_title_prefixes.add(title_prefix)
        out.append(art)
    return out


def sort_articles_by_date(articles):
    """Sort articles by published date (newest first), fallback to source priority."""
    def _sort_key(art):
        pub = art.get('published') or ''
        try:
            if 'T' in pub:
                return datetime.fromisoformat(pub.replace('Z', '+00:00'))
            elif len(pub) >= 8 and pub.isdigit():
                # GDELT format YYYYMMDDHHMMSS
                return datetime.strptime(pub[:14], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        except Exception:
            pass
        return datetime.min.replace(tzinfo=timezone.utc)
    return sorted(articles, key=_sort_key, reverse=True)


def discard_old_articles(articles, max_age_days=ARTICLE_AGE_DAYS_KEEP):
    """Drop articles older than max_age_days. Articles with no date are kept."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    out = []
    for art in articles:
        pub = art.get('published') or ''
        if not pub:
            out.append(art)
            continue
        try:
            if 'T' in pub:
                dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
            elif len(pub) >= 8 and pub.isdigit():
                dt = datetime.strptime(pub[:14], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
            else:
                out.append(art)
                continue
            if dt >= cutoff:
                out.append(art)
        except Exception:
            out.append(art)
    return out


# ============================================================
# MAIN GATHER (orchestrator)
# ============================================================
def run_gather(force=False):
    """
    Main gathering orchestrator.

    Strategy:
      1. Fetch continent-wide RSS once (humanitarian aggregators)
      2. For each country:
         a. Filter Africa-wide pool for country mentions
         b. Fetch GDELT (English + French if applicable)
         c. If GDELT thin, fetch Brave fallback
         d. Dedupe, sort by date, discard old, cap at MAX_ARTICLES_PER_COUNTRY
         e. Bucket articles: news / socials / ngos
         f. Write to Redis key africa:articles:<country>
      3. Write metrics + lastrun keys
    """
    start_ts = time.time()
    print(f"[africa_articles] === Starting gather run at {datetime.now(timezone.utc).isoformat()} ===")

    # Step 1: Continent-wide RSS
    africa_wide_pool = fetch_all_africa_wide_rss()
    print(f"[africa_articles] Africa-wide pool: {len(africa_wide_pool)} articles")

    metrics = {
        'africa_wide_rss_count': len(africa_wide_pool),
        'countries':             {},
        'total_articles_stored': 0,
        'duration_seconds':      0,
    }

    # Step 2: Per-country processing
    for country_id, cfg in COUNTRY_CONFIG.items():
        country_start = time.time()
        print(f"[africa_articles] --- {cfg['display_name']} ---")

        # 2a. Filter Africa-wide pool
        wide_matches = filter_articles_for_country(africa_wide_pool, country_id)
        print(f"[africa_articles]   wide-pool matches: {len(wide_matches)}")

        # 2b. GDELT
        gdelt_articles, need_brave = fetch_gdelt_for_country(country_id)
        print(f"[africa_articles]   GDELT: {len(gdelt_articles)} (brave fallback: {need_brave})")

        # 2c. Brave fallback (only if GDELT was thin)
        brave_articles = []
        if need_brave and BRAVE_API_KEY:
            brave_articles = fetch_brave_for_country(country_id)
            print(f"[africa_articles]   Brave: {len(brave_articles)}")

        # 2d. Combine + dedupe + sort + filter
        combined = wide_matches + gdelt_articles + brave_articles
        combined = dedupe_articles(combined)
        combined = discard_old_articles(combined)
        combined = sort_articles_by_date(combined)
        combined = combined[:MAX_ARTICLES_PER_COUNTRY]

        # 2e. Bucket articles
        buckets = {'news': [], 'socials': [], 'ngos': []}
        for art in combined:
            bucket = art.get('bucket', 'news')
            if bucket not in buckets:
                bucket = 'news'
            buckets[bucket].append(art)

        # 2f. Write to Redis
        payload = {
            'country':       country_id,
            'display_name':  cfg['display_name'],
            'updated_at':    datetime.now(timezone.utc).isoformat(),
            'article_count': len(combined),
            'buckets': {
                'news':    {'count': len(buckets['news']),    'articles': buckets['news']},
                'socials': {'count': len(buckets['socials']), 'articles': buckets['socials']},
                'ngos':    {'count': len(buckets['ngos']),    'articles': buckets['ngos']},
            },
        }
        ok = _redis_set(f"{ARTICLES_KEY_PREFIX}{country_id}", payload, ttl=ARTICLES_CACHE_TTL)

        country_duration = time.time() - country_start
        metrics['countries'][country_id] = {
            'display_name':   cfg['display_name'],
            'wide_matches':   len(wide_matches),
            'gdelt_count':    len(gdelt_articles),
            'brave_count':    len(brave_articles),
            'total_count':    len(combined),
            'news_count':     len(buckets['news']),
            'socials_count':  len(buckets['socials']),
            'ngos_count':     len(buckets['ngos']),
            'duration_s':     round(country_duration, 1),
            'redis_ok':       ok,
        }
        metrics['total_articles_stored'] += len(combined)
        print(f"[africa_articles]   stored {len(combined)} articles "
              f"(news={len(buckets['news'])} socials={len(buckets['socials'])} ngos={len(buckets['ngos'])}) "
              f"in {country_duration:.1f}s · Redis OK: {ok}")

    # Step 3: Metrics + lastrun
    total_duration = time.time() - start_ts
    metrics['duration_seconds'] = round(total_duration, 1)

    lastrun_payload = {
        'last_run_at':         datetime.now(timezone.utc).isoformat(),
        'article_count_total': metrics['total_articles_stored'],
        'duration_seconds':    round(total_duration, 1),
        'metrics':             metrics,
    }
    _redis_set(LASTRUN_KEY, lastrun_payload, ttl=ARTICLES_CACHE_TTL * 2)
    _redis_set(METRICS_KEY, metrics,         ttl=ARTICLES_CACHE_TTL * 2)

    print(f"[africa_articles] === Done. Stored {metrics['total_articles_stored']} articles "
          f"across {len(COUNTRY_CONFIG)} countries in {total_duration:.1f}s ===")
    return {
        'success':       True,
        'article_count': metrics['total_articles_stored'],
        'duration_s':    round(total_duration, 1),
        'metrics':       metrics,
    }


# ============================================================
# BACKGROUND SCHEDULER
# ============================================================
def _scheduler_loop():
    """Run gather every SCAN_INTERVAL_HOURS. Wait 90s on boot before first run."""
    print(f"[africa_articles] Scheduler: boot delay 90s, then every {SCAN_INTERVAL_HOURS}h")
    time.sleep(90)
    while True:
        global _gatherer_running
        try:
            with _gatherer_lock:
                if _gatherer_running:
                    print(f"[africa_articles] Scheduler: run already in progress, skipping")
                else:
                    _gatherer_running = True
            if _gatherer_running:
                try:
                    run_gather()
                finally:
                    with _gatherer_lock:
                        _gatherer_running = False
        except Exception as e:
            print(f"[africa_articles] Scheduler error: {str(e)[:100]}")
            traceback.print_exc()
            with _gatherer_lock:
                _gatherer_running = False
        # Sleep until next scan
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


def start_background_scheduler():
    """Start the scheduler thread (daemon)."""
    t = threading.Thread(target=_scheduler_loop, daemon=True, name='africa-articles-scheduler')
    t.start()
    print(f"[africa_articles] Background scheduler started (daemon)")


# ============================================================
# FLASK ENDPOINTS
# ============================================================
def register_africa_articles_endpoints(app, start_scheduler=True):
    """
    Register the Africa articles endpoints on a Flask app.

    Endpoints:
      GET /api/africa/articles/<country>          Per-country bucketed pool
      GET /api/africa/articles/scan?force=true    Manually trigger fresh scan
      GET /api/africa/articles/health             Health + last run + diagnostics

    Args:
      app:             Flask app instance.
      start_scheduler: If True (default), start background 12h scheduler thread.
    """
    from flask import jsonify, request

    @app.route('/api/africa/articles/<country>', methods=['GET'])
    def africa_articles_for_country(country):
        """Return the current cached article pool for one country."""
        country = country.lower().strip()
        if country not in COUNTRY_CONFIG:
            return jsonify({
                'success': False,
                'error':   f'Unknown country: {country}',
                'valid_countries': list(COUNTRY_CONFIG.keys()),
            }), 404

        payload = _redis_get(f"{ARTICLES_KEY_PREFIX}{country}")
        if not payload:
            return jsonify({
                'success':       False,
                'country':       country,
                'display_name':  COUNTRY_CONFIG[country]['display_name'],
                'article_count': 0,
                'buckets': {
                    'news':    {'count': 0, 'articles': []},
                    'socials': {'count': 0, 'articles': []},
                    'ngos':    {'count': 0, 'articles': []},
                },
                'message': 'No articles cached yet. Hit /api/africa/articles/scan?force=true to gather.',
            }), 200

        payload['success'] = True
        return jsonify(payload), 200

    @app.route('/api/africa/articles/scan', methods=['GET', 'POST'])
    def africa_articles_scan():
        """Trigger a manual scan. Returns cache info unless ?force=true."""
        global _gatherer_running
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        if _gatherer_running:
            return jsonify({
                'success':     False,
                'message':     'A scan is already in progress; please wait',
                'in_progress': True,
            }), 200

        if not force:
            lastrun = _redis_get(LASTRUN_KEY)
            if lastrun and isinstance(lastrun, dict):
                last_run_at = lastrun.get('last_run_at')
                try:
                    last_dt = datetime.fromisoformat(last_run_at)
                    age_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                    if age_h < SCAN_INTERVAL_HOURS:
                        return jsonify({
                            'success':       True,
                            'cached':        True,
                            'last_run_at':   last_run_at,
                            'article_count': lastrun.get('article_count_total', 0),
                            'metrics':       lastrun.get('metrics', {}),
                            'message':       f'Cached pool is {age_h:.1f}h old; use ?force=true to refresh',
                        }), 200
                except Exception:
                    pass

        with _gatherer_lock:
            _gatherer_running = True
        try:
            result = run_gather(force=force)
            return jsonify(result), 200
        finally:
            with _gatherer_lock:
                _gatherer_running = False

    @app.route('/api/africa/articles/health', methods=['GET'])
    def africa_articles_health():
        """Health check + last-run diagnostics."""
        lastrun = _redis_get(LASTRUN_KEY) or {}
        return jsonify({
            'module':              __module_id__,
            'version':             __version__,
            'countries_covered':   len(COUNTRY_CONFIG),
            'country_ids':         list(COUNTRY_CONFIG.keys()),
            'africa_wide_feeds':   len(AFRICA_WIDE_RSS_FEEDS),
            'brave_configured':    bool(BRAVE_API_KEY),
            'redis_configured':    bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'scan_interval_h':     SCAN_INTERVAL_HOURS,
            'currently_running':   _gatherer_running,
            'last_run_at':         lastrun.get('last_run_at') if isinstance(lastrun, dict) else None,
            'last_total_articles': lastrun.get('article_count_total', 0) if isinstance(lastrun, dict) else 0,
            'last_metrics':        lastrun.get('metrics', {}) if isinstance(lastrun, dict) else {},
            'status':              'operational',
        }), 200

    print('[africa_articles] Routes registered: /api/africa/articles/{<country>,scan,health}')

    if start_scheduler:
        start_background_scheduler()


# ============================================================
# MODULE METADATA
# ============================================================
__version__   = '1.0.0'
__module_id__ = 'africa_article_gatherer'
print(f'[Africa Article Gatherer] Module loaded -- v{__version__}')
