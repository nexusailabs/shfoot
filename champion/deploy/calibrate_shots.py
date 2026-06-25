#!/usr/bin/env python3
"""
Shot-model calibrator for the Agentic Football Cup champion policy.

GOAL: replace the ESTIMATES in policy_v2.py
  * GOAL_HALF_WIDTH        = 1.0   (goal-mouth half-width on the depth/z axis)
  * SHOOT_MIN_PROB         = 0.42  (model-prob gate)
  * SHOT_REAL_CHANCE_DIST  = 0.43  (fraction of FIELD_X; distance gate)
with values FITTED from REAL shot outcomes.

INPUT — decoded ticks (preferred). A JSON file: a list of per-tick snapshots.
The CANONICAL schema this tool consumes:
  {
    "t":   <gameTime secs, float>,                 # GAME CLOCK (aligns with the
                                                   #   API goals[].game_time_secs)
    "ball": {"x": <f>, "z": <f>, "h": <f optional>,   # field plane = (x, z); h = height
             "vx": <f optional>, "vz": <f optional>}, # velocity (optional; derived if absent)
    "players": [{"pid": <int>, "team": <0|1>, "x": <f>, "z": <f>}, ...],
    "poss":      <pid or null>,                    # possession-holder player id, if any
    "poss_team": <0|1 or null>                     # team in possession, if any
  }
This is exactly the per-tick FCTICK record, normalized. The loader is TOLERANT of
the raw live contract too (so the FCTICK->ticks shim is near-trivial):
  * nested "position": ball/players may be {"position": {...}} — unwrapped.
  * depth axis: ball depth = position.z (position.y is HEIGHT); players are 2D so
    their depth = position.y. The loader takes z if present else y (== policy_v2
    _field_xy), so live {x,y} players and {x,y,z} ball both work.
  * ids: "pid" or live "agentId"/"playerId" (trailing int) via policy_v2._pid.
  * team: 0/1, or live "teamCode" home/away, or "teamId".
  * possession: explicit poss/poss_team, OR a {"possession": {pid, team}} block,
    OR ball.possessionAgentId/possessionTeam (resolved like possession_holder).
Geometry (verified, policy_v2): goal line at x = +/-6.4; opp goal for team 0 is
x=+6.4, for team 1 is x=-6.4. Field depth (z) in ~[-3.5, 3.6]; goal mouth is |z|.

SHOT events: a tick may instead carry an explicit FCTICK SHOOT marker
  {"shoot": {"pid", "pos": {"x","z"}, "aim", "power"}}  (or a top-level "shots"
list per tick). Detection works from possession+ball-motion alone, so the marker
is optional — but if present it disambiguates the shooter on contested frames.

Alternatively pass a pre-extracted shot list with --shots (see SHOT schema below)
to skip detection.

WHAT IT DOES
  1. Detect SHOT events: the ball leaving a possessing player and moving toward
     that team's opponent goal above a speed floor.
  2. Track the ball forward to the goal line (x = +/-6.4); record the crossing z.
  3. Label GOAL when the ball crosses the line into the net (continues past the
     line untouched by a keeper); else SAVE/MISS.
  4. FIT:
       - GOAL_HALF_WIDTH       : the |z| boundary that best separates goals from
                                 non-goals at the goal line (1-D decision stump).
       - SHOOT_MIN_PROB /       : the (prob, dist) gates that maximize conversion
         SHOT_REAL_CHANCE_DIST    (goals / shots) while retaining shot volume.
  5. Print the recommended constant values.

The model probability for each shot is computed with the SAME evaluate_shot()
the live policy uses (imported from policy_v2) so the fitted gates are on-contract.

Pure stdlib. With no input file it generates a synthetic, ground-truthed sample
and calibrates against it (a self-test of the whole pipeline).

Usage:
  python3 champion/deploy/calibrate_shots.py                      # synthetic self-test
  python3 champion/deploy/calibrate_shots.py --ticks ticks.json   # real decoded ticks
  python3 champion/deploy/calibrate_shots.py --shots shots.json   # pre-extracted shots
  python3 champion/deploy/calibrate_shots.py --emit-synthetic s.json  # write a sample
"""
import argparse
import json
import math
import os
import sys

