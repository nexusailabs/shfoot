# Football Cup — §9 CORRECTION + IMPROVEMENT PLAN (2026-06-25, 3-Opus panel + Codex-gated)

Supersedes the "certainty / no lever moves it / 50% is the GAME's ceiling" conclusion in PLAYBOOK.md §9.
Built from a 3-lens Opus deep-think panel (stats / tactics / red-team), every claim code- or data-grounded.
**Status: PLAN — 0% until a live powered A/B confirms it (§13 anti-accretion). Shipped build a742108 stays the tournament entry until a flag-gated lever beats it outside CI.**

---

## 1. WHAT WAS WRONG IN §9 (the correction)

§9 claimed aggressive is a ~50% shootout whose ceiling is **the game, not our policy**, and that **"no lever moves it"** was PROVEN. Two independent errors:

### 1a. The A/Bs were statistically powerless (stats lens, quantified)
- Every "lever doesn't work" verdict was **n≈3–4 matches/arm**, decided on **W/L scoreline** — the noisiest metric available.
- Power to detect a true **+20%p** win-rate edge at n=4: **8%** (92% miss). To detect +10%p you need **~388/arm**; +15%p **~170**; +20%p **~93**.
- 95% CI on our own aggressive win-rate from the actual sample (3W-4L pooled): **[10%, 82%]** — cannot distinguish domination from parity from losing.
- **"No lever moves it" and "we had no power to see any lever move it" are statistically indistinguishable here.** A tournament-decisive +10–15%p lever would be invisible >90% of the time.
- Mechanistic metric variance (over 7 pooled matches): **opp-shots-conceded sd=1.25 ≪ us-shots sd=2.13 ≈ goal-margin sd=1.99 ≪ W/L**. We A/B'd on the worst signal while the best one sat in the same JSON.

### 1b. The SUSTAINED-POSSESSION creation lever was never tested (tactics lens, code-grounded)
§9 says the fast-transition counter "targeted exactly [in-behind] and STILL didn't move it." This is **misleading**: a **deep-turnover** in-behind counter WAS tested ON/OFF (2W-2L vs 2W-2L, CAB-ON/CAB-OFF) — but the **sustained final-third in-behind creation lever was never tested**, because:
- The counter (`_counter_opportunity`, policy_v2.py:802–815) is gated to **deep turnovers**: requires `we_have_ball AND ball in OUR half (line 812) AND ≥2 opp committed`. And it ships **DISABLED** (`COUNTER_MODE_ENABLED=False`, line 270).
- The real cap is **sustained final-third possession**, governed by `_support_run` (788–795). Its final-third FWD target is `opp_goal_x - dir*_sx(0.10)` ≈ **x=5.76**, while the away last line sits at **x≈6.4** → the FWD outlet always arrives **~0.64u IN FRONT of the last defender, never beyond it.** No through-ball term rewards a receiver past the deepest defender (`_pass_ev` :1157–1161, `chance_opts` :1140).
- Live tick data (`_build/ticks_*.jsonl`): in sustained final-third possession a FWD is genuinely beyond the last away outfielder only **0–18% of ticks**. The "79% break forward" is loose-ball advancement, NOT a timed in-behind run.
- → The tested counter was the **wrong trigger LOCATION** (deep turnover, and shipped disabled). The diagnosed cap — the **sustained-possession** final-third outlet sitting 0.64u short of the last line — is **genuinely unsolved and untested.**

**Honest stance: UNCERTAINTY, not certainty.** DEFAULT 1-1-2 ships because it is the safe, robust default that dominates balanced/defensive — **not** because aggressive levers were shown ineffective.

---

## 2. WHAT IS STILL SOUND IN §9 (do NOT re-chase — mechanistically credible rejections)
- **2-1-1 extra defender** → us-shots 3.7/m & conv 27% vs DEFAULT 4.6/m & 59%: directionally kills our attack. Reject.
- **per-tick LLM (Nova/Sonnet)** → suppresses/perturbs a near-optimal policy. Reject (prior, weak data, but mechanism credible).
- **shoot-more (loosen gates)** → us-shots barely moved & conversion FELL 59%→38%: the gate was not the bottleneck. Reject (soundest null).
- **DROP_MARK_ENABLED=True** stays (A/B-proven OFF made aggressive worse).
- **latency ~900ms** platform-bound, non-issue. Settled.

---

## 3. THE IMPROVEMENT PLAN — attack the UNTESTED creation cap, flag-gated, correctly-powered

