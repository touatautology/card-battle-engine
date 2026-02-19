"""Tests for v0.6: Card mutation operators + diversity filter."""

import json
import os
import tempfile
import unittest

from card_battle.cardmut import (
    TEMPLATE_FAMILIES,
    _family_of,
    _mutation_seed,
    _op_cost_adjust,
    _op_param_jitter,
    _op_stat_redistribute,
    _op_template_swap_within_family,
    _swap_targets,
    card_distance,
    dedupe_and_filter_diversity,
    generate_mutations,
    mutate_candidate,
)
from card_battle.cardgen import (
    _candidate_id,
    generate_candidates,
    run_cardgen,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


def _sample_constraints() -> dict:
    return {
        "templates": {
            "HealSelf": {
                "card_type": "spell",
                "cost_range": [1, 4],
                "tags": ["heal"],
                "params_ranges": {"amount": [2, 6]},
            },
            "RemoveUnit": {
                "card_type": "spell",
                "cost_range": [1, 4],
                "tags": ["removal"],
                "params_ranges": {"max_hp": [1, 4]},
            },
            "DamagePlayer": {
                "card_type": "spell",
                "cost_range": [1, 5],
                "tags": ["damage"],
                "params_ranges": {"amount": [1, 6]},
            },
            "Vanilla": {
                "card_type": "unit",
                "cost_range": [1, 6],
                "tags": ["creature"],
                "params_ranges": {"atk": [1, 6], "hp": [1, 8]},
            },
            "OnPlayDraw": {
                "card_type": "unit",
                "cost_range": [2, 6],
                "tags": ["creature"],
                "params_ranges": {"atk": [1, 4], "hp": [1, 5], "n": [1, 3]},
            },
            "OnPlayDamagePlayer": {
                "card_type": "unit",
                "cost_range": [1, 5],
                "tags": ["creature"],
                "params_ranges": {"atk": [1, 4], "hp": [1, 4], "amount": [1, 3]},
            },
            "Draw": {
                "card_type": "spell",
                "cost_range": [1, 5],
                "tags": ["draw"],
                "params_ranges": {"n": [1, 3]},
            },
        },
        "global": {
            "max_new_cards": 50,
            "forbid": [
                {"template": "RemoveUnit", "condition": "max_hp >= 4 and cost <= 2"},
                {"template": "DamagePlayer", "condition": "amount >= 5 and cost <= 2"},
                {"template": "Vanilla", "condition": "atk + hp >= cost * 3 + 2"},
            ],
        },
    }


def _sample_config_with_mutations() -> dict:
    return {
        "seed": 42,
        "base_candidates_max": 20,
        "top_patterns_per_type": {"counter": 2, "sequence": 1, "cooccurrence": 1},
        "candidates_per_pattern": 2,
        "mode_weights": {"suppress": 0.7, "support": 0.3},
        "suppress_templates": ["HealSelf", "RemoveUnit", "Vanilla"],
        "support_templates": ["OnPlayDraw", "Vanilla", "Draw"],
        "mutations": {
            "enabled": True,
            "per_base": 4,
            "op_weights": {
                "param_jitter": 0.45,
                "cost_adjust": 0.25,
                "template_swap_within_family": 0.15,
                "stat_redistribute": 0.15,
            },
        },
        "diversity": {
            "enabled": True,
            "min_distance": 0.25,
            "max_per_template": 12,
        },
        "adoption": {
            "matches_per_eval": 1,
            "policy_mix": None,
            "acceptance": {
                "min_overall_delta": 0.02,
                "max_win_rate": 0.95,
                "max_turns_delta_pct": 0.20,
            },
            "max_copies_to_test": 2,
            "selected_top_n": 5,
        },
    }


def _sample_patterns() -> list[dict]:
    return [
        {
            "pattern_id": "pat_counter_1",
            "type": "counter",
            "scope": "matchup",
            "definition": {"target_deck_id": "aggro_rush", "cards": ["bolt"]},
            "stats": {"support": 10, "win_rate": 0.8, "lift": 1.5, "avg_turns": 15},
            "examples": {"match_ids": ["m1"]},
        },
        {
            "pattern_id": "pat_counter_2",
            "type": "counter",
            "scope": "matchup",
            "definition": {"target_deck_id": "control_mage", "cards": ["heal"]},
            "stats": {"support": 8, "win_rate": 0.7, "lift": 1.3, "avg_turns": 18},
            "examples": {"match_ids": ["m2"]},
        },
        {
            "pattern_id": "pat_seq_1",
            "type": "sequence",
            "scope": "matchup",
            "definition": {"turns": 3, "tokens": [{"played": ["goblin"], "atk": 0, "blk": 0}]},
            "stats": {"support": 15, "win_rate": 0.75, "lift": 1.4, "avg_turns": 12},
            "examples": {"match_ids": ["m3"]},
        },
        {
            "pattern_id": "pat_coocc_1",
            "type": "cooccurrence",
            "scope": "deck",
            "definition": {"cards": ["goblin", "wolf"]},
            "stats": {"support": 20, "win_rate": 0.65, "lift": 1.2, "avg_turns": 14},
            "examples": {"match_ids": ["m4"]},
        },
    ]


def _make_vanilla_candidate(atk=3, hp=4, cost=3) -> dict:
    cid = _candidate_id("Vanilla", {"atk": atk, "hp": hp}, 100)
    return {
        "id": cid,
        "name": f"cand_vanilla_{cid[-6:]}",
        "cost": cost,
        "card_type": "unit",
        "template": "Vanilla",
        "params": {"atk": atk, "hp": hp},
        "tags": ["creature"],
        "intent": {"mode": "suppress", "target_pattern_ids": [], "target_deck_ids": []},
        "gen_reason": {"source_patterns": [], "heuristic": "test"},
        "lineage": {"origin": "base", "parent_id": None, "mutation_op": None, "mutation_params": None},
    }


def _make_draw_candidate(n=2, cost=3) -> dict:
    cid = _candidate_id("Draw", {"n": n}, 200)
    return {
        "id": cid,
        "name": f"cand_draw_{cid[-6:]}",
        "cost": cost,
        "card_type": "spell",
        "template": "Draw",
        "params": {"n": n},
        "tags": ["draw"],
        "intent": {"mode": "support", "target_pattern_ids": [], "target_deck_ids": []},
        "gen_reason": {"source_patterns": [], "heuristic": "test"},
        "lineage": {"origin": "base", "parent_id": None, "mutation_op": None, "mutation_params": None},
    }


def _make_damage_candidate(amount=3, cost=2) -> dict:
    cid = _candidate_id("DamagePlayer", {"amount": amount}, 300)
    return {
        "id": cid,
        "name": f"cand_damageplayer_{cid[-6:]}",
        "cost": cost,
        "card_type": "spell",
        "template": "DamagePlayer",
        "params": {"amount": amount},
        "tags": ["damage"],
        "intent": {"mode": "suppress", "target_pattern_ids": [], "target_deck_ids": []},
        "gen_reason": {"source_patterns": [], "heuristic": "test"},
        "lineage": {"origin": "base", "parent_id": None, "mutation_op": None, "mutation_params": None},
    }


# =====================================================================
# TestMutationSeed
# =====================================================================

class TestMutationSeed(unittest.TestCase):
    def test_same_input_same_seed(self):
        s1 = _mutation_seed(42, "cand_abc", "param_jitter", 0)
        s2 = _mutation_seed(42, "cand_abc", "param_jitter", 0)
        self.assertEqual(s1, s2)

    def test_different_parent_different_seed(self):
        s1 = _mutation_seed(42, "cand_abc", "param_jitter", 0)
        s2 = _mutation_seed(42, "cand_xyz", "param_jitter", 0)
        self.assertNotEqual(s1, s2)

    def test_different_op_different_seed(self):
        s1 = _mutation_seed(42, "cand_abc", "param_jitter", 0)
        s2 = _mutation_seed(42, "cand_abc", "cost_adjust", 0)
        self.assertNotEqual(s1, s2)

    def test_different_index_different_seed(self):
        s1 = _mutation_seed(42, "cand_abc", "param_jitter", 0)
        s2 = _mutation_seed(42, "cand_abc", "param_jitter", 1)
        self.assertNotEqual(s1, s2)

    def test_different_global_seed_different_seed(self):
        s1 = _mutation_seed(42, "cand_abc", "param_jitter", 0)
        s2 = _mutation_seed(99, "cand_abc", "param_jitter", 0)
        self.assertNotEqual(s1, s2)


# =====================================================================
# TestParamJitter
# =====================================================================

class TestParamJitter(unittest.TestCase):
    def test_changes_one_param(self):
        import random
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        rng = random.Random(42)
        result = _op_param_jitter(parent, constraints, rng)
        self.assertIsNotNone(result)
        # Exactly one param should differ by 1
        old_params = parent["params"]
        new_params = result["params"]
        diffs = {k: abs(new_params[k] - old_params[k]) for k in old_params}
        changed = [k for k, d in diffs.items() if d > 0]
        self.assertEqual(len(changed), 1)
        self.assertEqual(diffs[changed[0]], 1)

    def test_stays_in_range(self):
        import random
        # atk at max (6), hp at min (1) — jitter should clamp
        parent = _make_vanilla_candidate(atk=6, hp=1, cost=3)
        constraints = _sample_constraints()
        for seed in range(50):
            rng = random.Random(seed)
            result = _op_param_jitter(parent, constraints, rng)
            if result is None:
                continue
            atk_lo, atk_hi = constraints["templates"]["Vanilla"]["params_ranges"]["atk"]
            hp_lo, hp_hi = constraints["templates"]["Vanilla"]["params_ranges"]["hp"]
            self.assertGreaterEqual(result["params"]["atk"], atk_lo)
            self.assertLessEqual(result["params"]["atk"], atk_hi)
            self.assertGreaterEqual(result["params"]["hp"], hp_lo)
            self.assertLessEqual(result["params"]["hp"], hp_hi)

    def test_cost_unchanged(self):
        import random
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        rng = random.Random(42)
        result = _op_param_jitter(parent, constraints, rng)
        self.assertEqual(result["cost"], parent["cost"])


# =====================================================================
# TestCostAdjust
# =====================================================================

class TestCostAdjust(unittest.TestCase):
    def test_cost_changes_by_one(self):
        import random
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        for seed in range(50):
            rng = random.Random(seed)
            result = _op_cost_adjust(parent, constraints, rng)
            if result is None:
                continue
            self.assertIn(result["cost"], [2, 4])
            return
        self.fail("No successful cost_adjust in 50 seeds")

    def test_cost_in_range(self):
        import random
        # Cost at min (1)
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=1)
        constraints = _sample_constraints()
        for seed in range(50):
            rng = random.Random(seed)
            result = _op_cost_adjust(parent, constraints, rng)
            if result is None:
                continue
            cost_lo, cost_hi = constraints["templates"]["Vanilla"]["cost_range"]
            self.assertGreaterEqual(result["cost"], cost_lo)
            self.assertLessEqual(result["cost"], cost_hi)

    def test_param_compensation(self):
        import random
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        for seed in range(100):
            rng = random.Random(seed)
            result = _op_cost_adjust(parent, constraints, rng)
            if result is None:
                continue
            # Params should differ from parent (compensation)
            if result["cost"] > parent["cost"]:
                # Cost up -> max param should increase (or stay if at max)
                max_key = max(parent["params"], key=lambda k: parent["params"][k])
                self.assertGreaterEqual(result["params"][max_key], parent["params"][max_key])
            return
        self.fail("No successful cost_adjust in 100 seeds")


