"""v0.6.1: Cycle runner — evolve → patterns → cardgen → promote loop."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _derive_cycle_seed(global_seed: int, cycle_index: int) -> int:
    """SHA-256 based deterministic seed for each cycle."""
    digest = hashlib.sha256(f"{global_seed}:{cycle_index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _pool_hash(pool_path: Path) -> str:
    """SHA-256 hex digest of a pool file."""
    data = pool_path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def _snapshot_pool(pool_path: Path, pools_dir: Path, index: int) -> Path:
    """Copy pool to pools/pool_NNN.json."""
    dest = pools_dir / f"pool_{index:03d}.json"
    shutil.copy2(pool_path, dest)
    return dest


# -------------------------------------------------------------------------
# Single cycle
# -------------------------------------------------------------------------

def _run_single_cycle(
    cycle_index: int,
    pool_path: Path,
    cycle_dir: Path,
    config: dict[str, Any],
    cycle_seed: int,
) -> dict[str, Any]:
    """Execute one evolve→patterns→cardgen→promote cycle.

    Returns a result dict (always, even on error).
    """
    from card_battle.cardgen import run_cardgen
    from card_battle.evolve import EvolutionConfig, EvolutionRunner
    from card_battle.patterns import extract_all_patterns
    from card_battle.promotion import IDConflictError, run_promotion

    paths = config["paths"]
    target_paths = paths["targets"]
    result: dict[str, Any] = {
        "cycle_index": cycle_index,
        "cycle_seed": cycle_seed,
        "gate_passed": False,
        "cards_added": 0,
        "exit_reason": "not_started",
        "patterns_count": 0,
        "cardgen_result": None,
        "new_pool_path": str(pool_path),
    }

    try:
        # --- 1. Evolve ---
        evolve_dir = cycle_dir / "evolve"
        evolve_cfg = EvolutionConfig.from_json(
            paths["evolve_config"],
            cards_path=str(pool_path),
            output_dir=str(evolve_dir),
            global_seed=cycle_seed,
        )
        # Force telemetry ON — patterns need match summaries
        evolve_cfg.telemetry["enabled"] = True
        evolve_cfg.telemetry["save_match_summaries"] = True

        runner = EvolutionRunner(evolve_cfg)
        runner.run()

        # --- 2. Patterns ---
        with open(paths["patterns_config"], encoding="utf-8") as f:
            patterns_cfg = json.load(f)

        patterns_out = cycle_dir / "patterns.json"
        patterns = extract_all_patterns(
            artifact_dir=evolve_dir,
            config=patterns_cfg,
            output_path=patterns_out,
        )
        result["patterns_count"] = len(patterns)

        # --- 3. Cardgen ---
        cardgen_dir = cycle_dir / "cardgen"
        cardgen_result = run_cardgen(
            patterns_path=patterns_out,
            pool_path=pool_path,
            target_paths=target_paths,
            constraints_path=paths["constraints"],
            config_path=paths["cardgen_config"],
            output_dir=cardgen_dir,
        )
        result["cardgen_result"] = cardgen_result

        # --- 4. Promote ---
        promote_dir = cycle_dir / "promote"
        selected_path = cardgen_dir / "selected_cards.json"

        # If no cards were selected, skip promotion
        if cardgen_result["total_selected"] == 0:
            result["exit_reason"] = "no_candidates_selected"
            return result

        try:
            promote_result = run_promotion(
                selected_path=selected_path,
                pool_path=pool_path,
                target_paths=target_paths,
                config_path=paths["promotion_config"],
                output_dir=promote_dir,
                seed_override=cycle_seed,
                on_conflict_override="skip",
            )
        except IDConflictError:
            result["exit_reason"] = "id_conflict"
            return result

        result["gate_passed"] = promote_result["gate_passed"]
        result["cards_added"] = promote_result["cards_added"]
        result["exit_reason"] = promote_result["exit_reason"]

        if promote_result["gate_passed"]:
            result["new_pool_path"] = str(promote_dir / "cards_after.json")

    except Exception as exc:
        result["exit_reason"] = f"error: {type(exc).__name__}: {exc}"

    return result


# -------------------------------------------------------------------------
# Replay capture
# -------------------------------------------------------------------------

def _capture_replays(
    cycle_dir: Path,
    pool_path: Path,
    target_paths: list[str | Path],
    cycle_seed: int,
    replay_config: dict[str, Any],
) -> list[str]:
    """Capture replay JSONL for top-K delta matchups."""
    from card_battle.ai import GreedyAI
    from card_battle.engine import init_game, run_game
    from card_battle.loader import load_cards, load_deck
    from card_battle.replay import ReplayWriter

    top_k = replay_config.get("top_k_matchups", 3)
    replays_dir = cycle_dir / "replays"
    replays_dir.mkdir(parents=True, exist_ok=True)

    # Read promotion report for delta
    report_path = cycle_dir / "promote" / "promotion_report.json"
    if not report_path.exists():
        return []

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    delta = report.get("delta", {})
    if not delta:
        return []

    # Sort by abs(delta), take top K
    ranked = sorted(delta.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_k]

    card_db = load_cards(pool_path)
    targets = {load_deck(p, card_db).deck_id: load_deck(p, card_db) for p in target_paths}

    replay_paths: list[str] = []
    for idx, (deck_id, _) in enumerate(ranked):
        if deck_id not in targets:
            continue

        target_deck = targets[deck_id]
        # Pick any two decks: the target vs itself (simplest valid matchup)
        # Use the target deck for both sides to demonstrate the matchup
        gs = init_game(card_db, target_deck, target_deck, cycle_seed + idx)

        replay_path = replays_dir / f"matchup_{idx}.jsonl"
        rw = ReplayWriter(replay_path)
        rw.write({
            "type": "meta",
            "seed": cycle_seed + idx,
            "deck_ids": [deck_id, deck_id],
        })
        run_game(gs, (GreedyAI(), GreedyAI()), replay=rw)
        rw.close()
        replay_paths.append(str(replay_path))

    return replay_paths


# -------------------------------------------------------------------------
# Main entry
# -------------------------------------------------------------------------

def run_cycle(
    config_path: str | Path,
    output_dir: str | Path,
    cycles_override: int | None = None,
    seed_override: int | None = None,
    replay_override: bool | None = None,
) -> dict[str, Any]:
    """Run full pipeline loop: evolve → patterns → cardgen → promote.

    Returns a summary dict with per-cycle results.
    """
    config_path = Path(config_path)
    output_dir = Path(output_dir)

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    # Apply overrides
    total_cycles = cycles_override if cycles_override is not None else config["cycles"]
    global_seed = seed_override if seed_override is not None else config["seed"]
    replay_enabled = replay_override if replay_override is not None else config.get("replay", {}).get("enabled", False)
    replay_config = config.get("replay", {})

    # Create directory structure
    pools_dir = output_dir / "pools"
    cycles_dir = output_dir / "cycles"
    pools_dir.mkdir(parents=True, exist_ok=True)
    cycles_dir.mkdir(parents=True, exist_ok=True)

    # Resolve pool path
    pool_path = Path(config["paths"]["pool"])
    target_paths = config["paths"]["targets"]

    # Initial pool snapshot
    current_pool = pool_path
    _snapshot_pool(current_pool, pools_dir, 0)

    t_start = time.monotonic()
    cycle_results: list[dict[str, Any]] = []
    gates_passed = 0
    gates_failed = 0
    total_cards_added = 0

    for i in range(total_cycles):
        cycle_seed = _derive_cycle_seed(global_seed, i)
        cycle_dir = cycles_dir / f"cycle_{i:03d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"Cycle {i}/{total_cycles}  seed={cycle_seed}")
        print(f"{'='*60}")

        result = _run_single_cycle(i, current_pool, cycle_dir, config, cycle_seed)
        cycle_results.append(result)

        if result["gate_passed"]:
            gates_passed += 1
            total_cards_added += result["cards_added"]
            current_pool = Path(result["new_pool_path"])
            _snapshot_pool(current_pool, pools_dir, i + 1)

            # Replay capture
            if replay_enabled:
                replay_paths = _capture_replays(
                    cycle_dir, current_pool, target_paths,
                    cycle_seed, replay_config,
                )
                result["replay_paths"] = replay_paths
        else:
            gates_failed += 1
            # Snapshot same pool (unchanged)
            _snapshot_pool(current_pool, pools_dir, i + 1)

    elapsed = round(time.monotonic() - t_start, 2)
    final_hash = _pool_hash(current_pool)

    # Write cycle summary
    cycle_summary = {
        "total_cycles": total_cycles,
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
        "total_cards_added": total_cards_added,
        "final_pool_hash": final_hash,
        "cycles": cycle_results,
    }
    _write_json(output_dir / "cycle_summary.json", cycle_summary)

    # Write run meta
    run_meta = {
        "version": config.get("version", "0.6.1"),
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "global_seed": global_seed,
        "total_cycles": total_cycles,
        "replay_enabled": replay_enabled,
        "elapsed_seconds": elapsed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(output_dir / "run_meta.json", run_meta)

    print(f"\nCycle run complete: {gates_passed} passed, {gates_failed} failed, "
          f"{total_cards_added} cards added in {elapsed}s")

    return {
        "total_cycles": total_cycles,
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
        "total_cards_added": total_cards_added,
        "final_pool_hash": final_hash,
        "elapsed_seconds": elapsed,
        "cycles": cycle_results,
    }
