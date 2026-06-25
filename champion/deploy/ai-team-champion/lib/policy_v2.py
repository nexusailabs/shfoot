"""
Agentic Football Cup — CHAMPIONSHIP deterministic policy (real AWS contract).

This is the rewrite mandated by the 6/24 treasure hunt + live-config post-mortem:

  * The win/lose ceiling lives in CODE, not prompts. Every tick is decided here
    by pure functions in microseconds — far inside the contest's <500ms budget —
    so we never pay the LLM-per-tick latency tax that stalled the deployed team.
  * The deployed sample was LLM-primary with NO Gateway tools (list-gateways
    returned []), so pass-probability / shot-evaluation never touched the pitch.
    We INLINE that exact math here (evaluate_shot / calculate_pass_options) and
    decide on it directly.
  * Live contract (verified from on-agent logging, 2026-06-25):
      - Field plane is player(x, y) == ball(x, z). ball.position.y is height.
      - Small Unity scale, roughly single-digit field coordinates.
      - Roster of 5: id0=GK, id1=DEF, id2=MID, id3=FWD1, id4=FWD2  (a 1-1-2).
      - team_id 0 = HOME (my goal negative x, attack +x); 1 = AWAY (mirror).
      - obs: game_state{ball{position{x,y=height,z}, possessionAgentId|possessionPlayerId},
        score{home,away}, gameTime, players[{agentId|playerId, teamCode|teamId,
        position{x,y}, stamina(0..100)}]}.
      - Output command: {commandType, playerId, teamId, parameters, duration}.
      - Commands: MOVE_TO{target_x,target_y,sprint} PASS{target_player_id,type}
        SHOOT{aim_location,power} PRESS_BALL{intensity} MARK{target_player_id,
        tightness} INTERCEPT{aggressive} SLIDE_TACKLE{target_player_id}
        GK_DISTRIBUTE{target_player_id,method} SET_STANCE{stance}.

Pure stdlib. Importable with no AWS / no Strands so the offline sim and unit
tests exercise the exact bytes that deploy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

# Live pitch geometry. FCPOS_REPLACE values once the full-match bounds arrive:
#   FIELD_X: max(abs(player.x), abs(ball.x), abs(goal_x))
#   FIELD_Z: max(abs(player.y), abs(ball.z))
#   GOAL_HOME_X / GOAL_AWAY_X: goal-line crossing x positions
#   GOAL_HALF_WIDTH: half mouth width on the field-depth axis
# Measured from a full 400-tick FCPOS capture (2026-06-25):
#   player x in [-6.4, 6.4], player depth(y) in [-3.5, 3.6]
#   ball x in [-6.61, 6.86] (crosses the goal line into the net), depth(z) in [-3.64, 3.28]
FIELD_X = 6.4          # player half-length; goal line at |x| ~= 6.4
FIELD_Z = 3.5          # half-width on the field-depth axis
GOAL_HOME_X = -6.4
GOAL_AWAY_X = 6.4
GOAL_CENTER_Y = 0.0
GOAL_HALF_WIDTH = 1.0  # goal-mouth half-width on the depth axis (estimate; refine from goal-event ball-z)


def _sx(frac: float) -> float:
    """Scale a tactical fraction to live field units on the x-length scale."""
    return FIELD_X * frac


def _sz(frac: float) -> float:
    """Scale a tactical fraction to live field units on the depth scale."""
    return FIELD_Z * frac


def _zone_tol(cfg: "RoleConfig") -> float:
    return _sx(cfg.zone_tol)


def _press_dist(cfg: "RoleConfig") -> float:
    return _sx(cfg.press_trigger)


def _shoot_dist(cfg: "RoleConfig") -> float:
    return _sx(cfg.shoot_range)

# Roster: fixed player ids -> role.
GK, DEF, MID, FWD1, FWD2 = 0, 1, 2, 3, 4
DEF2, MID2 = 5, 6              # extra tactical slots used by non-1-1-2 formations
ROLE_NAME = {GK: "GK", DEF: "DEF", MID: "MID", FWD1: "FWD1", FWD2: "FWD2", DEF2: "DEF2", MID2: "MID2"}

# Role GROUPS — branch on the tactical group, never on a raw player id, so the
# same policy works under any formation->slot mapping (1-1-2 keeps identity).
DEFENDERS = (DEF, DEF2)
MIDS = (MID, MID2)
FORWARDS = (FWD1, FWD2)


def _is_def(slot: int) -> bool:
    return slot in DEFENDERS


def _is_mid(slot: int) -> bool:
    return slot in MIDS


def _is_fwd(slot: int) -> bool:
    return slot in FORWARDS


def _is_attacker(slot: int) -> bool:
    return slot in (MID, MID2, FWD1, FWD2)


# --------------------------------------------------------------------------- #
# Per-position config — the championship "settings per player" (1-1-2).        #
# Anchors are in ATTACKING-FRAME fractions: ax in [-1,1] where +1 = opp goal,  #
# ay in [-1,1] where +1 = +y touchline. Converted to world coords per team.   #
# --------------------------------------------------------------------------- #
@dataclass
class RoleConfig:
    anchor_ax: float                 # home x, attacking-frame fraction of FIELD_X
    anchor_ay: float                 # home field-depth fraction of FIELD_Z
    zone_tol: float                  # fraction of FIELD_X before recovering shape
    press_trigger: float             # fraction of FIELD_X for on-ball duels
    shoot_range: float               # fraction of FIELD_X to consider shooting
    push_when_attacking: float       # extra forward push (ax units) when we possess
    risk: float = 0.0                # 0 conservative .. 1 aggressive (long shots, slide tackles)
    model_id: str = "amazon.nova-lite-v1:0"   # only used on the optional gray-zone LLM path


# Defaults tuned from the baseline post-mortem: baseline swarms (everyone within
# 20u presses) and over-commits forwards. We hold a compact 1-1-2 with strict
# single-presser discipline and two staggered strikers for the long-shot meta.
# Tuned from LIVE match #1 vs Benchmark (lost 1-4): we over-pressed (188 PRESS,
# 0 MARK -> exposed backline) and spammed shots (53 SHOOT -> 1 on target). The
# winner played POSITIONING + efficient passing. So: tighter press triggers,
# shorter shoot ranges, lower risk -> hold shape, mark, and shoot only high-prob.
# ATTACKING REBUILD (match #5: 48% poss, 16 SHOOT -> 0 on target, lost 0-1). The old
# config was tuned for a 16-0 clean sheet (defensive: deep anchors, low risk, shoot only
# >=0.40 prob). The operator's goal is now OFFENSE — beat Benchmark by many goals. So:
# push the two strikers HIGH and into the box, push MID into the final third, keep GK+DEF
# disciplined so we don't get countered. Finishing is fixed in the on-ball block (carry to
# a central high-prob spot before shooting) — positioning, not just a lower threshold.
# BALANCED-ATTACK (match clean-1-1-2 lost 1-3: 203 PRESS = swarm -> countered 3x). Revert
# the over-aggression: DEF deep & home, press zones tightened, FWDs high but not reckless.
# Keep the finishing fix (carry-to-shoot) — that part works (2/3 on target in the 2-1 win).
ROLE_CONFIG: dict[int, RoleConfig] = {
    GK:   RoleConfig(anchor_ax=-0.92, anchor_ay=0.00, zone_tol=0.25, press_trigger=0.13, shoot_range=0.00, push_when_attacking=0.03, risk=0.0),
    DEF:  RoleConfig(anchor_ax=-0.46, anchor_ay=0.00, zone_tol=0.36, press_trigger=0.16, shoot_range=0.00, push_when_attacking=0.10, risk=0.05),
    MID:  RoleConfig(anchor_ax=0.02,  anchor_ay=0.00, zone_tol=0.44, press_trigger=0.20, shoot_range=0.44, push_when_attacking=0.34, risk=0.38),
    FWD1: RoleConfig(anchor_ax=0.58,  anchor_ay=-0.22, zone_tol=0.47, press_trigger=0.18, shoot_range=0.55, push_when_attacking=0.30, risk=0.55),
    FWD2: RoleConfig(anchor_ax=0.58,  anchor_ay=0.22,  zone_tol=0.47, press_trigger=0.18, shoot_range=0.55, push_when_attacking=0.30, risk=0.55),
    # Extra slots for non-1-1-2 formations (unused while ACTIVE_FORMATION=="1-1-2").
    # DEF2: second centre-back, splits to one side of DEF in a 2-1-1 back line.
    DEF2: RoleConfig(anchor_ax=-0.46, anchor_ay=0.26, zone_tol=0.36, press_trigger=0.16, shoot_range=0.00, push_when_attacking=0.10, risk=0.05),
    # MID2: second midfielder, splits from MID in a 1-2-1 to control the centre.
    MID2: RoleConfig(anchor_ax=0.02,  anchor_ay=0.26, zone_tol=0.44, press_trigger=0.20, shoot_range=0.44, push_when_attacking=0.34, risk=0.38),
}

# Formation -> {player_id: tactical_slot}. player_id 0 is ALWAYS the GK (engine
# roster). 1-1-2 is identity (the validated default; must stay byte-identical).
FORMATIONS: dict[str, dict[int, int]] = {
    "1-1-2": {0: GK, 1: DEF, 2: MID, 3: FWD1, 4: FWD2},
    "2-1-1": {0: GK, 1: DEF, 2: DEF2, 3: MID, 4: FWD1},
    "1-2-1": {0: GK, 1: DEF, 2: MID, 3: MID2, 4: FWD1},
}
ACTIVE_FORMATION = "1-1-2"   # default; live A/B tunes this per opponent archetype
DROP_MARK_ENABLED = True     # A/B (2026-06-25): drop-mark EXONERATED — OFF made aggressive WORSE
                             # (0-3,1-5 vs 2-3,3-4; opp shots 10/8 vs 7/7). Keep ON; it helps defence.


def role_for_player(my_id: int, formation: str | None = None) -> int:
    """Map a fixed engine player id to its tactical slot under the formation."""
    fmap = FORMATIONS.get(formation or ACTIVE_FORMATION, FORMATIONS["1-1-2"])
    return fmap.get(my_id, MID)

LOW_STAMINA = 18.0               # lowered: attacking play needs sprints; only freeze when truly gassed
SHOOT_MIN_PROB = 0.42           # only shoot if the shot model and geometry agree it is real
SHOOT_NOW_PROB = 0.62           # high-confidence: shoot immediately, never pass it off
CARRY_TO_SHOOT_DIST = 0.62      # fraction of FIELD_X; near goal but low prob -> carry to a better angle
SHOT_REAL_CHANCE_DIST = 0.43    # fraction of FIELD_X; filters long/non-registering SHOOT commands
SHOT_CENTER_BAND = 1.15         # multiple of GOAL_HALF_WIDTH for normal on-frame shots
SHOT_CLOSE_WIDE_BAND = 1.65     # allow tight-angle shots only when very close to goal
SUPPORT_MIN_MOVE = 0.07         # fraction of FIELD_X before re-issuing support MOVE_TO
PRESS_NEAR_DIST = 0.22          # real-scale nearest-presser distance to the carrier
PRESS_TIGHT_DIST = 0.12         # tight enough that the carrier must release now
PRESS_RELEASE_MIN_SUCCESS = 0.44


_STATE = {
    "press": {},                 # team_id -> {"t": gameTime, "ema": high-press score}
}

NEUTRAL_TACTICS = {"attack_zone": None, "push": 0.0, "exploit_opp_id": None, "tempo": "direct", "notes": ""}


def _current_tactics_safe() -> dict:
    try:
        import hybrid
        return hybrid.current_tactics()
    except Exception:
        return dict(NEUTRAL_TACTICS)


def _tactic_push_ax(t: dict) -> float:
    try:
        push = float((t or {}).get("push", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(push):
        return 0.0
    return 0.15 * max(0.0, min(1.0, push))


def _tactic_tempo(t: dict) -> str:
    return "patient" if (t or {}).get("tempo") == "patient" else "direct"


def _tactic_zone_target_y(t: dict):
    zone = (t or {}).get("attack_zone")
    if zone == "L":
        return -_sz(0.30)
    if zone == "C":
        return 0.0
    if zone == "R":
        return _sz(0.30)
    return None


def _nudge_y_toward(ty: float, target_y, max_delta: float) -> float:
    if target_y is None:
        return ty
    delta = max(-max_delta, min(max_delta, target_y - ty))
    return ty + delta


def _tactic_exploit_pid(t: dict):
    pid = (t or {}).get("exploit_opp_id")
    return pid if isinstance(pid, int) and 0 <= pid <= 4 else None


def _apply_attack_tactics(v: "View", tx: float, ty: float, t: dict,
                          use_exploit: bool = True) -> tuple[float, float]:
    """Apply attack-only nudges to a move target.

    Lateral zone bias is bounded to 0.30 field-depth units. exploit_opp_id can
    only move the target farther upfield or sideways toward space behind that
    opponent; it never lowers the target's attacking-frame x.
    """
    ty = _nudge_y_toward(ty, _tactic_zone_target_y(t), _sz(0.30))
    if not use_exploit:
        return tx, ty

    exploit_pid = _tactic_exploit_pid(t)
    if exploit_pid is None:
        return tx, ty
    opp = next((o for o in v.opponents if _pid(o) == exploit_pid), None)
    if opp is None:
        return tx, ty

    ox, oy = _field_xy(opp)
    behind_x = ox + v.dir * _sx(0.18)
    # Only accept the exploit x target if it is no deeper than the baseline.
    if _upfield(v, behind_x) > _upfield(v, tx):
        forward_delta = min(_sx(0.18), (behind_x - tx) * v.dir)
        tx += v.dir * max(0.0, forward_delta)
    ty = _nudge_y_toward(ty, oy, _sz(0.25))
    return tx, ty


# --------------------------------------------------------------------------- #
# obs adapters — tolerate both new (agentId/teamCode) and old (playerId/teamId) #
# --------------------------------------------------------------------------- #
def _pid(p: dict) -> int:
    if "agentId" in p:
        try:
            return int(str(p["agentId"]).rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            return 0
    return p.get("playerId", 0)


def _is_mine(p: dict, team_id: int) -> bool:
    if "teamCode" in p:
        return p["teamCode"] == ("home" if team_id == 0 else "away")
    return p.get("teamId") == team_id


def _aid(p: dict) -> str:
    """Globally-unique player identity. Prefer the full agentId string; fall
    back to teamCode/teamId + index so two teams never collide on a bare 0-4."""
    if p.get("agentId") is not None:
        return str(p["agentId"])
    team = p.get("teamCode", p.get("teamId", "?"))
    return f"{team}_{p.get('playerId', '?')}"


def _possession(ball: dict):
    """Legacy: trailing-int possession index (0-4). Ambiguous across teams —
    use possession_holder() for team-correct resolution."""
    aid = ball.get("possessionAgentId")
    if aid is not None:
        try:
            return int(str(aid).rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            return None
    return ball.get("possessionPlayerId")


def possession_holder(game_state: dict):
    """The player dict holding the ball, or None.

    ROBUST to the sample/live format where BOTH teams use a duplicate agentId
    like 'agentId_3' and possessionAgentId='agentId_3' (Codex live-#1 bug: exact
    match grabbed the first/home player -> false possession -> ghost shots). So:
    collect all id-matches, then disambiguate by possessionTeam if given, else by
    'the holder is physically on the ball' (nearest match to the ball)."""
    ball = game_state.get("ball", {})
    players = game_state.get("players", [])
    ball_xy = _field_xy(ball)
    pteam = ball.get("possessionTeam")
    aid = ball.get("possessionAgentId")
    cands = [p for p in players if _aid(p) == str(aid)] if aid is not None else []
    if not cands:
        ppid = ball.get("possessionPlayerId")
        if ppid is not None:
            cands = [p for p in players if _pid(p) == ppid]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    if pteam is not None:
        want = "home" if pteam in (0, "0", "home") else "away"
        tm = [p for p in cands if str(p.get("teamCode")) == want]
        if tm:
            cands = tm
            if len(cands) == 1:
                return cands[0]
    return min(cands, key=lambda p: _hypot(*_field_xy(p), *ball_xy))


def goal_x(team_id: int) -> tuple[float, float]:
    """(my_goal_x, opp_goal_x)."""
    return (GOAL_HOME_X, GOAL_AWAY_X) if team_id == 0 else (GOAL_AWAY_X, GOAL_HOME_X)


def _field_xy(entity: dict) -> tuple[float, float]:
    """Canonical field-plane accessor.

    Players are 2D: position{x, y} where y is field depth. The live ball is 3D:
    position{x, y=height, z}; use z for field depth. Legacy 2D ball fixtures still
    work by falling back to y when z is absent.
    """
    pos = entity.get("position", entity)
    depth_key = "z" if "z" in pos else "y"
    return float(pos.get("x", 0.0)), float(pos.get(depth_key, 0.0))


def _ball_height(ball: dict) -> float:
    pos = ball.get("position", ball)
    return float(pos.get("y", 0.0)) if "z" in pos else 0.0


def _xy(entity: dict) -> tuple[float, float]:
    """Backward-compatible alias for sim2/tests; internal code uses _field_xy."""
    return _field_xy(entity)


def _hypot(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)


# --------------------------------------------------------------------------- #
# Inlined Gateway math (the real contest tactical tools, decided in code).     #
# --------------------------------------------------------------------------- #
def evaluate_shot(sx, sy, gk_xy, opp_goal_x, blockers) -> dict:
    """Port of gateway_tools/evaluate_shot.py. Returns probability + aim + power."""
    gx, gy = opp_goal_x, GOAL_CENTER_Y
    dist_goal = _hypot(sx, sy, gx, gy)
    angle = math.atan2(GOAL_HALF_WIDTH, max(dist_goal, 1e-6))
    angle_factor = min(1.0, angle / 0.15)
    distance_factor = max(0.0, 1.0 - dist_goal / FIELD_X)
    gk_off = abs(gk_xy[1]) if gk_xy else 0.0
    gk_factor = min(1.0, gk_off / _sx(0.15)) * 0.3
    gk_dist = _hypot(gk_xy[0], gk_xy[1], gx, gy) if gk_xy else 0.0
    gk_dist_factor = min(1.0, gk_dist / _sx(0.27)) * 0.2
    pen = 0.0
    for bx, by in blockers:
        bd = _hypot(sx, sy, bx, by)
        block_radius = _sx(0.18)
        if bd < block_radius:
            pen += (block_radius - bd) / block_radius * 0.15
    pen = min(pen, 0.4)
    prob = round(max(0.02, min(0.95, distance_factor * 0.45 + angle_factor * 0.25 + gk_factor + gk_dist_factor - pen)), 2)
    # aim away from the GK
    if gk_xy and gk_xy[1] > 1:
        aim = "BL" if sy > 0 else "BR"
    elif gk_xy and gk_xy[1] < -1:
        aim = "TL" if sy > 0 else "TR"
    else:
        aim = "TR" if sy <= 0 else "TL"
    power = round(min(1.0, 0.6 + dist_goal / _sx(1.45)), 2)
    # should_shoot computed on the ROUNDED probability, matching the Lambda.
    return {"prob": prob, "aim": aim, "power": power, "should_shoot": prob > 0.25, "dist": dist_goal}


def calculate_pass_options(me_xy, teammates, opponents) -> list[dict]:
    """Port of gateway_tools/calculate_pass_options.py. Ranked pass options."""
    px, py = me_xy
    opp_xy = [_field_xy(o) for o in opponents]
    out = []
    for tm in teammates:
        tx, ty = _field_xy(tm)
        d = _hypot(px, py, tx, ty)
        risk = round(_intercept_risk(px, py, tx, ty, opp_xy), 2)
        success = round(max(0.05, 1.0 - risk - d / _sx(2.18)), 2)
        out.append({
            "pid": _pid(tm), "x": tx, "y": ty, "dist": round(d, 1),
            "risk": risk, "success": success,
            "type": "GROUND" if d < _sx(0.36) else ("THROUGH" if success > 0.5 else "AERIAL"),
        })
    out.sort(key=lambda o: o["success"], reverse=True)
    return out


def _intercept_risk(px, py, rx, ry, opp_xy) -> float:
    pd = _hypot(px, py, rx, ry)
    if pd < 1:
        return 0.0
    dx, dy = rx - px, ry - py
    risk = 0.0
    for ox, oy in opp_xy:
        t = max(0.0, min(1.0, ((ox - px) * dx + (oy - py) * dy) / (pd * pd)))
        cx, cy = px + t * dx, py + t * dy
        lane = _hypot(ox, oy, cx, cy)
        lane_radius = _sx(0.15)
        if lane < lane_radius:
            risk = max(risk, 1.0 - lane / lane_radius)
    return min(risk, 0.95)


# --------------------------------------------------------------------------- #
# Decision result                                                             #
# --------------------------------------------------------------------------- #
@dataclass
class Cmd:
    commandType: str
    parameters: dict
    duration: int = 0
    reason: str = ""
    gray_zone: bool = False


def _move(tx, ty, sprint=False, reason="", gray=False) -> Cmd:
    tx = max(-FIELD_X, min(FIELD_X, tx))
    ty = max(-FIELD_Z, min(FIELD_Z, ty))
    return Cmd("MOVE_TO", {"target_x": round(tx, 1), "target_y": round(ty, 1), "sprint": sprint}, 0, reason, gray)


# --------------------------------------------------------------------------- #
# Parsed view of the tick from one player's perspective                       #
# --------------------------------------------------------------------------- #
@dataclass
class View:
    me: dict
    me_xy: tuple[float, float]
    ball_xy: tuple[float, float]
    teammates: list          # excludes me
    opponents: list
    poss: object             # possession player id (mine numbering) or None
    i_have_ball: bool
    we_have_ball: bool
    team_id: int
    my_goal_x: float
    opp_goal_x: float
    dir: int                 # +1 if attacking +x, else -1
    stamina: float
    gt: float = 0.0          # gameTime seconds (for game-management + mixing seeds)
    goal_diff: int = 0       # our score - their score


def _parse(game_state: dict, team_id: int, my_id: int) -> View | None:
    players = game_state.get("players", [])
    ball = game_state.get("ball", {})
    ball_xy = _field_xy(ball)
    me = next((p for p in players if _pid(p) == my_id and _is_mine(p, team_id)), None)
    if me is None:
        return None
    mine = [p for p in players if _is_mine(p, team_id) and _pid(p) != my_id]
    opp = [p for p in players if not _is_mine(p, team_id)]
    my_goal_x, opp_goal_x = goal_x(team_id)
    holder = possession_holder(game_state)              # team-correct (disambiguated)
    we_have = bool(holder is not None and _is_mine(holder, team_id))
    # i_have_ball by OBJECT IDENTITY (holder and me are from the same players list).
    # _aid() equality is wrong under duplicate agentId_N (opp's same-numbered player
    # would also match -> ghost on-ball commands). Codex gate #3 blocker.
    i_have = (holder is me)
    sc = game_state.get("score") or {}
    home_s = sc.get("home", 0) or 0
    away_s = sc.get("away", 0) or 0
    our_s, their_s = (home_s, away_s) if team_id == 0 else (away_s, home_s)
    try:
        gt = float(game_state.get("gameTime") or 0.0)
    except (TypeError, ValueError):
        gt = 0.0
    return View(
        me=me, me_xy=_field_xy(me), ball_xy=ball_xy, teammates=mine, opponents=opp,
        poss=(_pid(holder) if holder is not None else None),
        i_have_ball=i_have, we_have_ball=we_have,
        team_id=team_id, my_goal_x=my_goal_x, opp_goal_x=opp_goal_x,
        dir=(1 if team_id == 0 else -1), stamina=_norm_stamina(me.get("stamina", 100)),
        gt=gt, goal_diff=int(our_s) - int(their_s),
    )


def _norm_stamina(raw) -> float:
    """Normalize stamina to 0..100. Live/sample state may send a 0..1 fraction
    (e.g. 0.95) OR a 0..100 value; on the 0..1 scale every player would read as
    'tired' against LOW_STAMINA and freeze the policy (Codex live-#1 bug)."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 100.0
    return v * 100.0 if v <= 1.0 else v


def anchor_world(slot: int, team_id: int, push: float = 0.0) -> tuple[float, float]:
    cfg = ROLE_CONFIG[slot]
    d = 1 if team_id == 0 else -1
    ax = max(-0.98, min(0.98, cfg.anchor_ax + push))
    # Only x is direction-flipped per team (goals are on the x axis). y is NOT
    # flipped — the pitch is y-symmetric and the sample contract uses absolute y
    # (lib/fallback.py), so flipping it would diverge from the engine's frame.
    return ax * FIELD_X * d, cfg.anchor_ay * FIELD_Z


def _forwardness(v: View, x: float) -> float:
    """How far upfield x is, in the attacking direction (+ = toward opp goal)."""
    return (x - v.me_xy[0]) * v.dir


def _upfield(v: View, x: float) -> float:
    """Absolute attacking-frame x (+ = closer to opponent goal)."""
    return x * v.dir


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _shot_is_real_chance(v: View, x: float, y: float, shot: dict) -> bool:
    """Geometry gate for SHOOT. The probability model is optimistic on the small
    field because the angle term saturates early; require an actually on-frame
    position before emitting a SHOOT command."""
    toward_goal = (v.opp_goal_x - x) * v.dir
    if toward_goal <= 0:
        return False
    goal_dx = abs(v.opp_goal_x - x)
    central = abs(y) <= GOAL_HALF_WIDTH * SHOT_CENTER_BAND
    close_wide = goal_dx <= _sx(0.20) and abs(y) <= GOAL_HALF_WIDTH * SHOT_CLOSE_WIDE_BAND
    return shot["dist"] <= _sx(SHOT_REAL_CHANCE_DIST) and (central or close_wide)


def _ball_rank(v: View) -> int:
    """0-based rank of me by distance to the ball among my OUTFIELD team (GK
    excluded). Deterministic (x,y) tiebreak so every agent computes the same
    ordering from the shared full state -> exactly N pressers, never a swarm."""
    mx, my = v.me_xy
    my_d = _hypot(mx, my, *v.ball_xy)
    rank = 0
    for t in v.teammates:
        if _pid(t) == GK:
            continue
        tx, ty = _field_xy(t)
        td = _hypot(tx, ty, *v.ball_xy)
        if td < my_d - 1e-9 or (abs(td - my_d) <= 1e-9 and (tx, ty) < (mx, my)):
            rank += 1
    return rank


def _closest_teammate_to_ball_is_me(v: View) -> bool:
    """True for exactly one outfield agent (rank 0)."""
    return _ball_rank(v) == 0


def _press_profile(game_state: dict, v: View) -> dict:
    """Shared deterministic estimate of opponent high press from the full obs."""
    holder = possession_holder(game_state)
    if holder is None or not _is_mine(holder, v.team_id):
        return {"score": 0.0, "direct": 0.0, "nearest": 999.0, "high": False, "holder": holder}

    hx, hy = _field_xy(holder)
    nearest = min((_hypot(hx, hy, *_field_xy(o)) for o in v.opponents), default=999.0)
    our_half = sum(1 for o in v.opponents if _upfield(v, _field_xy(o)[0]) < _sx(0.08))
    near_ball = sum(1 for o in v.opponents if _hypot(hx, hy, *_field_xy(o)) <= _sx(0.42))
    close_score = _clamp01((_sx(PRESS_NEAR_DIST) - nearest) / max(_sx(PRESS_NEAR_DIST - PRESS_TIGHT_DIST), 1e-6))
    half_score = _clamp01(our_half / 3.0)
    crowd_score = _clamp01(near_ball / 3.0)
    snapshot = 0.50 * close_score + 0.30 * half_score + 0.20 * crowd_score

    gt = game_state.get("gameTime")
    try:
        tick = round(float(gt), 2)
    except (TypeError, ValueError):
        tick = None
    if tick is None:
        return {"score": snapshot, "direct": _clamp01(snapshot), "nearest": nearest, "high": snapshot >= 0.48, "holder": holder}
    team_state = _STATE["press"].setdefault(v.team_id, {"t": None, "ema": snapshot})
    if team_state["t"] != tick:
        team_state["ema"] = snapshot if team_state["t"] is None else 0.65 * team_state["ema"] + 0.35 * snapshot
        team_state["t"] = tick
    score = max(snapshot, team_state["ema"])
    return {"score": score, "direct": _clamp01(score), "nearest": nearest, "high": score >= 0.48, "holder": holder}


def _carrier_under_pressure(v: View, press: dict) -> bool:
    nearest = press.get("nearest", 999.0)
    return nearest <= _sx(PRESS_TIGHT_DIST) or (press.get("high") and nearest <= _sx(PRESS_NEAR_DIST))


def _pressure_release_option(v: View, scored_opts: list[tuple[dict, dict]], directness: float,
                             formation: str | None = None):
    """Pick the fastest vertical escape pass when the carrier is being closed."""
    candidates = []
    for o, shot in scored_opts:
        if o["pid"] == GK:
            continue
        recv_slot = role_for_player(o["pid"], formation)   # formation-aware role, not raw pid
        gain = _forwardness(v, o["x"])
        upfield = _upfield(v, o["x"])
        lane_ok = o["success"] >= PRESS_RELEASE_MIN_SUCCESS and o["risk"] <= 0.66
        if lane_ok and gain > _sx(0.03):
            role_bonus = 0.18 if _is_fwd(recv_slot) else (0.08 if _is_mid(recv_slot) else -0.25)
            shot_bonus = shot["prob"] if _shot_is_real_chance(v, o["x"], o["y"], shot) else 0.0
            score = (
                1.35 * gain / FIELD_X
                + 0.55 * upfield / FIELD_X
                + 0.75 * o["success"]
                + 0.45 * shot_bonus
                + 0.25 * directness
                + role_bonus
                - 0.25 * o["risk"]
            )
            candidates.append((score, o))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]

    layoffs = [
        o for o, _ in scored_opts
        if o["pid"] != GK and o["success"] >= 0.60 and o["dist"] <= round(_sx(0.55), 1)
        and _forwardness(v, o["x"]) >= -_sx(0.07)
    ]
    if layoffs:
        return max(layoffs, key=lambda o: (o["success"], _forwardness(v, o["x"])))
    return None


