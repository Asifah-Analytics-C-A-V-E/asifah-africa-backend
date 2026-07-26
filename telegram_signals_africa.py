"""
========================================
TELEGRAM — Africa OSINT Channel Monitor (v2.0.0)
========================================
Mirrors telegram_signals_europe.py + telegram_signals_me.py pattern.

v2.0.0 ARCHITECTURE CHANGE (July 2026):
  The v1 design listed the same shared OSINT channels (OSINTdefender,
  ClashReport, AfricaIntelligence...) under every country, which meant:
    (a) a full scan cycle fetched the SAME channel once per country
        (8+ redundant Telethon fetches -> flood-wait exposure), and
    (b) every country's article pool received ALL posts from shared
        channels regardless of relevance -- a Darfur atrocity post
        could add pressure-bonus points to Kenya's score (signal bleed
        = manufactured convergence, doctrine violation).

  v2 fixes both:
    1. SHARED_CHANNELS are fetched ONCE per cycle and cached in-process
       (30 min TTL). Every country call reads the cache.
    2. Shared-channel posts pass a per-country RELEVANCE GATE (the post
       text must contain at least one country-specific term) before
       entering that country's pool.
    3. COUNTRY_CHANNELS (country-dedicated channels like DabangaSudan)
       are fetched per-country and skip the gate.
    4. Generic dispatch: app.py calls fetch_telegram_for_target(key).
       No per-country wrapper imports needed. (Thin wrappers kept below
       for backward compatibility.)

NOTE: African Telegram OSINT is THIN compared to Middle East / Europe.
Many channels we'd want (state media, militia formal channels) are
Arabic-only or run on Facebook/WhatsApp instead. If a channel goes
dark we graceful-degrade via the canonical try/except pattern.

v1.0.0 — May 24 2026 — initial Africa backend launch (14 countries).
v2.0.0 — Jul 18 2026 — shared-channel cache + relevance gate + generic
                        dispatch; relevance terms for 20 countries
                        (14 launch + CAR, Chad, Eq. Guinea, Mozambique,
                        Madagascar, Guinea).
v2.2.0 — Jul 26 2026 — Mali relevance gate widened (FLA/Africa Corps/
                        blockade vocabulary); Mali channel candidates noted
                        pending verification.
v2.1.0 — Jul 19 2026 — gate WIDENED (demonyms + spelling variants: the
                        first production cycle kept 1 of 134 shared msgs;
                        demonym matching is how OSINT channels actually
                        write). Dead Sudan handles pruned (UsernameInvalid
                        in prod logs). ' malian' keeps its leading space:
                        'somalian' contains 'malian'.
"""

import os
import base64
import asyncio
import time
from datetime import datetime, timezone, timedelta

# ── Telethon soft-dependency ──────────────────────────────────
try:
    from telethon import TelegramClient
    from telethon.errors import (
        FloodWaitError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
    )
    from telethon.tl.functions.messages import GetHistoryRequest
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    print("[Telegram Africa] ⚠️ Telethon not installed")

TELEGRAM_API_ID         = os.environ.get('TELEGRAM_API_ID')
TELEGRAM_API_HASH       = os.environ.get('TELEGRAM_API_HASH')
TELEGRAM_PHONE          = os.environ.get('TELEGRAM_PHONE')
SESSION_NAME            = 'asifah_africa_telegram'
TELEGRAM_SESSION_BASE64 = os.environ.get('TELEGRAM_SESSION_BASE64')


# ============================================================
# CHANNEL DIRECTORIES
# ============================================================

# ── SHARED channels: broad OSINT coverage spanning many African
#    theaters. Fetched ONCE per cycle, cached, then gated per
#    country by COUNTRY_RELEVANCE_TERMS below. ──
SHARED_CHANNELS = [
    'AfricaIntelligence',   # Africa-wide OSINT (English)
    'OSINTdefender',        # General OSINT, frequent Africa coverage
    'ClashReport',          # Conflict OSINT (Sudan/Darfur/Sahel)
    'wartranslated',        # Russian-language primary source translation
    'MiddleEastSpectator',  # Wagner / Russia / IS-affiliate coverage
]

