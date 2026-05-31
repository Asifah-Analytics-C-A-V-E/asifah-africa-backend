# -*- coding: utf-8 -*-
"""
NGX Index Scraper — v1.0.0 (May 31 2026)
========================================

Pulls real NGX All-Share Index (ASI) from african open data mirrors since Yahoo
Finance does NOT host this index directly.

ARCHITECTURE:
  Primary source:   https://afx.kwayisi.org/ngx/           (kwayisi mirror)
  Secondary source: https://www.african-markets.com/en/stock-markets/ngse
  Tertiary fallback: caller's last-known Redis value
  Quaternary:        None (caller decides what to do)

REGEX STRATEGY:
  Multi-pattern matching against known string anchors. If the primary site
  changes structure, we fall through to the secondary. If both fail, we return
  None and the caller can decide whether to fall back to NGE ETF or last-known.

CACHE: 1-hour Redis TTL. NGX trades 9-4 WAT Mon-Fri (5 AM - 11 AM ET).

SPARKLINE: this module does NOT build a sparkline directly — sparklines come
from our own historical scan accumulation via the parent nigeria_stability
module's history snapshots.

Reusable for: Egypt (EGX), Kenya (NSE Kenya), South Africa (JSE) — same source
pattern. Future modules just clone this file and swap the source URL + ticker anchors.
"""

import os
import re
import json
import requests
from datetime import datetime, timezone


# ============================================
# CONFIG
# ============================================

KWAYISI_URL = 'https://afx.kwayisi.org/ngx/'
AFRICAN_MARKETS_URL = 'https://www.african-markets.com/en/stock-markets/ngse'
SCRAPE_TIMEOUT_SEC = 15

# Browser-like UA to avoid trivial bot blocks
USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
)


# ============================================
# REGEX PATTERNS (most specific first)
# ============================================

# Kwayisi patterns — observed format: "ASI Index ... 160,591.76 (+640.68)"
# Markdown extraction shows: "ASI Index\nYear-to-Date\nMarket Cap.\n160,591.76 (+640.68)"
# Raw HTML likely has these in nearby tags — we match the most specific shape first.
KWAYISI_PATTERNS = [
    # Most specific: "ASI Index ... 160,591.76 (+640.68) ... +4,978.73 (3.2%)"
    # Pulls value, daily change, AND YTD change/pct in one match
    re.compile(
        r'ASI\s*Index[\s\S]{0,300}?'
        r'(?P<value>\d{1,3}(?:,\d{3})*\.\d{2})\s*'
        r'\(\s*(?P<change>[+-]?\d{1,3}(?:,\d{3})*\.\d{2})\s*\)',
        re.IGNORECASE,
    ),
    # "ASI ▴640.68 (0.4%)" pattern (real-time tick line)
    re.compile(
        r'ASI[\s\u25b4\u25be\u25b2\u25bc\u25b3\u25b5\u25bf]+'
        r'(?P<change>[+-]?\d{1,3}(?:,\d{3})*\.\d{2})\s*'
        r'\(\s*(?P<pct>[+-]?\d+\.\d+)%\s*\)',
        re.IGNORECASE,
    ),
    # Fallback: any "160,591.76" near "ASI Index" within 500 chars
    re.compile(
        r'ASI\s*Index[\s\S]{0,500}?(?P<value>\d{1,3}(?:,\d{3})*\.\d{2})',
        re.IGNORECASE,
    ),
]

AFRICAN_MARKETS_PATTERNS = [
    # African-markets often has "All-Share Index" or "ASI" with similar shape
    re.compile(
        r'(?:All[- ]Share\s*Index|ASI)[^\d-]{0,300}?'
        r'(?P<value>\d{1,3}(?:,\d{3})*\.\d{2})\s*'
        r'\(\s*(?P<change>[+-]?\d{1,3}(?:,\d{3})*\.\d{2})\s*\)',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r'(?:All[- ]Share\s*Index|ASI)[\s\S]{0,500}?(?P<value>\d{1,3}(?:,\d{3})*\.\d{2})',
        re.IGNORECASE,
    ),
]


# ============================================
# PARSER
# ============================================

