"""
========================================
BLUESKY — Africa Executive & Government Statement Monitor (v1.0.0)
========================================
Mirrors bluesky_signals_europe.py / bluesky_signals_wha.py pattern.

Uses Bluesky's public AppView API (https://public.api.bsky.app) — no
auth required, stable JSON endpoint:
  /xrpc/app.bsky.feed.getAuthorFeed?actor={handle}&limit={N}

NOTE on Africa Bluesky coverage:
  African government Bluesky presence is THIN as of May 2026. The
  channels available are largely:
    - International watchdog accounts (ICG, ACLED, Africa CDC mirrors)
    - Diplomatic accounts (US AfricaCom mirrors, EU AU delegation)
    - Journalism Bluesky native accounts (Africa-focused journalists)
  Native African government Bluesky accounts are rare — most state
  comms remain on X or Facebook. Accordingly, the per-country
  account lists below are short.

Returns the same article dict shape as the canonical scan pipeline,
so downstream scoring works unchanged.

v1.0.0 — May 24 2026 — Initial Africa backend launch.
"""

import requests
import time
from datetime import datetime, timezone, timedelta

# Public AppView — no auth required
BLUESKY_API     = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
BLUESKY_TIMEOUT = 8


# ════════════════════════════════════════════════════════════════
# ACCOUNT DIRECTORY (per-country relevance via 'targets')
# ════════════════════════════════════════════════════════════════
# Format: (handle, weight, targets[], description)
#
# handle:  Bluesky handle WITHOUT the @ prefix
# weight:  1.2 = head of state / direct gov statement
#          1.1 = minister / senior official / MFA
#          1.0 = institutional / military command / IO body
#          0.9 = journalism / monitoring / analytical
# targets: list of Africa backend country keys this account is
#          relevant to. Use ['*'] for all-Africa scope.
# ════════════════════════════════════════════════════════════════
BLUESKY_ACCOUNTS_AFRICA = [
    # ── International organizations (relevant across multiple) ──
    ('africacdc.bsky.social',          1.0, ['*'],
        'Africa CDC (if native) — continental public health authority'),
    ('icg.bsky.social',                0.9, ['*'],
        'International Crisis Group (if native) — Africa coverage'),
    ('reliefweb.bsky.social',          0.9, ['*'],
        'ReliefWeb (if native) — UN OCHA aggregation'),

    # ── US government — govmirrors fallbacks ──
    ('state-department.bsky.social',   1.0, ['*'],
        'US State Department (official) — Africa Bureau statements'),
    ('statedept.govmirrors.com',       0.9, ['*'],
        'StateDept (X mirror) — redundant fallback'),
    ('potus.govmirrors.com',           1.0, ['drc', 'uganda', 'sudan',
                                              'nigeria', 'south_africa'],
        'POTUS (X mirror) — Africa-relevant exec statements'),
    ('realdonaldtrump.govmirrors.com', 1.2, ['drc', 'uganda', 'sudan',
                                              'nigeria', 'south_africa'],
        'Trump (X mirror) — Africa-relevant statements'),
    ('secrubio.govmirrors.com',        1.1, ['*'],
        'SecState Rubio (X mirror) — Africa Bureau policy'),

    # ── Sudan-specific (active war, watchdog coverage) ──
    ('sudantribune.bsky.social',       0.9, ['sudan', 'south_sudan'],
        'Sudan Tribune (if native) — Sudan + South Sudan coverage'),

    # ── DRC + Ebola response ──
    ('whoafrica.bsky.social',          1.0, ['drc', 'uganda', 'rwanda',
                                              'south_sudan', 'kenya', 'tanzania'],
        'WHO Africa (if native) — Ebola response'),
    ('msf.bsky.social',                0.9, ['drc', 'sudan', 'south_sudan',
                                              'somalia', 'nigeria'],
        'Médecins Sans Frontières / Doctors Without Borders (if native)'),

    # ── AFRICOM / DoD ──
    ('africom.bsky.social',            1.0, ['*'],
        'US AFRICOM (if native) — military posture statements'),
    ('deptofdefense.govmirrors.com',   1.0, ['somalia', 'nigeria',
                                              'mali', 'niger'],
        'DoD (X mirror) — counter-terror operations Africa'),

    # ── Mediator countries / regional ──
    ('eu-mission.bsky.social',         0.9, ['sudan', 'drc', 'mali',
                                              'niger', 'south_africa'],
        'EU Africa mission (if native)'),
    ('nato.bsky.social',               0.9, ['sahel', 'mali', 'niger'],
        'NATO (if native) — Sahel adjacent posture'),

    # ── Sahel / Wagner watch ──
    ('wartranslated.bsky.social',      0.9, ['mali', 'niger', 'burkina_faso',
                                              'sudan'],
        'War Translated — Russian-language primary source translation'),
]


# ════════════════════════════════════════════════════════════════
# FETCH SINGLE ACCOUNT
# ════════════════════════════════════════════════════════════════

