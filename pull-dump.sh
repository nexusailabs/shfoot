#!/usr/bin/env bash
# Football Cup — slice live AgentCore dump to signal-only, upload robustly, print URL.
# Reuses ~/fc-dump.txt if present (no re-pull); else does a LIGHT pull (no 8h log tail).
set +e
SRC="$HOME/fc-dump.txt"
SMALL="$HOME/fc-small.txt"

if [ ! -s "$SRC" ]; then
  : > "$SRC"
  echo "## RUNTIMES ##" >> "$SRC"
  for a in ai_gk_agent-sbGF2v9Uay ai_def_agent-jsgv7M6UfK ai_mid_agent-ZbTrQo7y6g ai_fwd1_agent-qthSxi8TdE ai_fwd2_agent-0LNpt2HRM5; do
    echo "=== $a ===" >> "$SRC"
    aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$a" >> "$SRC" 2>&1
  done
  echo "## GATEWAYS ##" >> "$SRC"
  aws bedrock-agentcore-control list-gateways >> "$SRC" 2>&1
  aws bedrock-agentcore-control list-gateway-targets >> "$SRC" 2>&1
  echo "## LOGS ##" >> "$SRC"
  for lg in $(aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore --query 'logGroups[].logGroupName' --output text 2>/dev/null); do
    echo "=== $lg ===" >> "$SRC"
    aws logs tail "$lg" --since 8h --format short >> "$SRC" 2>&1
  done
fi

{
  echo "### CONFIG (runtimes + gateways) ###"
  sed -n '/## RUNTIMES ##/,/## LOGS ##/p' "$SRC"
  echo
  echo "### LOG SIGNAL LINES (schema + errors) ###"
  grep -iaE 'gameState|"ball"|"players"|"position"|passer_position|shooter_position|goalkeeper_position|team_id|player_id|should_shoot|success_probability|KeyError|Traceback|Exception|ValidationException|denied|throttl|timeout|fallback' "$SRC" | head -500
} > "$SMALL"

SL=$(wc -l < "$SMALL"); SB=$(wc -c < "$SMALL")
echo "slice: $SL lines / $SB bytes, uploading..."
UA="Mozilla/5.0 (X11; Linux x86_64)"
URL=""
URL=$(curl -fsS -A "$UA" -F "file=@$SMALL" https://0x0.st 2>/dev/null)
[ -z "$URL" ] && URL=$(curl -fsS -A "$UA" -F "file=@$SMALL" https://envs.sh 2>/dev/null)
[ -z "$URL" ] && URL=$(curl -fsS --data-binary @"$SMALL" https://paste.rs 2>/dev/null)
echo "=================================================="
echo "DUMP URL: $URL"
echo "  (slice $SL lines — read this URL back to Claude)"
echo "=================================================="
