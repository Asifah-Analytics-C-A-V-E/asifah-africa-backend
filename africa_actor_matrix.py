"""
Asifah Analytics -- Africa Actor Matrix v1.0.0
November 1, 2026

The Africa sibling of the ME Actor Matrix (threat_matrix_v3.py), built for a
different kind of war. The ME board asks which STATE is pressing which state.
Africa's conflicts are mostly armed groups against states, outside forces
hitting back, and PATRONS paying for one side. So every pair carries a KIND:

  offensive   armed group -> state        who has the initiative
  counter     state / partner -> group    who is hitting back, and with whose help
  patron      outside backer -> client    who is paying for it (the leading indicator)
  spillover   a war -> a neighbour        where it is leaking

The patron rows are the So What. Battlefields tend to follow the money and the
materiel: when UAE -> RSF climbs, the fighting usually follows. A reader who
only watches RSF -> SAF sees the result; the patron row shows what is coming.

A READER, NOT A SCANNER. Every cell comes from a rhetoric tracker that already
runs (Somalia, Sudan, Mali, Burkina Faso -- the africa_regional_bluf TRACKER_KEYS):
  ('actor',  tracker, actor_id)   payload['actors'][id]['escalation_level']
  ('vector', tracker, vector)     payload['vector_levels_platform'] or ['vector_levels']
The cell takes the highest source, CAPPED at that tracker's own gated theatre
level (theatre_escalation_level / theatre_level) -- a sub-reading may not
out-shout its tracker, whose level carries the L5 gate and the 2+ source rule.
Burkina Faso's actor levels are volume words (low..surge), not escalation, so
Burkina pairs read its platform vector levels only.

No tracker -> 'unread'. Tracker read but the source empty -> 'not sensed'.
Neither is ever shown as L0. Countries without a tracker are absent from the
board, not quiet; add their pairs here when their tracker ships.

ENDPOINTS
  /api/africa/actor-matrix               all pairs + headline + So What lines
  /api/africa/actor-matrix?actor=sudan   pairs touching one card (sudan, chad, mali ...)
  /api/africa/actor-matrix/debug         per tracker: actors, vectors, which pairs read them

Cost: Redis reads only (4 trackers), cached 15 min. No external fetch, ever.
"""

import time
from datetime import datetime, timezone

MATRIX_VERSION = '1.0.0'
CACHE_KEY = 'actor_matrix:africa:latest'
PREV_KEY = 'actor_matrix:africa:previous_levels'
CACHE_SEC = 15 * 60

LADDER = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning', 3: 'Confrontation',
          4: 'Coercion', 5: 'Active Conflict', 6: 'Red Line Breached'}
KIND_LABELS = {'offensive': 'Armed group → state', 'counter': 'Hitting back',
               'patron': 'Who is paying for it', 'spillover': 'Where it leaks'}

SD, SO, ML, BF = '🇸🇩', '🇸🇴', '🇲🇱', '🇧🇫'
RU, AE, US, TR, TD, SS, LY = '🇷🇺', '🇦🇪', '🇺🇸', '🇹🇷', '🇹🇩', '🇸🇸', '🇱🇾'
GROUP = '🏴'


def _P(pid, kind, actor, a_flag, target, t_flag, keys, sources, theatre, note=''):
    return {'id': pid, 'kind': kind, 'actor': actor, 'actor_flag': a_flag, 'target': target,
            'target_flag': t_flag, 'keys': keys, 'sources': sources, 'theatre': theatre, 'note': note}


