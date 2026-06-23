"""
Unit tests for the deterministic policy. Pure stdlib unittest (no pytest dep).
Run: python3 -m unittest -v test_policy

These assert the anti-swarm invariants — the whole reason we win:
a defender far from its zone must NOT chase the ball; only the closest
in-zone teammate engages; the striker shoots in range; the GK stays home.
Action vocabulary matches the official 11 commands (policy.Action).
"""

import unittest

from policy import (
    Action, Role, GameState, Entity, decide_action,
    best_forward_pass, is_open, i_am_closest_to_ball,
    ROLE_ANCHOR, OPP_GOAL,
)

# actions that mean "engage the ball carrier"
ENGAGE = {Action.PRESS, Action.TACKLE, Action.INTERCEPT}


class TestOnBall(unittest.TestCase):
    def test_striker_in_range_shoots(self):
        st = GameState(me=Entity(0.85, 0.5), ball=Entity(0.85, 0.5),
                       i_have_ball=True, has_ball=True)
        self.assertEqual(decide_action(Role.FWD, st).action, Action.SHOOT)

    def test_carrier_passes_to_open_forward(self):
        st = GameState(
            me=Entity(0.5, 0.5), ball=Entity(0.5, 0.5),
            teammates=[Entity(0.75, 0.5)],
            opponents=[Entity(0.55, 0.9)],
            i_have_ball=True, has_ball=True,
        )
        d = decide_action(Role.MID, st)
        self.assertEqual(d.action, Action.PASS)
        self.assertEqual(d.target, (0.75, 0.5))

    def test_carrier_dribbles_when_no_open_man(self):
        st = GameState(
            me=Entity(0.5, 0.5), ball=Entity(0.5, 0.5),
            teammates=[Entity(0.75, 0.5)],
            opponents=[Entity(0.75, 0.5)],            # striker tightly marked
            i_have_ball=True, has_ball=True,
        )
        d = decide_action(Role.MID, st)
        self.assertEqual(d.action, Action.DRIBBLE)
        self.assertEqual(d.target, OPP_GOAL)

    def test_deep_defender_clears_under_pressure(self):
        # DEF_L deep in own half, with ball, opponent breathing down -> CLEAR
        st = GameState(
            me=Entity(0.12, 0.30), ball=Entity(0.12, 0.30),
            teammates=[Entity(0.5, 0.5)],
            opponents=[Entity(0.16, 0.30)],           # right on top of me
            i_have_ball=True, has_ball=True,
        )
        self.assertEqual(decide_action(Role.DEF_L, st).action, Action.CLEAR)


class TestAntiSwarm(unittest.TestCase):
    def test_far_defender_does_not_chase_ball(self):
        st = GameState(
            me=Entity(*ROLE_ANCHOR[Role.DEF_L][:2]),
            ball=Entity(0.8, 0.5),
            teammates=[Entity(0.78, 0.5)],            # a forward is closer
            opponents=[Entity(0.8, 0.5)],
            has_ball=False,
        )
        d = decide_action(Role.DEF_L, st)
        self.assertNotIn(d.action, ENGAGE)
        self.assertIn(d.action, (Action.HOLD, Action.MOVE, Action.MARK))

    def test_only_closest_in_zone_engages(self):
        st = GameState(
            me=Entity(0.5, 0.5), ball=Entity(0.52, 0.5),
            teammates=[Entity(0.25, 0.3), Entity(0.78, 0.5)],
            opponents=[Entity(0.52, 0.5)],
            has_ball=False,
        )
        self.assertTrue(i_am_closest_to_ball(st))
        self.assertIn(decide_action(Role.MID, st).action, ENGAGE)

    def test_out_of_position_moves_to_anchor(self):
        st = GameState(
            me=Entity(0.1, 0.95), ball=Entity(0.6, 0.2),
            teammates=[Entity(0.6, 0.25)],            # someone closer to ball
            opponents=[Entity(0.6, 0.2)],
            has_ball=False,
        )
        d = decide_action(Role.MID, st)
        self.assertEqual(d.action, Action.MOVE)
        self.assertEqual(d.target, ROLE_ANCHOR[Role.MID])

    def test_in_shape_with_possession_supports(self):
        # MID at home, team has ball elsewhere, MID not closest -> SUPPORT
        st = GameState(
            me=Entity(*ROLE_ANCHOR[Role.MID][:2]),
            ball=Entity(0.3, 0.3),
            teammates=[Entity(0.3, 0.3)],             # carrier is closer to ball
            opponents=[Entity(0.9, 0.9)],
            has_ball=True, i_have_ball=False,
        )
        self.assertEqual(decide_action(Role.MID, st).action, Action.SUPPORT)


