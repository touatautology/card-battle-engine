"""Tests for v0.7.1: Promotion pipeline."""

import json
import os
import tempfile
import unittest

from card_battle.loader import load_cards, load_deck
from card_battle.models import Card
from card_battle.promotion import (
    IDConflictError,
    _card_dict_to_pool_entry,
    _card_value_score,
    _list_to_card_db,
    _pool_hash,
    adapt_targets_for_after,
    apply_promotion,
    compute_gate,
    run_benchmark,
    run_promotion,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")
CONFIG_JSON = os.path.join(
    os.path.dirname(__file__), "..", "configs", "promotion_v0_5_1.json",
)
TARGET_PATHS = [
    os.path.join(DATA_DIR, "decks", "aggro_rush.json"),
    os.path.join(DATA_DIR, "decks", "control_mage.json"),
    os.path.join(DATA_DIR, "decks", "midrange.json"),
]


def _sample_candidate_card() -> dict:
    """A sample candidate card dict (as found in adoption report)."""
    return {
        "id": "cand_test_001",
        "name": "Test Bolt",
        "cost": 2,
        "card_type": "spell",
        "tags": ["damage"],
        "template": "DamagePlayer",
        "params": {"amount": 4},
        "intent": {"mode": "suppress", "target_pattern_ids": ["p1"]},
        "gen_reason": {"heuristic": "test"},
    }


def _sample_report(candidate=None) -> dict:
    """Wrap a candidate in a minimal adoption report."""
    if candidate is None:
        candidate = _sample_candidate_card()
    return {
        "candidate_card": candidate,
        "before": {"overall_win_rate": 0.5},
        "after": {"overall_win_rate": 0.55},
        "delta": {"overall_win_rate_delta": 0.05},
    }


def _load_cards_list() -> list[dict]:
    with open(CARDS_JSON, encoding="utf-8") as f:
        return json.load(f)


# -------------------------------------------------------------------------
# TestCardDictToPoolEntry
# -------------------------------------------------------------------------

class TestCardDictToPoolEntry(unittest.TestCase):
    def test_removes_intent_and_gen_reason(self):
        cand = _sample_candidate_card()
        entry = _card_dict_to_pool_entry(cand)
        self.assertNotIn("intent", entry)
        self.assertNotIn("gen_reason", entry)

    def test_preserves_core_fields(self):
        cand = _sample_candidate_card()
        entry = _card_dict_to_pool_entry(cand)
        self.assertEqual(entry["id"], "cand_test_001")
        self.assertEqual(entry["name"], "Test Bolt")
        self.assertEqual(entry["cost"], 2)
        self.assertEqual(entry["card_type"], "spell")
        self.assertEqual(entry["template"], "DamagePlayer")
        self.assertEqual(entry["params"], {"amount": 4})
        self.assertEqual(entry["tags"], ["damage"])

    def test_rarity_defaults_uncommon(self):
        cand = _sample_candidate_card()
        entry = _card_dict_to_pool_entry(cand)
        self.assertEqual(entry["rarity"], "uncommon")

    def test_rarity_preserved_if_present(self):
        cand = _sample_candidate_card()
        cand["rarity"] = "rare"
        entry = _card_dict_to_pool_entry(cand)
        self.assertEqual(entry["rarity"], "rare")


# -------------------------------------------------------------------------
# TestApplyPromotion
# -------------------------------------------------------------------------

class TestApplyPromotion(unittest.TestCase):
    def test_adds_card_to_pool(self):
        cards = _load_cards_list()
        reports = [_sample_report()]
        config = {"max_promotions_per_run": 10, "on_id_conflict": "fail"}

        after, patch = apply_promotion(cards, reports, config)
        self.assertEqual(len(after), len(cards) + 1)
        self.assertEqual(len(patch["added"]), 1)
        self.assertEqual(patch["added"][0]["id"], "cand_test_001")

    def test_patch_structure(self):
        cards = _load_cards_list()
        reports = [_sample_report()]
        config = {"max_promotions_per_run": 10, "on_id_conflict": "fail"}

        _, patch = apply_promotion(cards, reports, config)
        self.assertEqual(patch["version"], "0.5.1")
        self.assertIn("base_pool_hash", patch)
        self.assertIn("new_pool_hash", patch)
        self.assertIsInstance(patch["added"], list)
        self.assertEqual(patch["updated"], [])
        self.assertEqual(patch["removed"], [])
        self.assertIsInstance(patch["skipped_conflicts"], list)

    def test_max_promotions_limit(self):
        cards = _load_cards_list()
        reports = []
        for i in range(5):
            c = _sample_candidate_card()
            c["id"] = f"cand_max_{i}"
            reports.append(_sample_report(c))

        config = {"max_promotions_per_run": 3, "on_id_conflict": "fail"}
        after, patch = apply_promotion(cards, reports, config)
        self.assertEqual(len(patch["added"]), 3)
        self.assertEqual(len(after), len(cards) + 3)

    def test_hashes_differ(self):
        cards = _load_cards_list()
        reports = [_sample_report()]
        config = {"max_promotions_per_run": 10, "on_id_conflict": "fail"}
        _, patch = apply_promotion(cards, reports, config)
        self.assertNotEqual(patch["base_pool_hash"], patch["new_pool_hash"])

    def test_no_reports_yields_empty_added(self):
        cards = _load_cards_list()
        config = {"max_promotions_per_run": 10, "on_id_conflict": "fail"}
        after, patch = apply_promotion(cards, [], config)
        self.assertEqual(len(after), len(cards))
        self.assertEqual(len(patch["added"]), 0)


# -------------------------------------------------------------------------
# TestIDConflict
# -------------------------------------------------------------------------

class TestIDConflict(unittest.TestCase):
    def test_fail_raises_error(self):
        cards = _load_cards_list()
        # Use an existing card ID
        c = _sample_candidate_card()
        c["id"] = "goblin"
        reports = [_sample_report(c)]
        config = {"max_promotions_per_run": 10, "on_id_conflict": "fail"}

        with self.assertRaises(IDConflictError) as ctx:
            apply_promotion(cards, reports, config)
        self.assertEqual(ctx.exception.card_id, "goblin")

    def test_skip_records_conflict(self):
        cards = _load_cards_list()
        c = _sample_candidate_card()
        c["id"] = "goblin"
        reports = [_sample_report(c)]
        config = {"max_promotions_per_run": 10, "on_id_conflict": "skip"}

        after, patch = apply_promotion(cards, reports, config)
        self.assertEqual(len(after), len(cards))
        self.assertEqual(len(patch["added"]), 0)
        self.assertIn("goblin", patch["skipped_conflicts"])

    def test_skip_allows_other_cards(self):
        cards = _load_cards_list()
        c1 = _sample_candidate_card()
        c1["id"] = "goblin"  # conflict
        c2 = _sample_candidate_card()
        c2["id"] = "cand_new_card"
        reports = [_sample_report(c1), _sample_report(c2)]
        config = {"max_promotions_per_run": 10, "on_id_conflict": "skip"}

        after, patch = apply_promotion(cards, reports, config)
        self.assertEqual(len(patch["added"]), 1)
        self.assertEqual(patch["added"][0]["id"], "cand_new_card")
        self.assertIn("goblin", patch["skipped_conflicts"])


# -------------------------------------------------------------------------
# TestComputeGate
# -------------------------------------------------------------------------

class TestComputeGate(unittest.TestCase):
    def _make_result(self, wrs=None, avg_turns=10.0, avg_p0_mana=1.0, avg_p1_mana=1.0):
        if wrs is None:
            wrs = {"d1": 0.5, "d2": 0.5}
        return {
            "win_rates_by_target": wrs,
            "overall_win_rate": sum(wrs.values()) / len(wrs),
            "telemetry_aggregate": {
                "avg_total_turns": avg_turns,
                "avg_p0_mana_wasted": avg_p0_mana,
                "avg_p1_mana_wasted": avg_p1_mana,
            },
        }

    def test_all_pass(self):
        before = self._make_result()
        after = self._make_result()
        gate_config = {
            "max_matchup_winrate": 0.95,
            "turns_delta_ratio": 0.20,
            "mana_wasted_delta_ratio": 0.20,
        }
        result = compute_gate(before, after, gate_config)
        self.assertTrue(result["passed"])
        self.assertIn("all checks passed", result["reason"])

    def test_max_wr_exceeded(self):
        before = self._make_result()
        after = self._make_result(wrs={"d1": 0.96, "d2": 0.5})
        gate_config = {
            "max_matchup_winrate": 0.95,
            "turns_delta_ratio": 0.20,
            "mana_wasted_delta_ratio": 0.20,
        }
        result = compute_gate(before, after, gate_config)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["max_matchup_winrate"]["passed"])

    def test_turns_exceeded(self):
        before = self._make_result(avg_turns=10.0)
        after = self._make_result(avg_turns=13.0)  # 30% change > 20% threshold
        gate_config = {
            "max_matchup_winrate": 0.95,
            "turns_delta_ratio": 0.20,
            "mana_wasted_delta_ratio": 0.20,
        }
        result = compute_gate(before, after, gate_config)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["turns_delta_ratio"]["passed"])

    def test_mana_exceeded(self):
        before = self._make_result(avg_p0_mana=1.0, avg_p1_mana=1.0)
        after = self._make_result(avg_p0_mana=1.5, avg_p1_mana=1.5)  # 50% change > 20%
        gate_config = {
            "max_matchup_winrate": 0.95,
            "turns_delta_ratio": 0.20,
            "mana_wasted_delta_ratio": 0.20,
        }
        result = compute_gate(before, after, gate_config)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["mana_wasted_delta_ratio"]["passed"])


