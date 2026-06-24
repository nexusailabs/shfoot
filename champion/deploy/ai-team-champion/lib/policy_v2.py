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
  * Real contract (verified from aws-samples sample-ai-possibilities + live
    CloudShell config, 2026-06-24), NOT the assumed agenticfootballcup.com one:
      - Field x in [-55, 55], y in [-35, 35]. Goals at x = +-55, y in [-5, 5].
      - Roster of 5: id0=GK, id1=DEF, id2=MID, id3=FWD1, id4=FWD2  (a 1-1-2).
      - team_id 0 = HOME (my goal x=-55, attack +x); 1 = AWAY (mirror).
      - obs: game_state{ball{position{x,y}, possessionAgentId|possessionPlayerId},
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
from dataclasses import dataclass, field

# Pitch geometry (world coordinates, matches the contest engine + Gateway tools)
FIELD_X = 55.0
FIELD_Y = 35.0
GOAL_HALF_WIDTH = 5.0          # goal mouth half-height around y=0 (evaluate_shot.py)

# Roster: fixed player ids -> role.
GK, DEF, MID, FWD1, FWD2 = 0, 1, 2, 3, 4
ROLE_NAME = {GK: "GK", DEF: "DEF", MID: "MID", FWD1: "FWD1", FWD2: "FWD2"}


# --------------------------------------------------------------------------- #
# Per-position config — the championship "settings per player" (1-1-2).        #
# Anchors are in ATTACKING-FRAME fractions: ax in [-1,1] where +1 = opp goal,  #
# ay in [-1,1] where +1 = +y touchline. Converted to world coords per team.   #
# --------------------------------------------------------------------------- #
@dataclass
class RoleConfig:
    anchor_ax: float                 # home x, attacking-frame fraction of FIELD_X
    anchor_ay: float                 # home y, fraction of FIELD_Y
    zone_tol: float                  # world-units a role may stray before recovering
    press_trigger: float             # engage on-ball duels only within this (world units)
    shoot_range: float               # |dist to opp goal| under which shooting is considered
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
ROLE_CONFIG: dict[int, RoleConfig] = {
    GK:   RoleConfig(anchor_ax=-0.92, anchor_ay=0.00, zone_tol=14.0, press_trigger=8.0,  shoot_range=0.0,  push_when_attacking=0.03, risk=0.0),
    DEF:  RoleConfig(anchor_ax=-0.45, anchor_ay=0.00, zone_tol=22.0, press_trigger=11.0, shoot_range=0.0,  push_when_attacking=0.10, risk=0.05),
    MID:  RoleConfig(anchor_ax=-0.02, anchor_ay=0.00, zone_tol=26.0, press_trigger=13.0, shoot_range=22.0, push_when_attacking=0.30, risk=0.30),
    FWD1: RoleConfig(anchor_ax=0.50,  anchor_ay=-0.32, zone_tol=30.0, press_trigger=11.0, shoot_range=28.0, push_when_attacking=0.28, risk=0.45),
    FWD2: RoleConfig(anchor_ax=0.50,  anchor_ay=0.32,  zone_tol=30.0, press_trigger=11.0, shoot_range=28.0, push_when_attacking=0.28, risk=0.45),
}

LOW_STAMINA = 22.0               # below this (0..100, normalized) avoid optional sprint actions
SHOOT_MIN_PROB = 0.40            # shoot only above this inlined prob (Codex #3: 0.45 starved shots; 0.40 still rejects bad long shots)


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
    ball_xy = _xy(ball.get("position", {"x": 0, "y": 0}))
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
    return min(cands, key=lambda p: _hypot(*_xy(p), *ball_xy))


def goal_x(team_id: int) -> tuple[float, float]:
    """(my_goal_x, opp_goal_x)."""
    return (-FIELD_X, FIELD_X) if team_id == 0 else (FIELD_X, -FIELD_X)


def _xy(p: dict) -> tuple[float, float]:
    pos = p.get("position", p)
    return float(pos.get("x", 0.0)), float(pos.get("y", 0.0))


def _hypot(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)


# --------------------------------------------------------------------------- #
# Inlined Gateway math (the real contest tactical tools, decided in code).     #
# --------------------------------------------------------------------------- #
def evaluate_shot(sx, sy, gk_xy, opp_goal_x, blockers) -> dict:
    """Port of gateway_tools/evaluate_shot.py. Returns probability + aim + power."""
    gx, gy = opp_goal_x, 0.0
    dist_goal = _hypot(sx, sy, gx, gy)
    angle = math.atan2(GOAL_HALF_WIDTH, max(dist_goal, 1e-6))
    angle_factor = min(1.0, angle / 0.15)
    distance_factor = max(0.0, 1.0 - dist_goal / FIELD_X)
    gk_off = abs(gk_xy[1]) if gk_xy else 0.0
    gk_factor = min(1.0, gk_off / 8.0) * 0.3
    gk_dist = _hypot(gk_xy[0], gk_xy[1], gx, gy) if gk_xy else 0.0
    gk_dist_factor = min(1.0, gk_dist / 15.0) * 0.2
    pen = 0.0
    for bx, by in blockers:
        bd = _hypot(sx, sy, bx, by)
        if bd < 10:
            pen += (10 - bd) / 10.0 * 0.15
    pen = min(pen, 0.4)
    prob = round(max(0.02, min(0.95, distance_factor * 0.45 + angle_factor * 0.25 + gk_factor + gk_dist_factor - pen)), 2)
    # aim away from the GK
    if gk_xy and gk_xy[1] > 1:
        aim = "BL" if sy > 0 else "BR"
    elif gk_xy and gk_xy[1] < -1:
        aim = "TL" if sy > 0 else "TR"
    else:
        aim = "TR" if sy <= 0 else "TL"
    power = round(min(1.0, 0.6 + dist_goal / 80.0), 2)
    # should_shoot computed on the ROUNDED probability, matching the Lambda.
    return {"prob": prob, "aim": aim, "power": power, "should_shoot": prob > 0.25, "dist": dist_goal}


def calculate_pass_options(me_xy, teammates, opponents) -> list[dict]:
    """Port of gateway_tools/calculate_pass_options.py. Ranked pass options."""
    px, py = me_xy
    opp_xy = [_xy(o) for o in opponents]
    out = []
    for tm in teammates:
        tx, ty = _xy(tm)
        d = _hypot(px, py, tx, ty)
        risk = round(_intercept_risk(px, py, tx, ty, opp_xy), 2)
        success = round(max(0.05, 1.0 - risk - d / 120.0), 2)   # rounded, matches Lambda
        out.append({
            "pid": _pid(tm), "x": tx, "y": ty, "dist": round(d, 1),
            "risk": risk, "success": success,
            "type": "GROUND" if d < 20 else ("THROUGH" if success > 0.5 else "AERIAL"),
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
        if lane < 8:
            risk = max(risk, 1.0 - lane / 8.0)
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
    ty = max(-FIELD_Y, min(FIELD_Y, ty))
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


def _parse(game_state: dict, team_id: int, my_id: int) -> View | None:
    players = game_state.get("players", [])
    ball = game_state.get("ball", {})
    ball_xy = _xy(ball.get("position", {"x": 0, "y": 0}))
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
    return View(
        me=me, me_xy=_xy(me), ball_xy=ball_xy, teammates=mine, opponents=opp,
        poss=(_pid(holder) if holder is not None else None),
        i_have_ball=i_have, we_have_ball=we_have,
        team_id=team_id, my_goal_x=my_goal_x, opp_goal_x=opp_goal_x,
        dir=(1 if team_id == 0 else -1), stamina=_norm_stamina(me.get("stamina", 100)),
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


def anchor_world(role_id: int, team_id: int, push: float = 0.0) -> tuple[float, float]:
    cfg = ROLE_CONFIG[role_id]
    d = 1 if team_id == 0 else -1
    ax = max(-0.98, min(0.98, cfg.anchor_ax + push))
    # Only x is direction-flipped per team (goals are on the x axis). y is NOT
    # flipped — the pitch is y-symmetric and the sample contract uses absolute y
    # (lib/fallback.py), so flipping it would diverge from the engine's frame.
    return ax * FIELD_X * d, cfg.anchor_ay * FIELD_Y


def _forwardness(v: View, x: float) -> float:
    """How far upfield x is, in the attacking direction (+ = toward opp goal)."""
    return (x - v.me_xy[0]) * v.dir


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
        tx, ty = _xy(t)
        td = _hypot(tx, ty, *v.ball_xy)
        if td < my_d - 1e-9 or (abs(td - my_d) <= 1e-9 and (tx, ty) < (mx, my)):
            rank += 1
    return rank


def _closest_teammate_to_ball_is_me(v: View) -> bool:
    """True for exactly one outfield agent (rank 0)."""
    return _ball_rank(v) == 0


# --------------------------------------------------------------------------- #
# Core per-tick decision                                                      #
# --------------------------------------------------------------------------- #
def decide(game_state: dict, team_id: int, my_id: int) -> Cmd:
    role_id = my_id
    cfg = ROLE_CONFIG.get(role_id, ROLE_CONFIG[MID])
    v = _parse(game_state, team_id, my_id)
    if v is None:
        return Cmd("SET_STANCE", {"stance": 0}, 0, "me not found")

    tired = v.stamina < LOW_STAMINA
    gk_opp = _gk_of(v.opponents)  # opponent keeper xy for shot eval

    # ===================== GK =========================================== #
    if role_id == GK:
        if v.i_have_ball:
            opts = calculate_pass_options(v.me_xy, v.teammates, v.opponents)
            opts = [o for o in opts if _forwardness(v, o["x"]) > -5] or opts
            if opts:
                o = opts[0]
                return Cmd("GK_DISTRIBUTE", {"target_player_id": o["pid"], "method": "THROW" if o["dist"] < 25 else "KICK"}, 0, "GK distribute best")
            return Cmd("GK_DISTRIBUTE", {"target_player_id": DEF, "method": "KICK"}, 0, "GK clear")
        # smother only a real close threat in the box
        ax, ay = anchor_world(GK, team_id)
        ball_fwd = _forwardness(v, v.ball_xy[0])
        near_box = abs(v.ball_xy[0] - v.my_goal_x) < 18
        if near_box and _closest_teammate_to_ball_is_me(v) and _hypot(*v.me_xy, *v.ball_xy) < cfg.press_trigger:
            return Cmd("PRESS_BALL", {"intensity": 0.9}, 2, "GK smother")
        # shadow the ball's y a little, hold the line in x
        return _move(ax, max(-GOAL_HALF_WIDTH * 1.5, min(GOAL_HALF_WIDTH * 1.5, v.ball_xy[1] * 0.4)), False, "GK hold line")

    # ===================== ON THE BALL ================================== #
    if v.i_have_ball:
        shot = evaluate_shot(v.me_xy[0], v.me_xy[1], gk_opp, v.opp_goal_x,
                             [_xy(o) for o in v.opponents])
        # SHOT DISCIPLINE (live #1: 53 SHOOT -> 1 on target). Shoot ONLY when in
        # range AND the inlined prob clears SHOOT_MIN_PROB. Otherwise pass/carry.
        if shot["dist"] <= cfg.shoot_range and shot["prob"] >= SHOOT_MIN_PROB:
            opts = calculate_pass_options(v.me_xy, v.teammates, v.opponents)
            best_pass = opts[0] if opts else None
            gray = (SHOOT_MIN_PROB <= shot["prob"] < SHOOT_MIN_PROB + 0.10
                    and best_pass is not None and best_pass["success"] > 0.7)
            return Cmd("SHOOT", {"aim_location": shot["aim"], "power": shot["power"]}, 0, f"shoot p={shot['prob']}", gray)

        # DEF deep in our own third under pressure -> clear forward, don't dribble
        # into a turnover. (own-third = my x within 22 units of our goal line.)
        nearest_opp_d = min((_hypot(*v.me_xy, *_xy(o)) for o in v.opponents), default=99)
        if role_id == DEF and abs(v.me_xy[0] - v.my_goal_x) < 22 and nearest_opp_d < cfg.press_trigger:
            return _move(v.opp_goal_x * 0.2, v.me_xy[1] + (8 if v.me_xy[1] <= 0 else -8), True, "DEF clear under pressure")

        # pass to the best forward option through a clear lane
        opts = calculate_pass_options(v.me_xy, v.teammates, v.opponents)
        fwd_opts = [o for o in opts if _forwardness(v, o["x"]) > 6 and o["success"] > 0.45]
        pool = fwd_opts or [o for o in opts if o["success"] > 0.55]
        if pool:
            o = pool[0]
            return Cmd("PASS", {"target_player_id": o["pid"], "type": o["type"]}, 0, f"pass->{o['pid']} s={round(o['success'],2)}")
        # no good pass -> carry toward goal
        return _move(v.me_xy[0] + v.dir * 12, v.me_xy[1] * 0.7, True, "dribble toward goal")

    # ===================== OFF THE BALL ================================= #
    # 1) single-presser discipline: ONLY the closest outfielder engages, and
    #    only inside its zone. This is the anti-swarm core — validated to beat
    #    the realistic baseline 16-0 clean sheet. (A 2nd presser was tried and
    #    REVERTED: it broke shape and lost the clean sheet for a degenerate
    #    all-swarm opponent that no real team plays. Don't chase that metric.)
    ball_d = _hypot(*v.me_xy, *v.ball_xy)
    in_zone = _hypot(*v.me_xy, *anchor_world(role_id, team_id)) <= cfg.zone_tol * 1.5

    # 1) DEF is a DEFENDER FIRST. Live #1 we played 0 MARK + 188 PRESS and got
    #    countered 4x. So DEF marks the most dangerous attacker by default and
    #    only leaves the mark to win a ball that is right at its feet.
    if role_id == DEF and not v.we_have_ball:
        if ball_d <= 6.0 and _closest_teammate_to_ball_is_me(v) and not tired:
            carrier = _on_ball_opp(v)
            if carrier is not None and cfg.risk >= 0.05:
                return Cmd("SLIDE_TACKLE", {"target_player_id": _pid(carrier), "sprint": True, "distance": 4.0}, 0, "DEF tackle at feet")
            return Cmd("PRESS_BALL", {"intensity": 0.8}, 2, "DEF press at feet")
        intruders = [o for o in v.opponents if abs(_xy(o)[0] - v.my_goal_x) < 45]
        if intruders:
            danger = min(intruders, key=lambda o: abs(_xy(o)[0] - v.my_goal_x))
            return Cmd("MARK", {"target_player_id": _pid(danger), "tightness": "TIGHT"}, 3, "DEF mark danger")

    # 2) single-presser for the rest: ONLY the closest outfielder, in zone, not
    #    tired. Holds shape, no swarm, no over-commit (DEF excluded -> stays home).
    if (not v.we_have_ball and role_id != DEF and ball_d <= cfg.press_trigger
            and _closest_teammate_to_ball_is_me(v) and in_zone and not tired):
        carrier = _on_ball_opp(v)
        if carrier is not None and _hypot(*v.me_xy, *_xy(carrier)) <= 6.0 and cfg.risk >= 0.3 and not tired:
            return Cmd("SLIDE_TACKLE", {"target_player_id": _pid(carrier), "sprint": True, "distance": 4.0}, 0, "tackle carrier")
        return Cmd("PRESS_BALL", {"intensity": 0.8}, 2, "closest+in-zone press")

    # 3) hold shape: recover to anchor (with attacking push if we possess)
    push = cfg.push_when_attacking if v.we_have_ball else 0.0
    ax, ay = anchor_world(role_id, team_id, push)
    if _hypot(*v.me_xy, ax, ay) > cfg.zone_tol:
        return _move(ax, ay, v.we_have_ball, "return to zone")

    # 4) in position: offer an advanced outlet if we have the ball, else hold
    if v.we_have_ball:
        return _move(ax + v.dir * 0.10 * FIELD_X, ay, False, "offer outlet")
    return Cmd("SET_STANCE", {"stance": 1 if role_id in (FWD1, FWD2) else 0}, 0, "hold shape")


def _gk_of(players: list):
    gk = next((p for p in players if _pid(p) == GK), None)
    return _xy(gk) if gk else None


def _on_ball_opp(v: View):
    if not v.opponents:
        return None
    o = min(v.opponents, key=lambda o: _hypot(*v.ball_xy, *_xy(o)))
    return o if _hypot(*v.ball_xy, *_xy(o)) <= 5.0 else None


# --------------------------------------------------------------------------- #
# Runtime entry: game_state -> the contest command dict                       #
# --------------------------------------------------------------------------- #
def command(game_state: dict, team_id: int, my_id: int) -> dict:
    c = decide(game_state, team_id, my_id)
    return {"commandType": c.commandType, "playerId": my_id, "teamId": team_id,
            "parameters": c.parameters, "duration": c.duration}


if __name__ == "__main__":
    # smoke: FWD1 on the ball near the opp goal should SHOOT
    gs = {
        "ball": {"position": {"x": 45, "y": -6}, "possessionAgentId": "agentId_3"},
        "score": {"home": 0, "away": 0}, "gameTime": 30,
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -20, "y": 0}, "stamina": 100},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 10, "y": 0}, "stamina": 100},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 45, "y": -6}, "stamina": 100},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 45, "y": 8}, "stamina": 100},
            {"agentId": "agentId_0", "teamCode": "away", "position": {"x": 54, "y": 1}, "stamina": 100},
        ],
    }
    print("FWD1 near goal ->", command(gs, 0, 3))
    print("MID holding    ->", command(gs, 0, 2))
    print("GK             ->", command(gs, 0, 0))