def _support_run(v: View, slot: int, my_id: int, holder: dict | None,
                 carrier_slot: int, directness: float = 0.0):
    """Possession support shape: MID offers the recycle/cutback; the spare FWD
    attacks the box. GK+DEF are intentionally excluded so counter cover stays.
    Branches on tactical GROUP (slot), not raw id, so it works under any
    formation; the carrier is identified by MY player id, not slot."""
    if holder is None or _pid(holder) == my_id or _is_def(slot) or slot == GK:
        return None
    hx, hy = _field_xy(holder)
    final_third = (v.opp_goal_x - hx) * v.dir <= _sx(0.42)
    high_press = directness >= 0.48
    carrier_is_fwd = carrier_slot in FORWARDS

    if _is_mid(slot):
        # MID2 mirrors MID laterally so two midfielders don't stack (1-2-1).
        m = -1.0 if slot == MID2 else 1.0
        if high_press:
            if carrier_is_fwd:
                return hx - v.dir * _sx(0.16), hy * 0.25 * m, True, "press layoff outlet"
            return hx + v.dir * _sx(0.16), hy * 0.20 * m, True, "press central outlet"
        if carrier_is_fwd and final_third:
            return hx - v.dir * _sx(0.20), -hy * 0.45 * m, False, "offer cutback outlet"
        return hx + v.dir * _sx(0.18), hy * 0.35 * m, True, "show central outlet"

    if _is_fwd(slot):
        side = -1 if slot == FWD1 else 1
        if high_press and not final_third:
            return hx + v.dir * _sx(0.38), side * _sz(0.30), True, "press in-behind outlet"
        if final_third:
            far_side = (-1 if hy > 0 else 1) if carrier_is_fwd else side
            return v.opp_goal_x - v.dir * _sx(0.10), far_side * GOAL_HALF_WIDTH * 0.75, True, "attack box outlet"
        return hx + v.dir * _sx(0.24), side * _sz(0.24), True, "stretch forward outlet"
    return None


