"""v3.1: Aggregation of match telemetry summaries."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


# Numeric fields in a telemetry summary (excluding metadata and bools)
_NUMERIC_PREFIXES = (
    "damage_to_player", "cards_played", "units_summoned",
    "mana_spent", "mana_wasted", "drawn_total", "drawn_turn",
    "drawn_effect", "attacks_declared", "attackers_total",
    "blocks_declared", "blocks_total", "unblocked_attackers",
    "unblocked_damage", "trades", "units_died",
    "units_died_in_combat", "total_mana_granted",
)

_NUMERIC_KEYS: set[str] = set()
for _prefix in _NUMERIC_PREFIXES:
    _NUMERIC_KEYS.add(f"p0_{_prefix}")
    _NUMERIC_KEYS.add(f"p1_{_prefix}")
_NUMERIC_KEYS.add("total_turns")


def aggregate_match_summaries(
    summaries: list[dict[str, Any]],
    group_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate a list of match telemetry summaries.

    Returns a dict with:
      - "overall": {field: {"sum": .., "mean": .., "count": ..}}
      - "by_group": {group_value: {field: {"sum": .., "mean": .., "count": ..}}}
        (only if group_keys is provided)
    """
    if group_keys is None:
        group_keys = []

    result: dict[str, Any] = {
        "overall": _aggregate_group(summaries),
        "count": len(summaries),
    }

    if group_keys:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for s in summaries:
            key_parts = [str(s.get(k, "unknown")) for k in group_keys]
            group_key = "|".join(key_parts)
            groups[group_key].append(s)
        result["by_group"] = {
            gk: _aggregate_group(gs) for gk, gs in sorted(groups.items())
        }

    return result


def _aggregate_group(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute sum/mean/count for all numeric fields in a group."""
    if not summaries:
        return {}

    totals: dict[str, float] = defaultdict(float)
    count = len(summaries)

    for s in summaries:
        for key in _NUMERIC_KEYS:
            if key in s:
                totals[key] += float(s[key])

    agg: dict[str, Any] = {}
    for key, total in sorted(totals.items()):
        agg[key] = {
            "sum": total,
            "mean": round(total / count, 4),
            "count": count,
        }
    return agg
