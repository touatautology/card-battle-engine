"""v0.6: Card mutation operators + diversity filter."""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from card_battle.cardgen import _candidate_id, _check_forbid

# -------------------------------------------------------------------------
# Template families
# -------------------------------------------------------------------------

TEMPLATE_FAMILIES: dict[str, list[str]] = {
    "draw": ["Draw", "OnPlayDraw"],
    "damage": ["DamagePlayer", "OnPlayDamagePlayer"],
}


def _family_of(template: str) -> str | None:
    """Return family name or None if singleton."""
    for family, members in TEMPLATE_FAMILIES.items():
        if template in members:
            return family
    return None


def _swap_targets(template: str) -> list[str]:
    """Return list of templates in same family (excluding self)."""
    family = _family_of(template)
    if family is None:
        return []
    return [t for t in TEMPLATE_FAMILIES[family] if t != template]


# -------------------------------------------------------------------------
# Mutation seed
# -------------------------------------------------------------------------

def _mutation_seed(global_seed: int, parent_id: str, op: str, index: int) -> int:
    """Deterministic seed derived from parent + op + index via SHA-256."""
    data = json.dumps(
        {"seed": global_seed, "parent": parent_id, "op": op, "idx": index},
        sort_keys=True,
    )
    return int(hashlib.sha256(data.encode()).hexdigest()[:8], 16)


# -------------------------------------------------------------------------
# Mutation operators
# -------------------------------------------------------------------------

def _op_param_jitter(
    parent: dict[str, Any],
    constraints: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any] | None:
    """Jitter a random numeric param by +/-1, clamped to params_ranges."""
    template = parent["template"]
    spec = constraints.get("templates", {}).get(template)
    if spec is None:
        return None
    params_ranges = spec.get("params_ranges", {})
    if not params_ranges:
        return None

    params = dict(parent["params"])
    keys = sorted(params_ranges.keys())
    key = rng.choice(keys)
    delta = rng.choice([-1, 1])
    new_val = params.get(key, 0) + delta

    lo, hi = params_ranges[key]
    new_val = max(lo, min(hi, new_val))
    params[key] = new_val

    return {
        "template": template,
        "cost": parent["cost"],
        "params": params,
        "mutation_detail": {"key": key, "delta": delta, "clamped": new_val},
    }


def _op_cost_adjust(
    parent: dict[str, Any],
    constraints: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any] | None:
    """Adjust cost by +/-1, with compensating param adjustment."""
    template = parent["template"]
    spec = constraints.get("templates", {}).get(template)
    if spec is None:
        return None

    cost_lo, cost_hi = spec.get("cost_range", [1, 5])
    delta = rng.choice([-1, 1])
    new_cost = parent["cost"] + delta
    new_cost = max(cost_lo, min(cost_hi, new_cost))

    if new_cost == parent["cost"]:
        return None

    params = dict(parent["params"])
    params_ranges = spec.get("params_ranges", {})

    # Compensating param adjustment: cost down -> reduce max param, cost up -> increase max param
    if params_ranges:
        sorted_keys = sorted(params_ranges.keys())
        # Find the key with max value
        max_key = max(sorted_keys, key=lambda k: params.get(k, 0))
        if new_cost < parent["cost"]:
            # Cost decreased: reduce max param by 1
            params[max_key] = params.get(max_key, 0) - 1
        else:
            # Cost increased: increase max param by 1
            params[max_key] = params.get(max_key, 0) + 1

        # Clamp to range
        lo, hi = params_ranges[max_key]
        params[max_key] = max(lo, min(hi, params[max_key]))

    return {
        "template": template,
        "cost": new_cost,
        "params": params,
        "mutation_detail": {"cost_delta": delta, "adjusted_key": max_key if params_ranges else None},
    }