def _center_restart(v: View) -> bool:
    """Kickoff/after-goal shape trigger when the ball is dead-center and loose."""
    return (not v.we_have_ball
            and abs(v.ball_xy[0]) <= _sx(0.08)
            and abs(v.ball_xy[1]) <= _sz(0.10))


# --------------------------------------------------------------------------- #
# Game management (score + clock) — scales the role config late in the match.  #
# Neutral in the first 60s and at level score, so early/0-0 play is unchanged. #
# --------------------------------------------------------------------------- #
def _game_mode(v: View) -> dict:
    # 2-min matches are SHOOTOUTS: protecting a lead ("sit deeper") just invites the
    # equalizer, so we NEVER ease off — attack always (operator directive 2026-06-25).
    # Leading or level -> play the normal attacking base; only ADD attack when chasing.
    t = v.gt or 0.0
    k = 0.0 if t < 60 else (0.5 if t < 90 else 1.0)   # ramp: mild 60-90s, strong >90s
    if k == 0.0 or v.goal_diff >= 0:                   # level OR leading -> keep attacking
        return {"push_delta": 0.0, "risk": 1.0, "press": 1.0, "shoot": 1.0}
    # chasing -> commit harder: push up, more risk/press, wider shot tolerance
    return {"push_delta": 0.10 * k, "risk": 1.0 + 0.4 * k, "press": 1.0 + 0.2 * k, "shoot": 1.0 + 0.2 * k}