# =====================================================================
# TestTemplateSwap
# =====================================================================

class TestTemplateSwap(unittest.TestCase):
    def test_swap_within_family(self):
        import random
        # DamagePlayer -> OnPlayDamagePlayer
        parent = _make_damage_candidate(amount=3, cost=2)
        constraints = _sample_constraints()
        rng = random.Random(42)
        result = _op_template_swap_within_family(parent, constraints, rng)
        self.assertIsNotNone(result)
        self.assertEqual(result["template"], "OnPlayDamagePlayer")

    def test_singleton_returns_none(self):
        import random
        # HealSelf has no family
        cid = _candidate_id("HealSelf", {"amount": 3}, 100)
        parent = {
            "id": cid, "template": "HealSelf", "cost": 2,
            "params": {"amount": 3}, "card_type": "spell",
        }
        constraints = _sample_constraints()
        rng = random.Random(42)
        result = _op_template_swap_within_family(parent, constraints, rng)
        self.assertIsNone(result)

    def test_draw_family_swap(self):
        import random
        # Draw -> OnPlayDraw
        parent = _make_draw_candidate(n=2, cost=3)
        constraints = _sample_constraints()
        rng = random.Random(42)
        result = _op_template_swap_within_family(parent, constraints, rng)
        self.assertIsNotNone(result)
        self.assertEqual(result["template"], "OnPlayDraw")
        # OnPlayDraw has atk, hp, n — n should be inherited, atk/hp should be midpoint
        self.assertEqual(result["params"]["n"], 2)
        self.assertIn("atk", result["params"])
        self.assertIn("hp", result["params"])

    def test_params_in_range(self):
        import random
        parent = _make_draw_candidate(n=2, cost=3)
        constraints = _sample_constraints()
        rng = random.Random(42)
        result = _op_template_swap_within_family(parent, constraints, rng)
        if result is None:
            return
        spec = constraints["templates"][result["template"]]
        for key, (lo, hi) in spec["params_ranges"].items():
            self.assertGreaterEqual(result["params"][key], lo)
            self.assertLessEqual(result["params"][key], hi)


