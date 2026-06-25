"""Two-timescale attacking adaptation for the champion policy.

The per-tick policy remains deterministic and never calls Bedrock. This module
only keeps a compact rolling opponent window and lets one daemon thread refresh
per-player attack-shaping tactics opportunistically. If anything fails,
current_tactics() returns neutral and policy_v2 behaves exactly as before.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import deque

SLOW_PERIOD_S = 8.0
TACTICS_STALE_S = 20.0
WINDOW_CAP = 120
MODEL_ID = "us.anthropic.claude-sonnet-4-6"
REGION = "us-east-1"
# SHIPPED CONFIG = pure deterministic (proxy verdict 2026-06-25, operator A): the LLM
# slow loop is OFF by default — it measurably underperformed the hand-tuned attack-always
# policy on every testable opponent (agg 4/4 -> 1/3, defensive 4-0/6-0 -> 0-0) by perturbing
# a near-optimal policy. The code stays as a flag-gated lever: flip to True to re-enable the
# Sonnet adaptation as a tournament hedge vs genuinely ADAPTING expert opponents.
HYBRID_ENABLED = False
NEUTRAL = {"attack_zone": None, "push": 0.0, "exploit_opp_id": None, "tempo": "direct", "notes": ""}

ALLOWED_KEYS = {"attack_zone", "push", "exploit_opp_id", "tempo", "notes"}
FORBIDDEN_KEYS = {
    "attack_side", "danger_opp_id", "press_level", "danger_mark", "mark",
    "mark_id", "drop", "drop_deeper", "sit_deeper", "defend", "defense",
}

BASE_PERSONA = (
    "You are an ELITE, RELENTLESSLY ATTACKING 5-a-side football manager. "
    "This is a 2-MINUTE SPRINT: sitting on a lead LOSES because the equalizer always comes. "
    "You ALWAYS attack. You NEVER advise defending, sitting deeper, parking, or pressing-to-protect. "
    "Your ONLY job is to make THIS player create and score MORE. "
    "Be decisive and aggressive."
)

ROLE_FLAVOR = {
    "FWD1": "THIS player is a ruthless poacher: gamble on the last shoulder, attack in behind, get shots off fast.",
    "FWD2": "THIS player is a ruthless poacher: gamble on the last shoulder, attack in behind, get shots off fast.",
    "MID": "THIS player is a press-resistant creator: drive forward, slip throughballs, arrive late in the box.",
    "DEF": "THIS player is an aggressive ball-winner who springs the counter INSTANTLY and steps up; never parks.",
    "GK": "THIS player is a fast-launch goalkeeper: distribute forward immediately to start attacks.",
}


def _policy():
    import policy_v2 as P
    return P


def _mem():
    P = _policy()
    mem = P._STATE.setdefault("mem", {})
    if not isinstance(mem.get("window"), deque):
        mem["window"] = deque(mem.get("window", []), maxlen=WINDOW_CAP)
    mem.setdefault("threads", {})
    return mem


def _xy(entity: dict) -> tuple[float, float]:
    pos = entity.get("position", entity) if isinstance(entity, dict) else {}
    depth_key = "z" if "z" in pos else "y"
    return float(pos.get("x", 0.0) or 0.0), float(pos.get(depth_key, 0.0) or 0.0)


def _pid(p: dict) -> int:
    if not isinstance(p, dict):
        return 0
    if "agentId" in p:
        try:
            return int(str(p["agentId"]).rsplit("_", 1)[-1])
        except Exception:
            return 0
    try:
        return int(p.get("playerId", 0) or 0)
    except Exception:
        return 0


def _is_mine(p: dict, team_id: int) -> bool:
    if not isinstance(p, dict):
        return False
    if "teamCode" in p:
        return p.get("teamCode") == ("home" if team_id == 0 else "away")
    return p.get("teamId") == team_id


def _holder(game_state: dict):
    try:
        P = _policy()
        return P.possession_holder(game_state)
    except Exception:
        return None


def _side(y: float) -> str:
    P = _policy()
    if y < -P._sz(0.18):
        return "L"
    if y > P._sz(0.18):
        return "R"
    return "C"


def observe(game_state, team_id) -> None:
    """Append one compact opponent snapshot. Best-effort and never raises."""
    try:
        if not isinstance(game_state, dict):
            return
        team_id = int(team_id or 0)
        P = _policy()
        players = game_state.get("players") or []
        opponents = [p for p in players if isinstance(p, dict) and not _is_mine(p, team_id)]
        mine = [p for p in players if isinstance(p, dict) and _is_mine(p, team_id)]
        if not opponents:
            return
        ball = game_state.get("ball") or {}
        ball_xy = _xy(ball)
        my_goal_x, _ = P.goal_x(team_id)
        opp_dir = -1 if team_id == 0 else 1
        holder = _holder(game_state)
        opp_holder = holder if holder is not None and not _is_mine(holder, team_id) else None
        our_holder = holder if holder is not None and _is_mine(holder, team_id) else None

        opp_xs = [_xy(o)[0] * opp_dir / P.FIELD_X for o in opponents]
        opp_mean_ax = sum(opp_xs) / len(opp_xs)
        carrier_x = None
        carrier_side = None
        shot_origin = None
        if opp_holder is not None:
            cx, cy = _xy(opp_holder)
            carrier_x = cx * opp_dir / P.FIELD_X
            carrier_side = _side(cy)
            if abs(cx - my_goal_x) < P._sx(0.42):
                shot_origin = {"x": round(cx, 2), "side": carrier_side, "pid": _pid(opp_holder)}

        nearest_presser = None
        if our_holder is not None and opponents:
            hx, hy = _xy(our_holder)
            nearest_presser = min(math.hypot(hx - _xy(o)[0], hy - _xy(o)[1]) for o in opponents)

        third = {}
        for o in opponents:
            ox, _ = _xy(o)
            if abs(ox - my_goal_x) < P._sx(0.82):
                third[_pid(o)] = 1

        sample = {
            "t": float(game_state.get("gameTime") or 0.0),
            "opp_mean_ax": round(opp_mean_ax, 3),
            "opp_mean_side": _side(sum(_xy(o)[1] for o in opponents) / len(opponents)),
            "carrier_x": None if carrier_x is None else round(carrier_x, 3),
            "carrier_side": carrier_side,
            "shot_origin": shot_origin,
            "nearest_presser": None if nearest_presser is None else round(nearest_presser, 3),
            "third": third,
            "ball": (round(ball_xy[0], 2), round(ball_xy[1], 2)),
        }
        _mem()["window"].append(sample)
    except Exception:
        return


def _validate_tactics(obj) -> dict:
    if not isinstance(obj, dict):
        return dict(NEUTRAL)
    if any(k not in ALLOWED_KEYS for k in obj):
        return dict(NEUTRAL)
    if any(k in FORBIDDEN_KEYS for k in obj):
        return dict(NEUTRAL)
    out = dict(NEUTRAL)
    if "attack_zone" in obj:
        if obj.get("attack_zone") is None:
            out["attack_zone"] = None
        elif obj.get("attack_zone") in ("L", "C", "R"):
            out["attack_zone"] = obj.get("attack_zone")
        else:
            return dict(NEUTRAL)
    if "push" in obj:
        try:
            push = float(obj.get("push"))
        except (TypeError, ValueError):
            return dict(NEUTRAL)
        if not math.isfinite(push) or push < 0.0 or push > 1.0:
            return dict(NEUTRAL)
        out["push"] = push
    try:
        exploit = obj.get("exploit_opp_id")
        if exploit is None:
            out["exploit_opp_id"] = None
        else:
            exploit = int(exploit)
            if 0 <= exploit <= 4:
                out["exploit_opp_id"] = exploit
            else:
                return dict(NEUTRAL)
    except Exception:
        return dict(NEUTRAL)
    if "tempo" in obj:
        if obj.get("tempo") in ("direct", "patient"):
            out["tempo"] = obj.get("tempo")
        else:
            return dict(NEUTRAL)
    notes = obj.get("notes")
    if isinstance(notes, str):
        out["notes"] = notes[:180]
    elif notes is not None:
        return dict(NEUTRAL)
    return out


def current_tactics() -> dict:
    try:
        P = _policy()
        rec = P._STATE.get("tactics")
        if not isinstance(rec, dict):
            return dict(NEUTRAL)
        value = _validate_tactics(rec.get("value"))
        if value == NEUTRAL:
            return dict(NEUTRAL)
        stamp = rec.get("wall_mono")
        if stamp is None or time.monotonic() - float(stamp) > TACTICS_STALE_S:
            return dict(NEUTRAL)
        return value
    except Exception:
        return dict(NEUTRAL)


def _summary(team_id: int, position_label: str) -> str:
    P = _policy()
    window = list(_mem().get("window") or [])
    if not window:
        return ""
    recent = window[-120:]
    n = len(recent)
    sides = {"L": 0, "C": 0, "R": 0}
    carrier_sides = {"L": 0, "C": 0, "R": 0}
    third_counts = {i: 0 for i in range(5)}
    shot_sides = {"L": 0, "C": 0, "R": 0}
    press_vals = []
    mean_ax = []
    carrier_ax = []
    for s in recent:
        sides[s.get("opp_mean_side", "C")] = sides.get(s.get("opp_mean_side", "C"), 0) + 1
        if s.get("carrier_side"):
            carrier_sides[s["carrier_side"]] = carrier_sides.get(s["carrier_side"], 0) + 1
        if s.get("carrier_x") is not None:
            carrier_ax.append(s["carrier_x"])
        if s.get("opp_mean_ax") is not None:
            mean_ax.append(s["opp_mean_ax"])
        if s.get("nearest_presser") is not None:
            press_vals.append(s["nearest_presser"])
        for pid, inc in (s.get("third") or {}).items():
            try:
                pid = int(pid)
                if 0 <= pid <= 4:
                    third_counts[pid] += int(inc)
            except Exception:
                continue
        so = s.get("shot_origin")
        if isinstance(so, dict):
            shot_sides[so.get("side", "C")] = shot_sides.get(so.get("side", "C"), 0) + 1

    mean_press = sum(press_vals) / len(press_vals) if press_vals else None
    lines = [
        f"team_id={team_id} position={position_label} samples={n} window_gameTime={recent[0].get('t')}..{recent[-1].get('t')}",
        f"opponent mean attack x toward our goal: avg={round(sum(mean_ax)/len(mean_ax),3) if mean_ax else 'n/a'}",
        f"opponent team flank occupancy counts L/C/R={sides}",
        f"opponent ball-carrier x toward our goal avg={round(sum(carrier_ax)/len(carrier_ax),3) if carrier_ax else 'n/a'}",
        f"opponent ball-carrier side counts L/C/R={carrier_sides}",
        f"potential shot origins near our goal by side L/C/R={shot_sides}",
        f"nearest opponent presser distance to our carrier avg={round(mean_press,3) if mean_press is not None else 'n/a'} field_units (small means high press)",
        f"per-opponent ticks in our defensive third={third_counts}",
        f"field scale: FIELD_X={P.FIELD_X}, FIELD_Z={P.FIELD_Z}",
    ]
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _role_flavor(position_label: str) -> str:
    pos = str(position_label or "").upper()
    return ROLE_FLAVOR.get(pos, ROLE_FLAVOR["MID"])


def _system_prompt(position_label: str) -> str:
    return (
        f"{BASE_PERSONA}\n"
        f"{_role_flavor(position_label)}\n"
        "Output ONLY one JSON object for THIS player. All fields are optional and omitted fields are neutral. "
        "Allowed schema: {\"attack_zone\":\"L\"|\"C\"|\"R\", \"push\":0.0..1.0, "
        "\"exploit_opp_id\":0..4|null, \"tempo\":\"direct\"|\"patient\", \"notes\":\"short text\"}. "
        "attack_zone means the channel THIS player should attack. push only ADDS forward commitment. "
        "exploit_opp_id means an opponent to attack PAST or behind, never to mark. "
        "FORBIDDEN: defending, sitting deeper, parking, pressing to protect, marking, press_level, danger_mark, "
        "danger_opp_id, or any field/action that reduces attack."
    )


def _bedrock_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "bedrock-runtime",
        region_name=REGION,
        config=Config(connect_timeout=2, read_timeout=6, retries={"max_attempts": 1}),
    )


def _call_sonnet(client, summary: str, position_label: str) -> dict:
    system = _system_prompt(position_label)
    user = "Numeric opponent summary:\n" + summary
    resp = client.converse(
        modelId=MODEL_ID,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"temperature": 0.8, "maxTokens": 300},  # HIGH: escape the bland mean — persona+schema are the guardrails
    )
    parts = resp.get("output", {}).get("message", {}).get("content", [])
    text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return _validate_tactics(_extract_json(text))


def _slow_worker(team_id: int, position_label: str) -> None:
    client = None
    while True:
        try:
            time.sleep(SLOW_PERIOD_S)
            summary = _summary(team_id, position_label)
            if not summary:
                continue
            if client is None:
                client = _bedrock_client()
            tactics = _call_sonnet(client, summary, position_label)
            P = _policy()
            window = list(_mem().get("window") or [])
            game_t = window[-1].get("t") if window else None
            P._STATE["tactics"] = {
                "value": tactics,
                "gameTime": game_t,
                "wall_mono": time.monotonic(),
                "wall_time": time.time(),
                "source": "bedrock-converse",
            }
            # firing-verification log (CloudWatch): proves the Sonnet slow loop ran.
            print("FCSLOW " + json.dumps({"pos": position_label, "gameTime": game_t,
                  "samples": len(window), "tactics": tactics}), flush=True)
        except Exception as _e:
            # FAIL-SAFE (Codex gate): on ANY call/parse failure, drop to NEUTRAL
            # immediately — never let stale non-neutral tactics linger. Neutral ==
            # the attack-always deterministic bot (the proven 4/4 spine).
            client = None
            try:
                _policy()._STATE.pop("tactics", None)
            except Exception:
                pass
            print("FCSLOW_ERR " + str(_e)[:200], flush=True)
            continue


def start_slow_loop(team_id, position_label) -> None:
    """Start one daemon slow-loop thread per process. Idempotent.
    No-op when HYBRID_ENABLED is False -> the bot is PURE deterministic (shipped config)."""
    if not HYBRID_ENABLED:
        return
    try:
        team_id = int(team_id or 0)
        mem = _mem()
        key = "slow"
        th = (mem.get("threads") or {}).get(key)
        if th is not None and th.is_alive():
            return
        th = threading.Thread(target=_slow_worker, args=(team_id, str(position_label)), daemon=True)
        mem.setdefault("threads", {})[key] = th
        th.start()
    except Exception:
        return