# --------------------------------------------------------------------------- #
# Anti-exploitation: mixed strategy over NEAR-OPTIMAL actions only.            #
# Never trades quality (only actions within epsilon of the best are candidates)#
# Seeds are episode-stable (ball cell + candidate set), NOT per-tick, so a     #
# persisted PASS/GK command does not thrash; SHOOT is terminal so a per-tick   #
# seed is fine there. Deterministic given the seed -> offline replay is exact. #
# --------------------------------------------------------------------------- #
def _seed_int(*parts) -> int:
    h = 2166136261
    for p in parts:
        for ch in str(p):
            h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def _ball_cell(v: View) -> tuple:
    return (round(v.ball_xy[0] * 2) / 2, round(v.ball_xy[1] * 2) / 2)


def _near_optimal_pick(items, value_of, eps, seed):
    if not items:
        return None
    best = max(value_of(i) for i in items)
    near = [i for i in items if best - value_of(i) <= eps]
    if len(near) <= 1:
        return near[0] if near else items[0]
    return near[_seed_int(seed) % len(near)]


def _mixed_aim(base_aim: str, seed) -> str:
    """Mix only the vertical corner (T<->B); keep the horizontal side (away from
    the keeper) fixed -> no quality loss, keeper can't pre-commit vertically."""
    if len(base_aim) != 2:
        return base_aim
    vert, horiz = base_aim[0], base_aim[1]
    if _seed_int(seed) & 1:
        vert = "B" if vert == "T" else "T"
    return vert + horiz


