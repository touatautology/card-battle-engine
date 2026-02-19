"""v0.4: Tactical pattern extraction from match telemetry."""

from __future__ import annotations

import hashlib
import json
import sys
import warnings
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Iterator


# -------------------------------------------------------------------------
# Data model
# -------------------------------------------------------------------------

def _pattern_id(pattern_type: str, definition: dict[str, Any]) -> str:
    """Generate a stable pattern ID from type + normalized definition."""
    canonical = json.dumps(
        {"type": pattern_type, "definition": definition},
        sort_keys=True, ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return digest[:12].hex()


def _make_pattern(
    pattern_type: str,
    scope: str,
    definition: dict[str, Any],
    support: int,
    win_rate: float,
    lift: float,
    avg_turns: float = 0.0,
    example_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "pattern_id": _pattern_id(pattern_type, definition),
        "type": pattern_type,
        "scope": scope,
        "definition": definition,
        "stats": {
            "support": support,
            "win_rate": round(win_rate, 4),
            "lift": round(lift, 4),
            "avg_turns": round(avg_turns, 4),
        },
        "examples": {
            "match_ids": (example_ids or [])[:5],
        },
    }


# -------------------------------------------------------------------------
# I/O
# -------------------------------------------------------------------------

def load_match_summaries(path: str | Path) -> Iterator[dict[str, Any]]:
    """Load match summaries from a JSONL file (streaming)."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_all_summaries_from_dir(artifact_dir: str | Path) -> list[dict[str, Any]]:
    """Load all gen_NNN_summaries.jsonl from an evolve artifact directory."""
    artifact_dir = Path(artifact_dir)
    summaries: list[dict[str, Any]] = []
    for jsonl_path in sorted(artifact_dir.glob("gen_*_summaries.jsonl")):
        for s in load_match_summaries(jsonl_path):
            summaries.append(s)
    return summaries


def write_patterns(
    patterns: list[dict[str, Any]],
    output_path: str | Path,
    meta: dict[str, Any],
) -> None:
    """Write pattern dictionary to JSON."""
    # Stable sort: (-lift, -support, pattern_id)
    sorted_patterns = sorted(
        patterns,
        key=lambda p: (
            -p["stats"]["lift"],
            -p["stats"]["support"],
            p["pattern_id"],
        ),
    )
    data = {
        "meta": meta,
        "patterns": sorted_patterns,
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# -------------------------------------------------------------------------
# Deck card extraction helpers
# -------------------------------------------------------------------------

def _deck_card_set(deck_data: dict[str, Any]) -> set[str]:
    """Extract the set of card IDs from a deck data dict."""
    return {e["card_id"] for e in deck_data.get("entries", [])}


def _load_decks_from_populations(
    artifact_dir: Path,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Load top-N decks from each generation's population.json."""
    decks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for pop_path in sorted(artifact_dir.glob("gen_*/population.json")):
        with open(pop_path, encoding="utf-8") as f:
            pop = json.load(f)
        ranked = sorted(pop, key=lambda d: d.get("fitness", 0), reverse=True)
        for d in ranked[:top_n]:
            if d["deck_id"] not in seen_ids:
                seen_ids.add(d["deck_id"])
                decks.append(d)
    return decks


# -------------------------------------------------------------------------
# Pattern 1: Cooccurrence
# -------------------------------------------------------------------------

def extract_cooccurrence(
    decks: list[dict[str, Any]],
    config: dict[str, Any],
    summaries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Extract frequent card co-occurrence patterns from top decks.

    Args:
        decks: List of deck dicts with "deck_id", "entries", "fitness".
        config: Pattern config with "min_support", "max_itemset_size".
        summaries: Optional match summaries for win_rate calculation.
    """
    min_support = config.get("min_support", 3)
    max_size = config.get("max_itemset_size", 3)

    # Build card sets per deck
    deck_cards: list[tuple[str, set[str], float]] = []
    for d in decks:
        cards = _deck_card_set(d)
        fitness = d.get("fitness", 0.5)
        deck_cards.append((d["deck_id"], cards, fitness))

    if not deck_cards:
        return []

    # Base win rate (average fitness across all decks)
    all_fitness = [f for _, _, f in deck_cards]
    base_wr = sum(all_fitness) / len(all_fitness) if all_fitness else 0.5

    # Build deck_id -> match_ids mapping if summaries provided
    deck_match_ids: dict[str, list[str]] = defaultdict(list)
    if summaries:
        for s in summaries:
            did = s.get("deck_id", "")
            mid = s.get("match_id", "")
            if did and mid:
                deck_match_ids[did].append(mid)

    patterns: list[dict[str, Any]] = []
    for size in range(2, max_size + 1):
        # Collect all card_id combos of this size
        combo_stats: dict[tuple[str, ...], list[tuple[str, float]]] = defaultdict(list)
        for deck_id, cards, fitness in deck_cards:
            for combo in combinations(sorted(cards), size):
                combo_stats[combo].append((deck_id, fitness))

        for combo, deck_list in combo_stats.items():
            support = len(deck_list)
            if support < min_support:
                continue
            avg_fitness = sum(f for _, f in deck_list) / len(deck_list)
            lift = avg_fitness / base_wr if base_wr > 0 else 1.0

            # Collect example match_ids
            example_ids: list[str] = []
            for did, _ in deck_list[:5]:
                if did in deck_match_ids:
                    example_ids.extend(deck_match_ids[did][:2])
            example_ids = example_ids[:5]

            patterns.append(_make_pattern(
                pattern_type="cooccurrence",
                scope="deck",
                definition={"cards": list(combo)},
                support=support,
                win_rate=avg_fitness,
                lift=lift,
                example_ids=example_ids,
            ))

    return patterns


# -------------------------------------------------------------------------
# Pattern 2: Sequence
# -------------------------------------------------------------------------

def extract_sequences(
    summaries: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract early-game sequence patterns from turn_trace data.

    Requires turn_trace in summaries. Returns empty list if not available.
    """
    seq_config = config.get("sequence", {})
    max_turns = seq_config.get("turns", 3)
    min_support = seq_config.get("min_support", 5)

    # Check if any summary has turn_trace
    has_trace = any("turn_trace" in s for s in summaries)
    if not has_trace:
        warnings.warn(
            "No turn_trace found in summaries; skipping sequence extraction.",
            stacklevel=2,
        )
        return []

    # Extract early-game sequences per match
    # Key: tuple of tokens representing the sequence
    seq_stats: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for s in summaries:
        trace = s.get("turn_trace")
        if not trace:
            continue

        # Take the first max_turns turns for the candidate deck's player
        deck_id = s.get("deck_id", "")
        swapped = s.get("swapped", False)
        cand_player = 1 if swapped else 0

        # Filter turns for the candidate player, limited to early turns
        cand_turns = [
            t for t in trace
            if t.get("player") == cand_player and t.get("turn", 999) <= max_turns
        ]

        if not cand_turns:
            continue

        # Build a canonical sequence token
        tokens: list[dict[str, Any]] = []
        for t in cand_turns:
            tokens.append({
                "played": t.get("played", []),
                "atk": t.get("atk", 0),
                "blk": t.get("blk", 0),
            })

        seq_key = json.dumps(tokens, sort_keys=True)
        seq_stats[seq_key].append(s)

    patterns: list[dict[str, Any]] = []
    for seq_key, matches in seq_stats.items():
        support = len(matches)
        if support < min_support:
            continue

        tokens = json.loads(seq_key)

        # Win rate: how often the candidate deck won
        wins = 0
        total_turns_sum = 0.0
        for s in matches:
            swapped = s.get("swapped", False)
            winner = s.get("winner", "")
            if swapped and winner == "player_1_win":
                wins += 1
            elif not swapped and winner == "player_0_win":
                wins += 1
            total_turns_sum += s.get("total_turns", 0)

        wr = wins / support if support > 0 else 0.5
        avg_turns = total_turns_sum / support if support > 0 else 0.0

        # Base win rate across all summaries
        all_wins = 0
        for s in summaries:
            swp = s.get("swapped", False)
            w = s.get("winner", "")
            if swp and w == "player_1_win":
                all_wins += 1
            elif not swp and w == "player_0_win":
                all_wins += 1
        base_wr = all_wins / len(summaries) if summaries else 0.5
        lift = wr / base_wr if base_wr > 0 else 1.0

        example_ids = [s.get("match_id", "") for s in matches[:5]]

        patterns.append(_make_pattern(
            pattern_type="sequence",
            scope="matchup",
            definition={"turns": max_turns, "tokens": tokens},
            support=support,
            win_rate=wr,
            lift=lift,
            avg_turns=avg_turns,
            example_ids=example_ids,
        ))

    return patterns


# -------------------------------------------------------------------------
# Pattern 3: Counter
# -------------------------------------------------------------------------

def extract_counters(
    summaries: list[dict[str, Any]],
    decks: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract counter-strategy patterns: card sets effective against targets.

    Args:
        summaries: Match summaries with deck_id, opponent_id, winner, swapped.
        decks: Deck dicts with "deck_id", "entries".
        config: Pattern config with "counter.targets", "counter.min_lift".
    """
    counter_config = config.get("counter", {})
    targets = counter_config.get("targets", [])
    min_lift = counter_config.get("min_lift", 1.05)
    min_support = config.get("min_support", 3)

    if not targets:
        return []

    # Build deck_id -> card set mapping
    deck_card_map: dict[str, set[str]] = {}
    for d in decks:
        deck_card_map[d["deck_id"]] = _deck_card_set(d)

    patterns: list[dict[str, Any]] = []

    for target in targets:
        # Find all matches where opponent_id matches target
        target_matches: list[dict[str, Any]] = []
        for s in summaries:
            if s.get("opponent_id") == target:
                target_matches.append(s)

        if not target_matches:
            continue

        # Base win rate against this target
        base_wins = 0
        for s in target_matches:
            swapped = s.get("swapped", False)
            winner = s.get("winner", "")
            if swapped and winner == "player_1_win":
                base_wins += 1
            elif not swapped and winner == "player_0_win":
                base_wins += 1
        base_wr = base_wins / len(target_matches) if target_matches else 0.5

        # Collect all card IDs appearing in candidate decks that faced this target
        all_cards: set[str] = set()
        for s in target_matches:
            did = s.get("deck_id", "")
            if did in deck_card_map:
                all_cards.update(deck_card_map[did])

        # Test size-1 and size-2 card sets
        for size in range(1, 3):
            for combo in combinations(sorted(all_cards), size):
                combo_set = set(combo)
                # Matches where the candidate deck contains this combo
                matching: list[dict[str, Any]] = []
                for s in target_matches:
                    did = s.get("deck_id", "")
                    if did in deck_card_map and combo_set <= deck_card_map[did]:
                        matching.append(s)

                support = len(matching)
                if support < min_support:
                    continue

                wins = 0
                total_turns_sum = 0.0
                for s in matching:
                    swapped = s.get("swapped", False)
                    winner = s.get("winner", "")
                    if swapped and winner == "player_1_win":
                        wins += 1
                    elif not swapped and winner == "player_0_win":
                        wins += 1
                    total_turns_sum += s.get("total_turns", 0)

                wr = wins / support
                lift = wr / base_wr if base_wr > 0 else 1.0
                if lift < min_lift:
                    continue

                avg_turns = total_turns_sum / support
                example_ids = [s.get("match_id", "") for s in matching[:5]]

                patterns.append(_make_pattern(
                    pattern_type="counter",
                    scope="matchup",
                    definition={
                        "target_deck_id": target,
                        "cards": list(combo),
                    },
                    support=support,
                    win_rate=wr,
                    lift=lift,
                    avg_turns=avg_turns,
                    example_ids=example_ids,
                ))

    return patterns


# -------------------------------------------------------------------------
# Top-level extraction
# -------------------------------------------------------------------------

def extract_all_patterns(
    artifact_dir: str | Path,
    config: dict[str, Any],
    meta: dict[str, Any] | None = None,
    output_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Run all pattern extractors against an evolve artifact directory.

    Returns the list of extracted patterns.
    """
    artifact_dir = Path(artifact_dir)
    top_n = config.get("top_n_decks", 10)

    # Load data
    summaries = load_all_summaries_from_dir(artifact_dir)
    decks = _load_decks_from_populations(artifact_dir, top_n=top_n)

    all_patterns: list[dict[str, Any]] = []

    # 1. Cooccurrence
    all_patterns.extend(
        extract_cooccurrence(decks, config, summaries=summaries)
    )

    # 2. Sequences
    all_patterns.extend(
        extract_sequences(summaries, config)
    )

    # 3. Counters
    all_patterns.extend(
        extract_counters(summaries, decks, config)
    )

    # Write output if path given
    if output_path is not None:
        if meta is None:
            meta = {}
        final_meta = {
            "version": "0.4",
            "source_run_id": str(artifact_dir.name),
            "seed": config.get("seed"),
            **meta,
        }
        write_patterns(all_patterns, output_path, final_meta)

    return all_patterns
