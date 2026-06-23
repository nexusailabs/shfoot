"""
Agentic Football Cup — deterministic decision policy (Pillar 2).

Design goal (transferred from AWS AI League 6/23 post-mortem):
the win/lose ceiling lives in the POLICY, not in prose prompts. So the
per-tick action is decided here by pure functions that run in microseconds,
well inside the 500ms return budget, with the LLM reserved only for genuine
gray-zone ties (see squad.py).

The naive failure mode this kills: all 5 agents chasing the ball ("ball-chasing
swarm"), the football analogue of the AI League stock pathfinder marching
through spikes. Role + zone discipline beats ball-chasing.

[VERIFIED from agenticfootballcup.com/learnmore, 2026-06-18]
  * 5 AI agents per side.
  * Every 2 seconds each agent receives the FULL game state:
    ball position, all player positions, stamina, score.
  * Action space = 11 commands: pass, shoot, dribble, press, mark, intercept,
    tackle, clear, move, support, hold.
  * Each agent must return a decision in UNDER 500ms.
  * Model is free choice: Amazon Nova, Claude, or any Bedrock model.

[ASSUMPTION] Exact field NAMES / coordinate convention of the state dict are
still gated (Player Portal). On 6/24 reconcile `state_from_obs()` in squad.py
to the real keys; the decision logic and the 11-command vocabulary transfer.

Pure stdlib only (no numpy / no Strands import) so it stays unit-testable
offline and the @tool wrapper in squad.py can call it directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

# --------------------------------------------------------------------------- #
# Pitch convention                                                            #
# --------------------------------------------------------------------------- #
# Normalized pitch: x in [0, 1] left->right, y in [0, 1] bottom->top.
# OUR goal is at x = 0.0, the OPPONENT goal we attack is at x = 1.0.
PITCH_W = 1.0
PITCH_H = 1.0
OUR_GOAL = (0.0, 0.5)
OPP_GOAL = (1.0, 0.5)

# --- tunables (the "tuning round" knobs — change ONE at a time) ------------- #
SHOT_RANGE = 0.28          # within this distance of OPP_GOAL -> shoot
PASS_MIN_AHEAD = 0.06      # a teammate must be at least this much further upfield
PASS_MAX_DIST = 0.45       # don't attempt passes longer than this
OPEN_RADIUS = 0.10         # teammate is "open" if no opponent within this radius
PRESS_TRIGGER = 0.18       # engage only if I'm closest AND ball within this
TACKLE_RANGE = 0.05        # within this of the on-ball opponent -> tackle (not press)
INTERCEPT_LANE = 0.07      # how close to a moving ball's path to attempt an intercept
CLEAR_X = 0.20             # a defender carrying the ball this deep clears under pressure
GK_BOX_X = 0.18            # GK sallies out only when ball x < this (near our box)
ZONE_TOLERANCE = 0.16      # how far a role may stray from its anchor before recovering
LOW_STAMINA = 0.25         # below this, avoid sprint-y actions (press/tackle) if optional
# --------------------------------------------------------------------------- #


class Role(str, Enum):
    GK = "GK"
    DEF_L = "DEF_L"
    DEF_R = "DEF_R"
    MID = "MID"
    FWD = "FWD"


class Action(str, Enum):
    # The 11 official commands (verbatim names from the Cup spec).
    PASS = "pass"
    SHOOT = "shoot"
    DRIBBLE = "dribble"
    PRESS = "press"
    MARK = "mark"
    INTERCEPT = "intercept"
    TACKLE = "tackle"
    CLEAR = "clear"
    MOVE = "move"
    SUPPORT = "support"
    HOLD = "hold"


# Anchor (home) position per role, in our attacking frame (x toward opp goal).
ROLE_ANCHOR: dict[Role, tuple[float, float]] = {
    Role.GK: (0.05, 0.50),
    Role.DEF_L: (0.25, 0.30),
    Role.DEF_R: (0.25, 0.70),
    Role.MID: (0.50, 0.50),
    Role.FWD: (0.78, 0.50),
}


@dataclass
class Entity:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    stamina: float = 1.0     # [ASSUMPTION] presence verified; 0..1 range gated -> confirm on-site


@dataclass
class GameState:
    """One tick of perception for a single agent (the full game state)."""
    me: Entity
    ball: Entity
    teammates: list[Entity] = field(default_factory=list)
    opponents: list[Entity] = field(default_factory=list)
    has_ball: bool = False          # does MY team possess the ball
    i_have_ball: bool = False       # do *I* personally hold the ball
    my_score: int = 0
    opp_score: int = 0


@dataclass
class Decision:
    action: Action
    target: tuple[float, float] | None = None   # where to move / pass / shoot
    reason: str = ""                            # logging only, never sent to LLM
    gray_zone: bool = False                     # True -> caller MAY escalate to LLM


# --------------------------------------------------------------------------- #
# geometry helpers (pure)                                                     #
# --------------------------------------------------------------------------- #
def dist(a: tuple[float, float] | Entity, b: tuple[float, float] | Entity) -> float:
    ax, ay = (a.x, a.y) if isinstance(a, Entity) else a
    bx, by = (b.x, b.y) if isinstance(b, Entity) else b
    return math.hypot(ax - bx, ay - by)


def nearest(point: Entity, others: list[Entity]) -> Entity | None:
    if not others:
        return None
    return min(others, key=lambda o: dist(point, o))


def is_open(teammate: Entity, opponents: list[Entity], radius: float = OPEN_RADIUS) -> bool:
    """A teammate is open if no opponent sits within `radius`."""
    return all(dist(teammate, opp) > radius for opp in opponents)


def _point_to_segment(p: Entity, a: Entity, b: Entity) -> float:
    """Shortest distance from opponent point p to the pass segment a->b."""
    abx, aby = b.x - a.x, b.y - a.y
    seg2 = abx * abx + aby * aby
    if seg2 == 0.0:
        return dist(p, a)
    t = ((p.x - a.x) * abx + (p.y - a.y) * aby) / seg2
    t = max(0.0, min(1.0, t))
    return math.hypot(p.x - (a.x + t * abx), p.y - (a.y + t * aby))


def lane_clear(st: GameState, target: Entity, width: float = OPEN_RADIUS * 0.8) -> bool:
    """No opponent sits in the corridor between me and target (pass won't be cut)."""
    return all(_point_to_segment(o, st.me, target) > width for o in st.opponents)


def best_forward_pass(st: GameState) -> Entity | None:
    """Deepest-upfield teammate who is OPEN and reachable through a CLEAR lane.

    Lane-clearance (optimization): a teammate can be 'open' at their feet yet
    have an opponent astride the passing line — that pass gets intercepted.
    We require the corridor me->target to be free, falling back to merely-open
    if no clear-lane option exists (better a risky pass than a turnover-dribble
    into traffic)."""
    open_ahead = [
        t for t in st.teammates
        if t.x >= st.me.x + PASS_MIN_AHEAD
        and dist(st.me, t) <= PASS_MAX_DIST
        and is_open(t, st.opponents)
    ]
    if not open_ahead:
        return None
    clear = [t for t in open_ahead if lane_clear(st, t)]
    pool = clear or open_ahead
    return max(pool, key=lambda t: t.x)          # deepest upfield


CLOSEST_EPS = 1e-6


def i_am_closest_to_ball(st: GameState) -> bool:
    """True for exactly ONE agent, even on exact distance ties.

    Each agent sees every teammate's position (full state), so they all run the
    same check. On a strict tie we break it deterministically by lexicographic
    (x, y) — the agent with the smallest (x, y) wins — so two equidistant agents
    can never both decide to engage (Codex blocker: the old `<=` let both press).
    """
    my_d = dist(st.me, st.ball)
    for t in st.teammates:
        td = dist(t, st.ball)
        if td < my_d - CLOSEST_EPS:
            return False                       # someone strictly closer
        if abs(td - my_d) <= CLOSEST_EPS and (t.x, t.y) < (st.me.x, st.me.y):
            return False                       # exact tie, teammate wins tiebreak
    return True


def in_my_zone(role: Role, point: Entity, tol: float = ZONE_TOLERANCE) -> bool:
    return dist(ROLE_ANCHOR[role], point) <= tol


def ball_is_moving(st: GameState, eps: float = 1e-3) -> bool:
    return math.hypot(st.ball.vx, st.ball.vy) > eps


def near_ball_path(st: GameState, lane: float = INTERCEPT_LANE) -> bool:
    """Rough: am I within `lane` of the ball's short-horizon travel point?"""
    if not ball_is_moving(st):
        return False
    future = (st.ball.x + st.ball.vx * 0.5, st.ball.y + st.ball.vy * 0.5)
    return dist(st.me, future) <= lane


def on_ball_opponent(st: GameState, radius: float = OPEN_RADIUS) -> Entity | None:
    """The opponent currently controlling the ball, if one is right on it."""
    opp = nearest(st.ball, st.opponents)
    if opp and dist(opp, st.ball) <= radius:
        return opp
    return None


# --------------------------------------------------------------------------- #
# the decision function — Pillar 2 core                                       #
# --------------------------------------------------------------------------- #
def decide_action(role: Role, st: GameState) -> Decision:
    """Deterministic per-tick policy. Never returns None (fallback = MOVE/HOLD)."""

    tired = st.me.stamina < LOW_STAMINA

    # ---- GK: special-cased, never leaves the box except on real threat ----- #
    if role == Role.GK:
        if st.i_have_ball:
            tm = best_forward_pass(st)
            if tm:
                return Decision(Action.PASS, (tm.x, tm.y), "GK distribute")
            return Decision(Action.CLEAR, (CLEAR_X + 0.3, st.me.y), "GK clear long")
        if (st.ball.x < GK_BOX_X
                and i_am_closest_to_ball(st)
                and dist(st.me, st.ball) <= PRESS_TRIGGER * 1.5):
            return Decision(Action.PRESS, (st.ball.x, st.ball.y), "GK smother in box")
        return Decision(Action.MOVE, OUR_GOAL, "GK hold line")

    # ---- ON THE BALL (I personally hold it) -------------------------------- #
    if st.i_have_ball:
        goal_d = dist(st.me, OPP_GOAL)
        if goal_d <= SHOT_RANGE:
            # near the shot-range boundary, shoot-vs-pass is a genuine tie ->
            # flag gray_zone so squad.py MAY consult the LLM (Pillar 2 escalation).
            gray = goal_d >= SHOT_RANGE * 0.8 and best_forward_pass(st) is not None
            return Decision(Action.SHOOT, OPP_GOAL, "in shot range", gray_zone=gray)
        # defender deep in our half under pressure -> clear, don't risk a turnover
        if role in (Role.DEF_L, Role.DEF_R) and st.me.x < CLEAR_X:
            opp = nearest(st.me, st.opponents)
            if opp and dist(st.me, opp) < PRESS_TRIGGER:
                return Decision(Action.CLEAR, (CLEAR_X + 0.4, st.me.y), "clear under pressure")
        tm = best_forward_pass(st)
        if tm is not None:
            return Decision(Action.PASS, (tm.x, tm.y), "forward pass to open man")
        return Decision(Action.DRIBBLE, OPP_GOAL, "carry toward goal")

    # ---- OFF THE BALL ------------------------------------------------------ #
    # Intercept a loose/moving ball coming through my lane — but ONLY if the
    # ball's projected point is in my zone OR I'm the closest. Without this gate
    # a far defender would chase a moving ball across the pitch (Codex blocker).
    if ball_is_moving(st) and near_ball_path(st) and not tired:
        future = (st.ball.x + st.ball.vx * 0.5, st.ball.y + st.ball.vy * 0.5)
        if in_my_zone(role, future, ZONE_TOLERANCE * 1.8) or i_am_closest_to_ball(st):
            return Decision(Action.INTERCEPT, (st.ball.x, st.ball.y), "cut the lane")

    ball_near_me = dist(st.me, st.ball) <= PRESS_TRIGGER
    closest_in_zone = (
        i_am_closest_to_ball(st)
        and ball_near_me
        and in_my_zone(role, st.ball, ZONE_TOLERANCE * 1.6)
    )
    if closest_in_zone:
        opp = on_ball_opponent(st)
        # very tight to the on-ball opponent -> tackle; otherwise press
        if opp and dist(st.me, opp) <= TACKLE_RANGE and not tired:
            return Decision(Action.TACKLE, (opp.x, opp.y), "tackle on-ball opp")
        if not tired:
            return Decision(Action.PRESS, (st.ball.x, st.ball.y), "closest + ball in zone")

    # Defenders mark the nearest opponent intruding into their zone.
    if role in (Role.DEF_L, Role.DEF_R):
        intruder = nearest(Entity(*ROLE_ANCHOR[role]), st.opponents)
        if intruder and dist(ROLE_ANCHOR[role], intruder) <= ZONE_TOLERANCE * 1.8:
            return Decision(Action.MARK, (intruder.x, intruder.y), "mark zone intruder")

    # Hold shape: move back to anchor (this is what kills ball-chasing).
    if not in_my_zone(role, st.me):
        return Decision(Action.MOVE, ROLE_ANCHOR[role], "return to zone")

    # In position & off ball: if WE have the ball, offer a passing outlet upfield.
    if st.has_ball:
        ax, ay = ROLE_ANCHOR[role]
        return Decision(Action.SUPPORT, (min(ax + 0.08, 0.95), ay), "offer outlet")

    return Decision(Action.HOLD, None, "hold shape")


# --------------------------------------------------------------------------- #
# tiny self-check when run directly                                           #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    s = GameState(me=Entity(0.85, 0.5), ball=Entity(0.85, 0.5), i_have_ball=True, has_ball=True)
    print("FWD on ball near goal:", decide_action(Role.FWD, s).action)
