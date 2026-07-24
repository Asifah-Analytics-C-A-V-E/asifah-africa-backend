"""
Asifah Analytics -- Africa Backend v1.0.0
May 24, 2026

Flask backend for the Africa / AFRICOM regional dashboard.

LAUNCH COVERAGE (14 countries):
  DRC, Uganda, Rwanda, South Sudan, Kenya, Tanzania, Sudan, Ethiopia,
  Somalia, Nigeria, Mali, Niger, Burkina Faso, South Africa

v1.1 EXPANSION (Jul 2026, +6 countries -- 20 total):
  CAR 62, Chad 58, Mozambique 48, Guinea 45, Madagascar 45,
  Equatorial Guinea 40 (base conflict pct, calibrated Jul 18 2026)

DELIBERATELY EXCLUDED (canonical in MENA):
  Morocco, Libya, Egypt -- live in asifah-backend (ME) and are
  mirrored on the Africa dashboard via Redis fingerprint linkage.

ARCHITECTURE (mirrors WHA / ME / Europe / Asia pattern):
  - Upstash Redis (REST via requests) -- persistent cache across cold starts
  - /tmp file fallback when Redis unavailable
  - Background refresh every 12 hours (daemon thread)
  - force=true query param bypasses cache for manual OSINT scans
  - All tracker / source-module imports wrapped in try/except so the
    backend boots cleanly even before rhetoric trackers, regional BLUF,
    and per-country modules ship

ENDPOINTS:
  /health                                -- service health check
  /debug/routes                          -- route inventory
  /api/africa/threat/<country>           -- conflict probability + OSINT scan
  /api/africa/threat/<country>?force=true -- force rescan
  /api/africa/stability/<country>        -- stability summary card data

CONFLICT % BASE SCORES (higher = worse, calibrated May 24 2026):
  sudan        88   -- active war, IPC Phase 5 famine, RSF/SAF
  somalia      72   -- al-shabaab control of significant rural territory
  south_sudan  68   -- 2026 peace process, displacement, oil dependency
  drc          65   -- ebola PHEIC + M23 + Wagner-adjacent dynamics
  burkina_faso 60   -- junta consolidation, JNIM advance
  mali         60   -- junta + Wagner, JNIM advance, UN withdrawal aftermath
  niger        58   -- junta, Wagner pivot, uranium/France stress
  nigeria      45   -- Boko Haram, ISWAP, oil delta, currency
  ethiopia     42   -- Tigray aftershocks, Amhara, Eritrea tension, GERD
  uganda       30   -- ebola spread, succession dynamics
  rwanda       28   -- ebola response + M23 exposure
  kenya        22   -- ebola border, Somalia spillover, Haiti deployment
  tanzania     16   -- ebola border, otherwise stable
  south_africa 25   -- diamond/sanctions exposure, energy crisis, ICJ posture

COPYRIGHT 2025-2026 Asifah Analytics. All rights reserved.
Not for operational use.
"""

# ============================================================
# IMPORTS
# ============================================================
import os
import re
import json
import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── Soft-fail wrappers for source modules (Round 2 + later) ──
# Each module is wrapped so the backend boots even before the
# module exists in this repo. Once a module is added, just push it
# to the repo and Render auto-deploy picks it up; the try-block
# below will succeed on next boot.

try:
    from telegram_signals_africa import fetch_telegram_for_target
    TELEGRAM_AFRICA_AVAILABLE = True
    print("[Africa] ✅ telegram_signals_africa loaded")
except ImportError as e:
    TELEGRAM_AFRICA_AVAILABLE = False
    print(f"[Africa] ⚠️ telegram_signals_africa not available: {e}")

try:
    from bluesky_signals_africa import fetch_bluesky_for_target
    BLUESKY_AFRICA_AVAILABLE = True
    print("[Africa] ✅ bluesky_signals_africa loaded")
except ImportError as e:
    BLUESKY_AFRICA_AVAILABLE = False
    print(f"[Africa] ⚠️ bluesky_signals_africa not available: {e}")

try:
    from commodity_proxy_africa import register_africa_commodity_proxy
    COMMODITY_PROXY_AVAILABLE = True
    print("[Africa] ✅ commodity_proxy_africa loaded")
except ImportError as e:
    COMMODITY_PROXY_AVAILABLE = False
    print(f"[Africa] ⚠️ commodity_proxy_africa not available: {e}")

try:
    from convergence_proxy_africa import register_africa_convergence_proxy
    CONVERGENCE_PROXY_AVAILABLE = True
    print("[Africa] ✅ convergence_proxy_africa loaded")
except ImportError as e:
    CONVERGENCE_PROXY_AVAILABLE = False
    print(f"[Africa] ⚠️ convergence_proxy_africa not available: {e}")

try:
    from africa_article_gatherer import register_africa_articles_endpoints
    ARTICLE_GATHERER_AVAILABLE = True
    print("[Africa] ✅ africa_article_gatherer loaded")
except ImportError as e:
    ARTICLE_GATHERER_AVAILABLE = False
    print(f"[Africa] ⚠️ africa_article_gatherer not available: {e}")

try:
    from somalia_humanitarian import register_somalia_humanitarian_endpoints
    SOMALIA_HUMANITARIAN_AVAILABLE = True
    print("[Africa] ✅ somalia_humanitarian loaded")
except ImportError as e:
    SOMALIA_HUMANITARIAN_AVAILABLE = False
    print(f"[Africa] ⚠️ somalia_humanitarian not available: {e}")

try:
    from sudan_humanitarian import register_sudan_humanitarian_endpoints
    SUDAN_HUMANITARIAN_AVAILABLE = True
    print("[Africa] ✅ sudan_humanitarian loaded")
except ImportError as e:
    SUDAN_HUMANITARIAN_AVAILABLE = False
    print(f"[Africa] ⚠️ sudan_humanitarian not available: {e}")

try:
    from rhetoric_tracker_somalia import register_somalia_rhetoric_routes
    SOMALIA_RHETORIC_AVAILABLE = True
    print("[Africa] ✅ rhetoric_tracker_somalia loaded")
except ImportError as e:
    SOMALIA_RHETORIC_AVAILABLE = False
    print(f"[Africa] ⚠️ rhetoric_tracker_somalia not available: {e}")

# ── Future imports (rhetoric trackers, regional BLUF) ──
# These will fill in over future rounds. Each wrapped in try/except.

try:
    from rhetoric_tracker_sudan import (
        register_sudan_rhetoric_endpoints,
        start_background_refresh as start_sudan_rhetoric_refresh,
    )
    SUDAN_RHETORIC_AVAILABLE = True
    print("[Africa] ✅ rhetoric_tracker_sudan loaded")
except ImportError as e:
    SUDAN_RHETORIC_AVAILABLE = False
    print(f"[Africa] ⚠️ rhetoric_tracker_sudan not yet available: {e}")

try:
    from africa_regional_bluf import register_africa_bluf_routes
    AFRICA_BLUF_AVAILABLE = True
    print("[Africa] ✅ africa_regional_bluf loaded")
except ImportError as e:
    AFRICA_BLUF_AVAILABLE = False
    print(f"[Africa] ⚠️ africa_regional_bluf not yet available: {e}")

try:
    from nigeria_stability import register_nigeria_stability_endpoints
    NIGERIA_STABILITY_AVAILABLE = True
    print("[Africa] ✅ nigeria_stability loaded")
except ImportError as e:
    NIGERIA_STABILITY_AVAILABLE = False
    print(f"[Africa] ⚠️ nigeria_stability not yet available: {e}")


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)
CORS(app)

# ============================================================
# CONFIGURATION
# ============================================================

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWSAPI_KEY    = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY  = os.environ.get('BRAVE_API_KEY')

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

CACHE_TTL_HOURS    = 12
SCAN_TIMEOUT_SEC   = 90        # max scan time per country before bailing out
RENDER_DEPLOY_TAG  = 'asifa-africa-backend'

# /tmp fallback cache directory
FILE_CACHE_DIR = Path('/tmp/africa_cache')
FILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# REDIS HELPERS (mirrors WHA pattern)
# ============================================================

def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get('result') is None:
            return None
        return json.loads(data['result'])
    except Exception as e:
        print(f'[Africa Redis] GET {key} error: {str(e)[:120]}')
        return None


def _redis_set(key, value, ttl_seconds=None):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        payload = ['SET', key, json.dumps(value)]
        if ttl_seconds:
            payload.extend(['EX', str(ttl_seconds)])
        r = requests.post(
            UPSTASH_REDIS_URL,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            json=payload,
            timeout=5,
        )
        return r.status_code == 200
    except Exception as e:
        print(f'[Africa Redis] SET {key} error: {str(e)[:120]}')
        return False


# ============================================================
# FILE CACHE FALLBACK
# ============================================================

def _file_cache_path(key):
    safe = key.replace('/', '_').replace(':', '_')
    return FILE_CACHE_DIR / f'{safe}.json'


def _file_get(key):
    try:
        path = _file_cache_path(key)
        if not path.exists():
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'[Africa FileCache] GET {key} error: {str(e)[:120]}')
        return None


def _file_set(key, value):
    try:
        path = _file_cache_path(key)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(value, f)
        return True
    except Exception as e:
        print(f'[Africa FileCache] SET {key} error: {str(e)[:120]}')
        return False


def cache_get(key):
    """Redis-first, file-cache fallback."""
    value = _redis_get(key)
    if value is not None:
        return value
    return _file_get(key)


def cache_set(key, value):
    """Write to both Redis and file cache (for resilience)."""
    _redis_set(key, value, ttl_seconds=CACHE_TTL_HOURS * 3600)
    _file_set(key, value)


def is_cache_fresh(cached_data, max_hours=None):
    """Check whether a cached payload is still within TTL."""
    if not cached_data:
        return False
    ttl = max_hours if max_hours is not None else CACHE_TTL_HOURS
    try:
        cached_at = cached_data.get('cached_at')
        if not cached_at:
            return False
        cached_dt = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
        age = datetime.now(timezone.utc) - cached_dt
        return age < timedelta(hours=ttl)
    except Exception:
        return False


# ============================================================
# GDELT CIRCUIT BREAKER
# ============================================================
# Lifted from WHA pattern: GDELT periodically returns 429 or times
# out for runs. Short-circuit after the first failure of a country
# scan to avoid hanging.

_gdelt_failed_this_scan = False

# ── Shared GDELT gateway (Jul 24 2026) ────────────────────────────────
# Same fix as the other four backends: one serialised, paced GDELT lane
# per process (semaphore + circuit breaker + 15-min response cache)
# instead of every caller racing the same IP into a soft-block. The
# per-scan circuit breaker below is preserved as the fallback path when
# the gateway file is absent.
try:
    from gdelt_gateway import gdelt_fetch as _gw_fetch
    _GDELT_GATEWAY = True
except ImportError:
    print("[Africa GDELT] gdelt_gateway not available -- using direct GDELT calls")
    _GDELT_GATEWAY = False


def _reset_gdelt_circuit():
    global _gdelt_failed_this_scan
    _gdelt_failed_this_scan = False