# =====================================================================
# TestStatRedistribute
# =====================================================================

class TestStatRedistribute(unittest.TestCase):
    def test_vanilla_only(self):
        import random
        parent = _make_draw_candidate(n=2, cost=3)
        constraints = _sample_constraints()
        rng = random.Random(42)
        result = _op_stat_redistribute(parent, constraints, rng)
        self.assertIsNone(result)

    def test_total_preserved_or_close(self):
        import random
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        old_total = parent["params"]["atk"] + parent["params"]["hp"]
        for seed in range(50):
            rng = random.Random(seed)
            result = _op_stat_redistribute(parent, constraints, rng)
            if result is None:
                continue
            new_total = result["params"]["atk"] + result["params"]["hp"]
            # Total may not be perfectly preserved due to clamping, but should be close
            self.assertLessEqual(abs(new_total - old_total), 2)
            return
        self.fail("No successful stat_redistribute in 50 seeds")

    def test_stays_in_range(self):
        import random
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        for seed in range(50):
            rng = random.Random(seed)
            result = _op_stat_redistribute(parent, constraints, rng)
            if result is None:
                continue
            atk_lo, atk_hi = constraints["templates"]["Vanilla"]["params_ranges"]["atk"]
            hp_lo, hp_hi = constraints["templates"]["Vanilla"]["params_ranges"]["hp"]
            self.assertGreaterEqual(result["params"]["atk"], atk_lo)
            self.assertLessEqual(result["params"]["atk"], atk_hi)
            self.assertGreaterEqual(result["params"]["hp"], hp_lo)
            self.assertLessEqual(result["params"]["hp"], hp_hi)