PAIRS = [
    # ---------------- SUDAN ----------------
    _P('rsf>saf', 'offensive', 'RSF (Hemedti)', GROUP, 'SAF / Port Sudan government', SD, ['sudan'],
       [('actor', 'sudan', 'rsf_hemedti'), ('vector', 'sudan', 'kinetic')], 'sudan'),
    _P('saf>rsf', 'counter', 'SAF (Burhan)', SD, 'RSF / Tasis areas', GROUP, ['sudan'],
       [('actor', 'sudan', 'saf_burhan'), ('vector', 'sudan', 'kinetic')], 'sudan'),
    _P('uae>rsf', 'patron', 'UAE', AE, 'RSF (principal patron)', GROUP, ['sudan', 'uae'],
       [('actor', 'sudan', 'uae_axis'), ('vector', 'sudan', 'uae_axis')], 'sudan'),
    _P('russia>saf', 'patron', 'Russia / Africa Corps', RU, 'SAF (Port Sudan naval plug)', SD, ['sudan', 'russia'],
       [('actor', 'sudan', 'russia_africa_corps'), ('vector', 'sudan', 'russia_plug')], 'sudan'),
    _P('patrons>saf', 'patron', 'Egypt · Saudi · Türkiye · Iran', '🌐', 'SAF', SD, ['sudan', 'egypt'],
       [('actor', 'sudan', 'saf_patrons'), ('vector', 'sudan', 'saf_patron')], 'sudan'),
    _P('haftar>rsf', 'patron', 'Haftar (eastern Libya)', LY, 'RSF supply corridor', GROUP, ['sudan', 'chad'],
       [('actor', 'sudan', 'libya_haftar'), ('vector', 'sudan', 'libya_haftar')], 'sudan'),
    _P('sudan>chad', 'spillover', 'Sudan war', SD, 'Chad (eastern border)', TD, ['sudan', 'chad'],
       [('actor', 'sudan', 'chad_border'), ('vector', 'sudan', 'spillover_west')], 'sudan'),
    _P('sudan>south_sudan', 'spillover', 'Sudan war', SD, 'South Sudan (oil corridor)', SS, ['sudan', 'south_sudan'],
       [('actor', 'sudan', 'south_sudan_corridor'), ('vector', 'sudan', 'spillover_south')], 'sudan'),

    # ---------------- SOMALIA ----------------
    _P('shabaab>fgs', 'offensive', 'Al-Shabaab', GROUP, 'Federal Government (Mogadishu)', SO, ['somalia'],
       [('actor', 'somalia', 'al_shabaab'), ('vector', 'somalia', 'shabaab')], 'somalia'),
    _P('isis>puntland', 'offensive', 'ISIS-Somalia', GROUP, 'Puntland / federal forces', SO, ['somalia'],
       [('actor', 'somalia', 'isis_somalia'), ('vector', 'somalia', 'isis')], 'somalia'),
    _P('africom>shabaab', 'counter', 'US / AFRICOM', US, 'Al-Shabaab & ISIS-Somalia', GROUP, ['somalia'],
       [('actor', 'somalia', 'us_africom'), ('vector', 'somalia', 'africom')], 'somalia'),
    _P('patrons>somalia', 'patron', 'Türkiye · UAE · Ethiopia · Egypt', TR, 'Mogadishu & member states', SO,
       ['somalia', 'ethiopia'],
       [('actor', 'somalia', 'foreign_patrons'), ('vector', 'somalia', 'patron')], 'somalia',
       note='Competing patrons: Turkish and Egyptian backing of Mogadishu vs UAE/Ethiopian ties to member states and Somaliland.'),
    _P('somaliland>somalia', 'spillover', 'Somaliland recognition push', '🌐', 'Somali unity', SO, ['somalia', 'ethiopia'],
       [('vector', 'somalia', 'somaliland')], 'somalia'),

    # ---------------- MALI ----------------
    _P('jnim>mali', 'offensive', 'JNIM (al-Qaeda)', GROUP, 'Mali junta / Bamako', ML, ['mali'],
       [('actor', 'mali', 'jnim'), ('vector', 'mali', 'blockade'), ('vector', 'mali', 'insurgent_convergence')], 'mali',
       note='Includes the fuel blockade on Bamako.'),
    _P('issp>mali', 'offensive', 'ISSP (Islamic State Sahel)', GROUP, 'Mali (Ménaka / tri-border)', ML, ['mali', 'niger'],
       [('actor', 'mali', 'issp')], 'mali'),
    _P('fla>mali', 'offensive', 'FLA (Tuareg, Azawad)', GROUP, 'Mali junta (north)', ML, ['mali'],
       [('actor', 'mali', 'fla')], 'mali'),
    _P('mali>insurgents', 'counter', 'Mali junta / FAMa', ML, 'JNIM, ISSP & FLA', GROUP, ['mali'],
       [('actor', 'mali', 'mali_junta'), ('vector', 'mali', 'kinetic')], 'mali'),
    _P('africacorps>mali', 'counter', 'Russia / Africa Corps', RU, 'Insurgents in Mali (with FAMa)', GROUP, ['mali', 'russia'],
       [('actor', 'mali', 'africa_corps')], 'mali',
       note='Africa Corps is both the junta\'s patron and a combatant; the Mali tracker\'s trajectory read says whether it is gaining or losing.'),
    _P('turkey>mali', 'patron', 'Türkiye (drones, hedge)', TR, 'Mali junta', ML, ['mali'],
       [('actor', 'mali', 'turkey_hedge'), ('vector', 'mali', 'hedging')], 'mali'),

    # ---------------- BURKINA FASO ----------------
    _P('insurgents>bf', 'offensive', 'JNIM & ISGS', GROUP, 'Burkina junta (Traoré)', BF, ['burkina_faso'],
       [('vector', 'burkina_faso', 'insurgent_contest')], 'burkina_faso'),
    _P('russia>bf', 'patron', 'Russia', RU, 'Burkina junta (alignment)', BF, ['burkina_faso', 'russia'],
       [('vector', 'burkina_faso', 'external_alignment')], 'burkina_faso'),
    _P('plotters>bf', 'offensive', 'Internal challengers (coup plots)', '⚔️', 'Traoré junta', BF, ['burkina_faso'],
       [('vector', 'burkina_faso', 'junta_consolidation')], 'burkina_faso'),
]