def fetch_gdelt(query, days=7, language='eng', max_records=50):
    """Fetch GDELT articles. Short-circuits after first failure per scan."""
    global _gdelt_failed_this_scan
    if _GDELT_GATEWAY:
        # Route through the shared gateway; adapt its canonical shape back
        # into this file's own dialect (source is a STRING domain,
        # `published`, description = seendate -- domain, plus `query`).
        raw = _gw_fetch(f'"{query}"', language=language, timespan=f'{days}d',
                        maxrecords=max_records, label=f'africa/{language}')
        return [{
            'title':       a.get('title', ''),
            'description': (a.get('published') or '') + ' -- ' + (a.get('source') or ''),
            'url':         a.get('url', ''),
            'published':   a.get('published', ''),
            'source':      a.get('source') or 'GDELT',
            'query':       query,
            'language':    language,
        } for a in raw]
    if _gdelt_failed_this_scan:
        return []
    params = {
        'query':      f'"{query}" sourcelang:{language}',
        'mode':       'ArtList',
        'format':     'JSON',
        'maxrecords': str(max_records),
        'timespan':   f'{days}d',
        'sort':       'datedesc',
    }
    try:
        r = requests.get(
            GDELT_BASE_URL,
            params=params,
            timeout=8,
            headers={'User-Agent': 'AsifahAnalytics/1.0 (+https://asifahanalytics.com)'},
        )
        if r.status_code == 429:
            print(f'[Africa GDELT] 429 rate limit -- skipping: {query[:80]}')
            _gdelt_failed_this_scan = True
            return []
        if r.status_code != 200:
            return []
        data = r.json()
        out = []
        for a in data.get('articles', []) or []:
            out.append({
                'title':       a.get('title', ''),
                'description': a.get('seendate', '') + ' -- ' + (a.get('domain') or ''),
                'url':         a.get('url', ''),
                'published':   a.get('seendate', ''),
                'source':      a.get('domain', 'GDELT'),
                'query':       query,
                'language':    language,
            })
        return out
    except Exception as e:
        print(f'[Africa GDELT] {language} error: {str(e)[:80]}')
        _gdelt_failed_this_scan = True
        return []


# ============================================================
# NEWSAPI FETCH
# ============================================================

def fetch_newsapi(query, days=7):
    """Fetch NewsAPI articles. Returns [] on missing key / error."""
    if not NEWSAPI_KEY:
        return []
    from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    try:
        r = requests.get(
            'https://newsapi.org/v2/everything',
            params={
                'q':        query,
                'from':     from_date,
                'sortBy':   'publishedAt',
                'language': 'en',
                'pageSize': '40',
                'apiKey':   NEWSAPI_KEY,
            },
            timeout=8,
        )
        if r.status_code != 200:
            print(f'[Africa NewsAPI] HTTP {r.status_code} on {query[:60]}')
            return []
        data = r.json()
        out = []
        for a in (data.get('articles') or []):
            out.append({
                'title':       a.get('title', '') or '',
                'description': a.get('description', '') or '',
                'url':         a.get('url', ''),
                'published':   a.get('publishedAt', ''),
                'source':      (a.get('source') or {}).get('name', 'NewsAPI'),
                'query':       query,
            })
        return out
    except Exception as e:
        print(f'[Africa NewsAPI] error: {str(e)[:80]}')
        return []


# ============================================================
# BRAVE SEARCH FALLBACK
# ============================================================

def fetch_brave_news(query, count=20, freshness='pw', search_lang='en', country='us'):
    """Brave Search News API. Free tier: ~1 req/sec, 2000/month."""
    if not BRAVE_API_KEY:
        return []
    try:
        r = requests.get(
            'https://api.search.brave.com/res/v1/news/search',
            headers={
                'Accept':                 'application/json',
                'X-Subscription-Token':   BRAVE_API_KEY,
                'User-Agent':             'AsifahAnalytics/1.0',
            },
            params={
                'q':                query,
                'count':            str(count),
                'freshness':        freshness,
                'search_lang':      search_lang,
                'country':          country,
            },
            timeout=8,
        )
        if r.status_code != 200:
            print(f'[Africa Brave] HTTP {r.status_code} on {query[:60]}')
            return []
        data = r.json()
        out = []
        for item in (data.get('results') or []):
            out.append({
                'title':       item.get('title', '') or '',
                'description': item.get('description', '') or '',
                'url':         item.get('url', ''),
                'published':   item.get('age', ''),
                'source':      (item.get('meta_url') or {}).get('hostname', 'Brave'),
                'query':       query,
            })
        return out
    except Exception as e:
        print(f'[Africa Brave] error: {str(e)[:80]}')
        return []


# ============================================================
# RSS FETCH
# ============================================================

def fetch_rss(feed_url, max_items=15):
    """Fetch and parse an RSS feed."""
    try:
        import feedparser
        feed = feedparser.parse(feed_url, request_headers={
            'User-Agent': 'AsifahAnalytics/1.0 (+https://asifahanalytics.com)'
        })
        out = []
        for entry in (feed.entries or [])[:max_items]:
            out.append({
                'title':       entry.get('title', ''),
                'description': entry.get('summary', '') or entry.get('description', ''),
                'url':         entry.get('link', ''),
                'published':   entry.get('published', '') or entry.get('updated', ''),
                'source':      feed_url,
                'query':       'rss',
            })
        return out
    except Exception as e:
        print(f'[Africa RSS] {feed_url[:80]} error: {str(e)[:80]}')
        return []


SOCIAL_SOURCE_HINTS = ('reddit', 'r/', 'bluesky', 'bsky', 'telegram', 'social', 'mirror')

REGIONAL_PRESSURE_TERMS = {
    'kinetic': {
        'weight': 2.0,
        'phrases': [
            'armed clash', 'ambush', 'massacre', 'airstrike', 'drone strike',
            'shelling', 'village attacked', 'civilian casualties',
            'border incursion', 'militia attack', 'jihadist attack',
            'attaque armee', 'massacre', 'embuscade', 'frappe aerienne',
            'Ø§Ø´ØªØ¨Ø§ÙƒØ§Øª', 'Ù‚ØµÙ', 'Ù…Ø¬Ø²Ø±Ø©', 'Ù‡Ø¬ÙˆÙ…',
            'mapigano', 'shambulio', 'mauaji',
        ],
    },
    'governance': {
        'weight': 1.4,
        'phrases': [
            'coup', 'junta', 'state of emergency', 'curfew',
            'election postponed', 'peace deal collapsed',
            'opposition arrested', 'protest crackdown',
            'coup d etat', 'junte', 'etat d urgence',
            'Ø§Ù†Ù‚Ù„Ø§Ø¨', 'Ø­Ø§Ù„Ø© Ø§Ù„Ø·ÙˆØ§Ø±Ø¦', 'Ø­Ø¸Ø± Ø§Ù„ØªØ¬ÙˆÙ„',
            'mapinduzi', 'hali ya hatari',
        ],
    },
    'humanitarian': {
        'weight': 1.1,
        'phrases': [
            'famine', 'ipc phase 5', 'cholera', 'ebola', 'mass displacement',
            'refugee surge', 'humanitarian access denied', 'food insecurity',
            'famine', 'deplacement massif', 'insecurite alimentaire',
            'Ù…Ø¬Ø§Ø¹Ø©', 'Ù†Ø²ÙˆØ­', 'Ù„Ø§Ø¬Ø¦ÙŠÙ†', 'ÙƒÙˆÙ„ÙŠØ±Ø§',
            'njaa', 'wakimbizi', 'kipindupindu',
        ],
    },
}


def _regional_source_name(article):
    source = article.get('source', 'Unknown')
    if isinstance(source, dict):
        return source.get('name', 'Unknown')
    return str(source or 'Unknown')


def _is_social_source(source_name):
    source_lower = (source_name or '').lower()
    return any(hint in source_lower for hint in SOCIAL_SOURCE_HINTS)


def _regional_pressure_bonus(text):
    text_lower = (text or '').lower()
    labels = []
    bonus = 0.0
    for label, config in REGIONAL_PRESSURE_TERMS.items():
        if any(phrase.lower() in text_lower for phrase in config['phrases']):
            labels.append(label)
            bonus += config['weight']
    return min(bonus, 3.7), labels


