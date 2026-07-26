"""
mali_signal_interpreter.py
Asifah Analytics -- Africa Backend Module
v1.0.0 -- July 25, 2026

Signal interpretation for the Mali Rhetoric & Pressure Tracker.

THE ORGANISING QUESTION IS NOT "how bad is Mali."
It is: IS RUSSIA GAINING OR LOSING GROUND HERE, and what would that mean?

Mali is the largest Russian deployment in Africa alongside CAR and Libya, and
it is the one taking losses. That makes it the test case for whether the Africa
Corps model works at all -- which is why this theatre carries weight well beyond
its own borders. The trajectory read leads every assessment here; the kinetic
picture is context for it.

WHAT RUSSIA IS SELLING (the frame every read sits inside):
The product is REGIME SURVIVAL, not counterterrorism -- insulation for a junta
against its own army and its own population. Payment is resource concessions
converting to cash outside the dollar system, which keeps the operation off the
Russian budget. Commodities are the payment MECHANISM, not the objective.
So the trajectory watches three things at once:
    the battlefield (is the force losing?)
    the payment stream (are the concessions still flowing?)
    the dependency (does the junta still need them?)
Hedging is the leading indicator, because a client shopping for alternatives is
questioning the product before the product visibly fails.

THE CONVERGENCE LADDER (why this matters beyond Mali):
    spoke   Russia contracting in Mali        -> a coda on the country page
    wheel   contracting in Mali AND Sudan AND
            CAR AND Libya                     -> a regional question: WHY?
    global  ...AND Ukraine                    -> the pattern earns a NAME

This interpreter only speaks at the first altitude. It emits the direction with
its evidence so the BLUF and the GPI can do the aggregating -- deliberately, so
one country's tracker can never declare a global trend on its own.

CLAIM DISCIPLINE:
Much of this corpus is FLA/JNIM claims amplified through partisan OSINT.
Trajectory prose NAMES its confidence level rather than burying it, and a
claim-sourced move is described as reported, not as fact.

Three analytical outputs (Yemen contract): so_what / red_lines / historical,
plus build_top_signals() for the Africa BLUF and GPI.

DOCTRINE: estimative voice only. No probabilities, no dates, no "will".

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

from datetime import datetime, timezone

MALI_FLAG = '\U0001F1F2\U0001F1F1'


# ============================================================
# RED LINES
# ============================================================
# EVENT-gated lines require their own phrase in the corpus; a hot vector alone
# is APPROACHING, never BREACHED. (Sudan taught this: "El Obeid Falls" fired on
# an unrelated casualty report because it keyed on the kinetic vector max.)
RED_LINES = [
    {
        'id': 'bamako_threatened',
        'label': 'Bamako Directly Threatened',
        'detail': 'Attacks reaching the capital or its immediate approaches -- '
                  'Kati, Senou, Kenieroba -- rather than the northern theatre',
        'severity': 3, 'color': '#dc2626', 'icon': '\U0001F6A8',
        'category': 'kinetic_trigger', 'vectors': ['kinetic'],
        'event_keywords': ['bamako falls', 'chute de bamako', 'attack on bamako',
                           'kenieroba', 'kati attacked', 'senou attacked'],
        'source': 'Mali 2012 ended with a coup in Bamako driven by battlefield '
                  'failure in the north; proximity to the capital changes the '
                  'regime-survival calculus, not just the military one',
    },
    {
        'id': 'blockade_tightens',
        'label': 'Fuel Blockade Tightens to Exhaustion',
        'detail': 'Bamako fuel supply moving from scarce to exhausted -- the '
                  'economic siege reaching a threshold the junta cannot absorb',
        'severity': 3, 'color': '#dc2626', 'icon': '\u26D4',
        'category': 'economic_trigger', 'vectors': ['blockade'],
        'event_keywords': ['bamako fuel exhausted', 'bamako cut off',
                           'capital besieged mali', 'bamako encircled'],
        'source': 'The blockade is Mali\'s signature mechanism: an insurgency '
                  'attacking the state\'s economic lifeline rather than its '
                  'forces. Sieges of capitals have historically preceded '
                  'political rupture more reliably than battlefield losses',
    },
    {
        'id': 'territory_lost',
        'label': 'Kidal-Class Territory Loss',
        'detail': 'A regional capital or last-standing garrison changing hands, '
                  'as Kidal did in April 2026',
        'severity': 3, 'color': '#dc2626', 'icon': '\U0001F5FA\uFE0F',
        'category': 'kinetic_trigger', 'vectors': ['kinetic'],
        'event_keywords': ['kidal falls', 'kidal seized', 'anefis seized',
                           'aguelhok seized', 'gao falls', 'lost control of'],
        'source': 'Kidal fell in April 2026 alongside the killing of the defence '
                  'minister; the pattern is garrison isolation followed by '
                  'withdrawal, not contested defence',
    },
    {
        'id': 'africa_corps_withdrawal',
        'label': 'Africa Corps Drawdown or Withdrawal',
        'detail': 'Russian force reduction, redeployment, or exit -- the hub '
                  'deciding the position is not worth holding',
        'severity': 3, 'color': '#dc2626', 'icon': '\u2708\uFE0F',
        'category': 'trajectory_trigger', 'vectors': ['kinetic'],
        'event_keywords': ['russia withdraws', 'africa corps withdraws',
                           'drawdown', 'retrait russe', 'pulled back',
                           'russia reduces presence'],
        'source': 'Withdrawal is the strongest single contraction signal '
                  'available: it is the hub\'s own judgement about the position, '
                  'not an adversary\'s claim about it',
    },
    {
        'id': 'junta_hedging_confirmed',
        'label': 'Junta Hedging Confirmed -- Dependency Loosening',
        'detail': 'Bamako signing with an alternative supplier, or a delivery '
                  'arriving from one. The client questioning the product',
        'severity': 2, 'color': '#ef4444', 'icon': '\u2696\uFE0F',
        'category': 'trajectory_trigger', 'vectors': ['hedging'],
        'event_keywords': ['mali turkish drones delivered', 'bayraktar delivered mali',
                           'mali signs turkey', 'mali uae deal',
                           'mali new security partner', 'livraison drones turcs'],
        'source': 'Hedging leads the visible failure. A regime whose survival '
                  'depends on one patron does not shop casually -- when it does, '
                  'it is pricing the patron\'s reliability',
    },
    {
        'id': 'insurgent_alliance_hardens',
        'label': 'FLA-JNIM Alliance Hardens',
        'detail': 'Secular Tuareg separatists and an al-Qaeda affiliate moving '
                  'from coordinated timing to unified command',
        'severity': 3, 'color': '#dc2626', 'icon': '\U0001F91D',
        'category': 'insurgency_trigger', 'vectors': ['insurgent_convergence'],
        'event_keywords': ['fla jnim joint offensive', 'unified insurgent command mali',
                           'coalition azawad jnim'],
        'source': 'These are ideologically incompatible movements cooperating '
                  'against a common enemy. Historically such coalitions are '
                  'brittle -- which is why hardening, rather than mere '
                  'coordination, would be the material change',
    },
    {
        'id': 'aes_fracture',
        'label': 'AES Bloc Fracture',
        'detail': 'Mali, Niger or Burkina Faso breaking from the confederation, '
                  'or open dispute between them',
        'severity': 2, 'color': '#ef4444', 'icon': '\U0001F494',
        'category': 'bloc_trigger', 'vectors': ['aes_cohesion'],
        'event_keywords': ['aes collapse', 'mali leaves aes', 'aes dissolved',
                           'aes rift', 'dissolution aes'],
        'source': 'The AES is the political architecture that made simultaneous '
                  'Western expulsion possible; its cohesion is a precondition '
                  'for the Russian model across all three states',
    },
    {
        'id': 'libya_corridor_severed',
        'label': 'Libya Logistics Corridor Severed',
        'detail': 'Interruption of the Benghazi -> Maaten al-Sarra -> Sahel spine',
        'severity': 3, 'color': '#dc2626', 'icon': '\U0001F6E3\uFE0F',
        'category': 'logistics_trigger', 'vectors': ['libya_corridor'],
        'event_keywords': ['libya sahel corridor severed', 'maaten al-sarra strike'],
        'source': 'The SAME corridor supplies Russian operations in Sudan, '
                  'through the same Haftar node. Severing it is not a Mali '
                  'event -- it is a continental sustainment event',
    },
]


# ============================================================
# HISTORICAL ANALOGS
# ============================================================
HISTORICAL_PATTERNS = [
    {
        'id': 'mali_2012',
        'label': '2012 Northern Collapse and the Bamako Coup',
        'signals': ['kinetic', 'insurgent_convergence'],
        'outcome': 'A Tuareg separatist rising, joined opportunistically by '
                   'jihadist groups, collapsed the northern front. Junior '
                   'officers then overthrew the government in Bamako, blaming '
                   'battlefield failure. The separatists were subsequently '
                   'sidelined by their jihadist partners.',
        'lesson': 'Battlefield failure in the north has historically produced '
                  'political rupture in the SOUTH. And the separatist-jihadist '
                  'partnership of that period did not hold -- a precedent for '
                  'reading the current FLA-JNIM coordination as brittle until '
                  'proven otherwise.',
    },
    {
        'id': 'afghanistan_2021',
        'label': '2021 Afghan Security-Force Collapse',
        'signals': ['kinetic', 'blockade'],
        'outcome': 'A foreign-backed force that appeared to hold on paper '
                   'dissolved rapidly once external support and confidence '
                   'withdrew; garrison isolation preceded collapse by months.',
        'lesson': 'The observable precursor was garrison isolation and supply '
                  'interdiction, not defeat in open battle. Mali\'s northern '
                  'garrisons and the Bamako fuel blockade are the same class '
                  'of indicator.',
    },
    {
        'id': 'niger_2023',
        'label': '2023 Niger Coup and Western Expulsion',
        'signals': ['hedging', 'aes_cohesion'],
        'outcome': 'A coup produced expulsion of French and later US forces, '
                   'and accession to the AES bloc; Russian security cooperation '
                   'followed rather than preceded the realignment.',
        'lesson': 'Realignment in this region has followed regime change rather '
                  'than causing it. Watching the junta\'s internal stability is '
                  'therefore a leading indicator for the external alignment.',
    },
    {
        'id': 'car_model',
        'label': 'The CAR Model (2018-present)',
        'signals': ['hedging'],
        'outcome': 'Presidential-guard provision plus mining concessions '
                   'produced the deepest and most durable Russian penetration '
                   'on the continent -- the template Mali was expected to follow.',
        'lesson': 'The model works where the regime is weak enough to need it '
                  'and the concessions are rich enough to fund it. Mali tests '
                  'whether it also works where an insurgency can actually '
                  'contest the ground.',
    },
    {
        'id': 'tinzaouaten_2024',
        'label': 'July 2024 Tinzaouaten Ambush',
        'signals': ['kinetic', 'insurgent_convergence'],
        'outcome': 'Tuareg fighters and JNIM ambushed a joint FAMa-Wagner column '
                   'near the Algerian border, inflicting the heaviest single-'
                   'engagement Russian losses recorded in Africa.',
        'lesson': 'The first demonstration that this force can be defeated '
                  'tactically. The April 2026 fall of Kidal and the 2026 '
                  'helicopter losses are consistent with that pattern '
                  'continuing rather than being anomalous.',
    },
    {
        'id': 'atrocity_recruitment_loop',
        'label': 'The Atrocity-Recruitment Loop (Moura 2022 onward)',
        'signals': ['kinetic'],
        'outcome': 'Mass-casualty operations against civilian populations -- '
                   'Moura being the documented case -- correlated with '
                   'expanded insurgent recruitment rather than suppression.',
        'lesson': 'Security has deteriorated in every country hosting these '
                  'forces. The mechanism is self-defeating: atrocities drive '
                  'recruitment, which requires more force, which produces more '
                  'atrocities. Escalating operational tempo is therefore NOT '
                  'evidence of the model working.',
    },
]


# ============================================================
# RED LINE SCORING
# ============================================================
def _rl_public(rl):
    return {
        'id': rl['id'], 'label': rl['label'], 'detail': rl['detail'],
        'severity': rl['severity'], 'color': rl['color'], 'icon': rl['icon'],
        'category': rl['category'], 'source': rl['source'],
        'gate': 'event' if rl.get('event_keywords') else 'condition',
    }


def _score_red_lines(scan_data):
    """Event-gated where the line names a specific occurrence."""
    vectors = scan_data.get('vector_levels', {}) or {}
    matched = set(scan_data.get('matched_phrases', []) or [])
    triggered = []

    for rl in RED_LINES:
        rl_max = max((vectors.get(v, 0) for v in rl.get('vectors', [])), default=0)
        ev = rl.get('event_keywords')
        if ev:
            fired = [k for k in ev if k in matched]
            if fired:
                status, trig = 'BREACHED', 'observed: %s' % fired[0]
            elif rl_max >= 4:
                status = 'APPROACHING'
                trig = ('%s vector at L%d, but the named event is not present in '
                        'the corpus this cycle' % (rl['category'], rl_max))
            elif rl_max == 3:
                status, trig = 'APPROACHING', f"{rl['category']} vector at L{rl_max}"
            else:
                status, trig = 'QUIET', ''
        else:
            status = 'BREACHED' if rl_max >= 4 else ('APPROACHING' if rl_max == 3 else 'QUIET')
            trig = f"{rl['category']} vector at L{rl_max}" if rl_max else ''
        triggered.append({**_rl_public(rl), 'status': status, 'trigger': trig})
    return triggered


def _match_historical(scan_data):
    vectors = scan_data.get('vector_levels', {}) or {}
    active = {v for v, lvl in vectors.items() if lvl >= 3}
    if not active:
        return []
    out = []
    for pat in HISTORICAL_PATTERNS:
        ps = set(pat['signals'])
        inter, union = active & ps, active | ps
        if union and inter:
            out.append({
                'id': pat['id'], 'label': pat['label'],
                'similarity': round(len(inter) / len(union), 2),
                'shared_signals': sorted(inter),
                'outcome': pat['outcome'], 'lesson': pat['lesson'],
            })
    out.sort(key=lambda m: m['similarity'], reverse=True)
    return out[:3]


# ============================================================
# TRAJECTORY PROSE  -- the headline read for this theatre
# ============================================================
_CLASS_PROSE = {
    'territory_lost':       'territory changing hands',
    'materiel_loss':        'materiel losses',
    'casualties':           'personnel casualties',
    'withdrawal':           'force withdrawal or drawdown',
    'client_hedging':       'the client shopping for alternatives',
    'agreement_lapsed':     'an agreement lapsing unrenewed',
    'expulsion':            'expulsion',
    'partner_defection':    'a local partner defecting',
    'agreement_signed':     'a new agreement signed',
    'new_basing':           'new basing',
    'rival_expelled':       'a rival being expelled',
    'concession_granted':   'a resource concession granted',
    'dependency_deepening': 'deepening dependency',
}

_CONFIDENCE_PROSE = {
    'multi_source':      'Corroborated across independent outlets.',
    'confirmed_partial': 'Partially corroborated -- at least one independent outlet.',
    'claim_sourced':     ('Sourced to insurgent claims amplified through partisan '
                          'channels and not independently confirmed. Read as '
                          'REPORTED, not established.'),
    'no_evidence':       'No directional evidence in this cycle\'s corpus.',
}


def _trajectory_prose(tr):
    """Plain-language read of the direction, with its confidence stated."""
    if not isinstance(tr, dict) or not tr:
        return ''
    direction = tr.get('direction', 'holding')
    conf = tr.get('confidence', 'no_evidence')
    classes = tr.get('evidence_classes', {}) or {}

    if direction == 'holding':
        return ('Russian position in Mali reads as HOLDING this cycle -- no '
                'directional evidence either way. Note the limit: a hub losing '
                'ground that nobody reports also reads as holding. Quiet is not '
                'the same as stable.')

    named = [_CLASS_PROSE.get(c, c.replace('_', ' '))
             for c in classes.get(direction, [])][:4]
    named_txt = ', '.join(named) if named else 'mixed evidence'

    if direction == 'contracting':
        body = (f'Russia\'s position in Mali reads as CONTRACTING: {named_txt}. '
                f'Mali is the largest Russian deployment in Africa alongside CAR '
                f'and Libya, and the one taking losses -- which makes contraction '
                f'here evidence about the Africa Corps MODEL, not only about this '
                f'theatre.')
        if 'client_hedging' in classes.get('contracting', []):
            body += (' The hedging signal is the one to weight: a regime whose '
                     'survival depends on a single patron does not shop casually. '
                     'Hedging has historically preceded visible failure rather '
                     'than following it.')
    else:
        body = (f'Russia\'s position in Mali reads as EXPANDING: {named_txt}. '
                f'The product being bought is regime survival, and the payment is '
                f'resource access -- so expansion here indicates the junta\'s '
                f'dependency deepening rather than the security picture improving.')

    return body + ' ' + _CONFIDENCE_PROSE.get(conf, '')


# ============================================================
# SO WHAT
# ============================================================
def _build_so_what(scan_data, red_lines, historical):
    vectors = scan_data.get('vector_levels', {}) or {}
    tr      = scan_data.get('trajectory', {}) or {}
    layers  = scan_data.get('compound_layers', {}) or {}
    silence = scan_data.get('silence_anomalies', []) or []
    level   = scan_data.get('theatre_escalation_level', 0) or 0

    breached    = [r for r in red_lines if r['status'] == 'BREACHED']
    approaching = [r for r in red_lines if r['status'] == 'APPROACHING']

    kin   = vectors.get('kinetic', 0)
    blk   = vectors.get('blockade', 0)
    conv  = vectors.get('insurgent_convergence', 0)
    hedge = vectors.get('hedging', 0)
    direction = tr.get('direction', 'holding')

    if direction == 'contracting' and tr.get('confidence') in ('multi_source', 'confirmed_partial'):
        scenario = 'Russian position contracting -- corroborated'
    elif direction == 'contracting':
        scenario = 'Russian position contracting -- claim-sourced'
    elif direction == 'expanding':
        scenario = 'Russian position expanding'
    elif blk >= 4:
        scenario = 'Capital under economic siege'
    elif kin >= 4:
        scenario = 'Active kinetic tempo'
    elif level >= 3:
        scenario = 'Elevated Mali pressure'
    else:
        scenario = 'Baseline monitoring'

    parts = []

    # 1. Trajectory ALWAYS leads in this theatre.
    tp = _trajectory_prose(tr)
    if tp:
        parts.append(tp)

    # 2. The blockade -- Mali's signature mechanism.
    if blk >= 3:
        hum = layers.get('humanitarian', {}) or {}
        detail = f" ({hum.get('in_need_display')} in need on the current sensor read)" \
                 if hum.get('in_need_display') else ''
        parts.append(
            f'Supply-route interdiction is running at L{blk}{detail}. The mechanism '
            f'is blockade to fuel scarcity to market collapse to displacement -- an '
            f'insurgency attacking the state\'s economic lifeline rather than its '
            f'forces. Sieges of capitals have historically preceded political '
            f'rupture more reliably than battlefield losses have.')

    # 3. The insurgent coalition -- and the reason to watch for a split.
    if conv >= 3:
        parts.append(
            'The FLA and JNIM -- a secular Tuareg separatist movement and an '
            'al-Qaeda affiliate -- are operating in coordination. These are '
            'ideologically incompatible actors cooperating against a common '
            'enemy, and the 2012 precedent is that such partnerships do not '
            'hold. A SPLIT would be as analytically significant as the alliance; '
            'both are being watched.')

    # 4. Hedging.
    if hedge >= 3 and 'client_hedging' not in (tr.get('evidence_classes', {}) or {}).get('contracting', []):
        parts.append(
            f'Junta hedging is at L{hedge} -- Bamako engaging alternative '
            f'suppliers. Read as the client pricing its patron\'s reliability.')

    # 5. Kinetic, when it is not already carried by trajectory.
    if kin >= 4 and direction == 'holding':
        parts.append(
            f'Kinetic tempo at L{kin} without a directional read attached: '
            f'fighting is occurring but the corpus is not saying who is gaining. '
            f'That gap is itself worth noting.')

    # 6. Claiming-actor silence.
    for a in silence:
        aid = a.get('actor_id')
        if aid in ('fla', 'jnim', 'mali_junta'):
            who = {'fla': 'The FLA', 'jnim': 'JNIM',
                   'mali_junta': 'The junta'}.get(aid, aid)
            parts.append(
                f'{who} has fallen well below its own claim-tempo baseline. For '
                f'an actor that normally publicises quickly, unusual quiet is '
                f'consistent with operational-security behaviour ahead of '
                f'activity rather than with de-escalation.')
            break

    if not parts:
        cold = []
        if not (layers.get('humanitarian', {}) or {}).get('present'):
            cold.append('humanitarian')
        if not (layers.get('commodity', {}) or {}).get('present'):
            cold.append('commodity')
        cold_txt = (f' Note: {" and ".join(cold)} sensor layer(s) returned no data '
                    f'this cycle, so the compound read is incomplete rather than '
                    f'negative.') if cold else ''
        parts.append(
            'Signals are at baseline for this cycle. No directional movement in '
            'the Russian position, no blockade escalation, no claiming-actor '
            'anomaly.' + cold_txt +
            ' Watch the hedging vector as the leading indicator: it has '
            'historically moved before the security picture did.')

    watch = ('Lead indicators: junta hedging toward alternative suppliers (the '
             'earliest tell that the dependency is loosening); Bamako fuel supply '
             'and blockade tempo; whether FLA-JNIM coordination hardens or '
             'splits; garrison isolation in the north, which preceded collapse in '
             'comparable cases; and Libya-corridor status, since that spine also '
             'supplies Russian operations in Sudan.')

    return {
        'scenario': scenario,
        'assessment': ' '.join(parts),
        'watch': watch,
        'trajectory_direction': direction,
        'trajectory_confidence': tr.get('confidence', 'no_evidence'),
        'breached_count': len(breached),
        'approaching_count': len(approaching),
        'disclaimer': 'This is a CONVERGENCE indicator, NOT a probability of action.',
    }


def _build_action_reads(scan_data, red_lines):
    reads = []
    v = scan_data.get('vector_levels', {}) or {}
    tr = scan_data.get('trajectory', {}) or {}

    if tr.get('direction') == 'contracting':
        reads.append({
            'read': 'Russian position contracting',
            'confirm': 'A drawdown announcement, a further garrison abandoned, or '
                       'a signed agreement with an alternative supplier would '
                       'confirm. Independent confirmation of claimed losses would '
                       'upgrade confidence.',
            'deny': 'Reinforcement arrivals, a renewed or expanded agreement, or '
                    'recovery of lost ground would deny.',
        })
    if tr.get('confidence') == 'claim_sourced':
        reads.append({
            'read': 'Evidence quality',
            'confirm': 'Reuters, AFP, RFI, Jeune Afrique or an ACLED entry '
                       'corroborating the claimed losses would move this from '
                       'reported to established.',
            'deny': 'Russian or Malian denial with imagery, or the claims not '
                    'recurring in subsequent cycles, would deny.',
        })
    if v.get('blockade', 0) >= 3:
        reads.append({
            'read': 'Blockade trajectory',
            'confirm': 'Fuel prices rising further, convoys suspended, or '
                       'rationing in Bamako would confirm tightening.',
            'deny': 'Convoys resuming under escort, or a negotiated corridor, '
                    'would deny.',
        })
    if v.get('insurgent_convergence', 0) >= 3:
        reads.append({
            'read': 'FLA-JNIM coalition durability',
            'confirm': 'A joint political statement, shared command language, or '
                       'territory administered jointly would confirm hardening.',
            'deny': 'Clashes between them, competing claims over the same '
                    'operation, or an FLA overture to Bamako would deny.',
        })
    if v.get('hedging', 0) >= 3:
        reads.append({
            'read': 'Dependency loosening',
            'confirm': 'A delivery arriving from Turkey or another supplier, or a '
                       'signed agreement, confirms the client is diversifying.',
            'deny': 'Talks lapsing with no delivery, or a reaffirmed Russian '
                    'agreement, denies.',
        })
    return reads


# ============================================================
# MAIN ENTRY
# ============================================================
def interpret_signals(scan_data):
    try:
        red_lines  = _score_red_lines(scan_data)
        historical = _match_historical(scan_data)
        so_what    = _build_so_what(scan_data, red_lines, historical)
        actions    = _build_action_reads(scan_data, red_lines)
        breached   = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']
        return {
            'so_what': so_what,
            'red_lines': {
                'triggered': red_lines,
                'breached_count': len(breached),
                'approaching_count': len(approaching),
                'highest_severity': max((r['severity'] for r in breached), default=0),
            },
            'historical_matches': historical,
            'action_reads': actions,
            'interpreter_version': '1.0.0',
            'interpreted_at': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f'[Mali Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what': {'scenario': 'Interpreter error', 'assessment': str(e)[:200]},
            'red_lines': {'triggered': [], 'breached_count': 0,
                          'approaching_count': 0, 'highest_severity': 0},
            'historical_matches': [], 'action_reads': [],
            'interpreter_version': '1.0.0', 'error': str(e)[:200],
        }


# ============================================================
# TOP SIGNALS  (Africa BLUF + GPI)
# ============================================================
# THE LENS PRINCIPLE: every layer down gets a wider lens. The country page
# shows everything emitted here, including L2 watch-tier. The Africa BLUF
# gates to L2+ (plus any diplomatic signal); the GPI narrows again.
#
# No caps applied here -- consumers gate, producers state.
def _tier(level, base):
    if level >= 4:
        return base + 1, 'active'
    if level == 3:
        return base, 'elevated'
    return max(base - 3, 4), 'watch'


def build_top_signals(result):
    signals = []
    v       = result.get('vector_levels', {}) or {}
    tr      = result.get('trajectory', {}) or {}
    interp  = result.get('interpretation', {}) or {}
    rl_obj  = interp.get('red_lines', {}) or {}
    silence = result.get('silence_anomalies', []) or []
    theatre = result.get('theatre_escalation_level', 0) or 0

    # ── 1. TRAJECTORY — the marquee for this theatre ──
    direction = tr.get('direction', 'holding')
    if direction != 'holding':
        conf = tr.get('confidence', 'no_evidence')
        corroborated = conf in ('multi_source', 'confirmed_partial')
        lvl = max(1, min(5, int(tr.get('level', 0) or 0)))
        classes = (tr.get('evidence_classes', {}) or {}).get(direction, [])
        named = ', '.join(_CLASS_PROSE.get(c, c.replace('_', ' ')) for c in classes[:3])
        signals.append({
            'priority': 13 if corroborated else 10,
            'category': 'hub_trajectory',
            'theatre': 'mali',
            'level': lvl,
            'icon': '\U0001F4C9' if direction == 'contracting' else '\U0001F4C8',
            'color': '#dc2626' if direction == 'contracting' else '#f97316',
            'short_text': (f'{MALI_FLAG} MALI: Russia {direction.upper()}'
                           f'{"" if corroborated else " (claimed)"}'),
            'long_text': (f'MALI: Russian position {direction} — {named or "mixed evidence"}. '
                          f'{"Corroborated across independent outlets." if corroborated else "Claim-sourced and unconfirmed; read as reported."} '
                          f'Mali is the largest Russian deployment in Africa alongside CAR '
                          f'and Libya and the one taking losses, so direction here is '
                          f'evidence about the model, not only the theatre.'),
            'trajectory': direction,
            'trajectory_confidence': conf,
        })

    # ── 2. RED LINES BREACHED ──
    for rl in rl_obj.get('triggered', []):
        if rl.get('status') == 'BREACHED':
            sev = int(rl.get('severity', 0) or 0)
            signals.append({
                'priority': 12 if sev >= 3 else 11,
                'category': 'red_line_breached', 'theatre': 'mali',
                'level': min(max(theatre, sev * 2), 5),
                'icon': rl.get('icon', '\U0001F6A8'), 'color': '#dc2626',
                'short_text': f'{MALI_FLAG} MALI: {rl.get("label", "Red line")[:58]}',
                'long_text': f'MALI red line breached — {rl.get("label","")}: {rl.get("detail","")[:130]}',
            })

    # ── 3. BLOCKADE — Mali's signature ──
    blk = v.get('blockade', 0)
    if blk >= 2:
        pri, frame = _tier(blk, 11)
        signals.append({
            'priority': pri, 'category': 'economic_siege', 'theatre': 'mali',
            'level': blk, 'icon': '\u26D4',
            'color': '#dc2626' if blk >= 4 else ('#f97316' if blk == 3 else '#f59e0b'),
            'pressure_type': 'economic',
            'short_text': f'{MALI_FLAG} MALI: Bamako blockade L{blk} ({frame})',
            'long_text': ('MALI: Supply-route interdiction against the capital. The '
                          'mechanism is blockade to fuel scarcity to market collapse '
                          'to displacement — an insurgency attacking the state\'s '
                          'economic lifeline rather than its forces.'),
        })

    # ── 4. INSURGENT CONVERGENCE ──
    conv = v.get('insurgent_convergence', 0)
    if conv >= 2:
        pri, frame = _tier(conv, 11)
        signals.append({
            'priority': pri, 'category': 'insurgent_convergence', 'theatre': 'mali',
            'level': conv, 'icon': '\U0001F91D',
            'color': '#dc2626' if conv >= 4 else '#f97316',
            'short_text': f'{MALI_FLAG} MALI: FLA-JNIM coordination L{conv} ({frame})',
            'long_text': ('MALI: A secular Tuareg separatist movement and an al-Qaeda '
                          'affiliate operating in coordination. Ideologically '
                          'incompatible actors against a common enemy — the 2012 '
                          'precedent is that such partnerships do not hold, so a '
                          'split would be as significant as the alliance.'),
        })

    # ── 5. HEDGING — the leading indicator ──
    hedge = v.get('hedging', 0)
    if hedge >= 2:
        pri, frame = _tier(hedge, 10)
        signals.append({
            'priority': pri, 'category': 'client_hedging', 'theatre': 'mali',
            'level': hedge, 'icon': '\u2696\uFE0F', 'color': '#f97316',
            'short_text': f'{MALI_FLAG} MALI: Junta hedging L{hedge} ({frame})',
            'long_text': ('MALI: Bamako engaging alternative suppliers. A regime whose '
                          'survival depends on one patron does not shop casually — '
                          'hedging has historically preceded visible failure rather '
                          'than following it.'),
        })

    # ── 6. KINETIC ──
    kin = v.get('kinetic', 0)
    if kin >= 2:
        pri, frame = _tier(kin, 10)
        signals.append({
            'priority': pri, 'category': 'kinetic_tempo', 'theatre': 'mali',
            'level': kin, 'icon': '\u2694\uFE0F',
            'color': '#dc2626' if kin >= 4 else '#f97316',
            'pressure_type': 'kinetic',
            'short_text': f'{MALI_FLAG} MALI: Kinetic tempo L{kin} ({frame})',
            'long_text': ('MALI: FAMa and Africa Corps against FLA and JNIM. Escalating '
                          'tempo is not evidence the model is working — atrocities have '
                          'correlated with expanded recruitment rather than suppression.'),
        })

    # ── 7. CLAIMING-ACTOR SILENCE ──
    for a in silence:
        if a.get('actor_id') in ('fla', 'jnim', 'mali_junta'):
            who = {'fla': 'FLA', 'jnim': 'JNIM', 'mali_junta': 'Junta'}.get(a.get('actor_id'))
            signals.append({
                'priority': 11, 'category': 'claiming_actor_silence', 'theatre': 'mali',
                'level': 4, 'icon': '\U0001F507', 'color': '#7c3aed',
                'short_text': f'{MALI_FLAG} MALI: {who} unusual quiet ({a.get("deviation","")})',
                'long_text': (f'MALI: {who} claim-tempo far below baseline. For a '
                              f'fast-claiming actor, silence is consistent with '
                              f'operational security ahead of activity.'),
            })

    # ── 8. LIBYA CORRIDOR — continental sustainment ──
    lib = v.get('libya_corridor', 0)
    if lib >= 2:
        pri, frame = _tier(lib, 10)
        signals.append({
            'priority': pri, 'category': 'logistics_corridor', 'theatre': 'mali',
            'level': lib, 'icon': '\U0001F6E3\uFE0F', 'color': '#f97316',
            'short_text': f'{MALI_FLAG} MALI: Libya corridor L{lib} ({frame})',
            'long_text': ('MALI: Benghazi to Maaten al-Sarra to Sahel logistics spine. '
                          'The SAME corridor supplies Russian operations in Sudan, '
                          'through the same Haftar node — corridor status is a '
                          'continental sustainment read, not a Mali one.'),
        })

    # ── 9. AES COHESION ──
    aes = v.get('aes_cohesion', 0)
    if aes >= 2:
        pri, frame = _tier(aes, 9)
        signals.append({
            'priority': pri, 'category': 'bloc_cohesion', 'theatre': 'mali',
            'level': aes, 'icon': '\U0001F91D', 'color': '#f59e0b',
            'short_text': f'{MALI_FLAG} MALI: AES bloc L{aes} ({frame})',
            'long_text': ('MALI: Alliance of Sahel States cohesion. The AES is the '
                          'political architecture that made simultaneous Western '
                          'expulsion possible across Mali, Niger and Burkina Faso.'),
        })

    # ── 10. FALLBACK ──
    if not signals and theatre >= 2:
        signals.append({
            'priority': 6, 'category': 'theatre_high', 'theatre': 'mali',
            'level': theatre, 'icon': MALI_FLAG, 'color': '#f59e0b',
            'short_text': f'{MALI_FLAG} MALI: Pressure L{theatre}',
            'long_text': f'MALI: Theatre pressure at L{theatre}. See tracker for vector detail.',
        })

    signals.sort(key=lambda s: (-s['priority'], -s.get('level', 0)))
    return signals
