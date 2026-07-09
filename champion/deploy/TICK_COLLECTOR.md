# WSS Unity tick-data collector

Capture the Agentic Football Cup engine's **ground-truth** tick stream (positions,
ball, shot outcomes) and turn it into calibration constants for `sim2.py`.

**Why this exists:** `sim2.py` physics are low-trust guesses — a knob sweep showed it
is insensitive to aggression params, so offline tuning is meaningless. The match
viewer is a Unity-WebGL app that patches `window.WebSocket` and streams **binary**
frames from `wss://game.agentic-football.aws.dev:5245`. Decoding one real match gives
the true shot-conversion model (what position/power/aim/GK-state actually scores) —
the lever to beat expert teams.

## Files
- `tick_collector.py` — capture (browser **sniff** + browserless **raw** + **collect** orchestration)
- `tick_decode.py` — offline reverse-engineer a capture into `calib-<id>.json`
- captures land in `deploy/ticks/` (gitignored — they contain match data)

Run with the **system** `python3` (has Playwright + chromium + websockets):
```bash
which python3   # /opt/homebrew/bin/python3 — has playwright 1.58 + websockets 16
```

## One-command flow (recommended)
```bash
# create a practice match, wait for in_progress, sniff its viewer to completion,
# stamp the final API record (game_stats/goals) into the .meta.json
python3 champion/deploy/tick_collector.py collect --opponent balanced --headed
```
**First run only:** pass `--headed`. A Chromium window opens on the viewer URL — log
into `agentic-football.aws.dev` once. The session persists in
`~/.cache/agentic-football-profile`, so later runs can drop `--headed` (headless).

If no WebSocket opens, you are not logged in (or the match never reached
`in_progress`) — re-run `--headed` and complete the login.

## Decode
```bash
python3 champion/deploy/tick_decode.py champion/deploy/ticks/frames-<id>.jsonl
```
Prints, and writes `calib-<id>.json`:
- **dominant tick size** — the high-frequency binary frame = per-tick world snapshot
- **float layout** — `<f`/`<d`, the aligned byte-offsets holding in-pitch values
- **entity hint** — in-pitch floats / 2 ≈ 23 (22 players + ball) confirms the layout
- **tick rate** — Hz from inter-frame dt
- **speed** — `p99_field_speed` = true max player/ball speed (units/s) for sim2 motion
  constants; `max` includes goal-reset teleports (informative, not a movement speed)
- **goal windows** — the tick seqs around each scored goal (from `meta.goals[].game_time_secs`)
  → inspect ball pos/velocity + GK geometry at the shot = the real shot model

## Protocol reverse-engineering plan (the spec's 3 approaches)
1. **sniff (done — bootstrap):** let the logged-in viewer do the handshake; record every
   frame. `tick_decode.py` infers the snapshot schema from the data, no guessing.
2. **raw (browserless, the "infinite loop"):** once a sniff exists, replay its handshake:
   ```bash
   python3 champion/deploy/tick_collector.py raw --match-id <id> \
       --replay-from champion/deploy/ticks/frames-<prior>.jsonl
   ```
   Replays the viewer's binary **send**-frames byte-for-byte to subscribe, then records
   server frames with zero browser. (If a frame embeds the match-specific
   `vendor_match_id`, patch those bytes — `meta.vendor_match_id` is recorded for that.)
3. **decode:** `tick_decode.py` candidates → hand-confirm offsets → write the calibrated
   constants into `sim2.py` (pitch dims, tick Hz, max speeds, shot model). Only then is
   offline optimization trustworthy.

## API/auth
Reuses `run_match.py` (same dir): `API` base, `Authorization: Bearer team:<code>`,
`TEAM_ID`. `GET /matches/{id}` supplies `game_server_url` + `vendor_match_id` once a
match is `in_progress`. Workshop AWS creds are NOT needed for capture — only the team
Bearer token (already in `run_match.py`) and a logged-in viewer session.

## Status
Built + offline-verified against a synthetic Unity-style capture (188-byte tick, 23
entities, 30 Hz): decoder correctly recovered the frame size, float32 layout, entity
count, tick rate, goal window, and true p99 speed. **Live capture is unverified** — it
needs an in-progress match + a logged-in viewer at the event (creds/login expire).
First real run: `collect --headed`, then `tick_decode.py` on the result.
