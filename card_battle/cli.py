"""Phase 9b: CLI entry point – play / simulate / stats subcommands."""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from card_battle.ai import GreedyAI, HumanAgent
from card_battle.display import render_board, render_stats, render_card_adoption
from card_battle.engine import init_game, run_game
from card_battle.loader import load_cards, load_deck
from card_battle.models import GameResult
from card_battle.simulation import run_batch, aggregate, compute_card_adoption

DEFAULT_CARDS = Path(__file__).resolve().parent.parent / "data" / "cards.json"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="card_battle", description="Card Battle Engine v0.1")
    sub = parser.add_subparsers(dest="command")

    # --- play ---
    p_play = sub.add_parser("play", help="Play a single match")
    p_play.add_argument("--deck-a", required=True, help="Path to deck A JSON")
    p_play.add_argument("--deck-b", required=True, help="Path to deck B JSON")
    p_play.add_argument("--seed", type=int, default=42)
    p_play.add_argument("--mode", choices=["ava", "hva", "hvh"], default="ava",
                        help="ava=AI vs AI, hva=Human vs AI, hvh=Human vs Human")
    p_play.add_argument("--cards", default=str(DEFAULT_CARDS), help="Path to cards.json")
    p_play.add_argument("--trace", action="store_true", help="Print play trace")

    # --- simulate ---
    p_sim = sub.add_parser("simulate", help="Run batch simulation")
    p_sim.add_argument("--decks", nargs="+", required=True, help="Deck JSON files (glob supported)")
    p_sim.add_argument("--matches", type=int, default=100, help="Matches per pair")
    p_sim.add_argument("--seed", type=int, default=42)
    p_sim.add_argument("--round-robin", action="store_true", default=True)
    p_sim.add_argument("--output", default="output/", help="Output directory")
    p_sim.add_argument("--trace", action="store_true", help="Include play traces in log")
    p_sim.add_argument("--cards", default=str(DEFAULT_CARDS), help="Path to cards.json")

    # --- stats ---
    p_stats = sub.add_parser("stats", help="Show stats from match logs")
    p_stats.add_argument("--logs", required=True, help="Path to match_logs.json")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "play":
        _cmd_play(args)
    elif args.command == "simulate":
        _cmd_simulate(args)
    elif args.command == "stats":
        _cmd_stats(args)


def _cmd_play(args: argparse.Namespace) -> None:
    card_db = load_cards(args.cards)
    deck_a = load_deck(args.deck_a, card_db)
    deck_b = load_deck(args.deck_b, card_db)

    if args.mode == "ava":
        agents = (GreedyAI(), GreedyAI())
    elif args.mode == "hva":
        agents = (HumanAgent(), GreedyAI())
    else:
        agents = (HumanAgent(), HumanAgent())

    gs = init_game(card_db, deck_a, deck_b, args.seed)
    log = run_game(gs, agents, trace=args.trace)

    render_board(gs)
    print(f"Result: {log.winner.value}")
    print(f"Turns: {log.turns}  Final HP: P0={log.final_hp[0]} P1={log.final_hp[1]}")

    if log.play_trace:
        print(f"\nTrace ({len(log.play_trace)} actions):")
        for entry in log.play_trace:
            print(f"  T{entry['turn']} P{entry['player']}: {entry['action']}")


def _cmd_simulate(args: argparse.Namespace) -> None:
    card_db = load_cards(args.cards)

    # Expand globs
    deck_paths: list[str] = []
    for pattern in args.decks:
        expanded = glob.glob(pattern)
        if expanded:
            deck_paths.extend(expanded)
        else:
            deck_paths.append(pattern)

    decks = [load_deck(p, card_db) for p in sorted(set(deck_paths))]
    print(f"Loaded {len(decks)} decks: {[d.deck_id for d in decks]}")

    logs = run_batch(card_db, decks, args.matches, args.seed, args.output, args.trace)
    stats = aggregate(logs)
    render_stats(stats)

    adoption = compute_card_adoption(decks)
    render_card_adoption(adoption, len(decks))

    print(f"Logs written to: {Path(args.output) / 'match_logs.json'}")


def _cmd_stats(args: argparse.Namespace) -> None:
    with open(args.logs, encoding="utf-8") as f:
        raw = json.load(f)

    # Reconstruct minimal MatchLog objects for aggregate()
    from card_battle.models import MatchLog
    logs = []
    for entry in raw:
        logs.append(MatchLog(
            seed=entry["seed"],
            deck_ids=tuple(entry["deck_ids"]),
            winner=GameResult(entry["winner"]),
            turns=entry["turns"],
            final_hp=tuple(entry["final_hp"]),
        ))

    stats = aggregate(logs)
    render_stats(stats)
