"""Tests for Phase 1: Data models."""

import random
import unittest

from card_battle.models import (
    Card, DeckDef, DeckEntry, GameResult, GameState, MatchLog,
    PlayerState, UnitInstance,
)


class TestCard(unittest.TestCase):
    def test_frozen(self):
        c = Card(id="x", name="X", cost=1, card_type="unit",
                 tags=("a",), template="Vanilla", params={"atk": 1, "hp": 1})
        with self.assertRaises(AttributeError):
            c.cost = 2  # type: ignore

    def test_is_unit(self):
        unit = Card(id="u", name="U", cost=1, card_type="unit",
                    tags=(), template="Vanilla", params={"atk": 1, "hp": 1})
        spell = Card(id="s", name="S", cost=1, card_type="spell",
                     tags=(), template="DamagePlayer", params={"amount": 1})
        self.assertTrue(unit.is_unit)
        self.assertFalse(spell.is_unit)


class TestPlayerState(unittest.TestCase):
    def test_defaults(self):
        p = PlayerState()
        self.assertEqual(p.hp, 20)
        self.assertEqual(p.mana, 0)
        self.assertEqual(p.deck, [])
        self.assertEqual(p.hand, [])
        self.assertEqual(p.board, [])

    def test_independent_lists(self):
        p1 = PlayerState()
        p2 = PlayerState()
        p1.hand.append("x")
        self.assertEqual(p2.hand, [])


class TestGameState(unittest.TestCase):
    def test_opponent_idx(self):
        gs = GameState(
            turn=1, active_player=0,
            players=[PlayerState(), PlayerState()],
            next_uid=1, result=None,
            rng=random.Random(42), card_db={},
        )
        self.assertEqual(gs.opponent_idx(), 1)
        gs.active_player = 1
        self.assertEqual(gs.opponent_idx(), 0)

    def test_alloc_uid(self):
        gs = GameState(
            turn=1, active_player=0,
            players=[PlayerState(), PlayerState()],
            next_uid=10, result=None,
            rng=random.Random(42), card_db={},
        )
        self.assertEqual(gs.alloc_uid(), 10)
        self.assertEqual(gs.alloc_uid(), 11)
        self.assertEqual(gs.next_uid, 12)


class TestGameResult(unittest.TestCase):
    def test_values(self):
        self.assertEqual(GameResult.PLAYER_0_WIN.value, "player_0_win")
        self.assertEqual(GameResult.DRAW.value, "draw")


class TestMatchLog(unittest.TestCase):
    def test_creation(self):
        log = MatchLog(
            seed=42, deck_ids=("a", "b"),
            winner=GameResult.DRAW, turns=10,
            final_hp=(5, 5),
        )
        self.assertIsNone(log.play_trace)


if __name__ == "__main__":
    unittest.main()
