#!/usr/bin/env bash
# Mac-side auto-responder for the GitHub relay channel.
# Polls the repo every POLL_SECS; when a NEW question file appears in _chat/
# (q*.txt / err*.txt / obs*.json), invokes `claude -p` with the kit docs as
# context, appends a Korean answer to _chat/REPLY.md, and pushes.
# Idle ticks cost only a `git pull` (no model call) -> cap-efficient.
#
# Run on the Mac (NOT the venue laptop):
#   cd ~/football-cup && bash _chat/watch.sh
# Stop: Ctrl-C, or `touch _chat/STOP` from anywhere.

set -uo pipefail
cd "$(dirname "$0")/.."          # repo root
POLL_SECS="${POLL_SECS:-60}"
echo "[watch] relay auto-responder up. polling every ${POLL_SECS}s. (touch _chat/STOP to quit)"

answer() {
  local qfile="$1" qtext
  qtext="$(cat "$qfile")"
  echo "[watch] $(date '+%H:%M:%S') answering $qfile"
  claude -p "You are the operator's on-site copilot at the AWS Agentic Football Cup (Shanghai, 6/24). \
For context, READ these files in this repo first: STRATEGY.md, KIRO-CHEAT.md, README.md, policy.py, reconcile.py. \
The operator just sent this from the venue laptop:\n\n$qtext\n\n\
Write a concise, actionable answer IN KOREAN. PREPEND it to _chat/REPLY.md under a '## <HH:MM> re: $(basename "$qfile")' heading, keeping all existing content below. Then stop." \
    --allowedTools "Read" "Edit" "Bash" \
    >/dev/null 2>&1 || { echo "[watch] claude -p failed on $qfile"; return 1; }
}

while true; do
  [ -e _chat/STOP ] && { echo "[watch] STOP found, exiting."; rm -f _chat/STOP; break; }
  git pull --no-edit -q 2>/dev/null
  for q in _chat/q*.txt _chat/err*.txt _chat/obs*.json; do
    [ -e "$q" ] || continue
    stamp="_chat/.answered_$(basename "$q")"
    if [ ! -e "$stamp" ] || [ "$q" -nt "$stamp" ]; then
      if answer "$q"; then
        touch "$stamp"
        git add -A
        git commit -q -m "relay: reply to $(basename "$q")" 2>/dev/null
        git pull --rebase --no-edit -q 2>/dev/null
        git push -q 2>/dev/null && echo "[watch] pushed reply for $(basename "$q")"
      fi
    fi
  done
  sleep "$POLL_SECS"
done
