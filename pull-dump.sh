#!/usr/bin/env bash
# Football Cup — pull live AgentCore artifacts from CloudShell, upload, print URL.
# Usage in CloudShell:  curl -fsSL https://raw.githubusercontent.com/nexusailabs/shfoot/main/pull-dump.sh | bash
set +e
OUT="$HOME/fc-dump.txt"; : > "$OUT"

echo "## RUNTIMES ##" >> "$OUT"
for a in ai_gk_agent-sbGF2v9Uay ai_def_agent-jsgv7M6UfK ai_mid_agent-ZbTrQo7y6g ai_fwd1_agent-qthSxi8TdE ai_fwd2_agent-0LNpt2HRM5; do
  echo "=== $a ===" >> "$OUT"
  aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$a" >> "$OUT" 2>&1
done

echo "## GATEWAYS ##" >> "$OUT"
aws bedrock-agentcore-control list-gateways >> "$OUT" 2>&1
aws bedrock-agentcore-control list-gateway-targets >> "$OUT" 2>&1

echo "## LOGS (real gameState + decisions + Gateway errors) ##" >> "$OUT"
for lg in $(aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore --query 'logGroups[].logGroupName' --output text 2>/dev/null); do
  echo "=== $lg ===" >> "$OUT"
  aws logs tail "$lg" --since 8h --format short >> "$OUT" 2>&1
done

LINES=$(wc -l < "$OUT")
echo "captured $LINES lines, uploading..."
URL=$(curl -fsS -F "file=@$OUT" https://0x0.st 2>/dev/null)
[ -z "$URL" ] && URL=$(curl -fsS --upload-file "$OUT" https://transfer.sh/fc-dump.txt 2>/dev/null)
echo "=================================================="
echo "DUMP URL: $URL"
echo "  (lines: $LINES — read this URL back to Claude)"
echo "=================================================="
