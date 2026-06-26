# Football Cup — CONTROLLABLE-ENDPOINT / LEVER CATALOG (2026-06-26)

Every knob we can actually turn, with current value + status. Built to stop "twiddle one
known knob" and force a full-surface review (AGENTS §0). Status legend: SHIPPED (in the live
default), GATED-OFF (built, behind a flag), DISPROVEN (live A/B said no), UNTUNED (default/
estimate, never calibrated), UNUSED (engine endpoint we never exercise).

## 0. ENGINE CONTRACT — the actual command endpoints (what the platform lets us control)
Commands we EMIT: MOVE_TO, PASS{target,type}, SHOOT{aim_location,power}, PRESS_BALL{intensity},
MARK{target,tightness}, SLIDE_TACKLE, GK_DISTRIBUTE{target,method THROW|KICK}, SET_STANCE{0|1}.
- **UNUSED engine endpoint: INTERCEPT** — listed in the contract, we never emit it (we use
  PRESS_BALL/SLIDE_TACKLE/MARK). Possible defensive lever.
- SHOOT **power** is a 1-line distance formula `min(1.0, 0.6 + dist/_sx(1.45))` (policy_v2.py:516) — UNTUNED.
- SHOOT **aim_location** TL/TR/BL/BR/CENTER via `_mixed_aim` (keeper-away side) — lightly used.
- GK_DISTRIBUTE method = THROW if dist<0.45 else KICK (policy_v2.py:1087) — crude; attack-initiation lever.
- SET_STANCE only ever 0/1 (policy_v2.py:1322) — minimal.
- Portal **PUT /teams/{id} {formation}** — formation is set out-of-band; mid-match change untested.

## 1. POLICY per-tick deterministic knobs (champion/policy_v2.py)
| Knob | Current | Status |
|---|---|---|
| ACTIVE_FORMATION | "1-1-2" | SHIPPED; 2-1-1 DISPROVEN(aggressive worse), 1-2-1 untested |
| ROLE anchors (anchor_ax/ay, zone_tol, press_trigger, shoot_range, push_when_attacking, risk) × 5-7 roles | fixed table :135-144 | SHIPPED — the BIG continuous surface, hand-set not optimized |
| SHOOT_MIN_PROB / SHOOT_NOW_PROB | 0.42 / 0.62 | SHIPPED; loosening DISPROVEN(no diff, conv fell) |
| CARRY_TO_SHOOT_DIST / SHOT_REAL_CHANCE_DIST | 0.62 / 0.43 | SHIPPED |
| SHOT_CENTER_BAND / SHOT_CLOSE_WIDE_BAND | 1.15 / 1.65 | SHIPPED (× GOAL_HALF_WIDTH) |
| GOAL_HALF_WIDTH | 1.0 | **UNTUNED estimate** — never calibrated from real goal-event ball-z |
| SHOOT power formula | 0.6+dist/1.45 | **UNTUNED** |
| PRESS_NEAR/TIGHT_DIST, PRESS_RELEASE_MIN_SUCCESS | 0.22/0.12/0.44 | SHIPPED |
| _ball_rank single-presser (anti-swarm) | invariant | SHIPPED (arch-tested, swarm leak 0) |
| DROP_MARK_ENABLED | True | SHIPPED (A/B-proven; OFF made aggressive worse) |
| LOW_STAMINA | 18.0 | SHIPPED — stamina barely used as a weapon |
| _game_mode(score, gameTime) | risk/press scale late | SHIPPED |
| anti-exploitation mixing (_near_optimal_pick eps) | 0.10 | SHIPPED |
| COUNTER_MODE_ENABLED (+6 consts) | False | GATED-OFF; deep-turnover counter, DISPROVEN(2W-2L vs 2W-2L) |
| INBEHIND_RUN_ENABLED (lever A) | False | GATED-OFF; A/B 2026-06-26 NULL (shot ratio 0.54→0.56, us_shots ↓) |
| THROUGHBALL_EV_ENABLED/_WEIGHT (lever B) | False / 0.5 | GATED-OFF; A/B NULL — inert-vs-disproven = OPEN Q for Codex |
| tactics seam push/attack_zone/exploit_opp_id/tempo (_apply_attack_tactics) | driven by playbook/hybrid only | partially UNUSED (attack_zone unused by shipped set) |

## 2. SELECTOR meta-controller (champion/selector.py)
- PLAYBOOKS {DEFAULT(on), TWO_STRIKER_COVER=2-1-1(off), HIGH_PRESS_BEATER=press-beater(off)} + per-playbook `enabled` ship gate.
- thresholds: TWO_STRIKER_MIN_IN_THIRD=2, HIGH_PRESS_MIN_IN_HALF=3, SCOUT_SECONDS=8, DEF_THIRD_FRAC=0.30, OUR_HALF_FRAC=0.05.
- Playbook anchor_dx/anchor_dy re-anchoring; FORCE_PLAYBOOK (build_deploy) to isolate one.
- Status: only DEFAULT ships; counters GATED-OFF until live-proven. Selector itself is a controllable layer (could pick a counter-playbook from a detected opponent archetype).

## 3. LLM HYBRID slow-loop (champion/hybrid.py) — GATED-OFF (HYBRID_ENABLED=False)
- MODEL_ID = claude-sonnet-4-6; SLOW_PERIOD_S=8; temperature 0.8; BASE_PERSONA + ROLE_FLAVOR.
- Output schema (attack-only): {attack_zone, push, exploit_opp_id, tempo, notes}; FORBIDDEN_KEYS block defensive perturbation.
- opponent memory via observe(); _HYBRID_TACTICS_ENABLED in policy applies it.
- Prior finding: per-tick LLM WORSE; slow-loop regresses to bland mean. **Re-examination requested (incl. opponent-MODELING vs perturbation).**

## 4. DEPLOY / INFRA knobs (champion/build_deploy.py, deploy/)
- 5 AgentCore runtimes (1/player), direct_code_deploy, PYTHON_3_10, arm64, PUBLIC, NO_MEMORY, observability.
- FCTICK_ENABLED (currently True, TEMP for data collection — revert before tournament).
- run_match.py variant {balanced|aggressive|defensive}; one match at a time.

## 5. DATA / CALIBRATION pipeline (champion/deploy/)
- FCTICK GK collector → calibrate_shots.py (fit GOAL_HALF_WIDTH + shot gates from real ball-z) — **BUILT, NEVER RUN on real data** (synthetic-only validated). This is the one UNTUNED-on-real-data path.
- coverage_audit.py (swarm/degenerate fuzzer), diagnose_counter.py (in-behind% from FCTICK).

## OPEN QUESTIONS FOR THE COMPLETENESS AUDIT
1. What controllable surface is MISSING from this catalog (engine endpoints under-used: INTERCEPT, SHOOT power/aim, GK distribution, kickoff/restart, stamina, mid-match formation)?
2. Is the LLM hybrid genuinely dead, or is there a positive-EV formulation (slow-loop OPPONENT-MODELING → counter-playbook selection, distinct from per-tick perturbation)?
3. Lever A+B null: did the through-ball EVER fire (static analysis of the success>0.50 gate vs real pass-success distribution)? Inert(bug) or disproven?
4. Given aggressive is the bottleneck and creation levers failed twice, what is the HIGHEST-EV unexplored lever (finishing-quality/shot-power, defensive solidity to win low-scoring shootouts, GK fast-distribution, stamina tempo)?
