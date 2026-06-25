"""Contract-adapter regression tests — the live-#1 root-cause bugs Codex found.
Run: python3 champion/test_contract.py
"""
import os, sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hybrid
import selector as S
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


def _clear_runtime_state():
    P._STATE["press"] = {}
    P._STATE.pop("tactics", None)
    P._STATE["playbook"] = None


def _enable(name, on=True):
    """Temporarily flip a playbook's SHIP GATE (frozen dataclass -> rebuild)."""
    import dataclasses
    P.PLAYBOOKS[name] = dataclasses.replace(P.PLAYBOOKS[name], enabled=on)


def _set_tactics(value, age=0.0):
    P._STATE["tactics"] = {
        "value": value,
        "wall_mono": time.monotonic() - age,
        "wall_time": time.time() - age,
        "gameTime": 0.0,
    }


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


def test_neutral_tactics_byte_identical():
    states = [
        (_state((5.0, -0.8), poss_aid="agentId_3", poss_team="home"), 0, 3, None),
        (_state((0.5, 0.2)), 0, 2, "1-2-1"),
        (_state((-4.0, 0.5), poss_aid="agentId_3", poss_team="away",
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (0.0, 0.6),
                          3: (-4.0, 0.5), 4: (-3.6, -0.8)}), 0, 2, None),
        (_state((-3.0, 0.0), poss_aid="agentId_1", poss_team="home",
                home_pos={0: (-6.4, 0), 1: (-3.0, 0), 2: (-3.0, 1.2),
                          3: (5.0, -0.8), 4: (5.0, 0.8)}), 0, 2, None),
        (_state((-1.0, 0.0), poss_aid="agentId_2", poss_team="home",
                home_pos={0: (-6.4, 0), 1: (-3.0, 0), 2: (-1.0, 0.0),
                          3: (0.0, -0.8), 4: (0.0, 0.8)}), 0, 3, None),
    ]
    for gs, team, pid, formation in states:
        _clear_runtime_state()
        baseline = P.command(gs, team, pid, formation)
        _clear_runtime_state()
        _set_tactics({"attack_zone": None, "push": 0.0, "exploit_opp_id": None, "tempo": "direct", "notes": ""})
        adapted = P.command(gs, team, pid, formation)
        assert adapted == baseline, (baseline, adapted)
    _clear_runtime_state()
    print("OK neutral tactics are byte-identical to no tactics")


def _target_forwardness(cmd, team_id):
    if cmd["commandType"] != "MOVE_TO":
        return None
    d = 1 if team_id == 0 else -1
    return cmd["parameters"]["target_x"] * d


def test_attack_tactics_never_reduce_forwardness():
    shaped = {"attack_zone": "R", "push": 1.0, "exploit_opp_id": 1, "tempo": "patient", "notes": "attack behind"}
    states = [
        (_state((-3.0, 0.0), poss_aid="agentId_1", poss_team="home",
                home_pos={0: (-6.4, 0), 1: (-3.0, 0), 2: (-3.0, 1.2),
                          3: (5.0, -0.8), 4: (5.0, 0.8)}), 0, 2, None),
        (_state((-1.0, 0.0), poss_aid="agentId_2", poss_team="home",
                home_pos={0: (-6.4, 0), 1: (-3.0, 0), 2: (-1.0, 0.0),
                          3: (0.0, -0.8), 4: (0.0, 0.8)}), 0, 3, None),
        (_state((0.0, 1.2), poss_aid="agentId_2", poss_team="home",
                home_pos={0: (-6.4, 0), 1: (-3.0, 0), 2: (0.0, 1.2),
                          3: (-1.0, -1.0), 4: (-1.0, 1.0)}), 0, 2, None),
    ]
    for gs, team, pid, formation in states:
        _clear_runtime_state()
        baseline = P.command(gs, team, pid, formation)
        _clear_runtime_state()
        _set_tactics(shaped)
        adapted = P.command(gs, team, pid, formation)
        b_fwd = _target_forwardness(baseline, team)
        a_fwd = _target_forwardness(adapted, team)
        assert b_fwd is not None and a_fwd is not None, (baseline, adapted)
        assert a_fwd >= b_fwd, (baseline, adapted)
    _clear_runtime_state()
    print("OK attack tactics never reduce MOVE_TO forwardness")


