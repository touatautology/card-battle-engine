"""Tests for v0.7.1: Cycle runner."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from card_battle.cycle import _capture_replays, _derive_cycle_seed, _pool_hash, run_cycle

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "..", "configs")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")
TARGET_PATHS = [
    os.path.join(DATA_DIR, "decks", "aggro_rush.json"),
    os.path.join(DATA_DIR, "decks", "control_mage.json"),
    os.path.join(DATA_DIR, "decks", "midrange.json"),
]


def _make_cycle_config(tmpdir: str, cycles: int = 1, seed: int = 42,
                        replay_enabled: bool = False) -> str:
    """Write a small cycle config for testing (fast evolve settings)."""
    # Small evolve config: 2 generations, 6 population, 1 match
    evolve_cfg = {
        "global_seed": seed,
        "generations": 2,
        "population_size": 6,
        "matches_per_eval": 1,
        "elite_pool_size": 3,
        "elitism": 2,
        "tournament_k": 3,
        "mutation_weights": {"swap_one": 0.5, "swap_n": 0.3, "tweak_counts": 0.2},
        "swap_n_range": [2, 4],
        "cards_path": CARDS_JSON,
        "seed_decks": TARGET_PATHS,
        "initial_population": "seed_decks",
        "output_dir": os.path.join(tmpdir, "evolve_unused"),
        "baseline_decks": TARGET_PATHS,
        "log_every_n": 1,
        "top_n_summary": 3,
        "telemetry": {"enabled": True, "save_match_summaries": True},
        "metrics": {"top_n_decks": 3},
        "evaluation": {},
    }
    evolve_path = os.path.join(tmpdir, "evolve_test.json")
    with open(evolve_path, "w") as f:
        json.dump(evolve_cfg, f)

    cycle_cfg = {
        "version": "0.6.1-test",
        "cycles": cycles,
        "seed": seed,
        "paths": {
            "pool": CARDS_JSON,
            "targets": TARGET_PATHS,
            "evolve_config": evolve_path,
            "patterns_config": os.path.join(CONFIGS_DIR, "patterns_v0_4.json"),
            "cardgen_config": os.path.join(CONFIGS_DIR, "generate_v0_6.json"),
            "constraints": os.path.join(CONFIGS_DIR, "constraints_v0_6.json"),
            "promotion_config": os.path.join(CONFIGS_DIR, "promotion_v0_5_1.json"),
        },
        "replay": {
            "enabled": replay_enabled,
            "top_k_matchups": 2,
        },
    }
    config_path = os.path.join(tmpdir, "cycle_test.json")
    with open(config_path, "w") as f:
        json.dump(cycle_cfg, f)
    return config_path


class TestSeedDerivation(unittest.TestCase):
    """Deterministic seed derivation from global_seed + cycle_index."""

    def test_same_input_same_seed(self):
        a = _derive_cycle_seed(42, 0)
        b = _derive_cycle_seed(42, 0)
        self.assertEqual(a, b)

    def test_different_index_different_seed(self):
        a = _derive_cycle_seed(42, 0)
        b = _derive_cycle_seed(42, 1)
        self.assertNotEqual(a, b)

    def test_different_global_different_seed(self):
        a = _derive_cycle_seed(42, 0)
        b = _derive_cycle_seed(99, 0)
        self.assertNotEqual(a, b)

    def test_returns_int(self):
        result = _derive_cycle_seed(42, 5)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)


class TestPoolHash(unittest.TestCase):
    """Pool file hashing."""

    def test_same_file_same_hash(self):
        path = Path(CARDS_JSON)
        a = _pool_hash(path)
        b = _pool_hash(path)
        self.assertEqual(a, b)

    def test_hex_64_chars(self):
        path = Path(CARDS_JSON)
        h = _pool_hash(path)
        self.assertEqual(len(h), 64)
        # All hex chars
        int(h, 16)

    def test_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"id": "a"}], f)
            p1 = Path(f.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"id": "b"}], f)
            p2 = Path(f.name)
        try:
            self.assertNotEqual(_pool_hash(p1), _pool_hash(p2))
        finally:
            p1.unlink()
            p2.unlink()


class TestCycleSmoke(unittest.TestCase):
    """Smoke test: 1 cycle completes and produces expected artifacts."""

    def test_single_cycle_completes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _make_cycle_config(tmpdir, cycles=1, seed=42)
            output_dir = os.path.join(tmpdir, "out")

            result = run_cycle(config_path=config_path, output_dir=output_dir)

            # Basic structure
            self.assertEqual(result["total_cycles"], 1)
            self.assertIn("gates_passed", result)
            self.assertIn("gates_failed", result)
            self.assertEqual(result["gates_passed"] + result["gates_failed"], 1)
            self.assertIn("elapsed_seconds", result)
            self.assertIn("final_pool_hash", result)
            self.assertEqual(len(result["cycles"]), 1)

            # Artifact directories
            out = Path(output_dir)
            self.assertTrue((out / "cycle_summary.json").exists())
            self.assertTrue((out / "run_meta.json").exists())
            self.assertTrue((out / "pools" / "pool_000.json").exists())
            self.assertTrue((out / "pools" / "pool_001.json").exists())
            self.assertTrue((out / "cycles" / "cycle_000").is_dir())

            # Evolve artifacts
            cycle_dir = out / "cycles" / "cycle_000"
            self.assertTrue((cycle_dir / "evolve").is_dir())

            # Patterns artifact
            self.assertTrue((cycle_dir / "patterns.json").exists())

            # Cardgen dir
            self.assertTrue((cycle_dir / "cardgen").is_dir())


class TestCycleDeterminism(unittest.TestCase):
    """Same seed → identical cycle_summary (except elapsed_seconds)."""

    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _make_cycle_config(tmpdir, cycles=1, seed=123)

            out1 = os.path.join(tmpdir, "run1")
            out2 = os.path.join(tmpdir, "run2")

            r1 = run_cycle(config_path=config_path, output_dir=out1)
            r2 = run_cycle(config_path=config_path, output_dir=out2)

            # Compare key fields (exclude timing)
            self.assertEqual(r1["total_cycles"], r2["total_cycles"])
            self.assertEqual(r1["gates_passed"], r2["gates_passed"])
            self.assertEqual(r1["gates_failed"], r2["gates_failed"])
            self.assertEqual(r1["total_cards_added"], r2["total_cards_added"])
            self.assertEqual(r1["final_pool_hash"], r2["final_pool_hash"])

            # Per-cycle results
            for c1, c2 in zip(r1["cycles"], r2["cycles"]):
                self.assertEqual(c1["cycle_seed"], c2["cycle_seed"])
                self.assertEqual(c1["gate_passed"], c2["gate_passed"])
                self.assertEqual(c1["cards_added"], c2["cards_added"])
                self.assertEqual(c1["patterns_count"], c2["patterns_count"])


class TestCycleGateFail(unittest.TestCase):
    """When gate fails, pool remains unchanged (hash matches)."""

    def test_pool_unchanged_on_gate_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _make_cycle_config(tmpdir, cycles=1, seed=42)
            output_dir = os.path.join(tmpdir, "out")

            result = run_cycle(config_path=config_path, output_dir=output_dir)

            pools_dir = Path(output_dir) / "pools"
            pool_000 = pools_dir / "pool_000.json"
            pool_001 = pools_dir / "pool_001.json"

            # If gate failed, pool_000 and pool_001 must have same hash
            if not result["cycles"][0]["gate_passed"]:
                self.assertEqual(_pool_hash(pool_000), _pool_hash(pool_001))


class TestCycleOverrides(unittest.TestCase):
    """CLI overrides are respected."""

    def test_cycles_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Config says 3 cycles, but we override to 1
            config_path = _make_cycle_config(tmpdir, cycles=3, seed=42)
            output_dir = os.path.join(tmpdir, "out")

            result = run_cycle(
                config_path=config_path,
                output_dir=output_dir,
                cycles_override=1,
            )
            self.assertEqual(result["total_cycles"], 1)
            self.assertEqual(len(result["cycles"]), 1)

    def test_seed_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _make_cycle_config(tmpdir, cycles=1, seed=42)
            output_dir = os.path.join(tmpdir, "out")

            result = run_cycle(
                config_path=config_path,
                output_dir=output_dir,
                seed_override=999,
            )
            # Cycle seed should be derived from 999, not 42
            expected_seed = _derive_cycle_seed(999, 0)
            self.assertEqual(result["cycles"][0]["cycle_seed"], expected_seed)


class TestCaptureReplays(unittest.TestCase):
    """Test that _capture_replays produces cross-matchup (not mirror) replays."""

    def _setup_replay_dir(self, tmpdir: str, delta: dict) -> tuple[Path, list[str]]:
        """Create a minimal cycle dir with a promotion_report containing the given delta."""
        cycle_dir = Path(tmpdir) / "cycle_000"
        promo_dir = cycle_dir / "promote"
        promo_dir.mkdir(parents=True)
        promo_report = {
            "before": {"fixed": {
                "win_rates_by_target": {k: 0.5 for k in delta},
                "overall_win_rate": 0.5,
                "telemetry_aggregate": {},
            }},
            "after": {"fixed": {
                "win_rates_by_target": {k: 0.5 + v for k, v in delta.items()},
                "overall_win_rate": 0.5,
                "telemetry_aggregate": {},
            }, "adapted": {
                "win_rates_by_target": {k: 0.5 + v for k, v in delta.items()},
                "overall_win_rate": 0.5,
                "telemetry_aggregate": {},
            }},
            "delta": {"fixed": delta, "adapted": delta},
            "gate": {"passed": True, "checks": {}, "reason": "ok"},
        }
        with open(promo_dir / "promotion_report.json", "w") as f:
            json.dump(promo_report, f)
        return cycle_dir, TARGET_PATHS

    def test_replays_are_cross_matchups(self):
        """With multiple targets, replays should not be mirror matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            delta = {
                "aggro_rush": 0.05,
                "control_mage": -0.03,
                "midrange": 0.01,
            }
            cycle_dir, target_paths = self._setup_replay_dir(tmpdir, delta)
            replay_config = {"top_k_matchups": 3}

            paths = _capture_replays(
                cycle_dir, Path(CARDS_JSON), target_paths,
                cycle_seed=42, replay_config=replay_config,
            )
            self.assertGreater(len(paths), 0)

            # Read each replay and check deck_ids are different
            for rp in paths:
                with open(rp, encoding="utf-8") as f:
                    for line in f:
                        ev = json.loads(line)
                        if ev.get("type") == "meta":
                            deck_ids = ev.get("deck_ids", [])
                            if len(deck_ids) == 2:
                                # With 3 targets, at least some should be cross
                                # (all are cross with circular pairing)
                                self.assertNotEqual(
                                    deck_ids[0], deck_ids[1],
                                    f"Mirror match found: {deck_ids}",
                                )
                            break

    def test_replay_seed_determinism(self):
        """Same cycle_seed should produce identical replays."""
        with tempfile.TemporaryDirectory() as tmpdir:
            delta = {"aggro_rush": 0.05, "control_mage": -0.03}

            # Run 1
            cycle_dir1, target_paths = self._setup_replay_dir(
                os.path.join(tmpdir, "r1"), delta,
            )
            paths1 = _capture_replays(
                cycle_dir1, Path(CARDS_JSON), target_paths,
                cycle_seed=42, replay_config={"top_k_matchups": 2},
            )

            # Run 2
            cycle_dir2, _ = self._setup_replay_dir(
                os.path.join(tmpdir, "r2"), delta,
            )
            paths2 = _capture_replays(
                cycle_dir2, Path(CARDS_JSON), target_paths,
                cycle_seed=42, replay_config={"top_k_matchups": 2},
            )

            self.assertEqual(len(paths1), len(paths2))
            for p1, p2 in zip(paths1, paths2):
                with open(p1) as f1, open(p2) as f2:
                    self.assertEqual(f1.read(), f2.read())


if __name__ == "__main__":
    unittest.main()
