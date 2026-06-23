"""
Agentic Football Cup — Strands squad wiring (Pillar 1 + 3).

Architecture: a fixed 5-node role Graph (not a Swarm) so behaviour is
predictable and ball-chasing cannot re-emerge. Each role agent:
  * has a terse role system prompt (prompts/*.md),
  * calls the deterministic `decide` tool first (policy.py),
  * only "thinks" with the LLM when the tool returns a gray-zone tie.

[VERIFIED] Strands public API used below:
    from strands import Agent, tool
    from strands.models import BedrockModel
    from strands.multiagent import GraphBuilder
[ASSUMPTION] The exact way the Cup runtime feeds per-tick GameState into each
agent and reads back the action is NOT yet known (Player Portal is gated).
On 6/24, plug the runtime's observation dict into `state_from_obs()` and return
`Decision.action` in whatever shape the runtime expects. Everything below the
`decide` tool transfers unchanged.

This file is import-guarded: it runs with or without strands installed, so the
deterministic core stays testable offline. `python3 squad.py --selftest`
exercises the policy through the tool path without any AWS calls.
"""

from __future__ import annotations

import json
import sys

from policy import (
    Role, GameState, Entity, Decision, Action, decide_action, ROLE_ANCHOR,
)

# Runtime may label roles differently than our enum values. Map known aliases;
# anything unrecognised falls back to MID (a safe central anchor) rather than
# raising and killing the tick. Confirm the portal's real role names on 6/24.
ROLE_ALIASES = {
    "gk": Role.GK, "goalkeeper": Role.GK, "keeper": Role.GK,
    "def_l": Role.DEF_L, "def_r": Role.DEF_R, "def": Role.DEF_L,
    "defender": Role.DEF_L, "leftback": Role.DEF_L, "rightback": Role.DEF_R,
    "lb": Role.DEF_L, "rb": Role.DEF_R, "cb": Role.DEF_L,
    "mid": Role.MID, "midfielder": Role.MID, "cm": Role.MID,
    "fwd": Role.FWD, "forward": Role.FWD, "striker": Role.FWD, "st": Role.FWD,
}

# The 11 legal action strings — anything outside this set must never reach the
# runtime (an illegal action = no-op or disqualification).
VALID_ACTIONS = {a.value for a in Action}


def resolve_role(role_name) -> Role:
    """role label (enum / our value / portal alias) -> Role, never raises."""
    if isinstance(role_name, Role):
        return role_name
    key = str(role_name).strip()
    try:
        return Role(key)
    except ValueError:
        return ROLE_ALIASES.get(key.lower(), Role.MID)


def valid_runtime_action(payload) -> bool:
    """True only if payload is a dict carrying one of the 11 legal actions."""
    if not isinstance(payload, dict) or payload.get("action") not in VALID_ACTIONS:
        return False
    tgt = payload.get("target")
    return tgt is None or (
        isinstance(tgt, dict)
        and isinstance(tgt.get("x"), (int, float))
        and isinstance(tgt.get("y"), (int, float))
    )

# [VERIFIED] model is free choice (Nova / Claude / any Bedrock model). A light,
# fast model keeps us inside the <500ms return budget; heavy reasoning is
# precomputed in policy.py. Bump to Claude only if a role's gray-zone ties
# genuinely need it and latency still clears 500ms.
MODEL_ID = "amazon.nova-lite-v1:0"

ROLE_PROMPT_FILE = {
    Role.GK: "prompts/gk.md",
    Role.DEF_L: "prompts/def.md",
    Role.DEF_R: "prompts/def.md",
    Role.MID: "prompts/mid.md",
    Role.FWD: "prompts/fwd.md",
}


# --------------------------------------------------------------------------- #
# runtime <-> policy adapter (the ONE place to fix on 6/24)                   #
# --------------------------------------------------------------------------- #
def state_from_obs(obs: dict) -> GameState:
    """Map the Cup runtime's observation dict -> our GameState.

    [ASSUMPTION] field names below follow the Google-Research-Football-style
    schema. Rename to match the real keys once the workshop materials are in.
    """
    def ent(d: dict) -> Entity:
        return Entity(d.get("x", 0.0), d.get("y", 0.0),
                      d.get("vx", 0.0), d.get("vy", 0.0),
                      d.get("stamina", 1.0))

    return GameState(
        me=ent(obs["me"]),
        ball=ent(obs["ball"]),
        teammates=[ent(t) for t in obs.get("teammates", [])],
        opponents=[ent(o) for o in obs.get("opponents", [])],
        has_ball=bool(obs.get("team_has_ball", False)),
        i_have_ball=bool(obs.get("i_have_ball", False)),
        my_score=int(obs.get("my_score", 0)),
        opp_score=int(obs.get("opp_score", 0)),
    )


def action_to_runtime(d: Decision) -> dict:
    """Map our Decision -> the runtime action payload. [ASSUMPTION] shape."""
    out: dict = {"action": d.action.value}
    if d.target is not None:
        out["target"] = {"x": d.target[0], "y": d.target[1]}
    return out


# --------------------------------------------------------------------------- #
# PRIMARY per-tick entry point — pure deterministic, ZERO LLM                  #
# --------------------------------------------------------------------------- #
# This is what the Cup runtime should call every tick. It runs the policy in
# microseconds with no model round-trip, so the <500ms budget is met with huge
# margin even under bad venue WiFi. The Strands Agent wrapper below is OPTIONAL
# and only earns its latency on decisions flagged gray_zone (see act_or_escalate).
def act(role_name: str, obs: dict) -> dict:
    """role + observation dict -> runtime action dict. Deterministic, no LLM."""
    role = resolve_role(role_name)            # never raises (alias-mapped)
    try:
        d = decide_action(role, state_from_obs(obs))
    except Exception:
        d = Decision(Action.MOVE, ROLE_ANCHOR[role], "fallback")
    return action_to_runtime(d)


