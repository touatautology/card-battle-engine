"""Tests for Phase 6: AI agents (v0.2 with blocking)."""

import random
import unittest

from card_battle.actions import EndTurn, GoToCombat, DeclareAttack, PlayCard
from card_battle.ai import GreedyAI, RandomAI, SimpleAI, _evaluate
from card_battle.models import Card, CombatState, GameState, PlayerState, UnitInstance


def _card_db() -> dict[str, Card]:
    return {
        "soldier": Card(id="soldier", name="Soldier", cost=2, card_type="unit",
                        tags=(), template="Vanilla", params={"atk": 2, "hp": 2}),
        "bolt": Card(id="bolt", name="Bolt", cost=1, card_type="spell",
                     tags=(), template="DamagePlayer", params={"amount": 3}),
    }


def _make_gs(**kwargs) -> GameState:
    db = _card_db()
    defaults = dict(
        turn=1, active_player=0,
        players=[
            PlayerState(mana=5, mana_max=5, deck=["soldier"] * 10),
            PlayerState(deck=["soldier"] * 10),
        ],
        next_uid=1, result=None,
        rng=random.Random(42), card_db=db,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


class TestEvaluate(unittest.TestCase):
    def test_initial_state_symmetric(self):
        gs = _make_gs()
        score = _evaluate(gs, 0)
        self.assertIsInstance(score, float)

    def test_opponent_dead_is_high(self):
        gs = _make_gs()
        gs.players[1].hp = 0
        score = _evaluate(gs, 0)
        self.assertGreaterEqual(score, 1000)

    def test_self_dead_is_low(self):
        gs = _make_gs()
        gs.players[0].hp = 0
        score = _evaluate(gs, 0)
        self.assertLessEqual(score, -1000)


class TestGreedyAI(unittest.TestCase):
    def test_prefers_bolt_over_end_turn(self):
        gs = _make_gs()
        gs.players[0].hand = ["bolt"]
        ai = GreedyAI()
        action = ai.choose_action(gs, [PlayCard(hand_index=0), EndTurn()])
        self.assertEqual(action, PlayCard(hand_index=0))

    def test_prefers_go_to_combat(self):
        gs = _make_gs()
        gs.players[0].board = [
            UnitInstance(uid=1, card_id="soldier", atk=2, hp=2, can_attack=True),
        ]
        ai = GreedyAI()
        action = ai.choose_action(gs, [GoToCombat(), EndTurn()])
        self.assertEqual(action, GoToCombat())

    def test_returns_end_turn_when_no_benefit(self):
        gs = _make_gs()
        ai = GreedyAI()
        action = ai.choose_action(gs, [EndTurn()])
        self.assertEqual(action, EndTurn())


class TestRandomAI(unittest.TestCase):
    def test_choice_in_legal_actions(self):
        gs = _make_gs()
        gs.players[0].hand = ["bolt"]
        ai = RandomAI(seed=42)
        actions = [PlayCard(hand_index=0), EndTurn()]
        choice = ai.choose_action(gs, actions)
        self.assertIn(choice, actions)

    def test_single_action(self):
        gs = _make_gs()
        ai = RandomAI(seed=0)
        choice = ai.choose_action(gs, [EndTurn()])
        self.assertEqual(choice, EndTurn())


class TestSimpleAI(unittest.TestCase):
    def test_prefers_bolt_over_end_turn(self):
        gs = _make_gs()
        gs.players[0].hand = ["bolt"]
        ai = SimpleAI()
        action = ai.choose_action(gs, [PlayCard(hand_index=0), EndTurn()])
        self.assertEqual(action, PlayCard(hand_index=0))

    def test_returns_end_turn_when_only_option(self):
        gs = _make_gs()
        ai = SimpleAI()
        action = ai.choose_action(gs, [EndTurn()])
        self.assertEqual(action, EndTurn())


if __name__ == "__main__":
    unittest.main()
