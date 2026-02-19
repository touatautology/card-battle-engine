"""Tests for v0.4: Tactical pattern extraction."""

import json
import os
import tempfile
import unittest
import warnings

from card_battle.patterns import (
    _pattern_id,
    extract_all_patterns,
    extract_cooccurrence,
    extract_counters,
    extract_sequences,
    load_match_summaries,
    write_patterns,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")
CONFIG_JSON = os.path.join(os.path.dirname(__file__), "..", "configs", "evolve_v0_3.json")
PATTERNS_CONFIG = os.path.join(
    os.path.dirname(__file__), "..", "configs", "patterns_v0_4.json",
)


def _make_deck(deck_id: str, card_ids: list[str], fitness: float = 0.5) -> dict:
    """Create a minimal deck dict for testing."""
    return {
        "deck_id": deck_id,
        "fitness": fitness,
        "entries": [{"card_id": c, "count": 2} for c in card_ids],
    }


def _make_summary(
    deck_id: str = "d1",
    opponent_id: str = "d2",
    winner: str = "player_0_win",
    swapped: bool = False,
    match_id: str = "m_1_0",
    total_turns: int = 10,
    turn_trace: list | None = None,
    **extra: object,
) -> dict:
    """Create a minimal match summary for testing."""
    s: dict = {
        "deck_id": deck_id,
        "opponent_id": opponent_id,
        "winner": winner,
        "swapped": swapped,
        "match_id": match_id,
        "total_turns": total_turns,
        "deck_id_p0": deck_id if not swapped else opponent_id,
        "deck_id_p1": opponent_id if not swapped else deck_id,
    }
    if turn_trace is not None:
        s["turn_trace"] = turn_trace
    s.update(extra)
    return s


class TestPatternId(unittest.TestCase):
    def test_deterministic(self):
        id1 = _pattern_id("cooccurrence", {"cards": ["a", "b"]})
        id2 = _pattern_id("cooccurrence", {"cards": ["a", "b"]})
        self.assertEqual(id1, id2)

    def test_different_definitions_differ(self):
        id1 = _pattern_id("cooccurrence", {"cards": ["a", "b"]})
        id2 = _pattern_id("cooccurrence", {"cards": ["a", "c"]})
        self.assertNotEqual(id1, id2)

    def test_different_types_differ(self):
        id1 = _pattern_id("cooccurrence", {"cards": ["a", "b"]})
        id2 = _pattern_id("sequence", {"cards": ["a", "b"]})
        self.assertNotEqual(id1, id2)


class TestLoadMatchSummaries(unittest.TestCase):
    def test_round_trip_jsonl(self):
        records = [
            {"match_id": "m1", "winner": "player_0_win"},
            {"match_id": "m2", "winner": "player_1_win"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False,
        ) as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
            path = f.name
        try:
            loaded = list(load_match_summaries(path))
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["match_id"], "m1")
            self.assertEqual(loaded[1]["match_id"], "m2")
        finally:
            os.unlink(path)


class TestWritePatterns(unittest.TestCase):
    def test_output_structure(self):
        patterns = [
            {
                "pattern_id": "abc",
                "type": "cooccurrence",
                "scope": "deck",
                "definition": {"cards": ["a", "b"]},
                "stats": {"support": 5, "win_rate": 0.7, "lift": 1.2, "avg_turns": 0.0},
                "examples": {"match_ids": []},
            },
        ]
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False,
        ) as f:
            path = f.name
        try:
            write_patterns(patterns, path, {"version": "0.4"})
            with open(path) as f:
                data = json.load(f)
            self.assertIn("meta", data)
            self.assertIn("patterns", data)
            self.assertEqual(data["meta"]["version"], "0.4")
            self.assertEqual(len(data["patterns"]), 1)
        finally:
            os.unlink(path)

    def test_sorted_by_lift_desc(self):
        p1 = {
            "pattern_id": "aaa",
            "type": "cooccurrence",
            "scope": "deck",
            "definition": {"cards": ["a"]},
            "stats": {"support": 5, "win_rate": 0.5, "lift": 1.0, "avg_turns": 0.0},
            "examples": {"match_ids": []},
        }
        p2 = {
            "pattern_id": "bbb",
            "type": "cooccurrence",
            "scope": "deck",
            "definition": {"cards": ["b"]},
            "stats": {"support": 3, "win_rate": 0.8, "lift": 2.0, "avg_turns": 0.0},
            "examples": {"match_ids": []},
        }
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            write_patterns([p1, p2], path, {"version": "0.4"})
            with open(path) as f:
                data = json.load(f)
            # p2 (lift=2.0) should come first
            self.assertEqual(data["patterns"][0]["pattern_id"], "bbb")
            self.assertEqual(data["patterns"][1]["pattern_id"], "aaa")
        finally:
            os.unlink(path)


