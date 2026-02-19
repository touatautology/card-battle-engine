"""Phase 3: Actions – types, legal-move generation, and application."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Union

from card_battle.effects import resolve_effect
from card_battle.models import CombatState, GameState, UnitInstance


# ---------------------------------------------------------------------------
# Action types (frozen dataclasses)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayCard:
    hand_index: int


@dataclass(frozen=True)
class GoToCombat:
    pass


@dataclass(frozen=True)
class DeclareAttack:
    attacker_uids: tuple[int, ...]


@dataclass(frozen=True)
class DeclareBlock:
    pairs: tuple[tuple[int, int], ...]   # ((blocker_uid, attacker_uid), ...)


@dataclass(frozen=True)
class EndTurn:
    pass


Action = Union[PlayCard, GoToCombat, DeclareAttack, DeclareBlock, EndTurn]

BOARD_LIMIT = 7


# ---------------------------------------------------------------------------
# Legal action generation
# ---------------------------------------------------------------------------

def get_legal_actions(gs: GameState) -> list[Action]:
    if gs.phase == "main":
        return _get_main_actions(gs)
    elif gs.phase == "combat_attack":
        return _get_attack_candidates(gs)
    elif gs.phase == "combat_block":
        return _get_block_candidates(gs)
    else:
        return [EndTurn()]


def _get_main_actions(gs: GameState) -> list[Action]:
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

    # GoToCombat if any unit can attack
    if any(u.can_attack for u in p.board):
        actions.append(GoToCombat())

    # Always can end turn
    actions.append(EndTurn())
    return actions


def _get_attack_candidates(gs: GameState) -> list[Action]:
    """Generate limited DeclareAttack candidates for AI tractability."""
    p = gs.active()
    attackable = [u.uid for u in p.board if u.can_attack]

    candidates: list[Action] = []
    seen: set[tuple[int, ...]] = set()

    def _add(uids: tuple[int, ...]) -> None:
        key = tuple(sorted(uids))
        if key not in seen:
            seen.add(key)
            candidates.append(DeclareAttack(attacker_uids=key))

    # 1. Empty (cancel combat)
    _add(())

    if attackable:
        # 2. All attackers
        _add(tuple(attackable))

        # 3. Each single attacker
        for uid in attackable:
            _add((uid,))

        # 4. All minus one
        if len(attackable) > 1:
            for uid in attackable:
                remaining = tuple(u for u in attackable if u != uid)
                _add(remaining)

    return candidates


def _get_block_candidates(gs: GameState) -> list[Action]:
    """Generate limited DeclareBlock candidates for the defender."""
    assert gs.combat is not None
    attacker_uids = gs.combat.attackers
    defender = gs.opponent()
    blockers = [u for u in defender.board]

    candidates: list[Action] = []
    seen: set[tuple[tuple[int, int], ...]] = set()

    def _add(pairs: list[tuple[int, int]]) -> None:
        key = tuple(sorted(pairs))
        if key not in seen:
            seen.add(key)
            candidates.append(DeclareBlock(pairs=key))

    # 1. No blocks
    _add([])

    if blockers and attacker_uids:
        # Look up attacker units for greedy matching
        active = gs.active()
        attacker_map = {u.uid: u for u in active.board}
        blocker_list = list(blockers)

        # 2. Greedy block: assign blockers to attackers sorted by atk descending
        sorted_attackers = sorted(
            attacker_uids,
            key=lambda uid: attacker_map[uid].atk if uid in attacker_map else 0,
            reverse=True,
        )
        greedy_pairs: list[tuple[int, int]] = []
        used_blockers: set[int] = set()
        for a_uid in sorted_attackers:
            best_blocker = None
            best_score = -999.0
            for b in blocker_list:
                if b.uid in used_blockers:
                    continue
                # Score: prefer blockers that can kill the attacker and survive
                a_unit = attacker_map.get(a_uid)
                if a_unit is None:
                    continue
                score = 0.0
                if b.atk >= a_unit.hp:
                    score += 10.0  # can kill attacker
                if b.hp > a_unit.atk:
                    score += 5.0   # blocker survives
                score += b.atk * 0.1  # tiebreak
                if score > best_score:
                    best_score = score
                    best_blocker = b
            if best_blocker is not None and best_score > 0:
                greedy_pairs.append((best_blocker.uid, a_uid))
                used_blockers.add(best_blocker.uid)

        if greedy_pairs:
            _add(greedy_pairs)

        # 3. Max block: assign as many blockers as possible (1:1)
        max_pairs: list[tuple[int, int]] = []
        used: set[int] = set()
        for a_uid in attacker_uids:
            for b in blocker_list:
                if b.uid not in used:
                    max_pairs.append((b.uid, a_uid))
                    used.add(b.uid)
                    break
        if max_pairs:
            _add(max_pairs)

        # 4. Single blocks: each blocker blocks the strongest attacker
        for b in blocker_list:
            if sorted_attackers:
                _add([(b.uid, sorted_attackers[0])])

    return candidates


# ---------------------------------------------------------------------------
# Action application
# ---------------------------------------------------------------------------

def apply_action(gs: GameState, action: Action) -> None:
    match action:
        case PlayCard(hand_index=idx):
            _apply_play_card(gs, idx)
        case GoToCombat():
            gs.phase = "combat_attack"
            gs.combat = CombatState()
        case DeclareAttack(attacker_uids=uids):
            _apply_declare_attack(gs, uids)
        case DeclareBlock(pairs=pairs):
            _apply_declare_block(gs, pairs)
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


def _apply_declare_attack(gs: GameState, attacker_uids: tuple[int, ...]) -> None:
    assert gs.combat is not None
    if not attacker_uids:
        # Cancel combat — return to main
        gs.combat = None
        gs.phase = "main"
    else:
        gs.combat.attackers = list(attacker_uids)
        gs.phase = "combat_block"


def _apply_declare_block(gs: GameState, pairs: tuple[tuple[int, int], ...]) -> None:
    assert gs.combat is not None
    gs.combat.blocks = {attacker_uid: blocker_uid for blocker_uid, attacker_uid in pairs}
