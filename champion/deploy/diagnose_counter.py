#!/usr/bin/env python3
"""
diagnose_counter.py — quantify FAST-TRANSITION / COUNTER-ATTACK opportunities and
how often we WASTE them, grounded in real engine tick data (NOT sim2 guesses).

Input: the FCTICK capture files under _build/ (one JSON object per line):
  {t, n, pb, ball{x,y,z,vx,vy,vz}, poss, poss_team, score, players[{pid,team,x,y}]}
We are team "home", attacking +x; our goal is at x=-6.4, opp goal at x=+6.4.

HYPOTHESIS (team-lead): vs an AGGRESSIVE opponent that commits bodies forward, when
we WIN/HOLD the ball deep there is SPACE IN BEHIND, but our DEFAULT policy recycles
slowly instead of springing a fast direct counter -> "wasted counters".

A COUNTER OPPORTUNITY tick =
  poss_team == "home"  (we hold the ball)
  AND ball.x < 0       (in our defensive half)
  AND >= N opponents (away players) with x < 0  (committed into our half -> space behind)

OUTCOME over the next K ticks (default K=3, ~6s at ~2s/tick):
  advance = max(ball.x in next K ticks while we still plausibly attack) - ball.x_now
  BREAK   = advance >= ADV_BREAK  (ball sprung forward toward +x fast)
  WASTED  = advance <  ADV_STALL  (stalled or went backward = slow recycle)

Run:  python3 champion/deploy/diagnose_counter.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.normpath(os.path.join(HERE, "..", "..", "_build"))

FIELD_X = 6.4  # half-length; goal line at |x| ~= 6.4 (matches policy_v2)


def load(fn):
    path = os.path.join(BUILD, fn)
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    # only ticks with a populated roster are usable for committed-forward counts
    return [r for r in rows if r.get("players")]


def away_forward(row):
    """# of away (opponent) players in OUR half (x < 0) -> committed forward."""
    return sum(1 for p in row["players"] if p.get("team") == "away" and p.get("x", 0.0) < 0.0)


def home_forward(row):
    return sum(1 for p in row["players"] if p.get("team") == "home" and p.get("x", 0.0) > 0.0)


def analyze(fn, N_forward=2, K=3):
    rows = load(fn)
    n = len(rows)

    # ---- calibrate: distribution of per-tick ball.x advance while we hold ----
    holds = [i for i, r in enumerate(rows) if r.get("poss_team") == "home"]
    deltas = []
    for i in holds:
        if i + 1 < n:
            deltas.append(rows[i + 1]["ball"]["x"] - rows[i]["ball"]["x"])
    deltas.sort()

    # ---- counter opportunities ----
    opps = []
    for i, r in enumerate(rows):
        if r.get("poss_team") != "home":
            continue
        bx = r["ball"]["x"]
        if bx >= 0.0:
            continue
        af = away_forward(r)
        if af < N_forward:
            continue
        # outcome over next K ticks: best forward ball.x reached
        future = rows[i + 1: i + 1 + K]
        if not future:
            continue
        best_fwd = max((f["ball"]["x"] for f in future), default=bx)
        advance = best_fwd - bx
        # did we keep possession at all during the window? (lost = turnover, not a recycle)
        kept = any(f.get("poss_team") == "home" for f in future)
        opps.append({
            "i": i, "t": r["t"], "ball_x": round(bx, 2), "away_fwd": af,
            "advance": round(advance, 2), "best_fwd_x": round(best_fwd, 2),
            "kept": kept,
        })
    return rows, deltas, opps


def pct(xs, q):
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))
    return round(xs[k], 2)


