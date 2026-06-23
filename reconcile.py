#!/usr/bin/env python3
"""
Schema-reconcile harness — the FIRST thing to run on 6/24 (first 30 min).

Why this exists (AWS AI League 6/23 post-mortem): we lost ~4000 vs #1 7264 because
custom tools silently received empty `{}` input and we only discovered it on-site at
minute ~90. The Football Cup analogue is `state_from_obs()` quietly not matching the
Player Portal's real observation dict -> KeyError, or worse, a FLIPPED coordinate axis
that throws no error but makes every player run the wrong way.

So before building/tuning anything: paste ONE real observation from the portal and run

    ./.venv/bin/python reconcile.py portal_obs.json
    # or:  pbpaste | ./.venv/bin/python reconcile.py -

This reports, in seconds:
  1. which expected keys are PRESENT / MISSING / renamed (the `{}`-input check),
  2. whether the full chain obs -> state_from_obs -> decide_action -> action_to_runtime
     runs for all 5 roles (each link verified, AI-League lesson #1),
  3. a coordinate-direction probe so a FLIPPED axis can't pass silently,
  4. a GREEN / FIXME verdict naming the exact edits needed in squad.state_from_obs().

No AWS, no strands, no network. Pure diagnosis.
"""
from __future__ import annotations

import json
import sys

from policy import Role, OPP_GOAL, dist, decide_action, Action
from squad import state_from_obs, action_to_runtime, act

# Keys squad.state_from_obs() currently expects. Hard = indexed (KeyError if absent);
# soft = .get() with a default (won't crash but a rename means silently-wrong data).
TOP_HARD = ["me", "ball"]
TOP_SOFT = ["teammates", "opponents", "team_has_ball", "i_have_ball",
            "my_score", "opp_score"]
ENTITY_HARD = []                       # ent() uses .get for everything
ENTITY_SOFT = ["x", "y", "vx", "vy", "stamina"]

# A built-in GRF-style sample so the harness is runnable NOW (proves it works before
# 6/24). On the day, replace with the portal's real observation.
SAMPLE = {
    "me": {"x": 0.85, "y": 0.5, "stamina": 0.9},
    "ball": {"x": 0.85, "y": 0.5},
    "teammates": [{"x": 0.6, "y": 0.4}, {"x": 0.55, "y": 0.6}],
    "opponents": [{"x": 0.9, "y": 0.5}, {"x": 0.7, "y": 0.5}],
    "team_has_ball": True, "i_have_ball": True,
    "my_score": 0, "opp_score": 0,
}


def _load(arg: str | None) -> dict:
    if arg is None:
        print("[i] no obs file given -> using built-in SAMPLE (replace on 6/24)\n")
        return SAMPLE
    raw = sys.stdin.read() if arg == "-" else open(arg, encoding="utf-8").read()
    return json.loads(raw)


def _key_report(obs: dict) -> list[str]:
    """Return a list of FIXME lines (empty == all keys mapped)."""
    fixmes: list[str] = []
    present = set(obs)
    print("== 1. TOP-LEVEL KEYS (the empty-`{}` check) ==")
    for k in TOP_HARD:
        if k in present:
            print(f"  ok    [hard] {k}")
        else:
            print(f"  FAIL  [hard] {k:14s} MISSING -> KeyError. rename in state_from_obs()")
            fixmes.append(f'obs["{k}"]: portal key differs -> remap. candidates: {sorted(present)}')
    for k in TOP_SOFT:
        if k in present:
            print(f"  ok    [soft] {k}")
        else:
            print(f"  WARN  [soft] {k:14s} absent -> defaults silently. confirm portal lacks it")
            fixmes.append(f'obs.get("{k}"): absent -> using default. is it named differently?')

    # entity-level keys, sampled from `me`
    me = obs.get("me") if isinstance(obs.get("me"), dict) else None
    print("\n== 2. ENTITY KEYS (sampled from `me`) ==")
    if me is None:
        print("  (no usable `me` dict to sample)")
    else:
        for k in ENTITY_SOFT:
            mark = "ok  " if k in me else "WARN"
            note = "" if k in me else " absent -> default (0.0 / stamina 1.0). confirm name"
            print(f"  {mark}  {k:8s}{note}")
            if k not in me and k in ("x", "y"):
                fixmes.append(f'entity "{k}" absent -> position will be 0.0. CRITICAL: find real key in {sorted(me)}')
    return fixmes


