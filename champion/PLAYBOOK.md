# Football Cup Champion — PLAYBOOK (authoritative learning doc)

Purpose: let a future session **re-validate the concept from scratch** and **decide which
direction to strengthen**, from evidence. Read this top-to-bottom before changing anything.

Goal (operator): a DETERMINISTIC (zero-LLM) bot that beats strong expert teams in the AWS
Summit Shanghai Agentic Football Cup. "Just win" (scoring rules irrelevant). Benchmark (the
AWS reference bot, 3 style variants) is the ONLY available sparring — beware overfitting to it.

Secrets are NOT in this file. Team code / account / ARNs live in `/tmp/awsenv` and the
gitignored `champion/deploy/run_match.py`. This file is public-safe (github.com/nexusailabs/shfoot).

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

**NEXT (when account is live):** A/B the 3 formations vs each archetype; characterize variance over
3-5 matches/variant; capture one real match → set GOAL_HALF_WIDTH + shot thresholds from goal-event
ball-z; only then extend ladder coverage.