# ── COUNTRY-DEDICATED channels: fetched per-country, NO relevance
#    gate (the channel itself is the relevance filter). ──
COUNTRY_CHANNELS = {
    'sudan': [
        # sudaneseTribune + DabangaSudan pruned Jul 19 2026 -- production
        # logs show UsernameInvalid (dead/renamed). Verify replacements at
        # t.me/s/<handle> before adding.
        'sudanwatch',        # Sudan watch (English) -- resolves, low volume
    ],
    # Other countries fall through to shared channels only.
    #
    # ── MALI: candidate handles, UNVERIFIED (Jul 26 2026) ──────────────
    # Mali's first production scan logged `dedicated=0 channels`. The
    # candidates below are NOT enabled because they have not been checked,
    # and this module's own history is the reason: 'sudaneseTribune' and
    # 'DabangaSudan' were added unverified and pruned after UsernameInvalid
    # appeared in production logs. A dead handle is worse than none -- it
    # burns a fetch slot and logs noise every cycle.
    #
    # Verify each at t.me/s/<handle> (must load a PUBLIC preview), then move
    # the line up into a 'mali': [...] entry:
    #
    #   'Sahel_Intelligence'   # Sahel-wide OSINT, FR/EN
    #   'malijet'              # Malijet, national outlet
    #   'studiotamani'         # Studio Tamani (Fondation Hirondelle)
    #   'MENASTREAM'           # Sahel/Maghreb conflict specialist
    #
    # Note also that the same scan logged `shared gate kept 0, dropped 0` --
    # zero shared messages were FETCHED at all that cycle, which is a
    # different problem from the gate being too narrow. Worth checking the
    # five SHARED_CHANNELS still resolve before assuming Mali needs its own.
    #
    # Add dedicated handles here as they are verified
    # (check t.me/s/<handle> loads a public preview first).
}

# ── RELEVANCE GATE terms (lowercase substrings).
#    A shared-channel post enters a country's pool only if its
#    title+description contains at least one of these terms.
#    Substring gotchas handled deliberately:
#      - ' mali' (leading space) so 'somalia' does not match Mali
#      - Guinea uses ONLY distinctive terms (never bare 'guinea',
#        which matches Equatorial Guinea / Guinea-Bissau / PNG)
#      - Niger uses 'niamey'/'nigerien' etc. (bare 'niger' matches
#        'nigeria')
COUNTRY_RELEVANCE_TERMS = {
    # ── launch 14 ──
    'sudan':        ['sudan', 'sudanese', 'rsf', 'darfur', 'el fasher',
                     'el-fasher', 'al-fashir', 'kordofan', 'khartoum',
                     'hemedti', 'burhan', 'port sudan'],
    'south_sudan':  ['south sudan', 'south sudanese', 'juba', 'kiir', 'machar'],
    'drc':          ['congo', 'congolese', 'drc', 'm23', 'goma', 'kivu',
                     'ituri', 'kinshasa'],
    'uganda':       ['uganda', 'ugandan', 'kampala', 'museveni'],
    'rwanda':       ['rwanda', 'rwandan', 'kigali', 'kagame'],
    'kenya':        ['kenya', 'kenyan', 'nairobi'],
    'tanzania':     ['tanzania', 'tanzanian', 'dar es salaam', 'dodoma'],
    'ethiopia':     ['ethiopia', 'ethiopian', 'tigray', 'amhara',
                     'addis ababa', 'abiy', 'gerd'],
    'somalia':      ['somalia', 'somali ', 'shabaab', 'al-shabaab',
                     'shabab', 'mogadishu', 'aussom', 'puntland'],
    'nigeria':      ['nigeria', 'nigerian', 'boko haram', 'iswap',
                     'abuja', 'niger delta'],
    'mali':         [' mali', ' malian', 'bamako', 'jnim', 'azawad',
                     'kidal', 'goita', 'wagner mali',
                     # Widened Jul 26 2026 -- the terms above predate the FLA
                     # rebrand, the Africa Corps transition and the Bamako
                     # blockade, so the gate was matching on vocabulary the
                     # channels have largely stopped using.
                     'fla ', 'africa corps mali', 'gao ', 'mopti', 'anefis',
                     'aguelhok', 'tinzaouaten', 'timbuktu', 'tombouctou',
                     'sévaré', 'sevare', 'fama ', 'macina',
                     'iyad ag ghaly', 'kouffa', 'malienne', 'maliens'],
    'niger':        ['niamey', 'tchiani', 'agadez', 'nigerien'],
    'burkina_faso': ['burkina', 'burkinabe', 'ouagadougou', 'traore'],
    'south_africa': ['south africa', 'south african', 'johannesburg',
                     'pretoria', 'eskom', 'ramaphosa'],
    # ── July 2026 additions ──
    'car':               ['central african', 'centrafrique', 'bangui',
                          'touadera'],
    'chad':              ['chad', 'chadian', 'tchad', "n'djamena",
                          'ndjamena', 'deby'],
    'equatorial_guinea': ['equatorial guinea', 'malabo', 'obiang',
                          'bioko'],
    'mozambique':        ['mozambique', 'mozambican', 'cabo delgado',
                          'maputo'],
    'madagascar':        ['madagascar', 'malagasy', 'antananarivo'],
    'guinea':            ['conakry', 'doumbouya', 'simandou'],
}