# =====================================================================
# TestMutateCandidate
# =====================================================================

class TestMutateCandidate(unittest.TestCase):
    def test_returns_valid_candidate(self):
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        op_weights = {
            "param_jitter": 0.45, "cost_adjust": 0.25,
            "template_swap_within_family": 0.15, "stat_redistribute": 0.15,
        }
        result = mutate_candidate(parent, constraints, 42, 0, op_weights, [])
        self.assertIsNotNone(result)
        self.assertIn("id", result)
        self.assertIn("template", result)
        self.assertIn("params", result)
        self.assertIn("cost", result)
        self.assertIn("lineage", result)

    def test_lineage_correct(self):
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        op_weights = {"param_jitter": 1.0}
        result = mutate_candidate(parent, constraints, 42, 0, op_weights, [])
        self.assertIsNotNone(result)
        lineage = result["lineage"]
        self.assertEqual(lineage["origin"], "mutated")
        self.assertEqual(lineage["parent_id"], parent["id"])
        self.assertIsNotNone(lineage["mutation_op"])
        self.assertIsNotNone(lineage["mutation_params"])

    def test_respects_forbid(self):
        parent = _make_vanilla_candidate(atk=5, hp=5, cost=2)
        constraints = _sample_constraints()
        # This forbid rule would catch the parent-like cards
        forbid = [{"template": "Vanilla", "condition": "atk + hp >= cost * 3 + 2"}]
        op_weights = {"param_jitter": 1.0}
        # Most mutations of this parent would still be forbidden
        results = []
        for i in range(20):
            r = mutate_candidate(parent, constraints, 42, i, op_weights, forbid)
            if r is not None:
                # Verify the result doesn't violate forbid
                ns = dict(r["params"])
                ns["cost"] = r["cost"]
                self.assertFalse(
                    eval("atk + hp >= cost * 3 + 2", {"__builtins__": {}}, ns),
                    f"Mutant violates forbid: {r['params']}, cost={r['cost']}",
                )
                results.append(r)

    def test_constraints_respected(self):
        parent = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        op_weights = {
            "param_jitter": 0.45, "cost_adjust": 0.25,
            "template_swap_within_family": 0.15, "stat_redistribute": 0.15,
        }
        for i in range(20):
            result = mutate_candidate(parent, constraints, 42, i, op_weights, [])
            if result is None:
                continue
            spec = constraints["templates"].get(result["template"])
            if spec is None:
                continue
            cost_lo, cost_hi = spec["cost_range"]
            self.assertGreaterEqual(result["cost"], cost_lo)
            self.assertLessEqual(result["cost"], cost_hi)
            for key, (lo, hi) in spec.get("params_ranges", {}).items():
                self.assertGreaterEqual(result["params"][key], lo, f"{key} below min")
                self.assertLessEqual(result["params"][key], hi, f"{key} above max")