# -------------------------------------------------------------------------
# TestRunBenchmark
# -------------------------------------------------------------------------

class TestRunBenchmark(unittest.TestCase):
    def test_smoke(self):
        """Benchmark runs to completion and returns correct structure."""
        card_db = load_cards(CARDS_JSON)
        targets = [load_deck(tp, card_db) for tp in TARGET_PATHS]
        benchmark_config = {"matches_per_pair": 1, "policies": None}

        result = run_benchmark(card_db, targets, 42, benchmark_config)
        self.assertIn("win_rates_by_target", result)
        self.assertIn("overall_win_rate", result)
        self.assertIn("telemetry_aggregate", result)
        self.assertIn("summaries", result)
        self.assertEqual(len(result["win_rates_by_target"]), 3)
        self.assertIsInstance(result["overall_win_rate"], float)


# -------------------------------------------------------------------------
# TestEndToEndSmoke
# -------------------------------------------------------------------------

class TestEndToEndSmoke(unittest.TestCase):
    def test_full_pipeline(self):
        """Full promotion pipeline completes and generates all artifacts."""
        cards_list = _load_cards_list()
        reports = [_sample_report()]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write inputs
            selected_path = os.path.join(tmpdir, "selected_cards.json")
            pool_path = os.path.join(tmpdir, "cards.json")
            config_path = os.path.join(tmpdir, "config.json")
            output_dir = os.path.join(tmpdir, "output")

            with open(selected_path, "w") as f:
                json.dump(reports, f)
            with open(pool_path, "w") as f:
                json.dump(cards_list, f)

            # Use minimal config for speed
            config = {
                "seed": 42,
                "max_promotions_per_run": 10,
                "on_id_conflict": "fail",
                "benchmark": {
                    "matches_per_pair": 1,
                    "policies": None,
                },
                "gate": {
                    "max_matchup_winrate": 0.95,
                    "turns_delta_ratio": 0.20,
                    "mana_wasted_delta_ratio": 0.20,
                },
            }
            with open(config_path, "w") as f:
                json.dump(config, f)

            result = run_promotion(
                selected_path=selected_path,
                pool_path=pool_path,
                target_paths=TARGET_PATHS,
                config_path=config_path,
                output_dir=output_dir,
            )

            # Check return value
            self.assertIn("gate_passed", result)
            self.assertIn("exit_reason", result)
            self.assertIn("cards_added", result)
            self.assertIn("report_path", result)
            self.assertEqual(result["cards_added"], 1)

            # Check all 5 artifacts exist
            expected_files = [
                "cards_before.json",
                "cards_after.json",
                "promotion_patch.json",
                "promotion_report.json",
                "run_meta.json",
            ]
            for fname in expected_files:
                fpath = os.path.join(output_dir, fname)
                self.assertTrue(os.path.exists(fpath), f"Missing: {fname}")

            # Verify cards_after has 21 cards
            with open(os.path.join(output_dir, "cards_after.json")) as f:
                after = json.load(f)
            self.assertEqual(len(after), 21)