class TestExtractCooccurrence(unittest.TestCase):
    def test_basic_extraction(self):
        decks = [
            _make_deck("d1", ["goblin", "soldier", "bolt"], 0.8),
            _make_deck("d2", ["goblin", "soldier", "heal"], 0.7),
            _make_deck("d3", ["goblin", "soldier", "fireball"], 0.9),
            _make_deck("d4", ["knight", "ogre", "heal"], 0.4),
        ]
        config = {"min_support": 3, "max_itemset_size": 2}
        patterns = extract_cooccurrence(decks, config)
        self.assertGreater(len(patterns), 0)
        # goblin+soldier should appear with support=3
        gs_patterns = [
            p for p in patterns
            if set(p["definition"]["cards"]) == {"goblin", "soldier"}
        ]
        self.assertEqual(len(gs_patterns), 1)
        self.assertEqual(gs_patterns[0]["stats"]["support"], 3)

    def test_min_support_filters(self):
        decks = [
            _make_deck("d1", ["goblin", "soldier", "bolt"], 0.8),
            _make_deck("d2", ["goblin", "soldier", "heal"], 0.7),
        ]
        config = {"min_support": 3, "max_itemset_size": 2}
        patterns = extract_cooccurrence(decks, config)
        self.assertEqual(len(patterns), 0)

    def test_raising_support_reduces_patterns(self):
        decks = [
            _make_deck(f"d{i}", ["goblin", "soldier", "bolt"], 0.8)
            for i in range(5)
        ]
        low = extract_cooccurrence(decks, {"min_support": 2, "max_itemset_size": 3})
        high = extract_cooccurrence(decks, {"min_support": 6, "max_itemset_size": 3})
        self.assertGreater(len(low), len(high))

    def test_empty_decks(self):
        patterns = extract_cooccurrence([], {"min_support": 1, "max_itemset_size": 2})
        self.assertEqual(patterns, [])


class TestExtractSequences(unittest.TestCase):
    def test_basic_extraction(self):
        trace = [
            {"turn": 1, "player": 0, "played": ["goblin"], "atk": 0, "blk": 0},
            {"turn": 2, "player": 0, "played": ["soldier"], "atk": 1, "blk": 0},
        ]
        summaries = [
            _make_summary(
                deck_id=f"d{i}", match_id=f"m_{i}_0",
                winner="player_0_win", turn_trace=trace,
            )
            for i in range(10)
        ]
        config = {"sequence": {"turns": 3, "min_support": 5}}
        patterns = extract_sequences(summaries, config)
        self.assertGreater(len(patterns), 0)
        self.assertEqual(patterns[0]["type"], "sequence")

    def test_no_turn_trace_warns(self):
        summaries = [_make_summary(deck_id="d1")]
        config = {"sequence": {"turns": 3, "min_support": 1}}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            patterns = extract_sequences(summaries, config)
            self.assertEqual(len(patterns), 0)
            self.assertEqual(len(w), 1)
            self.assertIn("turn_trace", str(w[0].message))

    def test_min_support_filters(self):
        trace = [
            {"turn": 1, "player": 0, "played": ["goblin"], "atk": 0, "blk": 0},
        ]
        summaries = [
            _make_summary(
                deck_id="d1", match_id="m_1_0",
                winner="player_0_win", turn_trace=trace,
            ),
        ]
        config = {"sequence": {"turns": 3, "min_support": 5}}
        patterns = extract_sequences(summaries, config)
        self.assertEqual(len(patterns), 0)


