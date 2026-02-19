"""Phase 9b: CLI entry point – play / simulate / stats subcommands."""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

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
    p_play.add_argument("--replay", choices=["on", "off"], default="off",
                        help="Enable replay JSONL output")
    p_play.add_argument("--replay-dir", default="output/replays",
                        help="Directory for replay files")

    # --- simulate ---
    p_sim = sub.add_parser("simulate", help="Run batch simulation")
    p_sim.add_argument("--decks", nargs="+", required=True, help="Deck JSON files (glob supported)")
    p_sim.add_argument("--matches", type=int, default=100, help="Matches per pair")
    p_sim.add_argument("--seed", type=int, default=42)
    p_sim.add_argument("--round-robin", action="store_true", default=True)
    p_sim.add_argument("--output", default="output/", help="Output directory")
    p_sim.add_argument("--trace", action="store_true", help="Include play traces in log")
    p_sim.add_argument("--cards", default=str(DEFAULT_CARDS), help="Path to cards.json")
    p_sim.add_argument("--telemetry", choices=["on", "off"], default="off",
                        help="Enable match telemetry collection")
    p_sim.add_argument("--replay", choices=["on", "off"], default="off",
                        help="Enable replay JSONL output")
    p_sim.add_argument("--replay-dir", default="output/replays",
                        help="Directory for replay files")
    p_sim.add_argument("--replay-sample-rate", type=float, default=1.0,
                        help="Fraction of matches to record replays for")

    # --- stats ---
    p_stats = sub.add_parser("stats", help="Show stats from match logs")
    p_stats.add_argument("--logs", required=True, help="Path to match_logs.json")

    # --- evolve ---
    p_evolve = sub.add_parser("evolve", help="Evolve decks via evolutionary search")
    p_evolve.add_argument("--config", required=True, help="Path to evolution config JSON")
    p_evolve.add_argument("--output", default=None, help="Override output directory")
    p_evolve.add_argument("--generations", type=int, default=None, help="Override generations count")
    p_evolve.add_argument("--seed", type=int, default=None, help="Override global seed")
    p_evolve.add_argument("--telemetry", choices=["on", "off"], default=None,
                          help="Override telemetry setting")
    p_evolve.add_argument("--candidate-policies", default=None,
                          help="name:weight,... (e.g. greedy:0.6,simple:0.3,random:0.1)")
    p_evolve.add_argument("--opponent-policies", default=None,
                          help="name:weight,... (e.g. greedy:0.7,simple:0.3)")

    # --- patterns ---
    p_pat = sub.add_parser("patterns", help="Extract tactical patterns from evolve artifacts")
    p_pat.add_argument("--input", required=True,
                       help="Path to evolve artifact dir or JSONL file")
    p_pat.add_argument("--config", required=True,
                       help="Path to pattern extraction config JSON")
    p_pat.add_argument("--output", default="patterns.json",
                       help="Output path for patterns.json")

    # --- cardgen ---
    p_cg = sub.add_parser("cardgen", help="Generate and test new card candidates")
    p_cg.add_argument("--patterns", required=True, help="Path to patterns.json")
    p_cg.add_argument("--pool", default=str(DEFAULT_CARDS), help="Path to card pool JSON")
    p_cg.add_argument("--targets", nargs="+", required=True,
                       help="Paths to target deck JSON files")
    p_cg.add_argument("--constraints", required=True,
                       help="Path to constraints JSON")
    p_cg.add_argument("--config", required=True, help="Path to generation config JSON")
    p_cg.add_argument("--output", default="output/cardgen", help="Output directory")
    p_cg.add_argument("--mutations", choices=["on", "off"], default=None,
                       help="Override mutations enabled setting")
    p_cg.add_argument("--mut-per-base", type=int, default=None,
                       help="Override mutations per base candidate")
    p_cg.add_argument("--min-distance", type=float, default=None,
                       help="Override diversity min distance")

    # --- promote ---
    p_promo = sub.add_parser("promote", help="Promote selected cards into the card pool")
    p_promo.add_argument("--selected", required=True,
                         help="Path to selected_cards.json")
    p_promo.add_argument("--pool", default=str(DEFAULT_CARDS),
                         help="Path to card pool JSON")
    p_promo.add_argument("--targets", nargs="+", required=True,
                         help="Paths to target deck JSON files")
    p_promo.add_argument("--config", required=True,
                         help="Path to promotion config JSON")
    p_promo.add_argument("--output", default="output/promotion",
                         help="Output directory")
    p_promo.add_argument("--max", type=int, default=None,
                         help="Override max promotions per run")
    p_promo.add_argument("--seed", type=int, default=None,
                         help="Override seed")
    conflict_group = p_promo.add_mutually_exclusive_group()
    conflict_group.add_argument("--fail-on-conflict", action="store_true",
                                help="Fail on ID conflict")
    conflict_group.add_argument("--skip-on-conflict", action="store_true",
                                help="Skip conflicting IDs")

    # --- replay ---
    p_replay = sub.add_parser("replay", help="View a JSONL replay file")
    p_replay.add_argument("file", help="Path to replay .jsonl")
    p_replay.add_argument("--compact", action="store_true",
                          help="Compact output (hide board details)")
    p_replay.add_argument("--from-turn", type=int, default=None,
                          help="Start displaying from this turn")
    p_replay.add_argument("--to-turn", type=int, default=None,
                          help="Stop displaying after this turn")

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
    elif args.command == "evolve":
        _cmd_evolve(args)
    elif args.command == "patterns":
        _cmd_patterns(args)
    elif args.command == "cardgen":
        _cmd_cardgen(args)
    elif args.command == "promote":
        _cmd_promote(args)
    elif args.command == "replay":
        _cmd_replay(args)


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

    rw = None
    if getattr(args, "replay", "off") == "on":
        from card_battle.replay import ReplayWriter
        replay_dir = Path(args.replay_dir)
        rw = ReplayWriter(replay_dir / f"{args.seed}.jsonl")
        rw.write({
            "type": "meta",
            "seed": args.seed,
            "deck_ids": [deck_a.deck_id, deck_b.deck_id],
        })

    log = run_game(gs, agents, trace=args.trace, replay=rw)

    if rw is not None:
        rw.close()
        print(f"Replay written to: {rw.path}")

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

    telemetry_on = getattr(args, "telemetry", "off") == "on"
    replay_on = getattr(args, "replay", "off") == "on"
    logs = run_batch(
        card_db, decks, args.matches, args.seed, args.output, args.trace,
        telemetry_enabled=telemetry_on,
        replay_enabled=replay_on,
        replay_dir=Path(args.replay_dir) if replay_on else None,
        replay_sample_rate=getattr(args, "replay_sample_rate", 1.0),
    )
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