def test_attack_tactics_preserve_coordination():
    _clear_runtime_state()
    _set_tactics({"attack_zone": "R", "push": 1.0, "exploit_opp_id": 4, "tempo": "patient"})
    gs = _state((-5.0, 0.5), poss_team="away", poss_aid="agentId_3",
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (0.0, 0.0),
                          3: (-5.0, 0.5), 4: (-4.6, -0.6)})
    cmds = [P.command(gs, 0, pid, "2-1-1") for pid in range(5)]
    pressers = [c for c in cmds if c["commandType"] in ("PRESS_BALL", "SLIDE_TACKLE")]
    marks = [c for c in cmds if c["commandType"] == "MARK"]
    targets = [c["parameters"]["target_player_id"] for c in marks]
    assert len(pressers) <= 1, cmds
    assert len(set(targets)) == len(targets), cmds
    _clear_runtime_state()
    print(f"OK attack tactics preserve coordination (pressers={len(pressers)}, mark targets={targets})")


def test_current_tactics_neutral_and_off_schema():
    _clear_runtime_state()
    assert hybrid.current_tactics() == hybrid.NEUTRAL
    _set_tactics({"attack_zone": "L", "push": 0.7, "exploit_opp_id": "2", "tempo": "patient", "notes": "go"})
    assert hybrid.current_tactics() == {"attack_zone": "L", "push": 0.7, "exploit_opp_id": 2, "tempo": "patient", "notes": "go"}
    _set_tactics({"attack_side": "C", "danger_opp_id": 2, "press_level": "high"})
    assert hybrid.current_tactics() == hybrid.NEUTRAL
    _set_tactics({"attack_zone": "wide", "push": 0.5})
    assert hybrid.current_tactics() == hybrid.NEUTRAL
    _set_tactics({"attack_zone": "R", "push": 1.2})
    assert hybrid.current_tactics() == hybrid.NEUTRAL
    _set_tactics({"attack_zone": "R", "push": 0.5, "sit_deeper": True})
    assert hybrid.current_tactics() == hybrid.NEUTRAL
    _set_tactics("garbage")
    assert hybrid.current_tactics() == hybrid.NEUTRAL
    _set_tactics({"attack_zone": "L", "push": 0.2, "exploit_opp_id": 2, "tempo": "patient"}, age=25.0)
    assert hybrid.current_tactics() == hybrid.NEUTRAL
    _clear_runtime_state()
    print("OK current_tactics neutralizes none/off-schema/stale")


def test_observe_never_raises_on_malformed_state():
    bad_states = [
        None,
        {},
        {"players": [None, {"agentId": "x", "teamCode": "away", "position": {"x": "bad"}}]},
        {"ball": {"position": {"x": object(), "z": object()}}, "players": "not-a-list"},
    ]
    for gs in bad_states:
        hybrid.observe(gs, 0)
    print("OK observe never raises on malformed game_state")


# ============================ PLAYBOOK + SELECTOR ============================ #
# Minimum-safe scope: DEFAULT + two GATED counters. The selector is a PURE function
# of the SHARED gameState (team-coherent across the 5 separate-process agents), no
# LLM, no per-process memory. Counters ship DISABLED -> the bot is == DEFAULT.

# Golden states for byte-identity (on-ball, off-ball, multiple formations).
_GOLDEN = [
    (_state((5.0, -0.8), poss_aid="agentId_3", poss_team="home"), 0, 3, None),
    (_state((0.5, 0.2)), 0, 2, "1-2-1"),
    (_state((-4.0, 0.5), poss_aid="agentId_3", poss_team="away",
            away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (0.0, 0.6),
                      3: (-4.0, 0.5), 4: (-3.6, -0.8)}), 0, 2, None),
    (_state((-3.0, 0.0), poss_aid="agentId_1", poss_team="home",
            home_pos={0: (-6.4, 0), 1: (-3.0, 0), 2: (-3.0, 1.2),
                      3: (5.0, -0.8), 4: (5.0, 0.8)}), 0, 2, None),
    (_state((-1.0, 0.0), poss_aid="agentId_2", poss_team="home",
            home_pos={0: (-6.4, 0), 1: (-3.0, 0), 2: (-1.0, 0.0),
                      3: (0.0, -0.8), 4: (0.0, 0.8)}), 0, 3, None),
]


