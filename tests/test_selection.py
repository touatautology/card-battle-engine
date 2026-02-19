"""Tests for v0.3: Selection operators."""

import random
import unittest

from card_battle.models import DeckDef, DeckEntry
from card_battle.selection import compute_fitness_stats, select_next_generation


def _make_deck(deck_id: str) -> DeckDef:
    """Create a minimal valid 30-card deck for testing."""
    # 10 unique cards x 3 copies = 30
    entries = tuple(
        DeckEntry(card_id=f"card_{i}", count=3) for i in range(10)
    )
    return DeckDef(deck_id=deck_id, entries=entries)


class TestSelectNextGeneration(unittest.TestCase):
    def setUp(self):
        # 10 decks with fitness 0.0 to 0.9
        self.population = [
            (_make_deck(f"deck_{i}"), i * 0.1) for i in range(10)
        ]

    def test_output_size(self):
        result = select_next_generation(
            self.population, target_size=10, elitism=3, tournament_k=4,
            rng=random.Random(42),
        )
        self.assertEqual(len(result), 10)

    def test_elites_are_top(self):
        """Top elitism decks should be the highest-fitness ones."""
        result = select_next_generation(
            self.population, target_size=10, elitism=3, tournament_k=4,
            rng=random.Random(42),
        )
        elite_ids = {result[i].deck_id for i in range(3)}
        # The top 3 by fitness are deck_9, deck_8, deck_7
        self.assertIn("deck_9", elite_ids)
        self.assertIn("deck_8", elite_ids)
        self.assertIn("deck_7", elite_ids)

    def test_deterministic(self):
        r1 = select_next_generation(
            self.population, 10, 3, 4, random.Random(99))
        r2 = select_next_generation(
            self.population, 10, 3, 4, random.Random(99))
        self.assertEqual([d.deck_id for d in r1], [d.deck_id for d in r2])

    def test_empty_population_raises(self):
        with self.assertRaises(ValueError):
            select_next_generation([], 5, 2, 3, random.Random(0))

    def test_small_population(self):
        """Elitism larger than population should not crash."""
        small = [(_make_deck("only"), 1.0)]
        result = select_next_generation(small, 5, 3, 2, random.Random(0))
        self.assertEqual(len(result), 5)


class TestComputeFitnessStats(unittest.TestCase):
    def test_basic(self):
        pop = [(_make_deck(f"d{i}"), float(i)) for i in range(5)]
        stats = compute_fitness_stats(pop)
        self.assertEqual(stats["max"], 4.0)
        self.assertEqual(stats["min"], 0.0)
        self.assertAlmostEqual(stats["mean"], 2.0)
        self.assertGreater(stats["std"], 0)

    def test_empty(self):
        stats = compute_fitness_stats([])
        self.assertEqual(stats["mean"], 0.0)

    def test_single(self):
        stats = compute_fitness_stats([(_make_deck("x"), 0.5)])
        self.assertEqual(stats["mean"], 0.5)
        self.assertEqual(stats["std"], 0.0)


if __name__ == "__main__":
    unittest.main()