def _carrier_pid(v: View):
    """Player id of the opponent on the ball (being pressed), or None."""
    c = _on_ball_opp(v)
    return _pid(c) if c is not None else None


def _carrier_will_be_pressed(v: View, team_id: int, formation: str | None) -> bool:
    """True iff our DESIGNATED presser (the rank-0 outfielder closest to the ball)
    actually satisfies its press/tackle gate — replicating the DEF-at-feet and
    single-presser conditions (closest + not tired + in range + non-DEF in-zone).
    A marker reserves the carrier for the presser ONLY when this is true, so a
    tired/out-of-zone nearby player does NOT falsely leave a lone carrier open."""
    if _on_ball_opp(v) is None:
        return False
    outs = [p for p in ([v.me] + list(v.teammates)) if _pid(p) != GK]
    if not outs:
        return False
    # rank-0 = closest to the ball with the same (dist, x, y) tiebreak as _ball_rank
    presser = min(outs, key=lambda p: (_hypot(*_field_xy(p), *v.ball_xy), *_field_xy(p)))
    if _norm_stamina(presser.get("stamina", 100)) < LOW_STAMINA:
        return False
    px, py = _field_xy(presser)
    ball_d = _hypot(px, py, *v.ball_xy)
    pslot = role_for_player(_pid(presser), formation)
    pcfg = ROLE_CONFIG.get(pslot, ROLE_CONFIG[MID])
    if _is_def(pslot):
        return ball_d <= _sx(0.11)                       # DEF press-at-feet gate (mode-independent)
    # non-DEF single-presser range is game-mode scaled in decide() (lead shrinks,
    # chase widens press_trigger) -> apply the SAME scaling here so the reservation
    # matches the presser's real range.
    mode_press = _game_mode(v)["press"]
    in_zone = _hypot(px, py, *anchor_world(pslot, team_id)) <= _zone_tol(pcfg) * 1.5
    return ball_d <= _press_dist(pcfg) * mode_press and in_zone   # single-presser gate


