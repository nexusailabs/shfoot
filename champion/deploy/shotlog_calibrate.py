#!/usr/bin/env python3
"""
On-agent SHOOT-log calibrator — the PRAGMATIC shot-calibration path that needs
NO WSS binary decode, only:
  (a) FCSHOT logs pulled from CloudWatch (enable the logger in build_deploy.py),
  (b) each match's API record (game_stats.goals[].game_time_secs), already pulled
      by run_match.py.

It labels each logged SHOOT as a GOAL when one of OUR goals fired soon after it
(matched on the game clock, one-to-one per match), then fits the SHOOT gates
(SHOT_REAL_CHANCE_DIST / SHOOT_MIN_PROB) by reusing calibrate_shots.fit_gates so
both paths share one fitter.

WHAT THIS PATH CAN AND CANNOT FIT
  * CAN  : SHOOT_MIN_PROB, SHOT_REAL_CHANCE_DIST — the FCSHOT log carries shooter
           (sx,sz), opp_goal_x and the keeper (gk) position, so the exact live
           model prob (evaluate_shot) and distance are reconstructable.
  * CANNOT: GOAL_HALF_WIDTH — that needs the ball's z as it CROSSES the goal line,
           which only the tick capture (calibrate_shots --ticks) provides. FCSHOT
           logs the shot ORIGIN, not the crossing. Keep GOAL_HALF_WIDTH on the
           WSS-decode path; use this path for the gates.

FCSHOT log line (emitted by the build_deploy.py logger):
  FCSHOT {"pid","team","sx","sz","opp_goal_x","gk":[x,z],"aim","power",
          "our_score","opp_score","gameTime"}
A CloudWatch prefix before "FCSHOT" is tolerated (we slice from the token).

INPUTS
  --pairs manifest.json   : [{"match_id","log":<path>,"record":<path>}, ...]
  --logs-dir D --matches-dir D : auto-pair *<match_id>*.log <-> *<match_id>*.json
  (no input)              : synthetic demo (self-test of the whole correlation)

Usage:
  python3 champion/deploy/shotlog_calibrate.py                       # synthetic demo
  python3 champion/deploy/shotlog_calibrate.py --pairs pairs.json
  python3 champion/deploy/shotlog_calibrate.py --logs-dir logs --matches-dir recs
"""
import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))           # deploy/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # champion/
import policy_v2 as P            # noqa: E402
import calibrate_shots as C      # noqa: E402

GOAL_CLOCK_WINDOW = 5.0          # secs of game-clock: goal_time - shot_time must be in [0, this]
OUR_TEAM_NAME = "NEXUS AI LABS"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def parse_fcshot_log(path):
    """Extract FCSHOT json objects from a log file (CloudWatch dump or raw)."""
    out = []
    with open(path) as f:
        for line in f:
            k = line.find("FCSHOT ")
            if k < 0:
                continue
            frag = line[k + len("FCSHOT "):].strip()
            try:
                out.append(json.loads(frag))
            except json.JSONDecodeError:
                # tolerate a trailing CloudWatch field after the json
                try:
                    out.append(json.loads(frag[:frag.rindex("}") + 1]))
                except Exception:
                    pass
    return out


def _our_side(record):
    """'home' or 'away' for our team, from the record's team names."""
    if record.get("home_team_name") == OUR_TEAM_NAME:
        return "home"
    if record.get("away_team_name") == OUR_TEAM_NAME:
        return "away"
    # fall back to team_id if present
    tid = record.get("team_id") or P.__dict__.get("TEAM_ID")
    if record.get("home_team_id") == tid:
        return "home"
    if record.get("away_team_id") == tid:
        return "away"
    return None


def our_goal_times(record):
    """game_time_secs of OUR goals from a match record. Tolerant to where the
    goals list lives and how each entry tags its team."""
    gs = record.get("game_stats") or {}
    goals = gs.get("goals") or record.get("goals") or []
    side = _our_side(record)
    out = []
    for g in goals:
        if not isinstance(g, dict):
            continue
        gt = g.get("game_time_secs", g.get("gameTime"))
        if gt is None:
            continue
        team = (g.get("team") or g.get("teamCode") or g.get("side")
                or g.get("scoring_team") or g.get("team_id"))
        if side is not None and team is not None:
            t = str(team).lower()
            if t in ("home", "away") and t != side:
                continue
            if t not in ("home", "away") and str(team) != str(record.get(f"{side}_team_id")):
                continue
        out.append(float(gt))
    return out, side


