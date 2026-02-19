"""v0.5: Card generation — constrained search + adoption test."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from card_battle.evaluation import evaluate_deck_vs_pool, evaluate_targets, telemetry_aggregate
from card_battle.loader import load_cards, load_deck
from card_battle.models import Card, DeckDef, DeckEntry
from card_battle.mutation import DECK_SIZE, MAX_COPIES, deck_to_counts, counts_to_deck


# -------------------------------------------------------------------------
# Candidate card ID generation
# -------------------------------------------------------------------------

def _candidate_id(template: str, params: dict[str, Any], seed: int) -> str:
    """Generate a stable candidate card ID via SHA-256."""
    canonical = json.dumps(
        {"template": template, "params": params, "seed": seed},
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return "cand_" + digest[:8].hex()


# -------------------------------------------------------------------------
# Forbid checking
# -------------------------------------------------------------------------

def _check_forbid(
    template: str, cost: int, params: dict[str, Any],
    forbid_rules: list[dict[str, Any]],
) -> bool:
    """Return True if this card is forbidden (should be skipped)."""
    for rule in forbid_rules:
        if rule.get("template") != template:
            continue
        condition = rule.get("condition", "")
        if not condition:
            continue
        # Build evaluation namespace from params + cost
        ns = dict(params)
        ns["cost"] = cost
        try:
            if eval(condition, {"__builtins__": {}}, ns):  # noqa: S307
                return True
        except Exception:
            continue
    return False


# -------------------------------------------------------------------------
# Candidate generation
# -------------------------------------------------------------------------

def generate_candidates(
    patterns: list[dict[str, Any]],
    constraints: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate candidate cards from patterns + constraints.

    Returns a list of CandidateCard dicts.
    """
    seed = config.get("seed", 42)
    rng = random.Random(seed)

    top_per_type = config.get("top_patterns_per_type", {})
    k = config.get("candidates_per_pattern", 2)
    mode_weights = config.get("mode_weights", {"suppress": 0.7, "support": 0.3})
    suppress_templates = config.get("suppress_templates", [])
    support_templates = config.get("support_templates", [])
    max_cards = config.get("base_candidates_max", constraints.get("global", {}).get("max_new_cards", 50))
    forbid_rules = constraints.get("global", {}).get("forbid", [])
    template_specs = constraints.get("templates", {})

    # Select top patterns per type
    by_type: dict[str, list[dict[str, Any]]] = {}
    for p in patterns:
        t = p.get("type", "")
        by_type.setdefault(t, []).append(p)

    selected_patterns: list[dict[str, Any]] = []
    for ptype in ["counter", "sequence", "cooccurrence"]:
        pool = by_type.get(ptype, [])
        # Already sorted by -lift, -support from patterns.json
        n = top_per_type.get(ptype, 10)
        selected_patterns.extend(pool[:n])

    # Determine mode distribution
    modes = list(mode_weights.keys())
    weights = [mode_weights[m] for m in modes]

    # Generate candidates
    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()  # (template, params_canonical) for dedup

    for pat in selected_patterns:
        pat_type = pat.get("type", "")
        pat_id = pat.get("pattern_id", "")
        pat_def = pat.get("definition", {})
        pat_stats = pat.get("stats", {})

        for ci in range(k):
            if len(candidates) >= max_cards:
                break

            # Choose mode
            mode = rng.choices(modes, weights=weights, k=1)[0]

            # Choose template list
            if mode == "suppress":
                tmpl_pool = suppress_templates
            else:
                tmpl_pool = support_templates

            if not tmpl_pool:
                continue

            tmpl_name = rng.choice(tmpl_pool)
            spec = template_specs.get(tmpl_name)
            if spec is None:
                continue

            # Generate params
            card_type = spec.get("card_type", "spell")
            cost_lo, cost_hi = spec.get("cost_range", [1, 5])
            cost = rng.randint(cost_lo, cost_hi)
            tags = tuple(spec.get("tags", []))

            params: dict[str, Any] = {}
            for pname, (plo, phi) in spec.get("params_ranges", {}).items():
                params[pname] = rng.randint(plo, phi)

            # Forbid check
            if _check_forbid(tmpl_name, cost, params, forbid_rules):
                continue

            # Dedup
            dedup_key = json.dumps(
                {"template": tmpl_name, "params": params, "cost": cost},
                sort_keys=True,
            )
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            cid = _candidate_id(tmpl_name, params, seed + ci + hash(pat_id))

            # Target info
            target_deck_ids = []
            if pat_type == "counter":
                tid = pat_def.get("target_deck_id")
                if tid:
                    target_deck_ids = [tid]

            candidate = {
                "id": cid,
                "name": f"cand_{tmpl_name.lower()}_{cid[-6:]}",
                "cost": cost,
                "card_type": card_type,
                "template": tmpl_name,
                "params": params,
                "tags": list(tags),
                "intent": {
                    "mode": mode,
                    "target_pattern_ids": [pat_id],
                    "target_deck_ids": target_deck_ids,
                },
                "gen_reason": {
                    "source_patterns": [{
                        "type": pat_type,
                        "lift": pat_stats.get("lift", 0),
                        "support": pat_stats.get("support", 0),
                    }],
                    "heuristic": f"{mode}_{tmpl_name.lower()}_from_{pat_type}",
                },
                "lineage": {
                    "origin": "base",
                    "parent_id": None,
                    "mutation_op": None,
                    "mutation_params": None,
                },
            }
            candidates.append(candidate)

        if len(candidates) >= max_cards:
            break

    return candidates