class TestEngageNuance(unittest.TestCase):
    def test_tackle_when_tight_to_carrier(self):
        # MID closest, ball in zone, opponent right on the ball and very close
        st = GameState(
            me=Entity(0.50, 0.50), ball=Entity(0.51, 0.50),
            teammates=[Entity(0.25, 0.3)],
            opponents=[Entity(0.51, 0.50)],           # on ball, within TACKLE_RANGE
            has_ball=False,
        )
        self.assertEqual(decide_action(Role.MID, st).action, Action.TACKLE)

    def test_intercept_moving_ball_in_lane(self):
        # ball moving toward me, I'm on its short path -> INTERCEPT
        st = GameState(
            me=Entity(0.50, 0.50), ball=Entity(0.40, 0.50, vx=0.2, vy=0.0),
            teammates=[Entity(0.2, 0.3)],
            opponents=[Entity(0.9, 0.9)],
            has_ball=False,
        )
        self.assertEqual(decide_action(Role.MID, st).action, Action.INTERCEPT)

    def test_tired_agent_avoids_pressing(self):
        st = GameState(
            me=Entity(0.50, 0.50, stamina=0.1), ball=Entity(0.52, 0.50),
            teammates=[Entity(0.25, 0.3)],
            opponents=[Entity(0.7, 0.7)],
            has_ball=False,
        )
        self.assertNotIn(decide_action(Role.MID, st).action, ENGAGE)

    def test_far_defender_does_not_intercept_distant_lane(self):
        # Codex blocker: a moving ball up the pitch must NOT pull a deep defender.
        st = GameState(
            me=Entity(0.25, 0.30),                     # DEF_L at home
            ball=Entity(0.80, 0.50, vx=0.2, vy=0.0),   # moving ball far upfield
            teammates=[Entity(0.78, 0.50)],            # forward is closest
            opponents=[Entity(0.9, 0.9)],
            has_ball=False,
        )
        self.assertNotEqual(decide_action(Role.DEF_L, st).action, Action.INTERCEPT)

    def test_exact_distance_tie_only_one_engages(self):
        # Two teammates exactly equidistant to the ball: at most one returns ENGAGE.
        ball = Entity(0.50, 0.50)
        a = Entity(0.50, 0.45)                          # both 0.05 from ball
        b = Entity(0.50, 0.55)
        st_a = GameState(me=a, ball=ball, teammates=[b],
                         opponents=[Entity(0.50, 0.50)], has_ball=False)
        st_b = GameState(me=b, ball=ball, teammates=[a],
                         opponents=[Entity(0.50, 0.50)], has_ball=False)
        engaged = [decide_action(Role.MID, st_a).action in ENGAGE,
                   decide_action(Role.MID, st_b).action in ENGAGE]
        self.assertLessEqual(sum(engaged), 1)


class TestGrayZone(unittest.TestCase):
    def test_boundary_shot_is_gray_zone(self):
        # just inside shot range with an open passer -> SHOOT but flagged gray
        st = GameState(
            me=Entity(0.74, 0.5), ball=Entity(0.74, 0.5),
            teammates=[Entity(0.9, 0.5)],              # open, deeper
            opponents=[Entity(0.1, 0.1)],
            i_have_ball=True, has_ball=True,
        )
        d = decide_action(Role.FWD, st)
        self.assertEqual(d.action, Action.SHOOT)
        self.assertTrue(d.gray_zone)

    def test_pointblank_shot_not_gray(self):
        st = GameState(me=Entity(0.97, 0.5), ball=Entity(0.97, 0.5),
                       i_have_ball=True, has_ball=True)
        d = decide_action(Role.FWD, st)
        self.assertEqual(d.action, Action.SHOOT)
        self.assertFalse(d.gray_zone)


