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

from policy import Role, OPP_GOAL, decide_action, Action
from squad import state_from_obs, action_to_runtime, VALID_ACTIONS

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

    # entity-level keys — check EVERY entity source, not just `me`. A renamed
    # x/y on `ball` or any player defaults to 0.0 and would otherwise pass GREEN
    # while the policy reads garbage positions (Codex blocker reconcile.py:79).
    print("\n== 2. ENTITY KEYS (me, ball, and every player) ==")

    def _check_entity(label: str, d) -> None:
        if not isinstance(d, dict):
            print(f"  FAIL  {label:14s} not a dict -> can't read position")
            fixmes.append(f'{label}: expected an object with x/y, got {type(d).__name__}')
            return
        for k in ENTITY_SOFT:
            present = k in d
            mark = "ok  " if present else "WARN"
            note = "" if present else " absent -> default (0.0 / stamina 1.0)"
            print(f"  {mark}  {label}.{k:8s}{note}")
            if not present and k in ("x", "y"):
                fixmes.append(f'{label}.{k} absent -> position becomes 0.0. CRITICAL: real key in {sorted(d)}')

    _check_entity("me", obs.get("me"))
    _check_entity("ball", obs.get("ball"))
    for grp in ("teammates", "opponents"):
        lst = obs.get(grp)
        if isinstance(lst, list) and lst:
            _check_entity(f"{grp}[0]", lst[0])
        elif lst is None:
            print(f"  --    {grp:14s} absent (checked at top level above)")
        else:
            print(f"  ok    {grp:14s} present but empty -> no entity to sample")
    return fixmes


def _chain_report(obs: dict) -> bool:
    """Run the full chain for all 5 roles, with NO swallowing fallback.

    We deliberately call state_from_obs -> decide_action -> action_to_runtime
    DIRECTLY instead of squad.act(): act() catches every exception and returns a
    MOVE fallback, which would make a broken adapter print 'ok' here and hide the
    exact failure we are trying to surface (Codex blocker reconcile.py:105 / the
    6/23 fail-loud lesson). Any exception or out-of-vocab action is a FAIL.
    """
    print("\n== 3. FULL CHAIN per role (direct, fail-loud: state->decide->runtime) ==")
    try:
        gs = state_from_obs(obs)
    except Exception as e:
        print(f"  FAIL  state_from_obs() raised {type(e).__name__}: {e}")
        return False
    ok = True
    for role in Role:
        try:
            out = action_to_runtime(decide_action(role, gs))
            if out.get("action") not in VALID_ACTIONS:
                print(f"  FAIL  {role.value:6s} -> illegal action {out.get('action')!r}")
                ok = False
            else:
                print(f"  ok    {role.value:6s} -> {json.dumps(out, separators=(',', ':'))}")
        except Exception as e:
            print(f"  FAIL  {role.value:6s} -> {type(e).__name__}: {e}")
            ok = False
    return ok


def _direction_probe(obs: dict) -> str:
    """Coordinate direction. Returns 'UNVERIFIED' | 'OK' | 'FLIPPED'.

    HONEST LIMITATION (Codex blocker reconcile.py:123): a static observation alone
    CANNOT tell us which x is the opponent goal — overwriting `me`/`ball` with our
    own OPP_GOAL coords just re-tests our own convention (circular, always 'shoots').
    So we do NOT claim the axis is correct from a sample obs. We resolve it only with
    a real signal:
      * env FBALL_ATTACK=right|left  (you set it after seeing one live tick), or
      * a labeled obs key  obs['attack_direction'] = 'right'|'left'.
    Right == our policy convention (attack toward x=1.0). Left == portal x is flipped
    -> fix with x -> 1.0 - x in state_from_obs(). Absent both -> UNVERIFIED, eyeball live.
    """
    import os
    print("\n== 4. COORDINATE-DIRECTION (cannot be verified from a static obs) ==")
    print("  policy convention: OUR goal x=0.0, OPP goal x=1.0 (attack toward x=1.0)")

    # self-consistency only — proves the policy shoots under ITS OWN convention,
    # NOT that the portal agrees. Labeled explicitly so it can't read as 'verified'.
    probe = dict(obs)
    probe["me"] = {"x": OPP_GOAL[0] - 0.08, "y": 0.5, "stamina": 1.0}
    probe["ball"] = {"x": OPP_GOAL[0] - 0.08, "y": 0.5}
    probe["team_has_ball"], probe["i_have_ball"] = True, True
    try:
        d = decide_action(Role.FWD, state_from_obs(probe))
        sc = "ok" if d.action == Action.SHOOT else "BROKEN"
        print(f"  [self-consistency only] FWD at x=0.92 under our convention -> {d.action.value} [{sc}]")
    except Exception as e:
        print(f"  self-consistency probe raised {type(e).__name__}: {e}")

    signal = (str(obs.get("attack_direction", "")).lower()
              or os.environ.get("FBALL_ATTACK", "").lower())
    if signal in ("right", "r", "1", "x+"):
        print("  signal=ATTACK_RIGHT -> matches policy convention. DIRECTION: OK")
        return "OK"
    if signal in ("left", "l", "0", "x-"):
        print("  signal=ATTACK_LEFT -> portal x is FLIPPED vs policy.")
        print("  FIX: in state_from_obs(), map x -> 1.0 - x (and vx -> -vx) for every entity.")
        return "FLIPPED"
    print("  DIRECTION: UNVERIFIED — no FBALL_ATTACK env / attack_direction key supplied.")
    print("  On 6/24: watch ONE live tick, see which way FWD should attack, then re-run with")
    print("  FBALL_ATTACK=right (or left) ./.venv/bin/python reconcile.py <obs>. EYEBALL is the gate.")
    return "UNVERIFIED"


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
    direction = _direction_probe(obs)

    print("\n== VERDICT ==")
    if chain_ok and not fixmes:
        if direction == "FLIPPED":
            print("  FIXME — keys+chain OK but x-axis is FLIPPED. Apply x -> 1.0 - x in")
            print("  state_from_obs() (see §4), then re-run.")
            return 1
        print("  KEYS+CHAIN GREEN — all expected keys mapped, all 5 roles return a legal action.")
        if direction == "OK":
            print("  DIRECTION OK (signalled). Safe to deploy the baseline squad.")
            return 0
        print("  DIRECTION still UNVERIFIED — NOT fully clear. Deploy the baseline, then in match 1")
        print("  EYEBALL that FWD attacks the opponent goal; re-run with FBALL_ATTACK=right|left to lock it.")
        return 0
    print("  FIXME before deploying — edit squad.state_from_obs():")
    for f in fixmes:
        print(f"    - {f}")
    if not chain_ok:
        print("    - a role chain raised/returned illegal above; fix the key it tripped on first.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
