#!/usr/bin/env python3
"""
REPLAY-BASED preset evaluator — the trustworthy offline signal.

Unlike sweep.py (which ran the low-trust sim2 physics, AND was inert due to a
dual-import bug: sim2 `import policy_v2` vs sweep `import champion.policy_v2` =
two module objects, so knob mutations never reached the sim), this evaluator
re-runs the REAL policy `command()` over REAL observed game states (the FCTICK
jsonl captured live) and measures how each preset changes the bot's DECISIONS.

HONEST SCOPE (same limit as PLAYBOOK §0 replay): positions are FROZEN, so this
proves the COMMAND/intent changed, not the OUTCOME (goals). It ranks decision
quality on identical states — exactly what isolates one preset from another.
Outcome still needs a LIVE match. Use this to pick 2-3 to validate live.

Run:  _build/tk-venv/bin/python -m champion.preset_eval
"""
import json
import champion.policy_v2 as P

TICK_FILES = ["_build/LIVE-FCTICK.jsonl", "_build/FCTICK-DEF.jsonl"]

# --------------------------------------------------------------------------- #
# PRESETS — each a COHERENT full tactic (not a single toggle). Overrides are
# vs the CURRENT HEAD default. Entry forms:
#   ("G", "SHOOT_MIN_PROB", 0.48)              -> module global
#   ("R", P_SLOT, "anchor_ax", -0.32)          -> ROLE_CONFIG[slot].field
# Slots are resolved lazily by name in _slot().
# --------------------------------------------------------------------------- #
def _slot(name):
    return {"GK": P.GK, "DEF": P.DEF, "MID": P.MID, "FWD1": P.FWD1, "FWD2": P.FWD2}[name]

PRESETS = {
    # control = current HEAD (no overrides) — the baseline every preset must beat.
    "A_sharp_counter": [],

    # High-press gegen: higher line + tighter press triggers, recovery ON so the
    # high line does not leak. Beats weak build-up. Risk: fast counter in behind.
    "B_high_press_gegen": [
        ("R", "DEF", "anchor_ax", -0.32), ("R", "DEF", "press_trigger", 0.24),
        ("R", "MID", "press_trigger", 0.26), ("R", "FWD1", "press_trigger", 0.24),
        ("R", "FWD2", "press_trigger", 0.24), ("G", "RECOVERY_DEF_ENABLED", True),
    ],

    # Front-two overload: strikers higher + more push + in-behind runs on.
    # Beats defensive low-block. Risk: countered.
    "C_front_two_overload": [
        ("R", "FWD1", "anchor_ax", 0.70), ("R", "FWD2", "anchor_ax", 0.70),
        ("R", "FWD1", "push_when_attacking", 0.40), ("R", "FWD2", "push_when_attacking", 0.40),
        ("R", "MID", "push_when_attacking", 0.46), ("G", "INBEHIND_RUN_ENABLED", True),
    ],

    # Low-block direct: sit deep, absorb, one high outlet + counter/recovery on.
    # Beats possession-dominant teams. Risk: cedes territory/shots.
    "D_low_block_direct": [
        ("R", "DEF", "anchor_ax", -0.60), ("R", "MID", "anchor_ax", -0.12),
        ("R", "MID", "push_when_attacking", 0.24), ("G", "RECOVERY_DEF_ENABLED", True),
    ],

    # Patient finish: no long shots (FWD risk down), higher shoot bar, carry closer
    # before shooting. Beats teams that concede the middle. Risk: fewer shots.
    "E_patient_finish": [
        ("R", "FWD1", "risk", 0.30), ("R", "FWD2", "risk", 0.30),
        ("G", "SHOOT_MIN_PROB", 0.48), ("G", "CARRY_TO_SHOOT_DIST", 0.72),
    ],

    # Creation-max: BOTH sustained-creation levers on + LOWER the through gate.
    # Codex Q2: the 0.50 gate filters out defended in-behind lanes (real states
    # compute 0.43/0.34), so flipping the flags alone leaves it INERT. Lower the
    # gate to 0.44 so a runner-behind-the-line pass can actually fire.
    "F_creation_max": [
        ("G", "INBEHIND_RUN_ENABLED", True), ("G", "THROUGHBALL_EV_ENABLED", True),
        ("G", "THROUGHBALL_EV_WEIGHT", 0.8), ("G", "COUNTER_THROUGH_MIN_SUCCESS", 0.44),
    ],

    # Evade-retention: dribble around the tackler instead of straight carries.
    # Mechanism: fewer turnovers -> more shots, fewer opp transitions.
    "G_evade_retention": [
        ("G", "DRIBBLE_EVADE_ENABLED", True),
    ],

    # Recovery-solid: FWDs drop to goal-side cover when pinned deep. Directly
    # attacks Codex's #1 gap (free shooters). Pairs with any attack preset.
    "H_recovery_solid": [
        ("G", "RECOVERY_DEF_ENABLED", True), ("G", "RECOVERY_BALL_DEPTH", 0.20),
    ],

    # ★ LEAD candidate: the two best-evidenced live arms combined (EVADE 50% +
    # RECOVERY 43%), never tested together. Retain the ball + goal-side cover.
    "Y_evade_recovery": [
        ("G", "DRIBBLE_EVADE_ENABLED", True),
        ("G", "RECOVERY_DEF_ENABLED", True), ("G", "RECOVERY_BALL_DEPTH", 0.20),
    ],

    # Best-guess COMBO: overload attack + recovery-solid defence.
    "Z_overload_plus_recovery": [
        ("R", "FWD1", "anchor_ax", 0.70), ("R", "FWD2", "anchor_ax", 0.70),
        ("R", "MID", "push_when_attacking", 0.46), ("G", "INBEHIND_RUN_ENABLED", True),
        ("G", "RECOVERY_DEF_ENABLED", True), ("G", "RECOVERY_BALL_DEPTH", 0.20),
    ],
}


