#!/usr/bin/env python3
"""
Live-match analyzer — judges by MECHANISM, not scoreline (Fable-5 correction:
opp_on_target == opp_goals, so on-target/score is a tautology, not a lever).

Consumes FCTICK lines (full-state per-tick positions) collected live into
_build/live/agents.log (or any file/glob), and reports the three things that
actually matter:

  1) ENGINE-SEMANTICS CHECK (priority): after our GK gets the ball, does the ball
     actually TRAVEL FORWARD to a teammate (GK fast-launch / long KICK works), or
     stall / turn over (a MARK-style engine no-op)? Same test flags whether long
     forward balls (AERIAL creation) complete at all. Run on baseline vs the
     GK+aerial build and COMPARE — this is the only way to know those levers aren't vaporware.
  2) FREE-SHOOTER %: opponent has the ball in our half with no home player goal-side within 1.0u.
  3) TURNOVERS: how often we lose possession (home -> away / loose).

Usage:
  _build/tk-venv/bin/python champion/deploy/analyze_live.py _build/live/agents.log
  _build/tk-venv/bin/python champion/deploy/analyze_live.py '_build/live/*.log' --label baseline
"""
import sys, json, re, glob

OUR_GOAL_X = -6.4      # home defends -x
OPP_GOAL_X = 6.4       # home attacks +x
FWD_PIDS = (3, 4)


def load_fctick(paths):
    rows = []
    for pat in paths:
        for f in glob.glob(pat):
            for line in open(f, errors="ignore"):
                m = re.search(r"FCTICK\s+(\{.*\})", line)
                if not m:
                    # also accept a bare json line (pre-extracted)
                    s = line.strip().removeprefix("FCTICK ")
                    if not s.startswith("{"):
                        continue
                    frag = s
                else:
                    frag = m.group(1)
                try:
                    rows.append(json.loads(frag))
                except Exception:
                    pass
    # order by time; de-dup identical (t,n)
    seen = set(); out = []
    for r in sorted(rows, key=lambda r: (r.get("t", 0), r.get("n", 0))):
        k = (r.get("t"), r.get("n"))
        if k in seen:
            continue
        seen.add(k); out.append(r)
    return out


def hpos(r, pid):
    for p in r.get("players", []):
        if p.get("pid") == pid and p.get("team") == "home":
            return p["x"], p["y"]
    return None


def engine_semantics(rows, lookahead=8):
    """After a home-GK possession, does the ball advance forward + reach a teammate?"""
    gk_seqs = adv = stall = turnover = 0
    fwd_reach = 0
    for i, r in enumerate(rows):
        if r.get("poss") == 0 and r.get("poss_team") == "home":  # our GK has it
            bx0 = (r.get("ball") or {}).get("x", 0)
            gk_seqs += 1
            best_dx = 0.0; ended = "stall"
            for j in range(i + 1, min(i + 1 + lookahead, len(rows))):
                rj = rows[j]; bxj = (rj.get("ball") or {}).get("x", bx0)
                best_dx = max(best_dx, bxj - bx0)          # forward = +x
                pt = rj.get("poss_team"); pp = rj.get("poss")
                if pt == "away":
                    ended = "turnover"; turnover += 1; break
                if pt == "home" and pp in FWD_PIDS and (bxj - bx0) > 2.5:
                    ended = "fwd_reach"; fwd_reach += 1; break
                if pt == "home" and pp is not None and pp != 0 and (bxj - bx0) > 2.5:
                    ended = "adv"; break
            if ended in ("fwd_reach", "adv"):
                adv += 1
            elif ended == "stall":
                stall += 1
    return dict(gk_possessions=gk_seqs, advanced_forward=adv, reached_a_FWD=fwd_reach,
                stalled=stall, turned_over=turnover)


def free_shooter(rows):
    deep = free = 0
    for r in rows:
        if r.get("poss_team") != "away":
            continue
        bx = (r.get("ball") or {}).get("x", 0)
        if bx >= 0:            # ball must be in OUR half (x<0)
            continue
        deep += 1
        # covered = a home player goal-side of the ball (x < ball.x) AND within 1.5u
        # (euclidean) of the ball — i.e. close enough to contest a shot. Matches the
        # overnight subagent's definition. NOTE: free-shooter% is DEFINITION-SENSITIVE
        # (Fable) — treat as directional, lean on the engine-semantics read instead.
        by = (r.get("ball") or {}).get("y", 0)
        covered = False
        for p in r.get("players", []):
            if p.get("team") != "home":
                continue
            if p["x"] < bx and ((p["x"] - bx) ** 2 + (p["y"] - by) ** 2) ** 0.5 < 1.5:
                covered = True; break
        if not covered:
            free += 1
    return dict(opp_deep_ticks=deep, free_shooter_ticks=free,
                free_pct=round(100 * free / deep, 1) if deep else None)


def possession_and_turnovers(rows):
    home = away = loose = 0; turnovers = 0; prev = None
    for r in rows:
        pt = r.get("poss_team")
        if pt == "home": home += 1
        elif pt == "away": away += 1
        else: loose += 1
        if prev == "home" and pt in ("away", None):
            turnovers += 1
        prev = pt
    tot = home + away + loose
    return dict(ticks=tot, home_poss_pct=round(100*home/tot, 1) if tot else None,
                turnovers=turnovers)


def main():
    label = "match"; skip = None
    if "--label" in sys.argv:
        li = sys.argv.index("--label"); label = sys.argv[li + 1]; skip = li + 1
    paths = [a for k, a in enumerate(sys.argv[1:], start=1)
             if not a.startswith("--") and k != skip] or ["_build/live/agents.log"]
    rows = load_fctick(paths)
    print(f"=== LIVE ANALYSIS [{label}] — {len(rows)} FCTICK ticks from {paths} ===\n")
    if not rows:
        print("no FCTICK ticks found. Is FCTICK_ENABLED=True + observability on + did a match run?")
        return
    print("1) ENGINE SEMANTICS (does our GK ball actually travel forward?):")
    es = engine_semantics(rows)
    print(f"   {es}")
    if es["gk_possessions"]:
        adv_pct = round(100 * es["advanced_forward"] / es["gk_possessions"])
        print(f"   -> {adv_pct}% of GK possessions advanced forward; {es['reached_a_FWD']} reached a FWD, "
              f"{es['turned_over']} turned over.")
        print("   READ: baseline (GK short throw) low forward% is EXPECTED; a GK-fastlaunch build should raise "
              "forward%/FWD-reach. If it does NOT rise -> the long KICK is an engine no-op (drop the lever).")
    print("\n2) FREE-SHOOTER % (opp ball in our half, no goal-side cover):")
    print(f"   {free_shooter(rows)}")
    print("\n3) POSSESSION + TURNOVERS:")
    print(f"   {possession_and_turnovers(rows)}")
    print("\nNOTE: n is small live; treat all numbers as directional. The ENGINE-SEMANTICS delta "
          "(baseline vs GK+aerial build) is the one high-value, near-deterministic read.")


if __name__ == "__main__":
    main()
