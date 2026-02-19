"""Tests for v0.5: Card generation — constrained search + adoption test."""

import json
import os
import tempfile
import unittest

from card_battle.cardgen import (
    _candidate_id,
    _check_forbid,
    adoption_test_one,
    build_deck_variants,
    check_acceptance,
    generate_candidates,
    run_cardgen,
)
from card_battle.loader import load_cards, load_deck
from card_battle.models import Card, DeckDef, DeckEntry
from card_battle.mutation import deck_to_counts

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")
CONSTRAINTS_JSON = os.path.join(
    os.path.dirname(__file__), "..", "configs", "constraints_v0_5.json",
)
GENERATE_JSON = os.path.join(
    os.path.dirname(__file__), "..", "configs", "generate_v0_5.json",
)


def _sample_patterns() -> list[dict]:
    """Create a minimal set of patterns for testing."""
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


def _sample_constraints() -> dict:
    return {
        "templates": {
            "HealSelf": {
                "card_type": "spell",
                "cost_range": [1, 3],
                "tags": ["heal"],
                "params_ranges": {"amount": [2, 5]},
            },
            "RemoveUnit": {
                "card_type": "spell",
                "cost_range": [2, 4],
                "tags": ["removal"],
                "params_ranges": {"max_hp": [1, 3]},
            },
            "Vanilla": {
                "card_type": "unit",
                "cost_range": [1, 4],
                "tags": ["creature"],
                "params_ranges": {"atk": [1, 4], "hp": [1, 5]},
            },
        },
        "global": {
            "max_new_cards": 20,
            "forbid": [],
        },
    }