def _article_recency_weight(article, days):
    raw_date = article.get('published') or article.get('publishedAt') or ''
    try:
        if raw_date:
            parsed = datetime.fromisoformat(str(raw_date).replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600
            return max(0.35, 1.0 - min(age_hours / max(days * 24, 1), 1.0) * 0.65)
    except Exception:
        pass
    return 0.65


# ============================================================
# COUNTRY CONFIG (14 countries)
# ============================================================
# Schema mirrors WHA COUNTRY_CONFIG: name, flag, base_conflict_pct,
# context, labels, gdelt_queries_en, gdelt_queries_fr/ar/sw (where
# applicable), newsapi_queries, rss_feeds, keywords_escalation,
# keywords_deescalation.
#
# Language strategy by region:
#   Sahel (Mali, Niger, Burkina Faso):  English + French
#   Sudan + South Sudan + Somalia:      English + Arabic
#   DRC:                                 English + French
#   Ethiopia + Kenya + Uganda + Tanzania + Rwanda: English + Swahili
#   Nigeria:                             English only (Hausa low-coverage)
#   South Africa:                        English only
# ============================================================

COUNTRY_CONFIG = {

    # ────────────────────────────────────────────────────────────
    'sudan': {
        'name':              'Sudan',
        'flag':              '\U0001f1f8\U0001f1e9',  # 🇸🇩
        'base_conflict_pct': 88,
        'context': ('Active war RSF v SAF since April 2023. IPC Phase 5 famine '
                    'localized (El Fasher, Zamzam camp). UAE-backed RSF / '
                    'Egypt-Russia-backed SAF axis. Mass displacement (~12M IDPs+refugees).'),
        'labels': {
            'low':    'War continuing (baseline awful)',
            'medium': 'Tactical escalation',
            'high':   'Strategic escalation',
            'surge':  'Capital threat / mass-atrocity event',
        },
        'gdelt_queries_en': [
            'sudan war RSF SAF', 'sudan famine IPC phase 5',
            'el fasher siege RSF', 'sudan UAE Russia',
            'sudan humanitarian access denied', 'sudan civilian casualties',
            'sudan port sudan attack', 'sudan ceasefire jeddah',
        ],
        'gdelt_queries_ar': [
            'السودان حرب الدعم السريع',
            'السودان مجاعة الفاشر',
        ],
        'newsapi_queries': [
            'Sudan RSF war famine',
            'Sudan UAE Russia weapons',
            'Sudan El Fasher siege',
            'Sudan ceasefire negotiations',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=sudan+war+OR+RSF+OR+famine&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=sudan+UAE+OR+egypt+OR+russia&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'el fasher falls', 'el fasher overrun', 'khartoum falls',
            'mass atrocity', 'chemical weapons sudan', 'foreign troops sudan',
            'darfur ethnic cleansing', 'genocide sudan', 'famine declared',
            'port sudan attack', 'eritrea intervention',
            'cross-border spillover', 'chad sudan refugees',
        ],
        'keywords_deescalation': [
            'sudan ceasefire signed', 'sudan peace deal', 'humanitarian corridor opened',
            'jeddah talks agreement', 'civilian government', 'aid delivered sudan',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'drc': {
        'name':              'Democratic Republic of Congo',
        'flag':              '\U0001f1e8\U0001f1e9',  # 🇨🇩
        'base_conflict_pct': 65,
        'context': ('Active Ebola Bundibugyo PHEIC since May 15 2026 (Ituri / '
                    'Nord-Kivu / Sud-Kivu, ~750 suspected cases). M23 advance '
                    'eastern provinces, Rwanda-backed. Cobalt convergence anchor.'),
        'labels': {
            'low':    'Routine eastern instability',
            'medium': 'Ebola spread + M23 pressure',
            'high':   'Ebola escalating + city threat',
            'surge':  'Multi-vector crisis (Ebola + war + state collapse)',
        },
        'gdelt_queries_en': [
            'DRC Ebola Ituri', 'DRC M23 advance',
            'congo Goma kivu', 'DRC Rwanda border',
            'DRC ebola contact tracing', 'DRC cobalt mining',
            'DRC Wagner mercenary', 'congo MONUSCO withdrawal',
        ],
        'gdelt_queries_fr': [
            'RDC Ebola Ituri Bundibugyo',
            'RDC M23 Goma Kivu',
            'RDC Rwanda frontière',
        ],
        'newsapi_queries': [
            'DRC Ebola outbreak Bundibugyo',
            'DRC M23 advance Goma',
            'DRC Rwanda border tension',
            'DRC cobalt mining Glencore',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=DRC+OR+Congo+OR+Kinshasa+Ebola+OR+M23&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'ebola spreads', 'ebola new province', 'ebola crosses border',
            'M23 takes city', 'goma falls', 'bukavu falls',
            'rwanda congo war', 'mass casualties drc',
            'cobalt mine attack', 'cobalt supply disruption',
        ],
        'keywords_deescalation': [
            'ebola contained', 'ebola last patient', 'M23 ceasefire',
            'rwanda congo talks', 'DRC peace agreement',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'uganda': {
        'name':              'Uganda',
        'flag':              '\U0001f1fa\U0001f1ec',  # 🇺🇬
        'base_conflict_pct': 30,
        'context': ('Five Ebola cases confirmed in Kampala (May 15-23 2026), '
                    'imported from DRC. Museveni succession pressure. ADF/IS '
                    'central africa cross-border threat from DRC.'),
        'labels': {
            'low':    'Routine',
            'medium': 'Ebola spread risk',
            'high':   'Ebola escalating',
            'surge':  'Outbreak + political crisis',
        },
        'gdelt_queries_en': [
            'uganda ebola kampala', 'uganda border closure DRC',
            'museveni uganda succession', 'uganda ADF islamic state',
            'uganda EAC east african community',
        ],
        'gdelt_queries_sw': [
            'Uganda Ebola Kampala',
        ],
        'newsapi_queries': [
            'Uganda Ebola Kampala',
            'Uganda Museveni succession',
            'Uganda ADF terrorism',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=uganda+ebola+OR+museveni+OR+ADF&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'uganda ebola spread', 'kampala lockdown', 'uganda outbreak',
            'museveni health', 'uganda coup',
            'ADF attack', 'islamic state uganda',
        ],
        'keywords_deescalation': [
            'uganda ebola contained', 'last ebola patient uganda',
            'uganda elections peaceful',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'rwanda': {
        'name':              'Rwanda',
        'flag':              '\U0001f1f7\U0001f1fc',  # 🇷🇼
        'base_conflict_pct': 28,
        'context': ('Partial border closure with DRC over Ebola (May 2026). '
                    'M23 backing pressure / sanctions risk. Kagame regime stable '
                    'but increasingly isolated diplomatically.'),
        'labels': {
            'low':    'Routine',
            'medium': 'Border tension',
            'high':   'Sanctions / M23 escalation',
            'surge':  'Open Rwanda-DRC conflict',
        },
        'gdelt_queries_en': [
            'rwanda DRC border ebola', 'rwanda M23 backing sanctions',
            'kagame rwanda diplomatic', 'rwanda EU minerals deal',
        ],
        'newsapi_queries': [
            'Rwanda DRC border tension',
            'Rwanda M23 sanctions',
            'Rwanda Kagame',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=rwanda+OR+kigali+M23+OR+DRC+OR+ebola&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'rwanda sanctioned', 'rwanda eu sanctions', 'rwanda us sanctions',
            'rwanda DRC war', 'kigali bombing', 'rwanda forces in DRC',
        ],
        'keywords_deescalation': [
            'rwanda DRC talks', 'rwanda M23 withdrawal',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'south_sudan': {
        'name':              'South Sudan',
        'flag':              '\U0001f1f8\U0001f1f8',  # 🇸🇸
        'base_conflict_pct': 68,
        'context': ('Africa CDC priority Member State for Ebola response. '
                    'Active 2026 peace process implementation. Heavy oil '
                    'dependency; Sudan war disrupts pipeline. Sudan refugee corridor.'),
        'labels': {
            'low':    'Implementation lag baseline',
            'medium': 'Peace stress',
            'high':   'Process collapse risk',
            'surge':  'Return to active conflict',
        },
        'gdelt_queries_en': [
            'south sudan kiir machar', 'south sudan peace agreement implementation',
            'south sudan ebola border DRC', 'south sudan oil pipeline sudan',
            'south sudan refugees sudan',
        ],
        'newsapi_queries': [
            'South Sudan Kiir Machar peace',
            'South Sudan ebola border',
            'South Sudan oil pipeline Sudan war',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=south+sudan+OR+juba+kiir+OR+machar&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'south sudan ceasefire collapse', 'kiir machar split',
            'south sudan war returns', 'oil pipeline destroyed',
            'south sudan ebola confirmed',
        ],
        'keywords_deescalation': [
            'south sudan elections announced', 'kiir machar agreement',
            'oil flow resumes south sudan',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'kenya': {
        'name':              'Kenya',
        'flag':              '\U0001f1f0\U0001f1ea',  # 🇰🇪
        'base_conflict_pct': 22,
        'context': ('Northern Corridor trade route exposure to Ebola. Heightened '
                    'border screening. Haiti MSS deployment. Somalia border '
                    'al-shabaab spillover. Ruto government economic pressure.'),
        'labels': {
            'low':    'Routine',
            'medium': 'Ebola screening / al-shabaab tempo',
            'high':   'Spillover / unrest',
            'surge':  'Multi-front crisis',
        },
        'gdelt_queries_en': [
            'kenya ebola screening', 'kenya somalia border al-shabaab',
            'kenya haiti deployment MSS', 'kenya ruto protest',
            'kenya economy shilling', 'kenya northern corridor truck',
        ],
        'gdelt_queries_sw': [
            'Kenya Ebola mpaka',
        ],
        'newsapi_queries': [
            'Kenya Ebola border screening',
            'Kenya al-shabaab Somalia',
            'Kenya Haiti deployment',
            'Kenya Ruto protests',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=kenya+ebola+OR+shabaab+OR+ruto&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'kenya ebola case', 'al-shabaab attack kenya',
            'kenya protest violence', 'haiti MSS withdrawn',
        ],
        'keywords_deescalation': [
            'kenya economy stable', 'kenya shilling strengthens',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'tanzania': {
        'name':              'Tanzania',
        'flag':              '\U0001f1f9\U0001f1ff',  # 🇹🇿
        'base_conflict_pct': 16,
        'context': ('Heightened ebola screening from DRC/Uganda. Generally stable '
                    'but ruling CCM dynamics opaque. Cabo Delgado (Mozambique) '
                    'spillover risk on southern border.'),
        'labels': {
            'low':    'Routine',
            'medium': 'Ebola screening',
            'high':   'Imported case / political crisis',
            'surge':  'Outbreak / mass unrest',
        },
        'gdelt_queries_en': [
            'tanzania ebola screening DRC', 'tanzania CCM',
            'tanzania cabo delgado spillover', 'tanzania samia',
        ],
        'gdelt_queries_sw': [
            'Tanzania Ebola',
        ],
        'newsapi_queries': [
            'Tanzania Ebola screening',
            'Tanzania Samia Suluhu',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=tanzania+OR+dodoma+OR+dar+es+salaam&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'tanzania ebola case', 'tanzania protest', 'cabo delgado tanzania',
        ],
        'keywords_deescalation': [
            'tanzania stable',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'ethiopia': {
        'name':              'Ethiopia',
        'flag':              '\U0001f1ea\U0001f1f9',  # 🇪🇹
        'base_conflict_pct': 42,
        'context': ('Tigray peace agreement implementation lag. Amhara Fano '
                    'insurgency active. Eritrea tension (TPLF nexus). GERD final '
                    'phase / Egypt-Sudan downstream dispute.'),
        'labels': {
            'low':    'Routine post-Tigray',
            'medium': 'Amhara escalation / GERD friction',
            'high':   'Multi-region insurgency / Eritrea war risk',
            'surge':  'State collapse risk',
        },
        'gdelt_queries_en': [
            'ethiopia amhara fano', 'ethiopia tigray TPLF',
            'ethiopia eritrea border', 'ethiopia GERD egypt',
            'ethiopia abiy ahmed', 'ethiopia somali region',
        ],
        'newsapi_queries': [
            'Ethiopia Amhara Fano insurgency',
            'Ethiopia Tigray TPLF',
            'Ethiopia GERD Egypt Sudan',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=ethiopia+OR+addis+ababa+OR+abiy&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'eritrea war ethiopia', 'GERD egypt strike', 'ethiopia mass atrocity',
            'tigray returns to war', 'amhara takes city',
        ],
        'keywords_deescalation': [
            'ethiopia ceasefire', 'amhara talks', 'eritrea border de-escalation',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'somalia': {
        'name':              'Somalia',
        'flag':              '\U0001f1f8\U0001f1f4',  # 🇸🇴
        'base_conflict_pct': 72,
        'context': ('Al-Shabaab controls significant rural territory + occasional '
                    'urban attacks. AMISOM successor (ATMIS / AUSSOM) transition. '
                    'Somaliland independence push / Ethiopia MoU. Red Sea / Indian '
                    'Ocean naval tempo.'),
        'labels': {
            'low':    'Baseline al-shabaab tempo',
            'medium': 'Major urban attack',
            'high':   'AUSSOM withdrawal / capital threat',
            'surge':  'Mogadishu siege / state collapse',
        },
        'gdelt_queries_en': [
            'somalia al-shabaab attack', 'somalia mogadishu',
            'somalia AUSSOM ATMIS', 'somaliland ethiopia MoU',
            'somalia us strike', 'somalia hassan sheikh',
        ],
        'gdelt_queries_ar': [
            'الصومال الشباب مقديشو',
        ],
        'newsapi_queries': [
            'Somalia al-Shabaab attack',
            'Somalia AUSSOM withdrawal',
            'Somaliland Ethiopia deal',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=somalia+OR+mogadishu+shabaab&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=somalia+(site:garoweonline.com+OR+site:hiiraan.com)&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'mogadishu attack', 'al-shabaab takes town', 'AUSSOM withdraws',
            'somaliland war ethiopia', 'somalia state collapse',
        ],
        'keywords_deescalation': [
            'al-shabaab leader killed', 'somalia liberation operation',
            'AUSSOM mandate extended',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'nigeria': {
        'name':              'Nigeria',
        'flag':              '\U0001f1f3\U0001f1ec',  # 🇳🇬
        'base_conflict_pct': 45,
        'context': ('Boko Haram + ISWAP in northeast. Bandits in northwest. '
                    'Biafra agitation in southeast. Niger Delta oil theft and '
                    'pipeline attacks. Naira currency crisis. Tinubu reform stress.'),
        'labels': {
            'low':    'Baseline multi-front insurgency',
            'medium': 'Major attack / oil disruption',
            'high':   'Currency / banking crisis',
            'surge':  'State capital lost / coup',
        },
        'gdelt_queries_en': [
            'nigeria boko haram ISWAP', 'nigeria bandits kidnapping',
            'nigeria niger delta oil', 'nigeria naira tinubu',
            'nigeria biafra IPOB', 'nigeria military coup',
        ],
        'newsapi_queries': [
            'Nigeria Boko Haram ISWAP attack',
            'Nigeria naira inflation Tinubu',
            'Nigeria Niger Delta oil theft',
            'Nigeria bandits kidnapping',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=nigeria+OR+abuja+OR+lagos+boko+OR+ISWAP+OR+naira&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'nigeria mass kidnapping', 'nigeria state capital attack',
            'naira collapse', 'nigeria coup attempt',
            'oil pipeline destroyed nigeria',
        ],
        'keywords_deescalation': [
            'nigeria security improvement', 'naira stabilizes',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'mali': {
        'name':              'Mali',
        'flag':              '\U0001f1f2\U0001f1f1',  # 🇲🇱
        'base_conflict_pct': 60,
        'context': ('Junta government (Goïta). Wagner / Africa Corps deployment '
                    'major presence. JNIM (al-Qaeda affiliate) controls significant '
                    'rural territory. MINUSMA withdrawn 2023. Sahel Confederation '
                    'with Niger + Burkina Faso.'),
        'labels': {
            'low':    'Baseline JNIM tempo',
            'medium': 'Major attack / Wagner casualties',
            'high':   'Junta crisis / capital threat',
            'surge':  'JNIM takes Bamako vicinity / second coup',
        },
        'gdelt_queries_en': [
            'mali junta goita', 'mali wagner africa corps',
            'mali JNIM tuareg', 'mali sahel confederation',
            'mali russia france', 'mali bamako attack',
        ],
        'gdelt_queries_fr': [
            'Mali junte Goita',
            'Mali Wagner Russie',
            'Mali JNIM Touareg',
        ],
        'newsapi_queries': [
            'Mali junta Wagner Russia',
            'Mali JNIM attack',
            'Mali Sahel Confederation',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=mali+OR+bamako+JNIM+OR+wagner+OR+junta&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'mali coup attempt', 'wagner casualties mali', 'bamako attack',
            'JNIM takes town mali', 'tuareg uprising',
        ],
        'keywords_deescalation': [
            'mali elections', 'mali wagner withdraw',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'niger': {
        'name':              'Niger',
        'flag':              '\U0001f1f3\U0001f1ea',  # 🇳🇪
        'base_conflict_pct': 58,
        'context': ('Tiani junta (July 2023 coup). French + US withdrawn; '
                    'Russia Africa Corps deployed. Uranium exports to France/EU '
                    'core stress point. Sahel Confederation member. JNIM/ISGS '
                    'pressure in border zones.'),
        'labels': {
            'low':    'Baseline junta consolidation',
            'medium': 'Major attack / sanctions tightening',
            'high':   'Niamey siege / coup-on-coup',
            'surge':  'State collapse / regional war',
        },
        'gdelt_queries_en': [
            'niger junta tiani', 'niger uranium france EU',
            'niger russia africa corps', 'niger ECOWAS sanctions',
            'niger sahel confederation', 'niger niamey attack',
        ],
        'gdelt_queries_fr': [
            'Niger junte Tiani uranium',
            'Niger Russie sanctions',
        ],
        'newsapi_queries': [
            'Niger junta uranium France',
            'Niger Russia Africa Corps',
            'Niger ECOWAS sanctions',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=niger+OR+niamey+uranium+OR+junta+OR+tiani&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'niger uranium cut', 'niger coup attempt', 'niamey attack',
            'JNIM takes town niger',
        ],
        'keywords_deescalation': [
            'niger ECOWAS deal', 'niger elections announced',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'burkina_faso': {
        'name':              'Burkina Faso',
        'flag':              '\U0001f1e7\U0001f1eb',  # 🇧🇫
        'base_conflict_pct': 60,
        'context': ('Traoré junta (Sept 2022 coup). Wagner / Africa Corps presence. '
                    'JNIM controls ~40% of territory. Cotton + gold export pressure. '
                    'Sahel Confederation member.'),
        'labels': {
            'low':    'Baseline junta consolidation',
            'medium': 'Major attack / VDP casualties',
            'high':   'Provincial capital threatened',
            'surge':  'Ouagadougou under attack',
        },
        'gdelt_queries_en': [
            'burkina faso traore junta', 'burkina faso wagner',
            'burkina faso JNIM', 'burkina faso VDP volunteers',
            'burkina faso gold cotton',
        ],
        'gdelt_queries_fr': [
            'Burkina Faso Traoré junte',
            'Burkina Faso Wagner JNIM',
        ],
        'newsapi_queries': [
            'Burkina Faso Traore junta',
            'Burkina Faso JNIM attack',
            'Burkina Faso Wagner Russia',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=burkina+faso+OR+ouagadougou+traore+OR+JNIM&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'burkina coup attempt', 'ouagadougou attack',
            'burkina JNIM takes town', 'traore deposed',
        ],
        'keywords_deescalation': [
            'burkina elections', 'burkina security improvement',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'south_africa': {
        'name':              'South Africa',
        'flag':              '\U0001f1ff\U0001f1e6',  # 🇿🇦
        'base_conflict_pct': 25,
        'context': ('Diamond convergence anchor. BRICS+ founding member. ICJ '
                    'genocide case against Israel posture. ANC-DA coalition '
                    'stress. Eskom energy crisis. Mining-region violence '
                    '(platinum, gold).'),
        'labels': {
            'low':    'Routine coalition stress',
            'medium': 'Energy / mining shock',
            'high':   'Coalition collapse / mass unrest',
            'surge':  'July 2021-style insurrection',
        },
        'gdelt_queries_en': [
            'south africa ANC DA coalition', 'south africa eskom load shedding',
            'south africa ICJ israel', 'south africa BRICS+',
            'south africa diamond mining', 'south africa ramaphosa',
        ],
        'newsapi_queries': [
            'South Africa coalition ANC DA',
            'South Africa Eskom power',
            'South Africa ICJ Israel BRICS',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=south+africa+OR+pretoria+OR+johannesburg+ANC+OR+eskom&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'south africa unrest', 'south africa coalition collapse',
            'eskom blackout extended', 'south africa mass violence',
        ],
        'keywords_deescalation': [
            'south africa power restored', 'south africa coalition stable',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'car': {
        'name':              'Central African Republic',
        'flag':              '\U0001f1e8\U0001f1eb',  # CF flag
        'base_conflict_pct': 62,
        'context': ('Touadera sworn in for contested third term Mar 2026 '
                    '(opposition boycott). Wagner absorbed into Africa Corps '
                    '(~1,500 personnel). Ndassima gold + diamonds underpin '
                    'Russian presence. MINUSCA drawdown under financial strain.'),
        'labels': {
            'low':    'Chronic instability baseline',
            'medium': 'Armed group / Africa Corps friction',
            'high':   'Rebel offensive / regime stress',
            'surge':  'Bangui threat / state-collapse vector',
        },
        'gdelt_queries_en': [
            'central african republic africa corps wagner',
            'central african republic rebels', 'CAR touadera bangui',
            'central african republic gold mining russia',
            'central african republic MINUSCA',
        ],
        'gdelt_queries_fr': [
            'Centrafrique Africa Corps Wagner',
            'Centrafrique rebelles Bangui',
            'Centrafrique Touadera',
        ],
        'newsapi_queries': [
            'Central African Republic Africa Corps',
            'Central African Republic rebels Touadera',
            'Central African Republic MINUSCA drawdown',
            'Bangui security',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=central+african+republic+OR+bangui+OR+touadera&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'bangui attack', 'rebels advance', 'rebel offensive',
            'coup attempt central african', 'minusca withdrawal',
            'africa corps clash', 'wagner clash', 'cpc offensive',
            'mass killing central african', 'mutiny bangui',
        ],
        'keywords_deescalation': [
            'ceasefire central african', 'disarmament agreement',
            'peace deal bangui', 'rebels disband',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'chad': {
        'name':              'Chad',
        'flag':              '\U0001f1f9\U0001f1e9',  # TD flag
        'base_conflict_pct': 58,
        'context': ('Sudan war spillover: RSF drone strikes into Wadi Fira '
                    '(17 civilians killed Mar 2026), 1,300km border closed, '
                    '1.2M+ Sudanese refugees. Boko Haram resurgence -- Lake '
                    'province emergency May 2026. Deby consolidation; Zaghawa '
                    'officer-corps fracture risk.'),
        'labels': {
            'low':    'Managed pressure baseline',
            'medium': 'Border spillover / Boko Haram pressure',
            'high':   'Cross-border strikes / internal fracture',
            'surge':  'Regime threat / multi-front crisis',
        },
        'gdelt_queries_en': [
            'chad sudan border attack', 'chad rsf drone strike',
            'chad deby government', 'chad boko haram lake',
            'chad sudanese refugees', 'chad zaghawa army',
        ],
        'gdelt_queries_fr': [
            'Tchad frontiere Soudan attaque',
            'Tchad Boko Haram lac',
            'Tchad Deby armee',
        ],
        'newsapi_queries': [
            'Chad Sudan border strike',
            'Chad Boko Haram Lake province',
            'Chad Deby opposition',
            'Chad refugees Darfur',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=chad+ndjamena+OR+deby+OR+sudan+border&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'drone strike chad', 'rsf attack chad', 'chad retaliation',
            'boko haram attack chad', 'soldiers killed chad',
            'mutiny chad', 'coup chad', 'zaghawa defection',
            'ndjamena attack', 'state of emergency chad',
        ],
        'keywords_deescalation': [
            'chad sudan talks', 'border reopened chad',
            'ceasefire chad', 'boko haram surrender',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'equatorial_guinea': {
        'name':              'Equatorial Guinea',
        'flag':              '\U0001f1ec\U0001f1f6',  # GQ flag
        'base_conflict_pct': 40,
        'context': ('Obiang at 47 years in power -- longest-ruling head of '
                    'state. VP Teodorin consolidating succession via elite '
                    'purges. Post-oil-boom crisis (ExxonMobil exit). Russian '
                    'mercenaries reinforce military; capital moving to '
                    'Ciudad de la Paz.'),
        'labels': {
            'low':    'Authoritarian stability baseline',
            'medium': 'Succession friction / elite purge',
            'high':   'Succession crisis signals',
            'surge':  'Regime rupture / coup vector',
        },
        'gdelt_queries_en': [
            'equatorial guinea obiang', 'equatorial guinea teodorin succession',
            'equatorial guinea coup', 'equatorial guinea oil economy',
            'equatorial guinea russia military',
        ],
        'gdelt_queries_es': [
            'Guinea Ecuatorial Obiang',
            'Guinea Ecuatorial Teodorin sucesion',
        ],
        'newsapi_queries': [
            'Equatorial Guinea Obiang succession',
            'Equatorial Guinea Teodorin',
            'Equatorial Guinea coup plot',
            'Equatorial Guinea oil crisis',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=equatorial+guinea+OR+obiang+OR+malabo&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'obiang dead', 'obiang dies', 'obiang hospitalized',
            'succession crisis', 'coup attempt equatorial',
            'teodorin purge', 'malabo unrest',
            'military mutiny equatorial',
        ],
        'keywords_deescalation': [
            'orderly transition', 'succession confirmed',
            'equatorial guinea reforms',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'guinea': {
        'name':              'Guinea',
        'flag':              '\U0001f1ec\U0001f1f3',  # GN flag
        'base_conflict_pct': 45,
        'context': ('Doumbouya won Dec 2025 election -- coup leader to elected '
                    'president, 14-year constitutional runway. AU sanctions '
                    'lifted. Simandou iron mega-project (majority Chinese-owned) '
                    'now the economic spine. Opposition repression persists.'),
        'labels': {
            'low':    'Consolidation baseline',
            'medium': 'Protest / repression pressure',
            'high':   'Unrest escalating / junta stress',
            'surge':  'Regime crisis / mass uprising',
        },
        'gdelt_queries_en': [
            'guinea conakry doumbouya', 'guinea protests opposition',
            'guinea simandou iron ore', 'guinea junta repression',
        ],
        'gdelt_queries_fr': [
            'Guinee Conakry Doumbouya',
            'Guinee manifestations opposition',
            'Guinee Simandou',
        ],
        'newsapi_queries': [
            'Guinea Doumbouya opposition',
            'Guinea Conakry protests',
            'Guinea Simandou mining',
            'Guinea crackdown civil society',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=guinea+conakry+OR+doumbouya+OR+simandou&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'protests conakry', 'protesters killed guinea',
            'opposition arrested guinea', 'strike conakry',
            'mutiny guinea', 'coup attempt guinea',
            'simandou halted', 'crackdown conakry',
        ],
        'keywords_deescalation': [
            'opposition dialogue guinea', 'prisoners released guinea',
            'guinea political reforms',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'madagascar': {
        'name':              'Madagascar',
        'flag':              '\U0001f1f2\U0001f1ec',  # MG flag
        'base_conflict_pct': 45,
        'context': ('Col. Randrianirina (CAPSAT) took power Oct 2025 after '
                    'Gen-Z protests ousted Rajoelina. Cabinet dissolved Mar '
                    '2026, anti-corruption chief installed as PM. AU/SADC '
                    'demand civilian transition + elections. Energy emergency; '
                    'foiled destabilization plot.'),
        'labels': {
            'low':    'Transition baseline',
            'medium': 'Transition friction / protest pressure',
            'high':   'Transition crisis / counter-coup signals',
            'surge':  'State rupture / mass unrest',
        },
        'gdelt_queries_en': [
            'madagascar randrianirina transition', 'madagascar protests',
            'madagascar military government', 'madagascar elections sadc',
            'madagascar energy crisis fuel',
        ],
        'gdelt_queries_fr': [
            'Madagascar transition Randrianirina',
            'Madagascar manifestations Antananarivo',
            'Madagascar elections',
        ],
        'newsapi_queries': [
            'Madagascar Randrianirina transition',
            'Madagascar protests Antananarivo',
            'Madagascar coup plot',
            'Madagascar SADC elections',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=madagascar+OR+antananarivo+randrianirina&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'counter-coup madagascar', 'coup plot madagascar',
            'protests antananarivo', 'protesters killed madagascar',
            'mutiny madagascar', 'state of emergency madagascar',
            'fuel crisis madagascar', 'blackout antananarivo',
        ],
        'keywords_deescalation': [
            'election date madagascar', 'civilian government madagascar',
            'transition agreement madagascar', 'sadc agreement madagascar',
        ],
    },

    # ────────────────────────────────────────────────────────────
    'mozambique': {
        'name':              'Mozambique',
        'flag':              '\U0001f1f2\U0001f1ff',  # MZ flag
        'base_conflict_pct': 48,
        'context': ('IS-Mozambique insurgency intensifying in Cabo Delgado: '
                    'N380 corridor ambushes, maritime attacks. ~2,000 Rwandan '
                    'troops reinforced + Tanzanian border force. Chapo dialogue '
                    'overtures alongside military push. Post-2024 election '
                    'tensions persist. LNG restart stakes.'),
        'labels': {
            'low':    'Contained insurgency baseline',
            'medium': 'Insurgent tempo rising',
            'high':   'Corridor / district threat',
            'surge':  'Major offensive / LNG threat',
        },
        'gdelt_queries_en': [
            'mozambique cabo delgado attack', 'mozambique islamic state insurgents',
            'mozambique rwanda forces', 'mozambique lng totalenergies',
            'mozambique mondlane protests',
        ],
        'gdelt_queries_pt': [
            'Mocambique Cabo Delgado ataque',
            'Mocambique insurgentes',
            'Mocambique protestos Mondlane',
        ],
        'newsapi_queries': [
            'Mozambique Cabo Delgado attack',
            'Mozambique ISIS insurgency',
            'Mozambique LNG security',
            'Mozambique Mondlane opposition',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=mozambique+cabo+delgado+OR+maputo&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'town falls mozambique', 'mocimboa attack', 'palma attack',
            'convoy ambush mozambique', 'insurgents seize',
            'lng suspended', 'maritime attack mozambique',
            'beheading cabo delgado', 'protests maputo',
        ],
        'keywords_deescalation': [
            'insurgents surrender', 'lng resumes',
            'cabo delgado dialogue', 'ceasefire mozambique',
        ],
    },
}


# ============================================================
# SCAN ENGINE
# ============================================================

def scan_country(country_id, days=7):
    """
    Run a full scan for a single country, hitting GDELT (en + native
    language), NewsAPI, Brave fallback, and RSS feeds. Returns a
    dict ready to cache.
    """
    config = COUNTRY_CONFIG.get(country_id)
    if not config:
        return None

    print(f'[Africa Scan] Scanning {country_id} ({days}d)...')
    scan_start = time.time()
    all_articles = []

    _reset_gdelt_circuit()

    # ── GDELT English ──
    gdelt_count = 0
    for query in config.get('gdelt_queries_en', []):
        articles = fetch_gdelt(query, days=days, language='eng')
        all_articles.extend(articles)
        gdelt_count += len(articles)
        time.sleep(0.5)

    # ── GDELT French (Sahel + DRC) ──
    for query in config.get('gdelt_queries_fr', []):
        articles = fetch_gdelt(query, days=days, language='fra')
        all_articles.extend(articles)
        gdelt_count += len(articles)
        time.sleep(0.5)

    # ── GDELT Arabic (Sudan / Somalia) ──
    for query in config.get('gdelt_queries_ar', []):
        articles = fetch_gdelt(query, days=days, language='ara')
        all_articles.extend(articles)
        gdelt_count += len(articles)
        time.sleep(0.5)

    # ── GDELT Swahili (East Africa) ──
    for query in config.get('gdelt_queries_sw', []):
        articles = fetch_gdelt(query, days=days, language='swa')
        all_articles.extend(articles)
        gdelt_count += len(articles)
        time.sleep(0.5)

    # ── GDELT Portuguese (Mozambique / lusophone) ──
    for query in config.get('gdelt_queries_pt', []):
        articles = fetch_gdelt(query, days=days, language='por')
        all_articles.extend(articles)
        gdelt_count += len(articles)
        time.sleep(0.5)

    # ── GDELT Spanish (Equatorial Guinea) ──
    for query in config.get('gdelt_queries_es', []):
        articles = fetch_gdelt(query, days=days, language='spa')
        all_articles.extend(articles)
        gdelt_count += len(articles)
        time.sleep(0.5)

    # ── NewsAPI ──
    newsapi_count = 0
    for query in config.get('newsapi_queries', []):
        articles = fetch_newsapi(query, days=days)
        all_articles.extend(articles)
        newsapi_count += len(articles)
        time.sleep(0.3)

    # ── Brave fallback (only if GDELT + NewsAPI thin) ──
    brave_count = 0
    if (gdelt_count + newsapi_count) < 10 and BRAVE_API_KEY:
        print(f'[Africa Scan] {country_id}: only {gdelt_count + newsapi_count} '
              f'articles -- firing Brave fallback')
        for query in config.get('newsapi_queries', [])[:2]:
            articles = fetch_brave_news(query, count=20, freshness='pw',
                                         search_lang='en', country='us')
            all_articles.extend(articles)
            brave_count += len(articles)
            time.sleep(1.1)

    # ── RSS ──
    rss_count = 0
    for feed_url in config.get('rss_feeds', []):
        articles = fetch_rss(feed_url, max_items=15)
        all_articles.extend(articles)
        rss_count += len(articles)
        time.sleep(0.3)

    # ── Telegram (shared-channel cache + per-country relevance gate) ──
    telegram_count = 0
    if TELEGRAM_AFRICA_AVAILABLE:
        try:
            tg_articles = fetch_telegram_for_target(country_id)
            all_articles.extend(tg_articles)
            telegram_count = len(tg_articles)
        except Exception as e:
            print(f'[Africa Scan] {country_id}: telegram fetch FAILED: {str(e)[:100]}')

    # ── Bluesky (public AppView, targets[] routing) ──
    bluesky_count = 0
    if BLUESKY_AFRICA_AVAILABLE:
        try:
            bs_articles = fetch_bluesky_for_target(country_id, days=days)
            all_articles.extend(bs_articles)
            bluesky_count = len(bs_articles)
        except Exception as e:
            print(f'[Africa Scan] {country_id}: bluesky fetch FAILED: {str(e)[:100]}')

    # ── Score escalation/de-escalation ──
    esc_keywords = [k.lower() for k in config.get('keywords_escalation', [])]
    de_keywords  = [k.lower() for k in config.get('keywords_deescalation', [])]
    esc_hits = 0
    de_hits = 0
    pressure_hits = []
    score_delta = 0.0
    signal_sources = set()
    social_signal_count = 0
    for a in all_articles:
        title = (a.get('title') or '').lower()
        desc  = (a.get('description') or '').lower()
        text = title + ' ' + desc
        source_name = _regional_source_name(a)
        source_weight = 0.55 if _is_social_source(source_name) else 1.0
        recency_weight = _article_recency_weight(a, days)
        pressure_bonus, pressure_labels = _regional_pressure_bonus(text)
        matched_escalation = False
        for k in esc_keywords:
            if k in text:
                esc_hits += 1
                matched_escalation = True
                signal_sources.add(source_name)
                if _is_social_source(source_name):
                    social_signal_count += 1
                score_delta += (2.0 + pressure_bonus) * source_weight * recency_weight
                break
        if pressure_bonus and not matched_escalation:
            signal_sources.add(source_name)
            if _is_social_source(source_name):
                social_signal_count += 1
            contribution = pressure_bonus * 0.7 * source_weight * recency_weight
            score_delta += contribution
            pressure_hits.append({
                'title': a.get('title', '')[:120],
                'url': a.get('url', ''),
                'source': source_name,
                'published': a.get('published', ''),
                'pressure_signals': pressure_labels,
                'contribution': round(contribution, 2),
            })
        for k in de_keywords:
            if k in text:
                de_hits += 1
                score_delta -= 1.8 * recency_weight
                break

    # ── Final score: base + escalation hits - de-escalation hits ──
    base_pct = config.get('base_conflict_pct', 30)
    unique_sources = len(set(_regional_source_name(a) for a in all_articles))
    non_social_signal_count = max(0, len(signal_sources) - social_signal_count)
    source_diversity_bonus = min(4.0, max(0, unique_sources - 4) * 0.25)
    social_corroboration_bonus = (
        min(2.5, social_signal_count * 0.25)
        if social_signal_count and non_social_signal_count >= 2 else 0.0
    )
    score = base_pct + score_delta + source_diversity_bonus + social_corroboration_bonus
    score = max(0, min(100, score))

    # ── Alert level ──
    if score >= 75:
        alert_level = 'surge'
    elif score >= 55:
        alert_level = 'high'
    elif score >= 35:
        alert_level = 'medium'
    else:
        alert_level = 'low'

    elapsed = round(time.time() - scan_start, 1)

    result = {
        'country':                 country_id,
        'country_name':            config['name'],
        'country_flag':            config['flag'],
        'conflict_probability':    score,
        'alert_level':             alert_level,
        'alert_label':             config.get('labels', {}).get(alert_level, alert_level),
        'context':                 config.get('context', ''),
        'total_articles':          len(all_articles),
        'articles_by_source': {
            'gdelt':    gdelt_count,
            'newsapi':  newsapi_count,
            'brave':    brave_count,
            'rss':      rss_count,
            'telegram': telegram_count,
            'bluesky':  bluesky_count,
        },
        'escalation_hits':         esc_hits,
        'deescalation_hits':       de_hits,
        'pressure_hits':           len(pressure_hits),
        'scoring_breakdown': {
            'base_conflict_pct': base_pct,
            'article_signal_delta': round(score_delta, 2),
            'source_diversity_bonus': round(source_diversity_bonus, 2),
            'social_corroboration_bonus': round(social_corroboration_bonus, 2),
            'unique_sources': unique_sources,
            'social_signal_count': social_signal_count,
            'non_social_signal_count': non_social_signal_count,
        },
        'pressure_only_signals':   pressure_hits[:8],
        'top_articles':            all_articles[:30],   # cap to avoid bloat
        'cached_at':               datetime.now(timezone.utc).isoformat(),
        'scan_duration_sec':       elapsed,
        'backend_version':         '1.3.0',
        'cache_status':            'fresh',
    }

    cache_key = f'africa_country:{country_id}'
    cache_set(cache_key, result)

    print(f'[Africa Scan] {country_id} complete: score={score}, alert={alert_level}, '
          f'articles={len(all_articles)}, elapsed={elapsed}s')
    return result


def _background_scan_country(country_id, days=7):
    """Run a country scan in a background thread."""
    try:
        scan_country(country_id, days=days)
    except Exception as e:
        print(f'[Africa Background] {country_id} error: {str(e)[:200]}')


def _run_all_countries_background(days=7):
    """Periodic full-region refresh. Runs every CACHE_TTL_HOURS."""
    while True:
        try:
            print('[Africa Background] Starting full-region refresh cycle...')
            for country_id in COUNTRY_CONFIG.keys():
                try:
                    scan_country(country_id, days=days)
                except Exception as e:
                    print(f'[Africa Background] {country_id} scan failed: {str(e)[:200]}')
                time.sleep(2)  # politeness between countries
            print('[Africa Background] Full-region refresh complete; sleeping...')
        except Exception as e:
            print(f'[Africa Background] cycle error: {str(e)[:200]}')
        time.sleep(CACHE_TTL_HOURS * 3600)


def _start_background_refresh():
    """Start the daemon refresh thread. Boot delay = 90s."""
    def _delayed_start():
        time.sleep(90)  # canonical 90s boot delay (per architecture)
        _run_all_countries_background(days=7)

    thread = threading.Thread(target=_delayed_start, daemon=True)
    thread.start()
    print('[Africa] Background refresh scheduled (90s delay → 12h cycle)')


# ============================================================
# ROUTES
# ============================================================

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        'service':       'asifah-africa-backend',
        'version':       '1.0.0',
        'theatre':       'Africa / AFRICOM',
        'countries':     list(COUNTRY_CONFIG.keys()),
        'country_count': len(COUNTRY_CONFIG),
        'docs':          'https://asifahanalytics.com',
        'not_for':       'operational use',
    })


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status':         'healthy',
        'service':        'asifah-africa-backend',
        'timestamp':      datetime.now(timezone.utc).isoformat(),
        'cache':          'redis+file',
        'modules': {
            'telegram_africa':        TELEGRAM_AFRICA_AVAILABLE,
            'bluesky_africa':         BLUESKY_AFRICA_AVAILABLE,
            'commodity_proxy':        COMMODITY_PROXY_AVAILABLE,
            'convergence_proxy':      CONVERGENCE_PROXY_AVAILABLE,
            'article_gatherer':       ARTICLE_GATHERER_AVAILABLE,
            'sudan_rhetoric':         SUDAN_RHETORIC_AVAILABLE,
            'africa_regional_bluf':   AFRICA_BLUF_AVAILABLE,
        },
    })


@app.route('/debug/routes', methods=['GET'])
def debug_routes():
    """List all registered Flask routes — diagnostic helper."""
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'rule':    str(rule),
            'methods': sorted(m for m in rule.methods if m not in ('HEAD', 'OPTIONS')),
            'endpoint': rule.endpoint,
        })
    routes.sort(key=lambda r: r['rule'])
    return jsonify({
        'service':    'asifah-africa-backend',
        'route_count': len(routes),
        'routes':     routes,
    })


@app.route('/api/africa/threat/<country>', methods=['GET'])
def api_africa_threat(country):
    """Conflict probability + OSINT scan for a single country."""
    country = country.lower()
    if country not in COUNTRY_CONFIG:
        return jsonify({
            'error':              f'Country "{country}" not in Africa coverage',
            'available_countries': list(COUNTRY_CONFIG.keys()),
        }), 404

    force = request.args.get('force', 'false').lower() == 'true'
    cache_key = f'africa_country:{country}'

    if not force:
        cached = cache_get(cache_key)
        if cached and is_cache_fresh(cached):
            cached['cache_status'] = 'fresh'
            return jsonify(cached)
        if cached:
            cached['cache_status'] = 'stale'
            # Trigger background refresh; return stale immediately
            threading.Thread(
                target=_background_scan_country,
                args=(country,),
                daemon=True,
            ).start()
            return jsonify(cached)

    # No cache OR force=true — synchronous scan
    # Honor optional ?days=N query param (default 7, clamped 1-30)
    try:
        days = int(request.args.get('days', 7))
        days = max(1, min(days, 30))
    except (ValueError, TypeError):
        days = 7
    try:
        result = scan_country(country, days=days)
        if not result:
            return jsonify({'error': 'Scan failed'}), 500
        return jsonify(result)
    except Exception as e:
        print(f'[Africa Threat] {country} error: {str(e)[:200]}')
        return jsonify({'error': str(e)[:200]}), 500


@app.route('/api/africa/stability/<country>', methods=['GET'])
def api_africa_stability(country):
    """Lightweight stability card — for dashboard hub use."""
    country = country.lower()
    if country not in COUNTRY_CONFIG:
        return jsonify({
            'error':              f'Country "{country}" not in Africa coverage',
            'available_countries': list(COUNTRY_CONFIG.keys()),
        }), 404

    cached = cache_get(f'africa_country:{country}')
    config = COUNTRY_CONFIG[country]

    # Always return a valid structure, even at cold start
    return jsonify({
        'country':              country,
        'country_name':         config['name'],
        'country_flag':         config['flag'],
        'conflict_probability': (cached or {}).get('conflict_probability',
                                                    config.get('base_conflict_pct', 30)),
        'alert_level':          (cached or {}).get('alert_level', 'medium'),
        'context':              config.get('context', ''),
        'cached_at':            (cached or {}).get('cached_at'),
        'cache_status':         'cached' if cached else 'cold',
    })


@app.route('/api/africa/scan-all', methods=['POST'])
def api_scan_all():
    """Trigger a full-region scan in the background."""
    def _scan():
        for country_id in COUNTRY_CONFIG.keys():
            try:
                scan_country(country_id, days=7)
                time.sleep(2)
            except Exception as e:
                print(f'[Africa ScanAll] {country_id} error: {str(e)[:200]}')

    threading.Thread(target=_scan, daemon=True).start()
    return jsonify({
        'status':    'background_scan_started',
        'countries': list(COUNTRY_CONFIG.keys()),
        'eta_sec':   len(COUNTRY_CONFIG) * 90,
    })

# ============================================================
# BEGIN PATCH v2 — africa.html supporting endpoints (May 24 2026)
# Cloned from ME canonical patterns: cadataapi.state.gov + FAA NOTAM API
# ============================================================

# ─────────────────────────────────────────────────────────────
# COUNTRIES INDEX
# /api/africa/countries — frontend roster + display names
# ─────────────────────────────────────────────────────────────

_COUNTRY_DISPLAY_NAMES = {
    'burkina_faso':      'Burkina Faso',
    'car':               'Central African Republic',
    'chad':              'Chad',
    'drc':               'Democratic Republic of Congo',
    'equatorial_guinea': 'Equatorial Guinea',
    'ethiopia':          'Ethiopia',
    'guinea':            'Guinea',
    'kenya':             'Kenya',
    'madagascar':        'Madagascar',
    'mali':              'Mali',
    'mozambique':        'Mozambique',
    'niger':             'Niger',
    'nigeria':           'Nigeria',
    'rwanda':            'Rwanda',
    'somalia':           'Somalia',
    'south_africa':      'South Africa',
    'south_sudan':       'South Sudan',
    'sudan':             'Sudan',
    'tanzania':          'Tanzania',
    'uganda':            'Uganda',
}

@app.route('/api/africa/countries', methods=['GET'])
def api_africa_countries():
    """Return the active country roster + display metadata."""
    result = []
    for cid in COUNTRY_CONFIG.keys():
        result.append({
            'id':            cid,
            'display_name':  _COUNTRY_DISPLAY_NAMES.get(cid, cid.replace('_', ' ').title()),
            'stability_url': f'{cid}-stability.html',
        })
    return jsonify({
        'success':   True,
        'count':     len(result),
        'countries': result,
    })


# ─────────────────────────────────────────────────────────────
# TRAVEL ADVISORIES — Live State Dept API (ME canonical pattern)
# /api/africa/travel-advisories
# Source: https://cadataapi.state.gov/api/TravelAdvisories
# ─────────────────────────────────────────────────────────────

_africa_travel_advisory_cache = {'data': None, 'fetched_at': None, 'ttl': 86400}  # 24h
AFRICA_TRAVEL_ADVISORY_API = "https://cadataapi.state.gov/api/TravelAdvisories"

# State Dept uses FIPS country codes — these may NOT match ISO codes
AFRICA_TRAVEL_ADVISORY_CODES = {
    'burkina_faso':      ['UV'],   # Burkina Faso (FIPS — UV)
    'car':               ['CT'],   # Central African Republic (FIPS — CT)
    'chad':              ['CD'],   # Chad (FIPS — CD; NOT DRC, which is CG!)
    'drc':               ['CG'],   # DRC (FIPS — Congo Kinshasa = CG)
    'equatorial_guinea': ['EK'],   # Equatorial Guinea (FIPS — EK)
    'ethiopia':          ['ET'],   # Ethiopia
    'guinea':            ['GV'],   # Guinea (FIPS — GV; Guinea-Bissau = PU)
    'kenya':             ['KE'],   # Kenya
    'madagascar':        ['MA'],   # Madagascar (FIPS — MA; Morocco = MO)
    'mali':              ['ML'],   # Mali
    'mozambique':        ['MZ'],   # Mozambique
    'niger':             ['NG'],   # Niger (FIPS — NG, confusingly!)
    'nigeria':           ['NI'],   # Nigeria (FIPS — NI, also confusing)
    'rwanda':            ['RW'],   # Rwanda
    'somalia':           ['SO'],   # Somalia
    'south_africa':      ['SF'],   # South Africa (FIPS — SF not ZA!)
    'south_sudan':       ['OD'],   # South Sudan (FIPS — OD)
    'sudan':             ['SU'],   # Sudan (FIPS — SU)
    'tanzania':          ['TZ'],   # Tanzania
    'uganda':            ['UG'],   # Uganda
}

AFRICA_TRAVEL_ADVISORY_LEVELS = {
    1: {'label': 'Exercise Normal Precautions', 'short': 'Normal Precautions', 'color': '#10b981'},
    2: {'label': 'Exercise Increased Caution', 'short': 'Increased Caution', 'color': '#f59e0b'},
    3: {'label': 'Reconsider Travel', 'short': 'Reconsider Travel', 'color': '#f97316'},
    4: {'label': 'Do Not Travel', 'short': 'Do Not Travel', 'color': '#ef4444'},
}


def _run_africa_travel_advisory_scan():
    """Fetch U.S. State Dept travel advisories for Africa targets."""
    try:
        response = requests.get(AFRICA_TRAVEL_ADVISORY_API, timeout=15)
        if response.status_code != 200:
            print(f"[Africa Travel Advisory] API returned HTTP {response.status_code}")
            return {'success': False, 'advisories': {}}

        all_advisories = response.json()
        results = {}

        for target, codes in AFRICA_TRAVEL_ADVISORY_CODES.items():
            for advisory in all_advisories:
                category_list = advisory.get('Category', [])
                if any(cat in codes for cat in category_list):
                    category = category_list[0] if category_list else ''
                    title = advisory.get('Title', '')
                    level_match = re.search(r'Level\s+(\d)', title)
                    level = int(level_match.group(1)) if level_match else 0
                    level_info = AFRICA_TRAVEL_ADVISORY_LEVELS.get(level, {})

                    summary_html = advisory.get('Summary', '')
                    first_p = re.search(r'<p[^>]*>(.*?)</p>', summary_html, re.DOTALL | re.IGNORECASE)
                    short_summary = ''
                    if first_p:
                        short_summary = re.sub(r'<[^>]+>', '', first_p.group(1)).strip()[:300]
                    if not short_summary:
                        short_summary = re.sub(r'<[^>]+>', '', summary_html).strip()[:300]

                    published = advisory.get('Published', '')
                    updated = advisory.get('Updated', '')
                    link = advisory.get('Link', '')

                    recently_changed = False
                    change_description = ''
                    try:
                        updated_dt = datetime.fromisoformat(updated)
                        if updated_dt.tzinfo is None:
                            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                        days_since = (datetime.now(timezone.utc) - updated_dt).days
                        if days_since <= 30:
                            recently_changed = True
                            summary_lower = summary_html.lower()
                            if 'advisory level was increased' in summary_lower or 'upgraded' in summary_lower:
                                change_description = f'Advisory level INCREASED (updated {days_since} days ago)'
                            elif 'advisory level was decreased' in summary_lower or 'downgraded' in summary_lower:
                                change_description = f'Advisory level DECREASED (updated {days_since} days ago)'
                            else:
                                change_description = f'Updated {days_since} days ago'
                    except Exception:
                        pass

                    results[target] = {
                        'country_code':       category,
                        'title':              title,
                        'level':              level,
                        'level_label':        level_info.get('label', 'Unknown'),
                        'level_short':        level_info.get('short', 'Unknown'),
                        'level_color':        level_info.get('color', '#6b7280'),
                        'short_summary':      short_summary,
                        'link':               link,
                        'published':          published,
                        'updated':            updated,
                        'recently_changed':   recently_changed,
                        'change_description': change_description,
                    }
                    break  # found advisory for this target, move to next

        return {'success': True, 'advisories': results}

    except Exception as e:
        print(f"[Africa Travel Advisory] Error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'advisories': {}}


@app.route('/api/africa/travel-advisories', methods=['GET'])
def api_africa_travel_advisories():
    """Return U.S. State Dept travel advisories for Africa targets. Cached 24h."""
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        now = time.time()

        if (not force
                and _africa_travel_advisory_cache['data'] is not None
                and _africa_travel_advisory_cache['fetched_at'] is not None
                and (now - _africa_travel_advisory_cache['fetched_at']) < _africa_travel_advisory_cache['ttl']):
            cached = _africa_travel_advisory_cache['data'].copy()
            cached['cached'] = True
            return jsonify(cached)

        data = _run_africa_travel_advisory_scan()
        data['timestamp'] = datetime.now(timezone.utc).isoformat()
        data['cached'] = False

        if data.get('success'):
            # Only a SUCCESSFUL scan may enter the cache -- a transient
            # state.gov failure must never poison 24h of advisories.
            _africa_travel_advisory_cache['data'] = data
            _africa_travel_advisory_cache['fetched_at'] = now
        elif _africa_travel_advisory_cache['data'] is not None:
            # Failed scan with a prior good cache: absence-honest stale-serve.
            stale = _africa_travel_advisory_cache['data'].copy()
            stale['cached'] = True
            stale['stale'] = True
            return jsonify(stale)

        return jsonify(data)
    except Exception as e:
        print(f"[Africa Travel Advisory] Endpoint error: {e}")
        if _africa_travel_advisory_cache['data'] is not None:
            stale = _africa_travel_advisory_cache['data'].copy()
            stale['cached'] = True
            stale['stale'] = True
            return jsonify(stale)
        return jsonify({'success': False, 'error': str(e), 'advisories': {}}), 500


# ─────────────────────────────────────────────────────────────
# NOTAMs — Live FAA API (ME canonical pattern)
# /api/africa/notams
# Source: https://external-api.faa.gov/notamapi/v1/notams
# ─────────────────────────────────────────────────────────────

# African FIR ICAO codes — covers all 14 target countries + key neighbors
AFRICA_FIRS = {
    'DFFF': {'country': 'Burkina Faso',  'flag': '🇧🇫', 'name': 'Ouagadougou FIR'},
    'FZZA': {'country': 'DRC',            'flag': '🇨🇩', 'name': 'Kinshasa FIR'},
    'HAAA': {'country': 'Ethiopia',       'flag': '🇪🇹', 'name': 'Addis Ababa FIR'},
    'HKNA': {'country': 'Kenya',          'flag': '🇰🇪', 'name': 'Nairobi FIR'},
    'GABS': {'country': 'Mali',           'flag': '🇲🇱', 'name': 'Bamako FIR'},
    'DRRR': {'country': 'Niger',          'flag': '🇳🇪', 'name': 'Niamey FIR'},
    'DNKK': {'country': 'Nigeria',        'flag': '🇳🇬', 'name': 'Kano FIR'},
    'DNAA': {'country': 'Nigeria',        'flag': '🇳🇬', 'name': 'Abuja FIR'},
    'HRYR': {'country': 'Rwanda',         'flag': '🇷🇼', 'name': 'Kigali FIR'},
    'HCMM': {'country': 'Somalia',        'flag': '🇸🇴', 'name': 'Mogadishu FIR'},
    'FAJS': {'country': 'South Africa',   'flag': '🇿🇦', 'name': 'Johannesburg FIR'},
    'HJJJ': {'country': 'South Sudan',    'flag': '🇸🇸', 'name': 'Juba FIR'},
    'HSSS': {'country': 'Sudan',          'flag': '🇸🇩', 'name': 'Khartoum FIR'},
    'HUEN': {'country': 'Uganda',         'flag': '🇺🇬', 'name': 'Entebbe FIR'},
    'FTTT': {'country': 'Chad',           'flag': '🇹🇩', 'name': "N'Djamena FIR"},
    'FMMM': {'country': 'Madagascar',     'flag': '🇲🇬', 'name': 'Antananarivo FIR'},
    'FQBE': {'country': 'Mozambique',     'flag': '🇲🇿', 'name': 'Beira FIR'},
    # Multi-country FIRs (ASECNA / joint) — cover new targets without own FIR
    'FCCC': {'country': 'Central Africa', 'flag': '🇨🇫', 'name': 'Brazzaville FIR (CAR / Eq. Guinea / Congo / Gabon)'},
    'GLRB': {'country': 'West Africa',    'flag': '🇬🇳', 'name': 'Roberts FIR (Guinea / Liberia / Sierra Leone)'},
    # Neighboring FIRs (high-context spillover)
    'HLLL': {'country': 'Libya',          'flag': '🇱🇾', 'name': 'Tripoli FIR'},
    'GMMM': {'country': 'Morocco',        'flag': '🇲🇦', 'name': 'Casablanca FIR'},
    'HECC': {'country': 'Egypt',          'flag': '🇪🇬', 'name': 'Cairo FIR'},
}

_africa_notam_cache = {'data': None, 'fetched_at': None, 'ttl': 6 * 3600}  # 6h


def _parse_africa_notam(notam_data, location_info):
    """Parse a single FAA NOTAM into structured format."""
    try:
        notam_text = notam_data.get('notamText', '').upper()

        notam_type = 'OTHER'
        icon = '📋'
        color = 'gray'

        if any(word in notam_text for word in ['AIRSPACE CLOSED', 'AIRSPACE CLO', 'FIR CLOSED']):
            notam_type = 'AIRSPACE CLOSURE'
            icon = '⛔'
            color = 'red'
        elif any(word in notam_text for word in ['RESTRICTED', 'PROHIBITED', 'DANGER AREA']):
            notam_type = 'FLIGHT RESTRICTION'
            icon = '🚫'
            color = 'orange'
        elif any(word in notam_text for word in ['MILITARY', 'MIL ACT', 'EXERCISE']):
            notam_type = 'MILITARY ACTIVITY'
            icon = '⚠️'
            color = 'yellow'
        elif any(word in notam_text for word in ['AIRPORT CLOSED', 'AD CLOSED', 'RWY CLOSED']):
            notam_type = 'AIRPORT CLOSURE'
            icon = '🛑'
            color = 'purple'
        elif any(word in notam_text for word in ['NAVAID', 'VOR', 'DME', 'ILS', 'U/S']):
            notam_type = 'NAVAID OUTAGE'
            icon = '📡'
            color = 'blue'
        elif any(word in notam_text for word in ['VOLCANIC', 'ASH', 'HAZARD', 'OBSTRUCTION']):
            notam_type = 'HAZARD'
            icon = '⚠️'
            color = 'gray'

        effective_date = notam_data.get('effectiveStart', '')
        expiry_date = notam_data.get('effectiveEnd', '')

        effective_formatted = ''
        expiry_formatted = ''

        if effective_date:
            try:
                eff_dt = datetime.fromisoformat(effective_date.replace('Z', '+00:00'))
                effective_formatted = eff_dt.strftime('%b %d, %Y')
            except Exception:
                effective_formatted = effective_date[:10]

        if expiry_date:
            try:
                exp_dt = datetime.fromisoformat(expiry_date.replace('Z', '+00:00'))
                expiry_formatted = exp_dt.strftime('%b %d, %Y')
            except Exception:
                expiry_formatted = expiry_date[:10]

        summary = notam_text[:150].strip()
        if len(notam_text) > 150:
            summary += '...'

        notam_id = notam_data.get('notamID', 'N/A')

        return {
            'id':              notam_id,
            'country':         location_info['country'],
            'flag':            location_info['flag'],
            'fir':             location_info['name'],
            'type':            notam_type,
            'classification':  notam_type,
            'icon':            icon,
            'color':           color,
            'summary':         summary,
            'effective_date':  effective_formatted,
            'expiry_date':     expiry_formatted,
            'effective':       effective_formatted or 'Immediately',
            'valid_range':     f"{effective_formatted} - {expiry_formatted}" if expiry_formatted else f"From {effective_formatted}",
            'notam_text':      notam_text,
            'source_url':      f"https://notams.aim.faa.gov/notamSearch/notam.html?id={notam_id}",
        }
    except Exception as e:
        print(f"[Africa NOTAM] parse error: {e}")
        return None


@app.route('/api/africa/notams', methods=['GET'])
def api_africa_notams():
    """Fetch active NOTAMs for African airspace (live FAA API)."""
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        now = time.time()

        if (not force
                and _africa_notam_cache['data'] is not None
                and _africa_notam_cache['fetched_at'] is not None
                and (now - _africa_notam_cache['fetched_at']) < _africa_notam_cache['ttl']):
            cached = _africa_notam_cache['data'].copy()
            cached['cached'] = True
            return jsonify(cached)

        notams = []
        base_url = "https://external-api.faa.gov/notamapi/v1/notams"

        for icao_code, info in AFRICA_FIRS.items():
            try:
                params = {
                    'locationICAOId': icao_code,
                    'responseType':   'application/json',
                }
                response = requests.get(base_url, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('notamList'):
                        for notam in data['notamList']:
                            parsed = _parse_africa_notam(notam, info)
                            if parsed:
                                notams.append(parsed)
                time.sleep(0.2)  # rate limit politeness
            except Exception as e:
                print(f"[Africa NOTAM] {icao_code} fetch error: {e}")
                continue

        priority_order = {
            'AIRSPACE CLOSURE':   1,
            'FLIGHT RESTRICTION': 2,
            'MILITARY ACTIVITY':  3,
            'AIRPORT CLOSURE':    4,
            'NAVAID OUTAGE':      5,
            'HAZARD':             6,
            'OTHER':              7,
        }
        notams.sort(key=lambda x: (priority_order.get(x['type'], 99), x.get('effective_date', '')))

        result = {
            'success':      True,
            'notams':       notams,
            'count':        len(notams),
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'cached':       False,
        }

        _africa_notam_cache['data']       = result
        _africa_notam_cache['fetched_at'] = now

        return jsonify(result)

    except Exception as e:
        print(f"[Africa NOTAM] Endpoint error: {e}")
        if _africa_notam_cache['data'] is not None:
            stale = _africa_notam_cache['data'].copy()
            stale['cached'] = True
            stale['stale'] = True
            return jsonify(stale)
        return jsonify({'success': False, 'notams': [], 'count': 0, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────
# FLIGHT DISRUPTIONS — curated baseline (no live API exists yet)
# /api/africa/flights
# Round 4+ will replace with live aggregator
# ─────────────────────────────────────────────────────────────

_africa_flights_cache = {'data': None, 'fetched_at': None, 'ttl': 12 * 3600}  # 12h

_AFRICA_FLIGHT_BASELINE = [
    {
        'airline':     'Lufthansa',
        'route':       'Frankfurt — Khartoum (KRT)',
        'destination': 'Khartoum',
        'status':      'Suspended',
        'headline':    'Khartoum service suspended indefinitely since April 2023 conflict.',
        'date':        '2023-04-15',
        'duration':    'Indefinite',
        'reason':      'Active conflict / airport non-operational',
        'source_url':  'https://www.lufthansa.com/',
        'data_as_of':  '2026-05-24',
    },
    {
        'airline':     'Air France',
        'route':       'Paris — Bamako (BKO)',
        'destination': 'Bamako',
        'status':      'Suspended',
        'headline':    'Air France Bamako service suspended; codeshare reroute via Air Algérie not currently active.',
        'date':        '2024-01-10',
        'duration':    'Indefinite',
        'reason':      'Political tensions / security situation',
        'source_url':  'https://www.airfrance.fr/',
        'data_as_of':  '2026-05-24',
    },
    {
        'airline':     'Air France',
        'route':       'Paris — Niamey (NIM)',
        'destination': 'Niamey',
        'status':      'Suspended',
        'headline':    'Air France Niamey service suspended since 2023 coup.',
        'date':        '2023-08-01',
        'duration':    'Indefinite',
        'reason':      'Diplomatic situation post-coup',
        'source_url':  'https://www.airfrance.fr/',
        'data_as_of':  '2026-05-24',
    },
    {
        'airline':     'Brussels Airlines',
        'route':       'Brussels — Kinshasa (FIH)',
        'destination': 'Kinshasa',
        'status':      'Disrupted',
        'headline':    'Kinshasa service operating with enhanced screening; Goma operations suspended.',
        'date':        '2026-05-15',
        'duration':    'Ongoing',
        'reason':      'Ebola Bundibugyo PHEIC — health screening',
        'source_url':  'https://www.brusselsairlines.com/',
        'data_as_of':  '2026-05-24',
    },
    {
        'airline':     'Kenya Airways',
        'route':       'Nairobi — Goma (GOM)',
        'destination': 'Goma',
        'status':      'Suspended',
        'headline':    'Goma service suspended due to Ebola quarantine zone + M23 security situation.',
        'date':        '2026-05-15',
        'duration':    'Indefinite',
        'reason':      'Ebola PHEIC + conflict',
        'source_url':  'https://www.kenya-airways.com/',
        'data_as_of':  '2026-05-24',
    },
    {
        'airline':     'RwandAir',
        'route':       'Kigali — Goma (GOM)',
        'destination': 'Goma',
        'status':      'Suspended',
        'headline':    'Kigali-Goma service suspended; DRC-Rwanda border partial closure.',
        'date':        '2026-05-18',
        'duration':    'Indefinite',
        'reason':      'Ebola PHEIC + diplomatic tensions',
        'source_url':  'https://www.rwandair.com/',
        'data_as_of':  '2026-05-24',
    },
    {
        'airline':     'Ethiopian Airlines',
        'route':       'Addis Ababa — Mogadishu (MGQ)',
        'destination': 'Mogadishu',
        'status':      'Disrupted',
        'headline':    'Mogadishu operations continue with enhanced security; periodic schedule changes.',
        'date':        '2026-05-01',
        'duration':    'Ongoing',
        'reason':      'Al-Shabaab security situation',
        'source_url':  'https://www.ethiopianairlines.com/',
        'data_as_of':  '2026-05-24',
    },
    {
        'airline':     'EgyptAir',
        'route':       'Cairo — Khartoum (KRT)',
        'destination': 'Khartoum',
        'status':      'Suspended',
        'headline':    'EgyptAir Khartoum service remains suspended; humanitarian charter ops only.',
        'date':        '2023-04-15',
        'duration':    'Indefinite',
        'reason':      'Sudan conflict',
        'source_url':  'https://www.egyptair.com/',
        'data_as_of':  '2026-05-24',
    },
]


@app.route('/api/africa/flights', methods=['GET'])
def api_africa_flights():
    """Return active flight disruptions for Africa (curated baseline)."""
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        now = time.time()

        if (not force
                and _africa_flights_cache['data'] is not None
                and _africa_flights_cache['fetched_at'] is not None
                and (now - _africa_flights_cache['fetched_at']) < _africa_flights_cache['ttl']):
            cached = _africa_flights_cache['data'].copy()
            cached['cached'] = True
            return jsonify(cached)

        result = {
            'success':       True,
            'count':         len(_AFRICA_FLIGHT_BASELINE),
            'disruptions':   _AFRICA_FLIGHT_BASELINE,
            'last_updated':  datetime.now(timezone.utc).isoformat(),
            'source':        'curated baseline + planned live aggregator',
            'cached':        False,
        }

        _africa_flights_cache['data']       = result
        _africa_flights_cache['fetched_at'] = now

        return jsonify(result)

    except Exception as e:
        print(f"[Africa Flights] Endpoint error: {e}")
        return jsonify({'success': False, 'disruptions': [], 'count': 0, 'error': str(e)}), 500


# ============================================================
# END PATCH v2 — africa.html supporting endpoints
# ============================================================

# ============================================================
# REGISTER OPTIONAL MODULES
# ============================================================

if COMMODITY_PROXY_AVAILABLE:
    try:
        register_africa_commodity_proxy(app)
        print('[Africa] ✅ Commodity proxy endpoints registered')
    except Exception as e:
        print(f'[Africa] ⚠️ Commodity proxy registration failed: {e}')

if CONVERGENCE_PROXY_AVAILABLE:
    try:
        register_africa_convergence_proxy(app)
        print('[Africa] ✅ Convergence proxy endpoints registered')
    except Exception as e:
        print(f'[Africa] ⚠️ Convergence proxy registration failed: {e}')

if ARTICLE_GATHERER_AVAILABLE:
    try:
        register_africa_articles_endpoints(app, start_scheduler=True)
        print('[Africa] ✅ Article gatherer endpoints registered (12h scheduler ON)')
    except Exception as e:
        print(f'[Africa] ⚠️ Article gatherer registration failed: {e}')

if SOMALIA_HUMANITARIAN_AVAILABLE:
    try:
        register_somalia_humanitarian_endpoints(app)
    except Exception as e:
        print(f'[Africa] ⚠️ Somalia humanitarian registration failed: {e}')

if SUDAN_HUMANITARIAN_AVAILABLE:
    try:
        register_sudan_humanitarian_endpoints(app)
    except Exception as e:
        print(f'[Africa] ⚠️ Sudan humanitarian registration failed: {e}')

if SOMALIA_RHETORIC_AVAILABLE:
    try:
        register_somalia_rhetoric_routes(app, start_background=True)
    except Exception as e:
        print(f'[Africa] ⚠️ Somalia rhetoric registration failed: {e}')

if SUDAN_RHETORIC_AVAILABLE:
    try:
        register_sudan_rhetoric_endpoints(app)
        start_sudan_rhetoric_refresh()
        print('[Africa] ✅ Sudan rhetoric endpoints registered')
    except Exception as e:
        print(f'[Africa] ⚠️ Sudan rhetoric registration failed: {e}')

if AFRICA_BLUF_AVAILABLE:
    try:
        register_africa_bluf_routes(app)
        print('[Africa] ✅ Africa regional BLUF endpoints registered')
    except Exception as e:
        print(f'[Africa] ⚠️ Africa BLUF registration failed: {e}')

if NIGERIA_STABILITY_AVAILABLE:
    try:
        register_nigeria_stability_endpoints(app, start_background=True)
        print('[Africa] ✅ Nigeria stability endpoints registered (12h scheduler ON)')
    except Exception as e:
        print(f'[Africa] ⚠️ Nigeria stability registration failed: {e}')


# ============================================================
# BOOT
# ============================================================

_start_background_refresh()

print('=' * 60)
print(f'  ASIFAH AFRICA BACKEND v1.0.0 -- BOOT COMPLETE')
print(f'  Countries: {len(COUNTRY_CONFIG)} ({", ".join(COUNTRY_CONFIG.keys())})')
print(f'  Redis:     {"✅ configured" if UPSTASH_REDIS_URL else "⚠️  not configured"}')
print(f'  NewsAPI:   {"✅ configured" if NEWSAPI_KEY else "⚠️  not configured"}')
print(f'  Brave:     {"✅ configured" if BRAVE_API_KEY else "⚠️  not configured"}')
print(f'  Telegram:  {"✅ module loaded" if TELEGRAM_AFRICA_AVAILABLE else "⏳ pending"}')
print(f'  Bluesky:   {"✅ module loaded" if BLUESKY_AFRICA_AVAILABLE else "⏳ pending"}')
print(f'  Commodity: {"✅ proxy loaded" if COMMODITY_PROXY_AVAILABLE else "⏳ pending"}')
print(f'  Articles:  {"✅ gatherer loaded" if ARTICLE_GATHERER_AVAILABLE else "⏳ pending"}')
print(f'  Sudan:     {"✅ tracker loaded" if SUDAN_RHETORIC_AVAILABLE else "⏳ pending"}')
print(f'  BLUF:      {"✅ regional BLUF loaded" if AFRICA_BLUF_AVAILABLE else "⏳ pending"}')
print('=' * 60)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
