#!/bin/bash
# Deploy the 5 champion agents to AgentCore DIRECTLY from the Mac (no CloudShell).
# Uses the workshop temp creds in /tmp/awsenv + the agentcore CLI in _build/tk-venv.
# Re-grab /tmp/awsenv from the event portal when the session token expires.
#   ./local-deploy.sh            # all 5
#   ./local-deploy.sh ai-mid     # one
set -e
ROOT="/Users/kei/football-cup"
TK="$ROOT/_build/tk-venv/bin"
export PATH="$TK:$PATH"
set -a; . /tmp/awsenv; set +a
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AGENTCORE_SUPPRESS_RECOMMENDATION=1
ACC=$("$TK/python" -c "import boto3;print(boto3.client('sts').get_caller_identity()['Account'])") \
  || { echo "ERROR: creds invalid/expired — re-grab /tmp/awsenv from the event portal"; exit 1; }
echo "account $ACC region $AWS_DEFAULT_REGION"
cd "$ROOT/champion/deploy/ai-team-champion"
./deploy-all.sh "$@"