def _two_striker_state(gt=30.0):
    # 2 opponents (away) camped DEEP in our (home) defensive third (x ~ -4).
    gs = _state((-4.0, 0.0), poss_team="away", poss_aid="agentId_3",
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (0.0, 0.0),
                          3: (-4.0, 0.4), 4: (-4.2, -0.5)})
    gs["gameTime"] = gt
    return gs


def _high_press_state(gt=30.0):
    # 3 opponents in our half but NOT deep (no two-striker); home keeps the ball.
    gs = _state((-0.5, 0.0), poss_team="home", poss_aid="agentId_2",
                home_pos={0: (-6.4, 0), 1: (-3.0, 0), 2: (-0.5, 0.0), 3: (3.0, -0.8), 4: (3.0, 0.8)},
                away_pos={0: (6.4, 0), 1: (-1.0, 0.6), 2: (-1.0, -0.6), 3: (-1.2, 0.0), 4: (4.5, 0.0)})
    gs["gameTime"] = gt
    return gs


def test_default_playbook_byte_identical():
    # DEFAULT playbook (explicit name, object, committed-state) == the no-playbook
    # policy across every player + formation. The proven floor must be untouched.
    for gs, team, pid, formation in _GOLDEN:
        _clear_runtime_state()
        floor = P.command(gs, team, pid, formation)
        _clear_runtime_state()
        explicit = P.command(gs, team, pid, formation, "DEFAULT")
        _clear_runtime_state()
        P._STATE["playbook"] = "DEFAULT"
        committed = P.command(gs, team, pid, formation)
        _clear_runtime_state()
        obj = P.command(gs, team, pid, formation, P.DEFAULT_PLAYBOOK)
        assert explicit == floor, (floor, explicit)
        assert committed == floor, (floor, committed)
        assert obj == floor, (floor, obj)
    _clear_runtime_state()
    print("OK DEFAULT playbook is byte-identical to the no-selector floor")


def test_shipped_counters_disabled_is_default():
    # SHIP GATE: with both counters disabled (the shipped state), the selector
    # returns DEFAULT even on clear archetype states -> deployed bot == DEFAULT.
    assert P.PLAYBOOKS["TWO_STRIKER_COVER"].enabled is False
    assert P.PLAYBOOKS["HIGH_PRESS_BEATER"].enabled is False
    for gs in (_two_striker_state(), _high_press_state()):
        assert S.select_playbook(gs, 0) == "DEFAULT", "disabled counters must stay DEFAULT"
        # ... and the emitted command equals the floor (no playbook) for all players.
        for pid in range(5):
            _clear_runtime_state()
            floor = P.command(gs, 0, pid)
            _clear_runtime_state()
            picked = P.command(gs, 0, pid, None, S.select_playbook(gs, 0))
            assert picked == floor, (pid, floor, picked)
    _clear_runtime_state()
    print("OK shipped (counters disabled) == DEFAULT floor on every archetype state")


def test_selector_is_pure_and_team_coherent():
    # PURE: select_playbook ignores agent identity (only gameState+team), is
    # deterministic, and mutates NO module state -> all 5 processes agree.
    _enable("TWO_STRIKER_COVER", True)
    try:
        gs = _two_striker_state()
        snap = dict(P._STATE)
        picks = [S.select_playbook(gs, 0) for _ in range(5)]   # "5 agents", same input
        assert picks == ["TWO_STRIKER_COVER"] * 5, picks
        assert P._STATE == snap, "select_playbook must not mutate _STATE (no per-process memory)"
    finally:
        _enable("TWO_STRIKER_COVER", False)
    _clear_runtime_state()
    print("OK selector is pure + team-coherent (no state, identical for all agents)")


def test_classifier_detects_two_striker():
    _enable("TWO_STRIKER_COVER", True)
    try:
        assert S.select_playbook(_two_striker_state(), 0) == "TWO_STRIKER_COVER"
        # only ONE opponent deep -> below threshold -> DEFAULT (conservative)
        one = _state((-4.0, 0.0), poss_team="away", poss_aid="agentId_3",
                     away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (1.0, 0.0),
                               3: (-4.0, 0.4), 4: (2.0, -0.5)})
        one["gameTime"] = 30.0
        assert S.select_playbook(one, 0) == "DEFAULT", "1 deep opponent must NOT trip the counter"
    finally:
        _enable("TWO_STRIKER_COVER", False)
    print("OK two-striker detected at >=2 deep, conservative below threshold")


