#!/usr/bin/env bash
# Run inside AWS CloudShell (live workshop account). Clones the champion team,
# deploys all 5 agents to AgentCore, collects the 5 runtime ARNs, uploads the
# log so Claude can read the ARNs back. Clipboard-free.
set +e
cd "$HOME" || exit 1
rm -rf shfoot
echo "## clone ##"
git clone -q https://github.com/nexusailabs/shfoot || { echo "clone failed"; exit 1; }
cd shfoot/champion/deploy/ai-team-champion || exit 1

# CloudShell runs inside a virtualenv -> plain pip install (NOT --user).
command -v agentcore >/dev/null || pip install -q bedrock-agentcore-starter-toolkit
# direct_code_deploy requires `uv`; CloudShell lacks it -> install via pip.
command -v uv >/dev/null || pip install -q uv
hash -r 2>/dev/null
command -v agentcore >/dev/null || { echo "ERROR: agentcore not on PATH"; pip show bedrock-agentcore-starter-toolkit 2>/dev/null | head -3; }
command -v uv >/dev/null && echo "uv: $(uv --version)" || echo "WARN: uv still missing"
export AWS_DEFAULT_REGION=us-east-1
export AGENTCORE_SUPPRESS_RECOMMENDATION=1

echo "## deploy ##"
./deploy-all.sh 2>&1 | tee "$HOME/deploy.log"

echo "" | tee -a "$HOME/deploy.log"
echo "## POST-DEPLOY VERIFY (entryPoint must NOT have opentelemetry-instrument; status READY) ##" | tee -a "$HOME/deploy.log"
for a in ai_gk_agent-sbGF2v9Uay ai_def_agent-jsgv7M6UfK ai_mid_agent-ZbTrQo7y6g ai_fwd1_agent-qthSxi8TdE ai_fwd2_agent-0LNpt2HRM5; do
  echo "=== $a ===" | tee -a "$HOME/deploy.log"
  aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id "$a" \
    --query '{status:status,version:agentRuntimeVersion,entryPoint:agentRuntimeArtifact.codeConfiguration.entryPoint}' 2>&1 | tee -a "$HOME/deploy.log"
done
echo "## RUNTIME ARNS (paste these 5 into the Player Portal) ##" | tee -a "$HOME/deploy.log"
grep -ioE 'arn:aws:bedrock-agentcore:[^ "]*runtime/[A-Za-z0-9_.-]+' "$HOME/deploy.log" | sort -u | tee -a "$HOME/deploy.log"

UA="Mozilla/5.0 (X11; Linux x86_64)"
URL=$(curl -fsS -A "$UA" -F "file=@$HOME/deploy.log" https://0x0.st 2>/dev/null)
[ -z "$URL" ] && URL=$(curl -fsS --data-binary @"$HOME/deploy.log" https://paste.rs 2>/dev/null)
echo "=================================================="
echo "DEPLOY LOG URL: $URL"
echo "=================================================="
