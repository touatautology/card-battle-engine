"""Phase 8: Batch simulation and aggregation."""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any

from card_battle.ai import GreedyAI
from card_battle.engine import init_game, run_game
from card_battle.models import Card, DeckDef, GameResult, MatchLog


def run_batch(
    card_db: dict[str, Card],
    decks: list[DeckDef],
    n_matches: int,
    base_seed: int,
    output_dir: str | Path | None = None,
    trace: bool = False,
) -> list[MatchLog]:
    """Run round-robin matches between all deck pairs."""
    agents = (GreedyAI(), GreedyAI())
    logs: list[MatchLog] = []
    pairs = list(combinations(range(len(decks)), 2))

    match_id = 0
    for i, j in pairs:
        for m in range(n_matches):
            seed = base_seed + match_id
            gs = init_game(card_db, decks[i], decks[j], seed)
            log = run_game(gs, agents, trace=trace)
            log.seed = seed  # type: ignore[misc]
            log.deck_ids = (decks[i].deck_id, decks[j].deck_id)  # type: ignore[misc]
            logs.append(log)
            match_id += 1

    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        _write_logs(logs, out / "match_logs.json")

    return logs


def _write_logs(logs: list[MatchLog], path: Path) -> None:
    data = []
    for i, log in enumerate(logs):
        entry: dict[str, Any] = {
            "match_id": i,
            "seed": log.seed,
            "deck_ids": list(log.deck_ids),
            "winner": log.winner.value,
            "turns": log.turns,
            "final_hp": list(log.final_hp),
        }
        if log.play_trace is not None:
            entry["play_trace"] = log.play_trace
        data.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def aggregate(logs: list[MatchLog]) -> dict[str, Any]:
    """Compute per-deck win rates and first/second player stats."""
    deck_stats: dict[str, dict[str, int]] = {}
    first_wins = 0
    second_wins = 0
    draws = 0

    for log in logs:
        d0, d1 = log.deck_ids
        for did in (d0, d1):
            if did not in deck_stats:
                deck_stats[did] = {"wins": 0, "losses": 0, "draws": 0, "games": 0}

        deck_stats[d0]["games"] += 1
        deck_stats[d1]["games"] += 1

        if log.winner == GameResult.PLAYER_0_WIN:
            deck_stats[d0]["wins"] += 1
            deck_stats[d1]["losses"] += 1
        elif log.winner == GameResult.PLAYER_1_WIN:
            deck_stats[d1]["wins"] += 1
            deck_stats[d0]["losses"] += 1
        else:
            deck_stats[d0]["draws"] += 1
            deck_stats[d1]["draws"] += 1
            draws += 1

        # First/second player (player 0 in GameState is seat 0, not necessarily first)
        # Winner tells us seat, not turn order — but since init_game randomizes first player,
        # we track from the MatchLog perspective
        if log.winner == GameResult.PLAYER_0_WIN:
            first_wins += 1
        elif log.winner == GameResult.PLAYER_1_WIN:
            second_wins += 1

    result: dict[str, Any] = {"decks": {}, "total_matches": len(logs), "draws": draws}
    for did, stats in sorted(deck_stats.items()):
        games = stats["games"]
        result["decks"][did] = {
            "games": games,
            "wins": stats["wins"],
            "losses": stats["losses"],
            "draws": stats["draws"],
            "win_rate": round(stats["wins"] / games * 100, 1) if games else 0,
        }
    result["seat_0_wins"] = first_wins
    result["seat_1_wins"] = second_wins

    return result


def compute_card_adoption(decks: list[DeckDef]) -> dict[str, int]:
    """Count how many decks include each card."""
    adoption: dict[str, int] = {}
    for deck in decks:
        for entry in deck.entries:
            adoption[entry.card_id] = adoption.get(entry.card_id, 0) + 1
    return dict(sorted(adoption.items(), key=lambda x: -x[1]))