# Reuse the live shot model + geometry (one source of truth). champion/ is the
# parent of this deploy/ dir; policy_v2.py lives there and is pure stdlib.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import policy_v2 as P  # noqa: E402

GOAL_X = P.GOAL_AWAY_X            # 6.4
FIELD_X = P.FIELD_X               # 6.4
FIELD_Z = P.FIELD_Z              # 3.5
SHOT_SPEED_FLOOR = 0.06          # min ball units/tick to count as a struck shot
NET_DEPTH = 0.6                  # how far past the line the ball travels into the net

# SHOT schema (what detection yields / what --shots accepts), one per dict:
#   {"team": 0|1, "sx": <shooter x>, "sz": <shooter z>, "opp_goal_x": +/-6.4,
#    "gk_xy": [x, z] or null, "blockers": [[x, z], ...],
#    "z_cross": <ball z at the goal line, or null if it never reached>,
#    "reached_line": bool, "keeper_touch": bool, "goal": bool}


# --------------------------------------------------------------------------- #
# Normalization — accept the canonical schema OR the raw live/FCTICK contract
# --------------------------------------------------------------------------- #
def _team01(entity):
    """Normalize a team tag to 0 (home) / 1 (away)."""
    if "team" in entity and entity["team"] in (0, 1, "0", "1"):
        return int(entity["team"])
    tc = entity.get("teamCode")
    if tc is not None:
        return 0 if str(tc).lower() in ("home", "0") else 1
    tid = entity.get("teamId")
    return 0 if str(tid) in ("0", "home") else 1


def _depth(pos):
    """Field-depth coordinate (== policy_v2._field_xy): z if present (the live 3D
    ball), else y (2D players, where position.y IS the depth)."""
    return float(pos.get("z", pos.get("y", 0.0)))


def normalize_ticks(ticks):
    """Map each tick (canonical OR raw live/FCTICK) to the internal form the
    detector uses: ball{x,z}, players[{pid,team,x,z}], poss, poss_team, t."""
    out = []
    for tk in ticks:
        b = tk.get("ball", {}) or {}
        bpos = b.get("position", b)
        nb = {"x": float(bpos.get("x", 0.0)), "z": _depth(bpos)}
        if "y" in bpos and "z" in bpos:
            nb["h"] = float(bpos["y"])
        nps = []
        for p in tk.get("players", []) or []:
            ppos = p.get("position", p)
            nps.append({"pid": P._pid(p) if ("agentId" in p or "playerId" in p) else p.get("pid", 0),
                        "team": _team01(p),
                        "x": float(ppos.get("x", 0.0)), "z": _depth(ppos)})
        # possession: explicit -> {possession:{pid,team}} -> ball.possession*
        poss, poss_team = tk.get("poss"), tk.get("poss_team")
        if poss is None and isinstance(tk.get("possession"), dict):
            poss = tk["possession"].get("pid")
            poss_team = tk["possession"].get("team", poss_team)
        if poss is None and b.get("possessionAgentId") is not None:
            try:
                poss = int(str(b["possessionAgentId"]).rsplit("_", 1)[-1])
            except (ValueError, IndexError):
                poss = None
        if poss_team is None and b.get("possessionTeam") is not None:
            pt = b["possessionTeam"]
            poss_team = 0 if str(pt).lower() in ("home", "0") else 1
        out.append({"t": float(tk.get("t", tk.get("gameTime", 0.0))),
                    "ball": nb, "players": nps, "poss": poss, "poss_team": poss_team})
    return out


# --------------------------------------------------------------------------- #
# Shot detection from decoded ticks
# --------------------------------------------------------------------------- #
def _opp_goal_x(team):
    return GOAL_X if team == 0 else -GOAL_X


def _vel(a, b, dt):
    if dt <= 0:
        return 0.0, 0.0
    return (b["x"] - a["x"]) / dt, (b["z"] - a["z"]) / dt


