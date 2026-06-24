# Championship build (`champion/`) — real-contract, code-primary

The 6/24 post-mortem rebuild. Treasure hunt + live-config proved the deployed
team was **LLM-primary with zero Gateway tools**, optimized only on surface
knobs (prompts/models). This is the inverse: a **zero-LLM deterministic policy**
on the **verified real contract**, with the Gateway tactical math inlined.

## Files
- `policy_v2.py` — the brain. `command(game_state, team_id, my_id) -> command dict`.
  Pure stdlib, microsecond decisions (max ~0.03ms, vs the 500ms budget).
- `sim2.py` — real-contract offline match sim + baseline/swarm opponents. Measures
  goals, possession, team-spread (anti-swarm), latency. `python3 champion/sim2.py`.

## Real contract (verified, NOT the assumed agenticfootballcup.com one)
- Field x∈[-55,55], y∈[-35,35]; goals at x=±55, mouth |y|<~7.
- Roster of 5 = **1-1-2**: id0 GK, id1 DEF, id2 MID, id3 FWD1, id4 FWD2.
- team0 HOME (goal -55, attacks +x); team1 AWAY mirrors on x only (y symmetric).
- obs: `players[]{agentId|playerId, teamCode|teamId, position{x,y}, stamina 0-100}`,
  `ball{position, possessionAgentId}`, `score{home,away}`.
- commands: MOVE_TO PASS{target_player_id,type} SHOOT{aim_location,power}
  PRESS_BALL MARK SLIDE_TACKLE INTERCEPT GK_DISTRIBUTE SET_STANCE.

## The three pillars
1. **Code decides every tick; LLM only gray-zone** (Decision.gray_zone exists for an
   optional escalation path — kept out of the hot path).
2. **Inlined Gateway math**: `evaluate_shot` (→ should_shoot/aim/power) and
   `calculate_pass_options` (→ best target_player_id) ported numerically from the
   real Lambda sources and consumed directly (the official path was never even
   deployed by anyone — list-gateways was empty).
3. **Anti-swarm zone discipline**: exactly ONE outfielder presses (deterministic
   rank from shared full state); everyone else holds a 1-1-2 shape.

## Validated results (sim2, 9 matches × 400 ticks, seeded)
| matchup | goals | read |
|---|---|---|
| **champion vs baseline** (realistic sample-team opponent) | **16 – 0** | clean sheet; spread 51 vs 8 (baseline collapses to a ball-chasing blob) |
| champion(A) vs champion(B) | ~even | symmetric (possession-id bug fixed) |
| champion vs all-out swarm (degenerate) | 23 – 72 | **known gap**: strict single-pressing is out-numbered by a 5-man gegenpress. A 2nd-presser fix was tried and REVERTED — it broke the clean sheet vs real opponents. No real team plays a 5-man+GK swarm, so we do not chase this metric. |

## Verification
- Codex adversarial review (`_build/CODEX-VERIFY-RESULT.md`): concept + treasure-hunt
  findings all CONFIRMED; 4 code bugs found → fixed (possession team-collision,
  dead DEF-clear branch, SLIDE_TACKLE missing `distance`, Gateway rounding); output
  shape (yield a LIST) handled in the deploy wrapper.

## Deploy (next, needs live workshop account via CloudShell)
Wrap `policy_v2.command()` in an AgentCore `@app.entrypoint` that `yield`s
`json.dumps([cmd])`, as 5 per-position `src/main.py`, build into the sample's
`deploy-all.sh` structure, register the 5 ARNs in the Player Portal, run live
practice matches to confirm sim→live transfer.
