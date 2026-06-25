"""Contract-adapter regression tests — the live-#1 root-cause bugs Codex found.
Run: python3 champion/test_contract.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy_v2 as P


def _state(ball_xy, poss_aid=None, poss_team=None, home_pos=None, away_pos=None, stam=100):
    home_pos = home_pos or {0: (-6.4, 0), 1: (-3.0, 0), 2: (0, 0), 3: (5.0, -0.8), 4: (5.0, 0.8)}
    away_pos = away_pos or {0: (6.4, 0), 1: (3.0, 0), 2: (0, 0.6), 3: (4.8, -0.8), 4: (4.8, 0.8)}
    players = []
    for pid, (x, y) in home_pos.items():
        players.append({"agentId": f"agentId_{pid}", "teamCode": "home", "position": {"x": x, "y": y}, "stamina": stam})
    for pid, (x, y) in away_pos.items():
        players.append({"agentId": f"agentId_{pid}", "teamCode": "away", "position": {"x": x, "y": y}, "stamina": stam})
    ball = {"position": {"x": ball_xy[0], "y": 0.10, "z": ball_xy[1]}}
    if poss_aid:
        ball["possessionAgentId"] = poss_aid
    if poss_team:
        ball["possessionTeam"] = poss_team
    return {"ball": ball, "score": {"home": 0, "away": 0}, "players": players}


def test_duplicate_agentid_possession_team():
    # Both teams have agentId_3; possession is home's #3 (via possessionTeam).
    gs = _state((5.0, -0.8), poss_aid="agentId_3", poss_team="home")
    h = P.possession_holder(gs)
    assert h is not None and h["teamCode"] == "home" and P._pid(h) == 3, h
    # home #3 thinks it has the ball; away #3 does NOT (the ghost bug).
    assert P._parse(gs, 0, 3).i_have_ball is True, "home3 should hold"
    assert P._parse(gs, 1, 3).i_have_ball is False, "away3 must NOT ghost-hold"
    print("OK duplicate-agentId possession (possessionTeam disambiguation)")


def test_duplicate_agentid_nearest_ball():
    # No possessionTeam -> disambiguate by who is ON the ball. Ball at away #3.
    gs = _state((4.8, -0.8), poss_aid="agentId_3")
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
    gs = _state((5.0, -0.8), poss_aid="agentId_3", poss_team="home")
    cmd_away = P.command(gs, 1, 3)
    assert cmd_away["commandType"] != "SHOOT", f"ghost shoot! {cmd_away}"
    # home #3 has the ball near opp goal -> should SHOOT (prob clears 0.40) or pass.
    cmd_home = P.command(gs, 0, 3)
    assert cmd_home["commandType"] in ("SHOOT", "PASS", "MOVE_TO"), cmd_home
    print(f"OK no ghost shoot (away3={cmd_away['commandType']}, home3={cmd_home['commandType']})")


def test_def_marks():
    # DEF off the ball with an intruder near our goal should MARK.
    gs = _state((4.0, 0), poss_aid="agentId_2", poss_team="away",
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (4.0, 0), 3: (-5.5, -0.6), 4: (4.8, 0.8)})
    cmd = P.command(gs, 0, 1)  # our DEF (id1)
    assert cmd["commandType"] in ("MARK", "PRESS_BALL", "SLIDE_TACKLE", "MOVE_TO"), cmd
    print(f"OK DEF defensive action = {cmd['commandType']}")


def test_formation_role_mapping():
    # playerId is separate from tactical slot; 1-1-2 is identity, others remap.
    assert P.role_for_player(2, "1-1-2") == P.MID
    assert P.role_for_player(2, "2-1-1") == P.DEF2
    assert P.role_for_player(3, "2-1-1") == P.MID
    assert P.role_for_player(4, "2-1-1") == P.FWD1
    assert P.role_for_player(3, "1-2-1") == P.MID2
    # every player decides without crashing under every formation
    gs = _state((0.0, 0.0))
    for f in P.FORMATIONS:
        for pid in range(5):
            c = P.command(gs, 0, pid, f)
            assert c["commandType"], (f, pid, c)
    print("OK formation role mapping + all formations decide")


def test_single_presser_invariant_all_formations():
    # The anti-swarm core: at most ONE outfielder presses/tackles in any formation.
    gs = _state((0.5, 0.2))   # loose ball near center, nobody possesses
    for f in ("1-1-2", "2-1-1", "1-2-1"):
        pressers = sum(
            1 for pid in range(1, 5)
            if P.command(gs, 0, pid, f)["commandType"] in ("PRESS_BALL", "SLIDE_TACKLE")
        )
        assert pressers <= 1, (f, pressers)
    print("OK single-presser invariant holds under all formations")


def test_game_management_scaling():
    early = type("V", (), {"gt": 30.0, "goal_diff": -1})()
    lead = type("V", (), {"gt": 110.0, "goal_diff": 1})()
    chase = type("V", (), {"gt": 110.0, "goal_diff": -1})()
    assert P._game_mode(early)["risk"] == 1.0, "first 60s must be neutral"
    m_lead = P._game_mode(lead)
    # 2-min shootout: NO lead-protect — leading keeps attacking (neutral), never sits.
    assert m_lead["risk"] == 1.0 and m_lead["push_delta"] == 0.0, "lead late must NOT sit deeper"
    m_chase = P._game_mode(chase)
    assert m_chase["risk"] > 1.0 and m_chase["push_delta"] > 0, "chase late -> commit more attack"
    print("OK game-management (attack-always: no lead-protect, chase boosts attack)")


def test_mixing_reproducible_and_safe():
    # same state -> identical command (deterministic mixing = exact offline replay)
    gs = _state((5.0, -0.8), poss_aid="agentId_3", poss_team="home")
    c1 = P.command(gs, 0, 3)
    c2 = P.command(gs, 0, 3)
    assert c1 == c2, "mixing must be deterministic for a fixed state"
    # shot mixing keeps the keeper-away horizontal side; only T/B varies
    if c1["commandType"] == "SHOOT":
        assert c1["parameters"]["aim_location"][1] in ("L", "R"), c1
    print(f"OK mixing reproducible + aim-safe (home3={c1['commandType']})")


def test_mid_drop_mark_second_striker():
    # two away attackers deep in OUR third (ball with one) -> our MID drops to mark.
    gs = _state((-4.0, 0.5), poss_aid="agentId_3", poss_team="away",
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (0.0, 0.6),
                          3: (-4.0, 0.5), 4: (-3.6, -0.8)})
    c = P.command(gs, 0, 2)  # our MID (id2)
    assert c["commandType"] == "MARK", f"MID should drop-mark the 2nd striker, got {c}"
    print(f"OK MID drop-mark fires = {c['commandType']} -> {c['parameters'].get('target_player_id')}")


def test_pressure_release_is_formation_aware():
    # pid3 is FWD1 in 1-1-2 but MID in 2-1-1. With two otherwise-equal outlets
    # (pid3, pid4), the release must prefer the actual FORWARD slot, not raw pid3.
    v = P.View(me={}, me_xy=(-2.0, 0.0), ball_xy=(-2.0, 0.0), teammates=[], opponents=[],
               poss=None, i_have_ball=True, we_have_ball=True, team_id=0,
               my_goal_x=-6.4, opp_goal_x=6.4, dir=1, stamina=100.0)
    shot = {"dist": 6.0, "prob": 0.1, "aim": "TR", "power": 0.7, "should_shoot": False}

    def _opt(pid):
        return {"pid": pid, "x": 0.5, "y": 0.0, "dist": 3.0, "risk": 0.2, "success": 0.7, "type": "THROUGH"}

    scored = [(_opt(3), shot), (_opt(4), shot)]
    # 2-1-1: pid4=FWD1 (forward) must beat pid3=MID. (Raw-pid bug would tie them.)
    rel = P._pressure_release_option(v, scored, 0.0, "2-1-1")
    assert rel is not None and rel["pid"] == 4, f"2-1-1 release should prefer FWD pid4, got {rel}"
    print("OK pressure-release is formation-aware (prefers true forward slot)")


def test_no_double_mark_multi_defender():
    # 2-1-1 has TWO defenders (pid1=DEF, pid2=DEF2). With two intruders deep in our
    # third, the defenders must mark DIFFERENT opponents (no swarm leak).
    gs = _state((-5.0, 0.5), poss_team="away", poss_aid="agentId_3",
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (0.0, 0.0),
                          3: (-5.0, 0.5), 4: (-4.6, -0.6)})
    c1 = P.command(gs, 0, 1, "2-1-1")  # DEF
    c2 = P.command(gs, 0, 2, "2-1-1")  # DEF2
    targets = [c["parameters"]["target_player_id"] for c in (c1, c2) if c["commandType"] == "MARK"]
    assert len(set(targets)) == len(targets), f"defenders double-marked: {c1}, {c2}"
    print(f"OK no double-mark in 2-1-1 (DEF={c1['commandType']}, DEF2={c2['commandType']}, targets={targets})")


def test_no_double_team_lone_carrier():
    # Lone attacker (away2) carrying the ball, our MID (id2) is the active presser.
    # The presser must own the carrier; DEF must NOT also mark the same lone carrier.
    gs = _state((-2.5, 0.0), poss_team="away", poss_aid="agentId_2",
                home_pos={0: (-6.4, 0), 1: (-4.0, 0.0), 2: (-2.4, 0.0), 3: (2.0, 0), 4: (2.0, 0.5)},
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (-2.5, 0.0), 3: (5.0, -0.8), 4: (5.0, 0.8)})
    on_carrier = [
        pid for pid in range(5)
        if (c := P.command(gs, 0, pid))["parameters"].get("target_player_id") == 2
        and c["commandType"] in ("MARK", "SLIDE_TACKLE", "PRESS_BALL")
    ]
    assert len(on_carrier) <= 1, f"double-team on lone carrier by players {on_carrier}"
    print(f"OK no double-team on lone carrier (committed players={on_carrier})")


def test_tired_presser_does_not_reserve_lone_carrier():
    # The closest outfielder is gassed -> it cannot press -> a marker MUST still
    # cover the lone carrier (the carrier-reservation must not leave it open).
    gs = _state((-2.5, 0.0), poss_team="away", poss_aid="agentId_2", stam=10,  # all gassed
                home_pos={0: (-6.4, 0), 1: (-4.0, 0.0), 2: (-2.4, 0.0), 3: (2.0, 0), 4: (2.0, 0.5)},
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (-2.5, 0.0), 3: (5.0, -0.8), 4: (5.0, 0.8)})
    on_carrier = [
        pid for pid in range(5)
        if (c := P.command(gs, 0, pid))["parameters"].get("target_player_id") == 2
        and c["commandType"] in ("MARK", "SLIDE_TACKLE", "PRESS_BALL")
    ]
    assert len(on_carrier) == 1, f"gassed closest must not reserve; exactly one covers: {on_carrier}"
    print(f"OK tired presser doesn't reserve lone carrier (covered by {on_carrier})")


def _committed_to(gs, target):
    # A player "commits" to the carrier by MARK/SLIDE on it, OR by PRESS_BALL (which
    # has no target id but presses the one ball = the carrier).
    out = []
    for pid in range(5):
        c = P.command(gs, 0, pid)
        if c["commandType"] == "PRESS_BALL":
            out.append(pid)
        elif c["commandType"] in ("MARK", "SLIDE_TACKLE") and c["parameters"].get("target_player_id") == target:
            out.append(pid)
    return out


def test_carrier_reservation_respects_game_mode_lead():
    # Late LEAD shrinks the non-DEF press range. A presser just OUTSIDE the scaled
    # range won't press, so it must NOT reserve the lone carrier (else uncovered).
    gs = _state((-2.0, 0.0), poss_team="away", poss_aid="agentId_2",
                home_pos={0: (-6.4, 0), 1: (-3.5, 0.0), 2: (-0.9, 0.0), 3: (2.0, 0), 4: (2.0, 0.5)},
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (-2.0, 0.0), 3: (5.0, -0.8), 4: (5.0, 0.8)})
    gs["gameTime"] = 110
    gs["score"] = {"home": 1, "away": 0}     # we (home) lead late -> press range shrinks
    covered = _committed_to(gs, 2)
    assert len(covered) >= 1, f"late-lead: lone carrier left uncovered ({covered})"
    print(f"OK carrier covered under late lead (by {covered})")


def test_carrier_reservation_respects_game_mode_chase():
    # Late CHASE widens the non-DEF press range. A presser inside the scaled (but
    # outside base) range DOES press, so the carrier must be reserved (no double-mark).
    gs = _state((-2.0, 0.0), poss_team="away", poss_aid="agentId_2",
                home_pos={0: (-6.4, 0), 1: (-3.6, 0.0), 2: (-0.6, 0.0), 3: (2.0, 0), 4: (2.0, 0.5)},
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (-2.0, 0.0), 3: (5.0, -0.8), 4: (5.0, 0.8)})
    gs["gameTime"] = 110
    gs["score"] = {"home": 0, "away": 1}     # we (home) chase late -> press range widens
    on_carrier = _committed_to(gs, 2)
    assert len(on_carrier) <= 1, f"late-chase double-team on carrier ({on_carrier})"
    print(f"OK no double-team under late chase (committed {on_carrier})")


if __name__ == "__main__":
    test_duplicate_agentid_possession_team()
    test_duplicate_agentid_nearest_ball()
    test_stamina_fraction_not_always_tired()
    test_shoot_discipline_and_no_ghost_shoot()
    test_def_marks()
    test_formation_role_mapping()
    test_single_presser_invariant_all_formations()
    test_game_management_scaling()
    test_mixing_reproducible_and_safe()
    test_mid_drop_mark_second_striker()
    test_pressure_release_is_formation_aware()
    test_no_double_mark_multi_defender()
    test_no_double_team_lone_carrier()
    test_tired_presser_does_not_reserve_lone_carrier()
    test_carrier_reservation_respects_game_mode_lead()
    test_carrier_reservation_respects_game_mode_chase()
    print("\nALL CONTRACT TESTS PASSED")
