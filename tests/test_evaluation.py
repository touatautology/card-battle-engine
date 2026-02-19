"""Tests for v0.3: Evaluation and fitness calculation."""

import os
import unittest

from card_battle.evaluation import (
    derive_match_seed,
    evaluate_deck_vs_pool,
    evaluate_population,
)
from card_battle.loader import load_cards, load_deck

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


class TestDeriveMatchSeed(unittest.TestCase):
    def test_deterministic(self):
        s1 = derive_match_seed(42, 0, "deck_a", "deck_b", 0, False)
        s2 = derive_match_seed(42, 0, "deck_a", "deck_b", 0, False)
        self.assertEqual(s1, s2)

    def test_different_params_different_seeds(self):
        seeds = set()
        for gen in range(3):
            for idx in range(3):
                for swapped in (False, True):
                    s = derive_match_seed(42, gen, "a", "b", idx, swapped)
                    seeds.add(s)
        # 3 * 3 * 2 = 18 unique seeds expected
        self.assertEqual(len(seeds), 18)

    def test_seat_swap_differs(self):
        s1 = derive_match_seed(42, 0, "a", "b", 0, False)
        s2 = derive_match_seed(42, 0, "a", "b", 0, True)
        self.assertNotEqual(s1, s2)

    def test_returns_positive_int(self):
        s = derive_match_seed(42, 0, "a", "b", 0, False)
        self.assertIsInstance(s, int)
        self.assertGreater(s, 0)


class TestEvaluateDeckVsPool(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.aggro = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db
        )
        self.control = load_deck(
            os.path.join(DATA_DIR, "decks", "control_mage.json"), self.card_db
        )
        self.midrange = load_deck(
            os.path.join(DATA_DIR, "decks", "midrange.json"), self.card_db
        )

    def test_fitness_range(self):
        fitness = evaluate_deck_vs_pool(
            self.aggro, [self.control, self.midrange],
            self.card_db, 42, 0, 1,
        )
        self.assertGreaterEqual(fitness, 0.0)
        self.assertLessEqual(fitness, 1.0)

    def test_empty_pool_returns_half(self):
        fitness = evaluate_deck_vs_pool(
            self.aggro, [], self.card_db, 42, 0, 1,
        )
        self.assertEqual(fitness, 0.5)

    def test_deterministic(self):
        f1 = evaluate_deck_vs_pool(
            self.aggro, [self.control], self.card_db, 42, 0, 1)
        f2 = evaluate_deck_vs_pool(
            self.aggro, [self.control], self.card_db, 42, 0, 1)
        self.assertEqual(f1, f2)


class TestEvaluatePopulation(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.decks = [
            load_deck(os.path.join(DATA_DIR, "decks", f), self.card_db)
            for f in ("aggro_rush.json", "control_mage.json", "midrange.json")
        ]

    def test_returns_all(self):
        results = evaluate_population(
            self.decks, self.decks[:1], self.card_db, 42, 0, 1,
        )
        self.assertEqual(len(results), 3)
        for deck, fitness in results:
            self.assertGreaterEqual(fitness, 0.0)
            self.assertLessEqual(fitness, 1.0)


if __name__ == "__main__":
    unittest.main()
