#!/usr/bin/env bash
# Powered-baseline aggressive practice loop. Runs N aggressive matches sequentially
# (one at a time — the engine rejects a 2nd concurrent create), appending each JSON
# summary as one line to _build/BASELINE-aggressive.jsonl. Behavior-neutral build
# (a742108 + FCTICK GK-only). Metrics that matter: opp_on_target (primary), us_shots
# + us_on_target + score (conversion). W/L is confirmatory only.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
set -a; . /tmp/awsenv; set +a
export PATH="$PWD/_build/tk-venv/bin:$PATH"
N="${1:-12}"
VARIANT="${2:-aggressive}"
OUT="${OUT:-_build/BASELINE-aggressive.jsonl}"
echo "baseline loop: $N aggressive matches -> $OUT" >&2
for i in $(seq 1 "$N"); do
  echo "=== match $i/$N $(date +%H:%M:%S) ===" >&2
  for attempt in 1 2 3 4 5; do
    raw="$(python3 champion/deploy/run_match.py "$VARIANT" 2>>_build/baseline_loop.err)"
    # everything from the first top-level '{' to EOF is the pretty-printed JSON summary
    json="$(printf '%s' "$raw" | python3 -c 'import sys,json
t=sys.stdin.read()
try:
 print(json.dumps(json.loads(t[t.index("{"):])))
except Exception:
 pass' 2>/dev/null)"
    if [ -n "$json" ]; then
      printf '%s\n' "$json" >> "$OUT"
      echo "  logged: $(printf '%s' "$json" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("score",d.get("score"),d.get("result"),"us_shots",d.get("us_shots"),"us_on_t",d.get("us_on_target"),"opp_on_t",d.get("opp_on_target"),"lat",d.get("us_avg_latency_ms"))' 2>/dev/null)" >&2
      break
    fi
    echo "  attempt $attempt failed (likely 'in progress'); backoff 20s" >&2
    sleep 20
  done
done
echo "=== baseline loop done: $(wc -l < "$OUT") matches in $OUT ===" >&2
