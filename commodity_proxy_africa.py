"""
========================================
COMMODITY PROXY — Africa (v1.0.0)
========================================
Mirrors commodity_proxy_europe.py pattern.

The canonical commodity_tracker lives on the ME backend
(asifah-backend.onrender.com). This module proxies per-country
commodity-pressure data into the Africa backend so the Africa
frontend can render commodity cards without cross-domain CORS
issues, AND so Africa scans don't need to know about commodity
internals.

ARCHITECTURE:
  Africa frontend / africa.html / per-country page
        │
        ▼
  GET /api/africa/commodity/<target>           (this module)
        │
        ▼  (12-hour Redis cache)
  GET asifah-backend.onrender.com/api/commodity-pressure/<target>
        │
        ▼
  Canonical commodity_tracker on ME backend

12-hour cache TTL — commodity sparklines update slowly, news scans
update every few hours; no need to hammer the ME backend.

v1.0.0 — May 24 2026 — Initial Africa backend launch.
"""

import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

# ── Canonical source ──
ME_BACKEND_BASE = 'https://asifah-backend.onrender.com'
PROXY_TIMEOUT_SEC = 25
CACHE_TTL_HOURS = 12

# ── Africa-relevant countries (matches app.py COUNTRY_CONFIG) ──
AFRICA_COMMODITY_TARGETS = [
    'sudan', 'drc', 'uganda', 'rwanda', 'south_sudan',
    'kenya', 'tanzania', 'ethiopia', 'somalia', 'nigeria',
    'mali', 'niger', 'burkina_faso', 'south_africa',
]

# ── Upstash Redis (shared with main app.py) ──
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')


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
        print(f'[Commodity Proxy Africa] Redis GET error: {str(e)[:120]}')
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
        print(f'[Commodity Proxy Africa] Redis SET error: {str(e)[:120]}')
        return False


def _fetch_from_me(target):
    """
    Pull commodity-pressure data from the ME backend for a given target.
    """
    url = f'{ME_BACKEND_BASE}/api/commodity-pressure/{target}'
    try:
        r = requests.get(url, timeout=PROXY_TIMEOUT_SEC)
        if r.status_code != 200:
            print(f'[Commodity Proxy Africa] ME backend HTTP {r.status_code} for {target}')
            return None
        return r.json()
    except requests.exceptions.Timeout:
        print(f'[Commodity Proxy Africa] ME backend timeout for {target}')
        return None
    except Exception as e:
        print(f'[Commodity Proxy Africa] ME backend error for {target}: {str(e)[:120]}')
        return None


def get_africa_commodity_data(target, force=False):
    """
    Returns cached or fresh commodity-pressure data for an Africa target.

    Cache pattern:
      africa:commodity:<target>  -> {ttl 12h, value = ME backend response}
    """
    target = target.lower()
    if target not in AFRICA_COMMODITY_TARGETS:
        return None

    cache_key = f'africa:commodity:{target}'

    if not force:
        cached = _redis_get(cache_key)
        if cached:
            cached['proxy_cached'] = True
            cached['proxy_fetched_at'] = cached.get('proxy_fetched_at')
            return cached

    fresh = _fetch_from_me(target)
    if fresh is None:
        # On failure, return stale cache if available
        stale = _redis_get(cache_key)
        if stale:
            stale['proxy_cached'] = True
            stale['proxy_stale'] = True
            return stale
        return None

    fresh['proxy_cached'] = False
    fresh['proxy_fetched_at'] = datetime.now(timezone.utc).isoformat()
    _redis_set(cache_key, fresh, ttl_seconds=CACHE_TTL_HOURS * 3600)
    print(f'[Commodity Proxy Africa] ✅ Cached {target} from ME backend')
    return fresh


# ============================================================
# FLASK ENDPOINTS
# ============================================================

def register_africa_commodity_proxy(app):
    """
    Register Africa commodity proxy endpoints on the Flask app.

    Endpoints:
      GET /api/africa/commodity/<target>          per-target data
      GET /api/africa/commodity/<target>?force=true  bypass cache
      GET /api/africa/commodity-debug             cache + target info
    """

    @app.route('/api/africa/commodity/<target>', methods=['GET'])
    def africa_commodity_target(target):
        force = request.args.get('force', 'false').lower() == 'true'
        target_low = target.lower()

        if target_low not in AFRICA_COMMODITY_TARGETS:
            return jsonify({
                'success': False,
                'error':   f'Target "{target}" not in Africa commodity coverage',
                'available_targets': AFRICA_COMMODITY_TARGETS,
            }), 404

        data = get_africa_commodity_data(target_low, force=force)
        if data is None:
            return jsonify({
                'success': False,
                'error':   'Failed to fetch commodity data from ME backend',
                'target':  target_low,
                'me_backend': ME_BACKEND_BASE,
            }), 503

        return jsonify(data)

    @app.route('/api/africa/commodity-debug', methods=['GET'])
    def africa_commodity_debug():
        """Diagnostic endpoint: cache status per target."""
        out = {
            'service':     'commodity_proxy_africa',
            'version':     '1.0.0',
            'me_backend':  ME_BACKEND_BASE,
            'targets':     AFRICA_COMMODITY_TARGETS,
            'cache_ttl_h': CACHE_TTL_HOURS,
            'cache_status': {},
        }
        for target in AFRICA_COMMODITY_TARGETS:
            cached = _redis_get(f'africa:commodity:{target}')
            out['cache_status'][target] = {
                'cached':           bool(cached),
                'proxy_fetched_at': cached.get('proxy_fetched_at') if cached else None,
            }
        return jsonify(out)