CARD_ALIASES = {'burkina': 'burkina_faso', 'south-sudan': 'south_sudan'}


def _now():
    return datetime.now(timezone.utc)


def _int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return max(0, min(6, int(v)))
    if isinstance(v, str) and v.strip().lstrip('-').isdigit():
        return max(0, min(6, int(v.strip())))
    return None


# ----------------------------------------------------------------------------
# TRACKER READ -- same keys and last-known-good fallback as the regional BLUF,
# but read-only (the BLUF owns the :lastgood writes).
# ----------------------------------------------------------------------------
def _bluf():
    import africa_regional_bluf as b
    return b


def theatre_level(raw):
    for k in ('theatre_escalation_level', 'theatre_level', 'overall_level', 'threat_level'):
        v = _int(raw.get(k))
        if v is not None:
            return v
    return 0


def normalise(raw):
    actors = {}
    a = raw.get('actors')
    if isinstance(a, dict):
        for aid, rec in a.items():
            if isinstance(rec, dict):
                lv = _int(rec.get('escalation_level'))
                if lv is not None:
                    actors[aid] = lv
    vectors = {}
    vp = raw.get('vector_levels_platform') if isinstance(raw.get('vector_levels_platform'), dict) else None
    for k, v in (vp or raw.get('vector_levels') or {}).items():
        lv = _int(v)
        if lv is not None:
            vectors[k] = lv
    return {'threat': theatre_level(raw), 'actors': actors, 'vectors': vectors,
            'scanned_at': raw.get('scan_date') or raw.get('timestamp') or ''}


def read_trackers(redis_get=None):
    b = _bluf()
    rget = redis_get or b._redis_get
    out, missing = {}, []
    for th, key in b.TRACKER_KEYS.items():
        raw = rget(key)
        fresh = 'live'
        if not isinstance(raw, dict) or not raw:
            raw = rget(b._lastgood_key(th))
            fresh = 'stale'
        if isinstance(raw, dict) and raw:
            n = normalise(raw)
            n['freshness'] = fresh
            out[th] = n
        else:
            missing.append(th)
    return out, missing


# ----------------------------------------------------------------------------
# CELL + MATRIX
# ----------------------------------------------------------------------------
def read_pair(pair, trackers):
    best, tried, unread = None, [], []
    for kind, th, sid in pair['sources']:
        t = trackers.get(th)
        if not t:
            unread.append(th)
            continue
        tried.append(th)
        lv = (t['actors'] if kind == 'actor' else t['vectors']).get(sid)
        if lv is None:
            continue
        capped = min(lv, t['threat'])
        cand = {'level': capped, 'raw_level': lv, 'tracker': th, 'kind': kind, 'id': sid,
                'capped': capped < lv, 'freshness': t['freshness']}
        if best is None or cand['level'] > best['level']:
            best = cand
    cell = {k: pair[k] for k in ('id', 'kind', 'actor', 'actor_flag', 'target', 'target_flag', 'keys', 'theatre', 'note')}
    cell['kind_label'] = KIND_LABELS[pair['kind']]
    if best:
        cell.update(state='read', level=best['level'], word=LADDER[best['level']], source=best)
    elif tried:
        cell.update(state='not_sensed', level=None, word='Not sensed',
                    source={'trackers_read': sorted(set(tried)), 'reason': 'tracker read; this actor/vector absent'})
    else:
        cell.update(state='unread', level=None, word='Unread', source={'trackers_missing': sorted(set(unread))})
    return cell