class TestExtractCounters(unittest.TestCase):
    def test_basic_extraction(self):
        decks = [
            _make_deck("d1", ["goblin", "bolt", "soldier"], 0.8),
            _make_deck("d2", ["goblin", "bolt", "knight"], 0.7),
            _make_deck("d3", ["goblin", "bolt", "heal"], 0.9),
            _make_deck("d4", ["knight", "ogre", "heal"], 0.4),
        ]
        # d1, d2, d3 all beat target "control_mage"
        summaries = [
            _make_summary(
                deck_id="d1", opponent_id="control_mage",
                match_id="m_1_0", winner="player_0_win",
            ),
            _make_summary(
                deck_id="d2", opponent_id="control_mage",
                match_id="m_2_0", winner="player_0_win",
            ),
            _make_summary(
                deck_id="d3", opponent_id="control_mage",
                match_id="m_3_0", winner="player_0_win",
            ),
            _make_summary(
                deck_id="d4", opponent_id="control_mage",
                match_id="m_4_0", winner="player_1_win",
            ),
        ]
        config = {
            "min_support": 3,
            "counter": {
                "targets": ["control_mage"],
                "min_lift": 1.0,
            },
        }
        patterns = extract_counters(summaries, decks, config)
        self.assertGreater(len(patterns), 0)
        for p in patterns:
            self.assertEqual(p["type"], "counter")
            self.assertEqual(p["definition"]["target_deck_id"], "control_mage")

    def test_no_targets_empty(self):
        config = {"min_support": 1, "counter": {"targets": [], "min_lift": 1.0}}
        patterns = extract_counters([], [], config)
        self.assertEqual(patterns, [])


class TestDeterminism(unittest.TestCase):
    """Same input + same config → same patterns.json (exact match)."""

    def test_same_input_same_output(self):
        decks = [
            _make_deck(f"d{i}", ["goblin", "soldier", "bolt"], 0.8)
            for i in range(5)
        ]
        trace = [
            {"turn": 1, "player": 0, "played": ["goblin"], "atk": 0, "blk": 0},
        ]
        summaries = [
            _make_summary(
                deck_id=f"d{i}", opponent_id="control_mage",
                match_id=f"m_{i}_0", winner="player_0_win",
                turn_trace=trace,
            )
            for i in range(5)
        ]
        config = {
            "min_support": 2,
            "max_itemset_size": 2,
            "sequence": {"turns": 3, "min_support": 2},
            "counter": {"targets": ["control_mage"], "min_lift": 1.0},
            "top_n_decks": 10,
        }

        results = []
        for _ in range(2):
            all_patterns = []
            all_patterns.extend(extract_cooccurrence(decks, config, summaries))
            all_patterns.extend(extract_sequences(summaries, config))
            all_patterns.extend(extract_counters(summaries, decks, config))

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                path = f.name
            try:
                write_patterns(all_patterns, path, {"version": "0.4"})
                with open(path) as f:
                    results.append(json.load(f))
            finally:
                os.unlink(path)

        self.assertEqual(results[0], results[1])