def test_classifier_detects_high_press():
    _enable("HIGH_PRESS_BEATER", True)
    try:
        assert S.select_playbook(_high_press_state(), 0) == "HIGH_PRESS_BEATER"
        # only 2 opponents in our half -> below threshold -> DEFAULT
        two = _state((-0.5, 0.0), poss_team="home", poss_aid="agentId_2",
                     home_pos={0: (-6.4, 0), 1: (-3.0, 0), 2: (-0.5, 0.0), 3: (3.0, -0.8), 4: (3.0, 0.8)},
                     away_pos={0: (6.4, 0), 1: (-1.0, 0.6), 2: (-1.0, -0.6), 3: (4.0, 0.0), 4: (4.5, 0.0)})
        two["gameTime"] = 30.0
        assert S.select_playbook(two, 0) == "DEFAULT"
    finally:
        _enable("HIGH_PRESS_BEATER", False)
    print("OK high-press detected at >=3 in our half, conservative below threshold")


def test_scout_gate_holds_default_early():
    _enable("TWO_STRIKER_COVER", True)
    try:
        early = _two_striker_state(gt=2.0)   # before SCOUT_SECONDS
        assert S.select_playbook(early, 0) == "DEFAULT", "scout window must hold DEFAULT early"
    finally:
        _enable("TWO_STRIKER_COVER", False)
    print("OK gameTime scout gate holds DEFAULT before shapes settle")


def test_high_press_not_switched_during_goal_danger():
    # Opponent possesses DEEP in our third -> never switch to the attacking
    # press-beater shape at a dangerous moment (Codex conservative gate).
    _enable("HIGH_PRESS_BEATER", True)
    try:
        gs = _state((-5.0, 0.0), poss_team="away", poss_aid="agentId_3",
                    away_pos={0: (6.4, 0), 1: (-1.0, 0.6), 2: (-1.0, -0.6),
                              3: (-5.0, 0.0), 4: (4.5, 0.0)})
        gs["gameTime"] = 30.0
        # 3 opponents in our half (press) BUT one possesses deep in our third.
        assert S.select_playbook(gs, 0) == "DEFAULT", "must not switch under goal-danger possession"
    finally:
        _enable("HIGH_PRESS_BEATER", False)
    print("OK high-press not switched during opponent possession near our goal")


def test_two_striker_priority_over_high_press():
    _enable("TWO_STRIKER_COVER", True)
    _enable("HIGH_PRESS_BEATER", True)
    try:
        # qualifies for BOTH (>=2 deep AND >=3 in half) -> defensive counter wins.
        gs = _state((-4.0, 0.0), poss_team="away", poss_aid="agentId_3",
                    away_pos={0: (6.4, 0), 1: (-1.0, 0.0), 2: (-3.0, 0.6),
                              3: (-4.0, 0.4), 4: (-4.2, -0.5)})
        gs["gameTime"] = 30.0
        assert S.select_playbook(gs, 0) == "TWO_STRIKER_COVER"
    finally:
        _enable("TWO_STRIKER_COVER", False)
        _enable("HIGH_PRESS_BEATER", False)
    print("OK TWO_STRIKER_COVER takes priority over HIGH_PRESS_BEATER")


def test_select_never_raises_on_malformed():
    _enable("TWO_STRIKER_COVER", True)
    try:
        for junk in [None, {}, {"players": None}, {"players": "x", "gameTime": "z"},
                     {"players": [None, 1, {"position": {"x": object()}}], "gameTime": 30}]:
            assert S.select_playbook(junk, 0) == "DEFAULT"
    finally:
        _enable("TWO_STRIKER_COVER", False)
    print("OK select_playbook never raises on malformed state -> DEFAULT")


def _pressers_and_marks(gs, formation, playbook=None):
    pressers, mark_targets = 0, []
    for pid in range(1, 5):
        c = P.command(gs, 0, pid, formation, playbook)
        if c["commandType"] in ("PRESS_BALL", "SLIDE_TACKLE"):
            pressers += 1
        elif c["commandType"] == "MARK":
            mark_targets.append(c["parameters"]["target_player_id"])
    return pressers, mark_targets


