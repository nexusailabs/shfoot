"""Opponent-reactive PLAYBOOK selector — team-coherent, pure, deterministic.

The match is decided 100% by deterministic code (policy_v2). This module sits on
the read-only path and only chooses WHICH pre-tuned deterministic playbook each
agent runs. It emits a discrete playbook NAME from policy_v2.PLAYBOOKS.

TEAM COHERENCE (the load-bearing property — Codex review 2026-06-25):
  The 5 agents are SEPARATE processes (separate microVMs). select_playbook() is a
  PURE FUNCTION of the SHARED gameState + team_id + module constants ONLY. It reads
  NO per-process memory (no accumulated window, no hysteresis counter) and writes
  NO state. So all 5 agents independently compute the IDENTICAL playbook from the
  same tick — the team can never split its shape, even across cold restarts.

  Anti-thrash is therefore STRUCTURAL, not memory-based: the classifier keys off
  INTEGER counts of opponents past fixed pitch lines (a player does not cross a
  line every tick) and a gameTime SCOUT gate every agent reads identically. There
  is no per-process accumulation to desync.

CONSERVATIVE + GATED (zero-downside ship):
  - Every counter ships DISABLED (policy_v2.Playbook.enabled=False) -> the deployed
    bot is == DEFAULT (the proven 4/4 floor) until a counter is live-proven.
  - A counter is returned ONLY on a HIGH-CONFIDENCE structural read, after the
    scout window, and (for the attacking press-beater) never while the opponent is
    threatening our goal. Borderline / ambiguous -> DEFAULT (bias to the floor).

NO LLM. The Sonnet path was removed: it perturbed a near-optimal policy and is not
team-coherent across processes. A deterministic classifier is the only selector.
"""

from __future__ import annotations

import policy_v2 as P

# gameTime (s) before any counter may engage — let kickoff shapes settle so the
# opening cluster doesn't trip a counter. All agents read gameTime identically.
SCOUT_SECONDS = 8.0

# HIGH-confidence structural thresholds (integer opponent counts -> flicker-free).
TWO_STRIKER_MIN_IN_THIRD = 2     # opponents camped in OUR defensive third
HIGH_PRESS_MIN_IN_HALF = 3       # opponents committed into OUR half (a real press)

# Fixed pitch lines in attacking-frame fractions (negative = toward OUR goal).
DEF_THIRD_FRAC = 0.30            # afx < -this  => deep in our defensive third
OUR_HALF_FRAC = 0.05             # afx < -this  => past midfield into our half


def _enabled(name: str) -> bool:
    pb = P.PLAYBOOKS.get(name)
    return bool(pb and pb.enabled)


def _opp_threatening_goal(game_state: dict, team_id: int, our_dir: int) -> bool:
    """True iff an OPPONENT currently possesses the ball deep in our defensive
    third. Used to forbid switching to the attacking press-beater shape at a
    dangerous moment (Codex gate: never switch during opp possession near our goal)."""
    try:
        h = P.possession_holder(game_state)
        if h is None or P._is_mine(h, team_id):
            return False
        hx, _ = P._field_xy(h)
        return hx * our_dir < -P._sx(DEF_THIRD_FRAC)
    except Exception:
        return False


def select_playbook(game_state: dict, team_id: int) -> str:
    """Pure, team-coherent playbook choice for THIS tick. Returns a name from
    policy_v2.PLAYBOOKS. Never raises; any fault / ambiguity -> 'DEFAULT'.

    Identical output for all 5 agents given the same gameState (it ignores agent
    identity entirely). Disabled counters are never returned -> shipped == DEFAULT.
    """
    try:
        # Fast out: if no counter is enabled, this is always the proven floor.
        if not (_enabled("TWO_STRIKER_COVER") or _enabled("HIGH_PRESS_BEATER")):
            return "DEFAULT"

        try:
            gt = float(game_state.get("gameTime") or 0.0)
        except (TypeError, ValueError):
            gt = 0.0
        if gt < SCOUT_SECONDS:
            return "DEFAULT"

        team_id = int(team_id or 0)
        our_dir = 1 if team_id == 0 else -1
        players = game_state.get("players") or []
        opponents = [p for p in players if isinstance(p, dict) and not P._is_mine(p, team_id)]
        if not opponents:
            return "DEFAULT"

        in_third = 0
        in_half = 0
        for o in opponents:
            ox, _ = P._field_xy(o)
            afx = ox * our_dir               # attacking-frame x; negative = our half
            if afx < -P._sx(DEF_THIRD_FRAC):
                in_third += 1
            if afx < -P._sx(OUR_HALF_FRAC):
                in_half += 1

        # Priority: TWO_STRIKER (defensive, conceding-risk) before HIGH_PRESS.
        if _enabled("TWO_STRIKER_COVER") and in_third >= TWO_STRIKER_MIN_IN_THIRD:
            return "TWO_STRIKER_COVER"
        if (_enabled("HIGH_PRESS_BEATER") and in_half >= HIGH_PRESS_MIN_IN_HALF
                and not _opp_threatening_goal(game_state, team_id, our_dir)):
            return "HIGH_PRESS_BEATER"
        return "DEFAULT"
    except Exception:
        return "DEFAULT"
