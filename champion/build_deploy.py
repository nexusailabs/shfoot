#!/usr/bin/env python3
"""
Generate the deployable AgentCore team `champion/deploy/ai-team-champion/` from
the single source `champion/policy_v2.py`. Mirrors the sample's deploy layout so
the sample toolchain (`agentcore deploy`) works unchanged, but:
  * zero-LLM: each agent's src/main.py just calls policy_v2.command() — no
    strands, no Bedrock model round-trip (faster cold start, <500ms trivially).
  * yields a JSON LIST of commands (the runtime contract).
  * team-local lib/ (self-contained; does not touch the sample's shared lib).

Run:  python3 champion/build_deploy.py
Then in CloudShell:  cd champion/deploy/ai-team-champion && ./deploy-all.sh
"""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "deploy", "ai-team-champion")
AGENTS = [("ai-gk", 0, "GK"), ("ai-def", 1, "DEF"), ("ai-mid", 2, "MID"),
          ("ai-fwd1", 3, "FWD1"), ("ai-fwd2", 4, "FWD2")]

MAIN_TMPL = '''\
"""
Championship AI player {label} — controls player {pid}. ZERO-LLM: the per-tick
decision is the deterministic champion policy (policy_v2), decided in code in
microseconds. No model round-trip. The runtime contract is a JSON LIST of one
command for our player.
"""
import os, sys, json, time, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
import policy_v2 as P

app = BedrockAgentCoreApp()

MY_PLAYER_ID = {pid}
POSITION_LABEL = "{label}"
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
_STATE = {{"n": 0}}


@app.entrypoint
async def invoke(payload, context):
    _t0 = time.time()
    _STATE["n"] += 1
    prompt = payload.get("prompt", "{{}}")
    try:
        data = json.loads(prompt) if isinstance(prompt, str) else (prompt or {{}})
    except Exception:
        data = {{}}
    game_state = data.get("gameState", {{}}) or {{}}
    team_id = int(data.get("teamId", 0) or 0)
    my_players = data.get("myPlayers") or [MY_PLAYER_ID]
    pid = my_players[0] if my_players else MY_PLAYER_ID
    try:
        cmd = P.command(game_state, team_id, pid)
    except Exception:
        cmd = {{"commandType": "SET_STANCE", "playerId": pid, "teamId": team_id,
               "parameters": {{"stance": 0}}, "duration": 0}}
    # Diagnostic FCINST/FCDBG/FCPOS per-tick prints REMOVED 2026-06-25: coordinates are
    # calibrated so they are no longer needed, and Codex's latency audit flagged the per-tick
    # stdout as the only (tiny, 0-50ms) reducible term — the ~900ms in-match latency is
    # platform-bound (contest game-server invoke path), not our code. Keep the hot path clean.
    # SSE streaming yield is MANDATORY (a non-streaming return failed fitness 0/5).
    yield json.dumps([cmd])


if __name__ == "__main__":
    app.run()
'''

REQS = """\
# Championship agent — zero-LLM, deterministic policy. No strands (no model round-trip).
# OTEL/observability RESTORED: the morning LLM build ran ~450ms WITH aws-opentelemetry-distro
# + observability:true on the SAME invoke path; our no-OTEL build was 705ms. Removing OTEL
# (thought to cause a 559ms cold-start in live #1) was likely the latency regression, not the
# cure. This restores the morning build's exact observability infra to isolate the ~700ms gap.
bedrock-agentcore>=1.0.3
aws-opentelemetry-distro>=0.10.0
"""

YAML_TMPL = '''\
default_agent: ai_{role}_agent
agents:
  ai_{role}_agent:
    name: ai_{role}_agent
    entrypoint: src/main.py
    deployment_type: direct_code_deploy
    runtime_type: PYTHON_3_10
    platform: linux/arm64
    container_runtime: null
    source_path: .
    aws:
      account: "${{AWS_ACCOUNT_ID}}"
      execution_role_auto_create: true
      region: ${{AWS_DEFAULT_REGION}}
      ecr_repository: null
      ecr_auto_create: false
      s3_auto_create: true
      network_configuration:
        network_mode: PUBLIC
        network_mode_config: null
      protocol_configuration:
        server_protocol: HTTP
      observability:
        enabled: true
      lifecycle_configuration:
        idle_runtime_session_timeout: null
        max_lifetime: null
    memory:
      mode: NO_MEMORY
    identity:
      credential_providers: []
      workload: null
    aws_jwt:
      enabled: false
      audiences: []
      signing_algorithm: ES384
      issuer_url: null
      duration_seconds: 300
    request_header_configuration: null
    oauth_configuration: null
    api_key_env_var_name: null
    api_key_credential_provider_name: null
    is_generated_by_agentcore_create: false
'''