### 3a. Code levers (all pure-deterministic, NO opponent-label gating, each behind its OWN new explicit OFF flag)
> NOTE: A/B/D need NEW explicit flags (e.g. `INBEHIND_RUN_ENABLED`, `THROUGHBALL_EV_ENABLED`, `DEPTH_RUNNER_ENABLED`) — they are not covered by the existing COUNTER/SELECTOR flags. Add the flag default-False with the lever.
| # | Lever | Hook (file:line) | Runtime trigger | Single metric it must move | Overfit risk |
|---|---|---|---|---|---|
| **A** | Push FWD final-third outlet BEYOND the last line: target `min(goalline-0.05, last_away_def_x + _sx(0.08))` instead of fixed 5.76 | `_support_run` :793–794 | always-on; final-third + spare FWD runner; reads LIVE deepest-away-defender x | in-behind% (0–18 → >40) | LOW (pure geometry off live x) |
| **B** | In-behind through-ball EV reward: `+W*(receiver.x beyond deepest away outfielder)*receiver.success` | `_pass_ev` :1157–1161 + `chance_opts` :1140 | fires ONLY when a runner is actually past the last line | in-behind shot count | LOW-MED (needs A to supply runner) |
| **D** | Stagger 2nd FWD as depth runner, opposite channel `last_line_x + _sx(0.10)` | `_support_run` :788–795 | always-on, two-FWD only | 2nd-runner availability | LOW |
| **C** | Calibrate `GOAL_HALF_WIDTH` + shot gates from REAL goal-crossing ball-z (never Benchmark-scoreline) | const :49; `calibrate_shots.py` | offline, no runtime gate; bound change to ±0.15 | conversion% on taken shots | MED (small sample — bound it) |

**Ship A+B together as one vertical slice** (A = supply, B = demand). D = cheap insurance. C = free de-risk, do once, but it's a tune (~few %), not the matchup flip. **Anti-swarm single-presser invariant (`_ball_rank`) MUST stay intact** — A/B/D move off-ball RUN targets only, never add a 2nd presser. Verify with `coverage_audit.py` swarm leaks = 0 (arch-test, not a comment).

### 3b. Correctly-powered A/B protocol (the real fix — re-open MEASUREMENT before CODE)
1. **Powered baseline FIRST:** run the SHIPPED a742108 config **≥12 aggressive matches**, log win% + 95% CI + mechanistic metrics. This alone tells us if the ceiling claim survives contact with data.
2. **Primary metric: opp-shots conceded/match** (total opp shots, sd=1.25 — lowest variance of the available metrics; opp-shots-on-target is even tighter if the match record exposes it). **Co-primary: us-shots + conversion%** (shot events accumulate ~5–9×/match → real binomial resolution). **Composite: expected goal-diff = us_shots·conv − opp_shots·oppConv.** **W/L = confirmatory ONLY, never the decision metric.**
3. **n ≥12/arm (20 if budget).** Interleave A↔B to cancel server drift. **Pre-register ONE primary metric + a one-sided rule** before running.
4. **Promotion rule (Benchmark-PROVISIONAL only):** flip a lever's flag to ON only if it beats DEFAULT **outside the baseline CI** (e.g. opp-shots ↓≥1.5/m OR xG-diff ↑≥0.5 at p<.10) AND keeps **zero regression vs balanced AND defensive** (≥3 matches each, must stay wins). A pass here proves "better vs the fixed Benchmark," NOT "robust vs an adapting expert" — Benchmark is the only sparring partner, so promotion is provisional and the lever stays flagged for re-check against real opponents in the tournament.
5. **Stop rule:** 2 levers that fail the CI test → close it, ship a742108. Do not keep twiddling (`feedback_regress_to_mean_use_proxy`: the pull to keep tuning IS the trap).

### 3c. Hard guardrails (red-team, all measurable)
- Calibration uses a **real goal-event ball-z capture**, never Benchmark-scoreline fitting (§8 rule).
- Any lever **ships behind its own new explicit default-OFF flag**; tournament entry stays a742108 until the (Benchmark-provisional) promotion rule passes.
- **Anti-swarm invariant = arch-test** (coverage_audit swarm leaks 0).
- Must keep balanced/defensive domination — the ACTUAL edge (most opponents guess wrong and lose there).

---

## 4. HONEST PROBABILITY & FRAMING
- Red-team estimate the creation lever actually tilts aggressive >50%: **~15–20%.** The symmetric-game ceiling case is real; but the lever was never tested, the finishing item is admittedly open, and "coin-flip vs aggressive" is thin vs adapting experts.
- The cheap, safe, correct first move is **re-open the measurement, not the code**: a powered baseline costs match-runs, not a re-architected tournament binary. If 12 matches show a tight ~50% CI, the ceiling is confirmed on evidence and this plan dies honestly. If it shows 60%+ or a creation-correlated loss pattern, levers A+B earned their A/B.

**Bottom line the operator was right about:** "can't dominate aggressive ⇒ not ready for experts" — but the premise "we proved we can't" was never established; the data couldn't tell domination from parity (CI 10–82%), and the one lever that could move it was never built. Uncertainty supports keeping the flag-gated levers alive for a powered live test, not declaring the ceiling closed.