# --------------------------------------------------------------------------- #
# Label + featurize
# --------------------------------------------------------------------------- #
def label_match(fcshots, goal_times):
    """One-to-one bind each our-goal time to the FCSHOT it most plausibly came
    from (nearest shot at-or-before the goal, within GOAL_CLOCK_WINDOW)."""
    shots = sorted([s for s in fcshots if s.get("gameTime") is not None],
                   key=lambda s: s["gameTime"])
    for s in shots:
        s["_goal"] = False
    used = set()
    for gt in sorted(goal_times):
        best, best_d = None, None
        for i, s in enumerate(shots):
            if i in used:
                continue
            d = gt - s["gameTime"]
            if 0 <= d <= GOAL_CLOCK_WINDOW and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is not None:
            shots[best]["_goal"] = True
            used.add(best)
    return shots


def to_calib_shot(s):
    """FCSHOT record -> the shot schema calibrate_shots.fit_gates expects."""
    sx, sz = s.get("sx"), s.get("sz")
    gx = s.get("opp_goal_x")
    if sx is None or sz is None or gx is None:
        return None
    gk = s.get("gk")
    gk_xy = (gk[0], gk[1]) if gk else None
    prob = P.evaluate_shot(sx, sz, gk_xy, gx, [])["prob"]
    dist = math.hypot(sx - gx, sz)
    return {"team": s.get("team"), "sx": sx, "sz": sz, "opp_goal_x": gx,
            "gk_xy": list(gk_xy) if gk_xy else None, "blockers": [],
            "prob": prob, "dist": round(dist, 3), "goal": bool(s.get("_goal"))}


# --------------------------------------------------------------------------- #
# Pairing inputs
# --------------------------------------------------------------------------- #
def _match_id_in(name):
    m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F-]{8,})", name)
    if m:
        return m.group(1)
    m = re.search(r"([0-9a-zA-Z]{6,})", os.path.splitext(os.path.basename(name))[0])
    return m.group(1) if m else name


def pairs_from_dirs(logs_dir, matches_dir):
    logs = {}
    for fn in os.listdir(logs_dir):
        if fn.endswith((".log", ".txt", ".json")) and "fcshot" in fn.lower():
            logs[_match_id_in(fn)] = os.path.join(logs_dir, fn)
    recs = {}
    for fn in os.listdir(matches_dir):
        if fn.endswith(".json"):
            recs[_match_id_in(fn)] = os.path.join(matches_dir, fn)
    out = []
    for mid, lp in logs.items():
        if mid in recs:
            out.append({"match_id": mid, "log": lp, "record": recs[mid]})
    return out