def _chain_report(obs: dict) -> bool:
    """Run the full chain for all 5 roles. Return True if every link survived."""
    print("\n== 3. FULL CHAIN per role (obs -> state -> decide -> runtime) ==")
    try:
        gs = state_from_obs(obs)
    except Exception as e:
        print(f"  FAIL  state_from_obs() raised {type(e).__name__}: {e}")
        return False
    ok = True
    for role in Role:
        try:
            out = act(role.value, obs)
            print(f"  ok    {role.value:6s} -> {json.dumps(out, separators=(',', ':'))}")
        except Exception as e:
            print(f"  FAIL  {role.value:6s} -> {type(e).__name__}: {e}")
            ok = False
    return ok


def _direction_probe(obs: dict) -> None:
    """A flipped x-axis throws NO error but loses every match. Probe it explicitly.

    Convention in policy.py: OUR goal x=0.0, OPP goal x=1.0, x grows left->right.
    Put a ball-carrying FWD just in front of OPP_GOAL: a correct mapping shoots.
    If the real portal axis is reversed, the SAME physical 'near opp goal' position
    will arrive as a small x and the FWD will NOT shoot -> visible mismatch here.
    """
    print("\n== 4. COORDINATE-DIRECTION PROBE (silent-killer guard) ==")
    print(f"  policy assumes: OUR goal x=0.0, OPP goal x=1.0 (attack toward x=1.0)")
    probe = dict(obs)
    probe["me"] = {"x": OPP_GOAL[0] - 0.08, "y": 0.5, "stamina": 1.0}
    probe["ball"] = {"x": OPP_GOAL[0] - 0.08, "y": 0.5}
    probe["team_has_ball"] = True
    probe["i_have_ball"] = True
    try:
        d = decide_action(Role.FWD, state_from_obs(probe))
        verdict = "ok" if d.action == Action.SHOOT else "CHECK"
        print(f"  FWD on ball at x={OPP_GOAL[0]-0.08:.2f} (near OPP goal) -> {d.action.value} [{verdict}]")
        if d.action != Action.SHOOT:
            print("  !! NOT shooting near opp goal -> x-axis may be FLIPPED, or SHOT_RANGE too small.")
            print("     On 6/24: confirm with a live tick which x is the opponent goal, then either")
            print("     flip x in state_from_obs() (x -> 1.0 - x) or adjust OPP_GOAL/SHOT_RANGE.")
    except Exception as e:
        print(f"  probe raised {type(e).__name__}: {e}")
    print("  NOTE: code can't see the pitch. In the FIRST match, EYEBALL that FWD advances")
    print("        toward the opponent goal. That live confirmation is the real gate (lesson #1).")


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        obs = _load(arg)
    except Exception as e:
        print(f"could not parse observation: {e}")
        return 2
    if not isinstance(obs, dict):
        print("observation is not a JSON object — paste the per-tick state dict.")
        return 2

    fixmes = _key_report(obs)
    chain_ok = _chain_report(obs)
    _direction_probe(obs)

    print("\n== VERDICT ==")
    if chain_ok and not fixmes:
        print("  GREEN — chain runs for all 5 roles, all expected keys mapped.")
        print("  Next: deploy the baseline squad, then EYEBALL direction in match 1.")
        return 0
    print("  FIXME before deploying — edit squad.state_from_obs():")
    for f in fixmes:
        print(f"    - {f}")
    if not chain_ok:
        print("    - a role chain raised above; fix the key it tripped on first.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