# =====================================================================
# TestGenerateMutations
# =====================================================================

class TestGenerateMutations(unittest.TestCase):
    def test_generates_mutations(self):
        parents = [
            _make_vanilla_candidate(atk=3, hp=4, cost=3),
            _make_draw_candidate(n=2, cost=3),
        ]
        constraints = _sample_constraints()
        config = _sample_config_with_mutations()
        mutated = generate_mutations(parents, constraints, config)
        self.assertGreater(len(mutated), 0)

    def test_per_base_limit(self):
        parents = [_make_vanilla_candidate(atk=3, hp=4, cost=3)]
        constraints = _sample_constraints()
        config = _sample_config_with_mutations()
        config["mutations"]["per_base"] = 2
        mutated = generate_mutations(parents, constraints, config)
        # At most per_base mutations per parent (some may fail -> None)
        self.assertLessEqual(len(mutated), 2)

    def test_all_have_lineage(self):
        parents = [
            _make_vanilla_candidate(atk=3, hp=4, cost=3),
            _make_damage_candidate(amount=3, cost=2),
        ]
        constraints = _sample_constraints()
        config = _sample_config_with_mutations()
        mutated = generate_mutations(parents, constraints, config)
        for m in mutated:
            self.assertIn("lineage", m)
            self.assertEqual(m["lineage"]["origin"], "mutated")
            self.assertIsNotNone(m["lineage"]["parent_id"])
            self.assertIsNotNone(m["lineage"]["mutation_op"])


# =====================================================================
# TestCardDistance
# =====================================================================

class TestCardDistance(unittest.TestCase):
    def test_identical_zero(self):
        a = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        constraints = _sample_constraints()
        self.assertAlmostEqual(card_distance(a, a, constraints), 0.0)

    def test_different_template_at_least_half(self):
        a = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        b = _make_draw_candidate(n=2, cost=3)
        constraints = _sample_constraints()
        d = card_distance(a, b, constraints)
        self.assertGreaterEqual(d, 0.5)

    def test_symmetric(self):
        a = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        b = _make_vanilla_candidate(atk=5, hp=2, cost=4)
        constraints = _sample_constraints()
        self.assertAlmostEqual(
            card_distance(a, b, constraints),
            card_distance(b, a, constraints),
        )

    def test_range_zero_to_one(self):
        a = _make_vanilla_candidate(atk=1, hp=1, cost=1)
        b = _make_draw_candidate(n=3, cost=5)
        constraints = _sample_constraints()
        d = card_distance(a, b, constraints)
        self.assertGreaterEqual(d, 0.0)
        self.assertLessEqual(d, 1.0)

    def test_cost_contributes(self):
        a = _make_vanilla_candidate(atk=3, hp=4, cost=1)
        b = _make_vanilla_candidate(atk=3, hp=4, cost=6)
        constraints = _sample_constraints()
        d = card_distance(a, b, constraints)
        self.assertGreater(d, 0.0)


