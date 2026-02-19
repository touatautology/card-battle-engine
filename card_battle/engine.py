"""Phase 5: Game engine – init, turn loop, win condition checks."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from card_battle.actions import Action, EndTurn, get_legal_actions, apply_action
from card_battle.effects import _draw_one
from card_battle.models import (
    Card, DeckDef, GameResult, GameState, MatchLog, PlayerState,
)

if TYPE_CHECKING:
    from card_battle.ai import Agent

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


def run_game(
    gs: GameState,
    agents: tuple["Agent", "Agent"],
    trace: bool = False,
) -> MatchLog:
    play_trace: list[dict] | None = [] if trace else None

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
        if result is not None:
            gs.result = result
            break

        agent = agents[gs.active_player]

        # Main phase: choose actions until EndTurn
        while gs.result is None:
            legal = get_legal_actions(gs)
            action = agent.choose_action(gs, legal)

            if play_trace is not None:
                play_trace.append({
                    "turn": gs.turn,
                    "player": gs.active_player,
                    "action": str(action),
                })

            if isinstance(action, EndTurn):
                break

            apply_action(gs, action)

            # Check win after every action
            result = _check_winner(gs)
            if result is not None:
                gs.result = result
                break

        # Switch active player
        gs.active_player = 1 - gs.active_player

    return MatchLog(
        seed=0,  # filled by caller
        deck_ids=("", ""),  # filled by caller
        winner=gs.result,
        turns=gs.turn,
        final_hp=(gs.players[0].hp, gs.players[1].hp),
        play_trace=play_trace,
    )
