# Agentic Football Cup — OFFLINE 5v5 match simulator (2026-06-23)
#
# Why: the same way ai-league/sim/ reproduces the dungeon + scoring OUTSIDE the
# contest, this reproduces a faithful-enough football match so the deterministic
# squad (squad.act, policy.py) can be RUN end-to-end and MEASURED before 6/24 —
# not just unit-tested on single frames.
#
# The thesis under test (STRATEGY.md Pillar 1): role + zone discipline beats the
# ball-chasing swarm (the football analogue of AI League's stock pathfinder
# marching through spikes). This harness puts our squad on the pitch against a
# swarm and against a mirror of itself and reports goals, possession, and — the
# headline — TEAM SPREAD (a swarm collapses onto the ball; a disciplined side
# holds its shape).
#
# ZERO AWS / ZERO API: every brain here is the deterministic `squad.act()` path
# or a pure-Python swarm. The LLM-escalation path (act_or_escalate -> Bedrock)
# only works inside the contest account and is NOT exercised here — that round
# trip is what threw the API error when run against local mac creds. The floor
# we ship and measure is the zero-LLM policy, exactly like HeuristicBrain in
# ai-league/sim.
#
# Faithful pieces reused as-is:
#   - squad.act(role, obs)  -> the REAL per-tick deterministic decision
#   - policy.ROLE_ANCHOR / Role / Action vocabulary
#
# Run:  python3 sim/engine.py            # squad vs swarm, squad vs squad
#       python3 sim/engine.py --ticks 600

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import squad as SQUAD
from policy import Role, Action, ROLE_ANCHOR

ROLES = [Role.GK, Role.DEF_L, Role.DEF_R, Role.MID, Role.FWD]
VALID_ACTIONS = {a.value for a in Action}

# --------------------------------------------------------------------------- #
# physics constants (normalized pitch [0,1] x [0,1])                          #
# Side A attacks x -> 1.0 (goal at x=1). Side B attacks x -> 0.0 (goal at x=0).#
# --------------------------------------------------------------------------- #
PLAYER_SPEED = 0.035       # max player displacement per tick
BALL_FRICTION = 0.80       # ball velocity decay per tick
PASS_SPEED = 0.055         # launch speed of a pass / clear (range ~0.27, catchable by the target)
SHOOT_SPEED = 0.16         # launch speed of a shot (reaches goal from shot range)
CONTROL_RADIUS = 0.05      # a slow ball within this of a player is controlled
TACKLE_RADIUS = 0.05       # a presser/tackler within this of the carrier wins it
GOAL_HALF = 0.18           # goal mouth half-height around y=0.5
STAM_DRAIN = 0.020         # per-tick stamina cost of a sprint action
STAM_RECOVER = 0.012       # per-tick stamina recovery otherwise
SPRINT_ACTIONS = {"press", "tackle", "intercept", "dribble", "shoot"}


@dataclass
class Player:
    side: str          # "A" or "B"
    idx: int           # 0..4 -> ROLES[idx]
    x: float
    y: float
    stamina: float = 1.0

    @property
    def role(self) -> Role:
        return ROLES[self.idx]


@dataclass
class Match:
    players: list = field(default_factory=list)   # 10 players, A then B
    bx: float = 0.5
    by: float = 0.5
    bvx: float = 0.0
    bvy: float = 0.0
    carrier: int | None = None     # index into players, or None (loose ball)
    score_a: int = 0
    score_b: int = 0
    tick: int = 0

    def team(self, side: str):
        return [p for p in self.players if p.side == side]


# --------------------------------------------------------------------------- #
# setup / kickoff                                                             #
# --------------------------------------------------------------------------- #
def _anchor_global(side: str, idx: int) -> tuple[float, float]:
    ax, ay = ROLE_ANCHOR[ROLES[idx]]
    return (ax, ay) if side == "A" else (1.0 - ax, ay)   # B mirrors across x