def detect_shots(ticks, goal_times=None):
    """Walk the tick stream; emit a SHOT each time the ball is released by a
    possessing player and travels toward that team's opp goal above the speed
    floor. Track each shot forward to the goal line and label the outcome.

    GOAL labeling uses goal_times (seconds) from the API match record when given
    — a shot is a GOAL if a goal occurred within GOAL_MATCH_WINDOW after launch.
    This is the ground-truth signal (same source tick_decode uses); it is far
    more reliable than guessing from geometry. Without goal_times we fall back to
    a reset heuristic (ball returns to center untouched after crossing)."""
    shots = []
    ticks = normalize_ticks(ticks)
    goal_times = sorted(goal_times) if goal_times else None
    n = len(ticks)
    i = 1
    while i < n - 1:
        prev, cur = ticks[i - 1], ticks[i]
        dt = max(1e-6, cur["t"] - prev["t"])
        vx, vz = _vel(prev["ball"], cur["ball"], dt)
        speed = math.hypot(vx, vz) * dt  # units/tick
        # A shot needs a team that HAD the ball on the previous tick.
        shooter_team = prev.get("poss_team")
        released = cur.get("poss") is None or cur.get("poss_team") != shooter_team
        if shooter_team is None or not released or speed < SHOT_SPEED_FLOOR:
            i += 1
            continue
        gx = _opp_goal_x(shooter_team)
        toward = (gx - prev["ball"]["x"]) * (1 if gx > 0 else -1) > 0 and (vx * (1 if gx > 0 else -1)) > 0
        if not toward:
            i += 1
            continue
        shot = _track_shot(ticks, i, shooter_team, prev, goal_times)
        shots.append(shot)
        # Skip past the resolved trajectory so one shot isn't double-counted.
        i = shot["_end_idx"] + 1
    if goal_times is not None:
        _assign_goals(shots, goal_times)
    return shots


GOAL_MATCH_WINDOW = 1.2   # secs: max |crossing_t - goal_time| to bind a goal to a shot


def _assign_goals(shots, goal_times):
    """One-to-one bind each API goal_time to the single shot whose ball reached
    the goal line nearest that time (greedy by |dt|, within GOAL_MATCH_WINDOW).
    Prevents a clustered save/miss from stealing a neighbour shot's goal."""
    for s in shots:
        s["goal"] = False
    used = set()
    for gt in goal_times:
        best, best_dt = None, GOAL_MATCH_WINDOW
        for idx, s in enumerate(shots):
            if idx in used or not s.get("reached_line") or s.get("crossing_t") is None:
                continue
            d = abs(s["crossing_t"] - gt)
            if d <= best_dt:
                best, best_dt = idx, d
        if best is not None:
            shots[best]["goal"] = True
            used.add(best)


