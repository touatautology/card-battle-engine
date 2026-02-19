"""Phase 7: Determinism test – same seed → same result, every time."""

import os
import unittest

from card_battle.ai import GreedyAI
from card_battle.engine import init_game, run_game
from card_battle.loader import load_cards, load_deck


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_result_10_runs(self):
        card_db = load_cards(CARDS_JSON)
        deck_a = load_deck(os.path.join(DATA_DIR, "decks", "aggro_rush.json"), card_db)
        deck_b = load_deck(os.path.join(DATA_DIR, "decks", "control_mage.json"), card_db)
        seed = 12345

        results = []
        for _ in range(10):
            gs = init_game(card_db, deck_a, deck_b, seed)
            agents = (GreedyAI(), GreedyAI())
            log = run_game(gs, agents, trace=True)
            results.append((
                log.winner,
                log.turns,
                log.final_hp,
                len(log.play_trace),
            ))

        # All 10 runs must produce identical results
        for i in range(1, len(results)):
            self.assertEqual(results[0], results[i],
                             f"Run 0 vs run {i} differ: {results[0]} != {results[i]}")

    def test_different_seeds_different_results(self):
        """Different seeds should (very likely) produce different games."""
        card_db = load_cards(CARDS_JSON)
        deck_a = load_deck(os.path.join(DATA_DIR, "decks", "aggro_rush.json"), card_db)
        deck_b = load_deck(os.path.join(DATA_DIR, "decks", "control_mage.json"), card_db)

        results = set()
        for seed in range(10):
            gs = init_game(card_db, deck_a, deck_b, seed)
            agents = (GreedyAI(), GreedyAI())
            log = run_game(gs, agents)
            results.add((log.winner, log.turns, log.final_hp))

        # With 10 different seeds, expect at least 2 distinct outcomes
        self.assertGreater(len(results), 1)


if __name__ == "__main__":
    unittest.main()
