#!/usr/bin/env python3
"""
State-space FUZZ + coverage audit for champion/policy_v2.py (Axis B).

WHY (Codex Axis-B guidance): the policy wins all 3 Benchmark styles but has
unexplained variance (a 1-3 loss with 73% possession). Until live tick capture
works (tick_collector -> tick_decode -> game_state dicts; see LIVE-DATA section
below), do NOT retune thresholds from Benchmark scorelines (overfit risk).
Instead sweep a broad, DETERMINISTIC, contract-valid synthetic state space and
audit WHICH decision branch fires where -- especially the 3 weak fallback
branches where the policy "gives up" to generic behavior:

  * on-ball "dribble toward goal"   reason="dribble toward goal"
  * off-ball "hold shape" SET_STANCE reason="hold shape"
  * GK "hold line"                   reason="GK hold line"

policy_v2.py is being edited CONCURRENTLY by another writer (it grew FORMATIONS +
role_for_player + new branches during this work), so this tool resolves every
file:line DYNAMICALLY from the live source at run time (see _resolve_branch_lines /
_line_of) rather than hard-coding numbers that go stale within minutes. The report
prints the resolved lines. The task brief quoted :657/:725/:577 for these branches;
at last run they were :794/:873/:701 — proof the dynamic resolver is doing its job.

This tool is PURE STDLIB + `import policy_v2`. No network, no Math.random: states
come from a fixed-seed LCG and itertools grids, so every run is byte-identical.

It does NOT propose threshold changes. It surfaces COVERAGE GAPS + reproducers:
  - histogram of branch-reason frequencies
  - % of states that land in each of the 3 weak fallback branches
  - degenerate state CLASSES: all-5-identical commands; attacker-with-ball near
    goal that fails to SHOOT; two of our players pick the SAME press target
    (swarm leak -- the single-presser invariant is supposed to forbid this).

Each finding ships a concrete reproducing game_state dict (printed inline in the
report) + the file:line of the branch.

Run:
  cd /Users/kei/football-cup && python3 champion/deploy/coverage_audit.py
Writes: _build/COVERAGE-AUDIT.md
"""
from __future__ import annotations

import itertools
import json
import os
import sys
from collections import Counter, defaultdict

# import the READ-ONLY policy under audit (same dir layout as test_contract.py)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import policy_v2 as P  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT_PATH = os.path.join(REPO_ROOT, "_build", "COVERAGE-AUDIT.md")

OUR_TEAM = 0          # audit from HOME's perspective (attack +x); policy is symmetric
PLAYER_IDS = (P.GK, P.DEF, P.MID, P.FWD1, P.FWD2)   # fixed engine roster ids 0..4
# policy_v2 NOW exposes FORMATIONS (1-1-2 / 2-1-1 / 1-2-1); sweep all of them.
FORMATION_KEYS = list(getattr(P, "FORMATIONS", {"1-1-2": None}).keys())