# -------------------------------------------------------------------------
# Deck variant building
# -------------------------------------------------------------------------

def build_deck_variants(
    deck: DeckDef,
    candidate_id: str,
    card_db: dict[str, Card],
    max_copies: int = 3,
) -> list[DeckDef]:
    """Build deck variants with 1..max_copies of the candidate card inserted.

    Replacement strategy:
    1. Same-template cards replaced first
    2. Then same-cost (±1) cards with highest count
    3. Then any card with highest count

    Returns list of valid DeckDef variants (may be empty if no valid variant).
    """
    counts = deck_to_counts(deck)
    card_ids_in_deck = sorted(counts.keys())

    # Build replacement priority list
    cand_card = card_db.get(candidate_id)
    if cand_card is None:
        return []

    def _replacement_priority(cid: str) -> tuple[int, int, str]:
        """Lower = replaced first. (template_match, cost_distance, card_id)"""
        c = card_db.get(cid)
        if c is None:
            return (1, 99, cid)
        tmpl_match = 0 if c.template == cand_card.template else 1
        cost_dist = abs(c.cost - cand_card.cost)
        return (tmpl_match, cost_dist, cid)

    replaceable = sorted(card_ids_in_deck, key=_replacement_priority)

    variants: list[DeckDef] = []
    for n_copies in range(1, max_copies + 1):
        trial = dict(counts)
        removed = 0
        for rid in replaceable:
            if removed >= n_copies:
                break
            if rid == candidate_id:
                continue
            can_remove = min(trial.get(rid, 0), n_copies - removed)
            if can_remove > 0:
                trial[rid] -= can_remove
                if trial[rid] == 0:
                    del trial[rid]
                removed += can_remove

        if removed < n_copies:
            break  # Can't fit more copies

        trial[candidate_id] = trial.get(candidate_id, 0) + n_copies

        # Validate
        total = sum(trial.values())
        if total != DECK_SIZE:
            break
        if any(c < 1 or c > MAX_COPIES for c in trial.values()):
            break

        try:
            variant = counts_to_deck(
                f"{deck.deck_id}+{candidate_id}x{n_copies}", trial,
            )
            variants.append(variant)
        except ValueError:
            break

    return variants


# -------------------------------------------------------------------------
# Adoption test
# -------------------------------------------------------------------------

def _evaluate_targets(
    targets: list[DeckDef],
    card_db: dict[str, Card],
    seed: int,
    matches_per_eval: int,
    policy_mix: dict[str, Any] | None,
    collect_telemetry: bool = True,
) -> dict[str, Any]:
    """Evaluate all target decks against each other. Returns summary."""
    return evaluate_targets(
        targets, card_db, seed, matches_per_eval, policy_mix,
        collect_telemetry=collect_telemetry,
    )


def _telemetry_aggregate(summaries: list[dict[str, Any]]) -> dict[str, float]:
    """Simple aggregate of key telemetry fields."""
    return telemetry_aggregate(summaries)


