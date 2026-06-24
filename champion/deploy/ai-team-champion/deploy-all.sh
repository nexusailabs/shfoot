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
command -v rsync >/dev/null || { echo "ERROR: rsync not found"; exit 1; }
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text) || { echo "ERROR: no AWS creds"; exit 1; }
export AWS_ACCOUNT_ID
echo "Account $AWS_ACCOUNT_ID  Region $AWS_DEFAULT_REGION"
cleanup() { rm -rf "$BUILD_DIR"; }; trap cleanup EXIT
DEPLOYED=(); FAILED=()
for a in "${AGENTS[@]}"; do
  SRC="$SCRIPT_DIR/$a"; STAGE="$BUILD_DIR/$a"
  echo "=== deploy $a ==="
  [ -d "$SRC" ] || { echo "missing $SRC"; FAILED+=("$a"); continue; }
  rm -rf "$STAGE"; mkdir -p "$STAGE/src"
  cp "$SRC/src/main.py" "$STAGE/src/main.py"
  rsync -a --exclude='__pycache__' "$SCRIPT_DIR/lib/" "$STAGE/lib/"
  cp "$SRC/requirements.txt" "$STAGE/requirements.txt"
  sed -e "s|\${AWS_ACCOUNT_ID}|$AWS_ACCOUNT_ID|g" -e "s|\${AWS_DEFAULT_REGION}|$AWS_DEFAULT_REGION|g" \
      "$SRC/.bedrock_agentcore.yaml.template" > "$STAGE/.bedrock_agentcore.yaml"
  if (cd "$STAGE" && agentcore deploy --auto-update-on-conflict); then
    echo "OK $a"; DEPLOYED+=("$a")
  else echo "FAIL $a"; FAILED+=("$a"); fi
done
echo "Deployed: ${DEPLOYED[*]:-none}   Failed: ${FAILED[*]:-none}"
echo "Find each runtime ARN in the deploy output above; paste the 5 ARNs into the Player Portal."
[ ${#FAILED[@]} -gt 0 ] && exit 1 || echo "ALL DEPLOYED"
