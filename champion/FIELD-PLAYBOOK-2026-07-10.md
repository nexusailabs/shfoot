# FIELD PLAYBOOK — Football Cup, 2026-07-10 (Thailand, live-ready)

Built overnight from a 3-signal synthesis: (A) replay of the REAL policy over 2131 live ticks,
(B) a read of every archived match, (C) an 80-match aggressive telemetry aggregation + Codex EV audit.
Everything here is offline-derived — **outcomes still need live validation** (positions in replay are
frozen; §0 rule). This doc tells you what to deploy, in what order, and how to judge it by MECHANISM.

---

## 0. TL;DR — the win formula is in the data

Over **80 unique matches vs the only real threat (aggressive "Total Attack United"): 27W-9D-44L (38%)**.
The WIN/LOSS discriminators are unambiguous:

| metric (avg/match) | WIN (n=27) | LOSS (n=44) | reading |
|---|---:|---:|---|
| **opponent shots ON TARGET** | **1.9** | **3.9** | ← THE lever: hold them to ≤2 and we win |
| **our shots ON TARGET** | **3.2** | 1.7 | need ≥3; our finishing when on-target is fine |
| PRESS_BALL cmds | 159 | **169** | losses OVER-press (chase, leave free shooters) |
| SHOOT cmds | 57 | **61** | losses shot-SPAM (doesn't help) |
| MOVE_TO cmds | 185 | **203** | losses = more chasing / out of shape |

**Win = defensive solidity (cut opp on-target) + retain the ball. Lose = over-press, shot-spam, chase.**
So the highest-EV move is NOT more attack and NOT more defenders — it is **goal-side cover on turnover +
ball retention + press discipline.** We already dominate the other two opponents (balanced 2-0/3-0, defensive
4-0/5-0); aggressive is where every point is decided.

**DEPLOY ORDER TOMORROW** (each = flag flip, rebuild, deploy, 2 live matches, judge by mechanism):
1. **Baseline** the shipped DEFAULT vs aggressive (2 matches, FCTICK on) — get the mechanism reference.
2. **`Y_evade_recovery`** (lead) — the two best-evidenced levers combined, never tested together. Cut opp on-target + retain.
3. **`GK_fastlaunch`** (Codex's #1 EV, +8-12pp) — GK possession → immediate long counter vs a committed press. Built + flag-gated + contract-tested tonight (`GK_FASTLAUNCH_ENABLED`). Stacks on Y.
4. If time: **`F_creation_max`** (now with the gate lowered — see §9 Q2) or **`E_patient_finish`** (kill shot-spam).
Keep **DEFAULT for balanced/defensive** — do not fix what wins 4-0. **Never deploy High-Press-Gegen** (both signals: over-press = losing).

---

## 1. The only opponent that matters

Three fixed practice archetypes = the tournament field:
- **The Benchmark FC (balanced/possession)** — we win every post-bug meeting 2-0/3-0/4-0, often on 29% possession. Solved.
- **Fort Knox Athletic (defensive low-block)** — we win 4-0/4-1/5-0/6-0 with patient MARK-heavy build-up. Solved.
- **Total Attack United (aggressive flooder)** — 38% coin-flip. **All losses live here.** In a 2-min game every real opponent attacks, so *our aggressive number ≈ our tournament number.*

Free-shooter incidence when they have the ball in our half: **63–78%** (from FCTICK position analysis). That
is the leak the 3.9-on-target losses come from.

---

## 2. The evidence ladder per lever (live A/B history, aggressive)

| lever (config arm) | live record | rate | verdict |
|---|---|---:|---|
| **DRIBBLE_EVADE** (`AB-EVADE`) | 7W-2D-7L | **50%** | BEST arm — retention cuts opp transitions |
| **RECOVERY_DEF** targeted goal-side cover (`AB-RECOVERY`) | 3W-1D-4L | 43% | above baseline (n=8 small) + **offline-proven** (§3) |
| creation levers A+B (`AB-LEVERS`) | 3W-4D-5L | 37.5% | inconclusive, many draws; unproven |
| blanket move-cover (`AB-MOVECOVER`) | 5W-1D-10L | 33% | **WORSE — the "add cover everywhere" trap** |
| move-only positioning (`AB-MOVEONLY`) | 3W-0D-7L | 30% | **WORSE — the "add bodies" trap** |
| baseline default | 27W-9D-44L | 38% | reference |

**Critical distinction:** *targeted* recovery (FWD drops goal-side only when pinned deep, 43%) beats *blanket*
move-cover (33%). The fix is CONDITIONAL cover on turnover, never always-on extra bodies (2-1-1 also proven worse).

---

## 3. Offline replay evidence (2131 real ticks, the trustworthy signal)

`champion/preset_eval.py` re-runs the REAL `command()` over every archived live tick and measures how each
preset changes the bot's DECISIONS on identical states. Result: **the one mechanism that provably responds is
goal-side recovery cover.**

| preset | recovery-cover cmds | vs baseline |
|---|---:|---|
| presets with `RECOVERY_DEF_ENABLED` (H, D, B, Z) | **420–427** | **+19%** |
| all others incl. baseline (A, C, E, F, G) | 359 | — |

Shots (17), forward-depth (3.01), direct-balls (89) are **flat across all presets** — because with frozen
positions the carrier's on-ball decision and off-ball run *targets* barely change the command. **Honest
conclusion: defensive solidity is offline-provable; attack/creation is NOT (needs live).** This is why the
lead candidate leans defensive/retention, where evidence exists, not on an unproven attacking gamble.

---

## 4. The portfolio — 9 coherent presets (in `champion/preset_eval.py::PRESETS`)

Each is a full coherent tactic (knob set), flag-gated, DEFAULT always available as rollback. Enable a preset
by setting its knobs in `policy_v2.py` (or wire it as a selector playbook — see §6). File:lines are the knobs.

**★ LEAD — `Y_evade_recovery`** (build this; it's the two best arms combined, untested together):
- `DRIBBLE_EVADE_ENABLED=True` (`policy_v2.py:300`) + `RECOVERY_DEF_ENABLED=True` (`:313`) + `RECOVERY_BALL_DEPTH=0.20` (`:314`).
- Beats: aggressive flooder. Mechanism: fewer turnovers (evade) → fewer opp transitions; goal-side cover when pinned → cut opp on-target 3.9→~2. Risk: low (both individually ≥ baseline; combo unproven).

**Also-rank:**
- **`H_recovery_solid`** — `RECOVERY_DEF_ENABLED=True` + `RECOVERY_BALL_DEPTH=0.20`. Offline-proven cover +19%. Safe.
- **`G_evade_retention`** — `DRIBBLE_EVADE_ENABLED=True`. Best single live arm (50%). Safe.
- **`E_patient_finish`** — FWD `risk 0.55→0.30` (`:138-139`), `SHOOT_MIN_PROB 0.42→0.48` (`:238`), `CARRY_TO_SHOOT_DIST 0.62→0.72` (`:240`). Kills the shot-spam the LOSS data flags (61 SHOOT). Risk: fewer shots.
- **`F_creation_max`** — `INBEHIND_RUN_ENABLED=True` (`:290`) + `THROUGHBALL_EV_ENABLED=True` (`:291`) + weight 0.8. Honest retest of the "creation is dead" claim — it rested on the BROKEN sweep (§5). Needs live. (Codex Q2 will say if the through-ball gate is even reachable — fold in.)
- **`C_front_two_overload`** — strikers higher + in-behind. For a stubborn low-block only (we already win those; low priority).
- **`D_low_block_direct`** — deep + counter. Only if we meet a possession side that outplays us (unlikely; we win balanced).
- **`B_high_press_gegen`** — ⚠️ **DEMOTED. Over-pressing correlates with LOSING** (press 169 in losses). Do NOT deploy vs aggressive. Kept only as a documented dead-end.

---

## 5. What was broken (so we don't trust old conclusions)

- **The offline sweep was inert.** `sim2.py` did `import policy_v2` while `sweep.py` did `import champion.policy_v2`
  → two module objects → knob mutations never reached the sim; all configs came out byte-identical. So the
  2026-06-26 "6 levers all fail, lock a742108" finding **measured the unchanged default 6×** — it does not
  disprove anything. FIXED (`sim2.py:36` import shim). Even fixed, sim2 physics reward constant-shooters
  (champion scores ~0 vs a naive shoot-bot) → sweep stays a weak tertiary signal; **replay + live history rule.**

---

## 6. Per-opponent decision tree (live)

```
observe opponent first ~8s (SCOUT), then:
  aggressive flooder (≥3 opp in our half, high press)  -> Y_evade_recovery   (cut opp on-target + retain)
  defensive low-block (opp sits, opp shots ~0)          -> DEFAULT 1-1-2       (already wins 4-0/5-0)
  balanced possession (move-heavy, ~0 press)            -> DEFAULT 1-1-2       (already wins on 29% poss)
```
The selector (`selector.py`) already classifies these (thresholds `:39-44`); today only DEFAULT ships enabled.
To make the tree live: wire `Y_evade_recovery` as a selector playbook enabled for the aggressive class only.
(Overnight I keep it as a single global config for a clean A/B; selector wiring is §7 task if time.)

---

## 7. GO-LIVE RUNBOOK (morning, needs fresh creds)

1. **Creds**: desktop-control → Workshop Studio login → OTP to event email → `pbpaste > /tmp/awsenv` → verify sts.
2. **Deploy DEFAULT + FCTICK on** (build_deploy.py:54 already True):
   `set -a; . /tmp/awsenv; set +a; export PATH=$PWD/_build/tk-venv/bin:$PATH; python3 champion/build_deploy.py && bash champion/deploy/local-deploy.sh`
3. **Baseline**: `python3 champion/deploy/run_match.py aggressive` ×2. Pull FCTICK, note **opp-on-target + free-shooter%**.
4. **Flip to `Y_evade_recovery`** (set the 3 flags in policy_v2.py), rebuild+deploy, run ×2 aggressive.
   **JUDGE BY MECHANISM, not scoreline**: did opp-on-target drop toward ≤2? did free-shooter% fall? did we keep the ball (fewer turnovers)?
5. Keep the arm that cuts opp-on-target most. **Before tournament lock: `FCTICK_ENABLED=False` (build_deploy.py:54), redeploy** (clean hot path).
6. **Rollback** is always DEFAULT (commit a742108) — flip all flags off.

---

## 8. Finishing calibration (the other half of the win formula)
`calibrate_shots.py` has NEVER run on real FCTICK. us-on-target (3.2 win vs 1.7 loss) is half the formula.
One FCTICK collection tomorrow → tune `GOAL_HALF_WIDTH` (1.0 untuned) + SHOOT power. Cheap, proven-only.

---

## 9. CODEX FOLD-IN — 3-signal synthesis (replay + live-history + Codex `_build/CODEX-EV-RESULT.md`)

**Where all signals AGREE (high confidence):**
- **sweep is VOID** (Codex confirmed distinct module objects + reproduced identical output). sim2 also uses the
  OLD 55×35 scale (`sim2.py:38`) while the policy is 6.4 (`policy_v2.py:44`) → sim2 is smoke/invariant only,
  NOT for ranking. **replay + live telemetry are the trustworthy signals** (both used here).
- **High-Press-Gegen is the WORST option.** Codex ranks it #8 (-5..+3pp); the 80-match telemetry shows losses
  over-press (169 vs 159). Do not deploy it. Over-committing the press is the free-shooter cause, not the cure.
- **Cut free-shooters = highest-value defensive mechanism.** Codex's #3 lever + my #1 telemetry discriminator
  (opp on-target 1.9 win vs 3.9 loss) + replay (recovery cover +19%) all point to conditional goal-side cover.

**NEW from Codex (not on my radar) — `GK_fastlaunch`, EV #1 (+8-12pp):** turn GK possession/goal-kicks into an
immediate long counter to the most-advanced FWD when opponents are committed, instead of safe recycle. Needs a
CODE branch (not a flag) — built tonight as `GK_FASTLAUNCH_ENABLED` (default OFF, DEFAULT byte-identical,
contract-tested). Highest upside of anything in the portfolio; unverified engine KICK accuracy is the only risk.

**CONFLICT resolved — 2-1-1 / extra bodies:** Codex's #3 "Low-Block Direct" uses the 2-1-1 formation
(`TWO_STRIKER_COVER`). My LIVE telemetry contradicts that specific choice: 2-1-1 / blanket move-cover arms went
30-33% (worse). **Resolution: take the RECOVERY_DEF half, drop the 2-1-1 half.** `Y_evade_recovery` expresses
the same "cut free-shooters" mechanism WITHOUT a formation change — the evidence-safe version. (Real-match data
outranks a mechanism estimate when they disagree.)

**Q2 (creation levers) — over-gated, NOT disproven:** the through-ball needs `success>0.50` but a defended
in-behind lane computes ~0.43 (`policy_v2.py:620` pass math; real tick `_build/ticks_counter_off.jsonl:67`).
So `F_creation_max` now ALSO lowers `COUNTER_THROUGH_MIN_SUCCESS→0.44` (else the flags are inert). Codex's
better fix: add an aerial/space-ball path (distance-only success, like the counter long-ball at `:976-994`) —
a follow-up if F shows life live.

**Q3 endpoint EV (unexplored surface, ranked):** 1) GK fast-launch (built), 2) keeper-away aim (make far-post
explicit; engine-unverified), 3) INTERCEPT for loose balls only — NOT as a carrier presser (swarm risk),
4) SHOOT power (raise close floor `0.70+dist/_sx(1.30)`), 5) stamina late-burst via game-mode ramp.

**Codex's EV-ranked portfolio (mechanism estimates vs aggressive), cross-checked:**
`GK-fastlaunch #1 (+8-12) · HighPress-Beater-A+B #2 (+6-10) · LowBlock+Recovery #3 (+4-8) · Sharp-Counter-gate-lower
#4 (+3-6) · Patient-Finish #5 (+2-4) · Finishing-Maxed #6 · Front-Two #7 · High-Press-Gegen #8 (negative)`.
My live-data adjustment: promote retention (EVADE 50% arm) into the lead combo `Y`; keep 2-1-1 OUT.

**FINAL tomorrow order:** baseline → `Y_evade_recovery` → `GK_fastlaunch` (stack on Y) → `F_creation_max`(gated) /
`E_patient_finish`. Judge every arm on opp-on-target↓ + free-shooter%↓, not scoreline. DEFAULT is always rollback.
