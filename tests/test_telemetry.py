"""Tests for v3.1: Match telemetry."""

import os
import unittest

from card_battle.ai import GreedyAI
from card_battle.engine import init_game, run_game
from card_battle.loader import load_cards, load_deck
from card_battle.telemetry import MatchTelemetry, TelemetryConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")


class TestTelemetryConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = TelemetryConfig()
        self.assertTrue(cfg.enabled)
        self.assertFalse(cfg.save_match_summaries)
        self.assertIsNone(cfg.output_path)


class TestMatchTelemetry(unittest.TestCase):
    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.aggro = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db
        )
        self.control = load_deck(
            os.path.join(DATA_DIR, "decks", "control_mage.json"), self.card_db
        )
        self.midrange = load_deck(
            os.path.join(DATA_DIR, "decks", "midrange.json"), self.card_db
        )

    def _run_with_telemetry(self, deck_a, deck_b, seed=42):
        gs = init_game(self.card_db, deck_a, deck_b, seed)
        agents = (GreedyAI(), GreedyAI())
        tm = MatchTelemetry()
        log = run_game(gs, agents, telemetry=tm)
        return log, tm

    def test_summary_has_expected_keys(self):
        _, tm = self._run_with_telemetry(self.aggro, self.control)
        summary = tm.to_summary()
        self.assertIn("total_turns", summary)
        self.assertIn("winner", summary)
        self.assertIn("reason", summary)
        self.assertIn("p0_cards_played", summary)
        self.assertIn("p1_cards_played", summary)
        self.assertIn("p0_mana_spent", summary)
        self.assertIn("p1_mana_wasted", summary)
        self.assertIn("p0_damage_to_player", summary)
        self.assertIn("p1_units_summoned", summary)

    def test_mana_invariant(self):
        """Mana spent + mana wasted == total mana granted for each player."""
        for seed in range(10):
            _, tm = self._run_with_telemetry(self.aggro, self.control, seed=seed)
            for pi in range(2):
                granted = tm.total_mana_granted[pi]
                spent = tm.mana_spent[pi]
                wasted = tm.mana_wasted[pi]
                self.assertEqual(
                    spent + wasted, granted,
                    f"Mana invariant violated for p{pi} seed={seed}: "
                    f"{spent} + {wasted} != {granted}",
                )

    def test_attacks_nonnegative(self):
        _, tm = self._run_with_telemetry(self.aggro, self.control)
        for pi in range(2):
            self.assertGreaterEqual(tm.attacks_declared[pi], 0)
            self.assertGreaterEqual(tm.attackers_total[pi], 0)

    def test_cards_played_positive(self):
        """At least some cards should be played in a typical game."""
        _, tm = self._run_with_telemetry(self.aggro, self.control)
        total_played = tm.cards_played[0] + tm.cards_played[1]
        self.assertGreater(total_played, 0)

    def test_drawn_total_includes_turn_and_effect(self):
        """drawn_total >= drawn_turn + drawn_effect for each player."""
        for seed in range(5):
            _, tm = self._run_with_telemetry(self.aggro, self.control, seed=seed)
            for pi in range(2):
                self.assertEqual(
                    tm.drawn_total[pi],
                    tm.drawn_turn[pi] + tm.drawn_effect[pi],
                    f"Draw count mismatch for p{pi} seed={seed}",
                )

    def test_damage_direction(self):
        """Total damage_to_player + unblocked_damage should be >= 0."""
        _, tm = self._run_with_telemetry(self.aggro, self.control)
        for pi in range(2):
            self.assertGreaterEqual(tm.damage_to_player[pi], 0)
            self.assertGreaterEqual(tm.unblocked_damage[pi], 0)


class TestDeterminismRegression(unittest.TestCase):
    """Telemetry on/off must not change game outcome."""

    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.decks = [
            load_deck(os.path.join(DATA_DIR, "decks", f), self.card_db)
            for f in ["aggro_rush.json", "control_mage.json", "midrange.json"]
        ]

    def test_telemetry_does_not_affect_outcome(self):
        """Same seed → same winner regardless of telemetry on/off."""
        agents = (GreedyAI(), GreedyAI())
        for seed in range(20):
            for da in self.decks:
                for db in self.decks:
                    if da.deck_id == db.deck_id:
                        continue
                    # Without telemetry
                    gs1 = init_game(self.card_db, da, db, seed)
                    log1 = run_game(gs1, agents)

                    # With telemetry
                    gs2 = init_game(self.card_db, da, db, seed)
                    tm = MatchTelemetry()
                    log2 = run_game(gs2, agents, telemetry=tm)

                    self.assertEqual(
                        log1.winner, log2.winner,
                        f"Winner mismatch seed={seed} {da.deck_id} vs {db.deck_id}",
                    )
                    self.assertEqual(log1.turns, log2.turns)
                    self.assertEqual(log1.final_hp, log2.final_hp)


class TestMultipleSeedsTelemetry(unittest.TestCase):
    """Run many games with telemetry to exercise all code paths."""

    def setUp(self):
        self.card_db = load_cards(CARDS_JSON)
        self.aggro = load_deck(
            os.path.join(DATA_DIR, "decks", "aggro_rush.json"), self.card_db
        )
        self.midrange = load_deck(
            os.path.join(DATA_DIR, "decks", "midrange.json"), self.card_db
        )

    def test_50_games_no_crash(self):
        agents = (GreedyAI(), GreedyAI())
        for seed in range(50):
            gs = init_game(self.card_db, self.aggro, self.midrange, seed)
            tm = MatchTelemetry()
            log = run_game(gs, agents, telemetry=tm)
            summary = tm.to_summary()
            self.assertIn("winner", summary)
            # Mana invariant
            for pi in range(2):
                self.assertEqual(
                    tm.mana_spent[pi] + tm.mana_wasted[pi],
                    tm.total_mana_granted[pi],
                )


if __name__ == "__main__":
    unittest.main()