# ----------------------------------------------------------------------------- #
# Map a Cmd.reason -> (label, file:line). The policy labels every branch via the
# reason string; that string IS the authoritative branch fingerprint. We carry a
# static (key -> human label) table, but resolve the file:LINE *dynamically* at
# runtime by grepping the live policy_v2.py source for the reason literal. The
# other writer is actively editing policy_v2.py in this worktree, so hard-coded
# line numbers go stale within minutes; dynamic resolution is self-correcting.
# Substring match, longest-key-first, so "GK hold line" wins over a bare "hold".
# ----------------------------------------------------------------------------- #
REASON_LABELS: list[tuple[str, str]] = [
    # weak fallback branches (the 3 the audit targets) -- flagged in the report
    ("dribble toward goal",          "ON-BALL fallback: dribble toward goal"),
    ("hold shape",                   "OFF-BALL fallback: hold shape SET_STANCE"),
    ("GK hold line",                 "GK fallback: hold line"),
    # GK
    ("GK distribute",                "GK distribute (best option / clear)"),
    ("GK smother",                   "GK smother in box"),
    # on-ball shoot / pass / carry
    ("shoot! p=",                    "ON-BALL high-conf SHOOT"),
    ("pass better look",            "ON-BALL pass to better look"),
    ("shoot p=",                     "ON-BALL decent SHOOT"),
    ("carry into shooting position", "ON-BALL carry-to-shoot"),
    ("press release",                "ON-BALL pressure-release pass"),
    ("DEF clear under pressure",     "ON-BALL DEF clear under pressure"),
    ("pass chance",                  "ON-BALL pass (receiver has chance)"),
    ("pass->",                       "ON-BALL pass (forward outlet)"),
    # off-ball
    ("restart claim center",         "OFF-BALL restart: claim center"),
    ("restart forward lane",         "OFF-BALL restart: forward lane"),
    ("DEF tackle at feet",           "OFF-BALL DEF slide tackle at feet"),
    ("DEF press at feet",            "OFF-BALL DEF press at feet"),
    ("DEF mark danger",              "OFF-BALL DEF mark danger"),
    ("MID drop-mark",                "OFF-BALL MID drop-mark 2nd striker"),
    ("tackle carrier",               "OFF-BALL slide tackle carrier"),
    ("closest+in-zone press",        "OFF-BALL single-presser press"),
    # support-run reasons (defined in _support_run())
    ("press layoff outlet",          "OFF-BALL support: press layoff outlet"),
    ("press central outlet",         "OFF-BALL support: press central outlet"),
    ("offer cutback outlet",         "OFF-BALL support: offer cutback"),
    ("show central outlet",          "OFF-BALL support: show central outlet"),
    ("press in-behind outlet",       "OFF-BALL support: in-behind outlet"),
    ("attack box outlet",            "OFF-BALL support: attack box outlet"),
    ("stretch forward outlet",       "OFF-BALL support: stretch forward"),
    # shape recovery / outlet
    ("return to zone",               "OFF-BALL return to zone anchor"),
    ("offer outlet",                 "OFF-BALL in-position offer outlet"),
    ("me not found",                 "ERROR: me not found"),
]

WEAK_FALLBACK_REASONS = {"dribble toward goal", "hold shape", "GK hold line"}


def _branch_probe(key: str) -> str:
    """Static prefix of a reason key for matching the SOURCE literal: keep a literal
    `->` (distinguishes `pass->` from `pass better look->`) but drop the dynamic
    `p=`/`s=` tails that are f-string interpolations."""
    p = key.split(" p=")[0].split(" s=")[0]
    return p.rstrip()


def _resolve_branch_lines() -> dict[str, str]:
    """Grep the live policy_v2.py for each reason literal -> 'policy_v2.py:LINE'.
    First source line containing the literal wins (the reason text appears at the
    branch's return/definition site). Falls back to ':?' if the literal moved/changed
    (which the UNMATCHED counter also surfaces)."""
    src_path = os.path.abspath(P.__file__)
    base = os.path.basename(src_path)
    with open(src_path) as f:
        src_lines = f.readlines()
    loc = {}
    for key, _label in REASON_LABELS:
        # Source literals are f-strings like  f"pass->{pid} s={...}"  or  "hold shape".
        # The distinguishing STATIC prefix runs up to the first f-string interpolation
        # `{` (keep a literal `->` so `pass->` != `pass better look->`). Match only
        # where it appears as a QUOTED literal (excludes prose comments).
        probe = _branch_probe(key)
        needles = (f'"{probe}', f"'{probe}")
        found = next((i + 1 for i, ln in enumerate(src_lines)
                      if any(nd in ln for nd in needles)), None)
        loc[key] = f"{base}:{found}" if found else f"{base}:?"
    return loc


BRANCH_LINE = _resolve_branch_lines()   # key -> "policy_v2.py:LINE", resolved at import


def classify(reason: str) -> tuple[str, str, str]:
    """Return (matched_reason_key, human_label, file_line) for a Cmd.reason."""
    for key, label in sorted(REASON_LABELS, key=lambda r: -len(r[0])):
        if key in reason:
            return key, label, BRANCH_LINE.get(key, "policy_v2.py:?")
    return ("<UNMATCHED>", f"UNMATCHED reason: {reason!r}", "policy_v2.py:?")


