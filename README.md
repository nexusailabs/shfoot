# football-cup — AWS Agentic Football Cup kit (6/24 Shanghai)

Companion to `~/ai-league/` (6/23). Same operator, next day, GO BUILD track.

| file | what |
|---|---|
| `STRATEGY.md` | full strategy, AI-League→Football-Cup transfer, risks. **Read first.** |
| `policy.py` | deterministic per-tick decision policy (Pillar 2). Pure stdlib, the win/lose core. |
| `test_policy.py` | unit tests asserting anti-swarm invariants. `python3 -m unittest -v test_policy` |
| `squad.py` | Strands 5-role Graph wiring (Pillar 1+3) + runtime adapter. `python3 squad.py --selftest` |
| `prompts/{gk,def,mid,fwd}.md` | terse role system prompts. Tune wording, not the numbers. |

## One-shot setup (any laptop, incl. venue Windows machine)
Clone, then run the script for your OS. It creates `.venv`, installs deps, and runs the sanity checks. **The decision core is pure stdlib, so the sanity checks pass even if the strands/boto3 install fails** (only `squad.py` deploy needs them).

```
git clone https://github.com/nexusailabs/shfoot && cd shfoot
```
| OS | run |
|---|---|
| **Windows (cmd)** | double-click **`setup.bat`** (or `setup.bat` in a terminal) |
| **Windows (PowerShell)** | `powershell -ExecutionPolicy Bypass -File .\setup.ps1` |
| **macOS / Linux** | `bash setup.sh` |

Expect `KEYS+CHAIN GREEN` and `OK` (23 tests). Clipboard schema-check on Windows: `Get-Clipboard | .venv\Scripts\python reconcile.py -`.

## On 6/24, in order
0. **Activate the venv** (the setup script already created it): Windows `.venv\Scripts\activate` · mac/Linux `source .venv/bin/activate`.
1. **First 30 min = reconcile schema. Run `reconcile.py` FIRST.** Grab one real observation from the Player Portal, then:
   `pbpaste | python reconcile.py -`  (or `python reconcile.py portal_obs.json`).
   It reports missing/renamed keys, runs the full chain for all 5 roles, and probes the x-axis direction — the football analogue of the AI-League "verify INPUT != {} in minute 5". Fix `state_from_obs()` until it prints **GREEN**, then **eyeball direction in match 1**. Decision logic transfers unchanged.
2. **Deploy baseline squad before the first match** (AI League HK lost to deploy delay — don't repeat).
3. **Tuning round = the win.** Adjust the tunables at the top of `policy.py` (SHOT_RANGE, PRESS_TRIGGER, zone anchors) ONE at a time; keep `test_policy` green.
4. **Confirm model availability** (Nova Lite vs others) and that external API calls in tools are/aren't allowed.

## Quick verify (offline, no AWS)
```
cd ~/football-cup
source .venv/bin/activate
python reconcile.py                 # schema/chain/direction self-check (built-in sample -> GREEN)
python -m unittest -v test_policy
python squad.py --selftest
```
