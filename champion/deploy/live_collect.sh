#!/usr/bin/env bash
# Real-time full-log collector for a live match session.
# Tails ALL 5 AgentCore agent log groups (FCTICK positions + FCINST timing +
# errors/decisions) live into ONE merged file for immediate analysis.
#
#   ./live_collect.sh start     # begin streaming all agent logs (background)
#   ./live_collect.sh stop      # stop all tails
#   ./live_collect.sh status    # what's running + line counts
#
# Needs /tmp/awsenv sourced (workshop creds). Output -> _build/live/agents.log
set -uo pipefail
ROOT="/Users/kei/football-cup"
TK="$ROOT/_build/tk-venv/bin"
export PATH="$TK:$PATH"
OUTDIR="$ROOT/_build/live"; mkdir -p "$OUTDIR"
LOG="$OUTDIR/agents.log"
PIDF="$OUTDIR/tails.pids"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

_creds() { [ -f /tmp/awsenv ] && { set -a; . /tmp/awsenv; set +a; }; export AWS_DEFAULT_REGION="$REGION"; }

start() {
  _creds
  aws sts get-caller-identity >/dev/null 2>&1 || { echo "ERROR: creds invalid/expired — re-grab /tmp/awsenv"; exit 1; }
  : > "$PIDF"
  local groups
  groups=$(aws logs describe-log-groups --region "$REGION" \
      --log-group-name-prefix /aws/bedrock-agentcore \
      --query 'logGroups[].logGroupName' --output text 2>/dev/null)
  [ -z "$groups" ] && { echo "no /aws/bedrock-agentcore log groups yet (deploy + run a match first)"; exit 1; }
  echo "# live_collect start $(date -u +%FT%TZ)" >> "$LOG"
  local n=0
  for lg in $groups; do
    # --follow streams new events live; prefix each line with the short group name
    ( aws logs tail "$lg" --region "$REGION" --follow --format short 2>/dev/null \
        | sed "s|^|[$(basename "$lg")] |" >> "$LOG" ) &
    echo $! >> "$PIDF"; n=$((n+1))
  done
  echo "streaming $n log groups -> $LOG  (pids in $PIDF)"
  echo "tail -f $LOG   # to watch; grep FCTICK/FCINST for positions/timing"
}

stop() {
  [ -f "$PIDF" ] || { echo "no tails running"; return; }
  while read -r p; do kill "$p" 2>/dev/null; done < "$PIDF"
  rm -f "$PIDF"; echo "stopped all tails"
}

status() {
  if [ -f "$PIDF" ]; then
    local alive=0; while read -r p; do kill -0 "$p" 2>/dev/null && alive=$((alive+1)); done < "$PIDF"
    echo "tails alive: $alive"
  else echo "no tails running"; fi
  [ -f "$LOG" ] && echo "log lines: $(wc -l < "$LOG")  FCTICK: $(grep -ac FCTICK "$LOG")  FCINST: $(grep -ac FCINST "$LOG")  ERROR: $(grep -aci error "$LOG")"
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}"; exit 1 ;;
esac
