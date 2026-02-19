"""v0.3: Fitness evaluation via match simulation."""

from __future__ import annotations

import hashlib

from card_battle.ai import GreedyAI
from card_battle.engine import init_game, run_game
from card_battle.models import Card, DeckDef, GameResult


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
) -> float:
    """Evaluate a deck against the elite pool. Returns average win rate [0, 1].

    Each matchup is played matches_per_opponent times x 2 seats (normal + swapped).
    Win = 1.0, Draw = 0.5, Loss = 0.0.
    """
    if not elite_pool:
        return 0.5

    agents = (GreedyAI(), GreedyAI())
    total_score = 0.0
    total_games = 0

    for opponent in elite_pool:
        for game_idx in range(matches_per_opponent):
            for swapped in (False, True):
                seed = derive_match_seed(
                    global_seed, generation,
                    deck.deck_id, opponent.deck_id,
                    game_idx, swapped,
                )
                if swapped:
                    gs = init_game(card_db, opponent, deck, seed)
                    log = run_game(gs, agents)
                    # deck is player 1 when swapped
                    if log.winner == GameResult.PLAYER_1_WIN:
                        total_score += 1.0
                    elif log.winner == GameResult.DRAW:
                        total_score += 0.5
                else:
                    gs = init_game(card_db, deck, opponent, seed)
                    log = run_game(gs, agents)
                    # deck is player 0 when not swapped
                    if log.winner == GameResult.PLAYER_0_WIN:
                        total_score += 1.0
                    elif log.winner == GameResult.DRAW:
                        total_score += 0.5

                total_games += 1

    return total_score / total_games


def evaluate_population(
    population: list[DeckDef],
    elite_pool: list[DeckDef],
    card_db: dict[str, Card],
    global_seed: int,
    generation: int,
    matches_per_opponent: int,
) -> list[tuple[DeckDef, float]]:
    """Evaluate all decks in a population against the elite pool."""
    results: list[tuple[DeckDef, float]] = []
    for deck in population:
        fitness = evaluate_deck_vs_pool(
            deck, elite_pool, card_db,
            global_seed, generation, matches_per_opponent,
        )
        results.append((deck, fitness))
    return results
