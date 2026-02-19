"""Tests for v0.3: Evolution runner integration tests."""

import json
import os
import tempfile
import unittest

from card_battle.evolve import EvolutionConfig, EvolutionRunner

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")
CONFIG_JSON = os.path.join(os.path.dirname(__file__), "..", "configs", "evolve_v0_3.json")


def _small_config(output_dir: str, **overrides) -> EvolutionConfig:
    """Create a small config for fast testing."""
    defaults = dict(
        global_seed=42,
        generations=2,
        population_size=6,
        matches_per_eval=1,
        elite_pool_size=3,
        elitism=2,
        tournament_k=3,
        mutation_weights={"swap_one": 0.5, "swap_n": 0.3, "tweak_counts": 0.2},
        swap_n_range=(2, 3),
        cards_path=CARDS_JSON,
        seed_decks=[
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"),
            os.path.join(DATA_DIR, "decks", "control_mage.json"),
            os.path.join(DATA_DIR, "decks", "midrange.json"),
        ],
        initial_population="seed_decks",
        output_dir=output_dir,
        baseline_decks=[],
        log_every_n=1,
        top_n_summary=3,
    )
    defaults.update(overrides)
    return EvolutionConfig(**defaults)


class TestEvolutionSmoke(unittest.TestCase):
    def test_two_generations(self):
        """Run 2 generations with small population, no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _small_config(tmpdir)
            runner = EvolutionRunner(config)
            runner.run()

            # Check artifacts exist
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "config_used.json")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "best_decks.json")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "gen_000", "population.json")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "gen_000", "summary.json")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "gen_001", "population.json")))

            # best_decks.json should have 2 entries (one per generation)
            with open(os.path.join(tmpdir, "best_decks.json")) as f:
                best = json.load(f)
            self.assertEqual(len(best), 2)

    def test_random_init(self):
        """Run with random initial population."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _small_config(
                tmpdir,
                initial_population="random",
                seed_decks=[],
            )
            runner = EvolutionRunner(config)
            runner.run()

            self.assertTrue(os.path.exists(os.path.join(tmpdir, "best_decks.json")))


class TestEvolutionDeterminism(unittest.TestCase):
    def test_same_config_same_result(self):
        """Two runs with identical config produce identical best_decks.json."""
        results = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmpdir:
                config = _small_config(tmpdir)
                runner = EvolutionRunner(config)
                runner.run()

                with open(os.path.join(tmpdir, "best_decks.json")) as f:
                    results.append(json.load(f))

        self.assertEqual(results[0], results[1])


class TestEvolutionConfig(unittest.TestCase):
    def test_from_json(self):
        """Load config from the actual config file."""
        config = EvolutionConfig.from_json(CONFIG_JSON)
        self.assertEqual(config.generations, 20)
        self.assertEqual(config.population_size, 30)
        self.assertEqual(config.global_seed, 42)

    def test_from_json_with_overrides(self):
        config = EvolutionConfig.from_json(
            CONFIG_JSON, generations=5, global_seed=99)
        self.assertEqual(config.generations, 5)
        self.assertEqual(config.global_seed, 99)


class TestEvolutionArtifacts(unittest.TestCase):
    def test_population_json_structure(self):
        """Verify population.json has expected fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _small_config(tmpdir)
            runner = EvolutionRunner(config)
            runner.run()

            with open(os.path.join(tmpdir, "gen_000", "population.json")) as f:
                pop = json.load(f)

            self.assertEqual(len(pop), config.population_size)
            for entry in pop:
                self.assertIn("deck_id", entry)
                self.assertIn("fitness", entry)
                self.assertIn("entries", entry)
                self.assertGreaterEqual(entry["fitness"], 0.0)
                self.assertLessEqual(entry["fitness"], 1.0)

    def test_summary_json_structure(self):
        """Verify summary.json has expected fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _small_config(tmpdir)
            runner = EvolutionRunner(config)
            runner.run()

            with open(os.path.join(tmpdir, "gen_000", "summary.json")) as f:
                summary = json.load(f)

            self.assertIn("generation", summary)
            self.assertIn("stats", summary)
            self.assertIn("top_decks", summary)
            self.assertIn("mean", summary["stats"])
            self.assertIn("max", summary["stats"])
            self.assertLessEqual(len(summary["top_decks"]), config.top_n_summary)


if __name__ == "__main__":
    unittest.main()