def _track_shot(ticks, start_idx, team, launch_tick, goal_times):
    """Follow the ball from start_idx to the goal line (x=opp_goal_x). Record the
    crossing z, whether a keeper touched it, and label GOAL/SAVE/MISS."""
    gx = _opp_goal_x(team)
    launch_t = launch_tick["t"]
    sign = 1 if gx > 0 else -1
    # Shooter geometry at launch (for the model-prob features).
    holder = None
    for p in launch_tick.get("players", []):
        if p["pid"] == launch_tick.get("poss") and p["team"] == team:
            holder = p
            break
    sx = holder["x"] if holder else launch_tick["ball"]["x"]
    sz = holder["z"] if holder else launch_tick["ball"]["z"]
    gk_xy, blockers = _defenders(launch_tick, team)

    z_cross, reached, keeper_touch, goal = None, False, False, False
    n = len(ticks)
    j = start_idx
    end = start_idx
    while j < n:
        b = ticks[j]["ball"]
        end = j
        # keeper contact: opp GK within a small radius of the ball before the line
        for p in ticks[j].get("players", []):
            if p["team"] != team and abs(p["x"] - gx) <= 1.2:  # near own goal => keeper-ish
                if math.hypot(p["x"] - b["x"], p["z"] - b["z"]) < 0.45:
                    keeper_touch = True
        # crossing the goal plane?
        if (b["x"] - gx) * sign >= 0:
            prev_b = ticks[j - 1]["ball"] if j > start_idx else launch_tick["ball"]
            z_cross = _interp_z(prev_b, b, gx)
            reached = True
            break
        # ball stopped / regained by a defender => save/miss; stop tracking
        if j > start_idx:
            dt = max(1e-6, ticks[j]["t"] - ticks[j - 1]["t"])
            vx, vz = _vel(ticks[j - 1]["ball"], b, dt)
            if math.hypot(vx, vz) * dt < SHOT_SPEED_FLOOR * 0.5:
                break
            if ticks[j].get("poss_team") == team and j > start_idx + 1:
                # ball back under attacker control beyond a rebound; treat as ended
                break
        j += 1

    # --- GOAL label ---
    crossing_t = ticks[end]["t"] if reached else None
    if goal_times is not None:
        goal = False   # bound later, one-to-one, by _assign_goals
    else:
        # fallback heuristic (no API goal times): crossed untouched, then the ball
        # resets to ~center (a kickoff after a scored goal).
        reset = False
        for k in range(end + 1, min(len(ticks), end + 6)):
            rb = ticks[k]["ball"]
            if math.hypot(rb["x"], rb["z"]) < 0.5:
                reset = True
                break
        goal = reached and (not keeper_touch) and reset

    prob = P.evaluate_shot(sx, sz, gk_xy, gx, blockers)["prob"]
    dist = math.hypot(sx - gx, sz)
    return {
        "team": team, "sx": round(sx, 3), "sz": round(sz, 3), "opp_goal_x": gx,
        "gk_xy": [round(gk_xy[0], 3), round(gk_xy[1], 3)] if gk_xy else None,
        "blockers": [[round(bx, 3), round(bz, 3)] for bx, bz in blockers],
        "z_cross": round(z_cross, 3) if z_cross is not None else None,
        "reached_line": reached, "keeper_touch": keeper_touch, "goal": bool(goal),
        "crossing_t": crossing_t, "prob": prob, "dist": round(dist, 3), "_end_idx": end,
    }


def _interp_z(a, b, gx):
    """Linear z at the moment ball x == gx, between ball positions a -> b."""
    dx = b["x"] - a["x"]
    if abs(dx) < 1e-9:
        return b["z"]
    f = (gx - a["x"]) / dx
    f = max(0.0, min(1.0, f))
    return a["z"] + f * (b["z"] - a["z"])


def _defenders(tick, team):
    """Opp keeper (the opp player nearest their own goal line) + opp outfielders
    within a blocking band as blockers, in the evaluate_shot contract."""
    gx = _opp_goal_x(team)
    opp = [p for p in tick.get("players", []) if p["team"] != team]
    if not opp:
        return None, []
    gk = min(opp, key=lambda p: abs(p["x"] - gx))
    gk_xy = (gk["x"], gk["z"])
    blockers = [(p["x"], p["z"]) for p in opp if p is not gk]
    return gk_xy, blockers


# --------------------------------------------------------------------------- #
# Fitting
# --------------------------------------------------------------------------- #
def fit_goal_half_width(shots):
    """The goal-mouth half-width = the |z_cross| boundary that best separates
    goals from non-goals at the goal line. A 1-D decision stump: pick w that
    maximizes (goals with |z|<=w) + (non-goals with |z|>w).

    The mouth is a GEOMETRIC property of the goal frame, so it must be fit from
    balls the keeper did NOT touch — a keeper save at small |z| is not a post
    miss and would pull the boundary in. Untouched balls go in iff |z|<=mouth."""
    crossed = [s for s in shots if s.get("z_cross") is not None and s.get("reached_line")]
    untouched = [s for s in crossed if not s.get("keeper_touch")]
    if untouched:
        crossed = untouched
    if not crossed:
        return None, 0, 0.0
    az = sorted(abs(s["z_cross"]) for s in crossed)
    # candidate boundaries: midpoints between sorted |z| values + the extremes
    cands = []
    for a, b in zip(az, az[1:]):
        cands.append((a + b) / 2.0)
    cands += [az[0] * 0.9, az[-1] * 1.1]
    goals = [abs(s["z_cross"]) for s in crossed if s["goal"]]
    nong = [abs(s["z_cross"]) for s in crossed if not s["goal"]]
    best_w, best_acc = None, -1.0
    for w in cands:
        correct = sum(1 for z in goals if z <= w) + sum(1 for z in nong if z > w)
        acc = correct / len(crossed)
        if acc > best_acc:
            best_acc, best_w = acc, w
    # If there are essentially no wide misses to bound the post, fall back to the
    # widest |z| that still scored (the mouth is at least that wide).
    if not nong and goals:
        best_w = max(goals)
    return best_w, len(crossed), best_acc


