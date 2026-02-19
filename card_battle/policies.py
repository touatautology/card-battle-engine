"""v3.2: Policy registry for multi-policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from card_battle.ai import Agent, GreedyAI, RandomAI, SimpleAI


@dataclass(frozen=True)
class Policy:
    name: str
    make_agent: Callable[[int], Agent]  # (seed) -> Agent


class PolicyRegistry:
    """Registry of named policies for evaluation."""

    def __init__(self) -> None:
        self._policies: dict[str, Policy] = {}

    def register(self, policy: Policy) -> None:
        self._policies[policy.name] = policy

    def get_policy(self, name: str) -> Policy:
        """Get a policy by name. Raises KeyError if not found."""
        return self._policies[name]

    def list_policies(self) -> list[str]:
        return sorted(self._policies.keys())


def default_registry() -> PolicyRegistry:
    """Return a registry with greedy, simple, and random policies."""
    registry = PolicyRegistry()
    registry.register(Policy(name="greedy", make_agent=lambda seed: GreedyAI()))
    registry.register(Policy(name="simple", make_agent=lambda seed: SimpleAI()))
    registry.register(Policy(name="random", make_agent=lambda seed: RandomAI(seed)))
    return registry


def normalize_weights(
    entries: list[dict[str, Any]],
) -> list[tuple[str, float]]:
    """Normalize policy weight entries to sum to 1.0.

    Input:  [{"name": "greedy", "weight": 3}, {"name": "simple", "weight": 1}]
    Output: [("greedy", 0.75), ("simple", 0.25)]

    Raises ValueError if entries is empty, any weight is negative, or total <= 0.
    """
    if not entries:
        raise ValueError("entries must not be empty")

    total = 0.0
    for entry in entries:
        w = float(entry["weight"])
        if w < 0:
            raise ValueError(f"Negative weight for policy '{entry['name']}': {w}")
        total += w

    if total <= 0:
        raise ValueError(f"Total weight must be positive, got {total}")

    return [(entry["name"], float(entry["weight"]) / total) for entry in entries]
