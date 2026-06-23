# sim/ — offline match validation

Reproduces a faithful-enough 5v5 football match **outside** the Player Portal so
the deterministic squad can be run end-to-end and measured before 6/24 — the same
way `ai-league/sim/` reproduces the dungeon + scoring outside the contest.

**Zero AWS, zero API.** Every brain is the deterministic `squad.act()` path or a
pure-Python swarm. The LLM-escalation path (`act_or_escalate` → Bedrock) only
works inside the contest account; running it against local mac creds throws the
API error we hit. The floor we ship and validate is the zero-LLM policy.

## Run

```bash
source .venv/bin/activate
python3 sim/engine.py            # squad vs swarm + self-play (both kickoffs)
python3 sim/engine.py --ticks 600
python3 -m unittest test_engine -v
```

## What it measures (the thesis: role/zone discipline beats the ball-chasing swarm)

| metric | why it matters |
|---|---|
| **team spread** (mean pairwise dist of the 5) | the headline anti-swarm signal — a swarm collapses onto the ball (low spread); a disciplined side holds shape (high spread) |
| score vs swarm | the swarm's GK chases the ball too, leaving its goal open — discipline punishes it |
| possession % | a swarm *hoards* possession by crowding the ball, yet converts none of it — high B possession + 0 B goals is the point, not a metric we try to "win" |
| FWD mean x | stays advanced toward the opponent goal (catches a flipped x-axis) |
| max decision latency | must clear the 500ms budget (deterministic = microseconds) |
| illegal actions (both sides) | must be 0 — only the 11-command vocabulary may reach the runtime; counted per side so self-play surfaces side-B illegality too |
| policy fallbacks | must be 0 — proves the real policy decided every tick, never the safety-net MOVE fallback |
| self-play mirror | identical policy both sides; swapping kickoff mirrors the result exactly (side-neutral tie-breaking), demonstrating the side-B frame flip + policy are symmetric |

## Representative result (300 ticks)

```
squad vs SWARM   26:0   spread A 0.366 / B 0.255   (swarm hoards 73% possession, scores 0)
self-play A-kick 7:8   B-kick 8:7   aggregate 15:15   (exact mirror, side-neutral ties)
all decisions < 0.04 ms   illegal 0/0   fallbacks 0   FWD mean x 0.77
```

## NOT claimed

This is a **behavioral** harness, not the official Cup score (the real engine /
scoring is gated until the portal opens). It proves the policy *behaves* right —
holds shape, doesn't ball-chase, stays legal and fast, beats the naive swarm — and
that the obs↔action adapter round-trips for both sides. On 6/24, reconcile
`state_from_obs()` to the portal's real keys (see `../reconcile.py`); the policy
and these behaviors transfer unchanged.