# ----------------------------------------------------------------------------- #
# Deterministic LCG (no Math.random / no random module) for jittered states.
# ----------------------------------------------------------------------------- #
class LCG:
    def __init__(self, seed: int = 0x9E3779B1):
        self.s = seed & 0xFFFFFFFF

    def next(self) -> float:
        # Numerical Recipes LCG -> uniform [0,1)
        self.s = (1664525 * self.s + 1013904223) & 0xFFFFFFFF
        return self.s / 0x100000000

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.next()


# ----------------------------------------------------------------------------- #
# Contract-valid state builder (mirrors champion/test_contract.py::_state).
# ----------------------------------------------------------------------------- #
def build_state(ball_xy, ball_h, poss_aid, poss_team, home_pos, away_pos, stam_map, game_time):
    """home_pos/away_pos: {pid:(x,y)}; stam_map: {('home'|'away', pid): stamina}."""
    players = []
    for pid, (x, y) in home_pos.items():
        players.append({"agentId": f"agentId_{pid}", "teamCode": "home",
                        "position": {"x": round(x, 3), "y": round(y, 3)},
                        "stamina": stam_map.get(("home", pid), 100)})
    for pid, (x, y) in away_pos.items():
        players.append({"agentId": f"agentId_{pid}", "teamCode": "away",
                        "position": {"x": round(x, 3), "y": round(y, 3)},
                        "stamina": stam_map.get(("away", pid), 100)})
    ball = {"position": {"x": round(ball_xy[0], 3), "y": round(ball_h, 3), "z": round(ball_xy[1], 3)}}
    if poss_aid is not None:
        ball["possessionAgentId"] = poss_aid
    if poss_team is not None:
        ball["possessionTeam"] = poss_team
    return {"ball": ball, "score": {"home": 0, "away": 0},
            "gameTime": round(game_time, 2), "players": players}


# Opponent (away) shape templates. away attacks -x, so its "forwards" sit at low x.
def away_shape(kind: str, ball_xy):
    bx, by = ball_xy
    if kind == "compact":      # tight bank near own goal (+x), low line
        return {0: (6.4, 0.0), 1: (4.6, -0.4), 2: (4.2, 0.4), 3: (3.4, -0.6), 4: (3.4, 0.6)}
    if kind == "spread":       # stretched across the pitch
        return {0: (6.4, 0.0), 1: (3.2, -2.6), 2: (0.5, 0.0), 3: (-1.5, 2.4), 4: (-2.0, -1.0)}
    if kind == "two-striker":  # two attackers pushed into OUR half (low x)
        return {0: (6.4, 0.0), 1: (2.0, 0.0), 2: (-1.0, 0.5), 3: (-4.5, -0.7), 4: (-4.5, 0.7)}
    if kind == "press":        # opponents crowding the ball (swarm pressure on us)
        return {0: (6.4, 0.0),
                1: (bx + 0.4, by - 0.3), 2: (bx - 0.4, by + 0.3),
                3: (bx + 0.2, by + 0.5), 4: (bx - 0.2, by - 0.5)}
    raise ValueError(kind)


# Our (home) shape templates. home attacks +x.
def home_shape(kind: str, ball_xy, carrier_pid=None):
    bx, by = ball_xy
    base = {0: (-6.4, 0.0), 1: (-3.0, 0.0), 2: (0.0, 0.0), 3: (5.0, -0.8), 4: (5.0, 0.8)}
    if kind == "default":
        pass
    elif kind == "high-line":   # whole team pushed up
        base = {0: (-5.6, 0.0), 1: (-1.0, 0.0), 2: (2.0, 0.0), 3: (5.5, -0.8), 4: (5.5, 0.8)}
    elif kind == "deep":        # whole team defending deep
        base = {0: (-6.4, 0.0), 1: (-5.0, -0.5), 2: (-3.0, 0.0), 3: (-1.0, -0.8), 4: (-1.0, 0.8)}
    # if a home player carries the ball, snap that player onto the ball
    if carrier_pid is not None and carrier_pid in base:
        base[carrier_pid] = (bx, by)
    return base