class TestEndToEndPipeline(unittest.TestCase):
    """Integration test: evolve → patterns extraction."""

    def test_evolve_then_patterns(self):
        from card_battle.evolve import EvolutionConfig, EvolutionRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            # Run a small evolution with summaries + turn_trace
            config = EvolutionConfig(
                global_seed=42,
                generations=3,
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
                output_dir=tmpdir,
                log_every_n=1,
                top_n_summary=3,
                telemetry={
                    "enabled": True,
                    "save_match_summaries": True,
                    "save_turn_trace": True,
                },
            )
            runner = EvolutionRunner(config)
            runner.run()

            # Verify JSONL files were created
            jsonl_files = list(
                p for p in os.listdir(tmpdir)
                if p.endswith("_summaries.jsonl")
            )
            self.assertGreater(len(jsonl_files), 0)

            # Run pattern extraction
            pat_config = {
                "min_support": 2,
                "max_itemset_size": 3,
                "sequence": {"turns": 3, "min_support": 2},
                "counter": {
                    "targets": ["aggro_rush", "control_mage", "midrange"],
                    "min_lift": 1.0,
                },
                "top_n_decks": 5,
            }
            output_path = os.path.join(tmpdir, "patterns.json")
            patterns = extract_all_patterns(
                tmpdir, pat_config, output_path=output_path,
            )

            # Verify output
            self.assertTrue(os.path.exists(output_path))
            with open(output_path) as f:
                data = json.load(f)
            self.assertIn("meta", data)
            self.assertIn("patterns", data)
            self.assertEqual(data["meta"]["version"], "0.4")

            # Should have some patterns
            types = {p["type"] for p in patterns}
            # At minimum, cooccurrence should be present
            self.assertIn("cooccurrence", types)

    def test_evolve_then_patterns_deterministic(self):
        """Same evolve → same patterns output."""
        from card_battle.evolve import EvolutionConfig, EvolutionRunner

        results = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmpdir:
                config = EvolutionConfig(
                    global_seed=42,
                    generations=2,
                    population_size=6,
                    matches_per_eval=1,
                    elite_pool_size=3,
                    elitism=2,
                    tournament_k=3,
                    cards_path=CARDS_JSON,
                    seed_decks=[
                        os.path.join(DATA_DIR, "decks", "aggro_rush.json"),
                        os.path.join(DATA_DIR, "decks", "control_mage.json"),
                        os.path.join(DATA_DIR, "decks", "midrange.json"),
                    ],
                    initial_population="seed_decks",
                    output_dir=tmpdir,
                    log_every_n=1,
                    top_n_summary=3,
                    telemetry={
                        "enabled": True,
                        "save_match_summaries": True,
                        "save_turn_trace": True,
                    },
                )
                runner = EvolutionRunner(config)
                runner.run()

                pat_config = {
                    "min_support": 2,
                    "max_itemset_size": 2,
                    "sequence": {"turns": 3, "min_support": 2},
                    "counter": {
                        "targets": ["aggro_rush", "control_mage"],
                        "min_lift": 1.0,
                    },
                    "top_n_decks": 5,
                }
                output_path = os.path.join(tmpdir, "patterns.json")
                extract_all_patterns(tmpdir, pat_config, output_path=output_path)
                with open(output_path) as f:
                    data = json.load(f)
                results.append(data["patterns"])

        self.assertEqual(results[0], results[1])


class TestTurnTraceOff(unittest.TestCase):
    """When turn_trace is OFF, sequence extraction skips with warning."""

    def test_no_crash_no_sequences(self):
        from card_battle.evolve import EvolutionConfig, EvolutionRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            config = EvolutionConfig(
                global_seed=42,
                generations=2,
                population_size=6,
                matches_per_eval=1,
                elite_pool_size=3,
                elitism=2,
                tournament_k=3,
                cards_path=CARDS_JSON,
                seed_decks=[
                    os.path.join(DATA_DIR, "decks", "aggro_rush.json"),
                    os.path.join(DATA_DIR, "decks", "control_mage.json"),
                    os.path.join(DATA_DIR, "decks", "midrange.json"),
                ],
                initial_population="seed_decks",
                output_dir=tmpdir,
                log_every_n=1,
                top_n_summary=3,
                telemetry={
                    "enabled": True,
                    "save_match_summaries": True,
                    "save_turn_trace": False,
                },
            )
            runner = EvolutionRunner(config)
            runner.run()

            pat_config = {
                "min_support": 2,
                "max_itemset_size": 2,
                "sequence": {"turns": 3, "min_support": 2},
                "counter": {
                    "targets": ["aggro_rush"],
                    "min_lift": 1.0,
                },
                "top_n_decks": 5,
            }
            output_path = os.path.join(tmpdir, "patterns.json")
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                patterns = extract_all_patterns(
                    tmpdir, pat_config, output_path=output_path,
                )
                # Should have warned about missing turn_trace
                trace_warnings = [
                    x for x in w if "turn_trace" in str(x.message)
                ]
                self.assertGreater(len(trace_warnings), 0)

            # No sequence patterns
            seq_patterns = [p for p in patterns if p["type"] == "sequence"]
            self.assertEqual(len(seq_patterns), 0)

            # File still produced (exit code 0 behavior)
            self.assertTrue(os.path.exists(output_path))


