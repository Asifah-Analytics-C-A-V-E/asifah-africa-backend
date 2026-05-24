"""
========================================
TELEGRAM — Africa OSINT Channel Monitor (v1.0.0)
========================================
Mirrors telegram_signals_europe.py + telegram_signals_me.py pattern.

Per-country wrapper functions (fetch_<country>_telegram_signals) for the
8 Tier-1 African countries with verified or known-active Telegram OSINT
channels. Countries without strong Telegram coverage (Tanzania, Rwanda,
Niger, Burkina Faso, South Africa, South Sudan) fall through to GDELT/
NewsAPI/RSS via the canonical scan pipeline.

NOTE: African Telegram OSINT is THIN compared to Middle East / Europe.
Many channels we'd want (state media, militia formal channels) are
Arabic-only or run on Facebook/WhatsApp instead. The handles below
were verified active as of May 24 2026; if a channel goes dark we
graceful-degrade via the canonical try/except pattern.

v1.0.0 — May 24 2026 — initial Africa backend launch (14 countries).
"""

import os
import base64
import asyncio
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
# CHANNEL DIRECTORIES (per country)
# ============================================================

# ── SUDAN ──
# Active war: RSF + SAF + UAE + Egypt + Sudanese diaspora media.
# Mostly Arabic; some English. RSF and SAF both run official channels
# of varying reliability.
SUDAN_CHANNELS = [
    'sudaneseTribune',     # Sudan Tribune (English)
    'DabangaSudan',        # Radio Dabanga (English + Arabic)
    'AfricaIntelligence',  # Africa-wide OSINT (English)
    'OSINTdefender',       # General OSINT, often covers Sudan
    'wartranslated',       # Translations of primary sources
    'ClashReport',         # Conflict OSINT (often covers Sudan/Darfur)
    'sudanwatch',          # Sudan watch (English)
]

# ── DRC ──
# Ebola PHEIC + M23 active. French + English. Limited Telegram presence;
# most local coverage on Twitter/X.
DRC_CHANNELS = [
    'AfricaIntelligence',
    'OSINTdefender',
    'wartranslated',
    'ClashReport',
    'MiddleEastSpectator',  # Wagner/Russia coverage spills into DRC
]

# ── UGANDA ──
UGANDA_CHANNELS = [
    'AfricaIntelligence',
    'OSINTdefender',
    'ClashReport',
]

# ── ETHIOPIA ──
ETHIOPIA_CHANNELS = [
    'AfricaIntelligence',
    'OSINTdefender',
    'ClashReport',
    'wartranslated',
]

# ── NIGERIA ──
# Boko Haram + ISWAP coverage; Nigerian government less Telegram-active.
NIGERIA_CHANNELS = [
    'AfricaIntelligence',
    'OSINTdefender',
    'ClashReport',
    'MiddleEastSpectator',  # ISWAP/IS coverage
]

# ── MALI ──
# Wagner / Africa Corps heavily-covered on Russia-aligned Telegram.
# French + Russian + English.
MALI_CHANNELS = [
    'AfricaIntelligence',
    'OSINTdefender',
    'ClashReport',
    'wartranslated',
    'MiddleEastSpectator',  # Wagner / Russia coverage
]

# ── KENYA ──
KENYA_CHANNELS = [
    'AfricaIntelligence',
    'OSINTdefender',
    'ClashReport',
]

# ── SOUTH AFRICA ──
SOUTHAFRICA_CHANNELS = [
    'AfricaIntelligence',
    'OSINTdefender',
    'ClashReport',
]


# ============================================================
# INFRASTRUCTURE HELPERS
# ============================================================

def _telegram_available():
    """Check if Telegram integration is fully configured."""
    if not TELETHON_AVAILABLE:
        return False
    if not all([TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE]):
        print("[Telegram Africa] ⚠️ Missing environment variables")
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
# PER-COUNTRY WRAPPERS
# ============================================================

def fetch_sudan_telegram_signals(hours_back=72):
    """Telegram signals for Sudan rhetoric tracker. 72h window — active war."""
    return _run_async_fetch(SUDAN_CHANNELS, hours_back)


def fetch_drc_telegram_signals(hours_back=72):
    """Telegram signals for DRC tracker. 72h window — Ebola + M23 fast moving."""
    return _run_async_fetch(DRC_CHANNELS, hours_back)


def fetch_uganda_telegram_signals(hours_back=120):
    """Telegram signals for Uganda. 120h (5 day) — slower tempo."""
    return _run_async_fetch(UGANDA_CHANNELS, hours_back)


def fetch_ethiopia_telegram_signals(hours_back=120):
    return _run_async_fetch(ETHIOPIA_CHANNELS, hours_back)


def fetch_nigeria_telegram_signals(hours_back=120):
    return _run_async_fetch(NIGERIA_CHANNELS, hours_back)


def fetch_mali_telegram_signals(hours_back=72):
    """Mali tracker — 72h. Wagner / JNIM activity fast-moving."""
    return _run_async_fetch(MALI_CHANNELS, hours_back)


def fetch_kenya_telegram_signals(hours_back=120):
    return _run_async_fetch(KENYA_CHANNELS, hours_back)


def fetch_southafrica_telegram_signals(hours_back=120):
    return _run_async_fetch(SOUTHAFRICA_CHANNELS, hours_back)