def fetch_bluesky_account(handle, weight=1.0, limit=20, timeout=BLUESKY_TIMEOUT):
    """
    Fetch recent posts from a single Bluesky account.

    Returns list of article dicts. Logs visibility on:
      - 404 (dead handle)
      - 429 (rate limit)
      - non-200 (other HTTP failure)
      - empty feeds (200 OK but no posts) — for diagnostic visibility
    """
    headers = {
        'User-Agent': 'AsifahAnalytics/1.0 (+https://asifahanalytics.com)',
        'Accept':     'application/json',
    }
    params = {'actor': handle, 'limit': limit}

    try:
        resp = requests.get(BLUESKY_API, headers=headers, params=params, timeout=timeout)

        if resp.status_code == 404:
            print(f'[Bluesky Africa] @{handle}: handle not found (404)')
            return []
        if resp.status_code == 429:
            print(f'[Bluesky Africa] @{handle}: rate-limited (429)')
            return []
        if resp.status_code != 200:
            print(f'[Bluesky Africa] @{handle}: HTTP {resp.status_code}')
            return []

        data = resp.json()
        feed = data.get('feed', [])
        articles = []

        for item in feed:
            post = item.get('post', {})
            record = post.get('record', {})
            author = post.get('author', {})

            text = record.get('text', '') or ''
            if not text.strip():
                continue

            pub = record.get('createdAt') or post.get('indexedAt') or ''
            post_uri = post.get('uri', '')
            rkey = post_uri.rsplit('/', 1)[-1] if post_uri else ''
            url = (f'https://bsky.app/profile/{handle}/post/{rkey}'
                   if rkey else f'https://bsky.app/profile/{handle}')

            articles.append({
                'title':            text[:200],
                'description':      text[:400],
                'url':              url,
                'publishedAt':      pub,
                'published':        pub,
                'source':           f'Bluesky @{handle}',
                'content':          text[:500],
                'language':         'en',
                'source_type':      'bluesky',
                '_bluesky_weight':  weight,
                '_bluesky_author':  author.get('displayName', handle),
            })

        if articles:
            print(f'[Bluesky Africa] @{handle}: {len(articles)} posts')
        else:
            # Always log even on empty — diagnostic visibility (matches v1.2
            # Europe Bluesky improvement so we can spot dead handles fast).
            print(f'[Bluesky Africa] @{handle}: 0 posts (200 OK, empty feed)')
        return articles

    except requests.exceptions.Timeout:
        print(f'[Bluesky Africa] @{handle}: timeout after {timeout}s')
        return []
    except Exception as e:
        print(f'[Bluesky Africa] @{handle}: {str(e)[:80]}')
        return []


# ════════════════════════════════════════════════════════════════
# PER-TARGET AGGREGATOR
# ════════════════════════════════════════════════════════════════

def fetch_bluesky_for_target(target, days=7, max_posts_per_account=20):
    """
    Fetch Bluesky posts relevant to a specific Africa target.

    Filters by:
      - target key ('*' or target in account's targets list)
      - recency (post must be within last `days` days)
      - deduplication by URL

    Returns list of article dicts.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen_urls = set()
    accounts_queried = 0
    posts_filtered_by_recency = 0
    posts_filtered_by_dedup   = 0
    posts_returned_raw        = 0

    for handle, weight, targets, _desc in BLUESKY_ACCOUNTS_AFRICA:
        if '*' not in targets and target not in targets:
            continue

        accounts_queried += 1
        posts = fetch_bluesky_account(handle, weight=weight, limit=max_posts_per_account)
        posts_returned_raw += len(posts)

        for p in posts:
            if p['url'] in seen_urls:
                posts_filtered_by_dedup += 1
                continue
            try:
                pub_str = (p.get('publishedAt') or '').replace('Z', '+00:00')
                pub = datetime.fromisoformat(pub_str)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    posts_filtered_by_recency += 1
                    continue
            except Exception:
                pass    # keep post if date parse fails (better than losing signal)

            seen_urls.add(p['url'])
            all_posts.append(p)

        time.sleep(0.2)  # politeness

    print(
        f'[Bluesky Africa] {target}: {len(all_posts)} posts kept '
        f'(raw={posts_returned_raw}, '
        f'cut_recency={posts_filtered_by_recency}, '
        f'cut_dedup={posts_filtered_by_dedup}) '
        f'from {accounts_queried} accounts queried'
    )
    return all_posts


# ════════════════════════════════════════════════════════════════
# PER-COUNTRY WRAPPERS
# ════════════════════════════════════════════════════════════════

def fetch_sudan_bluesky_signals(days=7, max_posts_per_account=20):
    return fetch_bluesky_for_target('sudan', days=days,
                                     max_posts_per_account=max_posts_per_account)


def fetch_drc_bluesky_signals(days=7, max_posts_per_account=20):
    return fetch_bluesky_for_target('drc', days=days,
                                     max_posts_per_account=max_posts_per_account)


def fetch_uganda_bluesky_signals(days=7, max_posts_per_account=20):
    return fetch_bluesky_for_target('uganda', days=days,
                                     max_posts_per_account=max_posts_per_account)


def fetch_ethiopia_bluesky_signals(days=7, max_posts_per_account=20):
    return fetch_bluesky_for_target('ethiopia', days=days,
                                     max_posts_per_account=max_posts_per_account)


def fetch_nigeria_bluesky_signals(days=7, max_posts_per_account=20):
    return fetch_bluesky_for_target('nigeria', days=days,
                                     max_posts_per_account=max_posts_per_account)


def fetch_southafrica_bluesky_signals(days=7, max_posts_per_account=20):
    return fetch_bluesky_for_target('south_africa', days=days,
                                     max_posts_per_account=max_posts_per_account)
