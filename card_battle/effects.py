"""Phase 2: Effect templates – decorator-based registry."""

from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from card_battle.models import GameState

EffectHandler = Callable[["GameState", int, dict[str, Any]], None]

EFFECT_REGISTRY: dict[str, EffectHandler] = {}


def register_effect(name: str):
    """Decorator to register an effect handler."""
    def decorator(fn: EffectHandler) -> EffectHandler:
        EFFECT_REGISTRY[name] = fn
        return fn
    return decorator


def resolve_effect(gs: "GameState", player_idx: int, template: str, params: dict[str, Any]) -> None:
    handler = EFFECT_REGISTRY.get(template)
    if handler is None:
        raise ValueError(f"Unknown effect template: {template}")
    handler(gs, player_idx, params)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _draw_one(gs: "GameState", player_idx: int) -> bool:
    """Draw one card for player. Returns False if deck is empty."""
    p = gs.players[player_idx]
    if not p.deck:
        return False
    p.hand.append(p.deck.pop(0))
    return True


# ---------------------------------------------------------------------------
# Unit effects
# ---------------------------------------------------------------------------

@register_effect("Vanilla")
def _vanilla(gs: "GameState", player_idx: int, params: dict[str, Any]) -> None:
    """No additional effect – stats are set at placement time."""
    pass


@register_effect("OnPlayDamagePlayer")
def _on_play_damage_player(gs: "GameState", player_idx: int, params: dict[str, Any]) -> None:
    amount = params["amount"]
    opp = gs.players[1 - player_idx]
    opp.hp -= amount


@register_effect("OnPlayDraw")
def _on_play_draw(gs: "GameState", player_idx: int, params: dict[str, Any]) -> None:
    n = params["n"]
    for _ in range(n):
        _draw_one(gs, player_idx)


# ---------------------------------------------------------------------------
# Spell effects
# ---------------------------------------------------------------------------

@register_effect("DamagePlayer")
def _damage_player(gs: "GameState", player_idx: int, params: dict[str, Any]) -> None:
    amount = params["amount"]
    opp = gs.players[1 - player_idx]
    opp.hp -= amount


@register_effect("HealSelf")
def _heal_self(gs: "GameState", player_idx: int, params: dict[str, Any]) -> None:
    amount = params["amount"]
    p = gs.players[player_idx]
    p.hp = min(p.hp + amount, 20)


@register_effect("Draw")
def _draw(gs: "GameState", player_idx: int, params: dict[str, Any]) -> None:
    n = params["n"]
    for _ in range(n):
        _draw_one(gs, player_idx)


@register_effect("RemoveUnit")
def _remove_unit(gs: "GameState", player_idx: int, params: dict[str, Any]) -> None:
    """Remove the first opponent unit with hp <= max_hp."""
    max_hp = params["max_hp"]
    opp = gs.players[1 - player_idx]
    for i, unit in enumerate(opp.board):
        if unit.hp <= max_hp:
            opp.graveyard.append(unit.card_id)
            opp.board.pop(i)
            return
