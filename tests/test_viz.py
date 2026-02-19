"""Tests for v0.7 visualization module."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from card_battle.viz import build_manifest, convert_replay_jsonl_to_json, export_static_site


def _make_replay_jsonl(path: Path, seed: int = 42,
                       deck_ids: list[str] | None = None) -> None:
    """Write a minimal JSONL replay file for testing."""
    if deck_ids is None:
        deck_ids = ["aggro_rush", "control_mage"]
    events = [
        {"type": "meta", "seed": seed, "deck_ids": deck_ids},
        {
            "type": "game_start", "active_player": 0,
            "p0": {"hp": 20, "mana": 0, "mana_max": 0, "hand_count": 5,
                   "deck_count": 25, "graveyard_count": 0, "board": []},
            "p1": {"hp": 20, "mana": 0, "mana_max": 0, "hand_count": 5,
                   "deck_count": 25, "graveyard_count": 0, "board": []},
        },
        {
            "type": "turn_start", "turn": 1, "active_player": 0,
            "p0": {"hp": 20, "mana": 1, "mana_max": 1, "hand_count": 6,
                   "deck_count": 24, "graveyard_count": 0, "board": []},
            "p1": {"hp": 20, "mana": 0, "mana_max": 0, "hand_count": 5,
                   "deck_count": 25, "graveyard_count": 0, "board": []},
        },
        {"type": "play_card", "turn": 1, "player": 0, "card_id": "bolt",
         "cost": 1, "card_type": "spell", "mana_after": 0, "hand_count_after": 5},
        {"type": "turn_end", "turn": 1, "active_player": 0},
        {
            "type": "turn_start", "turn": 2, "active_player": 1,
            "p0": {"hp": 20, "mana": 0, "mana_max": 1, "hand_count": 5,
                   "deck_count": 24, "graveyard_count": 1, "board": []},
            "p1": {"hp": 17, "mana": 1, "mana_max": 1, "hand_count": 6,
                   "deck_count": 24, "graveyard_count": 0, "board": []},
        },
        {"type": "turn_end", "turn": 2, "active_player": 1},
        {"type": "game_end", "winner": "player_0_win", "reason": "normal",
         "turns": 2, "final_hp": [20, 17]},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _make_run_dir(base: Path, *, num_cycles: int = 2,
                  include_replays: bool = True) -> Path:
    """Build a minimal cycle run directory structure for testing."""
    run_dir = base / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    cycles_data = []
    for i in range(num_cycles):
        cycle_id = f"cycle_{i:03d}"
        gate_passed = (i % 2 == 0)
        cards_added = 2 if gate_passed else 0

        cycles_data.append({
            "cycle_index": i,
            "cycle_seed": 1000 + i,
            "gate_passed": gate_passed,
            "cards_added": cards_added,
            "exit_reason": "success" if gate_passed else "gate_failed",
        })

        cycle_dir = run_dir / "cycles" / cycle_id

        # promotion_report.json
        promo_dir = cycle_dir / "promote"
        promo_dir.mkdir(parents=True, exist_ok=True)
        promo_report = {
            "before": {
                "win_rates_by_target": {"aggro_rush": 0.50, "control_mage": 0.50},
                "overall_win_rate": 0.50,
                "telemetry_aggregate": {
                    "avg_total_turns": 10.0,
                    "avg_p0_mana_wasted": 1.5,
                    "avg_p1_mana_wasted": 1.8,
                    "avg_p0_unblocked_damage": 3.0,
                    "avg_p1_unblocked_damage": 2.5,
                },
            },
            "after": {
                "win_rates_by_target": {"aggro_rush": 0.52, "control_mage": 0.48},
                "overall_win_rate": 0.50,
                "telemetry_aggregate": {
                    "avg_total_turns": 9.6,
                    "avg_p0_mana_wasted": 1.3,
                    "avg_p1_mana_wasted": 1.6,
                    "avg_p0_unblocked_damage": 1.9,
                    "avg_p1_unblocked_damage": 2.0,
                },
            },
            "delta": {"aggro_rush": 0.02, "control_mage": -0.02},
            "gate": {
                "passed": gate_passed,
                "checks": {
                    "max_matchup_winrate": {"passed": True, "threshold": 0.95, "actual": 0.52},
                    "turns_delta_ratio": {"passed": True, "threshold": 0.20, "actual": 0.04},
                    "mana_wasted_delta_ratio": {"passed": gate_passed, "threshold": 0.20, "actual": 0.05 if gate_passed else 0.25},
                },
                "reason": "all checks passed" if gate_passed else "failed: mana_wasted_delta_ratio",
            },
        }
        with open(promo_dir / "promotion_report.json", "w", encoding="utf-8") as f:
            json.dump(promo_report, f, indent=2, ensure_ascii=False)

        # selected_cards.json
        if gate_passed:
            cardgen_dir = cycle_dir / "cardgen"
            cardgen_dir.mkdir(parents=True, exist_ok=True)
            selected = [
                {"candidate_card": {"id": f"card_{i}_a", "card_type": "unit", "cost": 2}},
                {"candidate_card": {"id": f"card_{i}_b", "card_type": "spell", "cost": 3}},
            ]
            with open(cardgen_dir / "selected_cards.json", "w", encoding="utf-8") as f:
                json.dump(selected, f, indent=2, ensure_ascii=False)

        # replays
        if include_replays:
            replay_dir = cycle_dir / "replays"
            _make_replay_jsonl(
                replay_dir / "matchup_0.jsonl",
                seed=1000 + i,
                deck_ids=["aggro_rush", "control_mage"],
            )

    # cycle_summary.json
    summary = {
        "total_cycles": num_cycles,
        "gates_passed": sum(1 for c in cycles_data if c["gate_passed"]),
        "gates_failed": sum(1 for c in cycles_data if not c["gate_passed"]),
        "total_cards_added": sum(c["cards_added"] for c in cycles_data),
        "cycles": cycles_data,
    }
    with open(run_dir / "cycle_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return run_dir


class TestConvertReplay(unittest.TestCase):
    """Test JSONL → JSON conversion."""

    def test_basic_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jsonl_path = tmp_path / "test.jsonl"
            out_path = tmp_path / "out.json"

            _make_replay_jsonl(jsonl_path, seed=42, deck_ids=["aggro_rush", "control_mage"])
            replay_id = convert_replay_jsonl_to_json(jsonl_path, out_path)

            self.assertEqual(replay_id, "aggro_rush_vs_control_mage_42")
            self.assertTrue(out_path.exists())

            with open(out_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertGreater(len(data), 0)
            self.assertEqual(data[0]["type"], "meta")

    def test_replay_id_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jsonl_path = tmp_path / "test.jsonl"
            out_path = tmp_path / "out.json"

            _make_replay_jsonl(jsonl_path, seed=999, deck_ids=["deck_a", "deck_b"])
            replay_id = convert_replay_jsonl_to_json(jsonl_path, out_path)
            self.assertEqual(replay_id, "deck_a_vs_deck_b_999")


class TestBuildManifest(unittest.TestCase):
    """Test manifest building from run directory."""

    def test_manifest_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp), num_cycles=2)
            replays_out = Path(tmp) / "replays_out"
            replays_out.mkdir()

            manifest = build_manifest(run_dir, replays_out)

            self.assertIn("cycles", manifest)
            self.assertIn("replays", manifest)
            self.assertEqual(len(manifest["cycles"]), 2)

    def test_cycles_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp), num_cycles=2)
            replays_out = Path(tmp) / "replays_out"
            replays_out.mkdir()

            manifest = build_manifest(run_dir, replays_out)
            c0 = manifest["cycles"][0]

            self.assertEqual(c0["cycle_index"], 0)
            self.assertTrue(c0["gate_passed"])
            self.assertEqual(c0["cards_added"], 2)
            self.assertIn("deltas", c0)
            self.assertIn("win_rate", c0["deltas"])
            self.assertIn("gate_checks", c0)
            self.assertIn("promoted_cards", c0)
            self.assertEqual(len(c0["promoted_cards"]), 2)

    def test_replays_converted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp), num_cycles=2)
            replays_out = Path(tmp) / "replays_out"
            replays_out.mkdir()

            manifest = build_manifest(run_dir, replays_out)

            self.assertEqual(len(manifest["replays"]), 2)
            for r in manifest["replays"]:
                self.assertIn("replay_id", r)
                self.assertIn("cycle_index", r)
                # Check that JSON file was created
                json_file = replays_out / f"{r['replay_id']}.json"
                self.assertTrue(json_file.exists(), f"Missing: {json_file}")

    def test_stable_sort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp), num_cycles=3)
            replays_out = Path(tmp) / "replays_out"
            replays_out.mkdir()

            manifest = build_manifest(run_dir, replays_out)

            cycle_indices = [c["cycle_index"] for c in manifest["cycles"]]
            self.assertEqual(cycle_indices, sorted(cycle_indices))

            replay_ids = [r["replay_id"] for r in manifest["replays"]]
            self.assertEqual(replay_ids, sorted(replay_ids))


class TestExportStaticSite(unittest.TestCase):
    """Test full static site generation."""

    def test_all_files_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp), num_cycles=2)
            out_dir = Path(tmp) / "site"

            result = export_static_site(run_dir, out_dir)

            self.assertEqual(result, out_dir)
            self.assertTrue((out_dir / "index.html").exists())
            self.assertTrue((out_dir / "replay.html").exists())
            self.assertTrue((out_dir / "assets" / "app.js").exists())
            self.assertTrue((out_dir / "assets" / "style.css").exists())
            self.assertTrue((out_dir / "data" / "manifest.json").exists())

    def test_manifest_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp), num_cycles=2)
            out_dir = Path(tmp) / "site"

            export_static_site(run_dir, out_dir)

            with open(out_dir / "data" / "manifest.json", encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertIn("cycles", manifest)
            self.assertEqual(len(manifest["cycles"]), 2)

    def test_replay_json_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp), num_cycles=1)
            out_dir = Path(tmp) / "site"

            export_static_site(run_dir, out_dir)

            replay_files = list((out_dir / "data" / "replays").glob("*.json"))
            self.assertGreater(len(replay_files), 0)


class TestExportDeterminism(unittest.TestCase):
    """Test that same input produces byte-identical manifest."""

    def test_deterministic_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp), num_cycles=2)

            out1 = Path(tmp) / "site1"
            out2 = Path(tmp) / "site2"

            export_static_site(run_dir, out1)
            export_static_site(run_dir, out2)

            m1 = (out1 / "data" / "manifest.json").read_bytes()
            m2 = (out2 / "data" / "manifest.json").read_bytes()
            self.assertEqual(m1, m2, "manifest.json should be byte-identical for same input")


class TestExportNoReplays(unittest.TestCase):
    """Test that export works when no replays are present."""

    def test_no_replays_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp), num_cycles=1, include_replays=False)
            out_dir = Path(tmp) / "site"

            result = export_static_site(run_dir, out_dir)

            self.assertEqual(result, out_dir)
            self.assertTrue((out_dir / "index.html").exists())
            self.assertTrue((out_dir / "data" / "manifest.json").exists())

            with open(out_dir / "data" / "manifest.json", encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertEqual(len(manifest["replays"]), 0)

    def test_no_cycle_summary(self) -> None:
        """Export with empty run dir should not error."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "empty_run"
            run_dir.mkdir()
            out_dir = Path(tmp) / "site"

            result = export_static_site(run_dir, out_dir)

            self.assertTrue((out_dir / "index.html").exists())
            with open(out_dir / "data" / "manifest.json", encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertEqual(len(manifest["cycles"]), 0)
            self.assertEqual(len(manifest["replays"]), 0)


if __name__ == "__main__":
    unittest.main()