def adoption_test_one(
    candidate: dict[str, Any],
    targets: list[DeckDef],
    card_db: dict[str, Card],
    config: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    """Run adoption test for a single candidate card.

    Returns a report dict with before/after/delta.
    """
    adoption_cfg = config.get("adoption", {})
    matches_per_eval = adoption_cfg.get("matches_per_eval", 1)
    policy_mix = adoption_cfg.get("policy_mix")
    max_copies = adoption_cfg.get("max_copies_to_test", 3)

    # Create the Card object for the candidate
    cand = candidate
    cand_card = Card(
        id=cand["id"],
        name=cand["name"],
        cost=cand["cost"],
        card_type=cand["card_type"],
        tags=tuple(cand.get("tags", [])),
        template=cand["template"],
        params=cand["params"],
        rarity="uncommon",
    )

    # Before: evaluate with original card_db
    before = _evaluate_targets(
        targets, card_db, seed, matches_per_eval, policy_mix,
    )

    # After: add candidate to card_db, build variants, evaluate
    card_db_after = dict(card_db)
    card_db_after[cand_card.id] = cand_card

    # Build best variant for each target deck
    after_targets: list[DeckDef] = []
    for deck in targets:
        variants = build_deck_variants(deck, cand_card.id, card_db_after, max_copies)
        if not variants:
            after_targets.append(deck)
            continue

        # Pick the variant with best win_rate (greedy stage search)
        best_variant = deck
        best_wr = before["win_rates_by_target"].get(deck.deck_id, 0.5)
        opponents = [d for d in targets if d.deck_id != deck.deck_id]

        for variant in variants:
            if not opponents:
                break
            wr = evaluate_deck_vs_pool(
                variant, opponents, card_db_after, seed, 0, matches_per_eval,
                policy_mix=policy_mix,
            )
            if isinstance(wr, tuple):
                wr = wr[0]
            if wr > best_wr:
                best_wr = wr
                best_variant = variant

        after_targets.append(best_variant)

    after = _evaluate_targets(
        after_targets, card_db_after, seed, matches_per_eval, policy_mix,
    )

    # Compute delta
    before_overall = before["overall_win_rate"]
    after_overall = after["overall_win_rate"]
    delta_overall = after_overall - before_overall

    by_target_delta: dict[str, float] = {}
    for did in before["win_rates_by_target"]:
        b = before["win_rates_by_target"].get(did, 0.5)
        # Find matching after deck (may have been renamed)
        a_wr = 0.5
        for ad in after_targets:
            if ad.deck_id.startswith(did):
                a_wr = after["win_rates_by_target"].get(ad.deck_id, 0.5)
                break
        by_target_delta[did] = a_wr - b

    before_telem = _telemetry_aggregate(before["summaries"])
    after_telem = _telemetry_aggregate(after["summaries"])
    telemetry_delta: dict[str, float] = {}
    for k in before_telem:
        telemetry_delta[k] = round(after_telem.get(k, 0) - before_telem.get(k, 0), 4)

    return {
        "candidate_card": candidate,
        "before": {
            "win_rates_by_target": before["win_rates_by_target"],
            "overall_win_rate": before_overall,
            "telemetry_aggregate": before_telem,
        },
        "after": {
            "win_rates_by_target": after["win_rates_by_target"],
            "overall_win_rate": after_overall,
            "telemetry_aggregate": after_telem,
        },
        "delta": {
            "overall_win_rate_delta": round(delta_overall, 4),
            "by_target_delta": by_target_delta,
            "telemetry_delta": telemetry_delta,
        },
    }


def check_acceptance(
    report: dict[str, Any],
    config: dict[str, Any],
) -> bool:
    """Check if a candidate meets acceptance criteria."""
    acc = config.get("adoption", {}).get("acceptance", {})
    delta = report.get("delta", {})
    after = report.get("after", {})

    min_delta = acc.get("min_overall_delta", 0.02)
    max_wr = acc.get("max_win_rate", 0.95)
    max_turns_pct = acc.get("max_turns_delta_pct", 0.20)

    # Overall delta check
    if delta.get("overall_win_rate_delta", 0) < min_delta:
        return False

    # No extreme win rate
    for wr in after.get("win_rates_by_target", {}).values():
        if wr > max_wr:
            return False

    # Turns delta check
    before_telem = report.get("before", {}).get("telemetry_aggregate", {})
    telem_delta = delta.get("telemetry_delta", {})
    avg_turns_before = before_telem.get("avg_total_turns", 0)
    if avg_turns_before > 0:
        turns_change = abs(telem_delta.get("avg_total_turns", 0))
        if turns_change / avg_turns_before > max_turns_pct:
            return False

    return True


# -------------------------------------------------------------------------
# Full pipeline
# -------------------------------------------------------------------------

def run_cardgen(
    patterns_path: str | Path,
    pool_path: str | Path,
    target_paths: list[str | Path],
    constraints_path: str | Path,
    config_path: str | Path,
    output_dir: str | Path,
    mutations_override: str | None = None,
    mut_per_base_override: int | None = None,
    min_distance_override: float | None = None,
) -> dict[str, Any]:
    """Run the full card generation pipeline.

    Returns a summary dict with counts.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load inputs
    with open(patterns_path, encoding="utf-8") as f:
        patterns_data = json.load(f)
    patterns = patterns_data.get("patterns", [])

    card_db = load_cards(pool_path)

    targets: list[DeckDef] = []
    for tp in target_paths:
        targets.append(load_deck(tp, card_db))

    with open(constraints_path, encoding="utf-8") as f:
        constraints = json.load(f)

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    # Apply CLI overrides
    if mutations_override is not None:
        config.setdefault("mutations", {})["enabled"] = (mutations_override == "on")
    if mut_per_base_override is not None:
        config.setdefault("mutations", {})["per_base"] = mut_per_base_override
    if min_distance_override is not None:
        config.setdefault("diversity", {})["min_distance"] = min_distance_override

    seed = config.get("seed", 42)

    # 1. Generate base candidates
    candidates = generate_candidates(patterns, constraints, config)
    base_count = len(candidates)
    print(f"Generated {base_count} base candidate cards")

    # 2. Mutation stage
    total_mutated = 0
    mut_cfg = config.get("mutations", {})
    if mut_cfg.get("enabled", False):
        from card_battle.cardmut import generate_mutations, dedupe_and_filter_diversity

        mutated = generate_mutations(candidates, constraints, config)
        total_mutated = len(mutated)
        candidates = candidates + mutated
        print(f"  + {total_mutated} mutated candidates ({len(candidates)} total)")

        # 3. Diversity filter
        div_cfg = config.get("diversity", {})
        if div_cfg.get("enabled", False):
            candidates = dedupe_and_filter_diversity(candidates, constraints, config)
            print(f"  After diversity filter: {len(candidates)} candidates")

    total_after_diversity = len(candidates)
    _write_json(output_dir / "card_candidates.json", candidates)

    # 4. Adoption test
    reports: list[dict[str, Any]] = []
    for i, cand in enumerate(candidates):
        print(f"  Testing candidate {i+1}/{len(candidates)}: {cand['id']}")
        report = adoption_test_one(cand, targets, card_db, config, seed)
        reports.append(report)

    _write_json(output_dir / "adoption_report.json", reports)

    # 5. Select accepted cards
    selected = []
    for report in reports:
        if check_acceptance(report, config):
            selected.append(report)

    # Sort by delta descending, take top N
    top_n = config.get("adoption", {}).get("selected_top_n", 10)
    selected.sort(
        key=lambda r: r["delta"]["overall_win_rate_delta"],
        reverse=True,
    )
    selected = selected[:top_n]

    _write_json(output_dir / "selected_cards.json", selected)
    print(f"Selected {len(selected)} cards (from {len(reports)} candidates)")

    # 6. Run meta
    run_meta = {
        "seed": seed,
        "patterns_path": str(patterns_path),
        "pool_path": str(pool_path),
        "target_paths": [str(p) for p in target_paths],
        "constraints_path": str(constraints_path),
        "config_path": str(config_path),
        "total_candidates": len(candidates),
        "total_base": base_count,
        "total_mutated": total_mutated,
        "total_after_diversity": total_after_diversity,
        "total_selected": len(selected),
    }
    _write_json(output_dir / "run_meta.json", run_meta)

    return {
        "total_candidates": len(candidates),
        "total_base": base_count,
        "total_mutated": total_mutated,
        "total_after_diversity": total_after_diversity,
        "total_reports": len(reports),
        "total_selected": len(selected),
    }


def _write_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
