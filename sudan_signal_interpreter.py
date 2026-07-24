"""
sudan_signal_interpreter.py
Asifah Analytics -- Africa Backend Module
v1.0.0 -- July 24, 2026

Signal interpretation engine for the Sudan Rhetoric & Pressure Tracker.

Core analytical frame: Sudan is a HUB. Three questions run in parallel:
  1. Country: Is the SAF-RSF war intensifying or de-escalating? The Kordofan
     siege line (El Obeid) and the Boulos peace track are BOTH live -- and
     stating both is more honest than netting them into one number.
  2. Hub: Which patron plug is winning? Russia (Port Sudan state deal), UAE
     (RSF's principal backer), or the SAF patron composite (Egypt/KSA/Iran/
     Turkey)? This is the read that rides up to the Africa BLUF / GPI.
  3. Compound: Does the kinetic layer co-occur with humanitarian compression
     (famine, cholera, displacement) and commodity exposure (gold, gum arabic)?
     That compound is the doctrine's famine-pattern read.

THE CONTRADICTION FLAG (this tracker's signature analytical move):
Russia has TWO independent plugs into Sudan that point opposite directions --
the state-level Port Sudan naval/arms/mining deal with Khartoum, AND
Russia-aligned Haftar arming the RSF from Libya-east. When both are live, the
wheel is arguing with itself. We describe both and let the reader complete the
inference about which wins. We do NOT adjudicate.

Three analytical outputs (Yemen contract):
  1. So What Summary  -- plain-language estimative assessment
  2. Red Line Status  -- Sudan red lines + compound/contradiction convergence
  3. Historical Match -- documented pre-escalation analogs

Plus build_top_signals() -- the canonical schema for Africa BLUF + GPI, with
the compound-risk convergence as the marquee signal.

DOCTRINE: estimative voice only -- "consistent with", "historically precedes",
"likely indicates". No probabilities, no dates, no "will". The reader completes
the inference.

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone

SUDAN_FLAG = '\U0001F1F8\U0001F1E9'  # 🇸🇩


# ============================================================
# RED LINE DEFINITIONS
# ============================================================
RED_LINES = [
    {
        'id':       'el_obeid_falls',
        'label':    'El Obeid Falls / Kordofan Gateway Breached',
        'detail':   'RSF capture of North Kordofan\'s capital opens the corridor toward '
                    'the Nile valley and the SAF-held centre -- the current war\'s '
                    'decisive frontline',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\U0001F6A8',
        'category': 'kinetic_trigger',
        'vectors':  ['kinetic'],
        'source':   'El Fasher (Oct 2025) demonstrated the siege-to-fall-to-atrocity '
                    'sequence; El Obeid is the same pattern on a strategically '
                    'more consequential axis',
    },
    {
        'id':       'port_sudan_strike',
        'label':    'Port Sudan Struck / Wartime Capital Under Fire',
        'detail':   'Drone or missile attack on the SAF wartime seat of government, the '
                    'Red Sea corridor, or the aid-logistics hub',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\U0001F3AF',
        'category': 'kinetic_trigger',
        'vectors':  ['kinetic'],
        'source':   'Port Sudan is simultaneously the seat of government, the aid '
                    'lifeline, and the site of Russia\'s naval ambition -- strikes '
                    'there couple military, humanitarian, and great-power vectors',
    },
    {
        'id':       'russia_base_activation',
        'label':    'Russian Naval Base Activation at Port Sudan',
        'detail':   'Warship arrival, troop deployment, or operational declaration under '
                    'the 25-year agreement -- the Tartus plan-B becoming plan-A',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\u2693',
        'category': 'hub_trigger',
        'vectors':  ['russia_plug'],
        'source':   'Post-Assad loss of Tartus makes Red Sea basing the Africa Corps '
                    'supply-chain substitute; activation converts influence into '
                    'durable projection',
    },
    {
        'id':       'spillover_south_confirmed',
        'label':    'South Sudan Corridor Opens / Pipeline Severed',
        'detail':   'Blue Nile front activation, SPLM-N offensive from South Sudanese '
                    'territory, or Petrodar pipeline interruption',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\U0001F6E2\uFE0F',
        'category': 'spillover_trigger',
        'vectors':  ['spillover_south'],
        'source':   'South Sudan draws two-thirds of state revenue through a pipeline '
                    'crossing Sudanese territory; severing it couples Sudan\'s war to '
                    'South Sudanese state solvency',
    },
    {
        'id':       'chad_border_war',
        'label':    'Chad Border Crossed / Cross-Border War',
        'detail':   'RSF operations into Chadian territory, or SAF strikes on the '
                    'Amdjarass supply corridor -- regionalizing the war westward',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\u26A0\uFE0F',
        'category': 'spillover_trigger',
        'vectors':  ['spillover_west'],
        'source':   'Chad hosts both the largest Sudanese refugee population and the '
                    'alleged RSF resupply corridor -- the two functions are '
                    'geographically inseparable',
    },
    {
        'id':       'peace_track_collapse',
        'label':    'Peace Track Collapse (Escalation-by-Absence)',
        'detail':   'INVERTED POLARITY -- mediation going quiet while kinetic tempo '
                    'holds or rises removes the only observable off-ramp',
        'severity': 2,
        'color':    '#ef4444',
        'icon':     '\U0001F54A\uFE0F',
        'category': 'diplomatic_trigger',
        'vectors':  ['peace_track'],
        'source':   'Jeddah (2023) and successive rounds each collapsed into renewed '
                    'offensives; mediation silence during active kinetic tempo has '
                    'historically preceded escalation, not stalemate',
    },
    {
        'id':       'compound_risk',
        'label':    'COMPOUND CONVERGENCE -- Kinetic x Humanitarian x Commodity',
        'detail':   'War tempo, famine/disease compression, and commodity exposure '
                    'tightening in the same country simultaneously',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\U0001F300',
        'category': 'convergence_trigger',
        'vectors':  ['kinetic'],
        'source':   'The compound pattern that has historically preceded famine '
                    'expansion and subsistence-driven collapse -- IPC-5 at Zamzam '
                    '(2024) emerged from exactly this stack',
    },
    {
        'id':       'russia_contradiction',
        'label':    'RUSSIA TWO-PLUG CONTRADICTION',
        'detail':   'The Port Sudan state-level plug and Russia-aligned Haftar arming '
                    'the RSF are BOTH live -- the wheel arguing with itself',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '\u2696\uFE0F',
        'category': 'contradiction_trigger',
        'vectors':  ['russia_plug', 'libya_haftar'],
        'source':   'Moscow\'s Sudan alignment inverted once (RSF-first, then SAF-first); '
                    'a live contradiction is the observable evidence that the '
                    'alignment is being renegotiated rather than settled',
    },
    {
        'id':       'patron_axis_hardening',
        'label':    'Patron Axis Hardening / Direct Involvement',
        'detail':   'UAE or a SAF patron (Egypt / Iran / Turkey / KSA) moves from '
                    'deniable supply to acknowledged or confirmed direct involvement',
        'severity': 2,
        'color':    '#ef4444',
        'icon':     '\U0001F30D',
        'category': 'patron_trigger',
        'vectors':  ['uae_axis', 'saf_patron'],
        'source':   'Proxy wars historically escalate when a patron\'s deniability '
                    'lapses -- attribution forces either withdrawal or commitment',
    },
]


# ============================================================
# HISTORICAL ANALOGS
# ============================================================
HISTORICAL_PATTERNS = [
    {
        'id':       'darfur_2003',
        'label':    '2003-05 Darfur Campaign (Janjaweed lineage)',
        'signals':  ['kinetic', 'spillover_west'],
        'outcome':  'Government-backed militia campaign in Darfur produced mass atrocity, '
                    'a genocide determination, and a refugee population in Chad that '
                    'has never gone home',
        'lesson':   'The RSF\'s institutional ancestor conducted this campaign; '
                    'ethnic-targeting language co-occurring with Chad-border '
                    'displacement historically precedes atrocity documentation',
    },
    {
        'id':       'bashir_fall_2019',
        'label':    '2019 Bashir Fall + Khartoum Massacre',
        'signals':  ['kinetic', 'peace_track'],
        'outcome':  'A negotiated transition was agreed only after the RSF conducted a '
                    'massacre against the sit-in; power-sharing embedded rather than '
                    'resolved the two-army problem',
        'lesson':   'Sudanese mediation has historically produced agreements that '
                    'postpone the SAF-RSF question rather than settle it -- '
                    'watch what a truce defers, not only what it stops',
    },
    {
        'id':       'war_outbreak_2023',
        'label':    'April 2023 War Outbreak (failed integration)',
        'signals':  ['kinetic', 'uae_axis', 'saf_patron'],
        'outcome':  'The RSF-into-SAF integration timetable triggered the war it was '
                    'designed to prevent; external patrons aligned within weeks',
        'lesson':   'Patron alignment hardening around an integration or transition '
                    'deadline historically precedes rupture rather than compliance',
    },
    {
        'id':       'el_fasher_2025',
        'label':    'October 2025 Fall of El Fasher',
        'signals':  ['kinetic', 'spillover_west'],
        'outcome':  'An 18-month siege ended in capture accompanied by mass atrocities '
                    'against fleeing civilians and a displacement wave into Chad',
        'lesson':   'The siege-to-fall-to-atrocity sequence is the documented recent '
                    'pattern; a comparable siege elsewhere (El Obeid) is consistent '
                    'with the same sequence, not a different one',
    },
    {
        'id':       'zamzam_famine_2024',
        'label':    '2024 IPC Phase 5 Famine Declaration (Zamzam)',
        'signals':  ['kinetic', 'spillover_west'],
        'outcome':  'Siege conditions plus humanitarian-access denial produced the first '
                    'formal famine determination of the war',
        'lesson':   'Famine in this war has been siege-produced, not drought-produced -- '
                    'access denial co-occurring with encirclement is the lead '
                    'indicator, ahead of any price or harvest signal',
    },
    {
        'id':       'tartus_loss_2024',
        'label':    'Dec 2024 Loss of Tartus (Russian basing displacement)',
        'signals':  ['russia_plug'],
        'outcome':  'The post-Assad collapse of Russian basing in Syria redirected '
                    'Africa Corps logistics toward Libya-east and Red Sea alternatives',
        'lesson':   'Russian basing pressure in Sudan is downstream of a loss elsewhere; '
                    'Port Sudan activity likely indicates supply-chain necessity '
                    'rather than opportunistic expansion',
    },
]


# ============================================================
# RED LINE SCORING
# ============================================================
def _score_red_lines(scan_data):
    """Evaluate each Sudan red line against current vector levels.

    Two red lines key off detectors rather than a single vector max:
      * compound_risk        -> compound_convergence.compound_risk_active
      * russia_contradiction -> compound_convergence.russia_contradiction_active
    One red line has INVERTED polarity:
      * peace_track_collapse -> LOW peace_track WHILE kinetic is high
    """
    vectors = scan_data.get('vector_levels', {}) or {}
    compound = scan_data.get('compound_convergence', {}) or {}
    triggered = []

    for rl in RED_LINES:
        # ── Detector-driven red lines ──
        if rl['id'] == 'compound_risk':
            if compound.get('compound_risk_active'):
                triggered.append({**_rl_public(rl), 'status': 'BREACHED',
                                  'trigger': 'kinetic + humanitarian + commodity co-occurring'})
            else:
                triggered.append({**_rl_public(rl), 'status': 'QUIET', 'trigger': ''})
            continue

        if rl['id'] == 'russia_contradiction':
            if compound.get('russia_contradiction_active'):
                triggered.append({**_rl_public(rl), 'status': 'BREACHED',
                                  'trigger': 'Port Sudan plug and Libya-Haftar plug both live'})
            else:
                triggered.append({**_rl_public(rl), 'status': 'QUIET', 'trigger': ''})
            continue

        # ── Inverted-polarity red line: mediation ABSENCE during kinetic tempo ──
        if rl['id'] == 'peace_track_collapse':
            peace = vectors.get('peace_track', 0)
            kinetic = vectors.get('kinetic', 0)
            if kinetic >= 4 and peace == 0:
                status, trig = 'BREACHED', f'kinetic L{kinetic} with no mediation signal detected'
            elif kinetic >= 3 and peace <= 1:
                status, trig = 'APPROACHING', f'kinetic L{kinetic} with mediation at L{peace}'
            else:
                status, trig = 'QUIET', (f'mediation active at L{peace}' if peace else '')
            triggered.append({**_rl_public(rl), 'status': status, 'trigger': trig})
            continue

        # ── Standard vector-max red lines ──
        rl_max = max((vectors.get(v, 0) for v in rl.get('vectors', [])), default=0)
        if rl_max >= 4:
            status = 'BREACHED'
        elif rl_max == 3:
            status = 'APPROACHING'
        else:
            status = 'QUIET'
        triggered.append({**_rl_public(rl), 'status': status,
                          'trigger': f"{rl['category']} vector at L{rl_max}" if rl_max else ''})

    return triggered


def _rl_public(rl):
    """Strip internal fields for API output."""
    return {
        'id': rl['id'], 'label': rl['label'], 'detail': rl['detail'],
        'severity': rl['severity'], 'color': rl['color'], 'icon': rl['icon'],
        'category': rl['category'], 'source': rl['source'],
    }


# ============================================================
# HISTORICAL MATCHING (Jaccard over active vectors)
# ============================================================
def _match_historical(scan_data):
    """Match current active-vector set against historical analogs."""
    vectors = scan_data.get('vector_levels', {}) or {}
    # peace_track is de-escalatory polarity -- it is NOT an "active pressure"
    # vector for similarity purposes EXCEPT where a pattern explicitly names it.
    active = {v for v, lvl in vectors.items() if lvl >= 3}
    if not active:
        return []
    matches = []
    for pat in HISTORICAL_PATTERNS:
        pat_set = set(pat['signals'])
        inter = active & pat_set
        union = active | pat_set
        if union:
            jaccard = len(inter) / len(union)
            if jaccard > 0:
                matches.append({
                    'id': pat['id'],
                    'label': pat['label'],
                    'similarity': round(jaccard, 2),
                    'shared_signals': sorted(inter),
                    'outcome': pat['outcome'],
                    'lesson': pat['lesson'],
                })
    matches.sort(key=lambda m: m['similarity'], reverse=True)
    return matches[:3]


# ============================================================
# SO WHAT (estimative voice)
# ============================================================
def _build_so_what(scan_data, red_lines_triggered, historical_matches):
    vectors   = scan_data.get('vector_levels', {}) or {}
    compound  = scan_data.get('compound_convergence', {}) or {}
    layers    = scan_data.get('compound_layers', {}) or {}
    subtags   = scan_data.get('patron_subtags', {}) or {}
    silence   = scan_data.get('silence_anomalies', []) or []
    level     = scan_data.get('theatre_escalation_level', 0) or 0

    breached    = [r for r in red_lines_triggered if r['status'] == 'BREACHED']
    approaching = [r for r in red_lines_triggered if r['status'] == 'APPROACHING']

    kinetic = vectors.get('kinetic', 0)
    peace   = vectors.get('peace_track', 0)

    # ── Headline scenario ──
    if compound.get('compound_risk_active'):
        scenario = 'Compound convergence -- kinetic x humanitarian x commodity'
    elif kinetic >= 4 and peace >= 3:
        scenario = 'War tempo and mediation running simultaneously'
    elif kinetic >= 4:
        scenario = 'Active war tempo'
    elif vectors.get('russia_plug', 0) >= 4:
        scenario = 'Russian basing consolidation'
    elif level >= 3:
        scenario = 'Elevated Sudan pressure'
    else:
        scenario = 'Baseline monitoring'

    parts = []

    # ── 1. The compound read (marquee) ──
    if compound.get('compound_risk_active'):
        hum = layers.get('humanitarian', {}) or {}
        idp = hum.get('idp_display', '')
        detail = f' ({idp} displaced on the current sensor read)' if idp else ''
        parts.append(
            f"Kinetic tempo, humanitarian compression{detail}, and commodity exposure are "
            f"stacking on the same window -- the compound pattern that has historically "
            f"preceded famine expansion in this war. The 2024 Zamzam determination emerged "
            f"from exactly this stack, and it was siege-produced rather than harvest-driven.")

    # ── 2. The contradiction the doctrine exists for: BOTH tracks live ──
    if kinetic >= 4 and peace >= 3:
        parts.append(
            "The war tempo and the mediation track are both live in this cycle. These are "
            "reported separately rather than netted: an active peace track has historically "
            "coexisted with -- and at times accelerated -- offensive tempo in Sudan, as each "
            "side sought a stronger position ahead of any settlement. Simultaneity here is "
            "the finding, not a contradiction to resolve.")
    elif kinetic >= 4 and peace == 0:
        parts.append(
            "War tempo is elevated with no mediation signal detected this cycle. Read as "
            "escalation-by-absence: the observable off-ramp is not merely stalled, it is "
            "unobserved. Mediation silence during active kinetic tempo has historically "
            "preceded escalation rather than stalemate.")

    # ── 3. The Russia two-plug contradiction ──
    if compound.get('russia_contradiction_active'):
        parts.append(
            "Russia's two plugs into Sudan are simultaneously live: the state-level Port "
            "Sudan naval, arms, and mining arrangement with Khartoum, and Russia-aligned "
            "Haftar forces supplying the RSF from Libya-east. A live contradiction is "
            "consistent with an alignment being renegotiated rather than settled; which "
            "plug prevails is the read the reader completes.")
    elif vectors.get('russia_plug', 0) >= 4:
        parts.append(
            "Russian basing activity at Port Sudan is elevated. Following the loss of "
            "Tartus, Red Sea access likely indicates Africa Corps supply-chain necessity "
            "rather than opportunistic expansion -- basing converts influence into durable "
            "projection, and the logistics requirement is now structural.")

    # ── 4. Patron axis ──
    uae = vectors.get('uae_axis', 0)
    saf_patron = vectors.get('saf_patron', 0)
    if uae >= 3 and saf_patron >= 3:
        named = [k.upper() if k == 'ksa' else k.title()
                 for k, v in subtags.items() if v >= 3]
        named_txt = f" ({', '.join(named)} named)" if named else ''
        parts.append(
            f"Both patron axes are active simultaneously -- UAE-attributed support to the "
            f"RSF and the SAF patron composite{named_txt}. Proxy wars have historically "
            f"escalated when patron deniability lapses, because attribution forces either "
            f"withdrawal or deeper commitment.")
    elif uae >= 4:
        parts.append(
            "UAE-attributed support to the RSF is at attribution tempo. Note the "
            "measurement: this vector reads REPORTING and attribution cadence, not "
            "adjudicated fact -- sensor, not referee.")

    # ── 5. Spillover ──
    ss = vectors.get('spillover_south', 0)
    sw = vectors.get('spillover_west', 0)
    if ss >= 3 and sw >= 3:
        parts.append(
            "Both spillover corridors are active -- the Chad border westward and the Blue "
            "Nile / pipeline corridor southward. Simultaneous pressure on two frontiers is "
            "consistent with regionalization rather than containment.")
    elif ss >= 4:
        parts.append(
            "The South Sudan corridor is active. Because South Sudan draws the bulk of "
            "state revenue through a pipeline crossing Sudanese territory, corridor "
            "activity couples Sudan's war to South Sudanese state solvency -- a second-"
            "order effect that historically precedes instability in Juba.")
    elif sw >= 4:
        parts.append(
            "The Chad-border corridor is active. Chad hosts both the largest Sudanese "
            "refugee population and the alleged RSF resupply route; the two functions are "
            "geographically inseparable, which is what makes cross-border incidents there "
            "consistent with regionalization.")

    # ── 6. Silence reads (mode='actor' -- SAF and RSF both claim loudly) ──
    saf_silent = any(a.get('actor_id') == 'saf_burhan' for a in silence)
    rsf_silent = any(a.get('actor_id') == 'rsf_hemedti' for a in silence)
    if saf_silent and rsf_silent:
        parts.append(
            "Both claiming actors have fallen well below their own statement baselines. "
            "Bilateral quiet in a war where both sides normally claim fast is consistent "
            "either with an unannounced pause or with operational security ahead of "
            "activity -- the two are indistinguishable from rhetoric alone, which is "
            "itself the reason to watch the kinetic sensors this cycle.")
    elif rsf_silent:
        parts.append(
            "RSF claim-tempo has fallen well below its own baseline. For a force that "
            "normally publicizes gains quickly, unusual quiet is consistent with "
            "operational-security behavior ahead of activity rather than de-escalation.")
    elif saf_silent:
        parts.append(
            "SAF statement-tempo has fallen well below its own baseline. For a state actor "
            "that normally maintains a daily communiqué rhythm, quiet is consistent with "
            "either command disruption or a deliberate pre-operational posture.")

    # ── 7. Absence-honest fallback ──
    if not parts:
        cold_layers = []
        if not (layers.get('humanitarian', {}) or {}).get('present'):
            cold_layers.append('humanitarian')
        if not (layers.get('commodity', {}) or {}).get('present'):
            cold_layers.append('commodity')
        cold_txt = (f" Note: {' and '.join(cold_layers)} sensor layer(s) returned no data "
                    f"this cycle, so the compound read is incomplete rather than negative.") \
                   if cold_layers else ''
        parts.append(
            "Signals are at baseline for this cycle. No compound convergence, no patron-axis "
            "hardening, and no claiming-actor anomaly detected." + cold_txt +
            " Watch for kinetic tempo co-occurring with humanitarian compression as the "
            "lead compound indicator.")

    assessment = ' '.join(parts)

    watch = ('Lead indicators: the El Obeid siege line and Kordofan frontline movement; '
             'Port Sudan strike tempo; Russian basing signals measured against Haftar-RSF '
             'supply reporting (the two-plug question); mediation cadence versus kinetic '
             'cadence; and humanitarian access denial, which in this war has preceded '
             'famine determination ahead of any price signal.')

    return {
        'scenario': scenario,
        'assessment': assessment,
        'watch': watch,
        'breached_count': len(breached),
        'approaching_count': len(approaching),
        'compound_risk': compound.get('compound_risk_active', False),
        'russia_contradiction': compound.get('russia_contradiction_active', False),
        'disclaimer': 'This is a CONVERGENCE indicator, NOT a probability of action.',
    }


# ============================================================
# ACTION READS
# ============================================================
def _build_action_reads(scan_data, red_lines_triggered):
    """What observable behavior would confirm/deny the current read."""
    reads = []
    vectors  = scan_data.get('vector_levels', {}) or {}
    compound = scan_data.get('compound_convergence', {}) or {}

    if compound.get('compound_risk_active'):
        reads.append({
            'read': 'Compound famine-pattern stack',
            'confirm': 'An IPC re-classification, a new famine determination, or sustained '
                       'humanitarian-access denial at a besieged location would confirm.',
            'deny': 'A humanitarian corridor opening with verified convoy throughput, or an '
                    'IPC downgrade, would deny.',
        })
    if compound.get('russia_contradiction_active'):
        reads.append({
            'read': 'Russia two-plug contradiction',
            'confirm': 'Ratification steps, warship arrival, or arms deliveries under the '
                       'Port Sudan agreement WHILE Libya-east supply reporting continues '
                       'would confirm the contradiction is durable.',
            'deny': 'Either plug going quiet -- an agreement freeze, or a verified halt to '
                    'Haftar-RSF flows -- would resolve it in one direction.',
        })
    if vectors.get('kinetic', 0) >= 4:
        reads.append({
            'read': 'Kinetic tempo',
            'confirm': 'Frontline movement at El Obeid or the Kordofan axis, or a repeat '
                       'strike on Port Sudan, confirms sustained tempo.',
            'deny': 'A held siege line with declining claim cadence from both actors '
                    '(absent a silence anomaly) denies.',
        })
    if vectors.get('peace_track', 0) >= 3:
        reads.append({
            'read': 'Mediation track viability',
            'confirm': 'A signed humanitarian pause with observable implementation, or both '
                       'belligerents attending the same round, confirms the track is live.',
            'deny': 'Mediation cadence falling to zero while kinetic tempo holds denies -- '
                    'and reads as escalation-by-absence rather than neutral quiet.',
        })
    if vectors.get('uae_axis', 0) >= 3 or vectors.get('saf_patron', 0) >= 3:
        reads.append({
            'read': 'Patron deniability',
            'confirm': 'A UN Panel of Experts finding, sanctions designation, or open '
                       'acknowledgement of direct involvement confirms deniability has lapsed.',
            'deny': 'Sustained denial with no new attribution reporting denies.',
        })
    return reads


# ============================================================
# MAIN ENTRY
# ============================================================
def interpret_signals(scan_data):
    """Called from rhetoric_tracker_sudan.py. Returns interpretation dict."""
    try:
        red_lines   = _score_red_lines(scan_data)
        historical  = _match_historical(scan_data)
        so_what     = _build_so_what(scan_data, red_lines, historical)
        action_reads = _build_action_reads(scan_data, red_lines)

        breached    = [r for r in red_lines if r['status'] == 'BREACHED']
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
            'action_reads': action_reads,
            'interpreter_version': '1.0.0',
            'interpreted_at': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f'[Sudan Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what': {'scenario': 'Interpreter error', 'assessment': str(e)[:200]},
            'red_lines': {'triggered': [], 'breached_count': 0,
                          'approaching_count': 0, 'highest_severity': 0},
            'historical_matches': [],
            'action_reads': [],
            'interpreter_version': '1.0.0',
            'error': str(e)[:200],
        }


# ============================================================
# CANONICAL TOP_SIGNALS BUILDER  (Africa BLUF + GPI)
# ============================================================
# Signal shape:
# {priority:int, category:str, theatre:'sudan', level:int, icon:str,
#  color:str, short_text:str (<=80), long_text:str (<=200)}
#
# The compound-risk convergence is the marquee cross-theater signal
# (priority 13). Independent spokes also emit at lower priority so a lone
# Russia-plug or spillover signal still rides to GPI.
#
# NOTE ON pressure_type: the peace-track signal carries
# pressure_type='diplomatic' natively (canonical native tagging), so the GPI
# does not have to infer it from keywords. Humanitarian-compound signals
# carry pressure_type='humanitarian' for the same reason.

def build_top_signals(result):
    signals  = []
    vectors  = result.get('vector_levels', {}) or {}
    compound = result.get('compound_convergence', {}) or {}
    layers   = result.get('compound_layers', {}) or {}
    subtags  = result.get('patron_subtags', {}) or {}
    interp   = result.get('interpretation', {}) or {}
    rl_obj   = interp.get('red_lines', {}) or {}
    silence  = result.get('silence_anomalies', []) or []

    theatre_level = result.get('theatre_escalation_level', 0) or 0

    # ── CATEGORY 1: COMPOUND CONVERGENCE (marquee) ──
    if compound.get('compound_risk_active'):
        hum = layers.get('humanitarian', {}) or {}
        idp = hum.get('idp_display', '')
        signals.append({
            'priority': 13,
            'category': 'compound_convergence',
            'theatre': 'sudan',
            'level': max(theatre_level, 4),
            'icon': '\U0001F300',
            'color': '#dc2626',
            'pressure_type': 'humanitarian',
            'short_text': f'{SUDAN_FLAG} SUDAN: Kinetic x famine x commodity convergence',
            'long_text': (f'SUDAN: War tempo, humanitarian compression'
                          f'{f" ({idp} displaced)" if idp else ""}, and commodity exposure '
                          f'stacking on one window — the compound pattern that has '
                          f'historically preceded famine expansion.'),
        })

    # ── CATEGORY 2: RUSSIA TWO-PLUG CONTRADICTION (the signature read) ──
    if compound.get('russia_contradiction_active'):
        signals.append({
            'priority': 12,
            'category': 'russia_contradiction',
            'theatre': 'sudan',
            'level': max(vectors.get('russia_plug', 0), vectors.get('libya_haftar', 0)),
            'icon': '\u2696\uFE0F',
            'color': '#dc2626',
            'short_text': f'{SUDAN_FLAG} SUDAN: Russia two-plug contradiction live',
            'long_text': ('SUDAN: Port Sudan state-level plug AND Russia-aligned Haftar '
                          'arming the RSF both active — consistent with an alignment being '
                          'renegotiated rather than settled.'),
        })

    # ── CATEGORY 3: RED LINES BREACHED ──
    # Capped at the 3 most severe. The Africa BLUF pools only TOP_SIGNALS_COUNT
    # (12) signals across ALL trackers, so an uncapped breach loop from a
    # high-intensity theatre would crowd every other African country out of the
    # regional read entirely. Sudan should dominate when it deserves to --
    # it should not monopolise.
    _breached = [r for r in rl_obj.get('triggered', [])
                 if r.get('status') == 'BREACHED'
                 and r.get('id') not in ('compound_risk', 'russia_contradiction')]
    _breached.sort(key=lambda r: int(r.get('severity', 0) or 0), reverse=True)
    for rl in _breached[:3]:
        if True:
            sev = int(rl.get('severity', 0) or 0)
            signals.append({
                'priority': 12 if sev >= 3 else 11,
                'category': 'red_line_breached',
                'theatre': 'sudan',
                'level': max(theatre_level, sev * 2),
                'icon': rl.get('icon', '\U0001F6A8'),
                'color': '#dc2626',
                'short_text': f'{SUDAN_FLAG} SUDAN: {rl.get("label", "Red line")[:58]}',
                'long_text': f'SUDAN red line breached — {rl.get("label", "")}: {rl.get("detail", "")[:130]}',
            })

    # ── CATEGORY 4: CLAIMING-ACTOR SILENCE (mode='actor') ──
    for a in silence:
        aid = a.get('actor_id')
        if aid in ('saf_burhan', 'rsf_hemedti'):
            who = 'RSF' if aid == 'rsf_hemedti' else 'SAF'
            signals.append({
                'priority': 11,
                'category': 'claiming_actor_silence',
                'theatre': 'sudan',
                'level': 4,
                'icon': '\U0001F507',
                'color': '#7c3aed',
                'short_text': f'{SUDAN_FLAG} SUDAN: {who} unusual quiet ({a.get("deviation","")})',
                'long_text': (f'SUDAN: {who} claim-tempo far below baseline. For a fast-claiming '
                              f'actor in an active war, silence is consistent with operational '
                              f'security ahead of activity — not de-escalation.'),
            })

    # ── CATEGORY 5: KINETIC TEMPO ──
    if vectors.get('kinetic', 0) >= 4:
        signals.append({
            'priority': 11,
            'category': 'kinetic_tempo',
            'theatre': 'sudan',
            'level': vectors.get('kinetic', 0),
            'icon': '\U0001F6A8',
            'color': '#dc2626',
            'pressure_type': 'kinetic',
            'short_text': f'{SUDAN_FLAG} SUDAN: War tempo L{vectors.get("kinetic",0)} (Kordofan axis)',
            'long_text': ('SUDAN: SAF-RSF kinetic tempo elevated. The El Obeid siege line is '
                          'the current decisive frontline; El Fasher (Oct 2025) established '
                          'the siege-to-fall-to-atrocity sequence.'),
        })

    # ── CATEGORY 6: RUSSIA PLUG (rides up even if lone — the wheel spoke) ──
    if vectors.get('russia_plug', 0) >= 3:
        signals.append({
            'priority': 10,
            'category': 'russia_plug',
            'theatre': 'sudan',
            'level': vectors.get('russia_plug', 0),
            'icon': '\u2693',
            'color': '#dc2626',
            'short_text': f'{SUDAN_FLAG} SUDAN: Russia Port Sudan plug L{vectors.get("russia_plug",0)}',
            'long_text': ('SUDAN: Russian naval/arms/mining activity at Port Sudan. Following '
                          'the loss of Tartus, Red Sea basing likely indicates Africa Corps '
                          'supply-chain necessity — the Russia wheel\'s newest spoke.'),
        })

    # ── CATEGORY 7: PATRON AXIS ──
    if vectors.get('uae_axis', 0) >= 3 or vectors.get('saf_patron', 0) >= 3:
        named = [k.upper() if k == 'ksa' else k.title() for k, v in subtags.items() if v >= 3]
        named_txt = f' ({", ".join(named)})' if named else ''
        lvl = max(vectors.get('uae_axis', 0), vectors.get('saf_patron', 0))
        signals.append({
            'priority': 9,
            'category': 'patron_axis',
            'theatre': 'sudan',
            'level': lvl,
            'icon': '\U0001F30D',
            'color': '#f97316',
            'short_text': f'{SUDAN_FLAG} SUDAN: Patron axis L{lvl}{named_txt[:24]}',
            'long_text': (f'SUDAN: External patron activity elevated{named_txt} — UAE-attributed '
                          f'RSF support and/or the SAF patron composite. Measured as reporting '
                          f'and attribution tempo: sensor, not referee.'),
        })

    # ── CATEGORY 8: SPILLOVER CORRIDORS ──
    if vectors.get('spillover_south', 0) >= 3:
        signals.append({
            'priority': 10,
            'category': 'spillover_south',
            'theatre': 'sudan',
            'level': vectors.get('spillover_south', 0),
            'icon': '\U0001F6E2\uFE0F',
            'color': '#dc2626',
            'short_text': f'{SUDAN_FLAG} SUDAN: South Sudan corridor L{vectors.get("spillover_south",0)}',
            'long_text': ('SUDAN: Blue Nile / SPLM-N / Petrodar corridor active. South Sudan '
                          'draws most state revenue through a pipeline crossing Sudanese '
                          'territory — corridor activity couples the two states\' stability.'),
        })
    if vectors.get('spillover_west', 0) >= 3:
        signals.append({
            'priority': 9,
            'category': 'spillover_west',
            'theatre': 'sudan',
            'level': vectors.get('spillover_west', 0),
            'icon': '\u26A0\uFE0F',
            'color': '#f97316',
            'short_text': f'{SUDAN_FLAG} SUDAN: Chad-border corridor L{vectors.get("spillover_west",0)}',
            'long_text': ('SUDAN: Chad-border activity elevated. Chad hosts both the largest '
                          'refugee population and the alleged RSF resupply route — inseparable '
                          'functions that make incidents there consistent with regionalization.'),
        })

    # ── CATEGORY 9: PEACE TRACK (DIPLOMATIC — native pressure_type tag) ──
    if vectors.get('peace_track', 0) >= 3:
        signals.append({
            'priority': 9,
            'category': 'diplomatic_offramp',
            'theatre': 'sudan',
            'level': vectors.get('peace_track', 0),
            'icon': '\U0001F54A\uFE0F',
            'color': '#1d4ed8',
            'pressure_type': 'diplomatic',
            'short_text': f'{SUDAN_FLAG} SUDAN: Mediation track active L{vectors.get("peace_track",0)}',
            'long_text': ('SUDAN: Boulos/Quad mediation cadence elevated. Reported beside the '
                          'kinetic read, not netted against it — an active track has '
                          'historically coexisted with offensive tempo in Sudan.'),
        })

    # ── CATEGORY 10: THEATRE HIGH (fallback) ──
    if not signals and theatre_level >= 3:
        signals.append({
            'priority': 7,
            'category': 'theatre_high',
            'theatre': 'sudan',
            'level': theatre_level,
            'icon': SUDAN_FLAG,
            'color': '#f97316',
            'short_text': f'{SUDAN_FLAG} SUDAN: Elevated pressure L{theatre_level}',
            'long_text': f'SUDAN: Theatre pressure at L{theatre_level}. See tracker for vector detail.',
        })

    signals.sort(key=lambda s: s['priority'], reverse=True)

    # Total emission cap. Same reasoning as the breach cap above: the regional
    # BLUF pools 12 signals across every Africa tracker. Eight is enough for
    # Sudan to lead the regional read on merit without silencing its neighbours.
    return signals[:8]
