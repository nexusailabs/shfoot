# _chat — talk to Claude through GitHub (China-safe relay)

Git over HTTPS works from China (slow but reliable); this public repo is the message bus.

## Operator (venue Windows laptop)
1. Save your question / error / portal observation as a file in `_chat/`, e.g. `_chat/q.txt`
   (paste a screenshot's text, an error trace, or a JSON obs — anything).
2. Double-click **`push.bat`** (repo root). It commits + pulls + pushes.
3. Wait ~1–5 min, then double-click **`pull.bat`** — it prints `_chat/REPLY.md` (Claude's answer).

## Claude (Mac side)
- Reads new `_chat/*` files via `git pull`, writes answers to `_chat/REPLY.md`, pushes.
- If a polling loop is running on the Mac, replies are automatic within a few minutes.

## Rules to avoid conflicts
- Operator writes ONLY to your own files (`_chat/q*.txt`, `_chat/err.txt`, `_chat/obs.json`).
- Claude writes ONLY to `_chat/REPLY.md` (appends, newest at top).
- Never both edit the same file -> no merge conflicts.