def new_match() -> Match:
    players = []
    for side in ("A", "B"):
        for idx in range(5):
            gx, gy = _anchor_global(side, idx)
            players.append(Player(side, idx, gx, gy))
    return Match(players=players)


def kickoff(m: Match, to_side: str) -> None:
    """Reset all players to anchors and hand the ball to `to_side`'s MID at center."""
    for p in m.players:
        p.x, p.y = _anchor_global(p.side, p.idx)
    m.bx, m.by, m.bvx, m.bvy = 0.5, 0.5, 0.0, 0.0
    mid = next(i for i, p in enumerate(m.players) if p.side == to_side and p.idx == 3)
    m.players[mid].x, m.players[mid].y = 0.5, 0.5
    m.carrier = mid


# --------------------------------------------------------------------------- #
# observation builder: global match -> one agent's obs dict, in ITS attack    #
# frame (x toward the goal it attacks), so policy.py's x=1==opp-goal holds for #
# BOTH sides. Side B is mirrored across x.                                     #
# --------------------------------------------------------------------------- #
def _flip(side: str, x: float, y: float, vx: float = 0.0, vy: float = 0.0):
    if side == "A":
        return x, y, vx, vy
    return 1.0 - x, y, -vx, vy


def obs_for(m: Match, pi: int) -> dict:
    me = m.players[pi]
    mx, my, _, _ = _flip(me.side, me.x, me.y)
    bxx, byy, bvxx, bvyy = _flip(me.side, m.bx, m.by, m.bvx, m.bvy)

    teammates, opponents = [], []
    for j, p in enumerate(m.players):
        if j == pi:
            continue
        px, py, _, _ = _flip(me.side, p.x, p.y)
        rec = {"x": px, "y": py, "stamina": p.stamina}
        (teammates if p.side == me.side else opponents).append(rec)

    team_has = m.carrier is not None and m.players[m.carrier].side == me.side
    my_score = m.score_a if me.side == "A" else m.score_b
    opp_score = m.score_b if me.side == "A" else m.score_a
    return {
        "me": {"x": mx, "y": my, "stamina": me.stamina},
        "ball": {"x": bxx, "y": byy, "vx": bvxx, "vy": bvyy},
        "teammates": teammates,
        "opponents": opponents,
        "team_has_ball": team_has,
        "i_have_ball": m.carrier == pi,
        "my_score": my_score,
        "opp_score": opp_score,
    }


def _target_to_global(side: str, tgt: dict | None) -> tuple[float, float] | None:
    if not tgt:
        return None
    gx, gy, _, _ = _flip(side, tgt["x"], tgt["y"])   # flip is its own inverse on x
    return gx, gy


# --------------------------------------------------------------------------- #
# brains: (match, player_index) -> runtime action dict {action, target?}       #
# --------------------------------------------------------------------------- #
def squad_brain(m: Match, pi: int) -> dict:
    me = m.players[pi]
    return SQUAD.act(me.role.value, obs_for(m, pi))   # deterministic, no LLM


def swarm_brain(m: Match, pi: int) -> dict:
    """The naive failure mode: every player chases the ball; the carrier just
    barrels toward the opponent goal and shoots when close. No roles, no zones."""
    me = m.players[pi]
    opp_goal = (1.0, 0.5) if me.side == "A" else (0.0, 0.5)
    if m.carrier == pi:
        if math.hypot(opp_goal[0] - me.x, opp_goal[1] - me.y) <= 0.26:
            return {"action": "shoot", "target": {"x": opp_goal[0], "y": opp_goal[1]}}
        return {"action": "dribble", "target": {"x": opp_goal[0], "y": opp_goal[1]}}
    return {"action": "move", "target": {"x": m.bx, "y": m.by}}   # chase ball