def _intruders(v: View, deprioritize_pid=None, exclude_pid=None, prefer_pid=None) -> list:
    """Opponents inside our defensive third, sorted by closeness to our goal.
    exclude_pid (the actively-pressed ball-carrier) is dropped entirely so the
    presser owns it alone. deprioritize_pid (an unpressed carrier) is merely moved
    to the END so markers cover off-ball threats first but still cover it if it is
    the only intruder -> never left open, never double-teamed."""
    intr = [o for o in v.opponents
            if abs(_field_xy(o)[0] - v.my_goal_x) < _sx(0.82) and _pid(o) != exclude_pid]
    if prefer_pid is None:
        return sorted(intr, key=lambda o: (1 if _pid(o) == deprioritize_pid else 0,
                                           abs(_field_xy(o)[0] - v.my_goal_x)))
    return sorted(intr, key=lambda o: (0 if _pid(o) == prefer_pid else 1,
                                       1 if _pid(o) == deprioritize_pid else 0,
                                       abs(_field_xy(o)[0] - v.my_goal_x)))


def _our_defender_pids(v: View, my_id: int, formation: str | None) -> list:
    """Stable, sorted list of our defenders' player ids (me + teammate defenders).
    Used to assign each defender a DISTINCT intruder so multiple defenders in a
    2-1-1/1-2-1 back line never double-mark the same man (swarm leak)."""
    pids = [my_id] if _is_def(role_for_player(my_id, formation)) else []
    pids += [_pid(t) for t in v.teammates if _is_def(role_for_player(_pid(t), formation))]
    return sorted(set(pids))


def _our_mid_pids(v: View, my_id: int, formation: str | None) -> list:
    """Stable, sorted list of our midfielders' player ids — so two midfielders in a
    1-2-1 don't both drop-mark the same striker."""
    pids = [my_id] if _is_mid(role_for_player(my_id, formation)) else []
    pids += [_pid(t) for t in v.teammates if _is_mid(role_for_player(_pid(t), formation))]
    return sorted(set(pids))


