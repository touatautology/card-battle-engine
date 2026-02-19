"""Tests for v3.1: Metrics aggregation."""

import unittest

from card_battle.metrics import aggregate_match_summaries


class TestAggregateMatchSummaries(unittest.TestCase):
    def _make_summaries(self):
        return [
            {
                "deck_id": "deck_a",
                "total_turns": 10,
                "p0_cards_played": 5,
                "p1_cards_played": 3,
                "p0_mana_spent": 12,
                "p1_mana_spent": 8,
                "p0_mana_wasted": 3,
                "p1_mana_wasted": 7,
                "p0_total_mana_granted": 15,
                "p1_total_mana_granted": 15,
            },
            {
                "deck_id": "deck_a",
                "total_turns": 14,
                "p0_cards_played": 7,
                "p1_cards_played": 5,
                "p0_mana_spent": 20,
                "p1_mana_spent": 14,
                "p0_mana_wasted": 1,
                "p1_mana_wasted": 7,
                "p0_total_mana_granted": 21,
                "p1_total_mana_granted": 21,
            },
            {
                "deck_id": "deck_b",
                "total_turns": 8,
                "p0_cards_played": 4,
                "p1_cards_played": 2,
                "p0_mana_spent": 10,
                "p1_mana_spent": 6,
                "p0_mana_wasted": 2,
                "p1_mana_wasted": 6,
                "p0_total_mana_granted": 12,
                "p1_total_mana_granted": 12,
            },
        ]

    def test_overall_count(self):
        summaries = self._make_summaries()
        result = aggregate_match_summaries(summaries)
        self.assertEqual(result["count"], 3)

    def test_overall_mean(self):
        summaries = self._make_summaries()
        result = aggregate_match_summaries(summaries)
        overall = result["overall"]
        # total_turns: (10 + 14 + 8) / 3 = 10.6667
        self.assertAlmostEqual(overall["total_turns"]["mean"], 10.6667, places=3)
        self.assertAlmostEqual(overall["total_turns"]["sum"], 32.0)

    def test_overall_sum(self):
        summaries = self._make_summaries()
        result = aggregate_match_summaries(summaries)
        overall = result["overall"]
        # p0_cards_played: 5 + 7 + 4 = 16
        self.assertAlmostEqual(overall["p0_cards_played"]["sum"], 16.0)

    def test_grouping_by_deck_id(self):
        summaries = self._make_summaries()
        result = aggregate_match_summaries(summaries, group_keys=["deck_id"])
        self.assertIn("by_group", result)
        self.assertIn("deck_a", result["by_group"])
        self.assertIn("deck_b", result["by_group"])

        # deck_a has 2 entries
        deck_a = result["by_group"]["deck_a"]
        self.assertEqual(deck_a["total_turns"]["count"], 2)
        # mean turns for deck_a: (10 + 14) / 2 = 12.0
        self.assertAlmostEqual(deck_a["total_turns"]["mean"], 12.0)

        # deck_b has 1 entry
        deck_b = result["by_group"]["deck_b"]
        self.assertEqual(deck_b["total_turns"]["count"], 1)
        self.assertAlmostEqual(deck_b["total_turns"]["mean"], 8.0)

    def test_empty_summaries(self):
        result = aggregate_match_summaries([])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["overall"], {})

    def test_no_group_keys(self):
        summaries = self._make_summaries()
        result = aggregate_match_summaries(summaries)
        self.assertNotIn("by_group", result)

    def test_missing_field_ignored(self):
        """Summaries missing some numeric fields still aggregate others."""
        summaries = [
            {"deck_id": "x", "total_turns": 5},
            {"deck_id": "x", "total_turns": 7, "p0_cards_played": 3},
        ]
        result = aggregate_match_summaries(summaries)
        overall = result["overall"]
        self.assertAlmostEqual(overall["total_turns"]["mean"], 6.0)
        # p0_cards_played: only 1 summary has it, but we divide by 2 (total count)
        self.assertAlmostEqual(overall["p0_cards_played"]["mean"], 1.5)


if __name__ == "__main__":
    unittest.main()