def _op_template_swap_within_family(
    parent: dict[str, Any],
    constraints: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any] | None:
    """Swap template within the same family, remapping params."""
    template = parent["template"]
    targets = _swap_targets(template)
    if not targets:
        return None

    new_template = rng.choice(targets)
    new_spec = constraints.get("templates", {}).get(new_template)
    if new_spec is None:
        return None

    old_params = parent["params"]
    new_params_ranges = new_spec.get("params_ranges", {})
    new_params: dict[str, Any] = {}

    for key, (lo, hi) in new_params_ranges.items():
        if key in old_params:
            # Common parameter: inherit + clamp
            new_params[key] = max(lo, min(hi, old_params[key]))
        else:
            # Missing parameter: use midpoint
            new_params[key] = (lo + hi) // 2

    # Clamp cost to new template's range
    new_cost_lo, new_cost_hi = new_spec.get("cost_range", [1, 5])
    new_cost = max(new_cost_lo, min(new_cost_hi, parent["cost"]))

    return {
        "template": new_template,
        "cost": new_cost,
        "params": new_params,
        "mutation_detail": {"from_template": template, "to_template": new_template},
    }


def _op_stat_redistribute(
    parent: dict[str, Any],
    constraints: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any] | None:
    """Vanilla only: redistribute atk+hp while keeping total."""
    if parent["template"] != "Vanilla":
        return None

    spec = constraints.get("templates", {}).get("Vanilla")
    if spec is None:
        return None

    params_ranges = spec.get("params_ranges", {})
    atk_range = params_ranges.get("atk", [1, 6])
    hp_range = params_ranges.get("hp", [1, 8])

    old_atk = parent["params"].get("atk", 1)
    old_hp = parent["params"].get("hp", 1)
    total = old_atk + old_hp

    # Random split
    new_atk = rng.randint(atk_range[0], atk_range[1])
    new_hp = total - new_atk

    # Clamp hp
    new_hp = max(hp_range[0], min(hp_range[1], new_hp))
    # Recompute atk from clamped hp to maintain total if possible
    new_atk = total - new_hp
    new_atk = max(atk_range[0], min(atk_range[1], new_atk))

    params = dict(parent["params"])
    params["atk"] = new_atk
    params["hp"] = new_hp

    return {
        "template": "Vanilla",
        "cost": parent["cost"],
        "params": params,
        "mutation_detail": {"old_atk": old_atk, "old_hp": old_hp, "new_atk": new_atk, "new_hp": new_hp},
    }


# -------------------------------------------------------------------------
# Operator registry
# -------------------------------------------------------------------------

_OPERATORS: dict[str, Any] = {
    "param_jitter": _op_param_jitter,
    "cost_adjust": _op_cost_adjust,
    "template_swap_within_family": _op_template_swap_within_family,
    "stat_redistribute": _op_stat_redistribute,
}


# -------------------------------------------------------------------------
# Single mutation
# -------------------------------------------------------------------------

