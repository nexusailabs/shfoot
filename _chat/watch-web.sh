#!/usr/bin/env bash
# Mac-side auto-responder for the WEB chat (Cloudflare Worker + D1).
# Polls /api/pending; for each new operator message, feeds PRIMER + full thread
# to `claude -p`, then posts the answer to /api/reply. Context is injected every
# call (PRIMER + running conversation) so the web Claude "remembers" within-chat.
#
# Run on the Mac:  bash _chat/watch-web.sh     (stop: touch _chat/STOP)
set -uo pipefail
cd "$(dirname "$0")/.."                         # repo root
U="${WORKER_URL:-https://shfoot.mytimeskr.workers.dev}"
KEY="${AGENT_KEY:-e8f751d692ddf86bfdf804e4}"
POLL="${POLL_SECS:-15}"
TMP="$(mktemp -d)"
echo "[web-watch] up. polling $U every ${POLL}s  (touch _chat/STOP to quit)"

while true; do
  [ -e _chat/STOP ] && { echo "[web-watch] STOP."; rm -f _chat/STOP; break; }
  pend="$(curl -s --max-time 20 "$U/api/pending?key=$KEY")"
  n="$(printf '%s' "$pend" | jq 'length' 2>/dev/null || echo 0)"
  if [ "${n:-0}" -gt 0 ]; then
    thread="$(curl -s --max-time 20 "$U/api/poll" | jq -r '.[] | (if .role=="user" then "운영자" else "클로드" end) + ": " + .text' 2>/dev/null)"
    printf '%s' "$pend" | jq -c '.[]' | while read -r row; do
      id="$(printf '%s' "$row" | jq -r '.id')"
      q="$(printf '%s' "$row" | jq -r '.text')"
      img="$(printf '%s' "$row" | jq -r '.img // empty')"
      # assemble prompt via printf (no shell eval of operator text -> injection-safe)
      cat _chat/PRIMER.md > "$TMP/p.txt"
      printf '\n\n== 지금까지의 대화 ==\n' >> "$TMP/p.txt"
      printf '%s\n' "$thread"             >> "$TMP/p.txt"
      printf '\n== 방금 운영자 질문 (id=%s) ==\n' "$id" >> "$TMP/p.txt"
      printf '%s\n'  "$q"                  >> "$TMP/p.txt"
      if [ -n "$img" ]; then
        printf '%s' "${img#*,}" | python3 -c "import sys,base64;open('$TMP/shot.jpg','wb').write(base64.b64decode(sys.stdin.read()))" 2>/dev/null \
          && printf '\n[운영자가 캡쳐 이미지를 첨부함. 반드시 Read 도구로 이 파일을 열어 화면을 보고 답하라: %s/shot.jpg]\n' "$TMP" >> "$TMP/p.txt"
      fi
      printf '\n위 PRIMER와 대화 맥락(첨부 캡쳐가 있으면 그 화면)을 바탕으로 운영자에게 한국어로 간결·실행가능하게 답해라. 답변 본문만 출력.\n' >> "$TMP/p.txt"
      ans="$(claude -p --allowedTools "Read" "Bash" < "$TMP/p.txt" 2>/dev/null)"
      [ -z "$ans" ] && ans="(일시적으로 답 생성 실패 — 다시 보내줘)"
      jq -n --arg t "$ans" --argjson r "$id" --arg k "$KEY" '{text:$t,replyTo:$r,key:$k}' \
        | curl -s --max-time 20 -X POST "$U/api/reply" -H 'content-type: application/json' --data-binary @- >/dev/null
      echo "[web-watch] answered id=$id"
    done
  fi
  sleep "$POLL"
done