def apply(overrides):
    """Apply overrides; return a restore() closure that undoes them exactly."""
    saved = []
    for ov in overrides:
        if ov[0] == "G":
            _, name, val = ov
            saved.append(("G", name, getattr(P, name)))
            setattr(P, name, val)
        else:
            _, slotname, field, val = ov
            cfg = P.ROLE_CONFIG[_slot(slotname)]
            saved.append(("R", slotname, field, getattr(cfg, field)))
            setattr(cfg, field, val)
    def restore():
        for s in reversed(saved):
            if s[0] == "G":
                setattr(P, s[1], s[2])
            else:
                setattr(P.ROLE_CONFIG[_slot(s[1])], s[2], s[3])
    return restore


def load_rows():
    rows = []
    for f in TICK_FILES:
        try:
            for line in open(f):
                line = line.strip().removeprefix("FCTICK ")
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
        except FileNotFoundError:
            pass
    return rows


def to_gs(row):
    players = [{"agentId": "agentId_%d" % p["pid"], "teamCode": p["team"],
                "position": {"x": p["x"], "y": p["y"]}, "velocity": {"x": 0, "y": 0},
                "stamina": 100, "orientation": 0, "currentAction": "IDLE",
                "lastAction": "", "speed": 0, "isSprinting": False}
               for p in row.get("players", [])]
    b = row.get("ball") or {}
    poss = row.get("poss")
    pt = row.get("poss_team")
    gs = {"players": players,
          "ball": {"position": {"x": b.get("x", 0), "y": b.get("y", 0), "z": b.get("z", 0)},
                   "velocity": {"x": b.get("vx") or 0, "y": b.get("vy") or 0, "z": b.get("vz") or 0},
                   "isFree": poss is None,
                   "possessionAgentId": ("agentId_%d" % poss) if poss is not None else None,
                   "possessionTeam": pt},
          "score": row.get("score") or {"home": 0, "away": 0},
          "gameTime": row.get("t", 30) or 30}
    return gs, poss, pt, b