DEPLOY_SH = '''\
#!/bin/bash
set -e
# Deploy the 5 championship agents to Bedrock AgentCore (self-contained lib).
#   AWS_DEFAULT_REGION=us-east-1 ./deploy-all.sh         # all
#   ./deploy-all.sh ai-mid                               # one
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/_stage"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"; export AWS_DEFAULT_REGION
ALL=("ai-gk" "ai-def" "ai-mid" "ai-fwd1" "ai-fwd2")
AGENTS=("${1:-${ALL[@]}}"); [ -n "$1" ] && AGENTS=("$1") || AGENTS=("${ALL[@]}")

command -v agentcore >/dev/null || { echo "ERROR: agentcore CLI not found (pip install bedrock-agentcore-starter-toolkit)"; exit 1; }
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text) || { echo "ERROR: no AWS creds"; exit 1; }
export AWS_ACCOUNT_ID
echo "Account $AWS_ACCOUNT_ID  Region $AWS_DEFAULT_REGION"
cleanup() { rm -rf "$BUILD_DIR"; }; trap cleanup EXIT
DEPLOYED=(); FAILED=()
for a in "${AGENTS[@]}"; do
  SRC="$SCRIPT_DIR/$a"; STAGE="$BUILD_DIR/$a"
  echo "=== deploy $a ==="
  [ -d "$SRC" ] || { echo "missing $SRC"; FAILED+=("$a"); continue; }
  rm -rf "$STAGE"; mkdir -p "$STAGE/src" "$STAGE/lib"
  cp "$SRC/src/main.py" "$STAGE/src/main.py"
  cp "$SCRIPT_DIR"/lib/*.py "$STAGE/lib/"     # team-local lib (no rsync; CloudShell lacks it)
  cp "$SRC/requirements.txt" "$STAGE/requirements.txt"
  sed -e "s|\\${AWS_ACCOUNT_ID}|$AWS_ACCOUNT_ID|g" -e "s|\\${AWS_DEFAULT_REGION}|$AWS_DEFAULT_REGION|g" \\
      "$SRC/.bedrock_agentcore.yaml.template" > "$STAGE/.bedrock_agentcore.yaml"
  if (cd "$STAGE" && agentcore deploy --auto-update-on-conflict); then
    echo "OK $a"; DEPLOYED+=("$a")
  else echo "FAIL $a"; FAILED+=("$a"); fi
done
echo "Deployed: ${DEPLOYED[*]:-none}   Failed: ${FAILED[*]:-none}"
echo "Find each runtime ARN in the deploy output above; paste the 5 ARNs into the Player Portal."
[ ${#FAILED[@]} -gt 0 ] && exit 1 || echo "ALL DEPLOYED"
'''


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "lib"))
    shutil.copy(os.path.join(HERE, "policy_v2.py"), os.path.join(OUT, "lib", "policy_v2.py"))
    for folder, pid, label in AGENTS:
        role = label.lower()
        d = os.path.join(OUT, folder)
        os.makedirs(os.path.join(d, "src"))
        with open(os.path.join(d, "src", "main.py"), "w") as f:
            f.write(MAIN_TMPL.format(pid=pid, label=label))
        with open(os.path.join(d, "requirements.txt"), "w") as f:
            f.write(REQS)
        with open(os.path.join(d, ".bedrock_agentcore.yaml.template"), "w") as f:
            f.write(YAML_TMPL.format(role=role))
    sh = os.path.join(OUT, "deploy-all.sh")
    with open(sh, "w") as f:
        f.write(DEPLOY_SH)
    os.chmod(sh, 0o755)
    print(f"generated {OUT}")
    for root, _, files in os.walk(OUT):
        for fn in sorted(files):
            print("  ", os.path.relpath(os.path.join(root, fn), HERE))


if __name__ == "__main__":
    main()