# ----------------------------------------------------------------------------- #
# State-space sweep
# ----------------------------------------------------------------------------- #
def sweep():
    """Yield (state_label, formation, game_state) tuples. Deterministic grid + LCG jitter."""
    rng = LCG()
    # grid axes (kept modest so the run is fast; jitter widens coverage)
    xs = [-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0]
    zs = [-3.2, -1.6, 0.0, 1.6, 3.2]
    heights = [0.05, 1.2]                       # ground vs aerial ball
    poss_kinds = ["free", "ours", "theirs"]
    away_kinds = ["compact", "spread", "two-striker", "press"]
    home_kinds = ["default", "high-line", "deep"]
    stam_kinds = ["fresh", "mixed", "gassed"]
    gt = 0.0

    for bx, bz, bh, poss, ak, hk, sk, formation in itertools.product(
        xs, zs, heights, poss_kinds, away_kinds, home_kinds, stam_kinds, FORMATION_KEYS
    ):
        gt += 0.1
        ball_xy = (bx, bz)
        # who possesses?
        carrier_pid = None
        poss_aid = poss_team = None
        if poss == "ours":
            # pick the home player closest to the ball as carrier (snap onto ball)
            hp = home_shape(hk, ball_xy)
            carrier_pid = min(hp, key=lambda pid: (hp[pid][0] - bx) ** 2 + (hp[pid][1] - bz) ** 2)
            poss_aid, poss_team = f"agentId_{carrier_pid}", "home"
        elif poss == "theirs":
            ap = away_shape(ak, ball_xy)
            opp_carrier = min(ap, key=lambda pid: (ap[pid][0] - bx) ** 2 + (ap[pid][1] - bz) ** 2)
            poss_aid, poss_team = f"agentId_{opp_carrier}", "away"

        home_pos = home_shape(hk, ball_xy, carrier_pid)
        away_pos = away_shape(ak, ball_xy)

        # stamina profile
        stam_map = {}
        if sk == "fresh":
            pass  # all 100
        elif sk == "gassed":
            for pid in PLAYER_IDS:
                stam_map[("home", pid)] = round(rng.uniform(2.0, 15.0), 1)   # below LOW_STAMINA
        elif sk == "mixed":
            for pid in PLAYER_IDS:
                stam_map[("home", pid)] = round(rng.uniform(10.0, 100.0), 1)

        # small deterministic positional jitter so we don't only hit grid points
        jx, jz = rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3)
        ball_xy = (max(-6.4, min(6.4, bx + jx)), max(-3.5, min(3.5, bz + jz)))
        if carrier_pid is not None:
            home_pos[carrier_pid] = ball_xy

        label = (f"ball=({ball_xy[0]:.1f},{ball_xy[1]:.1f}) h={bh} poss={poss} "
                 f"away={ak} home={hk} stam={sk} form={formation}")
        gs = build_state(ball_xy, bh, poss_aid, poss_team, home_pos, away_pos, stam_map, gt)
        yield label, formation, gs


# ----------------------------------------------------------------------------- #
# Per-state analysis: degenerate classes
# ----------------------------------------------------------------------------- #
def press_target(cmd_dict) -> object | None:
    """Identify the opponent a command 'targets' for pressing/marking/tackling.
    PRESS_BALL has no target id (it presses the ball), so we treat the ball as the
    shared target -> two PRESS_BALL from us = both swarming the ball = swarm leak."""
    ct = cmd_dict["commandType"]
    if ct == "PRESS_BALL":
        return ("BALL",)
    if ct in ("MARK", "SLIDE_TACKLE", "INTERCEPT"):
        tid = cmd_dict["parameters"].get("target_player_id")
        if tid is not None:
            return ("OPP", tid)
    return None


