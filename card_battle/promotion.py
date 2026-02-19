"""v0.7.1: Promotion pipeline — selected cards → card pool."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from card_battle.evaluation import (
    PolicyMix,
    evaluate_deck_vs_pool,
    evaluate_targets,
    telemetry_aggregate,
)
from card_battle.loader import load_cards, load_deck, validate_card
from card_battle.models import Card, DeckDef
from card_battle.mutation import counts_to_deck, deck_to_counts, validate_counts


class IDConflictError(Exception):
    """Raised when a candidate card ID already exists in the pool."""

    def __init__(self, card_id: str) -> None:
        self.card_id = card_id
        super().__init__(f"ID conflict: card '{card_id}' already exists in pool")


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _card_dict_to_pool_entry(candidate_card: dict[str, Any]) -> dict[str, Any]:
    """Convert an adoption-report candidate_card dict to cards.json format.

    Removes ``intent`` and ``gen_reason``; defaults ``rarity`` to ``"uncommon"``.
    """
    entry: dict[str, Any] = {}
    for key in ("id", "name", "cost", "card_type", "tags", "template", "params"):
        if key in candidate_card:
            entry[key] = candidate_card[key]
    entry.setdefault("rarity", candidate_card.get("rarity", "uncommon"))
    return entry


def _pool_hash(cards_list: list[dict[str, Any]]) -> str:
    """SHA-256 first 16 hex chars of the canonical JSON representation."""
    canonical = json.dumps(cards_list, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _list_to_card_db(cards_list: list[dict[str, Any]]) -> dict[str, Card]:
    """Convert a raw cards list to a validated Card dict (card_db)."""
    card_db: dict[str, Card] = {}
    for entry in cards_list:
        card = Card(
            id=entry["id"],
            name=entry["name"],
            cost=entry["cost"],
            card_type=entry["card_type"],
            tags=tuple(entry.get("tags", ())),
            template=entry["template"],
            params=entry.get("params", {}),
            rarity=entry.get("rarity", "common"),
        )
        validate_card(card)
        card_db[card.id] = card
    return card_db


def _write_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _card_value_score(card: Card) -> float:
    """Simple heuristic score for a card — used by adaptation to pick removal targets."""
    if card.is_unit:
        return card.params.get("atk", 0) + card.params.get("hp", 0)
    return card.params.get("amount", 0) + card.params.get("n", 0) * 2


def adapt_targets_for_after(
    targets: list[DeckDef],
    new_card_ids: list[str],
    card_db_after: dict[str, Card],
    seed: int,
    benchmark_config: dict[str, Any],
) -> tuple[list[DeckDef], list[dict[str, Any]]]:
    """Create adapted target decks that incorporate new cards.

    For each target deck, tries injecting each new card at count 1/2/3,
    removing same-cost-band cards with the lowest value score. Picks the
    best-performing variant via quick evaluation.

    Returns (adapted_targets, adaptation_log).
    """
    if not new_card_ids:
        return (targets, [])

    adaptation_log: list[dict[str, Any]] = []
    adapted_targets: list[DeckDef] = []

    for target in targets:
        # Build elite pool = other original targets (for quick eval)
        elite_pool = [t for t in targets if t.deck_id != target.deck_id]
        if not elite_pool:
            # Single target — cannot evaluate, keep original
            adapted_targets.append(target)
            continue

        # Derive a deterministic seed for this target's adaptation
        adapt_seed_bytes = hashlib.sha256(
            f"{seed}:{target.deck_id}:adapt".encode()
        ).digest()[:8]
        adapt_seed = int.from_bytes(adapt_seed_bytes, "big")

        base_counts = deck_to_counts(target)

        # Evaluate baseline
        baseline_wr = evaluate_deck_vs_pool(
            target, elite_pool, card_db_after,
            global_seed=adapt_seed, generation=999,
            matches_per_opponent=1,
        )
        if isinstance(baseline_wr, tuple):
            baseline_wr = baseline_wr[0]

        best_variant: DeckDef | None = None
        best_wr = baseline_wr
        best_info: dict[str, Any] = {}

        for new_card_id in new_card_ids:
            if new_card_id not in card_db_after:
                continue
            new_card = card_db_after[new_card_id]

            for k in (1, 2, 3):
                counts = dict(base_counts)

                # Find same-cost-band cards (±1) sorted by value score ascending
                removable = []
                for cid, cnt in counts.items():
                    if cid not in card_db_after:
                        continue
                    c = card_db_after[cid]
                    if abs(c.cost - new_card.cost) <= 1:
                        removable.append((cid, _card_value_score(c), cnt))
                removable.sort(key=lambda x: x[1])

                # Remove k copies from lowest-value cards in the cost band
                to_remove = k
                for cid, _score, cnt in removable:
                    if to_remove <= 0:
                        break
                    can_remove = min(to_remove, cnt)
                    counts[cid] -= can_remove
                    if counts[cid] == 0:
                        del counts[cid]
                    to_remove -= can_remove

                if to_remove > 0:
                    continue  # couldn't remove enough

                # Inject new card
                counts[new_card_id] = counts.get(new_card_id, 0) + k

                if not validate_counts(counts):
                    continue

                variant_id = f"{target.deck_id}__adapt_{new_card_id}_x{k}"
                try:
                    variant = counts_to_deck(variant_id, counts)
                except ValueError:
                    continue

                var_wr = evaluate_deck_vs_pool(
                    variant, elite_pool, card_db_after,
                    global_seed=adapt_seed, generation=999,
                    matches_per_opponent=1,
                )
                if isinstance(var_wr, tuple):
                    var_wr = var_wr[0]

                if var_wr > best_wr:
                    best_wr = var_wr
                    best_variant = variant
                    best_info = {
                        "new_card_id": new_card_id,
                        "count": k,
                        "win_rate": round(var_wr, 4),
                    }

        if best_variant is not None:
            adapted_targets.append(best_variant)
            adaptation_log.append({
                "original_deck_id": target.deck_id,
                "adapted_deck_id": best_variant.deck_id,
                "baseline_win_rate": round(baseline_wr, 4),
                **best_info,
            })
        else:
            adapted_targets.append(target)
            adaptation_log.append({
                "original_deck_id": target.deck_id,
                "adapted_deck_id": target.deck_id,
                "baseline_win_rate": round(baseline_wr, 4),
                "note": "no_improvement_found",
            })

    return (adapted_targets, adaptation_log)


# -------------------------------------------------------------------------
# Core pipeline functions
# -------------------------------------------------------------------------

def apply_promotion(
    cards_before_list: list[dict[str, Any]],
    selected_reports: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply selected cards to the pool.

    Returns (cards_after_list, patch).
    """
    max_promotions = config.get("max_promotions_per_run", 10)
    on_conflict = config.get("on_id_conflict", "fail")

    existing_ids = {c["id"] for c in cards_before_list}
    base_hash = _pool_hash(cards_before_list)

    cards_after_list = list(cards_before_list)  # shallow copy
    added: list[dict[str, Any]] = []
    skipped_conflicts: list[str] = []

    for report in selected_reports[:max_promotions]:
        candidate = report.get("candidate_card", {})
        cid = candidate.get("id", "")

        if cid in existing_ids:
            if on_conflict == "fail":
                raise IDConflictError(cid)
            # skip
            skipped_conflicts.append(cid)
            continue

        pool_entry = _card_dict_to_pool_entry(candidate)
        cards_after_list.append(pool_entry)
        added.append(pool_entry)
        existing_ids.add(cid)

    new_hash = _pool_hash(cards_after_list)
    patch = {
        "version": "0.5.1",
        "base_pool_hash": base_hash,
        "new_pool_hash": new_hash,
        "added": added,
        "updated": [],
        "removed": [],
        "skipped_conflicts": skipped_conflicts,
    }
    return cards_after_list, patch


