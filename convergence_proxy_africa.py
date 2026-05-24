"""
========================================
CONVERGENCE PROXY — Africa (v1.0.0)
========================================
Reads convergence_registry from ME backend and surfaces the 3
Africa-anchored convergences plus any others affecting Africa
regions.

The canonical convergence_registry lives on ME backend
(asifah-backend.onrender.com/api/convergence/...). This module:
  1. Caches the registry locally (1-hour TTL)
  2. Filters for Africa-relevant convergences
  3. Exposes Africa-specific endpoints for africa.html consumption

AFRICA-ANCHORED CONVERGENCES (as of May 2026):
  - cobalt_drc_active       — DRC anchor
  - diamonds_sanctions_regime — South Africa + Zimbabwe + DRC anchor
  - phosphate_food_security — Morocco anchor (commodity-Africa impact)

AFRICA-AFFECTED CONVERGENCES (not anchored here but read Africa):
  - sanctions_evasion_cluster
  - belt_and_road_resource_leverage
  - arms_trade_realignment

v1.0.0 — May 24 2026 — Initial Africa backend launch.
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

ME_BACKEND_BASE       = 'https://asifah-backend.onrender.com'
PROXY_TIMEOUT_SEC     = 15
CACHE_TTL_SECONDS     = 3600   # 1 hour — registry is fairly static

UPSTASH_REDIS_URL     = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN   = os.environ.get('UPSTASH_REDIS_TOKEN')

CACHE_KEY_FULL_REG    = 'africa:convergence:full_registry'
CACHE_KEY_PREFIX_BY_C = 'africa:convergence:by_country:'

# Africa-anchored convergence IDs we care about most
AFRICA_ANCHORED_IDS = [
    'cobalt_drc_active',
    'diamonds_sanctions_regime',
    'phosphate_food_security',
]

# Trigger-region values that map to Africa
AFRICA_REGION_TAGS = ['africa']


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
        print(f'[Convergence Proxy Africa] Redis GET error: {str(e)[:120]}')
        return None


def _redis_set(key, value, ttl_seconds):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        r = requests.post(
            UPSTASH_REDIS_URL,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            json=['SET', key, json.dumps(value), 'EX', str(ttl_seconds)],
            timeout=5,
        )
        return r.status_code == 200
    except Exception as e:
        print(f'[Convergence Proxy Africa] Redis SET error: {str(e)[:120]}')
        return False


def _fetch_full_registry_from_me():
    """Pull the full convergence registry from ME backend."""
    url = f'{ME_BACKEND_BASE}/api/convergence/all'
    try:
        r = requests.get(url, timeout=PROXY_TIMEOUT_SEC)
        if r.status_code != 200:
            print(f'[Convergence Proxy Africa] ME backend HTTP {r.status_code}')
            return None
        return r.json()
    except Exception as e:
        print(f'[Convergence Proxy Africa] fetch error: {str(e)[:120]}')
        return None


def _filter_africa_relevant(registry):
    """
    Filter the full convergence registry down to entries that are
    Africa-anchored or Africa-affected.
    """
    if not registry or not isinstance(registry, dict):
        return []

    entries = registry.get('registry', []) or registry.get('convergences', [])
    africa_entries = []

    for entry in entries:
        # Anchored in Africa (trigger_region or regions include 'africa')
        trigger_region = (entry.get('trigger_region') or '').lower()
        regions = [r.lower() for r in (entry.get('regions') or [])]

        if trigger_region in AFRICA_REGION_TAGS or any(r in AFRICA_REGION_TAGS for r in regions):
            africa_entries.append(entry)
            continue

        # Explicit ID match (Africa-anchored canonical list)
        if entry.get('id') in AFRICA_ANCHORED_IDS:
            africa_entries.append(entry)
            continue

    return africa_entries


def get_africa_convergences(force=False):
    """
    Returns the Africa-filtered convergence registry.

    Cache: africa:convergence:full_registry (1h TTL on full pull,
    Africa filtering is fast so re-applied each call).
    """
    if not force:
        cached = _redis_get(CACHE_KEY_FULL_REG)
        if cached:
            africa_only = _filter_africa_relevant(cached)
            return {
                'success':       True,
                'count':         len(africa_only),
                'convergences':  africa_only,
                'cached':        True,
                'cached_at':     cached.get('fetched_at'),
            }

    fresh = _fetch_full_registry_from_me()
    if fresh is None:
        # Try stale cache as last resort
        stale = _redis_get(CACHE_KEY_FULL_REG)
        if stale:
            africa_only = _filter_africa_relevant(stale)
            return {
                'success':       True,
                'count':         len(africa_only),
                'convergences':  africa_only,
                'cached':        True,
                'stale':         True,
                'cached_at':     stale.get('fetched_at'),
            }
        return {
            'success': False,
            'error':   'Failed to fetch convergence registry from ME backend',
            'count':   0,
            'convergences': [],
        }

    # Cache full registry; filter on response
    _redis_set(CACHE_KEY_FULL_REG, fresh, ttl_seconds=CACHE_TTL_SECONDS)
    africa_only = _filter_africa_relevant(fresh)
    print(f'[Convergence Proxy Africa] ✅ Cached full registry; '
          f'{len(africa_only)} Africa-relevant convergence(s) surfaced')
    return {
        'success':       True,
        'count':         len(africa_only),
        'convergences':  africa_only,
        'cached':        False,
        'fetched_at':    fresh.get('fetched_at'),
    }


def get_africa_convergences_by_country(country):
    """Filter convergences down to those affecting a specific Africa country."""
    country = country.lower()
    bundle = get_africa_convergences()
    convergences = bundle.get('convergences', []) or []

    matches = []
    for entry in convergences:
        if (entry.get('country') or '').lower() == country:
            matches.append(entry)
            continue
        regions = [r.lower() for r in (entry.get('regions') or [])]
        if country in regions:
            matches.append(entry)

    return {
        'success':       True,
        'country':       country,
        'count':         len(matches),
        'convergences':  matches,
        'cached':        bundle.get('cached', False),
    }


# ============================================================
# FLASK ENDPOINTS
# ============================================================

def register_africa_convergence_proxy(app):
    """
    Register Africa convergence proxy endpoints on the Flask app.

    Endpoints:
      GET /api/africa/convergence/all              — Africa-filtered registry
      GET /api/africa/convergence/by-country/<c>   — country-filtered
      GET /api/africa/convergence-debug            — cache + filter info
    """

    @app.route('/api/africa/convergence/all', methods=['GET'])
    def africa_convergence_all():
        force = request.args.get('force', 'false').lower() == 'true'
        return jsonify(get_africa_convergences(force=force))

    @app.route('/api/africa/convergence/by-country/<country>', methods=['GET'])
    def africa_convergence_by_country(country):
        return jsonify(get_africa_convergences_by_country(country))

    @app.route('/api/africa/convergence-debug', methods=['GET'])
    def africa_convergence_debug():
        cached = _redis_get(CACHE_KEY_FULL_REG)
        return jsonify({
            'service':              'convergence_proxy_africa',
            'version':              '1.0.0',
            'me_backend':           ME_BACKEND_BASE,
            'cache_key':            CACHE_KEY_FULL_REG,
            'cache_ttl_seconds':    CACHE_TTL_SECONDS,
            'has_cached_registry':  bool(cached),
            'cached_at':            (cached or {}).get('fetched_at'),
            'africa_anchored_ids':  AFRICA_ANCHORED_IDS,
            'africa_region_tags':   AFRICA_REGION_TAGS,
        })