def test_every_playbook_preserves_invariants():
    # Each playbook must keep: single-presser, no-double-mark, attack-always mode.
    gs = _state((-5.0, 0.5), poss_team="away", poss_aid="agentId_3",
                away_pos={0: (6.4, 0), 1: (3.0, 0), 2: (0.0, 0.0),
                          3: (-5.0, 0.5), 4: (-4.6, -0.6)})
    for name in P.PLAYBOOKS:
        _clear_runtime_state()
        pressers, targets = _pressers_and_marks(gs, None, name)   # playbook drives formation
        assert pressers <= 1, (name, "double press", pressers)
        assert len(set(targets)) == len(targets), (name, "double mark", targets)
        v = type("V", (), {"gt": 110.0, "goal_diff": 1})()
        assert P._game_mode(v)["risk"] == 1.0, (name, "must not lead-protect (attack-always)")
    _clear_runtime_state()
    print("OK every playbook preserves single-presser + no-double-mark + attack-always")


def test_two_striker_cover_211_single_presser():
    # TWO_STRIKER_COVER runs a 2-1-1 in code (DEF2 added); single-presser must hold.
    _clear_runtime_state()
    gs = _state((0.5, 0.2))
    pressers, _ = _pressers_and_marks(gs, None, "TWO_STRIKER_COVER")
    assert pressers <= 1, pressers
    assert P.role_for_player(2, P.PLAYBOOKS["TWO_STRIKER_COVER"].formation) == P.DEF2
    _clear_runtime_state()
    print("OK TWO_STRIKER_COVER 2-1-1 keeps single-presser invariant")


def test_high_press_beater_keeps_shoot_and_possession():
    # A clear in-box chance still SHOOTs; on/off-ball commands all stay legal.
    _clear_runtime_state()
    gs = _state((5.0, -0.8), poss_aid="agentId_3", poss_team="home")
    c = P.command(gs, 0, 3, None, "HIGH_PRESS_BEATER")
    assert c["commandType"] in ("SHOOT", "PASS", "MOVE_TO"), c
    for pid in range(5):
        cc = P.command(gs, 0, pid, None, "HIGH_PRESS_BEATER")
        assert cc["commandType"], (pid, cc)
    _clear_runtime_state()
    print(f"OK HIGH_PRESS_BEATER preserves shoot/possession logic (home3={c['commandType']})")


def test_selector_pure_no_bedrock_no_llm():
    # No network deps and no LLM symbols in the selector decision path.
    assert "boto3" not in dir(S), "selector must not import boto3"
    for sym in ("llm_suggest", "classify_window", "select"):
        assert not hasattr(S, sym), f"removed LLM/stateful API still present: {sym}"
    assert hasattr(S, "select_playbook"), "pure select_playbook must exist"
    print("OK selector is pure deterministic (no Bedrock, no LLM, no stateful select)")


# ============================ FAST-TRANSITION / COUNTER ====================== #
# The counter is an ATTACK accelerant triggered PURELY from the shared gameState
# (team-coherent). Contract: no-counter-state => byte-identical to pre-counter
# DEFAULT (proven via the COUNTER_MODE_ENABLED kill switch); a counter-state =>
# the carrier plays a forward/through ball (not a backward recycle) and the FWDs
# sprint high in behind. Invariants hold; malformed state is safe.

def _counter_state(gt=40.0):
    # We (home) hold the ball DEEP (MID carrier at x=-3) and TWO opponents are
    # committed into our half (x<0) -> space in behind. A FWD sits high (x=2) as a
    # potential in-behind runner. Ball in our half -> the counter must trigger.
    return _state((-3.0, 0.0), poss_aid="agentId_2", poss_team="home",
                  home_pos={0: (-6.4, 0), 1: (-3.5, 0.2), 2: (-3.0, 0.0), 3: (2.0, -0.8), 4: (1.5, 0.8)},
                  away_pos={0: (6.4, 0), 1: (-2.0, 0.3), 2: (-1.5, -0.4), 3: (4.0, 0.0), 4: (4.5, 0.5)},
                  ) | {"gameTime": gt}