# =====================================================================
# TestDiversityFilter
# =====================================================================

class TestDiversityFilter(unittest.TestCase):
    def test_removes_duplicates(self):
        a = _make_vanilla_candidate(atk=3, hp=4, cost=3)
        b = _make_vanilla_candidate(atk=3, hp=4, cost=3)  # identical
        constraints = _sample_constraints()
        config = {"diversity": {"min_distance": 0.0, "max_per_template": 100}}
        result = dedupe_and_filter_diversity([a, b], constraints, config)
        self.assertEqual(len(result), 1)

    def test_higher_min_distance_fewer_candidates(self):
        candidates = [
            _make_vanilla_candidate(atk=i, hp=4, cost=3) for i in range(1, 7)
        ]
        constraints = _sample_constraints()
        config_low = {"diversity": {"min_distance": 0.01, "max_per_template": 100}}
        config_high = {"diversity": {"min_distance": 0.3, "max_per_template": 100}}
        low_result = dedupe_and_filter_diversity(candidates, constraints, config_low)
        high_result = dedupe_and_filter_diversity(candidates, constraints, config_high)
        self.assertGreaterEqual(len(low_result), len(high_result))

    def test_max_per_template(self):
        candidates = [
            _make_vanilla_candidate(atk=i, hp=j, cost=3)
            for i in range(1, 6) for j in range(1, 6)
        ]
        constraints = _sample_constraints()
        config = {"diversity": {"min_distance": 0.0, "max_per_template": 3}}
        result = dedupe_and_filter_diversity(candidates, constraints, config)
        template_counts = {}
        for c in result:
            t = c["template"]
            template_counts[t] = template_counts.get(t, 0) + 1
        for t, count in template_counts.items():
            self.assertLessEqual(count, 3, f"Template {t} has {count} candidates")

    def test_deterministic(self):
        candidates = [
            _make_vanilla_candidate(atk=i, hp=4, cost=3) for i in range(1, 6)
        ]
        constraints = _sample_constraints()
        config = {"diversity": {"min_distance": 0.1, "max_per_template": 10}}
        r1 = dedupe_and_filter_diversity(candidates, constraints, config)
        r2 = dedupe_and_filter_diversity(candidates, constraints, config)
        self.assertEqual([c["id"] for c in r1], [c["id"] for c in r2])


# =====================================================================
# TestLineage
# =====================================================================

class TestLineage(unittest.TestCase):
    def test_base_lineage(self):
        patterns = _sample_patterns()
        constraints = _sample_constraints()
        config = _sample_config_with_mutations()
        candidates = generate_candidates(patterns, constraints, config)
        for c in candidates:
            self.assertIn("lineage", c)
            self.assertEqual(c["lineage"]["origin"], "base")
            self.assertIsNone(c["lineage"]["parent_id"])
            self.assertIsNone(c["lineage"]["mutation_op"])
            self.assertIsNone(c["lineage"]["mutation_params"])

    def test_mutated_lineage(self):
        parents = [_make_vanilla_candidate(atk=3, hp=4, cost=3)]
        constraints = _sample_constraints()
        config = _sample_config_with_mutations()
        mutated = generate_mutations(parents, constraints, config)
        for m in mutated:
            lineage = m["lineage"]
            self.assertEqual(lineage["origin"], "mutated")
            self.assertEqual(lineage["parent_id"], parents[0]["id"])
            self.assertIn(lineage["mutation_op"], [
                "param_jitter", "cost_adjust",
                "template_swap_within_family", "stat_redistribute",
            ])
            self.assertIsNotNone(lineage["mutation_params"])


