"""Tests for Phase 8: Simulation and aggregation."""

import os
import tempfile
import unittest

from card_battle.loader import load_cards, load_deck
from card_battle.models import GameResult
from card_battle.simulation import aggregate, compute_card_adoption, run_batch


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


class TestRunBatch(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.decks = [
            load_deck(os.path.join(DATA_DIR, "decks", f), self.card_db)
            for f in ("aggro_rush.json", "control_mage.json", "midrange.json")
        ]

    def test_batch_small(self):
        logs = run_batch(self.card_db, self.decks, n_matches=5, base_seed=0)
        # 3 decks → 3 pairs × 5 matches = 15
        self.assertEqual(len(logs), 15)
        for log in logs:
            self.assertIn(log.winner, (
                GameResult.PLAYER_0_WIN, GameResult.PLAYER_1_WIN, GameResult.DRAW))

    def test_batch_writes_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = run_batch(self.card_db, self.decks, n_matches=3, base_seed=0,
                             output_dir=tmpdir)
            logfile = os.path.join(tmpdir, "match_logs.json")
            self.assertTrue(os.path.exists(logfile))

    def test_1000_matches_no_crash(self):
        """Acceptance criterion: 1000 matches run without errors."""
        logs = run_batch(self.card_db, self.decks, n_matches=334, base_seed=42)
        # 3 pairs × 334 = 1002 matches
        self.assertGreaterEqual(len(logs), 1000)
        for log in logs:
            self.assertIsNotNone(log.winner)


class TestAggregate(unittest.TestCase):
    def setUp(self):
        card_db = load_cards(CARDS_JSON)
        decks = [
            load_deck(os.path.join(DATA_DIR, "decks", f), card_db)
            for f in ("aggro_rush.json", "control_mage.json")
        ]
        self.logs = run_batch(card_db, decks, n_matches=20, base_seed=0)

    def test_aggregate_structure(self):
        stats = aggregate(self.logs)
        self.assertIn("decks", stats)
        self.assertIn("total_matches", stats)
        self.assertEqual(stats["total_matches"], 20)
        for did, ds in stats["decks"].items():
            self.assertIn("win_rate", ds)
            self.assertEqual(ds["wins"] + ds["losses"] + ds["draws"], ds["games"])


class TestCardAdoption(unittest.TestCase):
    def test_adoption(self):
        card_db = load_cards(CARDS_JSON)
        decks = [
            load_deck(os.path.join(DATA_DIR, "decks", f), card_db)
            for f in ("aggro_rush.json", "control_mage.json", "midrange.json")
        ]
        adoption = compute_card_adoption(decks)
        # soldier is in all 3 decks
        self.assertEqual(adoption["soldier"], 3)
        # dragon is only in control_mage
        self.assertEqual(adoption["dragon"], 1)


if __name__ == "__main__":
    unittest.main()
