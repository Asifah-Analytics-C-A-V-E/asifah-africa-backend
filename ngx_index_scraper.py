# -*- coding: utf-8 -*-
"""
NGX Index Scraper — v1.0.3 (May 31 2026)
========================================

Pulls real NGX All-Share Index (ASI) from african open data mirrors since Yahoo
Finance does NOT host this index directly.

v1.0.3 changes from v1.0.0:
  - DROPPED african-markets.com fallback — the page requires JavaScript rendering
    to show the ASI, and our requests-based scrape was matching unrelated numbers
    (Value Traded, Market Cap fragments). Better to show "Unavailable" than wrong data.
  - Added PLAUSIBILITY SANITY-CHECK: NGX-ASI has been in the 100,000-200,000 range
    for the past 2+ years. Any matched value outside [50,000 — 500,000] is rejected
    as obviously wrong, falls through to next pattern.
  - Added verbose logging on failure: HTTP status code, response size, exception type,
    truncated response body preview. Helps diagnose Render-side scrape failures.

ARCHITECTURE:
  Primary source:   https://afx.kwayisi.org/ngx/           (kwayisi mirror)
  No secondary — if kwayisi fails, caller returns last-known cache or Unavailable.

REGEX STRATEGY:
  Multi-pattern matching against known string anchors with plausibility check.

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
AFRICAN_MARKETS_URL = 'https://www.african-markets.com/en/stock-markets/ngse'  # kept for reference, no longer used
SCRAPE_TIMEOUT_SEC = 20  # bumped from 15 — kwayisi can be slow

# NGX ASI plausibility range (v1.0.3 — May 31 2026)
# ASI has been in the 100,000-170,000 range for the past 2+ years.
# Outside this band = almost certainly wrong (regex matched unrelated number).
NGX_ASI_MIN_PLAUSIBLE = 50000     # generous lower bound
NGX_ASI_MAX_PLAUSIBLE = 500000    # generous upper bound

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

def _parse_with_patterns(html, patterns, source_name, plausibility=(NGX_ASI_MIN_PLAUSIBLE, NGX_ASI_MAX_PLAUSIBLE)):
    """
    Run regex patterns in order, return first match with parsed numbers
    THAT PASSES PLAUSIBILITY CHECK.

    plausibility: (min, max) tuple — values outside this range are rejected.
                  v1.0.3 — added because v1.0.0 accepted "3,828.68" from
                  african-markets which was actually a different widget number.
    """
    min_val, max_val = plausibility
    for i, pattern in enumerate(patterns):
        for m in pattern.finditer(html):  # iterate ALL matches, not just first
            try:
                groups = m.groupdict()
                value_str = groups.get('value')
                change_str = groups.get('change')
                pct_str = groups.get('pct')

                # Convert "160,591.76" → 160591.76
                value = float(value_str.replace(',', '')) if value_str else None
                change = float(change_str.replace(',', '')) if change_str else None
                pct = float(pct_str) if pct_str else None

                # PLAUSIBILITY CHECK — reject obviously-wrong matches
                if value is not None and (value < min_val or value > max_val):
                    print(f'[NGX Scraper] {source_name} pattern #{i+1}: implausible value {value:,.2f} '
                          f'(outside [{min_val:,}, {max_val:,}]) — rejecting, continuing search')
                    continue

                # Compute pct from value+change if not directly given
                if pct is None and value is not None and change is not None and (value - change) != 0:
                    pct = (change / (value - change)) * 100

                # Compute change from value+pct if not directly given
                if change is None and value is not None and pct is not None:
                    prev = value / (1 + pct / 100) if (1 + pct / 100) != 0 else None
                    if prev is not None:
                        change = value - prev

                if value is None and change is not None and pct is not None and pct != 0:
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
    """Fetch raw HTML with browser-like UA. Returns string or None on failure.

    v1.0.3: verbose logging on failure (HTTP code, content length, exception type)
    to help diagnose Render-side scrape issues.
    """
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
            preview = (r.text[:200] if r.text else '(empty body)').replace('\n', ' ')
            print(f'[NGX Scraper] {url} HTTP {r.status_code} | size={len(r.text)} | preview="{preview}"')
            return None
        if len(r.text) < 500:
            print(f'[NGX Scraper] {url} suspiciously small response ({len(r.text)} bytes) — likely blocked')
            print(f'[NGX Scraper] body preview: {r.text[:200]}')
            return None
        print(f'[NGX Scraper] {url} OK — {len(r.text):,} bytes')
        return r.text
    except requests.exceptions.Timeout:
        print(f'[NGX Scraper] {url} TIMEOUT after {timeout}s')
        return None
    except requests.exceptions.ConnectionError as e:
        print(f'[NGX Scraper] {url} CONNECTION ERROR: {str(e)[:120]}')
        return None
    except Exception as e:
        print(f'[NGX Scraper] {url} UNEXPECTED ERROR ({type(e).__name__}): {str(e)[:120]}')
        return None


# ============================================
# PUBLIC API
# ============================================

def scrape_ngx_index():
    """
    Attempt to scrape the NGX All-Share Index from kwayisi.

    Returns dict on success:
      {
          'value': float,         # ASI level (e.g. 160591.76)
          'change_24h': float,    # absolute change vs previous close
          'change_pct_24h': float,# percentage change vs previous close
          'source': str,          # which source succeeded
          'pattern_index': int,   # which regex pattern matched
          'scraped_at': ISO datetime str,
      }
    Returns None if kwayisi unreachable or no plausible value found.

    v1.0.3: dropped african-markets fallback. african-markets renders the ASI
    via JavaScript that our requests-based scraper cannot evaluate. Without JS,
    the only numbers visible to regex are unrelated widgets (Value Traded,
    Market Cap fragments), which caused v1.0.0 to return 3,828.68 instead of
    ~160,591.76. Better to return None and let the caller surface "Unavailable"
    than to display wrong data. (Data honesty principle.)
    """
    # Primary (and only) source: kwayisi
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
        else:
            print('[NGX Scraper] kwayisi returned HTML but no plausible NGX value found')

    print('[NGX Scraper] ❌ kwayisi unreachable or value extraction failed')
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
