# DECODE_STATUS — can a tick capture become shot-event data?

Precise account of what `tick_collector.py` + `tick_decode.py` produce, what is
missing to calibrate the shot model, and which path is faster to real data.

## TL;DR verdict

**WSS binary decode is NOT tractable now AND is no longer needed.**
`tick_decode.py` is a *protocol calibrator*, not a `game_state` adapter — it finds
WHERE floats live in a frame, but not WHICH entity each float is. Closing that
gap needs a hand-confirmed **offset→entity schema** that does not exist and is a
multi-hour, fragile reverse-engineer requiring a real capture we do not have
(`deploy/ticks/` is empty; live capture needs a logged-in viewer at the event).

**The on-agent FCTICK log fully supersedes it.** The agent already receives the
complete `game_state` every tick (all 10 players + ball x/y/z + possession). A
per-tick **FCTICK** log (being added by the agent that owns `build_deploy.py` /
`policy_v2.py`) captures that stream directly — including the ball's z as it
crosses the goal line — so `calibrate_shots.py --ticks` can fit **BOTH**
`GOAL_HALF_WIDTH` **and** the SHOOT gates with **zero binary decode**. WSS decode
would only ever serve as an independent ground-truth cross-check.

---

## What `tick_collector.py` captures

A raw **WSS frame dump**, not game state. Modes: `collect` (create match → poll
`in_progress` → drive the logged-in Unity viewer via Playwright → record every
frame → stamp the final API record), `sniff` (existing match), `raw` (browserless,
replays a prior sniff's handshake). Output: `frames-<id>.jsonl` (base64 frames) +
`.meta.json` (match record + `goals[].game_time_secs`). The handshake is done by
the logged-in browser viewer, so a sniff must bootstrap before `raw` works.

## What `tick_decode.py` produces (and does NOT)

Given a capture it infers, with evidence: dominant frame size, float layout
(`<f`/`<d` in-pitch offsets), entity hint (~23 xy-pairs), tick rate, speeds, and
goal windows (tick seqs around each API goal time). It writes `calib-<id>.json`
— **candidates, not decoded entities.** It does NOT output `game_state` dicts or
shot events.

### The exact missing piece (why WSS decode is hard)
The decoder finds *that* ~46 floats are positions and *which byte offsets* hold
them, but not, for any offset: (1) which entity (player 0..21 vs ball), (2) which
axis (x vs z-depth vs y-height), (3) team/role, (4) possession, (5) packing edge
cases (endianness, quantization, delta-encoding). Without (1)–(4) you cannot
identify a shooter, attribute a shot, or read the keeper — so no shot event.
Resolving it means hand-anchoring against a real capture (ball = the entity that
reaches x=±6.4 in a goal window; GKs = deepest entities on opposite goal lines;
depth axis = the one bounded by ~[-3.5,3.6]) and writing a `tick_to_state`
adapter — realistically a few hours, and only if frames are plain float arrays.

**This work is now optional** — FCTICK gives the same `game_state` for free.

---

## The data the calibration scripts consume (define the schema)

### Per-tick record — what FCTICK should log (one JSON object per logged tick)
The agent that owns the handler should emit (canonical field names):

| field | type | required | note |
|---|---|---|---|
| `t` (or `gameTime`) | float secs | **yes** | the GAME CLOCK — must align with the API `goals[].game_time_secs` |
| `ball.x`, `ball.z` | float | **yes** | field plane = (x, z-depth); the crossing-z fits GOAL_HALF_WIDTH |
| `ball.y` / `ball.h` | float | no | height (informative; not used for the plane) |
| `ball.vx`, `ball.vz` | float | no | velocity (detection derives it from positions if absent) |
| `players[]` = `{pid, team, x, z}` | list | **yes** | ALL 10 players (need opp GK + blockers); team ∈ {0,1} |
| `poss` (holder pid) + `poss_team` | int / 0\|1 | **yes** | drives shot detection (ball release from a holder) |
| `shoot` = `{pid, pos:{x,z}, aim, power}` | obj | optional | explicit SHOOT marker; disambiguates the shooter on contested frames |

`calibrate_shots.py` is **tolerant of the raw live contract**, so the
FCTICK→ticks shim is near-trivial or unnecessary — `normalize_ticks()` accepts:
nested `position`; ball depth = `position.z` while players' depth = `position.y`
(the policy_v2 `_field_xy` rule); ids as `agentId`/`playerId`; team as `teamCode`
home/away or `teamId`; possession as `poss`/`poss_team`, a `{possession:{pid,team}}`
block, or `ball.possessionAgentId`/`possessionTeam`. Verified: a raw
`{position, agentId, teamCode, possessionAgentId}` tick normalizes and a shot is
detected + labeled correctly.

Goal labels come from the API match record (`run_match.py` already pulls it):
each shot is bound one-to-one to the nearest goal at `goals[].game_time_secs`.

### Pre-extracted shot list (`--shots`) — skips detection
`{team, sx, sz, opp_goal_x, gk_xy:[x,z]|null, blockers:[[x,z],...],
  z_cross:<ball z at goal line|null>, reached_line, keeper_touch, goal}`

### FCSHOT-subset (`shotlog_calibrate.py`) — lighter alternative
If pulling the full per-tick FCTICK stream from CloudWatch is too heavy, log only
SHOOT events: `{pid, team, sx, sz, opp_goal_x, gk:[x,z], aim, power, our_score,
opp_score, gameTime}`. `shotlog_calibrate.py` fits the **gates** from these +
match records (no decode). It CANNOT fit GOAL_HALF_WIDTH (no crossing-z) — use the
full-tick path for that.

---

## What each path can fit

| | WSS decode | **FCTICK full per-tick** | FCSHOT shot-only |
|---|---|---|---|
| New code to write | offset→entity adapter (none exists) | the FCTICK log (owned by other agent) | the FCSHOT log |
| Reverse-engineering | multi-hour, fragile | none | none |
| Prereqs | logged-in viewer + real capture | logger on, run N matches | logger on, run N matches |
| Fits GOAL_HALF_WIDTH | yes | **yes** (ball crossing-z is in game_state) | no |
| Fits SHOOT gates | yes | **yes** | yes |
| Volume to pull | whole match dump | full per-tick (heaviest) | SHOOT events only (lightest) |
| Consumer | `calibrate_shots.py --ticks` | `calibrate_shots.py --ticks` | `shotlog_calibrate.py` |

## Recommendation

1. **Primary:** have FCTICK log the per-tick schema above. Run ~10 matches with
   it on, pull the logs + match records, and run `calibrate_shots.py --ticks`
   → real `GOAL_HALF_WIDTH` + gates, no decode. This is the faster route by far.
2. **Fallback (lighter pull):** if full-tick volume is impractical, log only
   SHOOT events (FCSHOT subset) and run `shotlog_calibrate.py` for the gates;
   GOAL_HALF_WIDTH then waits on a full-tick or WSS sample.
3. **WSS-decode:** optional, only as an independent cross-check at the event with
   a logged-in viewer. Not on the critical path.
4. Do **not** edit `policy_v2.py` constants from synthetic / Benchmark-only data
   — calibrate from a real batch (≥ ~30–50 labeled shots; ≥ ~30 goal-line
   crossings for a stable GOAL_HALF_WIDTH).

### Exact capture commands (the live agent runs these)

FCTICK path (preferred):
```bash
# 1. FCTICK logging enabled by the agent owning build_deploy.py/policy_v2.py;
#    rebuild + deploy via that agent's normal step (NOT done here).

# 2. run a batch, saving each match record (the goal-time labels)
for i in $(seq 1 10); do
  _build/tk-venv/bin/python champion/deploy/run_match.py balanced \
    | tee champion/deploy/ticks/match-$i.json
done

# 3. pull FCTICK logs from CloudWatch for the run window (one shooter's log group
#    is enough — it carries the full ball trajectory each tick)
aws logs filter-log-events --region us-east-1 \
  --log-group-name /aws/bedrock-agentcore/runtimes/<ai-fwd1-runtime-id> \
  --filter-pattern "FCTICK" --start-time <epoch_ms> \
  --query 'events[].message' --output text > champion/deploy/ticks/fctick.log
# -> convert the FCTICK lines into a JSON list of per-tick records (strip the
#    "FCTICK " token; json.loads each); save as ticks.json (+ goals sidecar from
#    the match record's game_stats.goals).

# 4. fit ALL constants
python3 champion/deploy/calibrate_shots.py --ticks champion/deploy/ticks/ticks.json \
        --goals champion/deploy/ticks/match-1.json
```

FCSHOT-subset path (lighter): same but `--filter-pattern "FCSHOT"` →
`python3 champion/deploy/shotlog_calibrate.py --logs-dir champion/deploy/ticks --matches-dir champion/deploy/ticks`.

WSS-decode path (optional cross-check, needs a logged-in viewer at the event):
```bash
python3 champion/deploy/tick_collector.py collect --opponent balanced --headed
python3 champion/deploy/tick_decode.py champion/deploy/ticks/frames-<id>.jsonl   # candidates only
#  -> then hand-confirm the offset->entity schema + build tick_to_state, feed --ticks.
```

## Verification of the new tooling (offline, this session)
- `calibrate_shots.py` synthetic self-test: recovers GOAL_HALF_WIDTH **0.75–0.76
  vs ground-truth 0.750** (separation acc 1.00); gate fit lifts conversion
  ~0.45→0.54 at ≥71% goal retention. `--ticks` (+ auto `.goals.json`/`.meta.json`
  sidecar), `--shots`, and `--emit-synthetic` paths all run clean.
- **Raw live-contract tolerance**: a tick with nested `position`, `agentId`,
  `teamCode`, `possessionAgentId` normalizes correctly and the shot is detected +
  labeled (no shim needed).
- `shotlog_calibrate.py` synthetic + `--pairs` + `--logs-dir` demos: binds 100%
  of goals to logged shots, lifts conversion ~0.32→0.61; tolerates CloudWatch
  line prefixes.
- Scope: only the three analysis files under `champion/deploy/` were written.
  `build_deploy.py` and `policy_v2.py` are untouched (owned by the other agent).
