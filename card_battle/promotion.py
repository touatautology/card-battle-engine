"""v0.5.1: Promotion pipeline — selected cards → card pool."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from card_battle.evaluation import PolicyMix, evaluate_targets, telemetry_aggregate
from card_battle.loader import load_cards, load_deck, validate_card
from card_battle.models import Card, DeckDef


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

    # 7. Before benchmark
    print("Running before benchmark...")
    before_result = run_benchmark(card_db_before, targets, seed, benchmark_config)

    # 8. After benchmark
    print("Running after benchmark...")
    after_result = run_benchmark(card_db_after, targets, seed, benchmark_config)

    # 9. Delta
    delta: dict[str, Any] = {}
    for did in before_result["win_rates_by_target"]:
        b = before_result["win_rates_by_target"].get(did, 0.5)
        a = after_result["win_rates_by_target"].get(did, 0.5)
        delta[did] = round(a - b, 4)

    # 10. Gate
    gate_result = compute_gate(before_result, after_result, gate_config)

    # 11. Promotion report
    report = {
        "before": {
            "win_rates_by_target": before_result["win_rates_by_target"],
            "overall_win_rate": before_result["overall_win_rate"],
            "telemetry_aggregate": before_result["telemetry_aggregate"],
        },
        "after": {
            "win_rates_by_target": after_result["win_rates_by_target"],
            "overall_win_rate": after_result["overall_win_rate"],
            "telemetry_aggregate": after_result["telemetry_aggregate"],
        },
        "delta": delta,
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