# =====================================================================
# TestDeterminism
# =====================================================================

class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_mutations(self):
        parents = [
            _make_vanilla_candidate(atk=3, hp=4, cost=3),
            _make_draw_candidate(n=2, cost=3),
        ]
        constraints = _sample_constraints()
        config = _sample_config_with_mutations()

        m1 = generate_mutations(parents, constraints, config)
        m2 = generate_mutations(parents, constraints, config)

        self.assertEqual(len(m1), len(m2))
        for a, b in zip(m1, m2):
            self.assertEqual(a["id"], b["id"])
            self.assertEqual(a["template"], b["template"])
            self.assertEqual(a["params"], b["params"])
            self.assertEqual(a["cost"], b["cost"])

    def test_different_seed_different_mutations(self):
        parents = [_make_vanilla_candidate(atk=3, hp=4, cost=3)]
        constraints = _sample_constraints()
        config1 = _sample_config_with_mutations()
        config1["seed"] = 42
        config2 = _sample_config_with_mutations()
        config2["seed"] = 99

        m1 = generate_mutations(parents, constraints, config1)
        m2 = generate_mutations(parents, constraints, config2)

        # At least some should differ
        if m1 and m2:
            ids1 = {m["id"] for m in m1}
            ids2 = {m["id"] for m in m2}
            self.assertNotEqual(ids1, ids2)


# =====================================================================
# TestRegressionMutOff
# =====================================================================

class TestRegressionMutOff(unittest.TestCase):
    def test_mutations_off_produces_base_only(self):
        """With mutations disabled, run_cardgen should produce only base candidates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patterns = {"meta": {"version": "0.4"}, "patterns": _sample_patterns()}
            pat_path = os.path.join(tmpdir, "patterns.json")
            with open(pat_path, "w") as f:
                json.dump(patterns, f)

            constraints = _sample_constraints()
            con_path = os.path.join(tmpdir, "constraints.json")
            with open(con_path, "w") as f:
                json.dump(constraints, f)

            config = _sample_config_with_mutations()
            config["mutations"]["enabled"] = False
            config["top_patterns_per_type"] = {"counter": 1, "sequence": 1, "cooccurrence": 0}
            config["candidates_per_pattern"] = 1
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w") as f:
                json.dump(config, f)

            out_dir = os.path.join(tmpdir, "output")
            target_paths = [
                os.path.join(DATA_DIR, "decks", "aggro_rush.json"),
                os.path.join(DATA_DIR, "decks", "control_mage.json"),
                os.path.join(DATA_DIR, "decks", "midrange.json"),
            ]

            result = run_cardgen(
                patterns_path=pat_path,
                pool_path=CARDS_JSON,
                target_paths=target_paths,
                constraints_path=con_path,
                config_path=cfg_path,
                output_dir=out_dir,
            )

            self.assertEqual(result["total_mutated"], 0)
            self.assertEqual(result["total_candidates"], result["total_base"])

            # All candidates should have base lineage
            with open(os.path.join(out_dir, "card_candidates.json")) as f:
                candidates = json.load(f)
            for c in candidates:
                self.assertEqual(c["lineage"]["origin"], "base")

    def test_mutations_off_via_override(self):
        """CLI --mutations off should override config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patterns = {"meta": {"version": "0.4"}, "patterns": _sample_patterns()}
            pat_path = os.path.join(tmpdir, "patterns.json")
            with open(pat_path, "w") as f:
                json.dump(patterns, f)

            constraints = _sample_constraints()
            con_path = os.path.join(tmpdir, "constraints.json")
            with open(con_path, "w") as f:
                json.dump(constraints, f)

            config = _sample_config_with_mutations()
            # Config says enabled=True, but override says off
            config["mutations"]["enabled"] = True
            config["top_patterns_per_type"] = {"counter": 1, "sequence": 0, "cooccurrence": 0}
            config["candidates_per_pattern"] = 1
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w") as f:
                json.dump(config, f)

            out_dir = os.path.join(tmpdir, "output")
            target_paths = [
                os.path.join(DATA_DIR, "decks", "aggro_rush.json"),
                os.path.join(DATA_DIR, "decks", "control_mage.json"),
            ]

            result = run_cardgen(
                patterns_path=pat_path,
                pool_path=CARDS_JSON,
                target_paths=target_paths,
                constraints_path=con_path,
                config_path=cfg_path,
                output_dir=out_dir,
                mutations_override="off",
            )

            self.assertEqual(result["total_mutated"], 0)


