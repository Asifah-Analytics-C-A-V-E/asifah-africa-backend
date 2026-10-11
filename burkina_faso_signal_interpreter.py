"""
burkina_faso_signal_interpreter.py -- Asifah Analytics Africa Backend
v1.0.0 -- 11 October 2026

Analyst layer for rhetoric_tracker_burkina_faso (Tier-2 spoke node).

FIVE-FUNCTION CONTRACT, as canon:
    build_top_signals
    build_executive_summary
    build_so_what_factor
    score_commercial_axis            <- this node's drift-axis equivalent
    build_commercial_axis_top_signal

THE AXIS: three states, not four bands.
    capture / refusal / unread.
    The UAE interpreter's axis nets friction against lifeline and bands into
    four. Burkina's nets FOREIGN COMMERCIAL CAPTURE against STATE REFUSAL and
    reports three states, per Rachel's ruling of 11 Oct 2026. Both side-scores
    travel in the payload whatever the label says, because the both-hot case --
    Nordgold staying while Endeavour and IAMGOLD divest -- is the interesting
    one and a single word cannot carry it.

DEFECTS FIXED ON THE WAY IN (found in uae_signal_interpreter, 7 Oct 2026):
  1. THE DEAD CALM GUARD. build_alignment_drift_top_signal() there returns None
     for band 'US-anchored' -- a band that no longer exists, because the bands
     were renamed and the guard was not. Result: a completely calm UAE scan
     emits a top signal into the regional BLUF and the GPI every single cycle.
     Verified by execution. Here the calm guard names a state that is actually
     in the state list, and a test asserts it.
  2. DOCSTRING/IMPLEMENTATION DRIFT. That function's docstring describes a
     US-anchored -> Realigning ladder with id bri_inroad_<country> and returns
     dualtrack_axis_uae with lifeline/friction bands -- a completely different
     indicator. Here the docstring describes what the code does.
  3. DOUBLE DEFINITION. build_alignment_drift_top_signal and
     interpret_uae_signals are each defined twice in that file; the second
     silently wins. Nothing here is defined twice, and a test asserts it.

CHANNEL ASYMMETRY -- the honest caveat on this axis.
    The refusal channel is LOUDER than the capture channel, structurally.
    Traore announces nationalisations at podiums; Gulf gold moves through
    Dubai in quarterly investigative reporting, when it is reported at all.
    So a refusal-dominant reading is partly a real finding and partly an
    artefact of which channel publishes on a weekly cadence. The axis carries
    this caveat in every payload rather than letting an announcement-rich
    actor outscore a smuggling-route actor and calling the difference a
    discovery.

Estimative voice. Convergence, not prediction.
COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

from datetime import datetime, timezone

MODULE_VERSION = '1.0.0'

LEVEL_ORDER = ['low', 'normal', 'elevated', 'high', 'surge']
ESCALATORY = {'elevated', 'high', 'surge'}

VECTOR_NAMES = {
    'junta_consolidation': 'Junta Consolidation',
    'insurgent_contest':   'Insurgent Contest',
    'external_alignment':  'External Alignment',
    'commercial_capture':  'Commercial Capture',
}

VECTOR_MEMBERS = {
    'junta_consolidation': ('junta_traore', 'coup_counterplot'),
    'insurgent_contest':   ('jnim_burkina', 'isgs_burkina'),
    'external_alignment':  ('russia_axis_bf', 'aes_rupture'),
    'commercial_capture':  ('resource_sovereignty', 'gulf_gold_channel'),
}

ACTOR_PROSE_NAMES = {
    'junta_traore':         'the Traore / MPSR line',
    'coup_counterplot':     'the coup and counter-plot file',
    'jnim_burkina':         'JNIM',
    'isgs_burkina':         'ISGS and the inter-jihadist contest',
    'russia_axis_bf':       'the Russia axis',
    'aes_rupture':          'the AES and Western-rupture track',
    'resource_sovereignty': 'resource sovereignty',
    'gulf_gold_channel':    'the Gulf gold channel',
}

# ── THE THREE STATES. The calm guard below names one of THESE, which is the
#    whole fix for the UAE bug: a renamed state can no longer orphan the guard,
#    because the guard reads from this tuple and a test asserts membership.
AXIS_STATES = ('capture', 'refusal', 'unread')
AXIS_CALM_STATE = 'unread'

AXIS_META = {
    'capture': {'level': 3, 'color': '#f59e0b', 'priority': 12,
                'icon': '\U0001F4E5'},
    'refusal': {'level': 3, 'color': '#22c55e', 'priority': 12,
                'icon': '\U0001F6AB'},
    'unread':  {'level': 0, 'color': '#6b7280', 'priority': 4,
                'icon': '⬜'},
}

CAPTURE_ACTORS = ('gulf_gold_channel',)
REFUSAL_ACTORS = ('resource_sovereignty',)

CHANNEL_ASYMMETRY_NOTE = (
    'CHANNEL ASYMMETRY: refusal is a louder channel than capture. State '
    'nationalisations are announced; gold corridors are reported quarterly by '
    'investigators, if at all. A refusal-dominant reading is therefore part '
    'finding and part publication cadence, and the two scores are not '
    'like-for-like. Read the direction, distrust the margin.'
)

AXIS_DISCLAIMER = (
    'A CONVERGENCE read on commercial direction, not a prediction. refusal is '
    'NOT low capture: a quiet quarter and an active nationalisation both '
    'produce few acquisition headlines, and collapsing them into one low '
    'number is an unread zero with better manners.'
)

AXIS_LEADING_INDICATORS = [
    'SOPAMIB portfolio changes and further mine seizures',
    'Nordgold footprint against Western-operator divestment announcements',
    'Any LBMA Good Delivery application or accreditation',
    'Refinery throughput against the ~55-60 t/yr national production figure',
    'UAE import statistics against Burkinabe declared exports',
    'Rosatom build milestones after the Jan 2026 Vienna Convention ratification',
]

DEESCALATION_PATTERNS = [
    'talks', 'dialogue', 'negotiation', 'delegation', 'mediation',
    'ceasefire', 'agreement signed', 'reopens', 'resumes', 'released',
    'returns to', 'restores relations', 'lifts ban', 'lifts suspension',
]


# ════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════
def _rank(level):
    try:
        return LEVEL_ORDER.index(level)
    except ValueError:
        return 0


def _max_level(levels):
    return max(levels, key=_rank) if levels else 'low'


def _is_unvalidated(actor_summary):
    """True when this actor's keyword list has never matched real copy.

    An unvalidated actor reading 'low' is an UNREAD zero. The interpreter must
    never write prose asserting quiet on the strength of a list we never
    proved can match anything.
    """
    return (actor_summary or {}).get('validation', {}).get('status') == 'unvalidated'


def _has_deescalation(actor_summary):
    text = ' '.join((a.get('title') or '').lower()
                    for a in (actor_summary or {}).get('top_articles', []))
    return any(p in text for p in DEESCALATION_PATTERNS)


def _sources_from(actor_summary, n=3):
    return [{'title': a.get('title', ''), 'url': a.get('url', ''),
             'source': a.get('source', '')}
            for a in (actor_summary or {}).get('top_articles', [])[:n]]


# ════════════════════════════════════════════════════════════
# 1. THE COMMERCIAL AXIS
# ════════════════════════════════════════════════════════════
def score_commercial_axis(actor_summaries, tripwires_global):
    """Three-state read on commercial direction: capture / refusal / unread.

    Returns a dict carrying BOTH side-scores regardless of which word the
    label lands on, plus the channel-asymmetry caveat. Never raises.

    What this measures: whether foreign commercial control over Burkinabe
    resources is INCREASING (capture) or being DISPLACED by the state
    (refusal). What it does not measure: whether either is working.
    """
    asum = actor_summaries or {}
    cap = sum(_rank((asum.get(a) or {}).get('level', 'low')) for a in CAPTURE_ACTORS)
    ref = sum(_rank((asum.get(a) or {}).get('level', 'low')) for a in REFUSAL_ACTORS)

    tw_ids = {t.get('id') for t in (tripwires_global or []) if isinstance(t, dict)}
    drivers = []
    if 'mine_nationalisation' in tw_ids:
        ref += 2
        drivers.append('mine nationalisation tripwire (+2 refusal)')
    if 'refinery_accreditation' in tw_ids:
        ref += 1
        drivers.append('refinery accreditation tripwire (+1 refusal)')
    if 'foreign_operator_exit' in tw_ids:
        # Genuinely ambiguous: an operator leaving reads as refusal if it was
        # pushed and as capture if a non-Western buyer appears in the same
        # window. Counting it to BOTH stops it tipping the label alone.
        cap += 1
        ref += 1
        drivers.append('foreign operator exit tripwire (+1 BOTH -- ambiguous by construction)')

    both_hot = cap >= 2 and ref >= 2

    if cap == 0 and ref == 0:
        state = 'unread'
        reading = ('No commercial-direction reporting cleared the country gate '
                   'this cycle. This axis is UNREAD, not settled -- Burkina\'s '
                   'gold relationships do not go quiet, our feeds do.')
    elif ref > cap:
        state = 'refusal'
        reading = ('State displacement of foreign commercial control is '
                   'outpacing foreign acquisition. The refinery, SOPAMIB and '
                   'the self-funded expressway are the shape of it: a producer '
                   'building its own exit rather than selling access to one.')
    elif cap > ref:
        state = 'capture'
        reading = ('Foreign commercial positioning is outpacing state '
                   'displacement. The question this raises is WHOSE -- the Gulf '
                   'channel and a Chinese acquisition read identically on '
                   'volume and differently on everything that matters.')
    else:
        state = 'refusal' if ref else 'unread'
        reading = ('Capture and refusal are scoring level this cycle. The label '
                   'picks a side because it must; the scores below do not. '
                   'Read both.')

    meta = AXIS_META[state]
    return {
        'id': 'commercial_axis_burkina_faso',
        'country': 'burkina_faso',
        'flag': '\U0001F1E7\U0001F1EB',
        'state': state,
        'states_defined': list(AXIS_STATES),
        'capture_score': cap,
        'refusal_score': ref,
        'net': ref - cap,
        'both_hot': both_hot,
        'both_hot_note': (
            'Capture AND refusal are both live. This is the Nordgold-stays-'
            'while-Endeavour-divests case: a state expelling one foreign '
            'operator while another deepens. If this keeps firing it is the '
            'argument for a fourth state, and it is logged rather than '
            'papered over.') if both_hot else None,
        'score_drivers': drivers,
        'reading': reading,
        'channel_asymmetry': CHANNEL_ASYMMETRY_NOTE,
        'disclaimer': AXIS_DISCLAIMER,
        'leading_indicators': list(AXIS_LEADING_INDICATORS),
        'level': meta['level'],
        'priority': meta['priority'],
        'color': meta['color'],
        'icon': meta['icon'],
        'scored_at': datetime.now(timezone.utc).isoformat(),
    }


def build_commercial_axis_top_signal(axis):
    """Canonical top_signal for the axis -> regional BLUF / GPI.

    Returns None when the axis is at its CALM state, so a quiet cycle does not
    broadcast. The calm state is read from AXIS_CALM_STATE, which is asserted
    to be a member of AXIS_STATES -- that assertion is the fix for the UAE
    guard, which still tests for a band name that was renamed out of existence
    and therefore never returns None at all.
    """
    if not axis:
        return None
    state = axis.get('state')
    if state in (None, AXIS_CALM_STATE):
        return None

    verb = ('state displacing foreign control' if state == 'refusal'
            else 'foreign commercial positioning increasing')
    return {
        'priority': axis.get('priority', 12),
        'category': 'commercial_axis',
        'type': 'commercial_axis',
        'theatre': 'burkina_faso',
        'pressure_type': 'economic',
        'level': axis.get('level', 3),
        'icon': axis.get('icon', '⛏️'),
        'color': axis.get('color', '#f59e0b'),
        'short_text': ('%s BURKINA FASO: commercial axis %s -- %s'
                       % (axis.get('flag', ''), state.upper(), verb)),
        'long_text': (axis.get('reading', '') + ' '
                      + (axis.get('both_hot_note') + ' ' if axis.get('both_hot') else '')
                      + axis.get('channel_asymmetry', '') + ' '
                      + axis.get('disclaimer', ''))[:900],
    }


# ════════════════════════════════════════════════════════════
# 2. TOP SIGNALS
# ════════════════════════════════════════════════════════════
_TRIPWIRE_PROSE = {
    'regime_change_event': (
        'An ACTUAL change of regime, distinct from the announced foiled plots '
        'that run at a steady tempo. Burkina has had two successful coups in '
        '2022 alone; the base rate here is not low.'),
    'capital_threatened': (
        'Pressure reaching Ouagadougou is the Bamako-blockade pattern arriving '
        'at the Burkinabe capital. Burkina\'s siege has so far been '
        'DISTRIBUTED -- dozens of encircled towns rather than one strangled '
        'centre -- and this would be that changing shape.'),
    'mass_casualty_event': (
        'Solhan (June 2021, 160+), Karma (April 2023, 100+) and Barsalogho '
        '(August 2024, ~200+) are the precedent class. Mass-casualty events '
        'against civilians have historically preceded reservist mobilisation '
        'waves and fresh dissolution decrees.'),
    'siege_breaks': (
        'A besieged town falling puts a non-moveable population in play. '
        'Roughly 800,000 people live inside encirclements they cannot leave; '
        'Djibo has been blockaded since February 2022 and is resupplied by '
        'air. The humanitarian dial and the territorial dial converge here.'),
    'mine_nationalisation': (
        'A REFUSAL-side event and the clearest one the axis reads. SOPAMIB '
        'took Boungou and Wahgnion in 2024; the 2024 mining code raised the '
        'free-carried state interest. Each seizure moves the axis and reduces '
        'the pool of operators willing to be next.'),
    'foreign_operator_exit': (
        'Ambiguous BY CONSTRUCTION, and the axis counts it to both sides for '
        'that reason. An operator leaving reads as refusal if it was pushed '
        'and as capture if a non-Western buyer surfaces in the same window. '
        'Watch for the buyer before reading the direction.'),
    'refinery_accreditation': (
        'A standing WATCH item expected absent for years. Burkina\'s new '
        'refinery holds no LBMA Good Delivery accreditation -- only Rand '
        'Refinery in South Africa does in all of Africa -- and the standard '
        'needs ~$20m net worth, several years of operation and a '
        'responsible-sourcing audit in a country where JNIM taxes artisanal '
        'sites. Accreditation would change who is able to buy the bars.'),
    'diplomatic_rupture': (
        'Burkina broke off relations with France in June 2026; TV5Monde was '
        'banned in May. The rupture track has a direction and a tempo, and '
        'each break narrows the set of capitals that can carry a message.'),
    'aes_fracture': (
        'The Alliance des Etats du Sahel coming apart would re-price all three '
        'member trackers at once. Burkina, Mali and Niger left ECOWAS '
        'together; a defection would be the largest single realignment event '
        'available in this theatre.'),
    'corridor_closure': (
        'Landlocked: gold out and fuel, fertiliser and food in all cross four '
        'coastal neighbours -- Abidjan, Tema, Lome, Cotonou. Burkina left '
        'ECOWAS, the bloc governing those corridors. A closure is an economic '
        'event with a humanitarian tail measured in weeks.'),
}


def _actor_long_text(actor_id, summary):
    base = (summary or {}).get('description', '')
    lvl = (summary or {}).get('level', 'low')
    extra = ''
    if _has_deescalation(summary):
        extra = (' De-escalatory vocabulary is present in the same window -- '
                 'read the tempo against it rather than through it.')
    if _is_unvalidated(summary):
        extra += (' CAUTION: this actor\'s keyword list has never matched real '
                  'wire copy in validation. Treat its reading as unproven '
                  'instrumentation, not as a measurement.')
    return ('%s Currently at %s.%s' % (base, lvl, extra))


def build_top_signals(actor_summaries, tripwires_global, commercial_axis,
                      wheel_presence, humanitarian_context, amplifiers):
    """Canonical top_signals[] for the BF tracker. Sorted, capped at 12."""
    signals = []
    asum = actor_summaries or {}

    # ── 1. Tripwires, highest priority ──
    seen = set()
    for tw in (tripwires_global or []):
        tid = tw.get('id')
        if tid in seen:
            continue
        seen.add(tid)
        sev = tw.get('severity', 'high')
        signals.append({
            'priority': 14, 'category': 'tripwire', 'type': 'tripwire',
            'theatre': 'burkina_faso', 'level': sev,
            'icon': '\U0001F6A8', 'color': '#dc2626',
            'short_text': '\U0001F1E7\U0001F1EB Tripwire: %s' % str(tid).replace('_', ' '),
            'long_text': _TRIPWIRE_PROSE.get(
                tid, 'Low-base-rate, high-impact pattern fired this scan.'),
            'actor': tw.get('actor'),
            'sources': _sources_from(asum.get(tw.get('actor')), 1),
        })

    # ── 2. The off-wheel flag. This is the signal the architecture gained. ──
    wp = wheel_presence or {}
    gulf = wp.get('gulf') or {}
    if gulf.get('active'):
        signals.append({
            'priority': 13, 'category': 'off_wheel_actor',
            'type': 'off_wheel_actor', 'theatre': 'burkina_faso',
            'pressure_type': 'economic', 'level': 'elevated',
            'icon': '\U0001F9ED', 'color': '#f59e0b',
            'short_text': ('\U0001F1E6\U0001F1EA BURKINA FASO: Gulf channel '
                           'active -- dominant actor is OFF-WHEEL'),
            'long_text': (
                'The dominant external commercial counterparty for Burkinabe '
                'gold is the Gulf, and the Gulf is not a wheel this platform '
                'runs. Roughly 32% of Burkinabe gold was sold to the UAE in '
                '2024. This signal exists so the regional BLUF does NOT '
                'attribute the movement to Russia or China by elimination: '
                'absence of our actors is not presence of our actors.'),
        })

    # ── 3. Commercial axis (the tracker also prepends this; dedup upstream) ──
    axis_sig = build_commercial_axis_top_signal(commercial_axis)
    if axis_sig:
        signals.append(axis_sig)

    # ── 4. Per-actor at elevated+, skipping actors a tripwire already covers ──
    for aid, s in asum.items():
        lvl = s.get('level', 'low')
        if lvl not in ESCALATORY:
            continue
        covered = [t.get('severity') for t in (tripwires_global or [])
                   if t.get('actor') == aid]
        if covered and _rank(_max_level(covered)) >= _rank(lvl):
            continue
        signals.append({
            'priority': 8, 'category': 'actor_signal', 'type': 'actor_signal',
            'theatre': 'burkina_faso', 'level': lvl,
            'icon': s.get('icon', '\U0001F4CA'), 'color': s.get('color', '#6b7280'),
            'short_text': ('\U0001F1E7\U0001F1EB %s at %s (%d signals)'
                           % (ACTOR_PROSE_NAMES.get(aid, s.get('name', aid)),
                              lvl.upper(), s.get('article_count', 0))),
            'long_text': _actor_long_text(aid, s),
            'actor': aid,
            'sources': _sources_from(s),
        })

    # ── 5. Unvalidated instrumentation. An untested sensor reading low is a
    #       fact about US, and the reader is entitled to know it. ──
    unval = [aid for aid, s in asum.items() if _is_unvalidated(s)]
    if unval:
        signals.append({
            'priority': 6, 'category': 'instrumentation_gap',
            'type': 'instrumentation_gap', 'theatre': 'burkina_faso',
            'level': 'normal', 'icon': '⚠️', 'color': '#6b7280',
            'short_text': ('\U0001F1E7\U0001F1EB %d actor(s) running unvalidated '
                           'keyword lists' % len(unval)),
            'long_text': (
                'These actors have never matched real wire copy in validation: '
                '%s. Their current reading is unproven instrumentation rather '
                'than a measurement, and their silence carries no information. '
                'Shown because a tested quiet and an untested quiet look '
                'identical on a gauge and mean opposite things.'
                % ', '.join(ACTOR_PROSE_NAMES.get(a, a) for a in unval)),
        })

    # ── 6. Humanitarian convergence -- the siege ledger under the attack counts ──
    hc = humanitarian_context or {}
    if hc.get('available') and hc.get('besieged'):
        ins = (asum.get('jnim_burkina') or {}).get('level', 'low')
        if ins in ESCALATORY:
            signals.append({
                'priority': 11, 'category': 'humanitarian_convergence',
                'type': 'humanitarian_convergence', 'theatre': 'burkina_faso',
                'pressure_type': 'humanitarian', 'level': 'high',
                'icon': '\U0001FA78', 'color': '#ef4444',
                'short_text': ('\U0001F1E7\U0001F1EB Insurgent tempo %s against '
                               '~%s besieged' % (ins.upper(),
                                                 '{:,}'.format(hc['besieged']))),
                'long_text': (
                    'Insurgent contest is running at %s while roughly %s people '
                    'live inside encirclements they cannot leave. The besieged '
                    'figure is the only dial on the humanitarian page measuring '
                    'a population to whom movement is UNAVAILABLE, which is why '
                    'rising attack tempo and a static siege count are not '
                    'independent readings.'
                    % (ins, '{:,}'.format(hc['besieged']))),
            })

    # ── 7. Sibling wheel fingerprints, absence-honest ──
    for label, data in (amplifiers or {}).items():
        if not isinstance(data, dict):
            continue
        signals.append({
            'priority': 5, 'category': 'crosstheater', 'type': 'crosstheater',
            'theatre': 'burkina_faso', 'level': 'normal',
            'icon': '\U0001F6DE', 'color': '#a78bfa',
            'short_text': '\U0001F1E7\U0001F1EB Sibling fingerprint live: %s'
                          % label.replace('_fingerprint', ''),
            'long_text': ('A sibling tracker fingerprint (%s) is live in shared '
                          'Redis. For a Tier-2 spoke this is context, not '
                          'causation -- Burkina moving with Mali is the AES '
                          'baseline, not a discovery.' % label),
        })

    signals.sort(key=lambda s: -s.get('priority', 0))
    return signals[:12]


# ════════════════════════════════════════════════════════════
# 3. EXECUTIVE SUMMARY
# ════════════════════════════════════════════════════════════
def build_executive_summary(actor_summaries, vector_scores, vector_levels,
                            tripwires_global, commercial_axis, wheel_presence):
    asum = actor_summaries or {}
    lv = vector_levels or {}
    parts = []

    tw_ids = [t.get('id') for t in (tripwires_global or []) if isinstance(t, dict)]
    if tw_ids:
        parts.append('Tripwires this scan: %s.'
                     % ', '.join(str(t).replace('_', ' ') for t in tw_ids[:3]))

    hot = [VECTOR_NAMES.get(v, v) for v, l in lv.items() if l in ESCALATORY]
    if hot:
        drivers = [ACTOR_PROSE_NAMES.get(a, a) for a, d in asum.items()
                   if d.get('level') in ('high', 'surge')]
        parts.append('Active vectors: %s%s'
                     % (', '.join(hot).lower(),
                        ' -- driven by %s.' % ', '.join(drivers[:3]) if drivers else '.'))
    else:
        parts.append('All four vectors at baseline this scan.')

    ca = commercial_axis or {}
    if ca.get('state') and ca['state'] != 'unread':
        parts.append('Commercial axis reads %s (capture %s / refusal %s).'
                     % (ca['state'].upper(), ca.get('capture_score'),
                        ca.get('refusal_score')))
        if ca.get('both_hot'):
            parts.append('Both sides are live simultaneously.')
    else:
        parts.append('Commercial axis UNREAD this cycle.')

    wp = wheel_presence or {}
    if (wp.get('gulf') or {}).get('active'):
        parts.append('The dominant commercial actor is the Gulf, which is '
                     'off-wheel -- do not attribute this to Russia by elimination.')
    else:
        parts.append('Tier-2 spoke on Russia and China; no off-wheel dominant '
                     'actor firing this cycle.')

    unval = [a for a, s in asum.items() if _is_unvalidated(s)]
    if unval:
        parts.append('%d actor(s) running unvalidated keyword lists -- their '
                     'quiet carries no information.' % len(unval))

    parts.append('Convergence read, not prediction.')
    return ' '.join(parts)


# ════════════════════════════════════════════════════════════
# 4. SO-WHAT
# ════════════════════════════════════════════════════════════
_CHAINS = {
    'junta_consolidation': (
        'Junta consolidation at {lvl}. What it means: party dissolutions, '
        'association bans and mass reservist mobilisation measure how much of '
        'civil society the state is ABSORBING -- not how secure it is. In 2026 '
        'alone Burkina dissolved all political parties (January), 118 then '
        '200+ associations (April-May), banned a French broadcaster and '
        'arrested a preacher over a religious-practice law. An announced '
        'foiled plot is evidence about the state\'s narrative as much as about '
        'a plot. Who feels it: Burkinabe civil society, diaspora opposition, '
        'any external actor needing a domestic interlocutor. Confirmation '
        'gauges: decree tempo, arrest waves, whether dissolutions reach '
        'religious bodies.', 0.92),
    'insurgent_contest': (
        'Insurgent contest at {lvl}. What it means: Burkina\'s is a '
        'DISTRIBUTED siege -- dozens of simultaneous encirclements, not one '
        'strangled capital, which is what separates it from Mali. Around 40% '
        'of territory sits outside effective government control and ~800,000 '
        'people live in towns they cannot leave. Who feels it: the besieged '
        'populations first, then the coastal states the Est-region expansion '
        'runs toward. Confirmation gauges: named-locality specificity in '
        'claims, school-closure counts as a control proxy, whether any '
        'besieged town changes hands.', 0.95),
    'external_alignment': (
        'External alignment at {lvl}. What it means: the Paris break (June '
        '2026) and the AES bloc are the loud half. The Rosatom chain is the '
        'quiet half -- roadmap 2023, construction agreement October 2024, '
        'comprehensive agreement at SPIEF June 2025, and the Transitional '
        'Assembly ratifying the Vienna Convention on nuclear liability in '
        'January 2026, which is the LEGAL PRECONDITION for a build and reads '
        'as parliamentary housekeeping unless you know the chain. Who feels '
        'it: French and US missions, Rosatom\'s African pipeline, ECOWAS. '
        'Confirmation gauges: Rosatom milestones, Africa Corps footprint '
        'reporting, further expulsions.', 0.90),
    'commercial_capture': (
        'Commercial capture at {lvl}. What it means: Burkina built a 164 t/yr '
        'gold refinery in a country producing 55-60 t/yr, and it holds no LBMA '
        'accreditation -- so the bars must go to buyers who do not require '
        'Good Delivery: the UAE, Russia, China, Turkiye, India. The capacity '
        'gap says it was built for Mali\'s and Niger\'s gold too. Who feels '
        'it: the London market, which loses visibility of the flow; Dubai, '
        'which already takes ~32%; the AES as a settlement bloc. Confirmation '
        'gauges: UAE import statistics against Burkinabe declared exports, any '
        'accreditation application, refinery throughput.', 0.93),
}


def build_so_what_factor(actor_summaries, vector_levels, tripwires_global,
                         commercial_axis, wheel_presence, humanitarian_context):
    """Implication chains, highest weight first. Estimative voice."""
    bullets = []
    asum = actor_summaries or {}
    lv = vector_levels or {}

    def drivers(vec):
        names = [ACTOR_PROSE_NAMES.get(a, a) for a in VECTOR_MEMBERS.get(vec, ())
                 if (asum.get(a) or {}).get('level') in ESCALATORY]
        return (' Driving this scan: %s.' % ', '.join(names)) if names else ''

    for vec, (txt, w) in _CHAINS.items():
        if lv.get(vec) in ESCALATORY:
            bullets.append({'weight': w,
                            'bullet': txt.format(lvl=str(lv[vec]).upper()) + drivers(vec)})

    for tw in (tripwires_global or [])[:2]:
        tid = tw.get('id')
        if tid:
            bullets.append({'weight': 0.98, 'bullet':
                            'Tripwire -- %s: %s' % (str(tid).replace('_', ' '),
                                                    _TRIPWIRE_PROSE.get(tid, ''))})

    ca = commercial_axis or {}
    if ca.get('both_hot'):
        bullets.append({'weight': 0.96,
                        'bullet': 'Commercial axis BOTH-HOT: ' + (ca.get('both_hot_note') or '')})
    elif ca.get('state') and ca['state'] != 'unread':
        bullets.append({'weight': 0.88,
                        'bullet': ('Commercial axis %s. %s %s'
                                   % (ca['state'].upper(), ca.get('reading', ''),
                                      ca.get('channel_asymmetry', '')))})

    if (wheel_presence or {}).get('gulf', {}).get('active'):
        bullets.append({'weight': 0.91, 'bullet': (
            'OFF-WHEEL DOMINANT ACTOR. The Gulf is the leading commercial '
            'counterparty here and this platform runs no Gulf hub. The '
            'architectural risk is attribution by elimination -- reading '
            'Burkina\'s commercial movement as a Russia story because Russia '
            'is the only wheel available to read it with. Six Africa targets '
            '(Sudan, Mali, Burkina, Niger, Chad, Libya) converge on this same '
            'unbuilt hub.')})

    unval = [a for a, s in asum.items() if _is_unvalidated(s)]
    if unval:
        bullets.append({'weight': 0.55, 'bullet': (
            'INSTRUMENTATION: %s running unvalidated keyword list(s). Validation '
            'on 11 Oct 2026 matched them against zero real headlines, so their '
            'current reading is untested rather than low. A tested quiet and an '
            'untested quiet render identically and mean opposite things.'
            % ', '.join(ACTOR_PROSE_NAMES.get(a, a) for a in unval))})

    if not bullets:
        bullets.append({'weight': 0.3, 'bullet': (
            'All four vectors at baseline this scan. Baseline for a distributed '
            'siege still means ~800,000 people inside encirclements and ~40% of '
            'territory contested. A quiet scan is a quiet FEED, not a quiet '
            'country.')})

    bullets.sort(key=lambda b: -b['weight'])
    return bullets[:6]


# ════════════════════════════════════════════════════════════
# CONVENIENCE WRAPPER
# ════════════════════════════════════════════════════════════
def interpret_burkina_faso_signals(scan_data):
    """Accept a full scan payload, return the four derived analytical fields."""
    asum = scan_data.get('actor_summaries', {}) or {}
    tw = scan_data.get('tripwires_global', []) or []
    axis = score_commercial_axis(asum, tw)
    wp = scan_data.get('wheel_presence', {}) or {}
    hc = scan_data.get('humanitarian_context', {}) or {}
    amps = scan_data.get('crosstheater_amplifiers', {}) or {}
    return {
        'top_signals': build_top_signals(asum, tw, axis, wp, hc, amps),
        'executive_summary': build_executive_summary(
            asum, scan_data.get('vector_scores', {}) or {},
            scan_data.get('vector_levels', {}) or {}, tw, axis, wp),
        'so_what': build_so_what_factor(
            asum, scan_data.get('vector_levels', {}) or {}, tw, axis, wp, hc),
        'commercial_axis': axis,
    }


# Structural guard: the UAE interpreter's calm guard tests for a band name that
# no longer exists, so a calm scan broadcasts every cycle. This assertion makes
# the same mistake impossible here -- it fails at import, not in production.
assert AXIS_CALM_STATE in AXIS_STATES, (
    'AXIS_CALM_STATE must name a real state, or the calm guard in '
    'build_commercial_axis_top_signal can never return None.')

print('[BF Signal Interpreter] module loaded -- v%s' % MODULE_VERSION)
