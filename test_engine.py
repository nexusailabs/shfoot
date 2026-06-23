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
        scored = E._check_goal(m)
        self.assertTrue(scored)
        self.assertEqual(m.score_a, 1)
        self.assertEqual(m.players[m.carrier].side, "B")   # conceding side kicks off

    def test_offtarget_does_not_score(self):
        m = E.new_match()
        m.carrier = None
        m.bx, m.by = 1.001, 0.95               # wide of the mouth (|y-0.5| > GOAL_HALF)
        self.assertFalse(E._check_goal(m))
        self.assertEqual(m.score_a, 0)

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
        self.assertGreater(r["possession_pct"]["A"], r["possession_pct"]["B"])


if __name__ == "__main__":
    unittest.main()
