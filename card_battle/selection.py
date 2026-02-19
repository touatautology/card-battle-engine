"""v0.3: Selection operators for evolutionary deck search."""

from __future__ import annotations

import math
import random

from card_battle.models import DeckDef


def select_next_generation(
    population: list[tuple[DeckDef, float]],
    target_size: int,
    elitism: int,
    tournament_k: int,
    rng: random.Random,
) -> list[DeckDef]:
    """Select decks for the next generation.

    1. Sort by fitness descending.
    2. Keep top `elitism` decks unchanged.
    3. Fill remaining slots via tournament selection (k-way).
    """
    if not population:
        raise ValueError("Cannot select from empty population")

    # Sort by fitness descending
    ranked = sorted(population, key=lambda x: x[1], reverse=True)

    next_gen: list[DeckDef] = []

    # Elite preservation
    for i in range(min(elitism, len(ranked))):
        next_gen.append(ranked[i][0])

    # Tournament selection for the rest
    remaining = target_size - len(next_gen)
    for _ in range(remaining):
        # Sample k individuals, pick the best
        k = min(tournament_k, len(ranked))
        contestants = rng.sample(ranked, k)
        winner = max(contestants, key=lambda x: x[1])
        next_gen.append(winner[0])

    return next_gen


def compute_fitness_stats(
    population: list[tuple[DeckDef, float]],
) -> dict[str, float]:
    """Compute mean, max, min, std of fitness values."""
    if not population:
        return {"mean": 0.0, "max": 0.0, "min": 0.0, "std": 0.0}

    fitnesses = [f for _, f in population]
    n = len(fitnesses)
    mean = sum(fitnesses) / n
    max_f = max(fitnesses)
    min_f = min(fitnesses)
    variance = sum((f - mean) ** 2 for f in fitnesses) / n
    std = math.sqrt(variance)

    return {
        "mean": round(mean, 4),
        "max": round(max_f, 4),
        "min": round(min_f, 4),
        "std": round(std, 4),
    }
