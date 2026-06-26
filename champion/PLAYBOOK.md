# Football Cup Champion — PLAYBOOK (authoritative learning doc)

Purpose: let a future session **re-validate the concept from scratch** and **decide which
direction to strengthen**, from evidence. Read this top-to-bottom before changing anything.

Goal (operator): a DETERMINISTIC (zero-LLM) bot that beats strong expert teams in the AWS
Summit Shanghai Agentic Football Cup. "Just win" (scoring rules irrelevant). Benchmark (the
AWS reference bot, 3 style variants) is the ONLY available sparring — beware overfitting to it.

Secrets are NOT in this file. Team code / account / ARNs live in `/tmp/awsenv` and the
gitignored `champion/deploy/run_match.py`. This file is public-safe (github.com/nexusailabs/shfoot).

---

## 0. START HERE — DEFINITIVE STATE & NEXT-SESSION MAP (2026-06-25 marathon, read FIRST)

The 2026-06-25 session settled the core questions with LIVE A/B data. Read §0 fully before touching
anything; §1-§9 are detail/history. ⚠️ §3's ledger shows "4/4 aggressive" — that was later proven to be
VARIANCE (§9). On aggressive, trust §9 over §3.

> ═══════════════════════════════════════════════════════════════════════════════════════════════
> ## ⚡ LATEST SESSION — 2026-06-26/27 — THE AXIS WAS WRONG: it's PASSIVE-vs-SHARP off-ball, not LLM-vs-code
> ═══════════════════════════════════════════════════════════════════════════════════════════════
> **Read this FIRST — it supersedes the framing below.** Commits `3eaf110` (LLM recover hybrid) →
> `03c14c5` (sharp deterministic off-ball — THE build). Branch feat/champion-tactical-layer.
>
> ### The reframe (operator's call, vindicated by data)
> Six deterministic levers + the LLM hybrid all explored only "MORE ATTACK". The whole session had been
> chasing **win% vs the aggressive sparring bot — which is PURE NOISE** (n≈12, ~8% power; ±6 goal variance).
> The operator's frustration ("왜 갈피를 못잡냐") was correct: **we had NEVER WATCHED THE BOT PLAY.**
> The real axis is not "LLM brain vs code brain" — it is **bland/passive play vs sharp/decisive play.**
> The operator's own key insight: **the LLM hybrid was scrapped because it REGRESSES TO A NEUTRAL MEAN** —
> i.e. LLM is the WRONG tool for "정말 컴퓨터처럼 날카롭게" decisive play. Deterministic is the right tool.
>
> ### Pure-LLM record CORRECTED (the "LLM won" memory)
> Operator recalled pure-LLM (prompt-only, sample-style) "winning 4-0". Verified from _build/SAMPLE-LLM*.md:
> those 4-0/5-0 wins were vs **balanced/defensive** (every build beats those). **vs aggressive, pure LLM
> went 2W-4L (33%)**; deterministic pooled ~60%. AND pure-LLM averaged **845ms/tick (one agent 9493ms) ≫
> the <500ms budget** → it plays a tick behind → fatal vs a fast flooder. So per-tick LLM is OFF THE TABLE;
> the only way to use LLM is the two-timescale hybrid (deterministic per-tick + slow loop off critical path).
>
> ### §0 TREASURE: replay the bot through its own policy (champion/_build/LIVE-FCTICK.jsonl, a real 1-2 loss)
> Reconstruct each tick's gameState and re-run policy_v2.command() on it. Measured behaviour:
> - **49% of the match is loose-ball, but we contested only 3% of those ticks** — held anchor shape, let it sit.
> - **135 MARK commands/match are ENGINE NO-OPS** (49 vs-carrier + 86 loose) → "marking" defence was FICTION;
>   the marker idled while the man got free → **63% of opponent-in-our-half ticks had a FREE SHOOTER.**
> - **Attack was already fine** — 100% of our possession ticks had shot/pass/sprint intent. The leak is OFF-BALL.
>
> ### What shipped (commit 03c14c5) — sharp deterministic OFF-BALL, two safe high-value fixes
> 1. **`MARK_AS_MOVE_COVER = True`** — every MARK now executes as a goal-side MOVE-cover (carries
>    target_player_id for coordination) so defenders PHYSICALLY get between man and goal. Replay: no-op MARK 135→0.
> 2. **Loose-ball contest** (new block in decide(), after _center_restart): when NEITHER team possesses, the
>    closest outfielder (2 in our half) sprints onto the ball / PRESSES. Does NOT touch the anti-swarm
>    single-presser rule (that guards swarming a CARRIER; a loose ball has none). Replay: contest 3%→17%.
> - Contract suite (40+) passes; single-presser + no-double-mark invariants now verified via MOVE-cover
>   target_player_id. New test test_llm_recover_balance_lever + recover validation. sim2 clean (0.038ms/tick).
> - The `3eaf110` LLM hybrid (HYBRID_ENABLED=True; LLM sets ONLY a `recover` 0..1 balance dial off the
>   critical path; fail-safe to NEUTRAL==baseline) is now SECONDARY — the deterministic fixes carry the defence.
>
> ### ⚠️ HONEST validation scope (no blind win%-chasing)
> The replay PROVES the COMMAND behaviour changed (idle/no-op → real cover/contest) — deterministic, certain.
> It CANNOT prove the OUTCOME (free-shooter%, goals): replay positions are HISTORICAL/FROZEN, so re-running the
> policy can't move the players. Outcome needs a LIVE match (with FCTICK on, NEW positions evolve).
>
> ### NEXT (in order)
> 1. Deploy (CloudShell deploy-all.sh, fresh hourly creds) + 1-2 LIVE aggressive matches. Judge on the
>    **MECHANISM via fresh FCTICK** (free-shooter%, loose-ball win-rate, goal-side count) — NOT noisy win%.
> 2. If live STILL shows free-shooters → add task: **turnover counter-press** (relax single-presser to 2 in our
>    third only). DEFERRED now (reverted-2nd-presser regression risk; needs live evidence first).
> 3. Before final tournament lock: revert **FCTICK_ENABLED=False** (clean hot path).
>
> ### MANAGER WHOLE-PICTURE + L2 (2026-06-27, operator: "정말 축구 감독으로 전체 그림")
> Operator goal clarified: a COMPLETE deterministic football manager — every role (GK/DEF/MID/FWD) perfect,
> all knobs mapped, + phase tactics (attack when we hold; on losing it, win-back + COUNTER choosing
> LONG-BALL vs THROUGH-PASS vs CARRY). Answer: ACHIEVABLE — the machinery mostly EXISTS, just flag-off /
> un-tuned / never assembled+watched as a manager. Evidence = Opus whole-picture map + an independent
> Codex audit (`champion/_build/CODEX-MANAGER-AUDIT-RESULT.md`, gpt-5.5 high, MCP-off): ~50 knobs inventory,
> phase×role decision matrix, gaps, top-5 levers — all file:line, cross-checked vs the Opus map (agreement).
> Codex headline finding: of "롱볼 vs 스루", LONG-BALL was the ONE missing piece (counter force-labelled THROUGH).
>
> **The manager build is LAYERED (one lever at a time, flag-gated, each validated):**
> - **L0** `3eaf110` LLM recover hybrid (HYBRID_ENABLED=True; off-critical-path `recover` dial; fail-safe=baseline).
> - **L1** `03c14c5` sharp OFF-BALL: MARK_AS_MOVE_COVER=True (no-op MARK 135→0) + loose-ball contest (3%→17%).
> - **L2** `cbe7ada` COUNTER-ATTACK: COUNTER_MODE_ENABLED=True + the LONG-BALL/THROUGH/CARRY selector. A runner
>   PAST THE LAST OUTFIELD LINE (opp GK excluded — fixed bug that made "in behind" impossible) → lofted AERIAL
>   scored on distance only (clears ground interceptors); nearer in-behind → GROUND/THROUGH; none → carry. New
>   knobs COUNTER_LONGBALL_DIST=0.55, COUNTER_AERIAL_MIN_SUCCESS=0.20. Contract+probe validated; replay 1675
>   decisions no crash; counter did NOT trigger on that one frozen match (needs deep ball-win + ≥2 opp committed).
>
> **⚠️ STATE: 3 layers stacked, ALL offline-validated ONLY (contract + probe + replay command-behaviour). NONE
> live-validated** — the event is OVER, so the only remaining test is REAL COMPETITION. The §3 discipline note:
> stacking unvalidated levers means we can't attribute effect; in real matches, watch the MECHANISM via FCTICK
> (free-shooter%↓, loose-ball win-rate↑, does COUNTER fire + pick long/through sensibly) NOT noisy win%.
>
> **REMAINING LAYERS (not built): L3 creation in-behind (INBEHIND_RUN+THROUGHBALL_EV), L4 deterministic
> recovery (drop the LLM gate; RECOVERY_DEF_ENABLED or a deterministic free-shooter trigger), L5 tune the 30
> RoleConfig positional knobs as a coherent set. Selector counters (TWO_STRIKER_COVER/HIGH_PRESS_BEATER)
> remain enabled=False.**
>
> **BEFORE REAL COMPETITION:** revert `FCTICK_ENABLED=False` (build_deploy.py:48) for a clean hot path; redeploy
> via CloudShell `deploy-all.sh` (fresh hourly creds); confirm `bedrock:InvokeModel` on the agent role if you
> want L0's slow loop to actually fire (else it fail-safes to baseline — harmless). Branch feat/champion-tactical-layer.
>
> ### META-LESSON (the real fix for directionlessness)
> Blind win%-tuning on a noise-dominated metric = the cause of the flailing. The cure was the §0 move applied
> to GAMEPLAY: **watch what the bot actually does** (replay through the policy), find concrete behavioural
> failures, fix those deterministically. Watch the behaviour, not the scoreline.
> ═══════════════════════════════════════════════════════════════════════════════════════════════

