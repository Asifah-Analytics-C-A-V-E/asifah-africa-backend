"""
Asifah Analytics -- Africa Regional BLUF Engine
v1.0.0 -- July 23 2026  |  Africa backend

Layer 3 in the platform stack: sensors (country trackers) -> analyst (this) ->
global (GPI). Reads every Africa country tracker cache, rolls them into a single
regional posture, and emits the top_signals pool the Global Pressure Index
consumes.

Cloned from europe_regional_bluf.py v3.4.0 so the OUTPUT SCHEMA is identical --
GPI activation is a one-line uncomment in REGIONAL_BLUF_ENDPOINTS, no GPI code
change required.

═══════════════════════════════════════════════════════════════════════
WHAT MAKES AFRICA DIFFERENT (three deliberate divergences from Europe)
═══════════════════════════════════════════════════════════════════════

1. COVERAGE HONESTY (the big one). Europe rolls up twelve trackers. Africa
   today has ONE (Somalia). A regional BLUF built on a single country is NOT a
   regional synthesis, and this module refuses to pretend otherwise. In
   single-tracker mode the prose says so plainly and the payload carries
   `single_tracker_mode: True` + a `coverage_note`. The moment a second tracker
   lands the prose switches to genuine multi-country synthesis. Absence-honest
   is doctrine: never invent a regional picture from one data point.

2. JUNCTION-AWARE. Somalia is a junction tracker -- it reads four external
   wheels (Turkey / Russia / Bab-el-Mandeb / Israel-Somaliland) and fires a
   `wheel_convergence` block when >=2 light at once. That convergence is the
   marquee analytical read for the Horn, so it elevates regional posture and
   emits its own high-priority signal.

3. SILENCE-AWARE. Africa's insurgency trackers run claiming actors
   (mode='actor': al-Shabaab, ISIS-Somalia) where SILENCE IS THE SIGNAL. A
   claiming actor going quiet against its own baseline is surfaced as a signal
   class Europe has no equivalent for.

═══════════════════════════════════════════════════════════════════════
DOCTRINE
═══════════════════════════════════════════════════════════════════════
Convergence, not prediction. Country scores are rhetoric-signal composites
(weighted volume + severity of classified statements), not event counts and not
probabilities of action. Estimative language only. The reader completes the
inference.

REDIS:
  Reads:  rhetoric:{country}:latest  (+ :lastgood fallback, 7d ceiling)
  Writes: rhetoric:africa:regional_bluf  (14h TTL, 30min when picture incomplete)

ENDPOINTS:
  GET /api/rhetoric/africa/bluf            (cache-first)
  GET /api/rhetoric/africa/bluf?force=true (rebuild)
  GET /api/rhetoric/africa/bluf/debug      (cache inspection)

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import traceback
from datetime import datetime, timezone

import requests

# ── Shared spoke-and-wheel reader (v1.0.1, Jul 24 2026) ──────────────
# Byte-identical across ALL backends -- gdelt_gateway.py pattern. Reads the
# spoke/wheel keyspace straight from shared Redis; no cross-backend HTTP.
# Optional: absent file = no panel, BLUF still builds.
try:
    from spoke_wheel_reader import build_convergence_panel as _build_wheel_panel
    _WHEEL_READER = True
except ImportError:
    _WHEEL_READER = False
    print("[Africa BLUF] spoke_wheel_reader not available -- convergence panel disabled")


# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL   = (os.environ.get('UPSTASH_REDIS_URL')
                       or os.environ.get('UPSTASH_REDIS_REST_URL') or '')
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN') or '')

# Source caches (written by the respective country trackers).
# Country build queue (Rachel, Jul 2026): Somalia -> Sudan -> Mali ->
# Burkina Faso -> Niger -> CAR. Uncomment each as its tracker ships; the
# rollup, prose, and GPI feed pick it up with zero further wiring.
TRACKER_KEYS = {
    'somalia': 'rhetoric:somalia:latest',   # v1.0 Jul 21 2026 -- junction tracker (first Africa tracker)
    'sudan':   'rhetoric:sudan:latest',     # v1.0 Jul 24 2026 -- hub tracker (Russia/UAE/SAF-patron plugs)
    # 'mali':         'rhetoric:mali:latest',
    # 'burkina_faso': 'rhetoric:burkina_faso:latest',
    # 'niger':        'rhetoric:niger:latest',
    # 'car':          'rhetoric:car:latest',
    # 'drc':          'rhetoric:drc:latest',
    # 'ethiopia':     'rhetoric:ethiopia:latest',
    # 'nigeria':      'rhetoric:nigeria:latest',
}

THEATRE_FLAGS = {
    'somalia':      '\U0001F1F8\U0001F1F4',  # SO
    'sudan':        '\U0001F1F8\U0001F1E9',  # SD
    'mali':         '\U0001F1F2\U0001F1F1',  # ML
    'burkina_faso': '\U0001F1E7\U0001F1EB',  # BF
    'niger':        '\U0001F1F3\U0001F1EA',  # NE
    'car':          '\U0001F1E8\U0001F1EB',  # CF
    'drc':          '\U0001F1E8\U0001F1E9',  # CD
    'ethiopia':     '\U0001F1EA\U0001F1F9',  # ET
    'nigeria':      '\U0001F1F3\U0001F1EC',  # NG
}

THEATRE_DISPLAY = {
    'somalia':      'SOMALIA',
    'sudan':        'SUDAN',
    'mali':         'MALI',
    'burkina_faso': 'BURKINA FASO',
    'niger':        'NIGER',
    'car':          'CENTRAL AFRICAN REPUBLIC',
    'drc':          'DR CONGO',
    'ethiopia':     'ETHIOPIA',
    'nigeria':      'NIGERIA',
}

# ── SIGNAL POOL TUNING (v1.1.0 Jul 24 2026) ─────────────────────────────
# THE LENS PRINCIPLE: every layer DOWN gets a wider lens, every layer UP a
# narrower one. Country pages show everything their tracker emits (including
# L2 "watch" texture). This regional layer gates to L2+ and pools the best
# across Africa. The GPI narrows again above us.
TOP_SIGNALS_COUNT = 15   # was 12 -- headroom for the Sahel bundle + Libya-east.
                         # Deliberately leaves slots empty today: they exist so
                         # arriving trackers have somewhere to land, not to be filled.
MAX_PER_THEATRE   = 3    # No single country monopolises the regional read.
                         # 15 / 3 = five countries at full quota, with headroom.

MIN_LEVEL_TO_SURFACE = 2 # L0/L1 stays on the country page. A signal has to be
                         # at least "tension" to compete at regional altitude.

DIPLOMATIC_SURFACE_CAP = 3
# Mirrors the GPI's guard of the same name (Jun 14 2026). De-escalation MUST
# surface. Diplomatic signals are SCORE REDUCERS, so an escalation-weighted
# priority sort buries them structurally -- Sudan's mediation signal lands at
# priority 9 while its kinetic red lines sit at 12-13, so a straight top-3
# per-theatre cut drops the off-ramp entirely and the GPI never learns the
# mediation track exists. Up to this many diplomatic signals bypass
# MAX_PER_THEATRE and are never gate-kept out.
#
# Recognised by explicit pressure_type='diplomatic' (canonical native tagging,
# which the GPI also trusts) OR by category, for trackers not yet migrated.
DIPLOMATIC_CATEGORIES = (
    'diplomatic_offramp', 'diplomatic_active', 'mediation_active',
    'off_ramp_active', 'ceasefire', 'diplomatic',
)

# Synthesis cache
BLUF_CACHE_KEY      = 'rhetoric:africa:regional_bluf'
BLUF_CACHE_TTL      = 14 * 3600        # 14h
BLUF_LASTGOOD_TTL   = 7 * 24 * 3600    # 7d ceiling for held tracker snapshots
BLUF_INCOMPLETE_TTL = 30 * 60          # 30min when the picture is incomplete


def _lastgood_key(theatre):
    """Durable last-known-good snapshot key for a tracker."""
    return 'rhetoric:' + str(theatre) + ':lastgood'


# ============================================================
# ESCALATION LABELS (canonical, matches Somalia tracker ladder)
# ============================================================
ESCALATION_LABELS = {
    0: 'Monitoring',
    1: 'Rhetoric',
    2: 'Tension',
    3: 'Confrontation',
    4: 'Incident',
    5: 'Active Conflict',
}

ESCALATION_COLORS = {
    0: '#6b7280',
    1: '#3b82f6',
    2: '#f59e0b',
    3: '#f97316',
    4: '#ef4444',
    5: '#7c3aed',
}


# ============================================================
# REDIS HELPERS
# ============================================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            "%s/get/%s" % (UPSTASH_REDIS_URL, key),
            headers={"Authorization": "Bearer %s" % UPSTASH_REDIS_TOKEN},
            timeout=8,
        )
        if resp.status_code == 200:
            val = resp.json().get('result')
            if val:
                return json.loads(val)
    except Exception as e:
        print("[Africa BLUF] Redis GET error (%s): %s" % (key, str(e)[:120]))
    return None


def _redis_set(key, value, ttl=BLUF_CACHE_TTL):
    """Upstash REST SET -- command-array pattern (proven on this backend).

    Carries the scheme guard learned during the Jul 23 2026 caching debug: if
    UPSTASH_REDIS_URL ever holds a redis:// connection string instead of the
    https REST endpoint, requests.post raises before reaching Upstash and every
    write silently returns False. Fail loudly instead.
    """
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        print("[Africa BLUF] Redis SET skipped -- URL or TOKEN not set")
        return False
    if not UPSTASH_REDIS_URL.startswith('http'):
        print("[Africa BLUF] Redis SET ABORT -- UPSTASH_REDIS_URL is not an https "
              "REST URL (starts with '%s...')." % UPSTASH_REDIS_URL[:10])
        return False
    try:
        resp = requests.post(
            UPSTASH_REDIS_URL,
            headers={"Authorization": "Bearer %s" % UPSTASH_REDIS_TOKEN},
            json=['SET', key, json.dumps(value, default=str), 'EX', str(ttl)],
            timeout=10,
        )
        ok = (resp.status_code == 200)
        if not ok:
            print("[Africa BLUF] Redis SET FAILED (%s): HTTP %s body=%s"
                  % (key, resp.status_code, resp.text[:160]))
        return ok
    except Exception as e:
        print("[Africa BLUF] Redis SET EXCEPTION (%s): %s: %s"
              % (key, type(e).__name__, str(e)[:140]))
        return False


# ============================================================
# SAFE ACCESSORS
# ============================================================
def _safe_dict(val):
    return val if isinstance(val, dict) else {}


def _safe_list(val):
    return val if isinstance(val, list) else []


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_str(val, default=''):
    return val if isinstance(val, str) else default


# ============================================================
# NORMALIZATION SHIM
# ============================================================
def _normalize_tracker_data(theatre, raw_data):
    """
    Convert a raw Africa tracker cache into the canonical rollup shape.

    Africa trackers follow the ME/interpretation-wrapper pattern (Somalia
    emits result['interpretation'] containing so_what / red_lines /
    historical_matches / action_reads), plus junction-specific blocks
    (wheel_convergence, silence_anomalies, vector_levels).
    """
    if not raw_data:
        return None

    flag = THEATRE_FLAGS.get(theatre, '')
    interp     = _safe_dict(raw_data.get('interpretation'))
    so_what    = _safe_dict(interp.get('so_what')   or raw_data.get('so_what'))
    red_lines  = _safe_dict(interp.get('red_lines') or raw_data.get('red_lines'))

    # ---- THREAT LEVEL ----
    # Somalia emits theatre_escalation_level; keep the Europe fallbacks so a
    # future Africa tracker written to a different convention still lands.
    threat = _safe_int(raw_data.get('theatre_escalation_level',
                       raw_data.get('theatre_level',
                       raw_data.get('overall_level',
                       raw_data.get('threat_level', 0)))))

    # Vector-level backstop: a weighted composite can dilute genuine multi-front
    # activity. Surface the hottest single vector so the rollup does not
    # under-read breadth (mirrors Europe's peak_wheel/peak_vector handling).
    vector_levels = _safe_dict(raw_data.get('vector_levels'))
    if vector_levels:
        try:
            peak_vector = max(_safe_int(v) for v in vector_levels.values())
        except ValueError:
            peak_vector = 0
        if peak_vector > threat:
            threat = peak_vector

    # ---- SCORE ----
    score = _safe_int(raw_data.get('theatre_score',
                      raw_data.get('rhetoric_score',
                      raw_data.get('pressure_score',
                      raw_data.get('overall_score', 0)))))
    if score == 0 and threat:
        score = int(threat) * 20

    # ---- JUNCTION BLOCKS (Africa-specific) ----
    wheel = _safe_dict(raw_data.get('wheel_convergence'))
    silence = _safe_list(raw_data.get('silence_anomalies'))

    return {
        'theatre':      theatre,
        'display':      THEATRE_DISPLAY.get(theatre, theatre.upper()),
        'flag':         flag,
        'score':        score,
        'levels': {
            'threat':         int(threat or 0),
            'influence':      None,          # forward-ready (Africa has no influence axis yet)
            'dominant_axis':  'threat',
            'dominant_level': int(threat or 0),
        },
        'so_what':        so_what,
        'red_lines':      red_lines,
        'vector_levels':  vector_levels,
        'wheel':          wheel,
        'silence':        silence,
        'top_signals':    _safe_list(raw_data.get('top_signals')),
        'scanned_at':     _safe_str(raw_data.get('scan_date')),
        'article_count':  _safe_int(raw_data.get('article_count')),
        'raw':            raw_data,
    }


# ============================================================
# TRACKER READ (with last-known-good fallback)
# ============================================================
def _read_all_trackers():
    """
    Read every Africa tracker cache and normalize.

    Cold-start resilience (cloned from Europe A/B/C):
      C: missing live cache -> durable last-known-good snapshot (7d ceiling)
         so a country is HELD in the rollup rather than silently dropped.
      B: report which trackers are live / stale / fully absent.
    Returns (trackers, missing, stale).
    """
    trackers = {}
    missing  = []
    stale    = []
    for theatre, redis_key in TRACKER_KEYS.items():
        raw = _redis_get(redis_key)
        if raw:
            normalized = _normalize_tracker_data(theatre, raw)
            if normalized:
                normalized['freshness'] = 'live'
                trackers[theatre] = normalized
                _redis_set(_lastgood_key(theatre), raw, ttl=BLUF_LASTGOOD_TTL)
                print("[Africa BLUF] %s: loaded (L%d, score=%s)"
                      % (theatre, normalized['levels']['threat'], normalized['score']))
                continue
        lg = _redis_get(_lastgood_key(theatre))
        if lg:
            normalized = _normalize_tracker_data(theatre, lg)
            if normalized:
                normalized['freshness'] = 'stale'
                trackers[theatre] = normalized
                stale.append(theatre)
                print("[Africa BLUF] %s: STALE fallback (last-known-good held)" % theatre)
                continue
        missing.append(theatre)
        print("[Africa BLUF] %s: no cache available (absent from rollup)" % theatre)
    return trackers, missing, stale


# ============================================================
# REGIONAL POSTURE
# ============================================================
def _determine_regional_posture(trackers):
    """
    Roll up posture across Africa trackers.

    Junction divergence from Europe: an active multi-wheel convergence is a
    regional-realignment read and elevates posture on its own, because the
    analytical weight of >=2 external wheels lighting simultaneously exceeds
    what the country-level composite alone conveys.
    """
    if not trackers:
        return {
            'label':              'BASELINE',
            'color':              '#6b7280',
            'peak_level':         0,
            'breached_count':     0,
            'theatres_at_l3plus': 0,
            'wheel_converged':    False,
            'wheel_count':        0,
            'active_wheels':      [],
            'silence_count':      0,
        }

    levels = [t['levels']['threat'] for t in trackers.values()]
    max_level = max(levels) if levels else 0

    total_breached = 0
    for data in trackers.values():
        rl = data.get('red_lines', {}) or {}
        for r in rl.get('triggered', []) or []:
            if isinstance(r, dict) and r.get('status') == 'BREACHED':
                total_breached += 1

    theatres_at_l3plus = sum(1 for l in levels if l >= 3)

    # Junction convergence (Somalia today; any junction tracker in future)
    wheel_converged = False
    wheel_count     = 0
    active_wheels   = []
    for data in trackers.values():
        w = data.get('wheel', {}) or {}
        if w.get('converged'):
            wheel_converged = True
            wc = _safe_int(w.get('wheel_count'))
            aw = _safe_list(w.get('active_wheels'))
            if wc > wheel_count:
                wheel_count = wc
            for x in aw:
                if x not in active_wheels:
                    active_wheels.append(x)
    if wheel_count == 0 and active_wheels:
        wheel_count = len(active_wheels)

    # Silence anomalies across claiming actors
    silence_count = sum(len(_safe_list(d.get('silence'))) for d in trackers.values())

    # Posture ladder
    if total_breached >= 2 or max_level >= 5:
        label, color = 'CRITICAL -- MULTI-BREACH OR ACTIVE CONFLICT', '#dc2626'
    elif wheel_converged and wheel_count >= 3:
        label, color = 'CRITICAL -- MULTI-WHEEL JUNCTION CONVERGENCE', '#dc2626'
    elif total_breached >= 1 or max_level >= 4:
        label, color = 'ELEVATED -- INCIDENT OR RED LINE', '#ef4444'
    elif wheel_converged:
        label, color = 'ELEVATED -- JUNCTION CONVERGENCE', '#ef4444'
    elif theatres_at_l3plus >= 2:
        label, color = 'ELEVATED -- MULTI-COUNTRY WARNING', '#f97316'
    elif max_level >= 3:
        label, color = 'WARNING -- DIRECT THREAT', '#f59e0b'
    elif max_level >= 2:
        label, color = 'MONITORING -- WARNING', '#fbbf24'
    elif max_level >= 1:
        label, color = 'MONITORING -- RHETORIC', '#3b82f6'
    else:
        label, color = 'BASELINE', '#6b7280'

    return {
        'label':              label,
        'color':              color,
        'peak_level':         max_level,
        'breached_count':     total_breached,
        'theatres_at_l3plus': theatres_at_l3plus,
        'wheel_converged':    wheel_converged,
        'wheel_count':        wheel_count,
        'active_wheels':      active_wheels,
        'silence_count':      silence_count,
    }


# ============================================================
# COVERAGE HONESTY
# ============================================================
def _coverage_note(trackers, missing):
    """
    State the coverage reality plainly. A one-tracker 'region' is a country
    read carried at regional altitude -- saying so is the whole point of
    absence-honesty. Never let the reader infer synthesis that does not exist.
    """
    live = len(trackers)
    if live == 0:
        return ('No Africa tracker caches loaded. Nothing is being asserted about '
                'the region this cycle.')
    if live == 1:
        only = list(trackers.keys())[0]
        return ('Africa coverage is currently a SINGLE tracker (%s). This is a '
                'country read carried at regional altitude, not a synthesized '
                'regional picture -- treat it as one sensor, not a continent. '
                'Regional synthesis begins when additional trackers land.'
                % THEATRE_DISPLAY.get(only, only.title()))
    return ('Africa coverage: %d trackers live of %d configured. Countries without '
            'a tracker are absent from this read, not assessed as quiet.'
            % (live, len(TRACKER_KEYS)))


# ============================================================
# BLUF PROSE
# ============================================================
def _build_bluf_prose(posture, trackers, missing):
    """
    Generate the regional prose paragraph -- country-named, estimative voice.

    Branches on coverage depth: a single tracker gets an explicitly-scoped
    country read; two or more get genuine cross-country synthesis. The prose
    grows into a regional voice as the queue lands, rather than pretending to
    have one on day one.
    """
    if not trackers:
        return ('Africa regional BLUF unavailable -- no country tracker caches '
                'loaded this cycle. Absence of data is not absence of pressure.')

    live = len(trackers)
    parts = []

    # ---- SINGLE-TRACKER MODE (today: Somalia only) ----
    if live == 1:
        theatre, data = list(trackers.items())[0]
        display = THEATRE_DISPLAY.get(theatre, theatre.upper())
        lvl     = data['levels']['threat']
        label   = ESCALATION_LABELS.get(lvl, 'Unknown')
        score   = data.get('score', 0)

        parts.append('%s carries the Africa read at L%d (%s), composite %s/100.'
                     % (display, lvl, label, score))

        # Hottest vectors -- names the drivers rather than asserting a cause
        vl = data.get('vector_levels', {}) or {}
        hot = sorted(((k, _safe_int(v)) for k, v in vl.items() if _safe_int(v) >= 3),
                     key=lambda kv: kv[1], reverse=True)
        if hot:
            names = ', '.join('%s L%d' % (k.replace('_', ' '), v) for k, v in hot[:4])
            parts.append('Lead vectors: %s.' % names)

        # Junction read -- the marquee
        w = data.get('wheel', {}) or {}
        if w.get('converged'):
            wheels = ', '.join(_safe_list(w.get('active_wheels'))) or 'multiple'
            parts.append('Junction CONVERGED across %s -- simultaneous external-wheel '
                         'pressure at the Horn crossing-point is the pattern that has '
                         'historically preceded regional realignment windows.' % wheels)
        else:
            parts.append('Junction dormant: external wheels (Turkey, Russia, '
                         'Bab-el-Mandeb, Israel-Somaliland) are not lighting together '
                         'this cycle; each rides independently.')

        # Silence -- Africa-specific signal class
        sil = _safe_list(data.get('silence'))
        if sil:
            who = ', '.join(_safe_str(s.get('actor_name') or s.get('actor_id', ''))
                            .replace('_', ' ') for s in sil[:3] if isinstance(s, dict))
            parts.append('Claiming-actor silence detected (%s) -- for actors that '
                         'normally claim, quiet is itself a signal and is read as '
                         'tempo change, not absence of activity.' % who)

        # Red lines
        rl = data.get('red_lines', {}) or {}
        breached = _safe_int(rl.get('breached_count'))
        approaching = _safe_int(rl.get('approaching_count'))
        if breached or approaching:
            parts.append('Red lines: %d breached, %d approaching.' % (breached, approaching))

        parts.append('COVERAGE: this is a single-country read at regional altitude; '
                     'no continental synthesis is implied.')
        return ' '.join(parts)

    # ---- MULTI-TRACKER MODE (activates as the queue lands) ----
    parts.append('Africa regional posture: %s.' % posture['label'])

    ranked = sorted(trackers.items(),
                    key=lambda kv: (kv[1]['levels']['threat'], kv[1].get('score', 0)),
                    reverse=True)
    lead = ranked[0]
    lead_display = THEATRE_DISPLAY.get(lead[0], lead[0].upper())
    parts.append('%s leads at L%d (%s), composite %s/100.'
                 % (lead_display, lead[1]['levels']['threat'],
                    ESCALATION_LABELS.get(lead[1]['levels']['threat'], 'Unknown'),
                    lead[1].get('score', 0)))

    if len(ranked) > 1:
        others = '; '.join('%s L%d' % (THEATRE_DISPLAY.get(t, t.upper()),
                                       d['levels']['threat'])
                           for t, d in ranked[1:5])
        parts.append('Also live: %s.' % others)

    if posture['theatres_at_l3plus'] >= 2:
        parts.append('%d countries at L3+ simultaneously -- breadth, not a single '
                     'hotspot, is carrying the regional read.'
                     % posture['theatres_at_l3plus'])

    if posture['wheel_converged']:
        wheels = ', '.join(posture['active_wheels']) or 'multiple'
        parts.append('Junction CONVERGED across %s.' % wheels)

    if posture['silence_count']:
        parts.append('%d claiming-actor silence anomal%s flagged -- quiet from actors '
                     'that normally claim reads as tempo change.'
                     % (posture['silence_count'],
                        'y' if posture['silence_count'] == 1 else 'ies'))

    if posture['breached_count']:
        parts.append('%d red line%s breached region-wide.'
                     % (posture['breached_count'],
                        '' if posture['breached_count'] == 1 else 's'))

    if missing:
        parts.append('Absent from this read: %s (no tracker cache -- not assessed '
                     'as quiet).' % ', '.join(THEATRE_DISPLAY.get(m, m.upper())
                                              for m in missing[:5]))

    return ' '.join(parts)


# ============================================================
# SIGNAL POOL
# ============================================================
def _is_diplomatic(sig):
    """Is this a de-escalation / off-ramp signal?

    Explicit pressure_type wins (canonical native tagging -- the GPI trusts the
    same field). Falls back to category matching for trackers not yet migrated.
    """
    if not isinstance(sig, dict):
        return False
    if str(sig.get('pressure_type', '')).lower() == 'diplomatic':
        return True
    return str(sig.get('category', '')).lower() in DIPLOMATIC_CATEGORIES


def _surfaces_regionally(sig):
    """Regional-altitude gate: L2+ OR any diplomatic signal.

    Diplomatic signals bypass the level floor because an L1 mediation reference
    is still the only observable off-ramp -- absence of an off-ramp is itself a
    read, and we cannot report absence honestly if we filtered the presence out.
    Regional synthesis signals always surface.
    """
    if not isinstance(sig, dict):
        return False
    if sig.get('theatre') == 'regional':
        return True
    if _is_diplomatic(sig):
        return True
    return _safe_int(sig.get('level'), 0) >= MIN_LEVEL_TO_SURFACE


def _build_signals(posture, trackers):
    """Collect, enrich, and rank the signal pool GPI consumes."""
    all_signals = []

    # 1) Pass through each tracker's own top_signals
    for theatre, data in trackers.items():
        flag = data.get('flag', '')
        for sig in _safe_list(data.get('top_signals')):
            if not isinstance(sig, dict):
                continue
            s = dict(sig)
            s.setdefault('priority', 5)
            s.setdefault('category', 'unknown')
            s.setdefault('theatre', theatre)
            s.setdefault('icon', '\u2022')
            s.setdefault('color', '#6b7280')
            s.setdefault('short_text', '')
            s.setdefault('long_text', s.get('short_text', ''))
            # Prefix with country so regional context survives into GPI.
            # v1.0.1 (Jul 23 2026) FIX: the old check was startswith(disp), but
            # tracker signals arrive already prefixed with FLAG + name
            # ("SO SOMALIA: ..."), so startswith('SOMALIA') was False and the
            # prefix was applied twice ("SO SOMALIA: SO SOMALIA: ..."). Test
            # whether the country is named anywhere in the text instead.
            disp = THEATRE_DISPLAY.get(theatre, theatre.upper())
            if disp.upper() not in s['short_text'].upper():
                s['short_text'] = '%s %s: %s' % (flag, disp, s['short_text'])
            all_signals.append(s)

    # 2) Junction convergence -- Africa's marquee regional signal
    if posture.get('wheel_converged'):
        wheels = _safe_list(posture.get('active_wheels'))
        n = posture.get('wheel_count') or len(wheels)
        all_signals.append({
            'priority':   15,
            'category':   'junction_convergence',
            'theatre':    'regional',
            'level':      max(4, posture.get('peak_level', 0)),
            'icon':       '\U0001F300',   # cyclone
            'color':      '#dc2626',
            'short_text': 'AFRICA: Junction convergence -- %d wheels lit (%s)'
                          % (n, ', '.join(wheels) if wheels else 'multiple'),
            'long_text':  ('AFRICA junction convergence -- %d external wheels lighting '
                           'simultaneously at the Horn crossing-point (%s). Simultaneous '
                           'multi-patron pressure on a single junction state is the '
                           'pattern that historically precedes regional realignment. '
                           'CONVERGENCE indicator, NOT a probability of action.'
                           % (n, ', '.join(wheels) if wheels else 'multiple')),
        })

    # 3) Claiming-actor silence -- signal class Europe has no equivalent for
    for theatre, data in trackers.items():
        for anom in _safe_list(data.get('silence'))[:2]:
            if not isinstance(anom, dict):
                continue
            actor = _safe_str(anom.get('actor_name') or anom.get('actor_id', 'actor')).replace('_', ' ')
            disp  = THEATRE_DISPLAY.get(theatre, theatre.upper())
            all_signals.append({
                'priority':   11,
                'category':   'claiming_actor_silence',
                'theatre':    theatre,
                'level':      3,
                'icon':       '\U0001F507',   # muted speaker
                'color':      '#7c3aed',
                'short_text': '%s: %s quiet vs baseline -- silence is signal'
                              % (disp, actor),
                'long_text':  ('%s -- %s has gone quiet against its own claiming '
                               'baseline (%s). For actors that normally claim '
                               'operations, silence reads as tempo change rather than '
                               'absence of activity; historically consistent with '
                               'reconstitution or operational-security posture ahead of '
                               'renewed claiming.'
                               % (disp, actor, _safe_str(anom.get('deviation'), 'deviation unstated'))),
            })

    # 4) Gate, then sort with per-theatre quota.
    #    Order of operations matters: gate BEFORE the quota, so a country's
    #    three slots go to signals that actually cleared the bar.
    #
    #    Two bypasses:
    #      * theatre == 'regional'  -- synthesis-level signals, not a country's
    #      * diplomatic signals     -- score reducers the sort would bury
    gated = [s for s in all_signals
             if _surfaces_regionally(s)]

    gated.sort(key=lambda s: (-_safe_int(s.get('priority'), 5),
                              -_safe_int(s.get('level'), 0)))

    selected, per_theatre, dip_seen = [], {}, 0
    for s in gated:
        t = s.get('theatre', 'unknown')
        if t == 'regional':
            selected.append(s)
            continue
        if _is_diplomatic(s):
            # Bypass the per-theatre quota up to the cap. Diplomatic signals do
            # NOT consume a country's escalatory slots -- they sit beside them,
            # the same way the doctrine reports mediation beside kinetic tempo
            # rather than netting it against them.
            if dip_seen < DIPLOMATIC_SURFACE_CAP:
                dip_seen += 1
                selected.append(s)
                continue
            # Past the cap it competes normally.
        if per_theatre.get(t, 0) >= MAX_PER_THEATRE:
            continue
        per_theatre[t] = per_theatre.get(t, 0) + 1
        selected.append(s)

    dropped = len(all_signals) - len(gated)
    if dropped:
        print('[Africa BLUF] Gate: %d signal(s) below L%d held at country altitude'
              % (dropped, MIN_LEVEL_TO_SURFACE))
    if dip_seen:
        print('[Africa BLUF] Diplomatic guard: %d de-escalation signal(s) surfaced'
              % dip_seen)
    return selected


# ============================================================
# MAIN BUILD
# ============================================================
# ============================================================
# CONVERGENCE PANEL  (spoke & wheel -- Africa is SPOKES ONLY)
# ============================================================
# Africa hosts NO hub. Every wheel read here is OUTBOUND: African countries
# feed hubs that live on other backends -- Turkey (Europe), Russia (Europe),
# and in time China (Asia) and a light Israel touch via Somaliland.
#
# RESIDENT_HUBS is therefore empty, and the panel renders as pure emanating.
# The moment a hub does become resident here, adding its slug to this list is
# the entire change.
#
# NOTHING is a hardcoded country list: local_countries derives from
# TRACKER_KEYS, so the Sahel bundle joins the emanating scan the moment those
# trackers register. Wagner spokes across Mali/Niger/Burkina Faso and the
# future BRI spokes need no edit here and none in the frontend.
RESIDENT_HUBS = []


def _build_convergence_panel():
    """Outbound wheel read for the Africa payload. Never raises."""
    if not _WHEEL_READER:
        return None
    try:
        return _build_wheel_panel(
            resident_hubs=RESIDENT_HUBS,
            local_countries=list(TRACKER_KEYS.keys()),
            region='africa',
        )
    except Exception as e:
        print(f"[Africa BLUF] Convergence panel failed (non-fatal): {str(e)[:140]}")
        return None


def build_regional_bluf(force=False):
    """Build the Africa regional BLUF."""
    if not force:
        cached = _redis_get(BLUF_CACHE_KEY)
        if cached and cached.get('generated_at'):
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(cached['generated_at'])).total_seconds()
                if age < BLUF_CACHE_TTL:
                    cached['from_cache'] = True
                    return cached
            except Exception:
                pass

    print('[Africa BLUF v1.0] Building regional BLUF from Africa tracker caches...')

    try:
        trackers, trackers_missing, trackers_stale = _read_all_trackers()

        if not trackers:
            return {
                'success':       False,
                'error':         'No tracker data available',
                'bluf':          'Africa BLUF unavailable -- no country tracker caches loaded.',
                'coverage_note': _coverage_note({}, trackers_missing),
                'signals':       [],
                'top_signals':   [],
                'posture_label': 'UNAVAILABLE',
                'posture_color': '#6b7280',
                'region':        'africa',
            }

        posture     = _determine_regional_posture(trackers)
        bluf        = _build_bluf_prose(posture, trackers, trackers_missing)
        all_signals = _build_signals(posture, trackers)
        top_signals = all_signals[:TOP_SIGNALS_COUNT]
        trackers_live = len(trackers)

        # Per-theatre summary
        theatre_summary = {}
        for t, data in trackers.items():
            lvls = data.get('levels', {}) or {}
            threat_lvl = lvls.get('threat', 0)
            theatre_summary[t] = {
                'level':           threat_lvl,
                'label':           ESCALATION_LABELS.get(threat_lvl, 'Unknown'),
                'color':           ESCALATION_COLORS.get(threat_lvl, '#6b7280'),
                'score':           data.get('score', 0),
                'flag':            data.get('flag', THEATRE_FLAGS.get(t, '')),
                'display':         data.get('display', THEATRE_DISPLAY.get(t, t.upper())),
                'timestamp':       data.get('scanned_at', ''),
                'threat_level':    threat_lvl,
                'influence_level': None,
                'dominant_axis':   'threat',
                'dominant_level':  threat_lvl,
                'is_dual_axis':    False,
                'freshness':       data.get('freshness', 'live'),
                'article_count':   data.get('article_count', 0),
                'vector_levels':   data.get('vector_levels', {}),
            }

        scores = [t.get('score', 0) for t in theatre_summary.values()]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        result = {
            'success':            True,
            'from_cache':         False,
            'bluf':               bluf,
            'coverage_note':      _coverage_note(trackers, trackers_missing),
            'single_tracker_mode': (trackers_live == 1),
            'signals':            all_signals,
            'top_signals':        top_signals,
            'posture_label':      posture['label'],
            'posture_color':      posture['color'],
            'peak_level':         posture['peak_level'],
            'max_level':          posture['peak_level'],
            'avg_score':          avg_score,
            'red_lines_breached': posture['breached_count'],
            # Africa-specific rollup fields
            'wheel_converged':    posture['wheel_converged'],
            'wheel_count':        posture['wheel_count'],
            'active_wheels':      posture['active_wheels'],
            'silence_anomaly_count': posture['silence_count'],
            # Coverage bookkeeping
            'trackers_live':      trackers_live,
            'theatres_live':      trackers_live,
            'theatres_at_l3plus': posture['theatres_at_l3plus'],
            'trackers_total':     len(TRACKER_KEYS),
            'trackers_stale':     trackers_stale,
            'trackers_missing':   trackers_missing,
            'picture_complete':   (len(trackers_missing) == 0),
            'convergence_panel':  _build_convergence_panel(),
            'theatre_summary':    theatre_summary,
            'generated_at':       datetime.now(timezone.utc).isoformat(),
            'version':            '1.0.1',
            'methodology_note':   (
                'How to read this: country scores are rhetoric-signal composites -- '
                'weighted volume and severity of classified statements from officials, '
                'state media, insurgent claim channels, and OSINT feeds -- not event '
                'counts and not probabilities of action. Claiming-actor silence is read '
                'as tempo change, not quiet. Convergence, not prediction.'
            ),
            'region':             'africa',
            'top_signals_count':  len(top_signals),
        }

        _bluf_ttl = BLUF_INCOMPLETE_TTL if (trackers_missing or trackers_stale) else BLUF_CACHE_TTL
        wrote = _redis_set(BLUF_CACHE_KEY, result, ttl=_bluf_ttl)
        result['cache_written'] = bool(wrote)
        print("[Africa BLUF v1.0] Built: posture=%s, max_level=L%d, breached=%d, "
              "signals=%d, trackers_live=%d/%d, wheel_converged=%s, cache_written=%s"
              % (posture['label'], posture['peak_level'], posture['breached_count'],
                 len(top_signals), trackers_live, len(TRACKER_KEYS),
                 posture['wheel_converged'], wrote))
        return result

    except Exception as e:
        print("[Africa BLUF] SYNTHESIS EXCEPTION: %s" % e)
        print(traceback.format_exc())
        return {
            'success':       False,
            'error':         '%s: %s' % (type(e).__name__, str(e)[:300]),
            'bluf':          'Africa BLUF synthesis failed -- check backend logs for traceback.',
            'signals':       [],
            'top_signals':   [],
            'posture_label': 'ERROR',
            'posture_color': '#6b7280',
            'region':        'africa',
        }


# ============================================================
# ROUTE REGISTRATION
# ============================================================
def register_africa_bluf_routes(app):
    """Register Africa BLUF endpoints on the given Flask app."""
    from flask import jsonify, request as flask_request

    @app.route('/api/rhetoric/africa/bluf', methods=['GET'])
    def get_africa_bluf():
        force = flask_request.args.get('force', 'false').lower() in ('true', '1', 'yes')
        return jsonify(build_regional_bluf(force=force))

    @app.route('/api/rhetoric/africa/bluf/debug', methods=['GET'])
    def get_africa_bluf_debug():
        cached = _redis_get(BLUF_CACHE_KEY)
        tracker_state = {}
        for theatre, key in TRACKER_KEYS.items():
            tracker_state[theatre] = {
                'live_cache_present':     bool(_redis_get(key)),
                'lastgood_cache_present': bool(_redis_get(_lastgood_key(theatre))),
                'key':                    key,
            }
        return jsonify({
            'module':         'africa_regional_bluf v1.0.0',
            'bluf_cache_key': BLUF_CACHE_KEY,
            'cache_present':  cached is not None,
            'trackers_configured': list(TRACKER_KEYS.keys()),
            'tracker_state':  tracker_state,
            'cache_data':     cached,
        })

    print('[Africa BLUF] \u2705 Routes registered: /api/rhetoric/africa/bluf (+/bluf/debug)')


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    print("Africa Regional BLUF Engine -- standalone test")
    print("(Requires Redis env vars to actually read tracker caches)")
    print()
    result = build_regional_bluf(force=True)
    print('BLUF:')
    print(result.get('bluf', '(no BLUF)'))
    print()
    print('COVERAGE:')
    print(result.get('coverage_note', ''))
    print()
    print('TOP SIGNALS:')
    for s in result.get('top_signals', []):
        print('  %s %s' % (s.get('icon', '\u2022'), s.get('short_text', '')))
    print()
    print('POSTURE:      %s' % result.get('posture_label', ''))
    print('MAX LEVEL:    L%s' % result.get('max_level', 0))
    print('TRACKERS:     %s/%s live' % (result.get('trackers_live', 0),
                                        result.get('trackers_total', 0)))
    print('WHEEL CONV:   %s' % result.get('wheel_converged', False))
