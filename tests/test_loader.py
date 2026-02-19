"""Tests for Phase 4: Data loading."""

import json
import os
import tempfile
import unittest

from card_battle.loader import load_cards, load_deck


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


class TestLoadCards(unittest.TestCase):
    def test_load_all_cards(self):
        db = load_cards(CARDS_JSON)
        self.assertEqual(len(db), 20)
        self.assertIn("goblin", db)
        self.assertIn("dragon", db)

    def test_card_fields(self):
        db = load_cards(CARDS_JSON)
        bolt = db["bolt"]
        self.assertEqual(bolt.name, "Lightning Bolt")
        self.assertEqual(bolt.cost, 1)
        self.assertEqual(bolt.card_type, "spell")
        self.assertEqual(bolt.template, "DamagePlayer")

    def test_invalid_card_type(self):
        data = [{"id": "x", "name": "X", "cost": 1, "card_type": "artifact",
                 "template": "Vanilla", "params": {"atk": 1, "hp": 1}}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            with self.assertRaises(ValueError):
                load_cards(f.name)
        os.unlink(f.name)

    def test_invalid_cost_range(self):
        data = [{"id": "x", "name": "X", "cost": 11, "card_type": "unit",
                 "template": "Vanilla", "params": {"atk": 1, "hp": 1}}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            with self.assertRaises(ValueError):
                load_cards(f.name)
        os.unlink(f.name)


class TestLoadDeck(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)

    def test_load_aggro(self):
        deck = load_deck(os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db)
        self.assertEqual(deck.deck_id, "aggro_rush")
        total = sum(e.count for e in deck.entries)
        self.assertEqual(total, 30)

    def test_load_control(self):
        deck = load_deck(os.path.join(DATA_DIR, "decks", "control_mage.json"), self.card_db)
        total = sum(e.count for e in deck.entries)
        self.assertEqual(total, 30)

    def test_load_midrange(self):
        deck = load_deck(os.path.join(DATA_DIR, "decks", "midrange.json"), self.card_db)
        total = sum(e.count for e in deck.entries)
        self.assertEqual(total, 30)

    def test_invalid_count(self):
        data = {"deck_id": "bad", "entries": [
            {"card_id": "goblin", "count": 4},
        ]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            with self.assertRaises(ValueError):
                load_deck(f.name, self.card_db)
        os.unlink(f.name)

    def test_unknown_card(self):
        data = {"deck_id": "bad", "entries": [
            {"card_id": "nonexistent", "count": 3},
        ]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            with self.assertRaises(ValueError):
                load_deck(f.name, self.card_db)
        os.unlink(f.name)

    def test_wrong_total(self):
        data = {"deck_id": "bad", "entries": [
            {"card_id": "goblin", "count": 3},
            {"card_id": "soldier", "count": 3},
        ]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            with self.assertRaises(ValueError):
                load_deck(f.name, self.card_db)
        os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