def mutate_candidate(
    parent: dict[str, Any],
    constraints: dict[str, Any],
    global_seed: int,
    mutation_index: int,
    op_weights: dict[str, float],
    forbid_rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Apply a single mutation to a parent candidate.

    Returns a new candidate dict or None if all retries fail.
    """
    parent_id = parent["id"]

    # Build weighted operator list
    ops = sorted(op_weights.keys())
    weights = [op_weights[o] for o in ops]

    max_retries = 3
    for attempt in range(max_retries):
        mut_seed = _mutation_seed(global_seed, parent_id, "select", mutation_index * max_retries + attempt)
        rng = random.Random(mut_seed)

        # Select operator
        chosen_op = rng.choices(ops, weights=weights, k=1)[0]
        op_fn = _OPERATORS.get(chosen_op)
        if op_fn is None:
            continue

        result = op_fn(parent, constraints, rng)
        if result is None:
            continue

        # Forbid check
        if _check_forbid(result["template"], result["cost"], result["params"], forbid_rules):
            continue

        # Build new candidate
        template_specs = constraints.get("templates", {})
        spec = template_specs.get(result["template"], {})

        cid = _candidate_id(result["template"], result["params"], mut_seed)
        new_candidate = {
            "id": cid,
            "name": f"cand_{result['template'].lower()}_{cid[-6:]}",
            "cost": result["cost"],
            "card_type": spec.get("card_type", parent.get("card_type", "spell")),
            "template": result["template"],
            "params": result["params"],
            "tags": list(spec.get("tags", parent.get("tags", []))),
            "intent": dict(parent.get("intent", {})),
            "gen_reason": dict(parent.get("gen_reason", {})),
            "lineage": {
                "origin": "mutated",
                "parent_id": parent_id,
                "mutation_op": chosen_op,
                "mutation_params": result.get("mutation_detail", {}),
            },
        }
        return new_candidate

    return None


# -------------------------------------------------------------------------
# Batch mutation
# -------------------------------------------------------------------------

def generate_mutations(
    base_candidates: list[dict[str, Any]],
    constraints: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate mutations for all base candidates.

    Returns list of mutated candidates (excluding None results).
    """
    mut_cfg = config.get("mutations", {})
    per_base = mut_cfg.get("per_base", 4)
    op_weights = mut_cfg.get("op_weights", {
        "param_jitter": 0.45,
        "cost_adjust": 0.25,
        "template_swap_within_family": 0.15,
        "stat_redistribute": 0.15,
    })
    global_seed = config.get("seed", 42)
    forbid_rules = constraints.get("global", {}).get("forbid", [])

    mutated: list[dict[str, Any]] = []
    for parent in base_candidates:
        for i in range(per_base):
            child = mutate_candidate(
                parent, constraints, global_seed, i, op_weights, forbid_rules,
            )
            if child is not None:
                mutated.append(child)

    return mutated


# -------------------------------------------------------------------------
# Distance function
# -------------------------------------------------------------------------

def card_distance(
    a: dict[str, Any],
    b: dict[str, Any],
    constraints: dict[str, Any],
) -> float:
    """Compute distance between two candidates. Returns [0, 1]."""
    dist = 0.0

    # Template difference
    if a["template"] != b["template"]:
        dist += 0.5

    # Cost difference
    dist += abs(a["cost"] - b["cost"]) / 10.0 * 0.2

    # Params difference (shared keys only, range-normalized)
    params_a = a.get("params", {})
    params_b = b.get("params", {})
    common_keys = set(params_a.keys()) & set(params_b.keys())

    if common_keys:
        template_specs = constraints.get("templates", {})
        # Use template of a for ranges (fallback to b if not found)
        spec = template_specs.get(a["template"], template_specs.get(b["template"], {}))
        params_ranges = spec.get("params_ranges", {})

        param_diffs: list[float] = []
        for key in sorted(common_keys):
            lo, hi = params_ranges.get(key, [0, 1])
            span = max(hi - lo, 1)
            param_diffs.append(abs(params_a[key] - params_b[key]) / span)

        if param_diffs:
            dist += sum(param_diffs) / len(param_diffs) * 0.3

    return max(0.0, min(1.0, dist))


# -------------------------------------------------------------------------
# Diversity filter
# -------------------------------------------------------------------------

def dedupe_and_filter_diversity(
    candidates: list[dict[str, Any]],
    constraints: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Deduplicate and apply diversity filter.

    1. Remove exact duplicates (template, params, cost)
    2. Sort by id for deterministic order
    3. Greedy filter: keep if min distance to all accepted >= min_distance
    4. Enforce max_per_template
    """
    div_cfg = config.get("diversity", {})
    min_distance = div_cfg.get("min_distance", 0.25)
    max_per_template = div_cfg.get("max_per_template", 12)

    # 1. Deduplicate
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for c in candidates:
        key = json.dumps(
            {"template": c["template"], "params": c["params"], "cost": c["cost"]},
            sort_keys=True,
        )
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    # 2. Sort by id for deterministic order
    deduped.sort(key=lambda c: c["id"])

    # 3. Greedy diversity filter
    accepted: list[dict[str, Any]] = []
    template_counts: dict[str, int] = {}

    for c in deduped:
        tmpl = c["template"]

        # max_per_template check
        if template_counts.get(tmpl, 0) >= max_per_template:
            continue

        # min_distance check against all accepted
        too_close = False
        for a in accepted:
            if card_distance(c, a, constraints) < min_distance:
                too_close = True
                break

        if too_close:
            continue

        accepted.append(c)
        template_counts[tmpl] = template_counts.get(tmpl, 0) + 1

    return accepted
