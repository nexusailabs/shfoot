"""
Championship AI player GK — controls player 0. ZERO-LLM: the per-tick
decision is the deterministic champion policy (policy_v2), decided in code in
microseconds. No model round-trip. The runtime contract is a JSON LIST of one
command for our player.
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
import policy_v2 as P

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 0
POSITION_LABEL = "GK"


@app.entrypoint
async def invoke(payload, context):
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
    yield json.dumps([cmd])


if __name__ == "__main__":
    app.run()