# --------------------------------------------------------------------------- #
# one tick                                                                    #
# --------------------------------------------------------------------------- #
def _move_toward(p: Player, tx: float, ty: float, speed: float) -> None:
    dx, dy = tx - p.x, ty - p.y
    d = math.hypot(dx, dy)
    if d <= 1e-9:
        return
    step = min(speed, d)
    p.x = max(0.0, min(1.0, p.x + dx / d * step))
    p.y = max(0.0, min(1.0, p.y + dy / d * step))


def step(m: Match, brain_a, brain_b, latency_acc: list, illegal_acc: list) -> dict:
    """Advance one tick. Returns the tick's per-side action tallies."""
    brains = {"A": brain_a, "B": brain_b}
    actions: list[dict] = []
    tally = {"A": {}, "B": {}}

    # 1) every agent decides (timed — must clear the 500ms budget)
    for pi, p in enumerate(m.players):
        t0 = time.perf_counter()
        a = brains[p.side](m, pi)
        latency_acc.append((time.perf_counter() - t0) * 1000.0)
        if not isinstance(a, dict) or a.get("action") not in VALID_ACTIONS:
            if p.side == "A":
                illegal_acc.append(1)         # honest count of raw illegal A decisions
            a = {"action": "hold"}            # illegal -> no-op
        actions.append(a)
        tally[p.side][a["action"]] = tally[p.side].get(a["action"], 0) + 1

    # 2) resolve the carrier's ball event (kick releases possession)
    kicked = False
    if m.carrier is not None:
        c = m.players[m.carrier]
        ca = actions[m.carrier]
        tgt = _target_to_global(c.side, ca.get("target"))
        act = ca["action"]
        if act in ("pass", "clear", "shoot"):
            opp_goal = (1.0, 0.5) if c.side == "A" else (0.0, 0.5)
            if act == "shoot" or tgt is None:
                tgt = opp_goal if act == "shoot" else tgt
            if tgt is not None:
                dx, dy = tgt[0] - c.x, tgt[1] - c.y
                d = math.hypot(dx, dy) or 1.0
                spd = SHOOT_SPEED if act == "shoot" else PASS_SPEED
                m.bvx, m.bvy = dx / d * spd, dy / d * spd
                m.bx, m.by = c.x, c.y
                m.carrier = None
                kicked = True

    # 3) move every player toward their action's implied target
    for pi, p in enumerate(m.players):
        a = actions[pi]
        act = a["action"]
        speed = PLAYER_SPEED * (0.6 + 0.4 * p.stamina)     # tired => slower
        if act == "hold":
            pass
        elif pi == m.carrier and act == "dribble":
            tgt = _target_to_global(p.side, a.get("target")) or ((1.0, 0.5) if p.side == "A" else (0.0, 0.5))
            _move_toward(p, tgt[0], tgt[1], speed)
        else:
            tgt = _target_to_global(p.side, a.get("target"))
            if tgt is None:                       # press/tackle/intercept w/o target -> ball
                tgt = (m.bx, m.by)
            _move_toward(p, tgt[0], tgt[1], speed)
        # stamina bookkeeping
        if act in SPRINT_ACTIONS:
            p.stamina = max(0.0, p.stamina - STAM_DRAIN)
        else:
            p.stamina = min(1.0, p.stamina + STAM_RECOVER)

    # 4) carrier keeps the ball glued unless it was kicked away this tick
    if m.carrier is not None and not kicked:
        c = m.players[m.carrier]
        m.bx, m.by, m.bvx, m.bvy = c.x, c.y, 0.0, 0.0

    # 5) loose ball travels
    if m.carrier is None:
        m.bx += m.bvx
        m.by += m.bvy
        m.bvx *= BALL_FRICTION
        m.bvy *= BALL_FRICTION

    # 6) goal / out-of-bounds check (only meaningful for a loose, travelling ball)
    scored = _check_goal(m)

    # 7) possession contest (skip the tick we just scored & re-kicked off)
    if not scored:
        _resolve_possession(m, actions)

    return tally