> ⚠️⚠️ **CORRECTION (2026-06-25, 3-Opus panel + Codex-gated) — §9's "no lever moves it / 50% is the GAME's
> ceiling, PROVEN" is DOWNGRADED from certainty to UNCERTAINTY.** Two verified errors: (1) every "lever
> doesn't work" A/B was n≈3-4/arm on W/L scoreline = ~8% power to detect even a +20%p edge (95% CI on our
> own aggressive win-rate = [10%, 82%] — can't tell domination from parity); (2) the **sustained-possession**
> in-behind creation lever was NEVER tested — the failed counter was gated to deep turnovers (`_counter_opportunity`
> ball-in-our-half, policy_v2.py:812) and shipped disabled, while the real cap (`_support_run` final-third FWD
> outlet sits at x≈5.76, 0.64u SHORT of the last line at ~6.4) is untested. DEFAULT 1-1-2 still SHIPS (safe robust
> default that dominates balanced/defensive), but NOT because aggressive levers were disproven. **Authoritative
> next-step doc = `champion/IMPROVEMENT-PLAN.md`** (powered xG-based A/B protocol + flag-gated creation levers A/B/C/D).
> Trust IMPROVEMENT-PLAN over §9 on the ceiling claim.

### A. WHAT SHIPS (live: account <workshop-account-in-/tmp/awsenv>; branch feat/champion-tactical-layer; commit a742108; pushed)
Pure DETERMINISTIC DEFAULT **1-1-2 attack-always** (champion/policy_v2.py):
- 1-1-2 (GK0/DEF1/MID2/FWD1·2). Attack-always game mode (never sit on a lead in a 2-min match).
- SHOOT gates SHOOT_MIN_PROB=0.42 / SHOT_REAL_CHANCE_DIST=0.43 (proven — do NOT loosen, see §0.C).
- anti-swarm single-presser · anti-exploitation mixing · multi-marker coordination · carrier reservation.
- ALL experimental levers shipped OFF behind one-line flags: COUNTER_MODE_ENABLED, SELECTOR counters
  (enabled=False), HYBRID_ENABLED, FCTICK_ENABLED.

