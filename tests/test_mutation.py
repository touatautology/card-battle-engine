"""Tests for v0.3: Deck mutation operators."""

import os
import random
import unittest

from card_battle.loader import load_cards, load_deck
from card_battle.mutation import (
    DECK_SIZE,
    MAX_COPIES,
    counts_to_deck,
    deck_to_counts,
    mutate_deck,
    random_deck,
    swap_n,
    swap_one,
    tweak_counts,
    validate_counts,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


class TestDeckCountsConversion(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.deck = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db
        )

    def test_round_trip(self):
        """deck_to_counts -> counts_to_deck produces equivalent deck."""
        counts = deck_to_counts(self.deck)
        rebuilt = counts_to_deck(self.deck.deck_id, counts)
        # Same total cards
        self.assertEqual(
            sum(e.count for e in rebuilt.entries),
            sum(e.count for e in self.deck.entries),
        )
        # Same card counts (order may differ since counts_to_deck sorts)
        original = {e.card_id: e.count for e in self.deck.entries}
        rebuilt_map = {e.card_id: e.count for e in rebuilt.entries}
        self.assertEqual(original, rebuilt_map)

    def test_validate_counts_valid(self):
        counts = deck_to_counts(self.deck)
        self.assertTrue(validate_counts(counts))

    def test_validate_counts_wrong_total(self):
        counts = deck_to_counts(self.deck)
        # Remove a card
        first = next(iter(counts))
        counts[first] -= 1
        if counts[first] == 0:
            del counts[first]
        self.assertFalse(validate_counts(counts))

    def test_validate_counts_over_max(self):
        counts = {"goblin": 4, "wolf": 3, "soldier": 3}  # goblin=4 invalid
        self.assertFalse(validate_counts(counts))

    def test_counts_to_deck_rejects_invalid(self):
        with self.assertRaises(ValueError):
            counts_to_deck("bad", {"goblin": 4, "wolf": 26})


class TestSwapOne(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.deck = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db
        )

    def test_preserves_constraints(self):
        """swap_one always produces valid 30-card deck with counts in [1,3]."""
        rng = random.Random(42)
        counts = deck_to_counts(self.deck)
        for _ in range(100):
            result = swap_one(counts, self.card_db, rng)
            self.assertTrue(validate_counts(result),
                            f"Invalid counts: {result}")

    def test_deterministic(self):
        """Same seed produces same result."""
        counts = deck_to_counts(self.deck)
        r1 = swap_one(counts, self.card_db, random.Random(99))
        r2 = swap_one(counts, self.card_db, random.Random(99))
        self.assertEqual(r1, r2)


class TestSwapN(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.deck = load_deck(
            os.path.join(DATA_DIR, "decks", "midrange.json"), self.card_db
        )

    def test_preserves_constraints(self):
        rng = random.Random(7)
        counts = deck_to_counts(self.deck)
        for _ in range(50):
            result = swap_n(counts, self.card_db, rng, (2, 5))
            self.assertTrue(validate_counts(result))


class TestTweakCounts(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.deck = load_deck(
            os.path.join(DATA_DIR, "decks", "control_mage.json"), self.card_db
        )

    def test_preserves_constraints(self):
        rng = random.Random(123)
        counts = deck_to_counts(self.deck)
        for _ in range(100):
            result = tweak_counts(counts, self.card_db, rng)
            self.assertTrue(validate_counts(result),
                            f"Invalid counts: {result}")

    def test_can_add_new_card(self):
        """tweak_counts can introduce a card not in the original deck."""
        rng = random.Random(0)
        counts = deck_to_counts(self.deck)
        original_cards = set(counts.keys())
        found_new = False
        for _ in range(200):
            result = tweak_counts(counts, self.card_db, rng)
            if set(result.keys()) != original_cards:
                found_new = True
                break
        self.assertTrue(found_new, "tweak_counts never introduced a new card")


class TestMutateDeck(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.deck = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db
        )
        self.weights = {"swap_one": 0.5, "swap_n": 0.3, "tweak_counts": 0.2}

    def test_preserves_constraints(self):
        rng = random.Random(42)
        for _ in range(50):
            result = mutate_deck(self.deck, self.card_db, rng, self.weights)
            counts = deck_to_counts(result)
            self.assertTrue(validate_counts(counts))

    def test_deterministic(self):
        d1 = mutate_deck(self.deck, self.card_db, random.Random(42), self.weights)
        d2 = mutate_deck(self.deck, self.card_db, random.Random(42), self.weights)
        self.assertEqual(deck_to_counts(d1), deck_to_counts(d2))

    def test_unknown_operator_raises(self):
        with self.assertRaises(ValueError):
            mutate_deck(self.deck, self.card_db, random.Random(0), {"unknown_op": 1.0})


class TestRandomDeck(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)

    def test_valid(self):
        rng = random.Random(42)
        for i in range(20):
            deck = random_deck(f"rnd_{i}", self.card_db, rng)
            counts = deck_to_counts(deck)
            self.assertTrue(validate_counts(counts))

    def test_deterministic(self):
        d1 = random_deck("a", self.card_db, random.Random(42))
        d2 = random_deck("a", self.card_db, random.Random(42))
        self.assertEqual(deck_to_counts(d1), deck_to_counts(d2))


if __name__ == "__main__":
    unittest.main()
