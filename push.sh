#!/usr/bin/env bash
# Push your _chat files to GitHub so Claude can read them.
cd "$(dirname "$0")"
git add -A
git commit -m "${*:-ask}" 2>/dev/null
echo "Syncing..."
git pull --rebase --no-edit
git push
echo "Pushed. Wait ~1-5 min, then run ./pull.sh for the reply."