### B. DEFINITIVE FINDINGS (proven — do NOT re-litigate)
1. DETERMINISTIC > LLM here: we beat the LLM-only build 4/4 vs 0/4 on aggressive. Per-tick LLM is
   spatially imprecise + slow + regresses to a bland/defensive MEAN that loses the shootout.
2. attack-always is correct (2-min sprint: protecting a lead invites the equalizer).
3. precision + variance don't coexist: an LLM perturbing a near-optimal policy is downhill. LLM value
   needs HEADROOM (an ADAPTING opponent) that fixed Benchmark doesn't provide.
4. latency ~900ms is PLATFORM-BOUND (contest game-server transport), parity, graded "excellent" = NON-issue.
5. We DOMINATE balanced/defensive (4-0/6-0). AGGRESSIVE = the MODAL opponent (everyone attacks in 2 min)
   = a ~50% HIGH-VARIANCE SHOOTOUT whose ceiling is the GAME, not our policy (§9).

### C. DO NOT RE-CHASE (mechanistically-credible rejections — but see CORRECTION: these were UNDERPOWERED)
2-1-1/extra defender → WORSE (us-shots 3.7/m, conv 27% — directionally credible kill) · LLM adaptation
(Nova/Sonnet) → WORSE/no benefit · shoot-more (loosen gates) → NO DIFF (us-shots flat, conv FELL 59%→38%;
gate wasn't the bottleneck; reverted). These rejections rest on a MECHANISTIC metric (shot-rate), so they stand.
⚠️ BUT the **fast-transition counter "NO DIFF (2W-2L vs 2W-2L)"** does NOT close the creation question: that
counter fired only on DEEP TURNOVERS (disabled at ship), NOT the sustained-possession final-third in-behind run
that is the actual diagnosed cap. Creation during sustained possession is OPEN, not disproven (→ IMPROVEMENT-PLAN, levers A+B).

### D. THE OPEN LEVERS (not taken to completion — see champion/IMPROVEMENT-PLAN.md for the full plan)
1. **Sustained-possession in-behind CREATION** (the dominant leak; never tested). FWD final-third outlet sits
   0.64u short of the last line + no through-ball EV term rewards a runner past the deepest defender. Levers
   A (push outlet beyond live last-line x) + B (in-behind through-ball EV) attack exactly this. Flag-gated, A/B-gated.
2. **HARD shot-model calibration** from real data. Pipeline built+validated (calibrate_shots.py consumes FCTICK);
   measured 30% conversion vs aggressive on 643 ticks (too few). TODO: 10+ aggressive matches with FCTICK on
   → fit real GOAL_HALF_WIDTH + SHOOT gates → maybe lift finishing. Proportional, proven-only.
3. **The MEASUREMENT itself**: every prior A/B was n≈4/arm on W/L (~8% power). Re-open with a powered protocol
   FIRST (≥12 matches/arm, primary metric = opp-shots-conceded + us-shots/conversion, pre-registered one-sided
   rule, W/L confirmatory only). Powered baseline on the SHIPPED config comes before touching policy_v2.py.

### E. ASSET INVENTORY (flag-gated; how to re-enable)
- SELECTOR (champion/selector.py): pure-from-gameState, team-coherent (all 5 agents agree). PLAYBOOKS
  DEFAULT + TWO_STRIKER_COVER(2-1-1) + HIGH_PRESS_BEATER. Enable a counter ONLY after live A/B proves it
  > DEFAULT on its archetype (Playbook.enabled=True).
- Sonnet HYBRID (champion/hybrid.py): off-path LLM (HYBRID_ENABLED=True). Only worth it vs a genuinely
  ADAPTING expert (untestable on Benchmark). Use STRONG persona + HIGH temp + attack-only schema
  (neutral/low-temp prompt regresses to bland defensive mush — proven).
- FCTICK collector (build_deploy FCTICK_ENABLED=True, GK-only full-state) + calibrate_shots.py +
  diagnose_counter.py. WSS binary decode intractable/unneeded — FCTICK supersedes it (DECODE_STATUS.md).
- COUNTER mode (policy_v2 COUNTER_MODE_ENABLED): in-behind runs + direct ball on a deep turnover.

### F. RUNBOOK (reproduce everything)
- CREDS (expire ~hourly): desktop-control — Workshop Studio Sign in → Email OTP to the operator's event email → read
  OTP from that Gmail → rejoin the event access code (kept LOCAL — in /tmp/awsenv notes or ask operator; NOT in this public file) → "Get AWS CLI credentials" → copy →
  `pbpaste > /tmp/awsenv` → verify sts. (Or operator pastes the export block.)
- DEPLOY: `set -a; . /tmp/awsenv; set +a; export PATH=$PWD/_build/tk-venv/bin:$PATH; python3 champion/build_deploy.py; bash champion/deploy/local-deploy.sh` (~4min, stable ARNs, no portal re-paste).
- MATCH: `python3 champion/deploy/run_match.py aggressive|balanced|defensive` (~4.5min). ONE match/team at a
  time (2nd create errors "already in progress" → retry with backoff).
- A/B a lever: patch its flag (policy_v2/build_deploy), rebuild, deploy arm, run N, compare. FORCE_PLAYBOOK
  (build_deploy) forces a playbook every tick to isolate it (bypasses the classifier).
- CALIBRATE: FCTICK_ENABLED=True → deploy → 10+ matches → pull GK FCTICK from CloudWatch (filter "FCTICK")
  → jsonl→array → `python3 champion/deploy/calibrate_shots.py --ticks <file>`.

### G. POINTERS
- Commits on feat/champion-tactical-layer (pushed to github.com/nexusailabs/shfoot): a742108 (final ship)
  ← 53ea936 (selector) ← 6060769 (pure-det) ← 4cf435d/d763c63/9e59e34 (hybrid).
- Raw A/B + tick evidence (LOCAL ONLY, _build/ gitignored): AB-*.md, SAMPLE-*.md, CAB-*.md, ticks_*.jsonl,
  CODEX-*-RESULT.md.
- kaia saves 333 + 334 (full record). Lesson memory: feedback_regress_to_mean_use_proxy.
- Every correct turn came from the operator's calls (attack-always, no-label-gating, raise-temp, /proxy)
  + LIVE A/B overruling guesses. The /proxy verdict was: SHIP PURE DETERMINISTIC.

---

## 1. VERIFIED GROUND TRUTH (the contract — re-confirm before trusting)

The match runs on a **Unity** engine (game server `wss://game.agentic-football.aws.dev:5245`),
NOT the aws-samples Gateway contract. Verified from on-agent logging (FCDBG/FCPOS) 2026-06-25:

- **Coordinates are SMALL Unity coords, field plane = `player(x,y)` == `ball(x,z)`; `ball.y` is HEIGHT.**
  Measured bounds (400 ticks): player x∈[-6.4,6.4], depth(player.y / ball.z)∈[-3.5,3.6];
  ball x to ±6.86 (into the net); **goal line x=±6.4; goal mouth |z| < ~0.9** (|z|>2.8 = wide).
  → `FIELD_X=6.4, FIELD_Z=3.5, GOAL_HALF_WIDTH=1.0` (estimate; refine to ~0.65-0.8 from goal-event ball-z).
- **obs**: `game_state.ball = {position{x,y,z}, velocity{x,y,z}, isFree, possessionAgentId|null}`;
  `players[] = {teamCode "home"|"away", agentId "agentId_N", position{x,y}, velocity{x,y},
  orientation(deg), stamina(0..1!), currentAction, lastAction, speed, isSprinting}`. 10 players.
  Duplicate agentId across teams (both have agentId_3) → use `possession_holder()` (possessionTeam
  + nearest-to-ball) and object-identity `i_have`, never string-equal (ghost-shoot bug).
- **Commands** (one per player, SSE yield mandatory): MOVE_TO{target_x,target_y,sprint},
  PASS{target_player_id,type}, SHOOT{aim_location TL/TR/BL/BR/CENTER, power 0..1},
  PRESS_BALL{intensity}, MARK{target_player_id,tightness}, INTERCEPT, SLIDE_TACKLE,
  GK_DISTRIBUTE{target_player_id,method}, SET_STANCE.
- **Roster/formation**: 5 players id0=GK,1=DEF,2=MID,3=FWD1,4=FWD2. Portal formations:
  `1-1-2`, `1-2-1`, `2-1-1` (PUT /teams). team0=HOME (own goal -x, attack +x); team1 mirrors x.
- **Latency**: NOT a blocker. Portal grades "<1000ms = excellent"; in-match ~900ms, 100% success.
  (The earlier latency panic was a red herring; the real bug was coordinates.)

**THE KEY LESSON**: a deterministic policy MUST use the real coordinate system. The morning
LLM build won 4-0 only because LLMs don't hard-code coords. Hard-coded geometry on the wrong
scale (we used 55×35, ~8.6× too big) → degenerate play (always-press, ghost-shoot) → losses.

---

## 2. ARCHITECTURE & TECH

```
Unity game server (wss, ~2s ticks) → invokes 5 AgentCore runtimes (1/player, microVM)
  each runtime = src/main.py (@app.entrypoint async, SSE yield) + lib/policy_v2.py
  parse gameState → policy_v2.command(gs, team_id, pid) → yield 1 command  (zero-LLM, ~0.17ms)
```
- Runtime: AWS Bedrock AgentCore, `direct_code_deploy`, PYTHON_3_10, arm64, network PUBLIC,
  NO_MEMORY, observability=true (aws-opentelemetry-distro → CloudWatch). SSE async-gen yield
  REQUIRED (non-stream return fails fitness 0/5).
- Brain `champion/policy_v2.py` (~745 lines, pure stdlib): coord helpers `_sx/_sz` (field-fraction
  scaling), obs adapters, inlined `evaluate_shot`/`calculate_pass_options`/`_intercept_risk`,
  `decide()` ladder (GK → on-ball → off-ball), adaptation (`_press_profile`→directness,
  `_pressure_release_option`, `_support_run`, `_center_restart`, `_shot_is_real_chance`).
- Build: `build_deploy.py` (single source → 5 agent dirs + shared lib). Deploy: `local-deploy.sh`
  (sources /tmp/awsenv → `agentcore deploy --auto-update-on-conflict` ×5, stable ARNs).
- Toolchain: `_build/tk-venv` (agentcore CLI = bedrock-agentcore-starter-toolkit) + system `uv`.

---

## 3. EXPERIMENT LEDGER (cause → effect, all real practice matches vs Benchmark, 1-1-2)

| # | policy version | opponent | score | us shots | opp shots | poss% | PRESS | takeaway |
|---|---|---|---|---|---|---|---|---|
| A | broken coords (55×35) | balanced | **1-3 L** | 0 | 8 | 46 | 203 | swarm + ghost-shoot |
| B | broken coords, 2-1-1 form | balanced | 2-1 W | — | — | — | — | 2 defenders masked the bug |
| C | broken coords | balanced | 1-3 L | 0 | — | 37 | 193 | confirmed broken |
| D | **coord FIX** | balanced | **2-1 W** | 4 | 5 | 32 | 152 | bug was root cause |
| E | coord fix | balanced | 0-0 D | — | — | — | — | variance |
| F | coord fix | balanced | **3-1 W** | 6 | 6 | **60** | — | can dominate |
| G | +goal-max tactics | balanced | **5-1 W** | **9** | 7 | 40 | 200 | finishing+support works |
| H | +goal-max tactics | balanced | **2-0 W** | 5 | 4 | 46 | 169 | clean win |
| I | +goal-max tactics | defensive | **6-0 W** | 9 | 0 | 31 | — | crushes a low block |
| J | +goal-max tactics | **aggressive** | DRAW, weak | **1** | **11** | 57 | — | **WEAKNESS: sterile vs press** |
| K | +press-fix adaptation | aggressive | **5-2 W** | 8 | 7 | 48 | 118 | weakness FIXED |
| L | +press-fix | balanced | **4-0 W** | 6 | 5 | 43 | 207 | no regression |
| M | +press-fix | defensive | **2-0 W** | 6 | 1 | — | — | still wins |
| N | +press-fix | aggressive | **4-1 W** | 8 | 6 | — | — | weakness fix confirmed 2/2 |

**Reading it**: coord fix flipped 0W-3L → wins (D-F). Goal-max tactics (real-chance shot gating
+ support runs) drove shots 4→9 and goals to 5-6 (G-I). The high-press weakness (J: 1 shot, 11
conceded) was fixed by the beat-the-press adaptation (K-N: 5-2, 4-1, 8 shots). Current policy
wins all 3 styles, 2-6 goals/match. Variance exists (E: 0-0) — characterize it next.

Commits: 57320dd (coord fix) · 0eaeed7 (goal-max) · 6ef53aa (press-fix). Earlier: 5c6aa6f/906a034
(observability/latency).

---

## 4. CONCEPT-VALIDATION CHECKLIST (re-confirm from scratch, in order)

Run each; if any fails, STOP and re-derive before tuning tactics.
1. **Creds**: `set -a; . /tmp/awsenv; set +a; _build/tk-venv/bin/python -c "import boto3;print(boto3.client('sts').get_caller_identity()['Account'])"` → the workshop account (matches the one in /tmp/awsenv); else re-grab from the event portal.
2. **Contract tests**: `_build/tk-venv/bin/python champion/test_contract.py` → ALL PASS.
3. **Coords still small?** Deploy with FCPOS logging on, run 1 match, pull FCPOS, confirm player
   x∈~±6.4 (NOT ±55). (Engine could change between events.) Re-measure FIELD_X/Z/goal if drifted.
4. **possession/i_have correct?** FCDBG: on a SHOOT, `holder_pid == my_pid` (no ghost-shoot).
5. **Latency excellent?** match record `*_avg_latency_ms` < 1000 + success_rate 1.0.
6. **Baseline result**: run 1 match vs each variant; expect wins. If losing, the contract drifted
   — re-do step 3-4 (geometry first, ALWAYS — that was the whole lesson).

---

## 5. RUNBOOK (the CLI loop — no browser)

```bash
set -a; . /tmp/awsenv; set +a              # workshop creds (expire hourly; re-grab from portal)
export PATH="$PWD/_build/tk-venv/bin:$PATH"
# edit champion/policy_v2.py → then:
python3 champion/build_deploy.py            # regenerate 5 agents from the single source
bash champion/deploy/local-deploy.sh        # deploy (only when policy changed; ~4min)
python champion/deploy/run_match.py balanced|aggressive|defensive   # create+poll+summary (~4.5min)
# formation: PUT /teams/{id} {formation} via run_match's API helpers
# diagnostics: FCDBG/FCPOS lines in CloudWatch (observability on); pull-fcinst.sh
```
Skip deploy for same-policy re-runs. Match wall ≈ 30s delay + 120s game + finalization ≈ 4.5min.

---

## 6. DIRECTION HYPOTHESES — what to strengthen next (ranked, with rationale)

1. **Characterize & kill variance** (E: 0-0 draw amid wins). Run 3-5 matches/variant, log the
   distribution. If draws correlate with a state (e.g. cold first match, a specific kickoff),
   fix that. Consistency matters more than peak vs experts. [cheap, high value]
2. **Formation A/B** (1-1-2 vs 2-1-1 vs 1-2-1). 2-1-1 (2 defenders) masked the counter even with
   the bug (B). With correct coords, test all three — but FIRST add a formation→role remap in
   policy_v2 (currently hard-coded id1=DEF,id2=MID,id3/4=FWD = 1-1-2 only). [medium]
3. **Shot-model calibration** via the WSS tick collector (champion/deploy/tick_collector.py,
   built + sound but live-unverified). Decode one match → real shot-conversion model → set
   GOAL_HALF_WIDTH + shot thresholds from data, not estimate. Could unlock manufactured goals. [high effort, high ceiling]
4. **Deeper opponent adaptation** (Memory + optionally a slow LLM loop). The lightweight
   deterministic press-adaptation already works; extend to detect formation/tendencies and
   pre-empt. This is the real edge vs *adapting* expert teams. [high effort]
5. **Push goals 6→10** (more aggression) — LAST, and watch for Benchmark overfit. Real experts,
   not Benchmark, are the true test; don't sacrifice robustness for a Benchmark scoreline.

**Anti-overfit guard**: every change must keep wins vs ALL THREE variants. Gate any
opponent-specific behavior behind a runtime estimate (like directness), never a fixed assumption.

---

## 7. KNOWN TRAPS (don't repeat)
- Don't trust `sim2.py` — it's on the OLD 55×35 scale AND a sweep proved it's insensitive to
  tactics. Use REAL matches. (Or rewrite sim2 to the live contract first.)
- Don't tune tactics before re-confirming geometry (§4 step 3). Geometry bug = silent degeneration.
- Don't reintroduce the swarm (DEF must stay home; single-presser = exactly 1 outfielder/tick).
- Don't commit secrets: _build/, run_match.py, tick_collector.py, measure_latency.py are gitignored.
- Codex's proxy gate's `claude -p` fails rc=1 → Codex falls back to direct review/apply (fine);
  always verify Codex output via tests + a real match before committing.

---

## 8. TACTICAL LAYER (2026-06-25 — offline-built + Codex-verified, LIVE-VALIDATION PENDING)

Built this session after a 3-Opus panel + Codex consults concluded: per-tick zero-LLM is correct
(latency is fixed external transport); the next gains are CODE, like building an expert COM in
FIFA/PES — strengthen tactics + make the policy un-exploitable. All pure deterministic code, no LLM.
Verified offline: `test_contract.py` 12/12 + `deploy/coverage_audit.py` (113,400 decisions, swarm
leaks 0). **Still needs a live match to tune (which formation wins, variance, shot calibration).**

**C — tactics (implemented):**
- Formation-agnostic role layer: `FORMATIONS` {1-1-2, 2-1-1, 1-2-1}, `role_for_player()`, role
  groups (`_is_def/_is_mid/_is_fwd`). playerId is separate from tactical slot; **1-1-2 is identity =
  byte-identical to the validated bot.** `ACTIVE_FORMATION` default "1-1-2"; live A/B picks per
  opponent (2-1-1 vs aggressive/two-striker, 1-2-1 vs low block). `_ball_rank` single-presser
  invariant unchanged.
- Game management `_game_mode(score, gameTime)`: neutral first 60s & at level score; protects a lead
  (sit deeper, lower risk/press) / chases a deficit (push up, more risk) — ramps 60-90s then >90s.
- Defensive 2nd-mark + multi-marker coordination: a spare MID drops to mark an uncovered striker;
  defenders/mids are assigned DISTINCT intruders (no double-mark); the pressed ball-carrier is
  deprioritized so markers cover off-ball threats first. MARK is positioning, not a press → the
  anti-swarm single-presser invariant holds.

**A — anti-exploitation (implemented):** `_near_optimal_pick` mixes ONLY among actions within epsilon
of the best (never trades quality). Applied to GK distribution + buildup pass (mixed by COMPOSITE EV)
+ shot vertical corner (`_mixed_aim`, keeper-away side fixed). Episode-stable seeds (ball cell +
candidate set) for PASS/GK → no per-tick thrash; per-tick seed only for terminal SHOOT. EV-critical
paths (high-conf shot, better-look pass, xG chance pass) left deterministic. Mixing is reproducible
for a fixed state → offline replay stays exact.

**B — coverage (tooling built, ladder edits GATED on live data):** `deploy/coverage_audit.py` fuzzes
the state space and reports branch histogram + swarm/degenerate reproducers. `deploy/tick_decode.py`
is a protocol calibrator, NOT a state adapter — turning a real capture into game_state dicts needs a
hand-confirmed offset→entity schema that does not exist yet. Per Codex: NO threshold changes from
Benchmark-only data (overfit). `GOAL_HALF_WIDTH=1.0` stays an estimate until a real goal-event capture.

**DEFERRED (Codex-ranked lower / higher-risk — do NOT add without live evidence):**
- Possession-phase rest-defense lane screen (Codex tactics #4) — overlaps the drop-mark; marginal in
  1-1-2.
- Bounded final-third counter-press (#6) — the project deliberately reverted a 2nd presser; high
  swarm risk.
- Set pieces beyond center restart (#7) — only worth it if the engine exposes repeatable corners/FKs.
- `coverage_audit` weak-fallback share is ~43% (hold-shape + GK-hold-line) — expected for a positional
  policy; the variance fix targets these but needs live data, not Benchmark scorelines.

**LIVE RESULTS (2026-06-25, this session's deploy of the tactical layer, formation 1-1-2):**
- balanced 2-0, 3-0, 2-1 (W); defensive 4-0, 4-1, 6-1 (W, up to 13-1 shots) — strong, no regression.
- aggressive: 2-3 L, 3-4 L, then 5-4 W, 0-0 D, 1-2 L, 2-1 W = **2W-1D-3L, high variance**.
  KEY FINDING: aggressive is a HIGH-VARIANCE SHOOTOUT for EVERY version. The baseline (6ef53aa) does
  NOT reliably win it either — re-measured live it got 0-0 (outshot 4-12, lucky) + 6-3. The memory's
  "aggressive fixed 5-2/4-1, 2/2" was small-sample optimism. The initial "0/2 aggressive regression"
  alarm was variance, NOT a real regression (confirmed by a 4-match resample: 2W-1D-1L).
- drop-mark EXONERATED via A/B: turning it OFF made aggressive WORSE (0-3, 1-5; opp shots 10/8 vs
  7/7 ON). Kept ON (DROP_MARK_ENABLED=True) — it reduces conceded shots.
- LATENCY: in-match ~800-870ms is PLATFORM-BOUND (Codex audit + experiment). It is the contest
  game-server→runtime invoke path (a different mode than our CLI ~350ms direct invoke), NOT cold start
  (FCINST: warm, 0.17ms handler), NOT reducible by us. Removing the per-tick diagnostic prints did NOT
  change it (835/867/818 before vs after). Portal grades <1000ms "excellent". STOP spending latency
  effort. Diagnostic FCINST/FCDBG/FCPOS prints removed (coords calibrated; hot path clean).
- aggressive lever (label-free, runtime-detected — NOT keyed on the practice archetype): it is a
  shootout you win by OUTSCORING, so against a high-shot-volume opponent the edge is finishing/chance
  creation, not sitting deeper. Open: does game-management's lead/neutral "sit deeper" hurt the
  shootout? (untested; add a runtime flag + A/B if pursued — never gate on the opponent label.)

**NEXT (when account is live):** A/B the 3 formations vs each archetype (need ACTIVE_FORMATION +
portal PUT /teams synced); characterize variance over 5+ matches/variant (2 is noise); capture one
real match → set GOAL_HALF_WIDTH + shot thresholds from goal-event ball-z; only then extend ladder
coverage. Real test = tournament vs adapting experts, not Benchmark.

---

## 9. EXHAUSTIVE AGGRESSIVE FINDINGS (2026-06-25, the modal opponent) — ⚠️ CONCLUSION CORRECTED

> ⚠️ **CORRECTED 2026-06-25 (3-Opus panel + Codex-gated; see §0 banner + champion/IMPROVEMENT-PLAN.md).**
> This section's headline — "no lever moves it / ~50% ceiling is set by the GAME, PROVEN / CERTAINTY not
> failure" — is **OVERSTATED and downgraded to UNCERTAINTY.** Why: (1) every "lever doesn't work" row below
> was decided on n≈3-4 matches/arm using W/L scoreline, which has ~8% power to detect even a +20%p edge — so
> "no lever moves it" is statistically indistinguishable from "we had no power to see a lever move it." (2) The
> "fast-transition counter → NO DIFF" row did NOT test the real creation cap: that counter fired on deep
> TURNOVERS (disabled at ship), not the sustained-possession final-third in-behind run, which is untested.
> The mechanistic rejections (2-1-1, LLM, shoot-more — judged on shot-RATE) still stand. DEFAULT 1-1-2 ships as
> the safe robust default, not as proof the ceiling is closed. Re-open with a POWERED A/B (≥12/arm, opp-shots +
> conversion metrics) before trusting any conclusion here.

In a 2-min match EVERY competent opponent attacks (a sprint shootout), so the AGGRESSIVE benchmark is
the MODAL opponent and our aggressive result ~= our tournament result. We tried to dominate it. We could
not — and we PROVED why, with live A/B (not guessing). Every lever was tested vs the aggressive variant:

| Lever | aggressive result vs DEFAULT |
|---|---|
| DEFAULT 1-1-2 (attack-always) | ~50% high-variance coin-flip (≈ 4W-2L then 1W-2L then 2W-2L across samples) |
| 2-1-1 (extra defender) | WORSE — kills our attack (0W-1D-2L, us-shots 0/8/3); more defence loses the shootout |
| LLM adaptation (Nova / Sonnet persona-hybrid) | WORSE — the LLM defends/perturbs (0/4, then 1/3) |
| shoot-more (loosen SHOOT gates) | NO DIFFERENCE — shots didn't increase; the gate was NOT the bottleneck |
| fast-transition counter (in-behind runs + direct ball) | NO DIFFERENCE — 2W-2L vs 2W-2L (ON vs OFF) |

DIAGNOSIS (FCTICK, 643 ticks): low-shot games are a CREATION cap, not a gate cap — we DO break forward
79% of the time, but the forward ball lands as a LOOSE ball with no runner truly in behind the opp last
line (in-behind only 3-17%). The counter build targeted exactly that and STILL didn't move the coin-flip.

CONCLUSION: aggressive is a HIGH-VARIANCE SHOOTOUT whose ~50% ceiling is set by the GAME (2-min, both
teams attacking), not by our policy. No lever moves it. DEFAULT 1-1-2 attack-always is the best config
and is what ships. This is CERTAINTY, not failure: most opponents will guess wrong (use an LLM, protect
leads, add a 2nd defender) and lose to us on balanced/defensive (which we DOMINATE 4-0/6-0) while
coin-flipping aggressive like everyone. We beat the LLM-only field 4/4 vs 0/4.

SHIPPED CONFIG: DEFAULT 1-1-2, attack-always, SHOOT gates 0.42/0.43, anti-swarm single-presser,
anti-exploitation mixing, multi-marker coordination. ALL experimental levers preserved as one-line
flags but OFF (no live benefit): COUNTER_MODE_ENABLED, SELECTOR counters (enabled=False), HYBRID_ENABLED,
FCTICK_ENABLED. Assets kept for a future edge: the team-coherent playbook selector, the Sonnet hybrid,
the FCTICK tick-collector + calibrate_shots pipeline (needs 10+ matches for a hard shot-model calibration).