class TestGoalkeeper(unittest.TestCase):
    def test_gk_holds_line_when_ball_upfield(self):
        st = GameState(me=Entity(*ROLE_ANCHOR[Role.GK][:2]), ball=Entity(0.7, 0.5),
                       has_ball=False)
        self.assertEqual(decide_action(Role.GK, st).action, Action.MOVE)

    def test_gk_smothers_in_box_when_closest(self):
        st = GameState(
            me=Entity(0.05, 0.5), ball=Entity(0.10, 0.5),
            teammates=[Entity(0.25, 0.3)],
            opponents=[Entity(0.10, 0.5)],
            has_ball=False,
        )
        self.assertEqual(decide_action(Role.GK, st).action, Action.PRESS)

    def test_gk_distributes_when_holding(self):
        st = GameState(
            me=Entity(0.05, 0.5), ball=Entity(0.05, 0.5),
            teammates=[Entity(0.30, 0.5)],            # open outlet ahead
            opponents=[Entity(0.5, 0.9)],
            i_have_ball=True, has_ball=True,
        )
        self.assertEqual(decide_action(Role.GK, st).action, Action.PASS)

    def test_gk_clears_when_no_outlet(self):
        st = GameState(
            me=Entity(0.05, 0.5), ball=Entity(0.05, 0.5),
            teammates=[Entity(0.30, 0.5)],
            opponents=[Entity(0.30, 0.5)],            # outlet marked
            i_have_ball=True, has_ball=True,
        )
        self.assertEqual(decide_action(Role.GK, st).action, Action.CLEAR)


class TestHelpers(unittest.TestCase):
    def test_is_open_true_and_false(self):
        tm = Entity(0.5, 0.5)
        self.assertTrue(is_open(tm, [Entity(0.9, 0.9)]))
        self.assertFalse(is_open(tm, [Entity(0.52, 0.5)]))

    def test_best_forward_pass_picks_deepest_open(self):
        st = GameState(
            me=Entity(0.3, 0.5), ball=Entity(0.3, 0.5),
            teammates=[Entity(0.5, 0.5), Entity(0.7, 0.5)],
            opponents=[Entity(0.95, 0.95)],
            i_have_ball=True, has_ball=True,
        )
        self.assertEqual(best_forward_pass(st).x, 0.7)

    def test_best_forward_pass_avoids_blocked_lane(self):
        # deepest teammate (0.7) is open at his feet but an opponent sits ON the
        # passing line at 0.5; the clear-lane teammate at 0.5,0.2 should win.
        st = GameState(
            me=Entity(0.3, 0.5), ball=Entity(0.3, 0.5),
            teammates=[Entity(0.5, 0.2), Entity(0.7, 0.5)],
            opponents=[Entity(0.5, 0.5)],            # astride the line to 0.7
            i_have_ball=True, has_ball=True,
        )
        chosen = best_forward_pass(st)
        self.assertEqual((chosen.x, chosen.y), (0.5, 0.2))

    def test_never_returns_none_action_and_valid_command(self):
        import random
        rng = random.Random(42)
        for role in Role:
            for _ in range(200):
                st = GameState(
                    me=Entity(rng.random(), rng.random(), stamina=rng.random()),
                    ball=Entity(rng.random(), rng.random(),
                                vx=rng.uniform(-0.3, 0.3), vy=rng.uniform(-0.3, 0.3)),
                    teammates=[Entity(rng.random(), rng.random()) for _ in range(4)],
                    opponents=[Entity(rng.random(), rng.random()) for _ in range(5)],
                    has_ball=rng.random() < 0.5,
                    i_have_ball=rng.random() < 0.2,
                )
                d = decide_action(role, st)
                self.assertIsInstance(d.action, Action)


if __name__ == "__main__":
    unittest.main(verbosity=2)
