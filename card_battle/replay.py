"""v0.5.9: Replay recording and playback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from card_battle.models import PlayerState, UnitInstance


def snapshot_board(board: "list[UnitInstance]") -> list[dict]:
    """Snapshot the board state as a list of dicts."""
    return [
        {
            "uid": u.uid,
            "card_id": u.card_id,
            "atk": u.atk,
            "hp": u.hp,
            "can_attack": u.can_attack,
        }
        for u in board
    ]


def snapshot_player(player: "PlayerState") -> dict:
    """Snapshot a player's state."""
    return {
        "hp": player.hp,
        "mana": player.mana,
        "mana_max": player.mana_max,
        "hand_count": len(player.hand),
        "deck_count": len(player.deck),
        "graveyard_count": len(player.graveyard),
        "board": snapshot_board(player.board),
    }


class ReplayWriter:
    """Writes replay events as JSONL to a file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "w", encoding="utf-8")
        self._closed = False

    def write(self, event: dict) -> None:
        if self._closed:
            raise RuntimeError("ReplayWriter is closed")
        self._file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def close(self) -> None:
        if not self._closed:
            self._file.close()
            self._closed = True

    @property
    def path(self) -> Path:
        return self._path

    def __enter__(self) -> "ReplayWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def render_replay(
    path: str | Path,
    from_turn: int | None = None,
    to_turn: int | None = None,
    compact: bool = False,
) -> None:
    """Render a JSONL replay file to stdout."""
    path = Path(path)
    events: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    for ev in events:
        etype = ev.get("type", "")
        turn = ev.get("turn")

        # Filter by turn range
        if turn is not None:
            if from_turn is not None and turn < from_turn:
                # Always show meta and game_start
                if etype not in ("meta", "game_start"):
                    continue
            if to_turn is not None and turn > to_turn:
                if etype not in ("game_end",):
                    continue

        if etype == "meta":
            print(f"=== REPLAY: seed={ev.get('seed')} ===")
            deck_ids = ev.get("deck_ids", [])
            if deck_ids:
                print(f"  Decks: {deck_ids[0]} vs {deck_ids[1]}")

        elif etype == "game_start":
            print(f"  First player: P{ev.get('active_player')}")
            if not compact:
                for pi in range(2):
                    ps = ev.get(f"p{pi}", {})
                    print(f"  P{pi}: HP={ps.get('hp')} Hand={ps.get('hand_count')} "
                          f"Deck={ps.get('deck_count')}")

        elif etype == "turn_start":
            print(f"\n--- Turn {turn} (P{ev.get('active_player')}) ---")
            for pi in range(2):
                ps = ev.get(f"p{pi}", {})
                board = ps.get("board", [])
                board_str = ", ".join(
                    f"{u['card_id']}({u['atk']}/{u['hp']})" for u in board
                ) if board else "(empty)"
                print(f"  P{pi}: HP={ps.get('hp')} Mana={ps.get('mana')}/{ps.get('mana_max')} "
                      f"Hand={ps.get('hand_count')} Deck={ps.get('deck_count')}")
                if not compact:
                    print(f"    Board: {board_str}")

        elif etype == "play_card":
            ct = ev.get("card_type", "?")
            print(f"  P{ev.get('player')} plays {ev.get('card_id')} "
                  f"(cost {ev.get('cost')}, {ct})")

        elif etype == "go_to_combat":
            print(f"  P{ev.get('player')} -> combat")

        elif etype == "declare_attack":
            attackers = ev.get("attackers", [])
            if attackers:
                atk_str = ", ".join(
                    f"{a['card_id']}(atk={a['atk']})" for a in attackers
                )
                print(f"  Attack: {atk_str}")
            else:
                print("  Attack: (none)")

        elif etype == "declare_block":
            pairs = ev.get("pairs", [])
            if pairs:
                for p in pairs:
                    print(f"  Block: {p.get('blocker_card_id')} blocks "
                          f"{p.get('attacker_card_id')}")
            else:
                print("  Block: (none)")

        elif etype == "combat_resolve":
            dmg = ev.get("player_damage", 0)
            atk_d = ev.get("atk_deaths", 0)
            def_d = ev.get("def_deaths", 0)
            print(f"  Combat: {dmg} damage to player, "
                  f"{atk_d} attacker deaths, {def_d} defender deaths")
            print(f"    HP after: P0={ev.get('hp_after_p0')} P1={ev.get('hp_after_p1')}")

        elif etype == "turn_end":
            pass  # separator handled by next turn_start

        elif etype == "game_end":
            print(f"\n=== GAME END ===")
            print(f"  Winner: {ev.get('winner')} (reason: {ev.get('reason')})")
            final = ev.get("final_hp", [])
            if final:
                print(f"  Final HP: P0={final[0]} P1={final[1]}")
            print(f"  Turns: {ev.get('turns')}")