# ============================================================
# INFRASTRUCTURE HELPERS
# ============================================================

def _telegram_available():
    """Check if Telegram integration is fully configured.

    Diagnostic added Jul 26 2026. The TELETHON_AVAILABLE branch returned False
    with NO log line, so a production cycle that fetched nothing looked
    identical to a cycle where the channels genuinely had no Africa content.
    Mali and Somalia both logged `shared gate kept 0, dropped 0` and there was
    no way to tell which failure it was. Now it says.
    """
    if not TELETHON_AVAILABLE:
        print("[Telegram Africa] ❌ Telethon NOT INSTALLED -- the entire "
              "Telegram lane is dark. This is a dependency problem, not a "
              "content problem: no channel roster will help until it is fixed.")
        return False
    missing = [n for n, v in (('TELEGRAM_API_ID', TELEGRAM_API_ID),
                              ('TELEGRAM_API_HASH', TELEGRAM_API_HASH),
                              ('TELEGRAM_PHONE', TELEGRAM_PHONE)) if not v]
    if missing:
        print(f"[Telegram Africa] ⚠️ Missing env vars: {', '.join(missing)} "
              f"-- lane is dark until set on this backend.")
        return False
    return True


def _ensure_session_file():
    """Decode session file from base64 env var if needed."""
    session_path = f'{SESSION_NAME}.session'
    if os.path.exists(session_path):
        return True

    if TELEGRAM_SESSION_BASE64:
        try:
            session_data = base64.b64decode(TELEGRAM_SESSION_BASE64)
            with open(session_path, 'wb') as f:
                f.write(session_data)
            print(f"[Telegram Africa] ✅ Session file decoded ({len(session_data)} bytes)")
            return True
        except Exception as e:
            print(f"[Telegram Africa] ❌ Session decode error: {str(e)[:100]}")
            return False

    print("[Telegram Africa] ⚠️ No session file and no TELEGRAM_SESSION_BASE64 env var")
    return False


# ============================================================
# ASYNC FETCHER (canonical pattern)
# ============================================================