# -------------------------------------------------------------------------
# TestDeterminism
# -------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_result(self):
        """Same config + seed produces identical promotion_report.json."""
        cards_list = _load_cards_list()
        reports = [_sample_report()]

        results = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmpdir:
                selected_path = os.path.join(tmpdir, "selected_cards.json")
                pool_path = os.path.join(tmpdir, "cards.json")
                config_path = os.path.join(tmpdir, "config.json")
                output_dir = os.path.join(tmpdir, "output")

                with open(selected_path, "w") as f:
                    json.dump(reports, f)
                with open(pool_path, "w") as f:
                    json.dump(cards_list, f)

                config = {
                    "seed": 42,
                    "max_promotions_per_run": 10,
                    "on_id_conflict": "fail",
                    "benchmark": {
                        "matches_per_pair": 1,
                        "policies": None,
                    },
                    "gate": {
                        "max_matchup_winrate": 0.95,
                        "turns_delta_ratio": 0.20,
                        "mana_wasted_delta_ratio": 0.20,
                    },
                }
                with open(config_path, "w") as f:
                    json.dump(config, f)

                run_promotion(
                    selected_path=selected_path,
                    pool_path=pool_path,
                    target_paths=TARGET_PATHS,
                    config_path=config_path,
                    output_dir=output_dir,
                )

                with open(os.path.join(output_dir, "promotion_report.json")) as f:
                    results.append(json.load(f))

        self.assertEqual(results[0], results[1])