RETAIN_FRAC = 0.70   # a useful SHOOT gate must keep >= this share of real goals

def fit_gates(shots):
    """Sweep SHOT_REAL_CHANCE_DIST (frac of FIELD_X) x SHOOT_MIN_PROB. For each
    combo, among shots that PASS both gates, compute conversion = goals/shots and
    goals retained. Recommend the gate that MAXIMIZES conversion (best finishing)
    while still retaining >= RETAIN_FRAC of all real goals — i.e. cut the weak,
    low-yield shots without throwing away real chances. Falls back to the highest
    conversion*sqrt(goals) if no combo clears the retention bar."""
    shots = [s for s in shots if "prob" in s and "dist" in s and "goal" in s]
    if not shots:
        return None
    total_goals = sum(1 for s in shots if s["goal"])
    dist_grid = [round(0.25 + 0.03 * k, 3) for k in range(0, 14)]   # 0.25..0.64
    prob_grid = [round(0.25 + 0.03 * k, 2) for k in range(0, 14)]   # 0.25..0.64
    rows = []
    for dfrac in dist_grid:
        dlim = FIELD_X * dfrac
        for pmin in prob_grid:
            passed = [s for s in shots if s["dist"] <= dlim and s["prob"] >= pmin]
            if not passed:
                continue
            g = sum(1 for s in passed if s["goal"])
            conv = g / len(passed)
            rows.append({"dist_frac": dfrac, "min_prob": pmin, "shots": len(passed),
                         "goals": g, "conversion": round(conv, 3),
                         "goal_retain": round(g / total_goals, 3) if total_goals else 0.0,
                         "score": round(conv * math.sqrt(g), 4)})
    if not rows:
        return None
    eligible = [r for r in rows if r["goal_retain"] >= RETAIN_FRAC and r["shots"] >= 5]
    if eligible:
        # highest conversion; tie-break toward more goals retained
        eligible.sort(key=lambda r: (r["conversion"], r["goals"]), reverse=True)
        best = eligible[0]
        top = eligible[:8]
    else:
        rows.sort(key=lambda r: r["score"], reverse=True)
        best = rows[0]
        top = rows[:8]
    base_conv = total_goals / len(shots) if shots else 0.0
    return {"best": best, "baseline_conversion": round(base_conv, 3),
            "total_shots": len(shots), "total_goals": total_goals,
            "retain_frac": RETAIN_FRAC, "top": top}


# --------------------------------------------------------------------------- #
# Synthetic sample (ground-truthed) — pipeline self-test when no real capture
# --------------------------------------------------------------------------- #
def _rng(seed):
    s = seed & 0xFFFFFFFF

    def nxt():
        nonlocal s
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        return s / 0x7FFFFFFF
    return nxt


