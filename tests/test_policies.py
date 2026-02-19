"""Tests for v3.2: Multi-policy evaluation."""

import os
import tempfile
import unittest

from card_battle.ai import GreedyAI, RandomAI, SimpleAI
from card_battle.evaluation import derive_match_seed, evaluate_deck_vs_pool
from card_battle.loader import load_cards, load_deck
from card_battle.policies import (
    Policy,
    PolicyRegistry,
    default_registry,
    normalize_weights,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


class TestPolicyRegistry(unittest.TestCase):
    def test_default_has_three_policies(self):
        reg = default_registry()
        names = reg.list_policies()
        self.assertEqual(names, ["greedy", "random", "simple"])

    def test_unknown_name_raises(self):
        reg = default_registry()
        with self.assertRaises(KeyError):
            reg.get_policy("nonexistent")

    def test_custom_registration(self):
        reg = PolicyRegistry()
        p = Policy(name="custom", make_agent=lambda seed: GreedyAI())
        reg.register(p)
        self.assertEqual(reg.get_policy("custom"), p)
        self.assertEqual(reg.list_policies(), ["custom"])


class TestMakeAgent(unittest.TestCase):
    def test_greedy_returns_greedy(self):
        reg = default_registry()
        agent = reg.get_policy("greedy").make_agent(42)
        self.assertIsInstance(agent, GreedyAI)

    def test_simple_returns_simple(self):
        reg = default_registry()
        agent = reg.get_policy("simple").make_agent(42)
        self.assertIsInstance(agent, SimpleAI)

    def test_random_returns_random(self):
        reg = default_registry()
        agent = reg.get_policy("random").make_agent(42)
        self.assertIsInstance(agent, RandomAI)


class TestNormalizeWeights(unittest.TestCase):
    def test_basic_normalization(self):
        entries = [
            {"name": "greedy", "weight": 3},
            {"name": "simple", "weight": 1},
        ]
        result = normalize_weights(entries)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "greedy")
        self.assertAlmostEqual(result[0][1], 0.75)
        self.assertEqual(result[1][0], "simple")
        self.assertAlmostEqual(result[1][1], 0.25)

    def test_already_normalized(self):
        entries = [
            {"name": "a", "weight": 0.6},
            {"name": "b", "weight": 0.4},
        ]
        result = normalize_weights(entries)
        self.assertAlmostEqual(result[0][1], 0.6)
        self.assertAlmostEqual(result[1][1], 0.4)

    def test_negative_weight_raises(self):
        with self.assertRaises(ValueError):
            normalize_weights([{"name": "a", "weight": -1}])

    def test_zero_total_raises(self):
        with self.assertRaises(ValueError):
            normalize_weights([{"name": "a", "weight": 0}])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            normalize_weights([])


class TestRandomAIDeterminism(unittest.TestCase):
    def test_same_seed_same_result(self):
        """Same seed produces identical action sequences over 5 replays."""
        import random
        from card_battle.actions import EndTurn, PlayCard
        from card_battle.models import GameState, PlayerState, Card

        card_db = {"soldier": Card(
            id="soldier", name="Soldier", cost=2, card_type="unit",
            tags=(), template="Vanilla", params={"atk": 2, "hp": 2},
        )}
        actions = [PlayCard(hand_index=0), EndTurn()]

        results = []
        for _ in range(5):
            ai = RandomAI(seed=123)
            choices = [ai.choose_action(
                GameState(
                    turn=1, active_player=0,
                    players=[PlayerState(mana=5, mana_max=5, deck=["soldier"] * 10),
                             PlayerState(deck=["soldier"] * 10)],
                    next_uid=1, result=None, rng=random.Random(42), card_db=card_db,
                ),
                actions,
            ) for _ in range(3)]
            results.append(choices)

        for r in results[1:]:
            self.assertEqual(results[0], r)

    def test_different_seeds_differ(self):
        """Different seeds produce different action sequences with high probability."""
        import random
        from card_battle.actions import EndTurn, PlayCard
        from card_battle.models import GameState, PlayerState, Card

        card_db = {"soldier": Card(
            id="soldier", name="Soldier", cost=2, card_type="unit",
            tags=(), template="Vanilla", params={"atk": 2, "hp": 2},
        )}
        actions = [PlayCard(hand_index=0), EndTurn()]

        sequences = []
        for seed in range(10):
            ai = RandomAI(seed=seed)
            choices = []
            for _ in range(20):
                c = ai.choose_action(
                    GameState(
                        turn=1, active_player=0,
                        players=[PlayerState(mana=5, mana_max=5, deck=["soldier"] * 10),
                                 PlayerState(deck=["soldier"] * 10)],
                        next_uid=1, result=None, rng=random.Random(42), card_db=card_db,
                    ),
                    actions,
                )
                choices.append(c)
            sequences.append(choices)

        # At least some seeds should produce different sequences
        unique = len(set(str(s) for s in sequences))
        self.assertGreater(unique, 1)