def _parse_policy_arg(arg: str) -> list[dict[str, Any]]:
    """Parse 'greedy:0.6,simple:0.3' into [{"name": "greedy", "weight": 0.6}, ...]."""
    entries = []
    for part in arg.split(","):
        part = part.strip()
        if ":" in part:
            name, weight_str = part.split(":", 1)
            entries.append({"name": name.strip(), "weight": float(weight_str.strip())})
        else:
            entries.append({"name": part.strip(), "weight": 1.0})
    return entries


def _cmd_evolve(args: argparse.Namespace) -> None:
    from card_battle.evolve import EvolutionConfig, EvolutionRunner

    overrides: dict = {}
    if args.output is not None:
        overrides["output_dir"] = args.output
    if args.generations is not None:
        overrides["generations"] = args.generations
    if args.seed is not None:
        overrides["global_seed"] = args.seed

    config = EvolutionConfig.from_json(args.config, **overrides)

    # CLI --telemetry overrides config
    if args.telemetry is not None:
        config.telemetry["enabled"] = (args.telemetry == "on")

    # CLI --candidate-policies / --opponent-policies override config
    if args.candidate_policies or args.opponent_policies:
        policies = config.evaluation.get("policies", {})
        if args.candidate_policies:
            policies["candidates"] = _parse_policy_arg(args.candidate_policies)
        if args.opponent_policies:
            policies["opponents"] = _parse_policy_arg(args.opponent_policies)
        config.evaluation["policies"] = policies

    runner = EvolutionRunner(config)
    runner.run()


def _cmd_patterns(args: argparse.Namespace) -> None:
    from card_battle.patterns import extract_all_patterns

    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)

    input_path = Path(args.input)

    patterns = extract_all_patterns(
        artifact_dir=input_path,
        config=config,
        output_path=args.output,
    )

    # Count by type
    type_counts: dict[str, int] = {}
    for p in patterns:
        t = p["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"Extracted {len(patterns)} patterns:")
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")
    print(f"Written to: {args.output}")


def _cmd_cardgen(args: argparse.Namespace) -> None:
    from card_battle.cardgen import run_cardgen

    result = run_cardgen(
        patterns_path=args.patterns,
        pool_path=args.pool,
        target_paths=args.targets,
        constraints_path=args.constraints,
        config_path=args.config,
        output_dir=args.output,
        mutations_override=args.mutations,
        mut_per_base_override=args.mut_per_base,
        min_distance_override=args.min_distance,
    )
    print(f"\nCardgen complete: {result['total_candidates']} candidates, "
          f"{result['total_selected']} selected")
    print(f"Artifacts in: {args.output}")


def _cmd_promote(args: argparse.Namespace) -> None:
    from card_battle.promotion import run_promotion, IDConflictError

    on_conflict = None
    if args.fail_on_conflict:
        on_conflict = "fail"
    elif args.skip_on_conflict:
        on_conflict = "skip"

    try:
        result = run_promotion(
            selected_path=args.selected,
            pool_path=args.pool,
            target_paths=args.targets,
            config_path=args.config,
            output_dir=args.output,
            max_override=args.max,
            seed_override=args.seed,
            on_conflict_override=on_conflict,
        )
    except IDConflictError as e:
        print(f"ERROR: {e}")
        sys.exit(2)

    print(f"Report: {result['report_path']}")
    if not result["gate_passed"]:
        print(f"Gate FAILED: {result['exit_reason']}")
        sys.exit(3)


def _cmd_replay(args: argparse.Namespace) -> None:
    from card_battle.replay import render_replay
    render_replay(
        args.file,
        from_turn=args.from_turn,
        to_turn=args.to_turn,
        compact=args.compact,
    )
