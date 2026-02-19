"""Tests for Phase 5: Game engine."""

import os
import unittest

from card_battle.ai import GreedyAI
from card_battle.engine import init_game, run_game, MAX_TURNS
from card_battle.loader import load_cards, load_deck
from card_battle.models import GameResult


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


class TestInitGame(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.deck_a = load_deck(os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db)
        self.deck_b = load_deck(os.path.join(DATA_DIR, "decks", "control_mage.json"), self.card_db)

    def test_initial_state(self):
        gs = init_game(self.card_db, self.deck_a, self.deck_b, seed=42)
        # Both players have 5 cards in hand
        self.assertEqual(len(gs.players[0].hand), 5)
        self.assertEqual(len(gs.players[1].hand), 5)
        # Decks reduced by 5
        self.assertEqual(len(gs.players[0].deck), 25)
        self.assertEqual(len(gs.players[1].deck), 25)
        # HP is 20
        self.assertEqual(gs.players[0].hp, 20)
        self.assertEqual(gs.players[1].hp, 20)
        # Turn starts at 0
        self.assertEqual(gs.turn, 0)
        # Active player is 0 or 1
        self.assertIn(gs.active_player, (0, 1))

    def test_different_seeds_different_hands(self):
        gs1 = init_game(self.card_db, self.deck_a, self.deck_b, seed=1)
        gs2 = init_game(self.card_db, self.deck_a, self.deck_b, seed=2)
        # Highly unlikely to be identical
        hands_1 = (gs1.players[0].hand[:], gs1.players[1].hand[:])
        hands_2 = (gs2.players[0].hand[:], gs2.players[1].hand[:])
        self.assertNotEqual(hands_1, hands_2)


class TestRunGame(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.deck_a = load_deck(os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db)
        self.deck_b = load_deck(os.path.join(DATA_DIR, "decks", "control_mage.json"), self.card_db)

    def test_game_completes(self):
        gs = init_game(self.card_db, self.deck_a, self.deck_b, seed=42)
        agents = (GreedyAI(), GreedyAI())
        log = run_game(gs, agents)
        self.assertIsNotNone(gs.result)
        self.assertIn(gs.result, (GameResult.PLAYER_0_WIN, GameResult.PLAYER_1_WIN, GameResult.DRAW))
        self.assertGreater(log.turns, 0)

    def test_game_with_trace(self):
        gs = init_game(self.card_db, self.deck_a, self.deck_b, seed=42)
        agents = (GreedyAI(), GreedyAI())
        log = run_game(gs, agents, trace=True)
        self.assertIsNotNone(log.play_trace)
        self.assertGreater(len(log.play_trace), 0)

    def test_turn_limit(self):
        # A game should not exceed MAX_TURNS
        gs = init_game(self.card_db, self.deck_a, self.deck_b, seed=42)
        agents = (GreedyAI(), GreedyAI())
        log = run_game(gs, agents)
        self.assertLessEqual(log.turns, MAX_TURNS)


if __name__ == "__main__":
    unittest.main()
