"""Tests for Phase 2: Effect templates."""

import random
import unittest

from card_battle.effects import EFFECT_REGISTRY, resolve_effect, _draw_one
from card_battle.models import Card, GameState, PlayerState, UnitInstance


def _make_gs(**kwargs) -> GameState:
    defaults = dict(
        turn=1, active_player=0,
        players=[PlayerState(deck=["a", "b", "c"]), PlayerState(deck=["d", "e", "f"])],
        next_uid=1, result=None,
        rng=random.Random(42), card_db={},
    )
    defaults.update(kwargs)
    return GameState(**defaults)


class TestRegistry(unittest.TestCase):
    def test_all_templates_registered(self):
        expected = {"Vanilla", "OnPlayDamagePlayer", "OnPlayDraw",
                    "DamagePlayer", "HealSelf", "Draw", "RemoveUnit"}
        self.assertTrue(expected.issubset(set(EFFECT_REGISTRY.keys())))

    def test_unknown_template_raises(self):
        gs = _make_gs()
        with self.assertRaises(ValueError):
            resolve_effect(gs, 0, "NonExistent", {})


class TestDrawOne(unittest.TestCase):
    def test_draw_success(self):
        gs = _make_gs()
        ok = _draw_one(gs, 0)
        self.assertTrue(ok)
        self.assertEqual(gs.players[0].hand, ["a"])
        self.assertEqual(gs.players[0].deck, ["b", "c"])

    def test_draw_empty_deck(self):
        gs = _make_gs()
        gs.players[0].deck = []
        ok = _draw_one(gs, 0)
        self.assertFalse(ok)


class TestDamagePlayer(unittest.TestCase):
    def test_damage(self):
        gs = _make_gs()
        resolve_effect(gs, 0, "DamagePlayer", {"amount": 5})
        self.assertEqual(gs.players[1].hp, 15)


class TestHealSelf(unittest.TestCase):
    def test_heal_normal(self):
        gs = _make_gs()
        gs.players[0].hp = 10
        resolve_effect(gs, 0, "HealSelf", {"amount": 5})
        self.assertEqual(gs.players[0].hp, 15)

    def test_heal_cap(self):
        gs = _make_gs()
        gs.players[0].hp = 18
        resolve_effect(gs, 0, "HealSelf", {"amount": 5})
        self.assertEqual(gs.players[0].hp, 20)


class TestDraw(unittest.TestCase):
    def test_draw_n(self):
        gs = _make_gs()
        resolve_effect(gs, 0, "Draw", {"n": 2})
        self.assertEqual(gs.players[0].hand, ["a", "b"])
        self.assertEqual(gs.players[0].deck, ["c"])


class TestRemoveUnit(unittest.TestCase):
    def test_remove_eligible(self):
        gs = _make_gs()
        gs.players[1].board = [
            UnitInstance(uid=1, card_id="big", atk=5, hp=5),
            UnitInstance(uid=2, card_id="small", atk=2, hp=3),
        ]
        resolve_effect(gs, 0, "RemoveUnit", {"max_hp": 4})
        self.assertEqual(len(gs.players[1].board), 1)
        self.assertEqual(gs.players[1].board[0].card_id, "big")
        self.assertIn("small", gs.players[1].graveyard)

    def test_remove_none_eligible(self):
        gs = _make_gs()
        gs.players[1].board = [
            UnitInstance(uid=1, card_id="big", atk=5, hp=5),
        ]
        resolve_effect(gs, 0, "RemoveUnit", {"max_hp": 4})
        self.assertEqual(len(gs.players[1].board), 1)


class TestOnPlayDamagePlayer(unittest.TestCase):
    def test_on_play_damage(self):
        gs = _make_gs()
        resolve_effect(gs, 0, "OnPlayDamagePlayer", {"atk": 2, "hp": 2, "amount": 3})
        self.assertEqual(gs.players[1].hp, 17)


class TestOnPlayDraw(unittest.TestCase):
    def test_on_play_draw(self):
        gs = _make_gs()
        resolve_effect(gs, 0, "OnPlayDraw", {"atk": 2, "hp": 3, "n": 1})
        self.assertEqual(gs.players[0].hand, ["a"])


if __name__ == "__main__":
    unittest.main()