class TestDeriveMatchSeedWithPolicies(unittest.TestCase):
    def test_empty_policy_backward_compatible(self):
        """Empty policy names produce the same seed as v3.1."""
        s1 = derive_match_seed(42, 0, "a", "b", 0, False)
        s2 = derive_match_seed(42, 0, "a", "b", 0, False, "", "")
        self.assertEqual(s1, s2)

    def test_policy_name_changes_seed(self):
        """Adding policy names produces a different seed."""
        s1 = derive_match_seed(42, 0, "a", "b", 0, False)
        s2 = derive_match_seed(42, 0, "a", "b", 0, False, "greedy", "simple")
        self.assertNotEqual(s1, s2)

    def test_different_pairs_no_collision(self):
        """Different policy pairs produce unique seeds."""
        pairs = [
            ("greedy", "greedy"),
            ("greedy", "simple"),
            ("greedy", "random"),
            ("simple", "greedy"),
            ("simple", "simple"),
            ("random", "greedy"),
        ]
        seeds = set()
        for pc, po in pairs:
            s = derive_match_seed(42, 0, "a", "b", 0, False, pc, po)
            seeds.add(s)
        self.assertEqual(len(seeds), len(pairs))


class TestMultiPolicyEvaluation(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.aggro = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db
        )
        self.control = load_deck(
            os.path.join(DATA_DIR, "decks", "control_mage.json"), self.card_db
        )

    def test_none_is_backward_compatible(self):
        """policy_mix=None produces the same result as v3.1."""
        f1 = evaluate_deck_vs_pool(
            self.aggro, [self.control], self.card_db, 42, 0, 1,
            policy_mix=None,
        )
        f2 = evaluate_deck_vs_pool(
            self.aggro, [self.control], self.card_db, 42, 0, 1,
        )
        self.assertEqual(f1, f2)

    def test_greedy_only_mix_valid_fitness(self):
        """Greedy-only mix produces valid fitness in [0, 1]."""
        mix = {"candidates": [{"name": "greedy", "weight": 1.0}],
               "opponents": [{"name": "greedy", "weight": 1.0}]}
        fitness = evaluate_deck_vs_pool(
            self.aggro, [self.control], self.card_db, 42, 0, 1,
            policy_mix=mix,
        )
        self.assertGreaterEqual(fitness, 0.0)
        self.assertLessEqual(fitness, 1.0)

    def test_multi_mix_fitness_range(self):
        """Multi-policy mix produces fitness in [0, 1]."""
        mix = {
            "candidates": [
                {"name": "greedy", "weight": 0.6},
                {"name": "simple", "weight": 0.3},
                {"name": "random", "weight": 0.1},
            ],
            "opponents": [
                {"name": "greedy", "weight": 0.7},
                {"name": "simple", "weight": 0.3},
            ],
        }
        fitness = evaluate_deck_vs_pool(
            self.aggro, [self.control], self.card_db, 42, 0, 1,
            policy_mix=mix,
        )
        self.assertGreaterEqual(fitness, 0.0)
        self.assertLessEqual(fitness, 1.0)

    def test_determinism(self):
        """Same policy_mix and seed produce identical fitness."""
        mix = {
            "candidates": [
                {"name": "greedy", "weight": 0.5},
                {"name": "random", "weight": 0.5},
            ],
            "opponents": [{"name": "greedy", "weight": 1.0}],
        }
        f1 = evaluate_deck_vs_pool(
            self.aggro, [self.control], self.card_db, 42, 0, 1,
            policy_mix=mix,
        )
        f2 = evaluate_deck_vs_pool(
            self.aggro, [self.control], self.card_db, 42, 0, 1,
            policy_mix=mix,
        )
        self.assertEqual(f1, f2)

    def test_telemetry_has_policy_fields(self):
        """Telemetry summaries include candidate_policy and opponent_policy."""
        mix = {
            "candidates": [{"name": "greedy", "weight": 1.0}],
            "opponents": [{"name": "simple", "weight": 1.0}],
        }
        fitness, summaries = evaluate_deck_vs_pool(
            self.aggro, [self.control], self.card_db, 42, 0, 1,
            collect_telemetry=True, policy_mix=mix,
        )
        self.assertGreater(len(summaries), 0)
        for s in summaries:
            self.assertIn("candidate_policy", s)
            self.assertIn("opponent_policy", s)
            self.assertEqual(s["candidate_policy"], "greedy")
            self.assertEqual(s["opponent_policy"], "simple")

    def test_empty_pool_returns_half(self):
        """Empty pool with policy_mix returns 0.5."""
        mix = {"candidates": [{"name": "greedy", "weight": 1.0}],
               "opponents": [{"name": "greedy", "weight": 1.0}]}
        fitness = evaluate_deck_vs_pool(
            self.aggro, [], self.card_db, 42, 0, 1,
            policy_mix=mix,
        )
        self.assertEqual(fitness, 0.5)


if __name__ == "__main__":
    unittest.main()