def decide_full(role_name: str, obs: dict) -> Decision:
    """Same as act() but returns the raw Decision (carries .gray_zone)."""
    role = resolve_role(role_name)            # never raises (alias-mapped)
    try:
        return decide_action(role, state_from_obs(obs))
    except Exception:
        return Decision(Action.MOVE, ROLE_ANCHOR[role], "fallback")


def _decide_impl(role_name: str, obs_json: str) -> str:
    """JSON-string wrapper of act(), for use as a Strands @tool. Terse output."""
    return json.dumps(act(role_name, json.loads(obs_json)), separators=(",", ":"))


# --------------------------------------------------------------------------- #
# Strands agents (only if strands is installed)                               #
# --------------------------------------------------------------------------- #
# PRIMARY integration path. [VERIFIED] the Cup spec says "each agent receives
# the full game state every 2s and returns a decision" -> the Cup RUNTIME drives
# each player-agent independently per tick. So the thing that actually ships is
# FIVE role `Agent` definitions; the runtime calls each one. We do NOT need a
# multi-agent Graph to orchestrate handoffs between them (that would be the wrong
# abstraction and risks re-introducing ball-chasing via auto-handoff tools).


def _make_decide_tool():
    from strands import tool

    @tool
    def decide(role: str, observation: str) -> str:
        """Return the optimal football action for `role` given the JSON
        `observation` of the current tick. Always call this FIRST and return
        its output verbatim unless two actions are genuinely tied."""
        return _decide_impl(role, observation)

    return decide


def build_role_agents() -> dict:
    """Build the five role `Agent` instances for the OPTIONAL LLM path.

    The fast per-tick path is the deterministic `act()` above (no LLM). These
    agents are only needed if you run `act_or_escalate()` to let the model
    arbitrate gray-zone ticks, or if the portal requires registered Agents.
    Requires strands."""
    from strands import Agent
    from strands.models import BedrockModel

    decide = _make_decide_tool()
    # max_tokens must leave room for the tool-call payload; 32 truncates it.
    # Terseness is enforced inside the tool's output, not by starving the model.
    model = BedrockModel(model_id=MODEL_ID, temperature=0.2, max_tokens=256)

    agents = {}
    for role, pf in ROLE_PROMPT_FILE.items():
        with open(pf, encoding="utf-8") as fh:
            sys_prompt = fh.read()
        agents[role] = Agent(
            name=role.value,
            model=model,
            system_prompt=sys_prompt,
            tools=[decide],
        )
    return agents


def act_or_escalate(role_name: str, obs: dict, agent=None) -> dict:
    """Hybrid per-tick entry: deterministic by default, LLM ONLY on gray zones.

    This is the concrete implementation of the "LLM only for genuine ties"
    design (Codex blocker: previously described but unimplemented). The fast
    path costs no model round-trip. We escalate to the role `agent` strictly
    when the deterministic policy itself flags the decision ambiguous
    (Decision.gray_zone) AND an agent was supplied — so 95%+ of ticks never
    touch the LLM and the 500ms budget is trivially met.
    """
    d = decide_full(role_name, obs)
    if not d.gray_zone or agent is None:
        return action_to_runtime(d)
    try:
        # Ask the LLM to choose; it calls the same `decide` tool and may override
        # only at the boundary. Keep the prompt tiny to stay within budget.
        reply = agent(json.dumps({"role": role_name, "obs": obs,
                                  "policy_suggests": d.action.value}))
        text = getattr(reply, "message", None) or str(reply)
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            candidate = json.loads(text[start:end + 1])
            # NEVER pass unvalidated LLM output to the runtime: an out-of-vocab
            # action or malformed target = no-op / disqualification. Accept only
            # one of the 11 legal actions with a well-formed target.
            if valid_runtime_action(candidate):
                return candidate
    except Exception:
        pass
    return action_to_runtime(d)   # any failure / invalid LLM -> deterministic call


def build_squad_graph():
    """OPTIONAL: wrap the five agents in a no-edge Strands Graph (all nodes are
    independent entry points). Only use this if the on-site portal expects a
    single Graph artifact rather than five separate agents. Default to
    build_role_agents() until the portal's integration shape is confirmed."""
    from strands.multiagent import GraphBuilder

    gb = GraphBuilder()
    for role, ag in build_role_agents().items():
        gb.add_node(ag, role.value)
    return gb.build()


# --------------------------------------------------------------------------- #
# offline self-test (no AWS, no strands)                                      #
# --------------------------------------------------------------------------- #
def _selftest() -> None:
    obs = {
        "me": {"x": 0.85, "y": 0.5},
        "ball": {"x": 0.85, "y": 0.5},
        "teammates": [], "opponents": [],
        "team_has_ball": True, "i_have_ball": True,
    }
    out = _decide_impl("FWD", json.dumps(obs))
    print("FWD on ball near goal ->", out)
    assert json.loads(out)["action"] == "shoot", out

    obs2 = {
        "me": {"x": ROLE_ANCHOR[Role.DEF_L][0], "y": ROLE_ANCHOR[Role.DEF_L][1]},
        "ball": {"x": 0.8, "y": 0.5},
        "teammates": [{"x": 0.78, "y": 0.5}],
        "opponents": [{"x": 0.8, "y": 0.5}],
        "team_has_ball": False, "i_have_ball": False,
    }
    out2 = _decide_impl("DEF_L", json.dumps(obs2))
    print("far DEF, ball upfield  ->", out2)
    assert json.loads(out2)["action"] not in ("press", "tackle", "intercept"), out2
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: python3 squad.py --selftest   (build_role_agents() needs strands installed)")