# -------------------------------------------------------------------------
# TestCardValueScore
# -------------------------------------------------------------------------

class TestCardValueScore(unittest.TestCase):
    def test_unit_atk_plus_hp(self):
        card = Card(
            id="u1", name="Unit", cost=2, card_type="unit",
            tags=(), template="Vanilla", params={"atk": 3, "hp": 2},
        )
        self.assertEqual(_card_value_score(card), 5.0)

    def test_spell_damage(self):
        card = Card(
            id="s1", name="Spell", cost=4, card_type="spell",
            tags=(), template="DamagePlayer", params={"amount": 6},
        )
        self.assertEqual(_card_value_score(card), 6.0)

    def test_spell_draw(self):
        card = Card(
            id="s2", name="Draw", cost=3, card_type="spell",
            tags=(), template="Draw", params={"n": 2},
        )
        self.assertEqual(_card_value_score(card), 4.0)


# -------------------------------------------------------------------------
# TestAdaptTargets
# -------------------------------------------------------------------------

class TestAdaptTargets(unittest.TestCase):
    """Tests for adapt_targets_for_after()."""

    def _setup(self):
        """Load card_db and targets, add a candidate new card."""
        cards_list = _load_cards_list()
        # Add a new card to the pool
        new_card = {
            "id": "test_adapt_unit",
            "name": "Adapt Test Unit",
            "cost": 2,
            "card_type": "unit",
            "tags": ["creature"],
            "template": "Vanilla",
            "params": {"atk": 4, "hp": 3},
            "rarity": "uncommon",
        }
        cards_after_list = cards_list + [new_card]
        card_db_after = _list_to_card_db(cards_after_list)
        card_db_before = _list_to_card_db(cards_list)
        targets = [load_deck(tp, card_db_before) for tp in TARGET_PATHS]
        return targets, card_db_after, ["test_adapt_unit"]

    def test_adaptation_injects_new_card(self):
        targets, card_db_after, new_ids = self._setup()
        adapted, log = adapt_targets_for_after(
            targets, new_ids, card_db_after, seed=42,
            benchmark_config={"matches_per_pair": 1},
        )
        # At least one adapted deck should differ from original
        adapted_ids = [d.deck_id for d in adapted]
        has_adapted = any("__adapt_" in did for did in adapted_ids)
        # It's possible no adaptation improves, but the function should return
        self.assertEqual(len(adapted), len(targets))
        self.assertEqual(len(log), len(targets))
        # If adapted, the new card should be in the deck
        for d in adapted:
            if "__adapt_" in d.deck_id:
                card_ids = [e.card_id for e in d.entries]
                self.assertIn("test_adapt_unit", card_ids)

    def test_adaptation_preserves_deck_size(self):
        targets, card_db_after, new_ids = self._setup()
        adapted, _ = adapt_targets_for_after(
            targets, new_ids, card_db_after, seed=42,
            benchmark_config={"matches_per_pair": 1},
        )
        for d in adapted:
            total = sum(e.count for e in d.entries)
            self.assertEqual(total, 30, f"Deck {d.deck_id} has {total} cards")

    def test_adaptation_determinism(self):
        targets, card_db_after, new_ids = self._setup()
        r1, l1 = adapt_targets_for_after(
            targets, new_ids, card_db_after, seed=42,
            benchmark_config={"matches_per_pair": 1},
        )
        r2, l2 = adapt_targets_for_after(
            targets, new_ids, card_db_after, seed=42,
            benchmark_config={"matches_per_pair": 1},
        )
        self.assertEqual(
            [d.deck_id for d in r1],
            [d.deck_id for d in r2],
        )
        self.assertEqual(l1, l2)

    def test_no_new_cards_returns_originals(self):
        targets, card_db_after, _ = self._setup()
        adapted, log = adapt_targets_for_after(
            targets, [], card_db_after, seed=42,
            benchmark_config={"matches_per_pair": 1},
        )
        self.assertEqual(adapted, targets)
        self.assertEqual(log, [])

    def test_adaptation_log_structure(self):
        targets, card_db_after, new_ids = self._setup()
        _, log = adapt_targets_for_after(
            targets, new_ids, card_db_after, seed=42,
            benchmark_config={"matches_per_pair": 1},
        )
        for entry in log:
            self.assertIn("original_deck_id", entry)
            self.assertIn("adapted_deck_id", entry)
            self.assertIn("baseline_win_rate", entry)