def analyze():
    hist = Counter()
    loc_of = {}
    weak_hits = Counter()
    unmatched_reasons = Counter()   # raw Cmd.reason strings not in REASON_LABELS
    total = 0

    # finding buckets (cap reproducers so the report stays readable)
    deg_identical = []      # all 5 emit the same command dict
    attacker_no_shot = []   # attacker w/ ball near goal, on-frame, but not SHOOT
    swarm_leak = []         # >=2 of our players press/mark the SAME target

    CAP = 6  # max reproducers kept per finding class

    for label, formation, gs in sweep():
        total += 1
        cmds = {}        # pid -> command dict
        reasons = {}     # pid -> matched reason key
        for pid in PLAYER_IDS:
            c = P.decide(gs, OUR_TEAM, pid, formation)   # Cmd (carries .reason)
            cmd_dict = {"commandType": c.commandType, "parameters": c.parameters}
            cmds[pid] = cmd_dict
            key, label_h, loc = classify(c.reason)
            reasons[pid] = key
            loc_of[key] = loc
            hist[key] += 1
            if key == "<UNMATCHED>":
                unmatched_reasons[c.reason] += 1
            if key in WEAK_FALLBACK_REASONS:
                weak_hits[key] += 1

        # ---- degenerate class 1: all 5 identical command (type + params) ----
        sig = {json.dumps(cmds[pid], sort_keys=True) for pid in PLAYER_IDS}
        if len(sig) == 1 and len(deg_identical) < CAP:
            deg_identical.append((label, cmds[P.GK], gs))

        # ---- degenerate class 2: attacker w/ ball near goal fails to SHOOT ----
        holder = P.possession_holder(gs)
        if holder is not None and P._is_mine(holder, OUR_TEAM):
            hpid = P._pid(holder)
            hslot = P.role_for_player(hpid, formation)   # tactical slot under this formation
            if P._is_attacker(hslot):
                v = P._parse(gs, OUR_TEAM, hpid)
                if v is not None:
                    gk_opp = P._gk_of(v.opponents)
                    shot = P.evaluate_shot(v.me_xy[0], v.me_xy[1], gk_opp, v.opp_goal_x,
                                           [P._field_xy(o) for o in v.opponents])
                    real = P._shot_is_real_chance(v, v.me_xy[0], v.me_xy[1], shot)
                    # "near goal + on-frame + model says decent" but command is not SHOOT
                    if (real and shot["dist"] <= P._shoot_dist(P.ROLE_CONFIG[hslot])
                            and shot["prob"] >= P.SHOOT_MIN_PROB
                            and cmds[hpid]["commandType"] != "SHOOT"
                            and len(attacker_no_shot) < CAP):
                        attacker_no_shot.append(
                            (label, hpid, hslot, cmds[hpid], round(shot["prob"], 2),
                             round(shot["dist"], 2), gs))

        # ---- degenerate class 3: swarm leak (>=2 of us share a press target) --
        targets = Counter()
        target_pids = defaultdict(list)
        for pid in PLAYER_IDS:
            tgt = press_target(cmds[pid])
            if tgt is not None:
                targets[tgt] += 1
                target_pids[tgt].append(pid)
        for tgt, n in targets.items():
            if n >= 2 and len(swarm_leak) < CAP:
                swarm_leak.append((label, tgt, target_pids[tgt],
                                   {pid: cmds[pid]["commandType"] for pid in target_pids[tgt]}, gs))
                break

    return {
        "total_states": total,
        "total_decisions": total * len(PLAYER_IDS),
        "hist": hist,
        "loc_of": loc_of,
        "weak_hits": weak_hits,
        "deg_identical": deg_identical,
        "attacker_no_shot": attacker_no_shot,
        "swarm_leak": swarm_leak,
        "unmatched_reasons": unmatched_reasons,
    }


# ----------------------------------------------------------------------------- #
# Report
# ----------------------------------------------------------------------------- #
def _fmt_state(gs: dict) -> str:
    return json.dumps(gs, separators=(",", ":"))


def _line_of(needle: str) -> str:
    """Dynamic 'policy_v2.py:LINE' for an arbitrary source substring (a def name or
    quoted literal). First match wins; ':?' if absent. Used so the findings prose
    never carries a stale hard-coded line number."""
    base = os.path.basename(P.__file__)
    with open(os.path.abspath(P.__file__)) as f:
        for i, ln in enumerate(f):
            if needle in ln:
                return f"{base}:{i + 1}"
    return f"{base}:?"


