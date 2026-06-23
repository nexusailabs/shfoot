"""Regression tests for the offline match simulator (sim/engine.py).

These lock the invariants the 6/24 validation relies on: determinism, mirror
symmetry of self-play, legal action vocabulary, the 500ms budget, and that a
ball crossing the goal mouth actually scores. Pure offline — no AWS, no LLM.
"""

import unittest

from sim import engine as E
from policy import Role


class TestEngine(unittest.TestCase):
    def test_determinism(self):
        r1 = E.run_match(E.squad_brain, E.swarm_brain, ticks=120)
        r2 = E.run_match(E.squad_brain, E.swarm_brain, ticks=120)
        self.assertEqual(r1["score"], r2["score"])
        self.assertEqual(r1["action_hist_A"], r2["action_hist_A"])

    def test_kickoff_gives_ball_to_side_mid_at_center(self):
        m = E.new_match()
        E.kickoff(m, "B")
        self.assertIsNotNone(m.carrier)
        c = m.players[m.carrier]
        self.assertEqual(c.side, "B")
        self.assertEqual(c.role, Role.MID)
        self.assertAlmostEqual(m.bx, 0.5)
        self.assertAlmostEqual(m.by, 0.5)

    def test_goal_scores_and_resets(self):
        m = E.new_match()
        m.carrier = None                       # loose, travelling into A's attacking goal
        m.bx, m.by, m.bvx, m.bvy = 1.001, 0.5, 0.1, 0.0
        scored = E._check_goal(m, 0.9, 0.5)    # came from inside the field
        self.assertTrue(scored)
        self.assertEqual(m.score_a, 1)
        self.assertEqual(m.players[m.carrier].side, "B")   # conceding side kicks off

    def test_offtarget_does_not_score(self):
        m = E.new_match()
        m.carrier = None
        m.bx, m.by = 1.001, 0.95               # wide of the mouth (|y-0.5| > GOAL_HALF)
        self.assertFalse(E._check_goal(m, 0.9, 0.95))
        self.assertEqual(m.score_a, 0)

    def test_fast_diagonal_through_mouth_scores(self):
        # Crosses x=1 inside the mouth but LANDS wide — must still score on the
        # segment crossing, not the post-step point (Codex MAJOR fix).
        m = E.new_match()
        m.carrier = None
        m.bx, m.by = 1.05, 0.80                # ends wide (|0.80-0.5| > GOAL_HALF)
        scored = E._check_goal(m, 0.95, 0.50)  # at x=1 crossing y≈0.5 -> in mouth
        self.assertTrue(scored)
        self.assertEqual(m.score_a, 1)

    def test_kickoff_receiver_not_instantly_stealable(self):
        # The two MIDs must not overlap at restart, else the receiver sits inside
        # the opponent MID's tackle radius on tick 1 (Codex MAJOR fix).
        m = E.new_match()
        E.kickoff(m, "A")
        a_mid = next(p for p in m.players if p.side == "A" and p.idx == 3)
        b_mid = next(p for p in m.players if p.side == "B" and p.idx == 3)
        gap = ((a_mid.x - b_mid.x) ** 2 + (a_mid.y - b_mid.y) ** 2) ** 0.5
        self.assertGreater(gap, E.TACKLE_RADIUS)
        self.assertGreater(gap, E.CONTROL_RADIUS)

    def test_loose_ball_dead_heat_stays_loose(self):
        # Equidistant players from opposite sides on a loose ball -> contested,
        # not handed to the lower index (which was side-A-biased; Codex MAJOR fix).
        m = E.new_match()
        m.carrier = None
        m.bx, m.by, m.bvx, m.bvy = 0.5, 0.5, 0.0, 0.0
        a_mid = next(p for p in m.players if p.side == "A" and p.idx == 3)
        b_mid = next(p for p in m.players if p.side == "B" and p.idx == 3)
        a_mid.x, a_mid.y = 0.49, 0.5           # both exactly 0.01 from the ball
        b_mid.x, b_mid.y = 0.51, 0.5
        E._resolve_possession(m, [{"action": "hold"}] * 10)
        self.assertIsNone(m.carrier)

    def test_self_play_is_mirror_symmetric(self):
        # Same policy on both sides; swapping the kickoff must mirror the result
        # exactly (proves the side-B frame flip + policy are symmetric).
        a = E.run_match(E.squad_brain, E.squad_brain, ticks=200, kickoff_to="A")
        b = E.run_match(E.squad_brain, E.squad_brain, ticks=200, kickoff_to="B")
        self.assertEqual(a["score"], tuple(reversed(b["score"])))

    def test_only_legal_actions_and_budget(self):
        r = E.run_match(E.squad_brain, E.swarm_brain, ticks=150)
        self.assertEqual(r["illegal_actions_A"], 0)
        for act in r["action_hist_A"]:
            self.assertIn(act, E.VALID_ACTIONS)
        self.assertLess(r["max_latency_ms"], 500.0)

    def test_squad_beats_swarm(self):
        r = E.run_match(E.squad_brain, E.swarm_brain, ticks=300)
        self.assertGreater(r["score"][0], r["score"][1])           # outscores
        self.assertGreater(r["spread_A"], r["spread_B"])           # holds shape
        self.assertEqual(r["score"][1], 0)                         # swarm converts nothing

    def test_self_play_is_clean_both_sides(self):
        # Self-play exercises the squad on BOTH sides: neither may emit an illegal
        # action and the real policy must decide every tick (no fallback).
        r = E.run_match(E.squad_brain, E.squad_brain, ticks=200, kickoff_to="B")
        self.assertEqual(r["illegal_actions_A"], 0)
        self.assertEqual(r["illegal_actions_B"], 0)
        self.assertEqual(r["fallbacks"], 0)


if __name__ == "__main__":
    unittest.main()
