"""
Championship AI player FWD2 — controls player 4. ZERO-LLM: the per-tick
decision is the deterministic champion policy (policy_v2), decided in code in
microseconds. No model round-trip. The runtime contract is a JSON LIST of one
command for our player.
"""
import os, sys, json, time, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
import policy_v2 as P

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 4
POSITION_LABEL = "FWD2"
# Burst-stagger (hypothesis F): the engine sends all 5 invokes at tick start; five
# zero-LLM agents finishing together in ~0.17ms hammer the engine's concurrent-SSE
# handling (LLM agents naturally stagger on model latency, ~400-500ms in-match vs our
# ~975ms). De-sync our response times by player id so they don't all close at once.
_STAGGER_S = MY_PLAYER_ID * 0.06   # 0/60/120/180/240ms

# --- latency instrumentation ---------------------------------------------
# _PROC_START is set ONCE per process (microVM). If every invoke logs a small
# proc_age + n==1, the container is cold-started every tick (no warm reuse).
# If n increments and proc_age grows, the container is reused (warm). handler_ms
# is our pure-code time (should be ~1ms). The gap between handler_ms and the
# portal's reported latency is AgentCore/HTTP/microVM infra overhead.
_PROC_START = time.time()
_STATE = {"n": 0}


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
    try:
        cmd = P.command(game_state, team_id, pid)
    except Exception:
        cmd = {"commandType": "SET_STANCE", "playerId": pid, "teamId": team_id,
               "parameters": {"stance": 0}, "duration": 0}
    _h_ms = round((time.time() - _t0) * 1000, 2)
    print("FCINST " + json.dumps({"pos": POSITION_LABEL, "n": _STATE["n"],
          "proc_age_s": round(time.time() - _PROC_START, 1), "handler_ms": _h_ms}),
          flush=True)
    # SSE streaming yield is MANDATORY (a non-streaming return failed fitness 0/5).
    # Stagger the close by player id to de-sync the 5-agent burst (hypothesis F).
    if _STAGGER_S:
        await asyncio.sleep(_STAGGER_S)
    yield json.dumps([cmd])


if __name__ == "__main__":
    app.run()
