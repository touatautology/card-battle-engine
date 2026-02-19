"""Tests for Phase 5: Game engine (v0.2 with blocking)."""

import os
import unittest

from card_battle.ai import GreedyAI
from card_battle.engine import init_game, run_game, _resolve_combat, MAX_TURNS
from card_battle.loader import load_cards, load_deck
from card_battle.models import (
    CombatState, GameResult, GameState, PlayerState, UnitInstance,
)
import random


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


def _card_db():
    return {
        "soldier": __import__("card_battle.models", fromlist=["Card"]).Card(
            id="soldier", name="Soldier", cost=2, card_type="unit",
            tags=(), template="Vanilla", params={"atk": 2, "hp": 2},
        ),
        "knight": __import__("card_battle.models", fromlist=["Card"]).Card(
            id="knight", name="Knight", cost=3, card_type="unit",
            tags=(), template="Vanilla", params={"atk": 3, "hp": 4},
        ),
    }


def _make_gs(**kwargs):
    from card_battle.models import Card
    db = _card_db()
    defaults = dict(
        turn=1, active_player=0,
        players=[
            PlayerState(mana=5, mana_max=5, deck=["soldier"] * 10),
            PlayerState(deck=["soldier"] * 10),
        ],
        next_uid=100, result=None,
        rng=random.Random(42), card_db=db,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


class TestInitGame(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.deck_a = load_deck(os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db)
        self.deck_b = load_deck(os.path.join(DATA_DIR, "decks", "control_mage.json"), self.card_db)

    def test_initial_state(self):
        gs = init_game(self.card_db, self.deck_a, self.deck_b, seed=42)
        self.assertEqual(len(gs.players[0].hand), 5)
        self.assertEqual(len(gs.players[1].hand), 5)
        self.assertEqual(len(gs.players[0].deck), 25)
        self.assertEqual(len(gs.players[1].deck), 25)
        self.assertEqual(gs.players[0].hp, 20)
        self.assertEqual(gs.players[1].hp, 20)
        self.assertEqual(gs.turn, 0)
        self.assertIn(gs.active_player, (0, 1))
        self.assertEqual(gs.phase, "main")

    def test_different_seeds_different_hands(self):
        gs1 = init_game(self.card_db, self.deck_a, self.deck_b, seed=1)
        gs2 = init_game(self.card_db, self.deck_a, self.deck_b, seed=2)
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
        gs = init_game(self.card_db, self.deck_a, self.deck_b, seed=42)
        agents = (GreedyAI(), GreedyAI())
        log = run_game(gs, agents)
        self.assertLessEqual(log.turns, MAX_TURNS)


class TestResolveCombat(unittest.TestCase):
    def test_unblocked_damage(self):
        """Unblocked attacker deals damage to defender player."""
        gs = _make_gs()
        gs.players[0].board = [
            UnitInstance(uid=1, card_id="soldier", atk=3, hp=2, can_attack=True),
        ]
        gs.combat = CombatState(attackers=[1], blocks={})
        _resolve_combat(gs)
        self.assertEqual(gs.players[1].hp, 17)  # 20 - 3
        # Attacker marked as used
        self.assertFalse(gs.players[0].board[0].can_attack)

    def test_blocked_mutual_damage(self):
        """Blocked attacker and blocker deal mutual damage."""
        gs = _make_gs()
        gs.players[0].board = [
            UnitInstance(uid=1, card_id="soldier", atk=3, hp=4, can_attack=True),
        ]
        gs.players[1].board = [
            UnitInstance(uid=10, card_id="soldier", atk=2, hp=3),
        ]
        gs.combat = CombatState(attackers=[1], blocks={1: 10})
        _resolve_combat(gs)
        # No player damage (blocked)
        self.assertEqual(gs.players[1].hp, 20)
        # Attacker: 4 - 2 = 2 hp
        self.assertEqual(gs.players[0].board[0].hp, 2)
        # Blocker: 3 - 3 = 0 hp → dead
        self.assertEqual(len(gs.players[1].board), 0)
        self.assertIn("soldier", gs.players[1].graveyard)

    def test_both_die(self):
        """Both attacker and blocker die from mutual damage."""
        gs = _make_gs()
        gs.players[0].board = [
            UnitInstance(uid=1, card_id="soldier", atk=2, hp=2, can_attack=True),
        ]
        gs.players[1].board = [
            UnitInstance(uid=10, card_id="soldier", atk=2, hp=2),
        ]
        gs.combat = CombatState(attackers=[1], blocks={1: 10})
        _resolve_combat(gs)
        self.assertEqual(gs.players[1].hp, 20)
        self.assertEqual(len(gs.players[0].board), 0)
        self.assertEqual(len(gs.players[1].board), 0)
        self.assertIn("soldier", gs.players[0].graveyard)
        self.assertIn("soldier", gs.players[1].graveyard)

    def test_mixed_blocked_and_unblocked(self):
        """One attacker blocked, another unblocked."""
        gs = _make_gs()
        gs.players[0].board = [
            UnitInstance(uid=1, card_id="soldier", atk=2, hp=2, can_attack=True),
            UnitInstance(uid=2, card_id="knight", atk=3, hp=4, can_attack=True),
        ]
        gs.players[1].board = [
            UnitInstance(uid=10, card_id="soldier", atk=2, hp=2),
        ]
        # blocker 10 blocks attacker 1, attacker 2 is unblocked
        gs.combat = CombatState(attackers=[1, 2], blocks={1: 10})
        _resolve_combat(gs)
        # Unblocked attacker 2 deals 3 to player
        self.assertEqual(gs.players[1].hp, 17)
        # Attacker 1 and blocker 10 trade: both die (2 vs 2)
        self.assertEqual(len(gs.players[0].board), 1)  # only knight survives
        self.assertEqual(gs.players[0].board[0].uid, 2)
        self.assertEqual(len(gs.players[1].board), 0)

    def test_empty_attackers(self):
        """Empty attackers list: no damage, no crash."""
        gs = _make_gs()
        gs.combat = CombatState(attackers=[], blocks={})
        _resolve_combat(gs)
        self.assertEqual(gs.players[1].hp, 20)


if __name__ == "__main__":
    unittest.main()
