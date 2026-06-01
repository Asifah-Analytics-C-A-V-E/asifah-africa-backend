# -*- coding: utf-8 -*-
"""
NGX Pulse API Client — v1.0.0 (June 1 2026)
==========================================

Primary data source for the NGX All-Share Index (ASI).

Why NGX Pulse:
  - Native Nigerian platform built FOR NGX data (ngxpulse.ng)
  - Direct ASI endpoint returns value + daily %change + market cap + breadth
  - 30-second data refresh (we only poll every 12 hours, so this is plenty)
  - Free 'Personal' tier: 10 req/min, 100 req/day — well within our needs
  - Tracks 150+ NGX-listed equities; could power future Nigeria deep-dive features

Why not Twelve Data:
  - International API; their free tier coverage of African exchanges is sparse
  - NGX-specific data (market cap, breadth) not exposed cleanly
  - More expensive to scale ($29/mo vs NGX Pulse equivalent)

API authentication:
  - Pass NGX_PULSE_API_KEY env var (set in Render env vars)
  - Header: X-API-Key: <key>
  - Get a key at https://ngxpulse.ng/api (self-serve, instant)

Documentation: https://ngxpulse.ng/api
"""

import os
import requests
from datetime import datetime, timezone


# ============================================
# CONFIG
# ============================================

NGX_PULSE_BASE_URL = 'https://www.ngxpulse.ng'
NGX_PULSE_MARKET_ENDPOINT = '/api/ngxdata/market'
NGX_PULSE_INDEX_ENDPOINT = '/api/ngxdata/indices/ASI'
API_TIMEOUT_SEC = 15


# ============================================
# PUBLIC API
# ============================================

def fetch_ngx_via_pulse_api():
    """
    Fetch NGX All-Share Index from NGX Pulse API.

    Returns dict on success:
      {
          'value': float,         # ASI level (e.g. 250385.47)
          'change_24h': float,    # absolute change in points
          'change_pct_24h': float,# percentage change
          'market_cap_ngn': float,# bonus: total market cap
          'volume': int,          # bonus: total shares traded
          'value_traded_ngn': float,  # bonus: NGN value traded
          'deals': int,           # bonus: number of deals
          'advancers': int,       # bonus: stocks that gained
          'decliners': int,       # bonus: stocks that declined
          'source': 'ngxpulse.ng',
          'scraped_at': ISO datetime str,
      }
    Returns None on any failure (caller falls back to scraper).
    """
    api_key = os.environ.get('NGX_PULSE_API_KEY', '').strip()
    if not api_key:
        print('[NGX Pulse] ⚠️ NGX_PULSE_API_KEY env var not set — skipping primary, falling to scraper')
        return None

    url = NGX_PULSE_BASE_URL + NGX_PULSE_MARKET_ENDPOINT
    try:
        r = requests.get(
            url,
            timeout=API_TIMEOUT_SEC,
            headers={
                'X-API-Key': api_key,
                'Accept': 'application/json',
                'User-Agent': 'AsifahAnalytics/1.0 (asifahanalytics.com)',
            },
        )
        if r.status_code == 401 or r.status_code == 403:
            print(f'[NGX Pulse] ❌ Auth failed ({r.status_code}) — check NGX_PULSE_API_KEY is correct')
            return None
        if r.status_code == 429:
            print('[NGX Pulse] ⚠️ Rate limit hit (429) — falling to scraper')
            return None
        if r.status_code != 200:
            print(f'[NGX Pulse] ❌ HTTP {r.status_code}: {r.text[:200]}')
            return None

        data = r.json()
        asi_value = data.get('asi')
        pct_change = data.get('pct_change')

        if asi_value is None:
            print(f'[NGX Pulse] ❌ Response missing "asi" field: {str(data)[:200]}')
            return None

        # Plausibility sanity check (same logic as scraper)
        if asi_value < 50000 or asi_value > 500000:
            print(f'[NGX Pulse] ❌ Implausible ASI value {asi_value:,.2f} (expected 50k-500k range)')
            return None

        # Compute absolute change from pct + value
        change_abs = None
        if pct_change is not None and pct_change != 0:
            prev_close = asi_value / (1 + pct_change / 100)
            change_abs = asi_value - prev_close

        result = {
            'value':          round(float(asi_value), 2),
            'change_24h':     round(change_abs, 2) if change_abs is not None else None,
            'change_pct_24h': round(float(pct_change), 3) if pct_change is not None else 0,
            'market_cap_ngn': data.get('market_cap'),
            'volume':         data.get('volume'),
            'value_traded_ngn': data.get('value'),
            'deals':          data.get('deals'),
            'advancers':      data.get('advancers'),
            'decliners':      data.get('decliners'),
            'unchanged':      data.get('unchanged'),
            'source':         'ngxpulse.ng',
            'scraped_at':     datetime.now(timezone.utc).isoformat(),
        }
        print(f'[NGX Pulse] ✅ ASI: {result["value"]:,.2f} ({result["change_pct_24h"]:+.2f}%) — market cap NGN {(result["market_cap_ngn"] or 0)/1e12:.2f}Tr')
        return result

    except requests.exceptions.Timeout:
        print(f'[NGX Pulse] ❌ Timeout after {API_TIMEOUT_SEC}s')
        return None
    except requests.exceptions.ConnectionError as e:
        print(f'[NGX Pulse] ❌ Connection error: {str(e)[:120]}')
        return None
    except ValueError as e:
        # JSON parse error
        print(f'[NGX Pulse] ❌ JSON parse error: {str(e)[:120]}')
        return None
    except Exception as e:
        print(f'[NGX Pulse] ❌ Unexpected error ({type(e).__name__}): {str(e)[:120]}')
        return None


# ============================================
# STANDALONE TEST
# ============================================

if __name__ == '__main__':
    import json
    print('Testing NGX Pulse API client...')
    result = fetch_ngx_via_pulse_api()
    if result:
        print(json.dumps(result, indent=2))
    else:
        print('FAILED — check NGX_PULSE_API_KEY env var and network')
