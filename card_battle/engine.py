"""Phase 5: Game engine – init, turn loop, win condition checks."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import TYPE_CHECKING

from card_battle.actions import (
    Action, EndTurn, GoToCombat, DeclareAttack, DeclareBlock, PlayCard,
    get_legal_actions, apply_action,
)
from card_battle.effects import _draw_one
from card_battle.models import (
    Card, DeckDef, GameResult, GameState, MatchLog, PlayerState,
)

if TYPE_CHECKING:
    from card_battle.ai import Agent
    from card_battle.replay import ReplayWriter
    from card_battle.telemetry import MatchTelemetry

MAX_TURNS = 50


def _build_deck_list(deck_def: DeckDef) -> list[str]:
    cards: list[str] = []
    for entry in deck_def.entries:
        cards.extend([entry.card_id] * entry.count)
    return cards


def init_game(
    card_db: dict[str, Card],
    deck_a: DeckDef,
    deck_b: DeckDef,
    seed: int,
) -> GameState:
    rng = random.Random(seed)

    # Build and shuffle decks
    deck_list_a = _build_deck_list(deck_a)
    deck_list_b = _build_deck_list(deck_b)
    rng.shuffle(deck_list_a)
    rng.shuffle(deck_list_b)

    players = [
        PlayerState(deck=deck_list_a),
        PlayerState(deck=deck_list_b),
    ]

    gs = GameState(
        turn=0,
        active_player=0,
        players=players,
        next_uid=1,
        result=None,
        rng=rng,
        card_db=card_db,
    )

    # Decide who goes first (0 or 1)
    gs.active_player = rng.randint(0, 1)

    # Draw initial hands (5 cards each)
    for pi in range(2):
        for _ in range(5):
            _draw_one(gs, pi)

    return gs


def _check_winner(gs: GameState) -> GameResult | None:
    p0_dead = gs.players[0].hp <= 0
    p1_dead = gs.players[1].hp <= 0
    if p0_dead and p1_dead:
        return GameResult.DRAW
    if p0_dead:
        return GameResult.PLAYER_1_WIN
    if p1_dead:
        return GameResult.PLAYER_0_WIN
    return None


def _start_turn(gs: GameState) -> GameResult | None:
    gs.turn += 1
    gs.phase = "main"
    gs.combat = None
    p = gs.active()

    # Increase mana (cap 10)
    p.mana_max = min(p.mana_max + 1, 10)
    p.mana = p.mana_max

    # Draw a card – deck-out = loss
    if not _draw_one(gs, gs.active_player):
        return (
            GameResult.PLAYER_1_WIN
            if gs.active_player == 0
            else GameResult.PLAYER_0_WIN
        )

    # Wake up units
    for unit in p.board:
        unit.can_attack = True

    return None


def _resolve_combat(
    gs: GameState,
    telemetry: "MatchTelemetry | None" = None,
    replay: "ReplayWriter | None" = None,
) -> None:
    """Resolve combat: simultaneous damage, then remove dead units."""
    assert gs.combat is not None
    attackers = gs.combat.attackers
    blocks = gs.combat.blocks

    active_player = gs.active()
    defender_player = gs.opponent()

    # Build uid -> unit lookup for both sides
    active_units = {u.uid: u for u in active_player.board}
    defender_units = {u.uid: u for u in defender_player.board}

    # Buffer damage
    unit_damage: dict[int, int] = defaultdict(int)
    player_damage = 0

    # Telemetry accumulators
    unblocked_atk_count = 0
    unblocked_dmg = 0
    trade_count = 0

    for a_uid in attackers:
        attacker = active_units.get(a_uid)
        if attacker is None:
            continue  # attacker died to spell or was removed

        if a_uid in blocks:
            # Blocked — mutual damage
            b_uid = blocks[a_uid]
            blocker = defender_units.get(b_uid)
            if blocker is not None:
                unit_damage[b_uid] += attacker.atk
                unit_damage[a_uid] += blocker.atk
                # Trade: both would die
                if telemetry:
                    atk_would_die = attacker.hp <= blocker.atk
                    blk_would_die = blocker.hp <= attacker.atk
                    if atk_would_die and blk_would_die:
                        trade_count += 1
            else:
                # Blocker gone — unblocked
                player_damage += attacker.atk
                unblocked_atk_count += 1
                unblocked_dmg += attacker.atk
        else:
            # Unblocked — damage to defender player
            player_damage += attacker.atk
            unblocked_atk_count += 1
            unblocked_dmg += attacker.atk

    # Apply player damage
    defender_player.hp -= player_damage

    # Apply unit damage
    for uid, dmg in unit_damage.items():
        unit = active_units.get(uid) or defender_units.get(uid)
        if unit is not None:
            unit.hp -= dmg

    # Count deaths before removing (for telemetry/replay)
    atk_deaths = 0
    def_deaths = 0
    # Remove dead units from both boards
    for player in [active_player, defender_player]:
        dead = [u for u in player.board if u.hp <= 0]
        if telemetry or replay:
            if player is active_player:
                atk_deaths = len(dead)
            else:
                def_deaths = len(dead)
        for u in dead:
            player.board.remove(u)
            player.graveyard.append(u.card_id)

    # Mark attackers as having attacked (can_attack = False)
    for a_uid in attackers:
        unit = active_units.get(a_uid)
        if unit is not None and unit.hp > 0:
            unit.can_attack = False

    # Telemetry: report combat stats
    if telemetry:
        telemetry.on_combat_resolved(
            gs,
            atk_idx=gs.active_player,
            def_idx=gs.opponent_idx(),
            unblocked_atk_count=unblocked_atk_count,
            unblocked_dmg=unblocked_dmg,
            trade_count=trade_count,
            atk_deaths=atk_deaths,
            def_deaths=def_deaths,
            player_damage=player_damage,
        )

    # Replay: combat_resolve (2h)
    if replay:
        from card_battle.replay import snapshot_player
        replay.write({
            "type": "combat_resolve",
            "turn": gs.turn,
            "attacker_player": gs.active_player,
            "defender_player": gs.opponent_idx(),
            "unblocked_damage": unblocked_dmg,
            "unblocked_attackers": unblocked_atk_count,
            "trades": trade_count,
            "player_damage": player_damage,
            "atk_deaths": atk_deaths,
            "def_deaths": def_deaths,
            "hp_after_p0": gs.players[0].hp,
            "hp_after_p1": gs.players[1].hp,
        })

    # Clear combat state
    gs.combat = None


def _record_trace(
    play_trace: list[dict] | None,
    gs: GameState,
    action: Action,
    player: int,
) -> None:
    if play_trace is not None:
        play_trace.append({
            "turn": gs.turn,
            "player": player,
            "action": str(action),
        })


def run_game(
    gs: GameState,
    agents: tuple["Agent", "Agent"],
    trace: bool = False,
    telemetry: "MatchTelemetry | None" = None,
    replay: "ReplayWriter | None" = None,
) -> MatchLog:
    play_trace: list[dict] | None = [] if trace else None

    if telemetry:
        telemetry.on_game_start(gs)

    # Replay: game_start (2a)
    if replay:
        from card_battle.replay import snapshot_player
        replay.write({
            "type": "game_start",
            "active_player": gs.active_player,
            "p0": snapshot_player(gs.players[0]),
            "p1": snapshot_player(gs.players[1]),
        })

    while gs.result is None:
        # Turn limit
        if gs.turn >= MAX_TURNS:
            hp0, hp1 = gs.players[0].hp, gs.players[1].hp
            if hp0 > hp1:
                gs.result = GameResult.PLAYER_0_WIN
            elif hp1 > hp0:
                gs.result = GameResult.PLAYER_1_WIN
            else:
                gs.result = GameResult.DRAW
            break

        # Start turn
        result = _start_turn(gs)
        if telemetry:
            telemetry.on_turn_start(gs, gs.active_player)
        # Replay: turn_start (2b)
        if replay:
            from card_battle.replay import snapshot_player
            replay.write({
                "type": "turn_start",
                "turn": gs.turn,
                "active_player": gs.active_player,
                "p0": snapshot_player(gs.players[0]),
                "p1": snapshot_player(gs.players[1]),
            })
        if result is not None:
            # Deckout — no card drawn
            gs.result = result
            break
        else:
            # Successful draw
            if telemetry:
                telemetry.on_cards_drawn(gs, gs.active_player, 1, "turn_draw")

        # --- Main phase ---
        while gs.phase == "main" and gs.result is None:
            legal = get_legal_actions(gs)
            action = agents[gs.active_player].choose_action(gs, legal)
            _record_trace(play_trace, gs, action, gs.active_player)

            if isinstance(action, EndTurn):
                gs.phase = "end"
                break

            # Snapshot before applying PlayCard (for telemetry/replay)
            _card_snapshot = None
            if (telemetry or replay) and isinstance(action, PlayCard):
                p = gs.active()
                _card_snapshot = gs.card_db[p.hand[action.hand_index]]
                if telemetry:
                    opp = gs.opponent()
                    hand_size_before = len(p.hand)
                    opp_hp_before = opp.hp

            apply_action(gs, action)

            # Replay: play_card (2c)
            if replay and _card_snapshot is not None:
                replay.write({
                    "type": "play_card",
                    "turn": gs.turn,
                    "player": gs.active_player,
                    "card_id": _card_snapshot.id,
                    "cost": _card_snapshot.cost,
                    "card_type": _card_snapshot.card_type,
                    "mana_after": gs.active().mana,
                    "hand_count_after": len(gs.active().hand),
                })

            # Telemetry: record PlayCard effects
            if telemetry and isinstance(action, PlayCard):
                telemetry.on_card_played(gs, gs.active_player, _card_snapshot)
                # Detect effect draws: cards drawn = hand_now - hand_before + 1
                # (+1 because the played card was removed from hand)
                p = gs.active()
                opp = gs.opponent()
                draws = len(p.hand) - hand_size_before + 1
                if draws > 0:
                    telemetry.on_cards_drawn(gs, gs.active_player, draws, "effect")
                # Detect spell/effect damage to opponent
                damage = opp_hp_before - opp.hp
                if damage > 0:
                    telemetry.on_spell_damage(gs, gs.active_player, damage)

            # Replay: go_to_combat (2d)
            if replay and isinstance(action, GoToCombat):
                replay.write({
                    "type": "go_to_combat",
                    "turn": gs.turn,
                    "player": gs.active_player,
                })

            if gs.phase != "main":
                break  # GoToCombat transitioned to combat_attack

            result = _check_winner(gs)
            if result is not None:
                gs.result = result
                break

        # --- Combat attack phase ---
        if gs.phase == "combat_attack" and gs.result is None:
            legal = get_legal_actions(gs)
            action = agents[gs.active_player].choose_action(gs, legal)
            _record_trace(play_trace, gs, action, gs.active_player)
            apply_action(gs, action)
            # DeclareAttack(empty) → phase="main" (combat cancelled)

            # Replay: declare_attack (2e)
            if replay and isinstance(action, DeclareAttack):
                active_units = {u.uid: u for u in gs.active().board}
                replay.write({
                    "type": "declare_attack",
                    "turn": gs.turn,
                    "player": gs.active_player,
                    "attacker_uids": list(action.attacker_uids),
                    "attackers": [
                        {"uid": uid, "card_id": active_units[uid].card_id,
                         "atk": active_units[uid].atk, "hp": active_units[uid].hp}
                        for uid in action.attacker_uids if uid in active_units
                    ],
                })

            # Telemetry: record attack declaration
            if telemetry and isinstance(action, DeclareAttack):
                telemetry.on_declare_attack(
                    gs, gs.active_player, action.attacker_uids,
                )

        # --- Combat block phase (defender acts) ---
        if gs.phase == "combat_block" and gs.result is None:
            legal = get_legal_actions(gs)
            defender_idx = gs.opponent_idx()
            action = agents[defender_idx].choose_action(gs, legal)
            _record_trace(play_trace, gs, action, defender_idx)
            apply_action(gs, action)

            # Replay: declare_block (2f)
            if replay and isinstance(action, DeclareBlock):
                def_units = {u.uid: u for u in gs.players[defender_idx].board}
                atk_units = {u.uid: u for u in gs.active().board}
                replay.write({
                    "type": "declare_block",
                    "turn": gs.turn,
                    "player": defender_idx,
                    "pairs": [
                        {
                            "blocker_uid": b,
                            "blocker_card_id": def_units[b].card_id if b in def_units else "?",
                            "attacker_uid": a,
                            "attacker_card_id": atk_units[a].card_id if a in atk_units else "?",
                        }
                        for b, a in action.pairs
                    ],
                })

            # Telemetry: record block declaration
            if telemetry and isinstance(action, DeclareBlock):
                telemetry.on_declare_block(gs, defender_idx, action.pairs)

            _resolve_combat(gs, telemetry=telemetry, replay=replay)

            result = _check_winner(gs)
            if result is not None:
                gs.result = result

            gs.phase = "end"

        # --- End phase / turn switch ---
        if gs.phase == "end" or gs.phase == "main":
            # Telemetry: record turn end
            if telemetry:
                telemetry.on_turn_end(gs, gs.active_player)
            # Replay: turn_end (2i)
            if replay:
                replay.write({
                    "type": "turn_end",
                    "turn": gs.turn,
                    "active_player": gs.active_player,
                })
            # main can happen if combat was cancelled
            gs.active_player = 1 - gs.active_player

    # Compute reason for telemetry/replay
    reason = None
    if (telemetry or replay) and gs.result is not None:
        reason = "turn_limit" if gs.turn >= MAX_TURNS else "normal"
        # Detect deckout: loser is alive but has empty deck
        if reason == "normal" and gs.result != GameResult.DRAW:
            loser_idx = 0 if gs.result == GameResult.PLAYER_1_WIN else 1
            loser = gs.players[loser_idx]
            if loser.hp > 0 and not loser.deck:
                reason = "deckout"

    if telemetry and gs.result is not None:
        telemetry.on_game_end(gs, gs.result, reason)

    # Replay: game_end (2j)
    if replay and gs.result is not None:
        replay.write({
            "type": "game_end",
            "winner": gs.result.value,
            "reason": reason,
            "turns": gs.turn,
            "final_hp": [gs.players[0].hp, gs.players[1].hp],
        })

    return MatchLog(
        seed=0,  # filled by caller
        deck_ids=("", ""),  # filled by caller
        winner=gs.result,
        turns=gs.turn,
        final_hp=(gs.players[0].hp, gs.players[1].hp),
        play_trace=play_trace,
    )