async def _async_fetch_messages(channels, hours_back=72):
    """
    Async function to fetch messages from a list of Telegram channels.
    Returns list of message dicts compatible with the Africa backend
    article schema.
    """
    if not _ensure_session_file():
        return []

    messages = []
    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    try:
        client = TelegramClient(SESSION_NAME, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            print("[Telegram Africa] ❌ Session not authorized")
            await client.disconnect()
            return []

        print(f"[Telegram Africa] ✅ Connected, fetching from {len(channels)} channels...")

        for channel in channels:
            try:
                entity = await client.get_entity(channel)
                history = await client(GetHistoryRequest(
                    peer=entity,
                    limit=50,
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0,
                ))

                channel_count = 0
                for msg in history.messages:
                    if msg.date and msg.date.replace(tzinfo=timezone.utc) > since and msg.message:
                        messages.append({
                            'title':       msg.message[:200],
                            'description': msg.message[:500],
                            'url':         f'https://t.me/{channel}/{msg.id}',
                            'published':   msg.date.replace(tzinfo=timezone.utc).isoformat(),
                            'query':       f'telegram_{channel}',
                            'source':      f'Telegram @{channel}',
                            'views':       getattr(msg, 'views', 0) or 0,
                            'forwards':    getattr(msg, 'forwards', 0) or 0,
                            'source_type': 'telegram',
                        })
                        channel_count += 1

                print(f"[Telegram Africa] @{channel}: {channel_count} messages "
                      f"(last {hours_back}h)")

            except FloodWaitError as e:
                wait = e.seconds
                print(f"[Telegram Africa] @{channel} flood wait {wait}s -- skipping channel")
                if wait > 300:
                    print(f"[Telegram Africa] ⚠️ Flood wait > 5min -- stopping fetch early")
                    break
                await asyncio.sleep(min(wait, 30))
                continue
            except (UsernameInvalidError, UsernameNotOccupiedError):
                print(f"[Telegram Africa] @{channel} -- invalid/dead username, skipping")
                continue
            except Exception as e:
                print(f"[Telegram Africa] @{channel} error: {str(e)[:100]}")
                continue

        await client.disconnect()
        print(f"[Telegram Africa] ✅ Total: {len(messages)} messages from {len(channels)} channels")

    except Exception as e:
        print(f"[Telegram Africa] ❌ Connection error: {str(e)[:200]}")
        try:
            await client.disconnect()
        except Exception:
            pass

    return messages


def _run_async_fetch(channels, hours_back):
    """Run the async fetcher from sync code, handling event-loop edge cases."""
    if not _telegram_available():
        print("[Telegram Africa] Signals unavailable -- skipping")
        return []
    try:
        try:
            asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _async_fetch_messages(channels, hours_back))
                return future.result(timeout=120)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_async_fetch_messages(channels, hours_back))
            finally:
                loop.close()
    except Exception as e:
        print(f"[Telegram Africa] ❌ fetch error: {str(e)[:200]}")
        return []


# ============================================================
# SHARED-CHANNEL CACHE (fetched once per cycle, 30 min TTL)
# ============================================================

_SHARED_CACHE = {
    'messages':   [],
    'fetched_at': 0.0,      # time.time() epoch seconds
    'ttl':        1800,     # 30 minutes -- one full 14+ country
                            # scan cycle reuses a single fetch
    'window_h':   120,      # shared fetch always pulls the widest
                            # window; callers re-filter to their own
}


def _get_shared_messages():
    """
    Return shared-channel messages, fetching at most once per TTL.
    Absence-honest: on fetch failure the cache is NOT poisoned with
    an empty 'fresh' result -- a stale cache (if any) is preferred
    over pretending the feeds are quiet.
    """
    now = time.time()
    age = now - _SHARED_CACHE['fetched_at']
    if _SHARED_CACHE['fetched_at'] and age < _SHARED_CACHE['ttl']:
        print(f"[Telegram Africa] shared cache hit "
              f"({len(_SHARED_CACHE['messages'])} msgs, age {int(age)}s)")
        return _SHARED_CACHE['messages']

    fetched = _run_async_fetch(SHARED_CHANNELS, _SHARED_CACHE['window_h'])
    if fetched:
        _SHARED_CACHE['messages'] = fetched
        _SHARED_CACHE['fetched_at'] = now
    else:
        print(f"[Telegram Africa] ⚠️ shared fetch returned 0 messages from "
              f"{len(SHARED_CHANNELS)} channels ({', '.join(SHARED_CHANNELS)}) -- "
              f"keeping previous cache (absence-honest). If this repeats, the "
              f"problem is the FETCH, not the country roster: ClashReport, "
              f"wartranslated and MiddleEastSpectator all cover Sahel/Wagner "
              f"material and should be producing Mali hits.")
    return _SHARED_CACHE['messages']


