#!/usr/bin/env bash
# Run in CloudShell AFTER a match with the instrumented build. Pulls our agents'
# FCINST timing lines from CloudWatch, summarizes cold-vs-warm, uploads.
set +e
cd "$HOME" || exit 1
OUT="$HOME/fcinst.txt"; : > "$OUT"
echo "## FCINST raw (last 20m) ##" >> "$OUT"
LGS=$(aws logs describe-log-groups --region us-east-1 --log-group-name-prefix /aws/bedrock-agentcore --query 'logGroups[].logGroupName' --output text 2>/dev/null)
for lg in $LGS; do
  aws logs tail "$lg" --region us-east-1 --since 20m --format short 2>/dev/null | grep -a FCINST
done | tee -a "$OUT" | tail -5

echo "" >> "$OUT"
echo "## SUMMARY ##" >> "$OUT"
python3 - "$OUT" >> "$OUT" 2>&1 <<'PY'
import sys, json, re
lines=[l for l in open(sys.argv[1]) if 'FCINST' in l]
recs=[]
for l in lines:
    m=re.search(r'FCINST (\{.*\})', l)
    if m:
        try: recs.append(json.loads(m.group(1)))
        except Exception: continue  # best-effort diagnostic parse: skip a malformed log line
if not recs:
    print("no FCINST records found (stdout may not reach CloudWatch with observability off -> re-enable observability and redeploy)")
else:
    n1=sum(1 for r in recs if r.get('n')==1)
    hm=[r['handler_ms'] for r in recs if 'handler_ms' in r]
    print(f"records={len(recs)}  n==1(cold-fresh-process)={n1} ({round(100*n1/len(recs))}%)")
    print(f"handler_ms (our code): min={min(hm)} max={max(hm)} avg={round(sum(hm)/len(hm),2)}")
    print(f"max n seen (warm reuse depth): {max(r.get('n',0) for r in recs)}")
    print("INTERPRETATION: high n==1% => cold-start per tick (container churn). low handler_ms => our code is fast; the 800ms is AgentCore infra, not us.")
PY

UA="Mozilla/5.0 (X11; Linux x86_64)"
URL=$(curl -fsS -A "$UA" -F "file=@$OUT" https://0x0.st 2>/dev/null)
[ -z "$URL" ] && URL=$(curl -fsS --data-binary @"$OUT" https://paste.rs 2>/dev/null)
echo "=================================================="
echo "FCINST URL: $URL"
echo "=================================================="