# =====================================================================
# TestEndToEndSmoke
# =====================================================================

class TestEndToEndSmoke(unittest.TestCase):
    def test_v06_pipeline_completes(self):
        """Full v0.6 pipeline with mutations and diversity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patterns = {"meta": {"version": "0.4"}, "patterns": _sample_patterns()}
            pat_path = os.path.join(tmpdir, "patterns.json")
            with open(pat_path, "w") as f:
                json.dump(patterns, f)

            constraints = _sample_constraints()
            con_path = os.path.join(tmpdir, "constraints.json")
            with open(con_path, "w") as f:
                json.dump(constraints, f)

            config = _sample_config_with_mutations()
            config["top_patterns_per_type"] = {"counter": 2, "sequence": 1, "cooccurrence": 1}
            config["candidates_per_pattern"] = 2
            # Lower min_distance to keep more mutated candidates through filter
            config["diversity"]["min_distance"] = 0.05
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w") as f:
                json.dump(config, f)

            out_dir = os.path.join(tmpdir, "output")
            target_paths = [
                os.path.join(DATA_DIR, "decks", "aggro_rush.json"),
                os.path.join(DATA_DIR, "decks", "control_mage.json"),
                os.path.join(DATA_DIR, "decks", "midrange.json"),
            ]

            result = run_cardgen(
                patterns_path=pat_path,
                pool_path=CARDS_JSON,
                target_paths=target_paths,
                constraints_path=con_path,
                config_path=cfg_path,
                output_dir=out_dir,
            )

            # Check outputs exist
            self.assertTrue(os.path.exists(os.path.join(out_dir, "card_candidates.json")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "adoption_report.json")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "selected_cards.json")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "run_meta.json")))

            # Check counts
            self.assertGreater(result["total_candidates"], 0)
            self.assertGreater(result["total_base"], 0)
            self.assertGreater(result["total_mutated"], 0)
            self.assertGreater(result["total_after_diversity"], 0)

            # run_meta has new fields
            with open(os.path.join(out_dir, "run_meta.json")) as f:
                meta = json.load(f)
            self.assertIn("total_base", meta)
            self.assertIn("total_mutated", meta)
            self.assertIn("total_after_diversity", meta)

            # Candidates include both base and mutated
            with open(os.path.join(out_dir, "card_candidates.json")) as f:
                candidates = json.load(f)
            origins = {c["lineage"]["origin"] for c in candidates}
            self.assertIn("base", origins)
            self.assertIn("mutated", origins)


# =====================================================================
# Template family tests
# =====================================================================

class TestTemplateFamilies(unittest.TestCase):
    def test_family_of_draw(self):
        self.assertEqual(_family_of("Draw"), "draw")
        self.assertEqual(_family_of("OnPlayDraw"), "draw")

    def test_family_of_damage(self):
        self.assertEqual(_family_of("DamagePlayer"), "damage")
        self.assertEqual(_family_of("OnPlayDamagePlayer"), "damage")

    def test_family_of_singleton(self):
        self.assertIsNone(_family_of("Vanilla"))
        self.assertIsNone(_family_of("HealSelf"))
        self.assertIsNone(_family_of("RemoveUnit"))

    def test_swap_targets(self):
        self.assertEqual(_swap_targets("Draw"), ["OnPlayDraw"])
        self.assertEqual(_swap_targets("OnPlayDraw"), ["Draw"])
        self.assertEqual(_swap_targets("DamagePlayer"), ["OnPlayDamagePlayer"])
        self.assertEqual(_swap_targets("Vanilla"), [])


if __name__ == "__main__":
    unittest.main()