def make_synthetic_ticks(n_shots=80, true_mouth=0.75, seed=7):
    """Generate a tick stream with n_shots scripted shots and three honest
    outcomes:
      * GOAL : keeper missed AND |z_cross| < true_mouth -> ball into the net,
               then a kickoff reset to center; a goal_time is recorded.
      * SAVE : keeper on the ball's line -> ball stops at the keeper.
      * WIDE : keeper missed but |z_cross| >= true_mouth -> ball flies PAST the
               line at a large |z| (off frame); restart is a goal kick near goal.
    Returns (ticks, goal_times, expected_constants). The fitter must recover
    true_mouth from the GOAL/WIDE crossing-z split among keeper-untouched shots."""
    rnd = _rng(seed)
    ticks = []
    goal_times = []
    t = 0.0
    dt = 1.0 / 30.0
    gk_pid = {0: 10, 1: 0}  # opp keeper pid, by attacking team
    sign = 1
    for k in range(n_shots):
        team = 0  # all shots by team 0 toward +x for simplicity
        gx = _opp_goal_x(team)
        sd = 1.0 + rnd() * 3.5                 # shot distance 1.0..4.5
        sx = gx - sd
        sz = (rnd() - 0.5) * 4.0
        # crossing-z scatters WIDER on longer shots -> far shots miss more often
        # (gives the gate fitter a real distance->conversion signal to find).
        scatter = 0.5 + 1.8 * (sd / 4.5)
        z_cross = sz * (0.3 + 0.4 * rnd()) + (rnd() - 0.5) * scatter
        keeper_z = (rnd() - 0.5) * 2.0
        keeper_touch = abs(keeper_z - z_cross) < 0.35 and rnd() < 0.85
        scored = (not keeper_touch) and abs(z_cross) < true_mouth

        def row(bx, bz, poss=None, pteam=None):
            return {"t": round(t, 4),
                    "ball": {"x": round(bx, 3), "z": round(bz, 3)},
                    "players": [
                        {"pid": 100 + team, "team": team, "x": round(sx, 3), "z": round(sz, 3)},
                        {"pid": gk_pid[team], "team": 1 - team, "x": round(gx, 3), "z": round(keeper_z, 3)},
                    ],
                    "poss": poss, "poss_team": pteam}

        steps = 8
        for s in range(steps):
            f = s / (steps - 1)
            if s == 0:
                ticks.append(row(sx, sz, poss=100 + team, pteam=team)); t += dt
            else:
                ticks.append(row(sx + (gx - sx) * f, sz + (z_cross - sz) * f)); t += dt
        if keeper_touch:
            ticks.append(row(gx, keeper_z)); t += dt                 # ball dies at keeper
            ticks.append(row(gx * 0.85, keeper_z * 0.5)); t += dt    # GK restart near goal
        elif scored:
            ticks.append(row(gx + NET_DEPTH * sign, z_cross)); t += dt  # into the net
            goal_times.append(round(t, 4))
            ticks.append(row(0.0, 0.0)); t += dt                       # kickoff reset
        else:  # wide miss: flies past the line at a large |z|, goal-kick restart
            ticks.append(row(gx + NET_DEPTH * sign, z_cross)); t += dt
            ticks.append(row(gx * 0.85, 0.0)); t += dt
    return ticks, goal_times, {"true_mouth": true_mouth}


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def report(shots, expected=None):
    print(f"\n=== shot calibration ===")
    print(f"  detected shots      : {len(shots)}")
    reached = [s for s in shots if s.get("reached_line")]
    goals = [s for s in shots if s.get("goal")]
    print(f"  reached goal line   : {len(reached)}")
    print(f"  goals               : {len(goals)}")

    w, n_cross, acc = fit_goal_half_width(shots)
    print(f"\n  -- GOAL_HALF_WIDTH fit (from goal-line crossing |z|) --")
    if w is None:
        print("     insufficient crossings; need decoded ticks with ball reaching the line")
    else:
        print(f"     recommended GOAL_HALF_WIDTH = {w:.3f}  "
              f"(from {n_cross} crossings, separation acc={acc:.2f})")
        if expected and expected.get("true_mouth"):
            print(f"     [synthetic ground truth mouth = {expected['true_mouth']:.3f}]")

    g = fit_gates(shots)
    print(f"\n  -- SHOOT gate fit (maximize conversion x volume) --")
    if not g:
        print("     insufficient labeled shots")
    else:
        b = g["best"]
        print(f"     baseline conversion (all shots) = {g['baseline_conversion']:.3f} "
              f"({g['total_goals']}/{g['total_shots']})")
        print(f"     recommended SHOT_REAL_CHANCE_DIST = {b['dist_frac']}  "
              f"(= {b['dist_frac']*FIELD_X:.2f} units)")
        print(f"     recommended SHOOT_MIN_PROB        = {b['min_prob']}")
        print(f"     -> conversion {b['conversion']:.3f} on {b['goals']}/{b['shots']} "
              f"shots passing the gate (retains {b['goal_retain']*100:.0f}% of real goals)")
        print(f"\n     top candidate gates (>= {int(g['retain_frac']*100)}% goal retention):")
        print(f"     {'dist_frac':>9} {'min_prob':>8} {'shots':>6} {'goals':>6} {'conv':>6} {'retain':>7}")
        for r in g["top"]:
            print(f"     {r['dist_frac']:>9} {r['min_prob']:>8} {r['shots']:>6} "
                  f"{r['goals']:>6} {r['conversion']:>6.3f} {r['goal_retain']:>7.2f}")

    print(f"\n  NOTE: these are PROPOSED values. Do not edit policy_v2.py until they")
    print(f"        come from REAL decoded ticks (>= ~30 goal-line crossings for a")
    print(f"        stable GOAL_HALF_WIDTH). Synthetic mode validates the pipeline only.")
    return {"goal_half_width": w, "gates": g}