# --------------------------------------------------------------------------- #
# Core per-tick decision                                                      #
# --------------------------------------------------------------------------- #
def decide(game_state: dict, team_id: int, my_id: int, formation: str | None = None) -> Cmd:
    t = _current_tactics_safe()
    tactic_push = _tactic_push_ax(t)
    tactic_tempo = _tactic_tempo(t)
    slot = role_for_player(my_id, formation)        # tactical role under the active formation
    cfg = ROLE_CONFIG.get(slot, ROLE_CONFIG[MID])
    v = _parse(game_state, team_id, my_id)
    if v is None:
        return Cmd("SET_STANCE", {"stance": 0}, 0, "me not found")

    tired = v.stamina < LOW_STAMINA
    gk_opp = _gk_of(v.opponents)  # opponent keeper xy for shot eval
    press = _press_profile(game_state, v)

    # game management: late-match score-aware scaling (neutral first 60s / at 0-0)
    mode = _game_mode(v)
    press_mult = mode["press"]
    if slot != GK and (mode["risk"] != 1.0 or press_mult != 1.0 or mode["shoot"] != 1.0):
        cfg = replace(cfg, risk=cfg.risk * mode["risk"],
                      press_trigger=cfg.press_trigger * press_mult,
                      shoot_range=cfg.shoot_range * mode["shoot"])
    mode_push = mode["push_delta"] if slot != GK else 0.0

    # ===================== GK =========================================== #
    if slot == GK:
        if v.i_have_ball:
            opts = calculate_pass_options(v.me_xy, v.teammates, v.opponents)
            opts = [o for o in opts if _forwardness(v, o["x"]) > -_sx(0.09)] or opts
            if opts:
                seed = _seed_int("gk", _ball_cell(v), tuple(sorted(o["pid"] for o in opts)))
                o = _near_optimal_pick(opts, lambda x: x["success"], 0.08, seed)
                return Cmd("GK_DISTRIBUTE", {"target_player_id": o["pid"], "method": "THROW" if o["dist"] < _sx(0.45) else "KICK"}, 0, "GK distribute")
            return Cmd("GK_DISTRIBUTE", {"target_player_id": DEF, "method": "KICK"}, 0, "GK clear")
        # smother only a real close threat in the box
        ax, ay = anchor_world(slot, team_id)
        near_box = abs(v.ball_xy[0] - v.my_goal_x) < _sx(0.20)
        if near_box and _closest_teammate_to_ball_is_me(v) and _hypot(*v.me_xy, *v.ball_xy) < _press_dist(cfg):
            return Cmd("PRESS_BALL", {"intensity": 0.9}, 2, "GK smother")
        # shadow the ball's y a little, hold the line in x
        return _move(ax, max(-GOAL_HALF_WIDTH * 1.5, min(GOAL_HALF_WIDTH * 1.5, v.ball_xy[1] * 0.4)), False, "GK hold line")

    # ===================== ON THE BALL ================================== #
    if v.i_have_ball:
        shot = evaluate_shot(v.me_xy[0], v.me_xy[1], gk_opp, v.opp_goal_x,
                             [_field_xy(o) for o in v.opponents])
        attacker = _is_attacker(slot)
        real_chance = _shot_is_real_chance(v, v.me_xy[0], v.me_xy[1], shot)
        directness = press["direct"]
        # 1) HIGH-CONFIDENCE shot -> take it, never pass it off.
        if real_chance and shot["dist"] <= _shoot_dist(cfg) and shot["prob"] >= SHOOT_NOW_PROB:
            aim = _mixed_aim(shot["aim"], _seed_int("shoot", round(v.gt, 2), my_id, _ball_cell(v)))
            return Cmd("SHOOT", {"aim_location": aim, "power": shot["power"]}, 0, f"shoot! p={shot['prob']}")
        # 2) DECENT shot in range -> shoot unless a teammate has a clearly better look.
        if real_chance and shot["dist"] <= _shoot_dist(cfg) and shot["prob"] >= SHOOT_MIN_PROB:
            opts = calculate_pass_options(v.me_xy, v.teammates, v.opponents)
            # Pass it off ONLY if a teammate genuinely has a BETTER shot (Codex Q2:
            # the old test checked pass-success+forwardness, not the receiver's shot).
            better_pass = None
            for o in opts:
                if o["success"] <= 0.70 or _forwardness(v, o["x"]) <= _sx(0.11):
                    continue
                recv_shot = evaluate_shot(o["x"], o["y"], gk_opp, v.opp_goal_x,
                                          [_field_xy(opp) for opp in v.opponents])
                if (_shot_is_real_chance(v, o["x"], o["y"], recv_shot)
                        and recv_shot["prob"] >= max(SHOOT_NOW_PROB, shot["prob"] + 0.10)):
                    better_pass = o
                    break
            if better_pass is not None:
                return Cmd("PASS", {"target_player_id": better_pass["pid"], "type": better_pass["type"]}, 0, f"pass better look->{better_pass['pid']}")
            aim = _mixed_aim(shot["aim"], _seed_int("shoot", round(v.gt, 2), my_id, _ball_cell(v)))
            return Cmd("SHOOT", {"aim_location": aim, "power": shot["power"]}, 0, f"shoot p={shot['prob']}")
        # 3) FINISHING FIX (match #5: 16 shots, 0 on target = shooting from bad spots).
        #    Attacker near goal but low prob (wide angle / blocked) -> CARRY into a
        #    central high-prob shooting spot instead of recycling the ball backward.
        if attacker and shot["dist"] <= _sx(CARRY_TO_SHOOT_DIST):
            tx = v.opp_goal_x - v.dir * _sx(0.22)
            ty = v.me_xy[1] * 0.30
            tx, ty = _apply_attack_tactics(v, tx, ty, t)
            # carry-stall guard (Codex Q1): if already AT the spot but still blocked,
            # fall through to pass/dribble instead of re-issuing MOVE_TO forever.
            if _hypot(*v.me_xy, tx, ty) > _sx(0.05):
                return _move(tx, ty, True, f"carry into shooting position (p was {shot['prob']})")

        # DEF deep in our own third under pressure is handled after pass scoring:
        # release forward if a lane exists, clear only as the fallback.
        nearest_opp_d = min((_hypot(*v.me_xy, *_field_xy(o)) for o in v.opponents), default=999)
        def_deep_pressed = (
            _is_def(slot) and abs(v.me_xy[0] - v.my_goal_x) < _sx(0.40)
            and nearest_opp_d < _press_dist(cfg)
        )

        # pass to the best forward option through a clear lane
        opts = calculate_pass_options(v.me_xy, v.teammates, v.opponents)
        scored_opts = []
        for o in opts:
            recv_shot = evaluate_shot(o["x"], o["y"], gk_opp, v.opp_goal_x,
                                      [_field_xy(opp) for opp in v.opponents])
            scored_opts.append((o, recv_shot))
        if (attacker or def_deep_pressed) and _carrier_under_pressure(v, press):
            release = _pressure_release_option(v, scored_opts, directness, formation)
            if release is not None:
                ptype = release["type"]
                if _forwardness(v, release["x"]) > _sx(0.18):
                    ptype = "THROUGH"
                return Cmd("PASS", {"target_player_id": release["pid"], "type": ptype}, 0,
                           f"press release->{release['pid']} s={round(release['success'],2)}")
        if def_deep_pressed:
            return _move(v.opp_goal_x * 0.2, v.me_xy[1] + (_sz(0.23) if v.me_xy[1] <= 0 else -_sz(0.23)), True, "DEF clear under pressure")

        chance_opts = [
            (o, s) for o, s in scored_opts
            if o["success"] > 0.62 and _shot_is_real_chance(v, o["x"], o["y"], s) and s["prob"] >= SHOOT_MIN_PROB
        ]
        if chance_opts:
            o, s = max(chance_opts, key=lambda item: (item[1]["prob"], item[0]["success"]))
            return Cmd("PASS", {"target_player_id": o["pid"], "type": o["type"]}, 0, f"pass chance->{o['pid']} p={s['prob']}")
        fwd_opts = [o for o in opts if _forwardness(v, o["x"]) > _sx(0.11) and o["success"] > 0.58]
        safe_opts = []
        if tactic_tempo == "patient":
            safe_opts = [o for o in opts if o["success"] > 0.72 and _forwardness(v, o["x"]) >= -_sx(0.03)]
        pool = fwd_opts or safe_opts or [o for o in opts if o["success"] > 0.64]
        if pool:
            # anti-exploitation: mix near-equal buildup passes by COMPOSITE possession
            # EV (success + forwardness + receiver shot - risk), not raw success alone.
            shot_by_pid = {o2["pid"]: s for o2, s in scored_opts}

            def _pass_ev(o):
                s = shot_by_pid.get(o["pid"])
                shot_bonus = s["prob"] if (s and _shot_is_real_chance(v, o["x"], o["y"], s)) else 0.0
                return (0.6 * o["success"] + 0.5 * (_forwardness(v, o["x"]) / FIELD_X)
                        + 0.4 * shot_bonus - 0.3 * o["risk"])

            seed = _seed_int("pass", _ball_cell(v), tuple(sorted(o["pid"] for o in pool)))
            o = _near_optimal_pick(pool, _pass_ev, 0.10, seed)
            return Cmd("PASS", {"target_player_id": o["pid"], "type": o["type"]}, 0, f"pass->{o['pid']} s={round(o['success'],2)}")
        # no good pass -> carry toward goal
        tx, ty = _apply_attack_tactics(v, v.me_xy[0] + v.dir * _sx(0.22), v.me_xy[1] * 0.7, t)
        return _move(tx, ty, True, "dribble toward goal")

    # ===================== OFF THE BALL ================================= #
    # 1) single-presser discipline: ONLY the closest outfielder engages, and
    #    only inside its zone. This is the anti-swarm core — validated to beat
    #    the realistic baseline 16-0 clean sheet. (A 2nd presser was tried and
    #    REVERTED: it broke shape and lost the clean sheet for a degenerate
    #    all-swarm opponent that no real team plays. Don't chase that metric.)
    ball_d = _hypot(*v.me_xy, *v.ball_xy)
    in_zone = _hypot(*v.me_xy, *anchor_world(slot, team_id)) <= _zone_tol(cfg) * 1.5

    # 0) deterministic center restart: MID attacks the loose center ball while
    #    both strikers open lanes. GK+DEF stay in the normal home shape.
    if _center_restart(v):
        if _is_mid(slot):
            return _move(v.ball_xy[0], v.ball_xy[1], True, "restart claim center")
        if _is_fwd(slot):
            side = -1 if slot == FWD1 else 1
            return _move(v.dir * _sx(0.34), side * _sz(0.18), True, "restart forward lane")

    # 1) DEF is a DEFENDER FIRST. Live #1 we played 0 MARK + 188 PRESS and got
    #    countered 4x. So DEF marks the most dangerous attacker by default and
    #    only leaves the mark to win a ball that is right at its feet.
    if _is_def(slot) and not v.we_have_ball:
        if ball_d <= _sx(0.11) and _closest_teammate_to_ball_is_me(v) and not tired:
            carrier = _on_ball_opp(v)
            if carrier is not None and cfg.risk >= 0.05:
                return Cmd("SLIDE_TACKLE", {"target_player_id": _pid(carrier), "sprint": True, "distance": round(_sx(0.07), 2)}, 0, "DEF tackle at feet")
            return Cmd("PRESS_BALL", {"intensity": 0.8}, 2, "DEF press at feet")
        _cpid = _carrier_pid(v)
        _pressed = _carrier_will_be_pressed(v, team_id, formation)
        intruders = _intruders(v, deprioritize_pid=_cpid, exclude_pid=(_cpid if _pressed else None))
        if intruders:
            # multi-defender coordination: defender k marks the k-th most dangerous
            # intruder, so DEF and DEF2 (2-1-1) never double-mark the same man. A
            # spare defender (more defenders than intruders) holds shape below.
            defs = _our_defender_pids(v, my_id, formation)
            idx = defs.index(my_id) if my_id in defs else 0
            if idx < len(intruders):
                return Cmd("MARK", {"target_player_id": _pid(intruders[idx]), "tightness": "TIGHT"}, 3, "DEF mark danger")
        # else hold the deep anchor (the shape recovery below handles it). The earlier
        # "counter-screen" MOVE was REMOVED: it made DEF chase/drop and contributed to
        # the 203-PRESS swarm that got countered 1-3.

    # 2) single-presser for the rest: ONLY the closest outfielder, in zone, not
    #    tired. Holds shape, no swarm, no over-commit (DEF excluded -> stays home).
    if (not v.we_have_ball and not _is_def(slot) and ball_d <= _press_dist(cfg)
            and _closest_teammate_to_ball_is_me(v) and in_zone and not tired):
        carrier = _on_ball_opp(v)
        if carrier is not None and _hypot(*v.me_xy, *_field_xy(carrier)) <= _sx(0.11) and cfg.risk >= 0.3 and not tired:
            return Cmd("SLIDE_TACKLE", {"target_player_id": _pid(carrier), "sprint": True, "distance": round(_sx(0.07), 2)}, 0, "tackle carrier")
        return Cmd("PRESS_BALL", {"intensity": 0.8}, 2, "closest+in-zone press")

    # 2b) Rest-defense: a spare MID drops to mark a 2nd advanced attacker that DEF
    #     cannot cover (two-striker overload). MARK is positioning, not a press, so
    #     the single-presser anti-swarm invariant is preserved (no extra presser).
    if DROP_MARK_ENABLED and _is_mid(slot) and not v.we_have_ball and not tired:
        _cpid = _carrier_pid(v)
        _pressed = _carrier_will_be_pressed(v, team_id, formation)
        intruders = _intruders(v, deprioritize_pid=_cpid, exclude_pid=(_cpid if _pressed else None))
        num_def = len(_our_defender_pids(v, my_id, formation))
        mids = _our_mid_pids(v, my_id, formation)
        my_mid_idx = mids.index(my_id) if my_id in mids else 0
        # markers are ordered defenders THEN dropping midfielders; this MID takes the
        # (num_def + my_mid_idx)-th intruder so two mids (1-2-1) never double-mark.
        # In 1-1-2 (1 def, 1 mid) this is intruders[1] -> unchanged behavior.
        target_idx = num_def + my_mid_idx
        if target_idx < len(intruders):
            return Cmd("MARK", {"target_player_id": _pid(intruders[target_idx]), "tightness": "NORMAL"}, 3, "MID drop-mark spare striker")

    # 3) hold shape: recover to anchor (with attacking push if we possess)
    if v.we_have_ball:
        holder = possession_holder(game_state)
        carrier_slot = role_for_player(_pid(holder), formation) if holder is not None else MID
        support = _support_run(v, slot, my_id, holder, carrier_slot, press["direct"])
        if support is not None:
            tx, ty, sprint, reason = support
            if _is_mid(slot) or _is_fwd(slot):
                tx, ty = _apply_attack_tactics(v, tx, ty, t)
            if _hypot(*v.me_xy, tx, ty) > _sx(SUPPORT_MIN_MOVE):
                return _move(tx, ty, sprint and not tired, reason)

    push = (cfg.push_when_attacking + mode_push + tactic_push) if v.we_have_ball else 0.0
    if v.we_have_ball and press["high"]:
        if _is_def(slot):
            push = min(push, 0.03)
        elif _is_mid(slot):
            push = min(push, 0.18)
    ax, ay = anchor_world(slot, team_id, push)
    if v.we_have_ball:
        ax, ay = _apply_attack_tactics(v, ax, ay, t)
    if _hypot(*v.me_xy, ax, ay) > _zone_tol(cfg):
        return _move(ax, ay, v.we_have_ball, "return to zone")

    # 4) in position: offer an advanced outlet if we have the ball, else hold
    if v.we_have_ball:
        tx, ty = _apply_attack_tactics(v, ax + v.dir * 0.10 * FIELD_X, ay, t)
        return _move(tx, ty, False, "offer outlet")
    return Cmd("SET_STANCE", {"stance": 1 if _is_fwd(slot) else 0}, 0, "hold shape")


