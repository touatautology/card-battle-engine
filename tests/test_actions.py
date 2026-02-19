"""Tests for Phase 3: Actions."""

import random
import unittest

from card_battle.actions import (
    Action, Attack, EndTurn, PlayCard, BOARD_LIMIT,
    apply_action, get_legal_actions,
)
from card_battle.models import Card, GameState, PlayerState, UnitInstance


def _card_db() -> dict[str, Card]:
    return {
        "soldier": Card(id="soldier", name="Soldier", cost=2, card_type="unit",
                        tags=(), template="Vanilla", params={"atk": 2, "hp": 2}),
        "bolt": Card(id="bolt", name="Bolt", cost=1, card_type="spell",
                     tags=(), template="DamagePlayer", params={"amount": 3}),
        "dragon": Card(id="dragon", name="Dragon", cost=7, card_type="unit",
                       tags=(), template="Vanilla", params={"atk": 7, "hp": 7}),
    }


def _make_gs(**kwargs) -> GameState:
    db = _card_db()
    defaults = dict(
        turn=1, active_player=0,
        players=[PlayerState(mana=5, mana_max=5), PlayerState()],
        next_uid=1, result=None,
        rng=random.Random(42), card_db=db,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


class TestGetLegalActions(unittest.TestCase):
    def test_empty_hand_only_end_turn(self):
        gs = _make_gs()
        actions = get_legal_actions(gs)
        self.assertEqual(actions, [EndTurn()])

    def test_playable_card(self):
        gs = _make_gs()
        gs.players[0].hand = ["soldier"]
        actions = get_legal_actions(gs)
        self.assertIn(PlayCard(hand_index=0), actions)
        self.assertIn(EndTurn(), actions)

    def test_too_expensive(self):
        gs = _make_gs()
        gs.players[0].mana = 1
        gs.players[0].hand = ["dragon"]
        actions = get_legal_actions(gs)
        self.assertNotIn(PlayCard(hand_index=0), actions)

    def test_board_full_no_unit_play(self):
        gs = _make_gs()
        gs.players[0].hand = ["soldier"]
        gs.players[0].board = [
            UnitInstance(uid=i, card_id="soldier", atk=2, hp=2)
            for i in range(BOARD_LIMIT)
        ]
        actions = get_legal_actions(gs)
        # Can't play unit, but EndTurn is always there
        self.assertNotIn(PlayCard(hand_index=0), actions)

    def test_board_full_can_play_spell(self):
        gs = _make_gs()
        gs.players[0].hand = ["bolt"]
        gs.players[0].board = [
            UnitInstance(uid=i, card_id="soldier", atk=2, hp=2)
            for i in range(BOARD_LIMIT)
        ]
        actions = get_legal_actions(gs)
        self.assertIn(PlayCard(hand_index=0), actions)

    def test_attack_available(self):
        gs = _make_gs()
        gs.players[0].board = [
            UnitInstance(uid=1, card_id="soldier", atk=2, hp=2, can_attack=True),
        ]
        actions = get_legal_actions(gs)
        self.assertIn(Attack(board_index=0), actions)

    def test_summoning_sickness(self):
        gs = _make_gs()
        gs.players[0].board = [
            UnitInstance(uid=1, card_id="soldier", atk=2, hp=2, can_attack=False),
        ]
        actions = get_legal_actions(gs)
        self.assertNotIn(Attack(board_index=0), actions)


class TestApplyAction(unittest.TestCase):
    def test_play_unit(self):
        gs = _make_gs()
        gs.players[0].hand = ["soldier"]
        gs.players[0].mana = 5
        apply_action(gs, PlayCard(hand_index=0))
        self.assertEqual(gs.players[0].mana, 3)
        self.assertEqual(len(gs.players[0].board), 1)
        self.assertEqual(gs.players[0].board[0].atk, 2)
        self.assertFalse(gs.players[0].board[0].can_attack)

    def test_play_spell(self):
        gs = _make_gs()
        gs.players[0].hand = ["bolt"]
        gs.players[0].mana = 5
        apply_action(gs, PlayCard(hand_index=0))
        self.assertEqual(gs.players[0].mana, 4)
        self.assertEqual(gs.players[1].hp, 17)
        self.assertIn("bolt", gs.players[0].graveyard)

    def test_attack(self):
        gs = _make_gs()
        gs.players[0].board = [
            UnitInstance(uid=1, card_id="soldier", atk=3, hp=2, can_attack=True),
        ]
        apply_action(gs, Attack(board_index=0))
        self.assertEqual(gs.players[1].hp, 17)
        self.assertFalse(gs.players[0].board[0].can_attack)


if __name__ == "__main__":
    unittest.main()