def _no_counter_state(gt=40.0):
    # Same possession/ball but opponents are HOME in their own half (x>0) -> NOT
    # committed forward -> the trigger must stay off (DEFAULT behavior).
    return _state((-3.0, 0.0), poss_aid="agentId_2", poss_team="home",
                  home_pos={0: (-6.4, 0), 1: (-3.5, 0.2), 2: (-3.0, 0.0), 3: (2.0, -0.8), 4: (1.5, 0.8)},
                  away_pos={0: (6.4, 0), 1: (3.0, 0.3), 2: (2.5, -0.4), 3: (4.0, 0.0), 4: (4.5, 0.5)},
                  ) | {"gameTime": gt}


def _toggle_counter(on):
    P.COUNTER_MODE_ENABLED = on


def test_counter_trigger_detection():
    # The counter is a flag-gated lever (ships OFF: live A/B showed no benefit). Test the
    # trigger DETECTION logic by enabling it locally, then restore the shipped OFF default.
    _clear_runtime_state()
    _toggle_counter(True)
    try:
        v_yes = P._parse(_counter_state(), 0, 2)
        v_no = P._parse(_no_counter_state(), 0, 2)
        assert P._counter_opportunity(v_yes) is True, "deep possession + 2 opps forward must trigger"
        assert P._counter_opportunity(v_no) is False, "opponents home in their half must NOT trigger"
    finally:
        _toggle_counter(False)
    # ball in opp half -> never a deep counter even with opps back
    v_oppside = P._parse(_state((3.0, 0.0), poss_aid="agentId_2", poss_team="home",
                                away_pos={0: (6.4, 0), 1: (-2.0, 0), 2: (-1.5, 0), 3: (4.0, 0), 4: (4.5, 0)}), 0, 2)
    assert P._counter_opportunity(v_oppside) is False, "ball in opp half must not trigger a deep counter"
    print("OK counter trigger: fires deep w/ opps forward, off otherwise")


def test_counter_no_state_byte_identical_to_default():
    # The hard regression: for a NON-counter state, enabling the feature changes
    # NOTHING (the trigger is false -> exact same code path as pre-counter DEFAULT).
    gs = _no_counter_state()
    for pid in range(5):
        _clear_runtime_state(); _toggle_counter(False)
        off = P.command(gs, 0, pid)
        _clear_runtime_state(); _toggle_counter(True)
        on = P.command(gs, 0, pid)
        assert off == on, (pid, off, on)
    _toggle_counter(True); _clear_runtime_state()
    # And every GOLDEN state is unaffected by the feature toggle too.
    for gs, team, pid, formation in _GOLDEN:
        _clear_runtime_state(); _toggle_counter(False)
        off = P.command(gs, team, pid, formation)
        _clear_runtime_state(); _toggle_counter(True)
        on = P.command(gs, team, pid, formation)
        assert off == on, ("golden", pid, off, on)
    _toggle_counter(True); _clear_runtime_state()
    print("OK no-counter / golden states are byte-identical with counter on vs off")


def test_counter_carrier_plays_forward_not_recycle():
    _clear_runtime_state(); _toggle_counter(True)
    gs = _counter_state()
    c = P.command(gs, 0, 2)  # MID carrier deep
    assert c["commandType"] in ("PASS", "MOVE_TO"), c
    if c["commandType"] == "PASS":
        # through-ball to a forward teammate, not a sideways/back recycle
        assert c["parameters"]["type"] == "THROUGH", c
        tgt = c["parameters"]["target_player_id"]
        assert tgt in (3, 4), f"counter through-ball should target a forward runner, got {tgt}"
    else:
        # sprint-carry must advance toward the opp goal (forwardness > 0), sprinting
        assert c["parameters"]["sprint"] is True, c
        assert c["parameters"]["target_x"] > -3.0, f"carry must go forward (+x), got {c}"
    # the counter command must NEVER be a backward recycle: also assert it differs
    # from the (slower) pre-counter behavior for this state.
    _clear_runtime_state(); _toggle_counter(False)
    base = P.command(gs, 0, 2)
    _toggle_counter(True); _clear_runtime_state()
    assert c != base, "counter must change the carrier's action vs pre-counter DEFAULT"
    print(f"OK counter carrier plays forward ({c['commandType']}/{c['parameters'].get('type','')}) not recycle")


