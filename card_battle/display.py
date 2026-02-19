"""Phase 9a: CLI display – board state, actions, and stats."""

from __future__ import annotations

from typing import Any

from card_battle.actions import (
    Action, PlayCard, GoToCombat, DeclareAttack, DeclareBlock, EndTurn,
)
from card_battle.models import GameState


def render_board(gs: GameState) -> None:
    print(f"\n{'='*50}")
    print(f"  Turn {gs.turn}  |  Active: Player {gs.active_player}  |  Phase: {gs.phase}")
    print(f"{'='*50}")

    for pi in range(2):
        p = gs.players[pi]
        marker = " <<" if pi == gs.active_player else ""
        print(f"  P{pi}: HP={p.hp}  Mana={p.mana}/{p.mana_max}  "
              f"Hand={len(p.hand)}  Deck={len(p.deck)}{marker}")
        if p.board:
            units = "  ".join(
                f"[{u.card_id} {u.atk}/{u.hp}{'*' if u.can_attack else ''}]"
                for u in p.board
            )
            print(f"      Board: {units}")
        else:
            print(f"      Board: (empty)")
    print()


def render_actions(actions: list[Action], gs: GameState) -> None:
    p = gs.active()
    print("  Actions:")
    for i, action in enumerate(actions):
        match action:
            case PlayCard(hand_index=idx):
                card_id = p.hand[idx]
                card = gs.card_db[card_id]
                print(f"    [{i}] Play: {card.name} (cost {card.cost})")
            case GoToCombat():
                print(f"    [{i}] Go to Combat")
            case DeclareAttack(attacker_uids=uids):
                if not uids:
                    print(f"    [{i}] Cancel combat (attack with nobody)")
                else:
                    unit_map = {u.uid: u for u in p.board}
                    names = ", ".join(
                        f"{unit_map[uid].card_id}({unit_map[uid].atk}ATK)"
                        for uid in uids if uid in unit_map
                    )
                    print(f"    [{i}] Attack with: {names}")
            case DeclareBlock(pairs=pairs):
                if not pairs:
                    print(f"    [{i}] No blocks")
                else:
                    defender = gs.opponent()
                    b_map = {u.uid: u for u in defender.board}
                    a_map = {u.uid: u for u in p.board}
                    descs = []
                    for b_uid, a_uid in pairs:
                        b_name = b_map[b_uid].card_id if b_uid in b_map else f"uid{b_uid}"
                        a_name = a_map[a_uid].card_id if a_uid in a_map else f"uid{a_uid}"
                        descs.append(f"{b_name} blocks {a_name}")
                    print(f"    [{i}] Block: {', '.join(descs)}")
            case EndTurn():
                print(f"    [{i}] End Turn")
    print()


def render_stats(stats: dict[str, Any]) -> None:
    print(f"\n{'='*50}")
    print(f"  Simulation Results  ({stats['total_matches']} matches)")
    print(f"{'='*50}")

    for did, ds in stats["decks"].items():
        print(f"  {did:20s}  W={ds['wins']:4d}  L={ds['losses']:4d}  "
              f"D={ds['draws']:4d}  WR={ds['win_rate']:5.1f}%")

    print(f"\n  Seat 0 wins: {stats['seat_0_wins']}  |  "
          f"Seat 1 wins: {stats['seat_1_wins']}  |  "
          f"Draws: {stats['draws']}")
    print()


def render_card_adoption(adoption: dict[str, int], total_decks: int) -> None:
    print(f"\n  Card Adoption ({total_decks} decks):")
    for card_id, count in adoption.items():
        pct = count / total_decks * 100
        print(f"    {card_id:20s}  {count}/{total_decks}  ({pct:.0f}%)")
    print()