def _parse_with_patterns(html, patterns, source_name):
    """
    Run regex patterns in order, return first match with parsed numbers.
    Returns dict with at minimum {value} or None.
    """
    for i, pattern in enumerate(patterns):
        m = pattern.search(html)
        if not m:
            continue
        try:
            groups = m.groupdict()
            value_str = groups.get('value')
            change_str = groups.get('change')
            pct_str = groups.get('pct')

            # Convert "160,591.76" → 160591.76
            value = float(value_str.replace(',', '')) if value_str else None
            change = float(change_str.replace(',', '')) if change_str else None
            pct = float(pct_str) if pct_str else None

            # Compute pct from value+change if not directly given
            if pct is None and value is not None and change is not None and (value - change) != 0:
                pct = (change / (value - change)) * 100

            # Compute change from value+pct if not directly given
            if change is None and value is not None and pct is not None:
                # value = prev * (1 + pct/100), so prev = value / (1 + pct/100), change = value - prev
                prev = value / (1 + pct / 100) if (1 + pct / 100) != 0 else None
                if prev is not None:
                    change = value - prev

            if value is None and change is not None and pct is not None and pct != 0:
                # Edge case: ▴change(pct) line without absolute value
                # We can't reconstruct absolute value here, skip
                continue

            if value is None:
                continue

            print(f'[NGX Scraper] ✅ {source_name} pattern #{i+1} matched: '
                  f'value={value:,.2f}, change={change}, pct={pct}')
            return {
                'value':  round(value, 2),
                'change': round(change, 2) if change is not None else None,
                'pct':    round(pct, 3) if pct is not None else None,
                'source': source_name,
                'pattern_index': i + 1,
            }
        except (ValueError, TypeError) as e:
            print(f'[NGX Scraper] {source_name} pattern #{i+1} matched but parse failed: {e}')
            continue
    return None


def _fetch_html(url, timeout=SCRAPE_TIMEOUT_SEC):
    """Fetch raw HTML with browser-like UA. Returns string or None on failure."""
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={
                'User-Agent': USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            },
        )
        if r.status_code != 200:
            print(f'[NGX Scraper] {url} returned HTTP {r.status_code}')
            return None
        return r.text
    except Exception as e:
        print(f'[NGX Scraper] {url} fetch error: {str(e)[:120]}')
        return None


# ============================================
# PUBLIC API
# ============================================

def scrape_ngx_index():
    """
    Attempt to scrape the NGX All-Share Index from primary then secondary sources.

    Returns dict on success:
      {
          'value': float,         # ASI level (e.g. 160591.76)
          'change_24h': float,    # absolute change vs previous close
          'change_pct_24h': float,# percentage change vs previous close
          'source': str,          # which source succeeded
          'pattern_index': int,   # which regex pattern matched
          'scraped_at': ISO datetime str,
      }
    Returns None if both sources fail.
    """
    # Try kwayisi first
    html = _fetch_html(KWAYISI_URL)
    if html:
        parsed = _parse_with_patterns(html, KWAYISI_PATTERNS, 'kwayisi')
        if parsed and parsed.get('value'):
            return {
                'value':          parsed['value'],
                'change_24h':     parsed.get('change'),
                'change_pct_24h': parsed.get('pct') or 0,
                'source':         'afx.kwayisi.org',
                'pattern_index':  parsed['pattern_index'],
                'scraped_at':     datetime.now(timezone.utc).isoformat(),
            }

    # Fall through to african-markets
    html = _fetch_html(AFRICAN_MARKETS_URL)
    if html:
        parsed = _parse_with_patterns(html, AFRICAN_MARKETS_PATTERNS, 'african-markets')
        if parsed and parsed.get('value'):
            return {
                'value':          parsed['value'],
                'change_24h':     parsed.get('change'),
                'change_pct_24h': parsed.get('pct') or 0,
                'source':         'african-markets.com',
                'pattern_index':  parsed['pattern_index'],
                'scraped_at':     datetime.now(timezone.utc).isoformat(),
            }

    print('[NGX Scraper] ❌ Both primary and secondary sources failed')
    return None


# ============================================
# STANDALONE TEST
# ============================================

if __name__ == '__main__':
    print('Testing NGX Index Scraper...')
    result = scrape_ngx_index()
    if result:
        print(json.dumps(result, indent=2))
    else:
        print('FAILED — both sources unreachable or layouts changed')