def _within_window(msg, hours_back):
    """True if the message timestamp is inside the caller's window."""
    try:
        pub = datetime.fromisoformat(msg.get('published', ''))
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return pub > datetime.now(timezone.utc) - timedelta(hours=hours_back)
    except Exception:
        return True   # keep on parse failure (better than losing signal)


# ============================================================
# GENERIC DISPATCH (what app.py calls)
# ============================================================

def fetch_telegram_for_target(target, hours_back=96):
    """
    Return Telegram articles relevant to one Africa country key.

      1. Country-dedicated channels (COUNTRY_CHANNELS) -> fetched
         directly, no gate.
      2. Shared channels -> read from the cycle cache, then pass
         the per-country relevance gate (COUNTRY_RELEVANCE_TERMS).
      3. Dedup by URL, window-filter to hours_back.

    Unknown target keys return shared-gated results only if terms
    exist; otherwise empty list (absence-honest, logged).
    """
    if not _telegram_available():
        print(f"[Telegram Africa] {target}: unavailable -- skipping")
        return []

    results = []
    seen_urls = set()

    # ── 1. dedicated channels (ungated) ──
    dedicated = COUNTRY_CHANNELS.get(target, [])
    if dedicated:
        for msg in _run_async_fetch(dedicated, hours_back):
            if msg['url'] not in seen_urls:
                seen_urls.add(msg['url'])
                results.append(msg)

    # ── 2. shared channels (gated) ──
    terms = COUNTRY_RELEVANCE_TERMS.get(target)
    if terms is None:
        print(f"[Telegram Africa] {target}: no relevance terms defined -- "
              f"shared channels skipped (add to COUNTRY_RELEVANCE_TERMS)")
    else:
        gated_in = 0
        gated_out = 0
        for msg in _get_shared_messages():
            if msg['url'] in seen_urls:
                continue
            if not _within_window(msg, hours_back):
                continue
            text = ((msg.get('title') or '') + ' '
                    + (msg.get('description') or '')).lower()
            if any(t in text for t in terms):
                seen_urls.add(msg['url'])
                results.append(msg)
                gated_in += 1
            else:
                gated_out += 1
        print(f"[Telegram Africa] {target}: shared gate kept {gated_in}, "
              f"dropped {gated_out}")

    print(f"[Telegram Africa] {target}: {len(results)} total "
          f"(dedicated={len(dedicated)} channels, window={hours_back}h)")
    return results


# ============================================================
# PER-COUNTRY WRAPPERS (backward compatibility -- thin aliases)
# ============================================================

def fetch_sudan_telegram_signals(hours_back=72):
    return fetch_telegram_for_target('sudan', hours_back)


def fetch_drc_telegram_signals(hours_back=72):
    return fetch_telegram_for_target('drc', hours_back)


def fetch_uganda_telegram_signals(hours_back=120):
    return fetch_telegram_for_target('uganda', hours_back)


def fetch_ethiopia_telegram_signals(hours_back=120):
    return fetch_telegram_for_target('ethiopia', hours_back)


def fetch_nigeria_telegram_signals(hours_back=120):
    return fetch_telegram_for_target('nigeria', hours_back)


def fetch_mali_telegram_signals(hours_back=72):
    return fetch_telegram_for_target('mali', hours_back)


def fetch_kenya_telegram_signals(hours_back=120):
    return fetch_telegram_for_target('kenya', hours_back)


def fetch_southafrica_telegram_signals(hours_back=120):
    return fetch_telegram_for_target('south_africa', hours_back)
