"""v0.3: Fitness evaluation via match simulation."""

from __future__ import annotations

import hashlib
from typing import Any

from card_battle.ai import GreedyAI
from card_battle.engine import init_game, run_game
from card_battle.models import Card, DeckDef, GameResult
from card_battle.telemetry import MatchTelemetry


def derive_match_seed(
    global_seed: int,
    generation: int,
    deck_a_id: str,
    deck_b_id: str,
    game_index: int,
    seat_swapped: bool,
) -> int:
    """Deterministic seed from match parameters via SHA-256."""
    swap_flag = 1 if seat_swapped else 0
    key = f"{global_seed}:{generation}:{deck_a_id}:{deck_b_id}:{game_index}:{swap_flag}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def evaluate_deck_vs_pool(
    deck: DeckDef,
    elite_pool: list[DeckDef],
    card_db: dict[str, Card],
    global_seed: int,
    generation: int,
    matches_per_opponent: int,
    collect_telemetry: bool = False,
) -> float | tuple[float, list[dict[str, Any]]]:
    """Evaluate a deck against the elite pool. Returns average win rate [0, 1].

    Each matchup is played matches_per_opponent times x 2 seats (normal + swapped).
    Win = 1.0, Draw = 0.5, Loss = 0.0.

    If collect_telemetry is True, returns (win_rate, summaries) instead of just win_rate.
    """
    if not elite_pool:
        return (0.5, []) if collect_telemetry else 0.5

    agents = (GreedyAI(), GreedyAI())
    total_score = 0.0
    total_games = 0
    summaries: list[dict[str, Any]] = []

    for opponent in elite_pool:
        for game_idx in range(matches_per_opponent):
            for swapped in (False, True):
                seed = derive_match_seed(
                    global_seed, generation,
                    deck.deck_id, opponent.deck_id,
                    game_idx, swapped,
                )
                tm = MatchTelemetry() if collect_telemetry else None
                if swapped:
                    gs = init_game(card_db, opponent, deck, seed)
                    log = run_game(gs, agents, telemetry=tm)
                    # deck is player 1 when swapped
                    if log.winner == GameResult.PLAYER_1_WIN:
                        total_score += 1.0
                    elif log.winner == GameResult.DRAW:
                        total_score += 0.5
                else:
                    gs = init_game(card_db, deck, opponent, seed)
                    log = run_game(gs, agents, telemetry=tm)
                    # deck is player 0 when not swapped
                    if log.winner == GameResult.PLAYER_0_WIN:
                        total_score += 1.0
                    elif log.winner == GameResult.DRAW:
                        total_score += 0.5

                if tm is not None:
                    s = tm.to_summary()
                    s["deck_id"] = deck.deck_id
                    s["opponent_id"] = opponent.deck_id
                    s["swapped"] = swapped
                    summaries.append(s)

                total_games += 1

    win_rate = total_score / total_games
    if collect_telemetry:
        return (win_rate, summaries)
    return win_rate


def evaluate_population(
    population: list[DeckDef],
    elite_pool: list[DeckDef],
    card_db: dict[str, Card],
    global_seed: int,
    generation: int,
    matches_per_opponent: int,
    collect_telemetry: bool = False,
) -> list[tuple[DeckDef, float]] | tuple[list[tuple[DeckDef, float]], list[dict[str, Any]]]:
    """Evaluate all decks in a population against the elite pool.

    If collect_telemetry is True, returns (scored, all_summaries).
    """
    results: list[tuple[DeckDef, float]] = []
    all_summaries: list[dict[str, Any]] = []

    for deck in population:
        out = evaluate_deck_vs_pool(
            deck, elite_pool, card_db,
            global_seed, generation, matches_per_opponent,
            collect_telemetry=collect_telemetry,
        )
        if collect_telemetry:
            fitness, sums = out  # type: ignore[misc]
            all_summaries.extend(sums)
        else:
            fitness = out  # type: ignore[assignment]
        results.append((deck, fitness))

    if collect_telemetry:
        return (results, all_summaries)
    return results
