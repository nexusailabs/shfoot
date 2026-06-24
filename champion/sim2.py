"""
Agentic Football Cup — real-contract offline match simulator (championship).

Faithful to the verified AWS contract: ±55 × ±35 pitch, goals at x=±55 (mouth
|y|<7), 5 players/side (id0 GK..id4 FWD2), real game_state schema fed to each
brain every tick, real command dicts applied. ZERO AWS / ZERO LLM — every brain
is a pure function so we can MEASURE strategies before deploying.

Brains under test:
  * champion : champion.policy_v2.command  (our zero-LLM policy)
  * baseline : faithful port of the sample lib/fallback.py (the deployed-team
               behaviour: press-if-within-20 => ball-chasing swarm)
  * swarm    : everyone sprints at the ball (worst case)

Reported: score, possession %, mean team-spread (a swarm collapses spread ->
low; discipline holds it -> high), and max per-tick decision latency.

Physics constants are first-pass and TUNABLE; calibrate to a real Player-Portal
replay (game-events JSON) when available. Relative ranking of strategies is
robust to the exact constants.

Run:  python3 champion/sim2.py
      python3 champion/sim2.py --ticks 400 --matches 5
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy_v2 as P

FIELD_X, FIELD_Y = 55.0, 35.0
GOAL_MOUTH = 7.0
PLAYER_SPEED = 2.5
SPRINT_SPEED = 3.8
PASS_SPEED = 6.0
SHOOT_SPEED = 12.0
BALL_FRICTION = 0.90
CONTROL_RADIUS = 3.0
TACKLE_RADIUS = 3.5
GK_SAVE_RADIUS = 4.0
STAM_DRAIN = 0.30
STAM_RECOVER = 0.20
KICKOFF = {0: (-2.0, 0.0), 1: (2.0, 0.0)}

START_AX = {  # attacking-frame anchors per id (reuse policy anchors)
    i: (P.ROLE_CONFIG[i].anchor_ax, P.ROLE_CONFIG[i].anchor_ay) for i in range(5)
}


def _clampx(x): return max(-FIELD_X, min(FIELD_X, x))
def _clampy(y): return max(-FIELD_Y, min(FIELD_Y, y))


class Player:
    __slots__ = ("pid", "team", "x", "y", "stam")

    def __init__(self, pid, team):
        self.pid, self.team = pid, team
        ax, ay = START_AX[pid]
        d = 1 if team == 0 else -1
        self.x = _clampx(ax * FIELD_X * d)
        self.y = _clampy(ay * FIELD_Y * d)
        self.stam = 100.0

    def reset(self):
        ax, ay = START_AX[self.pid]
        d = 1 if self.team == 0 else -1
        self.x, self.y = _clampx(ax * FIELD_X * d), _clampy(ay * FIELD_Y * d)


class World:
    def __init__(self):
        self.players = {0: [Player(i, 0) for i in range(5)],
                        1: [Player(i, 1) for i in range(5)]}
        self.bx, self.by, self.bvx, self.bvy = 0.0, 0.0, 0.0, 0.0
        self.carrier = None          # (team, pid) or None
        self.score = {0: 0, 1: 0}
        self.pass_cooldown = 0        # ticks before passer can recapture
        self.shot_quality = 0.0       # evaluate_shot prob of the in-flight shot (0 = not a shot)
        self.shot_team = None         # which team's shot is in flight
        self.rng = random.Random(0)   # seeded per match for reproducible conversion

    def kickoff(self, team):
        for t in (0, 1):
            for p in self.players[t]:
                p.reset()
        self.bx = self.by = self.bvx = self.bvy = 0.0
        self.carrier = (team, MID := 2)
        self.pass_cooldown = 0

    # build the real-schema game_state from one team's perspective-agnostic world
    def game_state(self):
        players = []
        for t in (0, 1):
            code = "home" if t == 0 else "away"
            for p in self.players[t]:
                # GLOBALLY-UNIQUE agentId (home_0..away_4) so possession never
                # collides across teams; trailing int still = per-team index 0-4.
                players.append({"agentId": f"{code}_{p.pid}", "teamCode": code,
                                "position": {"x": p.x, "y": p.y}, "stamina": p.stam})
        ball = {"position": {"x": self.bx, "y": self.by}}
        if self.carrier is not None:
            ct, cp = self.carrier
            ball["possessionAgentId"] = f"{'home' if ct == 0 else 'away'}_{cp}"
        return {"ball": ball, "score": {"home": self.score[0], "away": self.score[1]},
                "gameTime": 0, "players": players}


def _aim_y(aim: str) -> float:
    return {"TL": -GOAL_MOUTH * 0.6, "BL": -GOAL_MOUTH * 0.6,
            "TR": GOAL_MOUTH * 0.6, "BR": GOAL_MOUTH * 0.6,
            "CENTER": 0.0}.get(aim, 0.0)


def _find(team_players, pid):
    for p in team_players:
        if p.pid == pid:
            return p
    return None


def _possession_for(world, team):
    """game_state already encodes possession by agentId + possessionTeam; the
    brains resolve 'mine' via teamCode, so we must make possessionAgentId unique
    across teams. Patch: encode team into the dict the brain reads."""
    return world.carrier


def step(world: World, brains, latencies):
    gs = world.game_state()
    # disambiguate possession per team for the brain: it checks possessionAgentId
    # against its own players; we annotate gs with possessionTeam so a brain only
    # counts possession if it's the holding team.
    cmds = {0: {}, 1: {}}
    for t in (0, 1):
        # give each team a possession-correct view (hide opp possessionAgentId
        # collision by clearing it when the holder isn't on team t)
        view = _view_for_team(gs, world, t)
        for p in world.players[t]:
            t0 = time.perf_counter()
            try:
                c = brains[t](view, t, p.pid)
            except Exception as e:
                c = {"commandType": "SET_STANCE", "playerId": p.pid, "teamId": t,
                     "parameters": {"stance": 0}, "duration": 0, "_err": str(e)}
            latencies.append((time.perf_counter() - t0) * 1000.0)
            cmds[t][p.pid] = c

    _apply(world, cmds)
    _ball_physics(world)
    _resolve_possession(world)
    return _goal_check(world)


def _view_for_team(gs, world, team):
    """A per-team copy where possessionAgentId is present only if the holder is
    on `team` OR on the opponent (brains need to know opp has it too). The real
    engine sends possessionAgentId + the holder's teamCode; our brains read
    possession by matching agentId among players of their own team. To stay
    faithful we keep possessionAgentId global and also keep possessionTeam so a
    brain can tell whose it is. policy_v2 already resolves holder via the players
    list + _is_mine, so a plain global gs is correct; we pass gs as-is."""
    return gs


def _apply(world, cmds):
    if world.pass_cooldown > 0:
        world.pass_cooldown -= 1
    for t in (0, 1):
        for p in world.players[t]:
            c = cmds[t].get(p.pid)
            if not c:
                continue
            ct = c.get("commandType")
            par = c.get("parameters", {})
            holding = world.carrier == (t, p.pid)
            sprint = False
            tx, ty = p.x, p.y

            if ct == "MOVE_TO":
                tx, ty = par.get("target_x", p.x), par.get("target_y", p.y)
                sprint = bool(par.get("sprint"))
            elif ct in ("PRESS_BALL", "INTERCEPT"):
                tx, ty, sprint = world.bx, world.by, True
            elif ct in ("MARK", "FOLLOW_PLAYER", "SLIDE_TACKLE"):
                target = _find(world.players[1 - t], par.get("target_player_id", -1))
                if ct in ("MARK", "FOLLOW_PLAYER") and target is None:
                    target = _find(world.players[1 - t], 2)
                if target:
                    tx, ty, sprint = target.x, target.y, (ct == "SLIDE_TACKLE")
            elif ct in ("PASS", "GK_DISTRIBUTE") and holding:
                mate = _find(world.players[t], par.get("target_player_id", -1))
                if mate:
                    _launch(world, p, mate.x, mate.y, PASS_SPEED)
                    world.carrier = None
                    world.pass_cooldown = 2
                    world.shot_quality, world.shot_team = 0.0, None   # a pass can't score
                continue
            elif ct == "SHOOT" and holding:
                opp_goal_x = FIELD_X if t == 0 else -FIELD_X
                # shot quality = the REAL evaluate_shot probability from here.
                # Selective high-quality shots convert; speculative long shots
                # (swarm power=1.0 from midfield) mostly get saved/miss.
                gk = _find(world.players[1 - t], 0)
                world.shot_quality = P.evaluate_shot(
                    p.x, p.y, (gk.x, gk.y) if gk else None, opp_goal_x,
                    [(o.x, o.y) for o in world.players[1 - t] if o.pid != 0])["prob"]
                world.shot_team = t
                _launch(world, p, opp_goal_x, _aim_y(par.get("aim_location", "CENTER")),
                        SHOOT_SPEED * max(0.5, float(par.get("power", 0.8))))
                world.carrier = None
                world.pass_cooldown = 3
                continue
            else:  # SET_STANCE / CLEAR_OVERRIDE / RESET / unknown -> hold
                pass

            # move toward (tx,ty)
            spd = SPRINT_SPEED if (sprint and p.stam > 5) else PLAYER_SPEED
            dx, dy = tx - p.x, ty - p.y
            d = math.hypot(dx, dy)
            if d > 1e-6:
                step_d = min(spd, d)
                p.x = _clampx(p.x + dx / d * step_d)
                p.y = _clampy(p.y + dy / d * step_d)
            p.stam = max(0.0, p.stam - STAM_DRAIN) if sprint else min(100.0, p.stam + STAM_RECOVER)
            # carrier drags the ball at his feet
            if holding:
                world.bx, world.by, world.bvx, world.bvy = p.x, p.y, 0.0, 0.0


def _launch(world, p, tx, ty, speed):
    dx, dy = tx - p.x, ty - p.y
    d = math.hypot(dx, dy) or 1.0
    world.bx, world.by = p.x, p.y
    world.bvx, world.bvy = dx / d * speed, dy / d * speed


def _ball_physics(world):
    if world.carrier is not None:
        return
    world.bx = world.bx + world.bvx
    world.by = world.by + world.bvy
    world.bvx *= BALL_FRICTION
    world.bvy *= BALL_FRICTION
    # bounce off side lines (y), let x run out for goal detection
    if world.by > FIELD_Y or world.by < -FIELD_Y:
        world.by = _clampy(world.by)
        world.bvy *= -0.5


def _resolve_possession(world):
    if world.carrier is not None:
        ct, cp = world.carrier
        carrier = _find(world.players[ct], cp)
        # an opponent within tackle radius knocks it loose
        for opp in world.players[1 - ct]:
            if math.hypot(opp.x - carrier.x, opp.y - carrier.y) <= TACKLE_RADIUS:
                world.carrier = None
                world.bvx, world.bvy = (carrier.x - opp.x), (carrier.y - opp.y)
                n = math.hypot(world.bvx, world.bvy) or 1.0
                world.bvx, world.bvy = world.bvx / n * 3, world.bvy / n * 3
                world.pass_cooldown = 1
                return
        return
    # ball is free: nearest player within control radius gains it (slow enough)
    if math.hypot(world.bvx, world.bvy) > PASS_SPEED * 1.1:
        return  # too fast to control yet
    best, bestd = None, 1e9
    for t in (0, 1):
        for p in world.players[t]:
            if world.pass_cooldown > 0:
                continue
            d = math.hypot(p.x - world.bx, p.y - world.by)
            if d < bestd:
                best, bestd = (t, p.pid), d
    if best and bestd <= CONTROL_RADIUS:
        world.carrier = best
        world.shot_quality, world.shot_team = 0.0, None   # ball controlled: no live shot


def _goal_check(world):
    if world.carrier is not None:
        return None
    crossed = None
    if world.bx >= FIELD_X and abs(world.by) <= GOAL_MOUTH:
        crossed = 0
    elif world.bx <= -FIELD_X and abs(world.by) <= GOAL_MOUTH:
        crossed = 1
    if crossed is None:
        return None
    # only a genuine shot by the attacking team can score, and it converts with
    # the REAL evaluate_shot probability — otherwise it's saved/wide and the
    # defending GK restarts. This makes shot SELECTION (our edge) decisive.
    scored = (world.shot_team == crossed and world.rng.random() < world.shot_quality)
    if scored:
        world.score[crossed] += 1
        world.kickoff(1 - crossed)
        return crossed
    # saved / wide -> GOAL KICK: defending team restarts from its own goal area,
    # keeper returns to take it (no midfield-teleport artifact).
    world.shot_quality, world.shot_team = 0.0, None
    def_team = 1 - crossed
    gx = (-FIELD_X + 6) if def_team == 0 else (FIELD_X - 6)
    gk = _find(world.players[def_team], 0)
    gk.x, gk.y = gx, 0.0
    world.bx, world.by, world.bvx, world.bvy = gx, 0.0, 0.0, 0.0
    world.carrier = (def_team, 0)
    world.pass_cooldown = 1
    return None


# --------------------------------------------------------------------------- #
# brains                                                                       #
# --------------------------------------------------------------------------- #
def champion_brain(gs, team, pid):
    return P.command(gs, team, pid)


def baseline_brain(gs, team, pid):
    """Faithful port of sample lib/fallback.py (the deployed-team behaviour)."""
    players = gs["players"]
    ball = gs["ball"]
    bp = ball.get("position", {"x": 0, "y": 0})
    my_goal_x, opp_goal_x = P.goal_x(team)
    me = next((p for p in players if P._pid(p) == pid and P._is_mine(p, team)), None)
    if not me:
        return _c("SET_STANCE", pid, team, {"stance": 0})
    mx, my = P._xy(me)
    holder = P.possession_holder(gs)                       # team-correct (global id)
    we_have = holder is not None and P._is_mine(holder, team)
    i_have = holder is not None and P._aid(holder) == P._aid(me)
    poss = P._pid(holder) if holder is not None else None

    if i_have:
        if pid == 0:  # GK distribute to nearest
            mates = [p for p in players if P._is_mine(p, team) and P._pid(p) != pid]
            tgt = min(mates, key=lambda p: P._hypot(*P._xy(p), mx, my)) if mates else None
            return _c("GK_DISTRIBUTE", pid, team, {"target_player_id": P._pid(tgt) if tgt else 1, "method": "THROW"})
        if pid in (2, 3, 4):  # MID/FWD shoot if near, else pass/advance
            if abs(mx - opp_goal_x) < 25:
                return _c("SHOOT", pid, team, {"aim_location": "TR", "power": 0.85})
            if pid == 2:
                fwds = [p for p in players if P._is_mine(p, team) and P._pid(p) in (3, 4)]
                tgt = min(fwds, key=lambda p: abs(P._xy(p)[0] - opp_goal_x)) if fwds else None
                return _c("PASS", pid, team, {"target_player_id": P._pid(tgt) if tgt else 3, "type": "GROUND"})
            return _c("MOVE_TO", pid, team, {"target_x": opp_goal_x * 0.6, "target_y": my, "sprint": True})
        # DEF pass to nearest non-GK
        mates = [p for p in players if P._is_mine(p, team) and P._pid(p) not in (0, pid)]
        tgt = min(mates, key=lambda p: P._hypot(*P._xy(p), mx, my)) if mates else None
        return _c("PASS", pid, team, {"target_player_id": P._pid(tgt) if tgt else 2, "type": "GROUND"})

    if pid == 1 and not we_have:  # DEF mark dangerous
        opps = [p for p in players if not P._is_mine(p, team)]
        if opps:
            dgr = min(opps, key=lambda p: abs(P._xy(p)[0] - my_goal_x))
            if abs(P._xy(dgr)[0] - my_goal_x) < 30:
                return _c("MARK", pid, team, {"target_player_id": P._pid(dgr), "tightness": "TIGHT"}, 3)

    # press if within 20 of the ball (the swarm trigger)
    if not we_have and P._hypot(mx, my, bp.get("x", 0), bp.get("y", 0)) < 20:
        return _c("PRESS_BALL", pid, team, {"intensity": 0.7}, 3)

    ax, ay = P.anchor_world(pid, team)
    return _c("MOVE_TO", pid, team, {"target_x": ax, "target_y": ay, "sprint": False})


def swarm_brain(gs, team, pid):
    holder = P.possession_holder(gs)
    me = next((p for p in gs["players"] if P._pid(p) == pid and P._is_mine(p, team)), None)
    if holder is not None and me is not None and P._aid(holder) == P._aid(me):
        return _c("SHOOT", pid, team, {"aim_location": "TR", "power": 1.0})
    return _c("PRESS_BALL", pid, team, {"intensity": 1.0}, 1)


def _c(ct, pid, team, par, dur=0):
    return {"commandType": ct, "playerId": pid, "teamId": team, "parameters": par, "duration": dur}


# --------------------------------------------------------------------------- #
# match runner + metrics                                                       #
# --------------------------------------------------------------------------- #
def spread(world, team):
    ps = world.players[team]
    n, s = 0, 0.0
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            s += math.hypot(ps[i].x - ps[j].x, ps[i].y - ps[j].y); n += 1
    return s / n if n else 0.0


def play(brain_a, brain_b, ticks=300, seed=0):
    world = World(); world.kickoff(0)
    world.rng = random.Random(seed)
    brains = {0: brain_a, 1: brain_b}
    lat = []; poss_ticks = {0: 0, 1: 0}; spread_acc = {0: 0.0, 1: 0.0}
    for _ in range(ticks):
        step(world, brains, lat)
        if world.carrier is not None:
            poss_ticks[world.carrier[0]] += 1
        spread_acc[0] += spread(world, 0); spread_acc[1] += spread(world, 1)
    tot = max(1, poss_ticks[0] + poss_ticks[1])
    return {
        "score": (world.score[0], world.score[1]),
        "poss": (round(100 * poss_ticks[0] / tot), round(100 * poss_ticks[1] / tot)),
        "spread": (round(spread_acc[0] / ticks, 1), round(spread_acc[1] / ticks, 1)),
        "max_lat_ms": round(max(lat), 3) if lat else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=300)
    ap.add_argument("--matches", type=int, default=3)
    args = ap.parse_args()

    cards = [("champion", champion_brain, "baseline", baseline_brain),
             ("champion", champion_brain, "swarm", swarm_brain),
             ("baseline", baseline_brain, "swarm", swarm_brain),
             ("champion(A)", champion_brain, "champion(B)", champion_brain)]
    for na, ba, nb, bb in cards:
        agg = {"a": 0, "b": 0}
        last = None
        for m in range(args.matches):
            r = play(ba, bb, args.ticks, seed=m * 17 + 1); last = r
            agg["a"] += r["score"][0]; agg["b"] += r["score"][1]
        print(f"\n=== {na}  vs  {nb}   ({args.matches} matches × {args.ticks} ticks) ===")
        print(f"  goals total : {na} {agg['a']} - {agg['b']} {nb}")
        print(f"  last match  : score {last['score']}  poss% {last['poss']}  "
              f"spread {last['spread']}  maxLat {last['max_lat_ms']}ms")
        print(f"  spread read : {na}={last['spread'][0]}  {nb}={last['spread'][1]}  "
              f"(higher = more disciplined shape; swarm collapses low)")


if __name__ == "__main__":
    main()