def _sample_config() -> dict:
    return {
        "seed": 42,
        "top_patterns_per_type": {"counter": 2, "sequence": 1, "cooccurrence": 1},
        "candidates_per_pattern": 2,
        "mode_weights": {"suppress": 0.7, "support": 0.3},
        "suppress_templates": ["HealSelf", "RemoveUnit", "Vanilla"],
        "support_templates": ["Vanilla"],
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


class TestCandidateId(unittest.TestCase):
    def test_deterministic(self):
        id1 = _candidate_id("Vanilla", {"atk": 2, "hp": 3}, 42)
        id2 = _candidate_id("Vanilla", {"atk": 2, "hp": 3}, 42)
        self.assertEqual(id1, id2)

    def test_different_params_differ(self):
        id1 = _candidate_id("Vanilla", {"atk": 2, "hp": 3}, 42)
        id2 = _candidate_id("Vanilla", {"atk": 3, "hp": 3}, 42)
        self.assertNotEqual(id1, id2)

    def test_starts_with_cand(self):
        cid = _candidate_id("Vanilla", {"atk": 2, "hp": 3}, 42)
        self.assertTrue(cid.startswith("cand_"))


class TestCheckForbid(unittest.TestCase):
    def test_no_rules(self):
        self.assertFalse(_check_forbid("Vanilla", 2, {"atk": 3, "hp": 3}, []))

    def test_matching_rule(self):
        rules = [
            {"template": "RemoveUnit", "condition": "max_hp >= 4 and cost <= 2"},
        ]
        self.assertTrue(_check_forbid("RemoveUnit", 2, {"max_hp": 5}, rules))

    def test_non_matching_rule(self):
        rules = [
            {"template": "RemoveUnit", "condition": "max_hp >= 4 and cost <= 2"},
        ]
        self.assertFalse(_check_forbid("RemoveUnit", 3, {"max_hp": 5}, rules))

    def test_different_template_ignored(self):
        rules = [
            {"template": "RemoveUnit", "condition": "max_hp >= 4 and cost <= 2"},
        ]
        self.assertFalse(_check_forbid("Vanilla", 1, {"atk": 5, "hp": 5}, rules))


class TestGenerateCandidates(unittest.TestCase):
    def test_generates_some(self):
        patterns = _sample_patterns()
        constraints = _sample_constraints()
        config = _sample_config()
        candidates = generate_candidates(patterns, constraints, config)
        self.assertGreater(len(candidates), 0)

    def test_deterministic(self):
        patterns = _sample_patterns()
        constraints = _sample_constraints()
        config = _sample_config()
        c1 = generate_candidates(patterns, constraints, config)
        c2 = generate_candidates(patterns, constraints, config)
        self.assertEqual(c1, c2)

    def test_respects_max_cards(self):
        patterns = _sample_patterns() * 10  # Many patterns
        constraints = _sample_constraints()
        config = _sample_config()
        config["candidates_per_pattern"] = 5
        constraints["global"]["max_new_cards"] = 5
        candidates = generate_candidates(patterns, constraints, config)
        self.assertLessEqual(len(candidates), 5)

    def test_has_required_fields(self):
        patterns = _sample_patterns()
        constraints = _sample_constraints()
        config = _sample_config()
        candidates = generate_candidates(patterns, constraints, config)
        for c in candidates:
            self.assertIn("id", c)
            self.assertIn("name", c)
            self.assertIn("cost", c)
            self.assertIn("card_type", c)
            self.assertIn("template", c)
            self.assertIn("params", c)
            self.assertIn("intent", c)
            self.assertIn("gen_reason", c)

    def test_no_duplicates(self):
        patterns = _sample_patterns()
        constraints = _sample_constraints()
        config = _sample_config()
        candidates = generate_candidates(patterns, constraints, config)
        keys = set()
        for c in candidates:
            key = json.dumps(
                {"template": c["template"], "params": c["params"], "cost": c["cost"]},
                sort_keys=True,
            )
            self.assertNotIn(key, keys, f"Duplicate candidate: {key}")
            keys.add(key)


class TestBuildDeckVariants(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.deck = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db,
        )
        # Add a test candidate card
        self.cand_card = Card(
            id="test_cand", name="Test Cand", cost=2, card_type="spell",
            tags=("removal",), template="RemoveUnit", params={"max_hp": 3},
        )
        self.card_db["test_cand"] = self.cand_card

    def test_returns_variants(self):
        variants = build_deck_variants(self.deck, "test_cand", self.card_db, 3)
        self.assertGreater(len(variants), 0)

    def test_deck_constraint_30_cards(self):
        variants = build_deck_variants(self.deck, "test_cand", self.card_db, 3)
        for v in variants:
            total = sum(e.count for e in v.entries)
            self.assertEqual(total, 30, f"Deck {v.deck_id} has {total} cards")

    def test_deck_constraint_max_copies(self):
        variants = build_deck_variants(self.deck, "test_cand", self.card_db, 3)
        for v in variants:
            for e in v.entries:
                self.assertLessEqual(e.count, 3, f"Card {e.card_id} has {e.count} copies")
                self.assertGreaterEqual(e.count, 1)

    def test_candidate_present_in_variants(self):
        variants = build_deck_variants(self.deck, "test_cand", self.card_db, 3)
        for v in variants:
            counts = deck_to_counts(v)
            self.assertIn("test_cand", counts)

    def test_unknown_candidate_returns_empty(self):
        variants = build_deck_variants(self.deck, "nonexistent", self.card_db, 3)
        self.assertEqual(variants, [])


class TestAdoptionTestOne(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.targets = [
            load_deck(os.path.join(DATA_DIR, "decks", f), self.card_db)
            for f in ["aggro_rush.json", "control_mage.json", "midrange.json"]
        ]

    def test_smoke_completes(self):
        """Single candidate adoption test completes without crash."""
        candidate = {
            "id": "test_heal_01",
            "name": "Test Heal",
            "cost": 2,
            "card_type": "spell",
            "template": "HealSelf",
            "params": {"amount": 4},
            "tags": ["heal"],
            "intent": {"mode": "suppress", "target_pattern_ids": [], "target_deck_ids": []},
            "gen_reason": {"source_patterns": [], "heuristic": "test"},
        }
        config = _sample_config()
        report = adoption_test_one(candidate, self.targets, self.card_db, config, 42)

        self.assertIn("before", report)
        self.assertIn("after", report)
        self.assertIn("delta", report)
        self.assertIn("overall_win_rate_delta", report["delta"])
        self.assertIsInstance(report["delta"]["overall_win_rate_delta"], float)

    def test_deterministic(self):
        """Same candidate + seed → same report."""
        candidate = {
            "id": "test_remove_01",
            "name": "Test Remove",
            "cost": 3,
            "card_type": "spell",
            "template": "RemoveUnit",
            "params": {"max_hp": 3},
            "tags": ["removal"],
            "intent": {"mode": "suppress", "target_pattern_ids": [], "target_deck_ids": []},
            "gen_reason": {"source_patterns": [], "heuristic": "test"},
        }
        config = _sample_config()
        r1 = adoption_test_one(candidate, self.targets, self.card_db, config, 42)
        r2 = adoption_test_one(candidate, self.targets, self.card_db, config, 42)
        self.assertEqual(
            r1["delta"]["overall_win_rate_delta"],
            r2["delta"]["overall_win_rate_delta"],
        )


class TestCheckAcceptance(unittest.TestCase):
    def test_accepted(self):
        report = {
            "before": {"telemetry_aggregate": {"avg_total_turns": 15}},
            "after": {"win_rates_by_target": {"a": 0.6, "b": 0.7}},
            "delta": {
                "overall_win_rate_delta": 0.05,
                "telemetry_delta": {"avg_total_turns": 1.0},
            },
        }
        config = {"adoption": {"acceptance": {
            "min_overall_delta": 0.02, "max_win_rate": 0.95,
            "max_turns_delta_pct": 0.20,
        }}}
        self.assertTrue(check_acceptance(report, config))

    def test_rejected_low_delta(self):
        report = {
            "before": {"telemetry_aggregate": {}},
            "after": {"win_rates_by_target": {"a": 0.5}},
            "delta": {
                "overall_win_rate_delta": 0.01,
                "telemetry_delta": {},
            },
        }
        config = {"adoption": {"acceptance": {"min_overall_delta": 0.02}}}
        self.assertFalse(check_acceptance(report, config))

    def test_rejected_extreme_wr(self):
        report = {
            "before": {"telemetry_aggregate": {}},
            "after": {"win_rates_by_target": {"a": 0.98}},
            "delta": {
                "overall_win_rate_delta": 0.10,
                "telemetry_delta": {},
            },
        }
        config = {"adoption": {"acceptance": {
            "min_overall_delta": 0.02, "max_win_rate": 0.95,
        }}}
        self.assertFalse(check_acceptance(report, config))


class TestEndToEndSmoke(unittest.TestCase):
    """Integration: generate candidates → adoption test → output files."""

    def test_pipeline_completes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal patterns.json
            patterns = {
                "meta": {"version": "0.4"},
                "patterns": _sample_patterns(),
            }
            pat_path = os.path.join(tmpdir, "patterns.json")
            with open(pat_path, "w") as f:
                json.dump(patterns, f)

            constraints = _sample_constraints()
            con_path = os.path.join(tmpdir, "constraints.json")
            with open(con_path, "w") as f:
                json.dump(constraints, f)

            config = _sample_config()
            # Reduce candidates for speed
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

            # Check output files exist
            self.assertTrue(os.path.exists(os.path.join(out_dir, "card_candidates.json")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "adoption_report.json")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "selected_cards.json")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "run_meta.json")))

            self.assertGreater(result["total_candidates"], 0)

    def test_pipeline_deterministic(self):
        """Same inputs → same card_candidates.json."""
        results = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmpdir:
                patterns = {
                    "meta": {"version": "0.4"},
                    "patterns": _sample_patterns(),
                }
                pat_path = os.path.join(tmpdir, "patterns.json")
                with open(pat_path, "w") as f:
                    json.dump(patterns, f)

                constraints = _sample_constraints()
                con_path = os.path.join(tmpdir, "constraints.json")
                with open(con_path, "w") as f:
                    json.dump(constraints, f)

                config = _sample_config()
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

                run_cardgen(
                    patterns_path=pat_path,
                    pool_path=CARDS_JSON,
                    target_paths=target_paths,
                    constraints_path=con_path,
                    config_path=cfg_path,
                    output_dir=out_dir,
                )

                with open(os.path.join(out_dir, "card_candidates.json")) as f:
                    results.append(json.load(f))

        self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
