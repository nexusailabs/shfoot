#!/usr/bin/env bash
# Pull Claude's latest reply and print it.
cd "$(dirname "$0")"
git pull --no-edit
echo "===================== _chat/REPLY.md ====================="
cat _chat/REPLY.md
echo "=========================================================="