def _name(c):
    return f"{c['actor']} → {c['target']}"


def build_lines(cells, prev, region_gap_note=True):
    lines = []
    read = [c for c in cells if c['state'] == 'read']
    if read:
        top = max(c['level'] for c in read)
        tops = [c for c in read if c['level'] == top]
        if top >= 3:
            lines.append(f"Highest pressure: {'; '.join(_name(c) for c in tops[:3])} at L{top} {LADDER[top]}.")
        else:
            lines.append(f"No pair above L{top} {LADDER[top]} -- pressure is rhetorical, not yet confrontational.")

    # Patron rows: the leading indicator
    pats = sorted([c for c in read if c['kind'] == 'patron' and c['level'] >= 3], key=lambda c: -c['level'])
    rising = [c for c in read if c['kind'] == 'patron' and isinstance((prev or {}).get(c['id']), int)
              and c['level'] > prev[c['id']]]
    if rising:
        lines.append('Patron pressure rising: ' + '; '.join(f"{_name(c)} (L{prev[c['id']]}→L{c['level']})" for c in rising[:3])
                     + ' -- backing moves first; battlefield shifts tend to follow.')
    elif pats:
        lines.append('Who is paying for it: ' + '; '.join(f"{_name(c)} L{c['level']}" for c in pats[:3])
                     + ' -- outside backing is active, which sustains the fight.')

    # Initiative: offensive vs counter, per theatre
    for th in sorted({c['theatre'] for c in read}):
        off = [c for c in read if c['theatre'] == th and c['kind'] == 'offensive']
        cnt = [c for c in read if c['theatre'] == th and c['kind'] == 'counter']
        if off and cnt:
            o, k = max(off, key=lambda c: c['level']), max(cnt, key=lambda c: c['level'])
            if o['level'] - k['level'] >= 2:
                lines.append(f"Initiative with the insurgents in {th.replace('_', ' ').title()}: {_name(o)} L{o['level']} "
                             f"vs the response ({k['actor']}) at L{k['level']}.")
            elif k['level'] - o['level'] >= 2:
                lines.append(f"Counter-pressure leads in {th.replace('_', ' ').title()}: {k['actor']} L{k['level']} "
                             f"vs {o['actor']} at L{o['level']}.")

    # Russia across theatres -- the great-power displacement read
    ru = [c for c in read if 'russia' in c['keys'] and c['level'] >= 2]
    if len({c['theatre'] for c in ru}) >= 2:
        lines.append('Russia is active in ' + ', '.join(
            f"{c['theatre'].replace('_', ' ').title()} (L{c['level']})" for c in sorted(ru, key=lambda c: -c['level'])[:4])
            + ' -- one footprint across several wars, which is the displacement story.')

    moved = [f"{_name(c)} (L{prev[c['id']]}→L{c['level']})" for c in read
             if isinstance((prev or {}).get(c['id']), int) and c['level'] - prev[c['id']] >= 2 and c['kind'] != 'patron']
    if moved:
        lines.append('Sharp moves since the last read: ' + '; '.join(moved[:3]) + '.')

    gaps = [c for c in cells if c['state'] != 'read']
    if gaps:
        lines.append(f"{len(gaps)} of {len(cells)} pairs not read this cycle -- shown as gaps, not as calm.")
    return lines[:5]


def build_matrix(redis_get, redis_set, trackers=None, missing=None):
    if trackers is None:
        trackers, missing = read_trackers(redis_get)
    cells = [read_pair(p, trackers) for p in PAIRS]
    prev = redis_get(PREV_KEY) or {}
    if not isinstance(prev, dict):
        prev = {}
    for c in cells:
        p = prev.get(c['id'])
        c['previous_level'] = p if isinstance(p, int) else None
        c['delta'] = (c['level'] - p) if (c['state'] == 'read' and isinstance(p, int)) else None
    read = [c for c in cells if c['state'] == 'read']
    head = max(read, key=lambda c: c['level']) if read else None
    try:
        tracked = sorted(_bluf().TRACKER_KEYS)
    except Exception:
        tracked = sorted(trackers)
    payload = {
        'success': True, 'version': MATRIX_VERSION, 'region': 'africa', 'built_at': _now().isoformat(),
        'headline': ({'pair': _name(head), 'level': head['level'], 'word': head['word'], 'kind': head['kind']}
                     if head else None),
        'pairs': cells,
        'kinds': KIND_LABELS,
        'lines': build_lines(cells, prev),
        'trackers_read': sorted(trackers), 'trackers_missing': sorted(missing or []),
        'stale_trackers': sorted(t for t, v in trackers.items() if v['freshness'] != 'live'),
        'coverage': {'tracked_countries': tracked,
                     'note': 'Countries without a rhetoric tracker are absent from this board, not quiet.'},
        'method': ('Each pair reads the rhetoric tracker that watches it (an actor\'s escalation level or a vector '
                   'level) and takes the highest, capped at that tracker\'s corroborated theatre level. Nothing here '
                   'is scanned separately. Unread and not-sensed pairs are gaps, never L0.'),
    }
    if read:
        redis_set(PREV_KEY, {c['id']: c['level'] for c in read})
    return payload