GOAL_OPP_X = 6.4   # home attacks +x


def evaluate(rows):
    m = dict(shots=0, shot_dist=0.0, shot_power=0.0, direct=0, ground=0,
             fwd_depth=0.0, fwd_n=0, recover_cover=0, opp_deep=0,
             loose_contest=0, loose=0, err=0, we_poss=0)
    for r in rows:
        gs, poss, pt, b = to_gs(r)
        bx = b.get("x", 0)
        for pid in range(5):
            try:
                c = P.command(gs, 0, pid)
            except Exception:
                m["err"] += 1
                continue
            ct = c.get("commandType")
            pr = c.get("parameters", {})
            # on-ball carrier (we possess, this is the holder)
            if pt == "home" and poss == pid:
                m["we_poss"] += 1
                if ct == "SHOOT":
                    m["shots"] += 1
                    m["shot_dist"] += abs(GOAL_OPP_X - r["players"][pid]["x"])
                    m["shot_power"] += pr.get("power", 0)
                elif ct == "PASS":
                    t = pr.get("type")
                    if t in ("THROUGH", "AERIAL"):
                        m["direct"] += 1
                    else:
                        m["ground"] += 1
            # off-ball forward depth for FWDs when we possess
            if pt == "home" and poss != pid and pid in (3, 4) and ct == "MOVE_TO":
                m["fwd_depth"] += pr.get("target_x", 0)
                m["fwd_n"] += 1
            # defensive recovery cover on opp-deep ticks (ball in our half)
            if pt == "away" and bx < 0:
                if pid == 0:
                    m["opp_deep"] += 1  # count tick once (via GK slot)
                if ct == "MOVE_TO" and pr.get("target_x", 0) < bx:
                    m["recover_cover"] += 1
            # loose-ball contest
            if pt is None:
                if pid == 0:
                    m["loose"] += 1
                if ct in ("PRESS_BALL", "SLIDE_TACKLE") or (ct == "MOVE_TO" and pr.get("sprint")):
                    m["loose_contest"] += 1
    return m


def score(m):
    avg_dist = (m["shot_dist"] / m["shots"]) if m["shots"] else 99
    # transparent mechanism weights (higher = sharper). dist penalized.
    return (m["shots"] * 1.0 + m["direct"] * 1.5 + m["recover_cover"] * 0.5
            + m["loose_contest"] * 0.3 + m["fwd_depth"] * 0.02 - avg_dist * 0.5)


def main():
    rows = load_rows()
    print(f"replay corpus: {len(rows)} real ticks over {len(TICK_FILES)} files\n")
    results = []
    for name, ov in PRESETS.items():
        restore = apply(ov)
        try:
            m = evaluate(rows)
        finally:
            restore()
        results.append((score(m), name, m))
    results.sort(reverse=True)
    hdr = f"{'preset':26s} {'shots':>5s} {'sdist':>6s} {'direct':>6s} {'fwdX':>6s} {'recov':>6s} {'loose':>6s} {'err':>4s} {'SCORE':>7s}"
    print(hdr); print("-" * len(hdr))
    base = next(m for s, n, m in results if n == "A_sharp_counter")
    for s, name, m in results:
        avg_dist = (m["shot_dist"] / m["shots"]) if m["shots"] else 0
        favg = (m["fwd_depth"] / m["fwd_n"]) if m["fwd_n"] else 0
        print(f"{name:26s} {m['shots']:5d} {avg_dist:6.2f} {m['direct']:6d} {favg:6.2f} "
              f"{m['recover_cover']:6d} {m['loose_contest']:6d} {m['err']:4d} {s:7.1f}")
    print(f"\nphases: we_poss={base['we_poss']} opp_deep={base['opp_deep']} loose={base['loose']}")
    print(f"WINNER (mechanism-score, RELATIVE only; validate top-3 live): {results[0][1]}")


if __name__ == "__main__":
    main()