def _check_goal(m: Match) -> bool:
    if m.carrier is not None:
        return False
    in_mouth = abs(m.by - 0.5) <= GOAL_HALF
    if m.bx >= 1.0:
        if in_mouth:
            m.score_a += 1
            kickoff(m, "B")
            return True
        m.bx, m.bvx = 1.0, 0.0                    # rebound off back wall, stay loose
    elif m.bx <= 0.0:
        if in_mouth:
            m.score_b += 1
            kickoff(m, "A")
            return True
        m.bx, m.bvx = 0.0, 0.0
    if m.by <= 0.0:
        m.by, m.bvy = 0.0, -m.bvy
    elif m.by >= 1.0:
        m.by, m.bvy = 1.0, -m.bvy
    return False


def _resolve_possession(m: Match, actions: list) -> None:
    # (a) tackle/press steal: a defender within TACKLE_RADIUS of the carrier who
    #     chose an engaging action wins the ball (closest such defender).
    if m.carrier is not None:
        c = m.players[m.carrier]
        stealers = [
            (math.hypot(p.x - c.x, p.y - c.y), j)
            for j, p in enumerate(m.players)
            if p.side != c.side
            and actions[j]["action"] in ("tackle", "press", "intercept")
            and math.hypot(p.x - c.x, p.y - c.y) <= TACKLE_RADIUS
        ]
        if stealers:
            m.carrier = min(stealers)[1]
            nc = m.players[m.carrier]
            m.bx, m.by, m.bvx, m.bvy = nc.x, nc.y, 0.0, 0.0
        return

    # (b) loose & slow ball -> nearest player within CONTROL_RADIUS controls it.
    if math.hypot(m.bvx, m.bvy) <= CONTROL_RADIUS:
        cand = [
            (math.hypot(p.x - m.bx, p.y - m.by), j)
            for j, p in enumerate(m.players)
            if math.hypot(p.x - m.bx, p.y - m.by) <= CONTROL_RADIUS
        ]
        if cand:
            m.carrier = min(cand)[1]
            nc = m.players[m.carrier]
            m.bx, m.by, m.bvx, m.bvy = nc.x, nc.y, 0.0, 0.0


# --------------------------------------------------------------------------- #
# match runner + metrics                                                      #
# --------------------------------------------------------------------------- #
def team_spread(m: Match, side: str) -> float:
    """Mean pairwise distance among a side's 5 players. Low == collapsed onto the
    ball (swarm); high == holding shape. THE anti-swarm signal."""
    ps = m.team(side)
    pairs = [math.hypot(a.x - b.x, a.y - b.y)
             for i, a in enumerate(ps) for b in ps[i + 1:]]
    return sum(pairs) / len(pairs) if pairs else 0.0


def run_match(brain_a, brain_b, ticks: int = 300, label: str = "", kickoff_to: str = "A") -> dict:
    m = new_match()
    kickoff(m, kickoff_to)
    latency: list[float] = []
    illegal_acc: list[int] = []
    poss = {"A": 0, "B": 0, "loose": 0}
    spread = {"A": 0.0, "B": 0.0}
    fwd_x_sum = 0.0
    act_hist: dict[str, int] = {}
    illegal = 0

    for _ in range(ticks):
        m.tick += 1
        tally = step(m, brain_a, brain_b, latency, illegal_acc)
        # possession bookkeeping
        if m.carrier is None:
            poss["loose"] += 1
        else:
            poss[m.players[m.carrier].side] += 1
        spread["A"] += team_spread(m, "A")
        spread["B"] += team_spread(m, "B")
        fwd_x_sum += next(p.x for p in m.players if p.side == "A" and p.idx == 4)
        for act, n in tally["A"].items():
            act_hist[act] = act_hist.get(act, 0) + n

    illegal = sum(illegal_acc)      # raw illegal A decisions, counted pre-no-op

    n = float(ticks)
    res = {
        "label": label,
        "ticks": ticks,
        "score": (m.score_a, m.score_b),
        "possession_pct": {k: round(100 * v / n, 1) for k, v in poss.items()},
        "spread_A": round(spread["A"] / n, 3),
        "spread_B": round(spread["B"] / n, 3),
        "fwd_mean_x_A": round(fwd_x_sum / n, 3),
        "max_latency_ms": round(max(latency), 3) if latency else 0.0,
        "illegal_actions_A": illegal,
        "action_hist_A": dict(sorted(act_hist.items(), key=lambda kv: -kv[1])),
    }
    return res