def run_benchmark(
    card_db: dict[str, Card],
    targets: list[DeckDef],
    seed: int,
    benchmark_config: dict[str, Any],
) -> dict[str, Any]:
    """Run round-robin benchmark of targets.

    Returns {win_rates_by_target, overall_win_rate, telemetry_aggregate, summaries}.
    """
    matches_per_pair = benchmark_config.get("matches_per_pair", 2)
    policies = benchmark_config.get("policies")

    result = evaluate_targets(
        targets, card_db, seed, matches_per_pair,
        policy_mix=policies,
        collect_telemetry=True,
    )

    telem_agg = telemetry_aggregate(result["summaries"])

    return {
        "win_rates_by_target": result["win_rates_by_target"],
        "overall_win_rate": result["overall_win_rate"],
        "telemetry_aggregate": telem_agg,
        "summaries": result["summaries"],
    }


def compute_gate(
    before_result: dict[str, Any],
    after_result: dict[str, Any],
    gate_config: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate gate conditions on before/after benchmark results.

    Returns {passed, checks: {name: {passed, threshold, actual}}, reason}.
    """
    max_wr_threshold = gate_config.get("max_matchup_winrate", 0.95)
    turns_threshold = gate_config.get("turns_delta_ratio", 0.20)
    mana_threshold = gate_config.get("mana_wasted_delta_ratio", 0.20)

    checks: dict[str, dict[str, Any]] = {}

    # 1. max_matchup_winrate: after's max win rate must be <= threshold
    after_wrs = after_result.get("win_rates_by_target", {})
    max_after_wr = max(after_wrs.values()) if after_wrs else 0.0
    checks["max_matchup_winrate"] = {
        "passed": max_after_wr <= max_wr_threshold,
        "threshold": max_wr_threshold,
        "actual": round(max_after_wr, 4),
    }

    # 2. turns_delta_ratio
    before_turns = before_result.get("telemetry_aggregate", {}).get("avg_total_turns", 0)
    after_turns = after_result.get("telemetry_aggregate", {}).get("avg_total_turns", 0)
    if before_turns > 0:
        turns_ratio = abs(after_turns - before_turns) / before_turns
    else:
        turns_ratio = 0.0
    checks["turns_delta_ratio"] = {
        "passed": turns_ratio <= turns_threshold,
        "threshold": turns_threshold,
        "actual": round(turns_ratio, 4),
    }

    # 3. mana_wasted_delta_ratio
    before_mana_p0 = before_result.get("telemetry_aggregate", {}).get("avg_p0_mana_wasted", 0)
    before_mana_p1 = before_result.get("telemetry_aggregate", {}).get("avg_p1_mana_wasted", 0)
    after_mana_p0 = after_result.get("telemetry_aggregate", {}).get("avg_p0_mana_wasted", 0)
    after_mana_p1 = after_result.get("telemetry_aggregate", {}).get("avg_p1_mana_wasted", 0)
    before_mana_avg = (before_mana_p0 + before_mana_p1) / 2 if (before_mana_p0 + before_mana_p1) > 0 else 0
    after_mana_avg = (after_mana_p0 + after_mana_p1) / 2
    if before_mana_avg > 0:
        mana_ratio = abs(after_mana_avg - before_mana_avg) / before_mana_avg
    else:
        mana_ratio = 0.0
    checks["mana_wasted_delta_ratio"] = {
        "passed": mana_ratio <= mana_threshold,
        "threshold": mana_threshold,
        "actual": round(mana_ratio, 4),
    }

    all_passed = all(c["passed"] for c in checks.values())
    reasons = [name for name, c in checks.items() if not c["passed"]]
    reason = "all checks passed" if all_passed else f"failed: {', '.join(reasons)}"

    return {
        "passed": all_passed,
        "checks": checks,
        "reason": reason,
    }


# -------------------------------------------------------------------------
# Full pipeline
# -------------------------------------------------------------------------

def run_promotion(
    selected_path: str | Path,
    pool_path: str | Path,
    target_paths: list[str | Path],
    config_path: str | Path,
    output_dir: str | Path,
    max_override: int | None = None,
    seed_override: int | None = None,
    on_conflict_override: str | None = None,
) -> dict[str, Any]:
    """Run the full promotion pipeline.

    Returns {gate_passed, exit_reason, cards_added, report_path}.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load config + apply CLI overrides
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    if max_override is not None:
        config["max_promotions_per_run"] = max_override
    if seed_override is not None:
        config["seed"] = seed_override
    if on_conflict_override is not None:
        config["on_id_conflict"] = on_conflict_override

    seed = config.get("seed", 42)
    benchmark_config = config.get("benchmark", {})
    gate_config = config.get("gate", {})

    # 2. Load inputs
    with open(selected_path, encoding="utf-8") as f:
        selected_reports = json.load(f)
    with open(pool_path, encoding="utf-8") as f:
        cards_before_list = json.load(f)

    # 3. Apply promotion
    cards_after_list, patch = apply_promotion(cards_before_list, selected_reports, config)

    # 4. Write intermediate artifacts
    _write_json(output_dir / "cards_before.json", cards_before_list)
    _write_json(output_dir / "cards_after.json", cards_after_list)
    _write_json(output_dir / "promotion_patch.json", patch)

    # 5. Build card_db for before and after
    card_db_before = _list_to_card_db(cards_before_list)
    card_db_after = _list_to_card_db(cards_after_list)

    # 6. Load target decks (using before card_db — targets should not reference new cards)
    targets: list[DeckDef] = []
    for tp in target_paths:
        targets.append(load_deck(tp, card_db_before))

    # 7. Before benchmark (fixed targets, before card pool)
    print("Running before benchmark (fixed)...")
    before_fixed = run_benchmark(card_db_before, targets, seed, benchmark_config)

    # 7.5. Adapt targets for after card pool
    new_card_ids = [a["id"] for a in patch["added"]]
    adapted_targets, adaptation_log = adapt_targets_for_after(
        targets, new_card_ids, card_db_after, seed, benchmark_config,
    )

    # 8a. After benchmark (fixed targets, after card pool)
    print("Running after benchmark (fixed)...")
    after_fixed = run_benchmark(card_db_after, targets, seed, benchmark_config)

    # 8b. After benchmark (adapted targets, after card pool)
    print("Running after benchmark (adapted)...")
    after_adapted = run_benchmark(card_db_after, adapted_targets, seed, benchmark_config)

    # 9. Deltas
    delta_fixed: dict[str, Any] = {}
    for did in before_fixed["win_rates_by_target"]:
        b = before_fixed["win_rates_by_target"].get(did, 0.5)
        a = after_fixed["win_rates_by_target"].get(did, 0.5)
        delta_fixed[did] = round(a - b, 4)

    # For adapted delta, map adapted deck_ids back to original deck_ids
    delta_adapted: dict[str, Any] = {}
    after_adapted_normalized: dict[str, Any] = {
        "win_rates_by_target": {},
        "overall_win_rate": after_adapted["overall_win_rate"],
        "telemetry_aggregate": after_adapted["telemetry_aggregate"],
        "summaries": after_adapted["summaries"],
    }
    for adapted_did, wr in after_adapted["win_rates_by_target"].items():
        original_id = adapted_did.split("__adapt_")[0]
        after_adapted_normalized["win_rates_by_target"][original_id] = wr
        b = before_fixed["win_rates_by_target"].get(original_id, 0.5)
        delta_adapted[original_id] = round(wr - b, 4)

    # 10. Gate — benchmark_view selects which after data to use
    benchmark_view = gate_config.get("benchmark_view", "fixed")
    if benchmark_view == "adapted":
        gate_result = compute_gate(before_fixed, after_adapted_normalized, gate_config)
    else:
        gate_result = compute_gate(before_fixed, after_fixed, gate_config)
    gate_result["benchmark_view"] = benchmark_view

    # 11. Promotion report (new two-track schema)
    def _bench_summary(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "win_rates_by_target": result["win_rates_by_target"],
            "overall_win_rate": result["overall_win_rate"],
            "telemetry_aggregate": result["telemetry_aggregate"],
        }

    report = {
        "before": {
            "fixed": _bench_summary(before_fixed),
        },
        "after": {
            "fixed": _bench_summary(after_fixed),
            "adapted": _bench_summary(after_adapted_normalized),
        },
        "delta": {
            "fixed": delta_fixed,
            "adapted": delta_adapted,
        },
        "adaptation": adaptation_log,
        "gate": gate_result,
        "patch_summary": {
            "added": len(patch["added"]),
            "skipped_conflicts": patch["skipped_conflicts"],
        },
    }
    report_path = output_dir / "promotion_report.json"
    _write_json(report_path, report)

    # 12. Run meta
    run_meta = {
        "seed": seed,
        "selected_path": str(selected_path),
        "pool_path": str(pool_path),
        "target_paths": [str(p) for p in target_paths],
        "config_path": str(config_path),
        "cards_added": len(patch["added"]),
        "gate_passed": gate_result["passed"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(output_dir / "run_meta.json", run_meta)

    exit_reason = "gate_passed" if gate_result["passed"] else gate_result["reason"]
    print(f"Promotion complete: {len(patch['added'])} cards added, gate={'PASS' if gate_result['passed'] else 'FAIL'}")

    return {
        "gate_passed": gate_result["passed"],
        "exit_reason": exit_reason,
        "cards_added": len(patch["added"]),
        "report_path": str(report_path),
    }