def main():
    ap = argparse.ArgumentParser(description="Calibrate the shot model from real shot outcomes")
    ap.add_argument("--ticks", help="decoded ticks JSON (list of per-tick snapshots)")
    ap.add_argument("--shots", help="pre-extracted shot list JSON")
    ap.add_argument("--goals", help="goal times: a JSON list of seconds, OR a capture "
                    ".meta.json (goals[].game_time_secs are read out)")
    ap.add_argument("--emit-synthetic", help="write a synthetic ticks sample to this path and exit")
    ap.add_argument("--n-shots", type=int, default=80)
    args = ap.parse_args()

    if args.emit_synthetic:
        ticks, goal_times, _ = make_synthetic_ticks(args.n_shots)
        with open(args.emit_synthetic, "w") as f:
            json.dump(ticks, f)
        gp = os.path.splitext(args.emit_synthetic)[0] + ".goals.json"
        with open(gp, "w") as f:
            json.dump(goal_times, f)
        print(f"wrote {len(ticks)} synthetic ticks -> {args.emit_synthetic}")
        print(f"wrote {len(goal_times)} goal times  -> {gp}")
        return

    expected = None
    if args.shots:
        with open(args.shots) as f:
            shots = json.load(f)
        print(f"loaded {len(shots)} pre-extracted shots from {args.shots}")
    elif args.ticks:
        with open(args.ticks) as f:
            ticks = json.load(f)
        goal_times = _load_goal_times(args.goals, args.ticks)
        print(f"loaded {len(ticks)} ticks from {args.ticks} "
              f"({len(goal_times) if goal_times else 0} goal times)")
        shots = detect_shots(ticks, goal_times)
    else:
        print("no --ticks/--shots given: running synthetic self-test")
        ticks, goal_times, expected = make_synthetic_ticks(args.n_shots)
        shots = detect_shots(ticks, goal_times)

    report(shots, expected)


def _load_goal_times(goals_arg, ticks_path):
    """Resolve goal times from --goals (a list, or a .meta.json with goals[]) or,
    if absent, an auto-discovered sidecar next to the ticks file. Returns a list
    of seconds or None (None => detector uses its reset heuristic)."""
    path = goals_arg
    if path is None:
        for cand in (os.path.splitext(ticks_path)[0] + ".goals.json",
                     os.path.splitext(ticks_path)[0] + ".meta.json"):
            if os.path.exists(cand):
                path = cand
                break
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list) and (not data or isinstance(data[0], (int, float))):
        return list(data)
    goals = data.get("goals") if isinstance(data, dict) else None
    if not goals:
        return None
    out = []
    for g in goals:
        gt = g.get("game_time_secs") if isinstance(g, dict) else None
        if gt is not None:
            out.append(float(gt))
    return out or None


if __name__ == "__main__":
    main()
