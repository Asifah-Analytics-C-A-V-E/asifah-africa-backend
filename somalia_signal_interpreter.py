"""
somalia_signal_interpreter.py
Asifah Analytics -- Africa Backend Module
v1.0.0 -- July 20, 2026

Signal interpretation engine for the Somalia Rhetoric & Pressure Tracker.

Core analytical frame: Somalia is a JUNCTION. Two questions run in parallel:
  1. Country: Is the al-Shabaab resurgence + federal fracture + AUSSOM funding
     collapse converging toward a Mogadishu-pressure / state-fragmentation window?
  2. Junction: Are the Turkey, Russia, and Bab-el-Mandeb wheels lighting at the
     same time -- a Horn realignment read that rides up to the Africa BLUF / GPI?

Three analytical outputs (Yemen contract):
  1. So What Summary  -- plain-language estimative assessment
  2. Red Line Status  -- Somalia red lines + wheel-convergence
  3. Historical Match -- documented pre-escalation analogs

Plus build_top_signals() -- the canonical schema for Africa BLUF + GPI, with
the wheel-convergence as the marquee cross-theater signal (like Yemen's dual
chokepoint).

DOCTRINE: estimative voice only -- "consistent with", "historically precedes",
"likely indicates". No probabilities, no dates, no "will". The reader completes
the inference.

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone

SOMALIA_FLAG = '\U0001F1F8\U0001F1F4'  # 🇸🇴


# ============================================================
# RED LINE DEFINITIONS
# ============================================================
RED_LINES = [
    {
        'id':       'mogadishu_penetration',
        'label':    'Mogadishu Penetration / Siege',
        'detail':   'al-Shabaab complex attack or advance into the capital -- the '
                    'state-survival threshold',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\U0001F6A8',
        'category': 'shabaab_trigger',
        'vectors':  ['shabaab'],
        'source':   'Historical threshold -- capital penetration is the signal that '
                    'separates insurgency from state-collapse risk',
    },
    {
        'id':       'aussom_collapse',
        'label':    'AUSSOM Collapse / Abrupt Withdrawal',
        'detail':   'Peacekeeping security floor removed before Somali forces can hold '
                    '-- the 2021 Afghanistan-style vacuum risk',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\U0001F6D1',
        'category': 'security_floor',
        'vectors':  ['aussom'],
        'source':   'ATMIS->AUSSOM drawdown gap already produced the 2025 al-Shabaab '
                    'reversal; funding collapse is the accelerant',
    },
    {
        'id':       'state_fragmentation',
        'label':    'Federal Fragmentation / Armed Standoff',
        'detail':   'Puntland/Jubaland rupture escalates to armed federal confrontation '
                    'during the mandate crisis',
        'severity': 2,
        'color':    '#ef4444',
        'icon':     '\U0001F5FA\uFE0F',
        'category': 'fracture_trigger',
        'vectors':  ['fracture'],
        'source':   'Expired presidential mandate (May 2026) + member-state recognition '
                    'withdrawal is the 2021-crisis failure mode, sharpened',
    },
    {
        'id':       'isis_finance_expansion',
        'label':    'ISIS-Somalia Finance-Hub Expansion',
        'detail':   'Cal-Miskaad node expands as an IS global finance/facilitation hub',
        'severity': 2,
        'color':    '#ef4444',
        'icon':     '\U0001F3F4',
        'category': 'isis_trigger',
        'vectors':  ['isis'],
        'source':   'al-Karrar office moves money across the IS global system -- a '
                    'counter-terror-finance concern beyond Somali borders',
    },
    {
        'id':       'foreign_base_establishment',
        'label':    'Foreign Military Base Establishment',
        'detail':   'Turkey, Russia, or Egypt establishes or formalizes a military/naval '
                    'foothold -- the junction hardening into basing',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\u2693',
        'category': 'junction_trigger',
        'vectors':  ['patron'],
        'source':   'TURKSOM precedent + Russian Red Sea base ambition; basing converts '
                    'influence into durable projection',
    },
    {
        'id':       'wheel_convergence',
        'label':    'MULTI-WHEEL CONVERGENCE -- Horn Realignment',
        'detail':   'Two or more of Turkey / Russia / Bab-el-Mandeb / Israel-Somaliland '
                    'pressure simultaneously -- the junction lighting up',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\U0001F300',
        'category': 'convergence_trigger',
        'vectors':  ['patron', 'maritime', 'somaliland'],
        'source':   'Strategic pattern -- simultaneous great-power + chokepoint + '
                    'recognition pressure is the Horn-realignment convergence read',
    },
    {
        'id':       'somaliland_recognition',
        'label':    'Somaliland Recognition Move',
        'detail':   'Israel, the US, or Ethiopia moves toward recognizing Somaliland -- '
                    'the wildcard that reorders the Horn',
        'severity': 2,
        'color':    '#ef4444',
        'icon':     '\U0001F1F8\U0001F1F4',
        'category': 'recognition_trigger',
        'vectors':  ['somaliland'],
        'source':   'Recognition would rupture Mogadishu relations and entangle the '
                    'Turkey-mediation and Berbera-basing questions',
    },
]


# ============================================================
# HISTORICAL ANALOGS
# ============================================================
HISTORICAL_PATTERNS = [
    {
        'id':       'icu_2006',
        'label':    '2006 Islamic Courts Union / Ethiopian Intervention',
        'signals':  ['fracture', 'patron', 'shabaab'],
        'outcome':  'External (Ethiopian) intervention against an Islamist authority '
                    'birthed al-Shabaab as an insurgency',
        'lesson':   'Foreign intervention against a Mogadishu authority historically '
                    'hardens rather than resolves the insurgency',
    },
    {
        'id':       'famine_2011',
        'label':    '2011 Famine + Kismayo Offensive',
        'signals':  ['shabaab', 'maritime'],
        'outcome':  'Territorial rollback of al-Shabaab coincided with humanitarian '
                    'catastrophe; the group lost cities but kept the countryside',
        'lesson':   'Territorial loss for al-Shabaab historically precedes adaptation '
                    'to rural taxation + asymmetric urban attacks, not defeat',
    },
    {
        'id':       'atmis_gap_2025',
        'label':    '2025 ATMIS->AUSSOM Drawdown Gap',
        'signals':  ['aussom', 'shabaab'],
        'outcome':  'The peacekeeping transition gap enabled al-Shabaab\'s Shabelle '
                    'offensive and the reversal of years of gains',
        'lesson':   'Peacekeeping drawdown ahead of Somali-force readiness historically '
                    'precedes insurgent resurgence -- the funding crisis repeats it',
    },
    {
        'id':       'mou_2024',
        'label':    '2024 Ethiopia-Somaliland MoU Shock',
        'signals':  ['somaliland', 'patron'],
        'outcome':  'A recognition/port MoU detonated regional diplomacy; Turkey '
                    'mediation (Ankara Declaration) de-escalated Mogadishu-Addis tension',
        'lesson':   'Recognition moves historically trigger acute regional realignment '
                    'that pulls in Turkey, Egypt, and the Gulf simultaneously',
    },
]


# ============================================================
# RED LINE SCORING
# ============================================================
def _score_red_lines(scan_data):
    """Evaluate each Somalia red line against current vector levels."""
    vectors = scan_data.get('vector_levels', {})
    convergence = scan_data.get('wheel_convergence', {}) or {}
    triggered = []

    for rl in RED_LINES:
        # Convergence red line keys off the convergence detector, not a vector max
        if rl['id'] == 'wheel_convergence':
            if convergence.get('converged'):
                triggered.append({**_rl_public(rl), 'status': 'BREACHED',
                                  'trigger': convergence.get('headline', '')[:160]})
            else:
                triggered.append({**_rl_public(rl), 'status': 'QUIET', 'trigger': ''})
            continue

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
    vectors = scan_data.get('vector_levels', {})
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
    vectors = scan_data.get('vector_levels', {})
    convergence = scan_data.get('wheel_convergence', {}) or {}
    silence = scan_data.get('silence_anomalies', [])
    level = scan_data.get('theatre_escalation_level', 0)

    breached = [r for r in red_lines_triggered if r['status'] == 'BREACHED']
    approaching = [r for r in red_lines_triggered if r['status'] == 'APPROACHING']

    # Headline scenario
    if convergence.get('converged'):
        scenario = 'Multi-wheel junction convergence'
    elif vectors.get('shabaab', 0) >= 4:
        scenario = 'al-Shabaab active-attack tempo'
    elif vectors.get('aussom', 0) >= 4:
        scenario = 'AUSSOM security-floor crisis'
    elif vectors.get('fracture', 0) >= 4:
        scenario = 'Federal fragmentation'
    elif level >= 3:
        scenario = 'Elevated Horn pressure'
    else:
        scenario = 'Baseline monitoring'

    parts = []

    if convergence.get('converged'):
        wheels = ', '.join(convergence.get('active_wheels', []))
        parts.append(
            f"Simultaneous pressure across {wheels} at the Somalia junction is "
            f"consistent with the pattern that historically precedes a Horn "
            f"realignment window -- great-power projection, chokepoint friction, "
            f"and recognition politics moving together rather than separately.")

    if vectors.get('shabaab', 0) >= 4:
        parts.append(
            "al-Shabaab is at active-attack tempo; sustained operations co-occurring "
            "with the AUSSOM funding crisis is the compound pattern that historically "
            "precedes territorial contest around fixed government positions.")

    # Silence read (mode='actor' marquee)
    shabaab_silent = any(a['actor_id'] == 'al_shabaab' for a in silence)
    if shabaab_silent:
        parts.append(
            "Notably, al-Shabaab claim-tempo has fallen well below its own baseline -- "
            "for a group that normally claims fast, unusual quiet is consistent with "
            "operational-security behavior ahead of activity, not de-escalation.")

    if vectors.get('aussom', 0) >= 3:
        parts.append(
            "AUSSOM funding signals are elevated; a withdrawal read here is escalatory-"
            "by-absence -- the security floor is the variable, and its removal "
            "historically precedes insurgent opportunity, per the 2025 drawdown gap.")

    if not parts:
        parts.append(
            "Signals are at baseline. No cross-wheel convergence and no claiming-actor "
            "anomaly detected this cycle; watch for Turkey/Russia/Bab-el-Mandeb "
            "co-occurrence as the lead junction indicator.")

    assessment = ' '.join(parts)

    watch = ('Lead indicators: al-Shabaab claim-cadence deviation (silence or surge), '
             'AUSSOM funding/mandate signals, Puntland-Jubaland federal posture, and '
             'Turkey/Russia/Berbera junction activity moving together.')

    return {
        'scenario': scenario,
        'assessment': assessment,
        'watch': watch,
        'breached_count': len(breached),
        'approaching_count': len(approaching),
        'wheel_convergence': convergence.get('converged', False),
        'disclaimer': 'This is a CONVERGENCE indicator, NOT a probability of action.',
    }


# ============================================================
# ACTION READS
# ============================================================
def _build_action_reads(scan_data, red_lines_triggered):
    """What observable behavior would confirm/deny the current read."""
    reads = []
    vectors = scan_data.get('vector_levels', {})
    convergence = scan_data.get('wheel_convergence', {}) or {}

    if convergence.get('converged'):
        reads.append({
            'read': 'Junction hardening',
            'confirm': 'Foreign basing announcements, recognition moves, or a Gulf-of-Aden '
                       'shipping-risk spike would confirm the realignment read.',
            'deny': 'Turkey mediation (Ankara-Declaration-style de-escalation) fading the '
                    'wheels back below threshold would deny it.',
        })
    if vectors.get('aussom', 0) >= 3:
        reads.append({
            'read': 'Security-floor stress',
            'confirm': 'A funding-renewal failure or an accelerated drawdown date confirms.',
            'deny': 'A 2719-framework funding agreement or mandate extension denies (and '
                    'reads as de-escalation).',
        })
    if vectors.get('shabaab', 0) >= 3:
        reads.append({
            'read': 'Insurgent tempo',
            'confirm': 'Claimed complex attacks on fixed government/AU positions confirm.',
            'deny': 'Sustained government-held territory + declining claim cadence (absent '
                    'a silence anomaly) denies.',
        })
    return reads


# ============================================================
# MAIN ENTRY
# ============================================================
def interpret_signals(scan_data):
    """Called from rhetoric_tracker_somalia.py. Returns interpretation dict."""
    try:
        red_lines = _score_red_lines(scan_data)
        historical = _match_historical(scan_data)
        so_what = _build_so_what(scan_data, red_lines, historical)
        action_reads = _build_action_reads(scan_data, red_lines)

        breached = [r for r in red_lines if r['status'] == 'BREACHED']
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
        print(f'[Somalia Interpreter] Error: {str(e)[:120]}')
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
# {priority:int, category:str, theatre:'somalia', level:int, icon:str,
#  color:str, short_text:str (<=80), long_text:str (<=200)}
#
# The wheel-convergence is the marquee cross-theater signal (priority 13),
# mirroring Yemen's dual_chokepoint. Independent wheel spokes also emit at
# lower priority so a lone Turkey-in-Somalia signal still rides to GPI.

def build_top_signals(result):
    signals = []
    vectors = result.get('vector_levels', {}) or {}
    convergence = result.get('wheel_convergence', {}) or {}
    interp = result.get('interpretation', {}) or {}
    rl_obj = interp.get('red_lines', {}) or {}
    silence = result.get('silence_anomalies', []) or []

    theatre_level = result.get('theatre_escalation_level', 0) or 0

    # ── CATEGORY 1: MULTI-WHEEL CONVERGENCE (marquee) ──
    if convergence.get('converged'):
        wheels = ', '.join(convergence.get('active_wheels', []))
        signals.append({
            'priority': 13,
            'category': 'wheel_convergence',
            'theatre': 'somalia',
            'level': max(theatre_level, 4),
            'icon': '\U0001F300',
            'color': '#dc2626',
            'short_text': f'{SOMALIA_FLAG} SOMALIA: Multi-wheel junction — {wheels}',
            'long_text': (f'SOMALIA: {convergence.get("wheel_count", 0)} wheels converging '
                          f'({wheels}). Great-power + chokepoint + recognition pressure '
                          f'co-occurring — the Horn-realignment convergence read.'),
        })

    # ── CATEGORY 2: RED LINES BREACHED ──
    for rl in rl_obj.get('triggered', []):
        if rl.get('status') == 'BREACHED' and rl.get('id') != 'wheel_convergence':
            sev = int(rl.get('severity', 0) or 0)
            signals.append({
                'priority': 12 if sev >= 3 else 11,
                'category': 'red_line_breached',
                'theatre': 'somalia',
                # Clamp to the 0-5 canonical palette. severity 3 -> sev*2 = 6,
                # which is off-scale: it renders as 'L6 Red-Line Breach' on the
                # Africa BLUF and, being the highest number in the pool, sets the
                # GPI's global KINETIC axis to an impossible L6.
                'level': min(max(theatre_level, sev * 2), 5),
                'icon': rl.get('icon', '\U0001F6A8'),
                'color': '#dc2626',
                'short_text': f'{SOMALIA_FLAG} SOMALIA: {rl.get("label", "Red line")[:58]}',
                'long_text': f'SOMALIA red line breached — {rl.get("label", "")}: {rl.get("detail", "")[:130]}',
            })

    # ── CATEGORY 3: al-SHABAAB SILENCE (mode='actor' marquee) ──
    for a in silence:
        if a.get('actor_id') == 'al_shabaab':
            signals.append({
                'priority': 11,
                'category': 'shabaab_silence',
                'theatre': 'somalia',
                'level': 4,
                'icon': '\U0001F507',
                'color': '#7c3aed',
                'short_text': f'{SOMALIA_FLAG} SOMALIA: al-Shabaab unusual quiet ({a.get("deviation","")})',
                'long_text': ('SOMALIA: al-Shabaab claim-tempo far below baseline. For a fast-'
                              'claiming actor, silence is consistent with operational security '
                              'ahead of activity — not de-escalation.'),
            })

    # ── CATEGORY 4: FOREIGN-PATRON PROJECTION (rides up even if lone) ──
    if vectors.get('patron', 0) >= 3:
        signals.append({
            'priority': 9,
            'category': 'turkey_projection',
            'theatre': 'somalia',
            'level': vectors.get('patron', 0),
            'icon': '\U0001F1F9\U0001F1F7',
            'color': '#f97316',
            'short_text': f'{SOMALIA_FLAG} SOMALIA: Foreign-patron projection L{vectors.get("patron",0)}',
            'long_text': ('SOMALIA: Foreign-patron activity elevated (Turkey/Gulf/Ethiopia). '
                          'Feeds the Turkey wheel as its African spoke; watch for ME co-occurrence.'),
        })

    # ── CATEGORY 5: BAB-EL-MANDEB COUPLING ──
    if vectors.get('maritime', 0) >= 3:
        signals.append({
            'priority': 10,
            'category': 'bab_el_mandeb_coupling',
            'theatre': 'somalia',
            'level': vectors.get('maritime', 0),
            'icon': '\U0001F6A2',
            'color': '#dc2626',
            'short_text': f'{SOMALIA_FLAG} SOMALIA: Gulf of Aden / piracy L{vectors.get("maritime",0)}',
            'long_text': ('SOMALIA: Piracy resurgence / Gulf of Aden tempo couples to the Yemen '
                          'Bab-el-Mandeb vector — the dual-chokepoint supply-risk read.'),
        })

    # ── CATEGORY 6: AUSSOM SECURITY-FLOOR ──
    if vectors.get('aussom', 0) >= 3:
        signals.append({
            'priority': 10,
            'category': 'aussom_crisis',
            'theatre': 'somalia',
            'level': vectors.get('aussom', 0),
            'icon': '\U0001F6D1',
            'color': '#ef4444',
            'short_text': f'{SOMALIA_FLAG} SOMALIA: AUSSOM security-floor stress L{vectors.get("aussom",0)}',
            'long_text': ('SOMALIA: AUSSOM funding/withdrawal signals elevated. Withdrawal reads '
                          'as escalation-by-absence — the 2025 drawdown-gap pattern.'),
        })

    # ── CATEGORY 7: STATE FRAGMENTATION ──
    if vectors.get('fracture', 0) >= 3:
        signals.append({
            'priority': 9,
            'category': 'state_fragmentation',
            'theatre': 'somalia',
            'level': vectors.get('fracture', 0),
            'icon': '\U0001F5FA\uFE0F',
            'color': '#f97316',
            'short_text': f'{SOMALIA_FLAG} SOMALIA: Federal fracture L{vectors.get("fracture",0)}',
            'long_text': ('SOMALIA: Puntland/Jubaland rupture amid the expired-mandate crisis. '
                          'Federal fragmentation during a legitimacy vacuum is the 2021-crisis '
                          'failure mode, sharpened.'),
        })

    # ── CATEGORY 8: SOMALILAND RECOGNITION WILDCARD ──
    if vectors.get('somaliland', 0) >= 4:
        signals.append({
            'priority': 9,
            'category': 'somaliland_recognition',
            'theatre': 'somalia',
            'level': vectors.get('somaliland', 0),
            'icon': SOMALIA_FLAG,
            'color': '#f59e0b',
            'short_text': f'{SOMALIA_FLAG} SOMALIA: Somaliland recognition signal L{vectors.get("somaliland",0)}',
            'long_text': ('SOMALIA: Somaliland recognition activity (Israel/US/Ethiopia + Berbera). '
                          'Recognition would reorder the Horn and entangle the Turkey-mediation angle.'),
        })

    # ── CATEGORY 9: THEATRE HIGH (fallback) ──
    if not signals and theatre_level >= 3:
        signals.append({
            'priority': 7,
            'category': 'theatre_high',
            'theatre': 'somalia',
            'level': theatre_level,
            'icon': SOMALIA_FLAG,
            'color': '#f97316',
            'short_text': f'{SOMALIA_FLAG} SOMALIA: Elevated Horn pressure L{theatre_level}',
            'long_text': f'SOMALIA: Theatre pressure at L{theatre_level}. See tracker for vector detail.',
        })

    signals.sort(key=lambda s: s['priority'], reverse=True)
    return signals
