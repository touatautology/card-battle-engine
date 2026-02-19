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

    # Count deaths before removing (for telemetry)
    atk_deaths = 0
    def_deaths = 0
    # Remove dead units from both boards
    for player in [active_player, defender_player]:
        dead = [u for u in player.board if u.hp <= 0]
        if telemetry:
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
) -> MatchLog:
    play_trace: list[dict] | None = [] if trace else None

    if telemetry:
        telemetry.on_game_start(gs)

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

            # Telemetry: snapshot before applying PlayCard
            if telemetry and isinstance(action, PlayCard):
                p = gs.active()
                opp = gs.opponent()
                hand_size_before = len(p.hand)
                opp_hp_before = opp.hp
                card = gs.card_db[p.hand[action.hand_index]]

            apply_action(gs, action)

            # Telemetry: record PlayCard effects
            if telemetry and isinstance(action, PlayCard):
                telemetry.on_card_played(gs, gs.active_player, card)
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

            # Telemetry: record block declaration
            if telemetry and isinstance(action, DeclareBlock):
                telemetry.on_declare_block(gs, defender_idx, action.pairs)

            _resolve_combat(gs, telemetry=telemetry)

            result = _check_winner(gs)
            if result is not None:
                gs.result = result

            gs.phase = "end"

        # --- End phase / turn switch ---
        if gs.phase == "end" or gs.phase == "main":
            # Telemetry: record turn end
            if telemetry:
                telemetry.on_turn_end(gs, gs.active_player)
            # main can happen if combat was cancelled
            gs.active_player = 1 - gs.active_player

    # Telemetry: record game end
    if telemetry and gs.result is not None:
        reason = "turn_limit" if gs.turn >= MAX_TURNS else "normal"
        # Detect deckout: loser is alive but has empty deck
        if reason == "normal" and gs.result != GameResult.DRAW:
            loser_idx = 0 if gs.result == GameResult.PLAYER_1_WIN else 1
            loser = gs.players[loser_idx]
            if loser.hp > 0 and not loser.deck:
                reason = "deckout"
        telemetry.on_game_end(gs, gs.result, reason)

    return MatchLog(
        seed=0,  # filled by caller
        deck_ids=("", ""),  # filled by caller
        winner=gs.result,
        turns=gs.turn,
        final_hp=(gs.players[0].hp, gs.players[1].hp),
        play_trace=play_trace,
    )