def _gk_of(players: list):
    gk = next((p for p in players if _pid(p) == GK), None)
    return _field_xy(gk) if gk else None


def _on_ball_opp(v: View):
    if not v.opponents:
        return None
    o = min(v.opponents, key=lambda o: _hypot(*v.ball_xy, *_field_xy(o)))
    return o if _hypot(*v.ball_xy, *_field_xy(o)) <= _sx(0.09) else None


# --------------------------------------------------------------------------- #
# Runtime entry: game_state -> the contest command dict                       #
# --------------------------------------------------------------------------- #
def command(game_state: dict, team_id: int, my_id: int, formation: str | None = None) -> dict:
    c = decide(game_state, team_id, my_id, formation)
    return {"commandType": c.commandType, "playerId": my_id, "teamId": team_id,
            "parameters": c.parameters, "duration": c.duration}


if __name__ == "__main__":
    # smoke: FWD1 on the ball near the opp goal should SHOOT
    gs = {
        "ball": {"position": {"x": 5.0, "y": 0.10, "z": -0.8}, "possessionAgentId": "agentId_3", "possessionTeam": "home"},
        "score": {"home": 0, "away": 0}, "gameTime": 30,
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -6.4, "y": 0.0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -3.0, "y": 0.0}, "stamina": 100},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 0.5, "y": 0.0}, "stamina": 100},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 5.0, "y": -0.8}, "stamina": 100},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 5.0, "y": 0.8}, "stamina": 100},
            {"agentId": "agentId_0", "teamCode": "away", "position": {"x": 6.4, "y": 0.1}, "stamina": 100},
        ],
    }
    print("FWD1 near goal ->", command(gs, 0, 3))
    print("MID holding    ->", command(gs, 0, 2))
    print("GK             ->", command(gs, 0, 0))