def _bl(key: str) -> str:
    """Resolved file:line for a known branch reason key."""
    return BRANCH_LINE.get(key, "policy_v2.py:?")


def write_report(r: dict):
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    total = r["total_states"]
    decisions = r["total_decisions"]
    hist = r["hist"]
    loc_of = r["loc_of"]

    lines = []
    A = lines.append
    A("# COVERAGE-AUDIT — policy_v2 state-space fuzz (Axis B)\n")
    A("Generated by `champion/deploy/coverage_audit.py` (pure stdlib, deterministic).")
    A("Sweeps a broad contract-valid synthetic state space and records which decision")
    A("branch fires (via `Cmd.reason`). NO threshold proposals — coverage gaps + reproducers only.\n")
    A(f"- **states swept:** {total}")
    A(f"- **decisions recorded:** {decisions}  (5 players x {total} states)")
    A(f"- **perspective:** team_id={OUR_TEAM} (HOME); engine roster = ids 0..4")
    A(f"- **formations swept:** {', '.join(FORMATION_KEYS)} (via policy_v2.FORMATIONS; "
      "`decide(... , formation)`)")
    A("- **opponent shapes swept:** compact / spread / two-striker / press")
    A("- **our line heights swept:** default / high-line / deep")
    A("- **ball:** x in [-6.4,6.4], depth in [-3.5,3.5], ground + aerial heights")
    A("- **possession:** free / ours / theirs; **stamina:** fresh / mixed / gassed")
    A("- **file:line numbers are resolved DYNAMICALLY** from the live policy_v2.py at")
    A("  run time (the file is edited concurrently), so they track the current source.\n")

    # --- histogram ---
    A("## Branch-reason histogram\n")
    A("| count | % of decisions | branch | file:line |")
    A("|------:|---------------:|--------|-----------|")
    for key, n in hist.most_common():
        pct = 100.0 * n / decisions
        flag = " **[WEAK FALLBACK]**" if key in WEAK_FALLBACK_REASONS else ""
        A(f"| {n} | {pct:.1f}% | `{key}`{flag} | {loc_of.get(key,'?')} |")
    A("")

    # --- weak fallback summary ---
    A("## Weak-fallback share (the 3 audited 'give-up' branches)\n")
    A("| branch | file:line | hits | % of decisions |")
    A("|--------|-----------|-----:|---------------:|")
    weak_total = 0
    for key in ("dribble toward goal", "hold shape", "GK hold line"):
        n = r["weak_hits"].get(key, 0)
        weak_total += n
        A(f"| `{key}` | {loc_of.get(key,'?')} | {n} | {100.0*n/decisions:.1f}% |")
    A(f"| **TOTAL weak fallback** | | **{weak_total}** | **{100.0*weak_total/decisions:.1f}%** |")
    A("")

    # --- findings ---
    A("## Findings (degenerate / leak state classes)\n")

    A("### 1. Swarm leak — two+ of our players share a press/mark target\n")
    A(f"The single-presser invariant (`_closest_teammate_to_ball_is_me`, "
      f"{_line_of('def _closest_teammate_to_ball_is_me')}) guarantees exactly one PRESS,")
    A("but the MARK paths (DEF mark danger / MID drop-mark) have NO cross-player")
    A("coordination, so two defenders can MARK the same opponent. `('BALL',)` = both")
    A("emitted PRESS_BALL; `('OPP', id)` = both MARK/TACKLE the same opponent.\n")
    if not r["swarm_leak"]:
        A("_No swarm leak found in the swept space._\n")
    else:
        for label, tgt, pids, types, gs in r["swarm_leak"]:
            A(f"- **{label}**")
            A(f"  - target `{tgt}` shared by our players {pids} -> {types}")
            A(f"  - candidate branches: `DEF mark danger` {_bl('DEF mark danger')} / "
              f"`MID drop-mark` {_bl('MID drop-mark')} / `closest+in-zone press` "
              f"{_bl('closest+in-zone press')}")
            A(f"  - repro: `{_fmt_state(gs)}`")
        A("")

    A("### 2. Attacker with ball near goal fails to SHOOT\n")
    A("Holder is an attacker slot, the shot model says on-frame + dist in shoot range")
    A(f"+ prob >= SHOOT_MIN_PROB ({P.SHOOT_MIN_PROB}), yet the emitted command is not SHOOT.")
    A("NOTE: `pass better look` is often INTENDED (passing to a teammate with a clearly")
    A("better shot is correct) — these are surfaced so a human can confirm the model")
    A("agreed the receiver was genuinely better, vs. a state where we declined a real shot.\n")
    if not r["attacker_no_shot"]:
        A("_No attacker-near-goal-no-shot states found._\n")
    else:
        for label, hpid, hslot, cmd, prob, dist, gs in r["attacker_no_shot"]:
            A(f"- **{label}**")
            A(f"  - holder pid={hpid} (slot {P.ROLE_NAME.get(hslot)}) emitted {cmd['commandType']} "
              f"(model prob={prob}, dist={dist})")
            A(f"  - relevant branches: carry-to-shoot {_bl('carry into shooting position')} / "
              f"pass-better-look {_bl('pass better look')} / pass-chance {_bl('pass chance')} / "
              f"pass-fwd {_bl('pass->')} / dribble fallback {_bl('dribble toward goal')}")
            A(f"  - repro: `{_fmt_state(gs)}`")
        A("")

    A("### 3. All-5-identical command (degenerate uniformity)\n")
    A("Every one of our 5 players emitted the byte-identical command — a sign the")
    A("state collapsed everyone into one generic behavior (e.g. all hold shape).\n")
    if not r["deg_identical"]:
        A("_No all-5-identical states found._\n")
    else:
        for label, cmd, gs in r["deg_identical"]:
            A(f"- **{label}**")
            A(f"  - all 5 -> `{cmd['commandType']}` params={json.dumps(cmd['parameters'])}")
            A(f"  - repro: `{_fmt_state(gs)}`")
        A("")

    # --- unmatched reasons (a NEW branch the other writer added; fingerprint gap) ---
    if "<UNMATCHED>" in hist:
        A("### ! Unmatched reasons — new policy branches not yet in this tool's table\n")
        A(f"{hist['<UNMATCHED>']} decisions produced a `Cmd.reason` not in `REASON_LABELS`")
        A("(policy_v2.py is being edited concurrently; these are likely NEW branches).")
        A("Add the literal to `REASON_LABELS` to fold it into the histogram + line-resolver:\n")
        A("| count | raw reason | resolved line |")
        A("|------:|------------|---------------|")
        for raw, n in r["unmatched_reasons"].most_common(30):
            probe = _branch_probe(raw)
            # best-effort live line lookup for the unmatched literal (quoted only)
            src = open(os.path.abspath(P.__file__)).read().splitlines()
            nds = (f'"{probe}', f"'{probe}")
            ln = next((i + 1 for i, t in enumerate(src) if probe and any(d in t for d in nds)), "?")
            A(f"| {n} | `{raw}` | {os.path.basename(P.__file__)}:{ln} |")
        A("")

    with open(OUT_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    r = analyze()
    write_report(r)
    # stdout summary (machine-friendly for the orchestrator)
    print(f"coverage_audit: swept {r['total_states']} states, {r['total_decisions']} decisions")
    weak = sum(r["weak_hits"].values())
    print(f"  weak-fallback decisions: {weak} ({100.0*weak/r['total_decisions']:.1f}%)")
    for key in ("dribble toward goal", "hold shape", "GK hold line"):
        n = r["weak_hits"].get(key, 0)
        print(f"    {key:24s} {n:6d}  {100.0*n/r['total_decisions']:5.1f}%  {r['loc_of'].get(key,'?')}")
    print(f"  swarm-leak reproducers     : {len(r['swarm_leak'])}")
    print(f"  attacker-no-shot reproducers: {len(r['attacker_no_shot'])}")
    print(f"  all-5-identical reproducers : {len(r['deg_identical'])}")
    if "<UNMATCHED>" in r["hist"]:
        print(f"  UNMATCHED reasons          : {r['hist']['<UNMATCHED>']} (update REASON_BRANCHES)")
    print(f"  wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