def _print(res: dict) -> None:
    a, b = res["score"]
    print(f"\n=== {res['label']}  ({res['ticks']} ticks) ===")
    print(f"  SCORE  A(squad) {a} : {b} B")
    print(f"  possession%   A={res['possession_pct']['A']}  B={res['possession_pct']['B']}  "
          f"loose={res['possession_pct']['loose']}")
    print(f"  team spread   A(squad)={res['spread_A']}   B={res['spread_B']}   "
          f"(higher = holds shape, lower = ball-chasing swarm)")
    print(f"  FWD mean x A  {res['fwd_mean_x_A']}  (anchor 0.78; >0.5 = stays advanced toward opp goal)")
    print(f"  max decision  {res['max_latency_ms']} ms   (budget 500ms)")
    print(f"  illegal A     {res['illegal_actions_A']}")
    print(f"  A actions     {res['action_hist_A']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=300)
    args = ap.parse_args()

    print("Agentic Football Cup — offline match validation (deterministic squad, ZERO API)")
    print(f"Pitch normalized; A attacks x->1, B attacks x->0. {args.ticks} ticks/match.")

    r1 = run_match(squad_brain, swarm_brain, args.ticks, "squad  vs  ball-chasing SWARM")
    _print(r1)
    # Self-play is fully deterministic, so whoever kicks off carries a real
    # first-possession edge. Play it BOTH ways and aggregate: a symmetric policy
    # nets out roughly even, which isolates the policy from the kickoff handout.
    s1 = run_match(squad_brain, squad_brain, args.ticks, "self-play (A kicks off)", "A")
    s2 = run_match(squad_brain, squad_brain, args.ticks, "self-play (B kicks off)", "B")
    _print(s1)
    _print(s2)
    agg_a = s1["score"][0] + s2["score"][0]
    agg_b = s1["score"][1] + s2["score"][1]
    print(f"\n  self-play AGGREGATE (both kickoffs):  A {agg_a} : {agg_b} B  "
          f"(symmetric policy -> near-even)")

    print("\n================ VALIDATION VERDICT ================")
    a, b = r1["score"]
    spread_gap = r1["spread_A"] - r1["spread_B"]
    lat_ok = all(r["max_latency_ms"] < 500 for r in (r1, s1, s2))
    illegal_ok = all(r["illegal_actions_A"] == 0 for r in (r1, s1, s2))
    checks = [
        ("squad keeps more shape than the swarm (spread_A > spread_B)",
         r1["spread_A"] > r1["spread_B"]),
        ("squad beats the naive swarm (A > B)", a > b),
        ("squad starves the swarm of possession (A% > B%)",
         r1["possession_pct"]["A"] > r1["possession_pct"]["B"]),
        ("FWD stays advanced (mean x > 0.5)", r1["fwd_mean_x_A"] > 0.5),
        ("every decision clears the 500ms budget", lat_ok),
        ("zero illegal actions reached the runtime", illegal_ok),
        ("self-play is symmetric over both kickoffs (|aggA-aggB| <= 3)",
         abs(agg_a - agg_b) <= 3),
    ]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}]  {desc}")
    print(f"\n  spread gap (A-B) in swarm match = {round(spread_gap, 3)}  "
          f"(positive = anti-swarm thesis holds)")
    allok = all(ok for _, ok in checks)
    print(f"\n  OVERALL: {'GREEN — squad validated end-to-end' if allok else 'CHECK FAILED — see above'}")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
