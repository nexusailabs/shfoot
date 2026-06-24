"""Contract-adapter regression tests — the live-#1 root-cause bugs Codex found.
Run: python3 champion/test_contract.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy_v2 as P


def _state(ball_xy, poss_aid=None, poss_team=None, home_pos=None, away_pos=None, stam=100):
    home_pos = home_pos or {0: (-50, 0), 1: (-20, 0), 2: (0, 0), 3: (40, -6), 4: (40, 6)}
    away_pos = away_pos or {0: (50, 0), 1: (20, 0), 2: (0, 5), 3: (38, -6), 4: (38, 6)}
    players = []
    for pid, (x, y) in home_pos.items():
        players.append({"agentId": f"agentId_{pid}", "teamCode": "home", "position": {"x": x, "y": y}, "stamina": stam})
    for pid, (x, y) in away_pos.items():
        players.append({"agentId": f"agentId_{pid}", "teamCode": "away", "position": {"x": x, "y": y}, "stamina": stam})
    ball = {"position": {"x": ball_xy[0], "y": ball_xy[1]}}
    if poss_aid:
        ball["possessionAgentId"] = poss_aid
    if poss_team:
        ball["possessionTeam"] = poss_team
    return {"ball": ball, "score": {"home": 0, "away": 0}, "players": players}


def test_duplicate_agentid_possession_team():
    # Both teams have agentId_3; possession is home's #3 (via possessionTeam).
    gs = _state((40, -6), poss_aid="agentId_3", poss_team="home")
    h = P.possession_holder(gs)
    assert h is not None and h["teamCode"] == "home" and P._pid(h) == 3, h
    # home #3 thinks it has the ball; away #3 does NOT (the ghost bug).
    assert P._parse(gs, 0, 3).i_have_ball is True, "home3 should hold"
    assert P._parse(gs, 1, 3).i_have_ball is False, "away3 must NOT ghost-hold"
    print("OK duplicate-agentId possession (possessionTeam disambiguation)")


def test_duplicate_agentid_nearest_ball():
    # No possessionTeam -> disambiguate by who is ON the ball. Ball at away #3 (38,-6).
    gs = _state((38, -6), poss_aid="agentId_3")
    h = P.possession_holder(gs)
    assert h is not None and h["teamCode"] == "away", f"nearest-to-ball should be away3, got {h}"
    assert P._parse(gs, 1, 3).i_have_ball is True
    assert P._parse(gs, 0, 3).i_have_ball is False
    print("OK duplicate-agentId possession (nearest-to-ball fallback)")


def test_stamina_fraction_not_always_tired():
    gs = _state((0, 0), stam=0.95)            # 0..1 live scale
    v = P._parse(gs, 0, 2)
    assert v.stamina == 95.0, v.stamina
    assert v.stamina >= P.LOW_STAMINA, "0.95 must normalize to 95, not read as tired"
    gs2 = _state((0, 0), stam=95)             # 0..100 scale
    assert P._parse(gs2, 0, 2).stamina == 95.0
    print("OK stamina normalization (0..1 and 0..100)")


def test_shoot_discipline_and_no_ghost_shoot():
    # away #3 (does NOT have ball) must never emit SHOOT.
    gs = _state((40, -6), poss_aid="agentId_3", poss_team="home")
    cmd_away = P.command(gs, 1, 3)
    assert cmd_away["commandType"] != "SHOOT", f"ghost shoot! {cmd_away}"
    # home #3 has the ball near opp goal -> should SHOOT (prob clears 0.40) or pass.
    cmd_home = P.command(gs, 0, 3)
    assert cmd_home["commandType"] in ("SHOOT", "PASS", "MOVE_TO"), cmd_home
    print(f"OK no ghost shoot (away3={cmd_away['commandType']}, home3={cmd_home['commandType']})")


def test_def_marks():
    # DEF off the ball with an intruder near our goal should MARK.
    gs = _state((30, 0), poss_aid="agentId_2", poss_team="away",
                away_pos={0: (50, 0), 1: (20, 0), 2: (30, 0), 3: (-30, -4), 4: (38, 6)})
    cmd = P.command(gs, 0, 1)  # our DEF (id1)
    assert cmd["commandType"] in ("MARK", "PRESS_BALL", "SLIDE_TACKLE", "MOVE_TO"), cmd
    print(f"OK DEF defensive action = {cmd['commandType']}")


if __name__ == "__main__":
    test_duplicate_agentid_possession_team()
    test_duplicate_agentid_nearest_ball()
    test_stamina_fraction_not_always_tired()
    test_shoot_discipline_and_no_ghost_shoot()
    test_def_marks()
    print("\nALL CONTRACT TESTS PASSED")
