"""v0.5.9: Tests for replay recording and playback."""

import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from card_battle.ai import GreedyAI
from card_battle.engine import init_game, run_game
from card_battle.loader import load_cards, load_deck
from card_battle.replay import ReplayWriter, render_replay, snapshot_board, snapshot_player

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CARDS_JSON = os.path.join(DATA_DIR, "cards.json")
DECK_DIR = os.path.join(DATA_DIR, "decks")


def _load_fixtures():
    card_db = load_cards(CARDS_JSON)
    deck_a = load_deck(os.path.join(DECK_DIR, "aggro_rush.json"), card_db)
    deck_b = load_deck(os.path.join(DECK_DIR, "control_mage.json"), card_db)
    return card_db, deck_a, deck_b


def _run_with_replay(card_db, deck_a, deck_b, seed, replay_path):
    """Run a game with replay enabled and return (log, events)."""
    gs = init_game(card_db, deck_a, deck_b, seed)
    with ReplayWriter(replay_path) as rw:
        rw.write({
            "type": "meta",
            "seed": seed,
            "deck_ids": [deck_a.deck_id, deck_b.deck_id],
        })
        log = run_game(gs, (GreedyAI(), GreedyAI()), replay=rw)

    events = []
    with open(replay_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return log, events


class TestReplayWriter(unittest.TestCase):
    def test_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.jsonl"
            with ReplayWriter(path) as rw:
                rw.write({"a": 1})
                rw.write({"b": 2})
            lines = path.read_text().strip().split("\n")
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0]), {"a": 1})
            self.assertEqual(json.loads(lines[1]), {"b": 2})

    def test_context_manager(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.jsonl"
            with ReplayWriter(path) as rw:
                rw.write({"x": 1})
            # File should be closed
            self.assertTrue(rw._closed)

    def test_close_then_write_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.jsonl"
            rw = ReplayWriter(path)
            rw.close()
            with self.assertRaises(RuntimeError):
                rw.write({"x": 1})

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "a" / "b" / "c" / "test.jsonl"
            with ReplayWriter(path) as rw:
                rw.write({"x": 1})
            self.assertTrue(path.exists())

    def test_path_property(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.jsonl"
            with ReplayWriter(path) as rw:
                self.assertEqual(rw.path, path)


class TestReplayDeterminism(unittest.TestCase):
    """Replay ON/OFF must produce identical game results."""

    def test_replay_does_not_affect_result(self):
        card_db, deck_a, deck_b = _load_fixtures()
        decks = [
            (deck_a, deck_b),
            (deck_b, deck_a),
            (deck_a, deck_a),
        ]
        for da, db in decks:
            for seed in range(20):
                # Without replay
                gs1 = init_game(card_db, da, db, seed)
                log1 = run_game(gs1, (GreedyAI(), GreedyAI()))

                # With replay
                with tempfile.TemporaryDirectory() as td:
                    replay_path = Path(td) / f"{seed}.jsonl"
                    gs2 = init_game(card_db, da, db, seed)
                    with ReplayWriter(replay_path) as rw:
                        rw.write({"type": "meta", "seed": seed,
                                  "deck_ids": [da.deck_id, db.deck_id]})
                        log2 = run_game(gs2, (GreedyAI(), GreedyAI()), replay=rw)

                    self.assertEqual(log1.winner, log2.winner,
                                     f"Winner mismatch at seed={seed}")
                    self.assertEqual(log1.turns, log2.turns,
                                     f"Turns mismatch at seed={seed}")
                    self.assertEqual(log1.final_hp, log2.final_hp,
                                     f"Final HP mismatch at seed={seed}")


class TestReplayStructure(unittest.TestCase):
    """Verify event ordering and required keys."""

    def test_event_order(self):
        card_db, deck_a, deck_b = _load_fixtures()
        with tempfile.TemporaryDirectory() as td:
            replay_path = Path(td) / "test.jsonl"
            log, events = _run_with_replay(card_db, deck_a, deck_b, 42, replay_path)

        types = [e["type"] for e in events]

        # Must start with meta, then game_start
        self.assertEqual(types[0], "meta")
        self.assertEqual(types[1], "game_start")

        # Must end with game_end
        self.assertEqual(types[-1], "game_end")

        # turn_start and turn_end must be paired
        turn_starts = [e for e in events if e["type"] == "turn_start"]
        turn_ends = [e for e in events if e["type"] == "turn_end"]
        self.assertEqual(len(turn_starts), len(turn_ends))

        # Turn numbers must match in order
        for ts, te in zip(turn_starts, turn_ends):
            self.assertEqual(ts["turn"], te["turn"])

    def test_required_keys(self):
        card_db, deck_a, deck_b = _load_fixtures()
        with tempfile.TemporaryDirectory() as td:
            replay_path = Path(td) / "test.jsonl"
            _, events = _run_with_replay(card_db, deck_a, deck_b, 42, replay_path)

        required_keys = {
            "meta": {"type", "seed", "deck_ids"},
            "game_start": {"type", "active_player", "p0", "p1"},
            "turn_start": {"type", "turn", "active_player", "p0", "p1"},
            "play_card": {"type", "turn", "player", "card_id", "cost", "card_type"},
            "go_to_combat": {"type", "turn", "player"},
            "declare_attack": {"type", "turn", "player", "attacker_uids", "attackers"},
            "declare_block": {"type", "turn", "player", "pairs"},
            "combat_resolve": {"type", "turn", "attacker_player", "defender_player",
                               "player_damage", "hp_after_p0", "hp_after_p1"},
            "turn_end": {"type", "turn", "active_player"},
            "game_end": {"type", "winner", "reason", "turns", "final_hp"},
        }

        for event in events:
            etype = event["type"]
            if etype in required_keys:
                missing = required_keys[etype] - set(event.keys())
                self.assertEqual(missing, set(),
                                 f"Missing keys in {etype}: {missing}")

    def test_meta_has_correct_seed(self):
        card_db, deck_a, deck_b = _load_fixtures()
        with tempfile.TemporaryDirectory() as td:
            replay_path = Path(td) / "test.jsonl"
            _, events = _run_with_replay(card_db, deck_a, deck_b, 99, replay_path)

        self.assertEqual(events[0]["seed"], 99)

    def test_game_end_matches_log(self):
        card_db, deck_a, deck_b = _load_fixtures()
        with tempfile.TemporaryDirectory() as td:
            replay_path = Path(td) / "test.jsonl"
            log, events = _run_with_replay(card_db, deck_a, deck_b, 42, replay_path)

        game_end = events[-1]
        self.assertEqual(game_end["winner"], log.winner.value)
        self.assertEqual(game_end["turns"], log.turns)
        self.assertEqual(game_end["final_hp"], list(log.final_hp))


class TestReplayHPConsistency(unittest.TestCase):
    """combat_resolve hp_after must match next turn_start hp."""

    def test_hp_consistency(self):
        card_db, deck_a, deck_b = _load_fixtures()

        for seed in range(10):
            with tempfile.TemporaryDirectory() as td:
                replay_path = Path(td) / f"{seed}.jsonl"
                _, events = _run_with_replay(card_db, deck_a, deck_b, seed, replay_path)

            # Collect hp snapshots from combat_resolve and following turn_start
            combat_resolves = []
            turn_starts = []
            for i, ev in enumerate(events):
                if ev["type"] == "combat_resolve":
                    combat_resolves.append(ev)
                    # Find the next turn_start after this
                    for j in range(i + 1, len(events)):
                        if events[j]["type"] == "turn_start":
                            turn_starts.append(events[j])
                            break

            for cr, ts in zip(combat_resolves, turn_starts):
                self.assertEqual(
                    cr["hp_after_p0"], ts["p0"]["hp"],
                    f"HP P0 mismatch at turn {cr['turn']}: "
                    f"combat_resolve={cr['hp_after_p0']} vs turn_start={ts['p0']['hp']}"
                )
                self.assertEqual(
                    cr["hp_after_p1"], ts["p1"]["hp"],
                    f"HP P1 mismatch at turn {cr['turn']}: "
                    f"combat_resolve={cr['hp_after_p1']} vs turn_start={ts['p1']['hp']}"
                )


class TestReplayViewer(unittest.TestCase):
    """render_replay should not crash."""

    def test_render_default(self):
        card_db, deck_a, deck_b = _load_fixtures()
        with tempfile.TemporaryDirectory() as td:
            replay_path = Path(td) / "test.jsonl"
            _run_with_replay(card_db, deck_a, deck_b, 42, replay_path)

            with patch("sys.stdout", new_callable=StringIO) as out:
                render_replay(replay_path)
            output = out.getvalue()
            self.assertIn("REPLAY", output)
            self.assertIn("GAME END", output)

    def test_render_compact(self):
        card_db, deck_a, deck_b = _load_fixtures()
        with tempfile.TemporaryDirectory() as td:
            replay_path = Path(td) / "test.jsonl"
            _run_with_replay(card_db, deck_a, deck_b, 42, replay_path)

            with patch("sys.stdout", new_callable=StringIO) as out:
                render_replay(replay_path, compact=True)
            output = out.getvalue()
            self.assertIn("REPLAY", output)

    def test_render_turn_range(self):
        card_db, deck_a, deck_b = _load_fixtures()
        with tempfile.TemporaryDirectory() as td:
            replay_path = Path(td) / "test.jsonl"
            _run_with_replay(card_db, deck_a, deck_b, 42, replay_path)

            with patch("sys.stdout", new_callable=StringIO) as out:
                render_replay(replay_path, from_turn=3, to_turn=5)
            output = out.getvalue()
            # Should still have meta/game start info
            self.assertIn("REPLAY", output)


class TestReplay50Games(unittest.TestCase):
    """Stress test: 50 games with replay should all complete."""

    def test_50_games(self):
        card_db, deck_a, deck_b = _load_fixtures()
        with tempfile.TemporaryDirectory() as td:
            for seed in range(50):
                replay_path = Path(td) / f"{seed}.jsonl"
                log, events = _run_with_replay(card_db, deck_a, deck_b, seed, replay_path)

                # Basic sanity
                self.assertGreater(len(events), 3)
                self.assertEqual(events[0]["type"], "meta")
                self.assertEqual(events[-1]["type"], "game_end")
                self.assertEqual(events[-1]["winner"], log.winner.value)


class TestSnapshotHelpers(unittest.TestCase):
    def test_snapshot_player(self):
        from card_battle.models import PlayerState, UnitInstance
        p = PlayerState(hp=15, mana=3, mana_max=5)
        p.hand = ["c1", "c2"]
        p.deck = ["c3"]
        p.graveyard = ["c4", "c5"]
        p.board = [UnitInstance(uid=1, card_id="u1", atk=2, hp=3)]

        snap = snapshot_player(p)
        self.assertEqual(snap["hp"], 15)
        self.assertEqual(snap["mana"], 3)
        self.assertEqual(snap["mana_max"], 5)
        self.assertEqual(snap["hand_count"], 2)
        self.assertEqual(snap["deck_count"], 1)
        self.assertEqual(snap["graveyard_count"], 2)
        self.assertEqual(len(snap["board"]), 1)
        self.assertEqual(snap["board"][0]["card_id"], "u1")

    def test_snapshot_board(self):
        from card_battle.models import UnitInstance
        board = [
            UnitInstance(uid=1, card_id="u1", atk=2, hp=3, can_attack=True),
            UnitInstance(uid=2, card_id="u2", atk=4, hp=1, can_attack=False),
        ]
        snap = snapshot_board(board)
        self.assertEqual(len(snap), 2)
        self.assertEqual(snap[0]["uid"], 1)
        self.assertTrue(snap[0]["can_attack"])
        self.assertFalse(snap[1]["can_attack"])


if __name__ == "__main__":
    unittest.main()