class TestTurnTraceCollection(unittest.TestCase):
    """Verify that turn_trace is properly collected by telemetry."""

    def test_turn_trace_present_in_summary(self):
        from card_battle.ai import GreedyAI
        from card_battle.engine import init_game, run_game
        from card_battle.loader import load_cards, load_deck
        from card_battle.telemetry import MatchTelemetry

        card_db = load_cards(CARDS_JSON)
        deck_a = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), card_db,
        )
        deck_b = load_deck(
            os.path.join(DATA_DIR, "decks", "control_mage.json"), card_db,
        )

        tm = MatchTelemetry(save_turn_trace=True, turn_trace_max_cards=3)
        gs = init_game(card_db, deck_a, deck_b, 42)
        agents = (GreedyAI(), GreedyAI())
        run_game(gs, agents, telemetry=tm)

        summary = tm.to_summary()
        self.assertIn("turn_trace", summary)
        self.assertIsInstance(summary["turn_trace"], list)
        self.assertGreater(len(summary["turn_trace"]), 0)

        # Each turn entry has expected fields
        for entry in summary["turn_trace"]:
            self.assertIn("turn", entry)
            self.assertIn("player", entry)
            self.assertIn("played", entry)
            self.assertIn("atk", entry)
            self.assertIn("blk", entry)
            self.assertIsInstance(entry["played"], list)

    def test_turn_trace_absent_when_off(self):
        from card_battle.ai import GreedyAI
        from card_battle.engine import init_game, run_game
        from card_battle.loader import load_cards, load_deck
        from card_battle.telemetry import MatchTelemetry

        card_db = load_cards(CARDS_JSON)
        deck_a = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), card_db,
        )
        deck_b = load_deck(
            os.path.join(DATA_DIR, "decks", "control_mage.json"), card_db,
        )

        tm = MatchTelemetry(save_turn_trace=False)
        gs = init_game(card_db, deck_a, deck_b, 42)
        agents = (GreedyAI(), GreedyAI())
        run_game(gs, agents, telemetry=tm)

        summary = tm.to_summary()
        self.assertNotIn("turn_trace", summary)

    def test_max_cards_truncation(self):
        from card_battle.ai import GreedyAI
        from card_battle.engine import init_game, run_game
        from card_battle.loader import load_cards, load_deck
        from card_battle.telemetry import MatchTelemetry

        card_db = load_cards(CARDS_JSON)
        deck_a = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), card_db,
        )
        deck_b = load_deck(
            os.path.join(DATA_DIR, "decks", "control_mage.json"), card_db,
        )

        # Use max_cards=1 to test truncation
        tm = MatchTelemetry(save_turn_trace=True, turn_trace_max_cards=1)
        gs = init_game(card_db, deck_a, deck_b, 42)
        agents = (GreedyAI(), GreedyAI())
        run_game(gs, agents, telemetry=tm)

        summary = tm.to_summary()
        for entry in summary["turn_trace"]:
            # played list should be at most 2 (1 card + "__MORE__")
            self.assertLessEqual(len(entry["played"]), 2)
            if len(entry["played"]) == 2:
                self.assertEqual(entry["played"][-1], "__MORE__")


if __name__ == "__main__":
    unittest.main()