def filter_for_actor(payload, actor):
    a = CARD_ALIASES.get(actor, actor)
    pairs = [c for c in payload.get('pairs', []) if a in c['keys']]
    out = dict(payload)
    out['pairs'] = pairs
    out['actor'] = a
    read = [c for c in pairs if c['state'] == 'read']
    head = max(read, key=lambda c: c['level']) if read else None
    out['headline'] = ({'pair': _name(head), 'level': head['level'], 'word': head['word'], 'kind': head['kind']}
                       if head else None)
    out['lines'] = build_lines(pairs, {c['id']: c.get('previous_level') for c in pairs}) if pairs else []
    return out


# ----------------------------------------------------------------------------
# FLASK
# ----------------------------------------------------------------------------
def register_africa_actor_matrix(app):
    from flask import jsonify, request
    b = _bluf()

    def rset(k, v, ttl=7 * 86400):
        try:
            b._redis_set(k, v, ttl=ttl)
        except Exception:
            pass

    _mem = {'payload': None, 'at': 0}

    def current():
        if _mem['payload'] and time.time() - _mem['at'] < CACHE_SEC:
            return _mem['payload']
        cached = b._redis_get(CACHE_KEY)
        if isinstance(cached, dict) and time.time() - cached.get('_at', 0) < CACHE_SEC:
            _mem.update(payload=cached, at=cached['_at'])
            return cached
        payload = build_matrix(b._redis_get, rset)
        payload['_at'] = time.time()
        rset(CACHE_KEY, payload, ttl=CACHE_SEC * 4)
        _mem.update(payload=payload, at=time.time())
        return payload

    def api_matrix():
        try:
            data = current()
            actor = (request.args.get('actor') or '').strip().lower()
            return jsonify(filter_for_actor(data, actor) if actor else data)
        except Exception as e:
            return jsonify({'success': False, 'version': MATRIX_VERSION, 'state': 'unread',
                            'error': f'{type(e).__name__}: {str(e)[:200]}', 'pairs': []}), 200

    def api_debug():
        try:
            trackers, missing = read_trackers()
        except Exception as e:
            return jsonify({'error': f'{type(e).__name__}: {e}'}), 200
        rows = {}
        for th, t in trackers.items():
            used_a = {s[2] for p in PAIRS for s in p['sources'] if s[1] == th and s[0] == 'actor'}
            used_v = {s[2] for p in PAIRS for s in p['sources'] if s[1] == th and s[0] == 'vector'}
            rows[th] = {'theatre_level': t['threat'], 'freshness': t['freshness'],
                        'actors': t['actors'], 'vectors': t['vectors'],
                        'unused_actors': sorted(set(t['actors']) - used_a),
                        'unused_vectors': sorted(set(t['vectors']) - used_v),
                        'expected_but_absent': sorted((used_a - set(t['actors'])) | (used_v - set(t['vectors'])))}
        return jsonify({'version': MATRIX_VERSION, 'trackers': rows, 'missing': missing,
                        'pairs_by_source': {p['id']: [f'{k}:{th}:{sid}' for k, th, sid in p['sources']] for p in PAIRS}})

    app.add_url_rule('/api/africa/actor-matrix', 'africa_actor_matrix', api_matrix, methods=['GET'])
    app.add_url_rule('/api/africa/actor-matrix/debug', 'africa_actor_matrix_debug', api_debug, methods=['GET'])
    print(f"[Africa Matrix] ✅ /api/africa/actor-matrix (+ /debug) -- {len(PAIRS)} pairs, reader only")
