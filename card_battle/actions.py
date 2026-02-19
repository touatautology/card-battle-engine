"""Phase 3: Actions – types, legal-move generation, and application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from card_battle.effects import resolve_effect
from card_battle.models import GameState, UnitInstance


# ---------------------------------------------------------------------------
# Action types (frozen dataclasses)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayCard:
    hand_index: int


@dataclass(frozen=True)
class Attack:
    board_index: int


@dataclass(frozen=True)
class EndTurn:
    pass


Action = Union[PlayCard, Attack, EndTurn]

BOARD_LIMIT = 7


# ---------------------------------------------------------------------------
# Legal action generation
# ---------------------------------------------------------------------------

def get_legal_actions(gs: GameState) -> list[Action]:
    actions: list[Action] = []
    p = gs.active()

    # Play cards from hand (if enough mana and board space for units)
    for i, card_id in enumerate(p.hand):
        card = gs.card_db[card_id]
        if card.cost > p.mana:
            continue
        if card.is_unit and len(p.board) >= BOARD_LIMIT:
            continue
        actions.append(PlayCard(hand_index=i))

    # Attack with units that can attack
    for i, unit in enumerate(p.board):
        if unit.can_attack:
            actions.append(Attack(board_index=i))

    # Always can end turn
    actions.append(EndTurn())
    return actions


# ---------------------------------------------------------------------------
# Action application
# ---------------------------------------------------------------------------

def apply_action(gs: GameState, action: Action) -> None:
    match action:
        case PlayCard(hand_index=idx):
            _apply_play_card(gs, idx)
        case Attack(board_index=idx):
            _apply_attack(gs, idx)
        case EndTurn():
            pass  # handled by engine
        case _:
            raise ValueError(f"Unknown action: {action}")


def _apply_play_card(gs: GameState, hand_index: int) -> None:
    p = gs.active()
    card_id = p.hand.pop(hand_index)
    card = gs.card_db[card_id]
    p.mana -= card.cost

    if card.is_unit:
        atk = card.params.get("atk", 0)
        hp = card.params.get("hp", 0)
        unit = UnitInstance(
            uid=gs.alloc_uid(),
            card_id=card_id,
            atk=atk,
            hp=hp,
            can_attack=False,  # summoning sickness
        )
        p.board.append(unit)
        resolve_effect(gs, gs.active_player, card.template, card.params)
    else:
        # spell → graveyard, then resolve
        p.graveyard.append(card_id)
        resolve_effect(gs, gs.active_player, card.template, card.params)


def _apply_attack(gs: GameState, board_index: int) -> None:
    p = gs.active()
    unit = p.board[board_index]
    unit.can_attack = False
    # v0.1: direct damage to opponent player
    gs.opponent().hp -= unit.atk