# --------------------------------------------------------------------------- #
# Synthetic demo
# --------------------------------------------------------------------------- #
def make_synthetic(n_matches=6, shots_per=14, seed=11):
    """Build FCSHOT lists + match records with a ground-truth conversion that
    decays with distance, so the demo proves the correlation + fit recover a
    sensible distance gate. Returns a list of (fcshots, record) pairs."""
    rnd = C._rng(seed)
    pairs = []
    gx = P.GOAL_AWAY_X
    for m in range(n_matches):
        fcshots, goals = [], []
        clock = 5.0
        for _ in range(shots_per):
            clock += 8 + rnd() * 20
            sd = 0.8 + rnd() * 4.5
            sx = gx - sd
            sz = (rnd() - 0.5) * 3.5
            gk = [round(gx - 0.2, 3), round((rnd() - 0.5) * 1.5, 3)]
            # ground truth: closer + more central scores more
            p_goal = max(0.05, 0.85 - 0.16 * sd - 0.12 * abs(sz))
            scored = rnd() < p_goal
            fcshots.append({"pid": 3, "team": 0, "sx": round(sx, 3), "sz": round(sz, 3),
                            "opp_goal_x": gx, "gk": gk, "aim": "TR", "power": 0.8,
                            "our_score": 0, "opp_score": 0, "gameTime": round(clock, 2)})
            if scored:
                goals.append(round(clock + 1.0 + rnd(), 2))
        record = {"MatchId": f"synthetic-{m}", "home_team_name": OUR_TEAM_NAME,
                  "away_team_name": "BENCHMARK",
                  "game_stats": {"goals": [{"game_time_secs": g, "team": "home"} for g in goals]}}
        pairs.append((fcshots, record))
    return pairs


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def run(pairs, label):
    all_shots = []
    used_goals = matched = 0
    for fcshots, record in pairs:
        gtimes, side = our_goal_times(record)
        used_goals += len(gtimes)
        labeled = label_match(fcshots, gtimes)
        matched += sum(1 for s in labeled if s.get("_goal"))
        for s in labeled:
            cs = to_calib_shot(s)
            if cs:
                all_shots.append(cs)
    print(f"\n=== shotlog calibration ({label}) ===")
    print(f"  matches            : {len(pairs)}")
    print(f"  FCSHOT shots       : {len(all_shots)}")
    print(f"  our goals in records: {used_goals}  (bound to a logged shot: {matched})")
    if used_goals and matched < used_goals:
        print(f"  NOTE: {used_goals - matched} goal(s) had no logged SHOOT within "
              f"{GOAL_CLOCK_WINDOW:.0f}s before them (own-goal, deflection, rebound, or "
              f"the logger was off that tick).")

    g = C.fit_gates(all_shots)
    if not g:
        print("\n  -- SHOOT gate fit --")
        print("     insufficient labeled shots (need more matches with the logger on)")
        return
    print(f"\n  -- SHOOT gate fit (maximize conversion, keep >= "
          f"{int(g['retain_frac']*100)}% of goals) --")
    b = g["best"]
    print(f"     baseline conversion (all shots) = {g['baseline_conversion']:.3f} "
          f"({g['total_goals']}/{g['total_shots']})")
    print(f"     recommended SHOT_REAL_CHANCE_DIST = {b['dist_frac']}  "
          f"(= {b['dist_frac']*C.FIELD_X:.2f} units)")
    print(f"     recommended SHOOT_MIN_PROB        = {b['min_prob']}")
    print(f"     -> conversion {b['conversion']:.3f} on {b['goals']}/{b['shots']} shots "
          f"(retains {b['goal_retain']*100:.0f}% of goals)")
    print(f"\n     {'dist_frac':>9} {'min_prob':>8} {'shots':>6} {'goals':>6} {'conv':>6} {'retain':>7}")
    for r in g["top"]:
        print(f"     {r['dist_frac']:>9} {r['min_prob']:>8} {r['shots']:>6} "
              f"{r['goals']:>6} {r['conversion']:>6.3f} {r['goal_retain']:>7.2f}")
    print(f"\n  GOAL_HALF_WIDTH is NOT fittable from FCSHOT (needs goal-line crossing z;")
    print(f"  use calibrate_shots.py --ticks for that). These gates are PROPOSED — verify")
    print(f"  on >= ~30-50 logged shots before touching policy_v2.py.")


def main():
    ap = argparse.ArgumentParser(description="Fit SHOOT gates from FCSHOT logs + match records")
    ap.add_argument("--pairs", help="manifest JSON: [{match_id, log, record}, ...]")
    ap.add_argument("--logs-dir")
    ap.add_argument("--matches-dir")
    args = ap.parse_args()

    if args.pairs:
        with open(args.pairs) as f:
            manifest = json.load(f)
        pairs = []
        for it in manifest:
            fcshots = parse_fcshot_log(it["log"])
            with open(it["record"]) as f:
                record = json.load(f)
            pairs.append((fcshots, record))
        run(pairs, f"{len(pairs)} matches from manifest")
    elif args.logs_dir and args.matches_dir:
        man = pairs_from_dirs(args.logs_dir, args.matches_dir)
        pairs = []
        for it in man:
            fcshots = parse_fcshot_log(it["log"])
            with open(it["record"]) as f:
                record = json.load(f)
            pairs.append((fcshots, record))
        run(pairs, f"{len(pairs)} auto-paired matches")
    else:
        print("no --pairs/--logs-dir given: running synthetic demo")
        run(make_synthetic(), "synthetic")


if __name__ == "__main__":
    main()
