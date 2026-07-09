#!/usr/bin/env python3
"""
Fast offline aggression sweep: vary policy knobs, measure goals/conceded vs a
panel of opponent archetypes in sim2. Low-trust physics, so use RELATIVE ranking
to pick a direction to validate in a real match (run_match.py).

Run: _build/tk-venv/bin/python champion/sweep.py
"""
import importlib
import statistics as st

import champion.policy_v2 as P
import champion.sim2 as S


def run_panel(matches=4, ticks=300):
    """champion (current knobs) vs each archetype. Returns (gf, ga) summed."""
    out = {}
    for name, opp in [("baseline", S.baseline_brain), ("swarm", S.swarm_brain),
                      ("mirror", S.champion_brain)]:
        gf = ga = 0
        for m in range(matches):
            sc = S.play(S.champion_brain, opp, ticks=ticks, seed=m + 1)
            gf += sc["score"][0]; ga += sc["score"][1]
        out[name] = (gf, ga)
    return out


def set_knobs(shoot_min, fwd_ax, fwd_push, mid_push, carry_dist, risk):
    P.SHOOT_MIN_PROB = shoot_min
    P.CARRY_TO_SHOOT_DIST = carry_dist
    for fid in (P.FWD1, P.FWD2):
        c = P.ROLE_CONFIG[fid]
        c.anchor_ax = fwd_ax
        c.push_when_attacking = fwd_push
        c.risk = risk
    P.ROLE_CONFIG[P.MID].push_when_attacking = mid_push


CONFIGS = [
    # name, shoot_min, fwd_ax, fwd_push, mid_push, carry_dist, risk
    ("current",      0.34, 0.66, 0.30, 0.42, 30.0, 0.62),
    ("more_shots",   0.28, 0.70, 0.34, 0.48, 34.0, 0.70),
    ("box_camp",     0.30, 0.74, 0.28, 0.46, 36.0, 0.66),
    ("hi_press_atk", 0.30, 0.68, 0.38, 0.55, 34.0, 0.72),
    ("patient",      0.40, 0.60, 0.26, 0.40, 28.0, 0.50),
    ("max_aggro",    0.24, 0.74, 0.40, 0.58, 38.0, 0.80),
]


def main():
    if not hasattr(S, "play"):
        print("sim2 has no play(); abort"); return
    base = dict(SHOOT_MIN_PROB=P.SHOOT_MIN_PROB, CARRY=P.CARRY_TO_SHOOT_DIST)
    print(f"{'config':14s} {'vs baseline':>14s} {'vs swarm':>12s} {'vs mirror':>12s}  score")
    rows = []
    for cfg in CONFIGS:
        name = cfg[0]
        set_knobs(*cfg[1:])
        r = run_panel()
        # objective: maximize goals-for minus goals-against across the panel,
        # weight mirror (strong opp) highest, swarm leak penalized but not dominant.
        gf = sum(v[0] for v in r.values()); ga = sum(v[1] for v in r.values())
        mir = r["mirror"]; bas = r["baseline"]
        score = (bas[0] - bas[1]) * 1.0 + (mir[0] - mir[1]) * 1.5 + (r["swarm"][0] - r["swarm"][1]) * 0.3
        rows.append((score, name, r))
        print(f"{name:14s} {str(r['baseline']):>14s} {str(r['swarm']):>12s} {str(r['mirror']):>12s}  {score:+.1f}")
    rows.sort(reverse=True)
    print("\nRANKED:")
    for score, name, r in rows:
        print(f"  {name:14s} score={score:+.1f}  baseline={r['baseline']} swarm={r['swarm']} mirror={r['mirror']}")
    print(f"\nWINNER: {rows[0][1]}")


if __name__ == "__main__":
    main()
