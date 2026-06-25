"""
Championship AI player FWD2 — controls player 4. ZERO-LLM: the per-tick
decision is the deterministic champion policy (policy_v2), decided in code in
microseconds. No model round-trip. The runtime contract is a JSON LIST of one
command for our player.
"""
import os, sys, json, time, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import policy_v2 as P
try:
    import selector as S
except Exception:
    S = None
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 4
POSITION_LABEL = "FWD2"
# Calibration-only tick logging. OFF by default (per-tick stdout was deliberately
# removed for latency); flip True for an explicit ShotCalib data-collection run.
# Even when ON, ONLY the GK process (pid 0) logs the full-pitch FCTICK; each agent
# logs only its own FCSHOOT. Keeps the hot path clean.
FCTICK_ENABLED = False
# A/B override: set to a playbook NAME to FORCE it every tick (isolates a playbook's
# effect, bypassing the classifier). None -> normal selector. Shipped config: None.
FORCE_PLAYBOOK = None
# Burst-stagger (hypothesis F) was REMOVED: live match #5 proved it made latency WORSE
# (946ms with stagger vs 861ms without), and GK with 0 stagger was still 705ms. So the
# ~700ms is a fixed overhead ADDED to handler time, not a fast-close/burst penalty. The
# one remaining infra difference vs the morning LLM build (which ran ~450ms on the SAME
# invoke path + deployment_type) is observability — restored to enabled:true below.

# --- latency instrumentation ---------------------------------------------
# _PROC_START is set ONCE per process (microVM). If every invoke logs a small
# proc_age + n==1, the container is cold-started every tick (no warm reuse).
# If n increments and proc_age grows, the container is reused (warm). handler_ms
# is our pure-code time (should be ~1ms). The gap between handler_ms and the
# portal's reported latency is AgentCore/HTTP/microVM infra overhead.
_PROC_START = time.time()
_STATE = {"n": 0}


# --- FCTICK / FCSHOOT tick collection (offline calibration; no WSS decode) -----
# Our agents see FULL state every tick, so we log it to stdout -> CloudWatch.
# pid 0 logs the whole-pitch snapshot (FCTICK); each agent logs its OWN shot
# (FCSHOOT). join FCSHOOT->FCTICK by gameTime. Gated by FCTICK_ENABLED (off).
def _num(d, key, default=0.0):
    try:
        return float(d.get(key, default))
    except Exception:
        return default


def _player_pid(p):
    aid = p.get("agentId") if isinstance(p, dict) else None
    if aid is not None:
        try:
            return int(str(aid).rsplit("_", 1)[-1])
        except Exception:
            return -1
    try:
        return int(p.get("playerId", -1))
    except Exception:
        return -1


def _log_fctick(game_state, team_id, n, pb):
    try:
        ball = game_state.get("ball", {}) or {}
        bpos = ball.get("position", ball) or {}
        bvel = ball.get("velocity", {}) or {}
        players = []
        for p in (game_state.get("players") or []):
            if not isinstance(p, dict):
                continue
            pos = p.get("position", p) or {}
            players.append({"pid": _player_pid(p),
                             "team": p.get("teamCode", p.get("teamId")),
                             "x": round(_num(pos, "x"), 3), "y": round(_num(pos, "y"), 3)})
        holder, hteam = None, None
        try:
            h = P.possession_holder(game_state)
            if isinstance(h, dict):
                holder = _player_pid(h)
                hteam = h.get("teamCode", h.get("teamId"))
        except Exception:
            pass
        rec = {
            "t": game_state.get("gameTime"), "n": n, "pb": pb,
            "ball": {"x": round(_num(bpos, "x"), 3), "y": round(_num(bpos, "y"), 3),
                      "z": round(_num(bpos, "z"), 3),
                      "vx": (_num(bvel, "x", None) if bvel else None),
                      "vy": (_num(bvel, "y", None) if bvel else None),
                      "vz": (_num(bvel, "z", None) if bvel else None)},
            "poss": holder, "poss_team": hteam,
            "score": game_state.get("score") or {}, "players": players,
        }
        print("FCTICK " + json.dumps(rec), flush=True)
    except Exception:
        pass


def _log_fcshoot(cmd, game_state, team_id, pid, pb):
    try:
        if cmd.get("commandType") != "SHOOT":
            return
        me = None
        want = "home" if team_id == 0 else "away"
        for p in (game_state.get("players") or []):
            if not isinstance(p, dict):
                continue
            if _player_pid(p) == pid and (p.get("teamCode") == want or p.get("teamId") == team_id):
                me = p
                break
        pos = (me.get("position", me) if isinstance(me, dict) else {}) or {}
        par = cmd.get("parameters", {}) or {}
        rec = {"t": game_state.get("gameTime"), "pid": pid,
                "pos": [round(_num(pos, "x"), 3), round(_num(pos, "y"), 3)],
                "aim": par.get("aim_location"), "power": par.get("power"), "pb": pb}
        print("FCSHOOT " + json.dumps(rec), flush=True)
    except Exception:
        pass


@app.entrypoint
async def invoke(payload, context):
    _t0 = time.time()
    _STATE["n"] += 1
    prompt = payload.get("prompt", "{}")
    try:
        data = json.loads(prompt) if isinstance(prompt, str) else (prompt or {})
    except Exception:
        data = {}
    game_state = data.get("gameState", {}) or {}
    team_id = int(data.get("teamId", 0) or 0)
    my_players = data.get("myPlayers") or [MY_PLAYER_ID]
    pid = my_players[0] if my_players else MY_PLAYER_ID
    # OPPONENT-REACTIVE PLAYBOOK SELECT: a PURE function of the SHARED gameState, so
    # all 5 (separate-process) agents independently compute the IDENTICAL playbook.
    # No Bedrock, no per-process memory. Counters ship DISABLED -> always "DEFAULT".
    pb = FORCE_PLAYBOOK or "DEFAULT"
    if not FORCE_PLAYBOOK:
        try:
            if S is not None:
                pb = S.select_playbook(game_state, team_id) or "DEFAULT"
        except Exception:
            pb = "DEFAULT"
    try:
        cmd = P.command(game_state, team_id, pid, None, pb)   # wire the playbook through
    except Exception:
        cmd = {"commandType": "SET_STANCE", "playerId": pid, "teamId": team_id,
               "parameters": {"stance": 0}, "duration": 0}
    # TICK COLLECTION (calibration-only, gated): GK logs the full pitch snapshot;
    # every agent logs its own shot. Off by default to keep the hot path clean.
    if FCTICK_ENABLED:
        try:
            if MY_PLAYER_ID == 0:
                _log_fctick(game_state, team_id, _STATE["n"], pb)
            _log_fcshoot(cmd, game_state, team_id, pid, pb)
        except Exception:
            pass
    # Diagnostic FCINST/FCDBG/FCPOS per-tick prints REMOVED 2026-06-25: coordinates are
    # calibrated so they are no longer needed, and Codex's latency audit flagged the per-tick
    # stdout as the only (tiny, 0-50ms) reducible term — the ~900ms in-match latency is
    # platform-bound (contest game-server invoke path), not our code. Keep the hot path clean.
    # SSE streaming yield is MANDATORY (a non-streaming return failed fitness 0/5).
    yield json.dumps([cmd])


if __name__ == "__main__":
    app.run()
