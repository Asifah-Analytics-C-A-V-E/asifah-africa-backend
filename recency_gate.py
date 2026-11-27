"""
recency_gate.py -- Asifah Analytics, Africa backend
v1.0.0  (Nov 27 2026)

WHY THIS EXISTS
---------------
The Niger, Burkina Faso and CAR trackers ask GDELT and NewsAPI for "the last
7 days" -- but Google News RSS search and Brave do NOT honour that window.
Google News sorts a search by relevance, so a quiet country's feed fills up
with stories from weeks or months ago. Before this gate, a July attack on
peacekeepers or an August mine collapse could fire a CAR red line in late
November as if it had happened this week, and a two-year-old think-tank brief
could push the Russia actor to SURGE.

Mali, Somalia and Sudan already filter by date at fetch time; this module
gives the newer trackers the same discipline in one place.

THE RULE
--------
- Dated and inside the window (plus one day of grace for time zones) -> kept.
- Dated and older -> dropped, and COUNTED (the debug view shows how many).
- Undated -> kept, and counted as 'undated'. Dropping undated items would
  silently blind the scan to feeds that omit dates; counting them keeps the
  gap visible instead.

No network calls, no Redis, no cost.
"""

import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

__version__ = '1.0.0'

_REL = re.compile(r'(\d+)\s*(minute|min|hour|hr|day|week|month|year)s?\s+ago', re.I)
_REL_UNITS = {'minute': 1 / 1440, 'min': 1 / 1440, 'hour': 1 / 24, 'hr': 1 / 24,
              'day': 1, 'week': 7, 'month': 30, 'year': 365}


def parse_published(value, now=None):
    """Best-effort parse of the date formats our feeds emit. None if unknown.

    Handles RFC 822 (RSS pubDate), ISO 8601 (NewsAPI, Brave page_age),
    GDELT seendate (20261127T061500Z), Brave relative ages ("3 days ago")
    and long dates ("November 20, 2025").
    """
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    now = now or datetime.now(timezone.utc)
    # GDELT: 20261127T061500Z
    if re.fullmatch(r'\d{8}T\d{6}Z', s):
        try:
            return datetime.strptime(s, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    # Relative: "3 days ago"
    m = _REL.search(s)
    if m:
        return now - timedelta(days=int(m.group(1)) * _REL_UNITS[m.group(2).lower()])
    # ISO 8601
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # RFC 822
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    # "November 20, 2025" / "20 November 2025"
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %b %Y'):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def filter_recent(articles, days, grace_days=1, now=None):
    """Return (kept_articles, stats). See the module docstring for the rule."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days + grace_days)
    kept, stale, undated = [], 0, 0
    oldest_dropped = None
    for a in articles:
        dt = parse_published(a.get('published', ''), now=now)
        if dt is None:
            undated += 1
            kept.append(a)
            continue
        if dt < cutoff:
            stale += 1
            if oldest_dropped is None or dt < oldest_dropped:
                oldest_dropped = dt
            continue
        kept.append(a)
    stats = {
        'window_days': days, 'kept': len(kept), 'dropped_stale': stale, 'undated_kept': undated,
        'oldest_dropped': oldest_dropped.date().isoformat() if oldest_dropped else None,
        'note': ('Stories older than the scan window are dropped before scoring, so old news '
                 'cannot set a level or fire a red line. Undated items are kept and counted.'),
    }
    return kept, stats