def report():
    files = ["ticks_default.jsonl", "ticks_shootmore.jsonl"]
    # thresholds calibrated below from the data; print a sweep so they're grounded
    ADV_BREAK = 1.5   # >= ~1.5 units forward over the window = a real break
    ADV_STALL = 0.5   # < 0.5 units = stalled / backward = wasted

    all_opps = []
    for fn in files:
        if not os.path.exists(os.path.join(BUILD, fn)):
            print(f"!! missing {fn}")
            continue
        print("=" * 72)
        print(f"FILE: {fn}")
        for Nf in (1, 2, 3):
            rows, deltas, opps = analyze(fn, N_forward=Nf, K=3)
            if Nf == 2:
                # full detail only for the headline threshold
                n = len(rows)
                print(f"  usable ticks: {n}")
                print(f"  per-tick ball.x advance while home holds (n={len(deltas)}): "
                      f"p10={pct(deltas,0.1)} p50={pct(deltas,0.5)} p90={pct(deltas,0.9)} "
                      f"max={round(deltas[-1],2) if deltas else None}")
                af_dist = Counter(away_forward(r) for r in rows if r.get("poss_team") == "home"
                                  and r["ball"]["x"] < 0)
                print(f"  among home-deep-possession ticks, #opp-forward dist: {dict(sorted(af_dist.items()))}")
            n_opp = len(opps)
            if n_opp == 0:
                print(f"  [N>={Nf}] counter-opportunities: 0")
                continue
            breaks = [o for o in opps if o["advance"] >= ADV_BREAK]
            stalls = [o for o in opps if o["advance"] < ADV_STALL]
            mid = [o for o in opps if ADV_STALL <= o["advance"] < ADV_BREAK]
            kept = [o for o in opps if o["kept"]]
            print(f"  [N>={Nf}] counter-opps={n_opp} | BREAK(adv>={ADV_BREAK})={len(breaks)} "
                  f"({100*len(breaks)//n_opp}%)  MID={len(mid)}  "
                  f"WASTED(adv<{ADV_STALL})={len(stalls)} ({100*len(stalls)//n_opp}%) | "
                  f"kept-poss={len(kept)}/{n_opp}")
            if Nf == 2:
                all_opps.extend(opps)

    # ---- combined headline (N>=2) ----
    print("=" * 72)
    if all_opps:
        n = len(all_opps)
        breaks = [o for o in all_opps if o["advance"] >= ADV_BREAK]
        stalls = [o for o in all_opps if o["advance"] < ADV_STALL]
        kept = [o for o in all_opps if o["kept"]]
        # wasted counter = had the opportunity, kept the ball, but did NOT break
        wasted_kept = [o for o in all_opps if o["kept"] and o["advance"] < ADV_BREAK]
        print(f"COMBINED (N>=2 opp forward, K=3 ticks, thresholds break>={ADV_BREAK}/stall<{ADV_STALL}):")
        print(f"  total counter-opportunities: {n}")
        print(f"  BREAK (fast forward): {len(breaks)} ({100*len(breaks)//n}%)")
        print(f"  WASTED (stall/backward): {len(stalls)} ({100*len(stalls)//n}%)")
        print(f"  kept possession through window: {len(kept)} ({100*len(kept)//n}%)")
        print(f"  WASTED-COUNTER RATE (kept ball but no break): "
              f"{len(wasted_kept)}/{len(kept) or 1} = "
              f"{100*len(wasted_kept)//(len(kept) or 1)}% of retained-possession counters")
        adv = sorted(o["advance"] for o in all_opps)
        print(f"  advance distribution: p25={pct(adv,0.25)} p50={pct(adv,0.5)} p75={pct(adv,0.75)} max={round(adv[-1],2)}")
        print("  sample wasted (kept ball, no break):")
        for o in wasted_kept[:8]:
            print(f"    t={o['t']:.1f} ball_x={o['ball_x']:+.2f} opp_fwd={o['away_fwd']} "
                  f"advance={o['advance']:+.2f} -> best_fwd_x={o['best_fwd_x']:+.2f}")
    else:
        print("No counter opportunities found at N>=2 -> hypothesis NOT supported by data.")


if __name__ == "__main__":
    report()