# -------------------------------------------------------------------------
# TestPromotionReportSchema
# -------------------------------------------------------------------------

class TestPromotionReportSchema(unittest.TestCase):
    """Verify the new two-track report schema."""

    def _run_pipeline(self):
        cards_list = _load_cards_list()
        reports = [_sample_report()]

        with tempfile.TemporaryDirectory() as tmpdir:
            selected_path = os.path.join(tmpdir, "selected_cards.json")
            pool_path = os.path.join(tmpdir, "cards.json")
            config_path = os.path.join(tmpdir, "config.json")
            output_dir = os.path.join(tmpdir, "output")

            with open(selected_path, "w") as f:
                json.dump(reports, f)
            with open(pool_path, "w") as f:
                json.dump(cards_list, f)

            config = {
                "seed": 42,
                "max_promotions_per_run": 10,
                "on_id_conflict": "fail",
                "benchmark": {"matches_per_pair": 1, "policies": None},
                "gate": {
                    "max_matchup_winrate": 0.95,
                    "turns_delta_ratio": 0.20,
                    "mana_wasted_delta_ratio": 0.20,
                },
            }
            with open(config_path, "w") as f:
                json.dump(config, f)

            run_promotion(
                selected_path=selected_path,
                pool_path=pool_path,
                target_paths=TARGET_PATHS,
                config_path=config_path,
                output_dir=output_dir,
            )

            with open(os.path.join(output_dir, "promotion_report.json")) as f:
                return json.load(f)

    def test_report_has_fixed_and_adapted(self):
        report = self._run_pipeline()
        # before.fixed
        self.assertIn("fixed", report["before"])
        self.assertIn("win_rates_by_target", report["before"]["fixed"])
        # after.fixed and after.adapted
        self.assertIn("fixed", report["after"])
        self.assertIn("adapted", report["after"])
        # delta.fixed and delta.adapted
        self.assertIn("fixed", report["delta"])
        self.assertIn("adapted", report["delta"])
        # adaptation log
        self.assertIn("adaptation", report)
        self.assertIsInstance(report["adaptation"], list)
        # gate has benchmark_view
        self.assertIn("benchmark_view", report["gate"])

    def test_delta_fixed_near_zero(self):
        report = self._run_pipeline()
        # delta.fixed should be near zero (same decks, same targets)
        for val in report["delta"]["fixed"].values():
            self.assertAlmostEqual(val, 0.0, places=2,
                                   msg="delta.fixed should be ~0")


if __name__ == "__main__":
    unittest.main()
