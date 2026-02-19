"""v3.1: Match telemetry – per-game event counters for behavioral analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from card_battle.models import Card, GameResult, GameState


@dataclass
class TelemetryConfig:
    enabled: bool = True
    save_match_summaries: bool = False
    output_path: str | None = None


class MatchTelemetry:
    """Collects per-game statistics via on_*() hooks called from the engine.

    All counters are per-player lists [p0, p1].
    """

    def __init__(self) -> None:
        # Per-player counters
        self.damage_to_player: list[int] = [0, 0]
        self.cards_played: list[int] = [0, 0]
        self.units_summoned: list[int] = [0, 0]
        self.mana_spent: list[int] = [0, 0]
        self.mana_wasted: list[int] = [0, 0]
        self.drawn_total: list[int] = [0, 0]
        self.drawn_turn: list[int] = [0, 0]
        self.drawn_effect: list[int] = [0, 0]
        self.attacks_declared: list[int] = [0, 0]
        self.attackers_total: list[int] = [0, 0]
        self.blocks_declared: list[int] = [0, 0]
        self.blocks_total: list[int] = [0, 0]
        self.unblocked_attackers: list[int] = [0, 0]
        self.unblocked_damage: list[int] = [0, 0]
        self.trades: list[int] = [0, 0]
        self.units_died: list[int] = [0, 0]
        self.units_died_in_combat: list[int] = [0, 0]
        self.fatigue_loss: list[bool] = [False, False]

        # Accumulated mana_max per turn (for invariant checking)
        self.total_mana_granted: list[int] = [0, 0]

        # Turn-scoped temporaries
        self._turn_mana_spent: list[int] = [0, 0]
        self._turn_mana_max: list[int] = [0, 0]

        # Game metadata
        self._total_turns: int = 0
        self._winner: str = ""
        self._reason: str = ""

    # ------------------------------------------------------------------
    # Hook methods – called by engine.py
    # ------------------------------------------------------------------

    def on_game_start(self, gs: "GameState") -> None:
        pass

    def on_turn_start(self, gs: "GameState", player_idx: int) -> None:
        p = gs.players[player_idx]
        self.total_mana_granted[player_idx] += p.mana_max
        self._turn_mana_spent[player_idx] = 0
        self._turn_mana_max[player_idx] = p.mana_max

    def on_card_played(
        self, gs: "GameState", player_idx: int, card: "Card",
    ) -> None:
        self.cards_played[player_idx] += 1
        self.mana_spent[player_idx] += card.cost
        self._turn_mana_spent[player_idx] += card.cost
        if card.is_unit:
            self.units_summoned[player_idx] += 1

    def on_cards_drawn(
        self, gs: "GameState", player_idx: int, n: int, reason: str,
    ) -> None:
        self.drawn_total[player_idx] += n
        if reason == "turn_draw":
            self.drawn_turn[player_idx] += n
        elif reason == "effect":
            self.drawn_effect[player_idx] += n

    def on_declare_attack(
        self, gs: "GameState", player_idx: int, attacker_uids: tuple[int, ...],
    ) -> None:
        if attacker_uids:
            self.attacks_declared[player_idx] += 1
            self.attackers_total[player_idx] += len(attacker_uids)

    def on_declare_block(
        self, gs: "GameState", defender_idx: int, pairs: tuple[tuple[int, int], ...],
    ) -> None:
        if pairs:
            self.blocks_declared[defender_idx] += 1
            self.blocks_total[defender_idx] += len(pairs)

    def on_combat_resolved(
        self,
        gs: "GameState",
        atk_idx: int,
        def_idx: int,
        unblocked_atk_count: int,
        unblocked_dmg: int,
        trade_count: int,
        atk_deaths: int,
        def_deaths: int,
        player_damage: int,
    ) -> None:
        self.unblocked_attackers[atk_idx] += unblocked_atk_count
        self.unblocked_damage[atk_idx] += unblocked_dmg
        self.trades[atk_idx] += trade_count
        self.units_died_in_combat[atk_idx] += atk_deaths
        self.units_died_in_combat[def_idx] += def_deaths
        self.units_died[atk_idx] += atk_deaths
        self.units_died[def_idx] += def_deaths
        self.damage_to_player[atk_idx] += player_damage

    def on_turn_end(self, gs: "GameState", player_idx: int) -> None:
        wasted = self._turn_mana_max[player_idx] - self._turn_mana_spent[player_idx]
        self.mana_wasted[player_idx] += max(wasted, 0)

    def on_game_end(
        self, gs: "GameState", result: "GameResult", reason: str,
    ) -> None:
        self._total_turns = gs.turn
        self._winner = result.value
        self._reason = reason
        if reason == "deckout":
            # The player who decked out lost due to fatigue
            for pi in range(2):
                if gs.players[pi].hp > 0:
                    continue
                # This player didn't necessarily deck out; check deck
            # Actually: deckout means the active player couldn't draw
            # The active player at the time of deckout is indicated by
            # the game result: loser is the one who decked out
            from card_battle.models import GameResult as GR
            if result == GR.PLAYER_1_WIN:
                self.fatigue_loss[0] = True
            elif result == GR.PLAYER_0_WIN:
                self.fatigue_loss[1] = True

    def on_spell_damage(
        self, gs: "GameState", player_idx: int, damage: int,
    ) -> None:
        """Track damage dealt to opponent via spells/effects (non-combat)."""
        self.damage_to_player[player_idx] += damage

    # ------------------------------------------------------------------
    # Summary export
    # ------------------------------------------------------------------

    def to_summary(self) -> dict[str, Any]:
        """Return a flat dict summarizing this match's telemetry."""
        summary: dict[str, Any] = {
            "total_turns": self._total_turns,
            "winner": self._winner,
            "reason": self._reason,
        }
        # Per-player fields as p0_*/p1_* keys
        per_player_fields = [
            "damage_to_player", "cards_played", "units_summoned",
            "mana_spent", "mana_wasted", "drawn_total", "drawn_turn",
            "drawn_effect", "attacks_declared", "attackers_total",
            "blocks_declared", "blocks_total", "unblocked_attackers",
            "unblocked_damage", "trades", "units_died",
            "units_died_in_combat", "fatigue_loss",
            "total_mana_granted",
        ]
        for fname in per_player_fields:
            vals = getattr(self, fname)
            for pi in range(2):
                key = f"p{pi}_{fname}"
                v = vals[pi]
                summary[key] = v if not isinstance(v, bool) else int(v)
        return summary