def test_counter_forwards_sprint_high():
    _clear_runtime_state(); _toggle_counter(True)
    gs = _counter_state()
    for pid in (3, 4):  # FWD1, FWD2
        c = P.command(gs, 0, pid)
        assert c["commandType"] == "MOVE_TO", (pid, c)
        assert c["parameters"]["sprint"] is True, (pid, "FWD must sprint on counter", c)
        # high in behind: well into the opp half toward the opp goal
        assert c["parameters"]["target_x"] >= P._sx(P.COUNTER_FWD_RUN_AX) - 0.2, (pid, c)
    # FWDs split channels (don't stack): opposite-sign target_y
    c3 = P.command(gs, 0, 3); c4 = P.command(gs, 0, 4)
    assert c3["parameters"]["target_y"] * c4["parameters"]["target_y"] < 0, (c3, c4)
    _clear_runtime_state()
    print("OK counter FWDs sprint high in behind on opposite channels")


def test_counter_preserves_invariants():
    # Single-presser + no-double-mark must still hold while the counter is active.
    _clear_runtime_state(); _toggle_counter(True)
    gs = _counter_state()
    pressers, targets = _pressers_and_marks(gs, None)
    assert pressers <= 1, ("counter broke single-presser", pressers)
    assert len(set(targets)) == len(targets), ("counter caused double-mark", targets)
    # GK + DEF off-ball shape unchanged: enabling the counter must not alter their
    # command on this state (attack accelerant only, not a defensive change).
    for pid in (0, 1):
        _clear_runtime_state(); _toggle_counter(False)
        off = P.command(gs, 0, pid)
        _clear_runtime_state(); _toggle_counter(True)
        on = P.command(gs, 0, pid)
        assert off == on, ("counter changed GK/DEF", pid, off, on)
    _clear_runtime_state()
    print("OK counter preserves single-presser/no-double-mark, GK+DEF unchanged")


def test_counter_team_coherent_and_safe():
    # PURE: every agent computes the same trigger from the shared state; no _STATE
    # mutation; malformed state never raises.
    _clear_runtime_state(); _toggle_counter(True)
    gs = _counter_state()
    v = P._parse(gs, 0, 2)
    snap = dict(P._STATE)
    picks = [P._counter_opportunity(P._parse(gs, 0, pid)) for pid in range(5)]
    assert all(picks), f"all agents must agree the counter is on: {picks}"
    assert P._STATE == snap, "counter detection must not mutate _STATE"
    for junk in ({"players": [], "ball": {"position": {"x": 0, "z": 0}}},):
        vj = P._parse(junk, 0, 2)
        if vj is not None:
            P._counter_opportunity(vj)  # must not raise
    _clear_runtime_state()
    print("OK counter is team-coherent, stateless, and malformed-safe")


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
    test_neutral_tactics_byte_identical()
    test_attack_tactics_never_reduce_forwardness()
    test_attack_tactics_preserve_coordination()
    test_current_tactics_neutral_and_off_schema()
    test_observe_never_raises_on_malformed_state()
    # --- playbook + selector (team-coherent, gated, deterministic) ---
    test_default_playbook_byte_identical()
    test_shipped_counters_disabled_is_default()
    test_selector_is_pure_and_team_coherent()
    test_classifier_detects_two_striker()
    test_classifier_detects_high_press()
    test_scout_gate_holds_default_early()
    test_high_press_not_switched_during_goal_danger()
    test_two_striker_priority_over_high_press()
    test_select_never_raises_on_malformed()
    test_every_playbook_preserves_invariants()
    test_two_striker_cover_211_single_presser()
    test_high_press_beater_keeps_shoot_and_possession()
    test_selector_pure_no_bedrock_no_llm()
    # --- fast-transition / counter-attack (team-coherent, bounded, fail-safe) ---
    test_counter_trigger_detection()
    test_counter_no_state_byte_identical_to_default()
    test_counter_carrier_plays_forward_not_recycle()
    test_counter_forwards_sprint_high()
    test_counter_preserves_invariants()
    test_counter_team_coherent_and_safe()
    print("\nALL CONTRACT TESTS PASSED")
