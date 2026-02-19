"""Phase 1: Data models for the card battle engine."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Card definition (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Card:
    id: str
    name: str
    cost: int
    card_type: str          # "unit" or "spell"
    tags: tuple[str, ...]
    template: str           # effect template name
    params: dict[str, Any]
    rarity: str = "common"  # common / uncommon / rare

    # convenience
    @property
    def is_unit(self) -> bool:
        return self.card_type == "unit"


# ---------------------------------------------------------------------------
# Deck definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeckEntry:
    card_id: str
    count: int


@dataclass(frozen=True)
class DeckDef:
    deck_id: str
    entries: tuple[DeckEntry, ...]


# ---------------------------------------------------------------------------
# In-game instances
# ---------------------------------------------------------------------------

@dataclass
class UnitInstance:
    uid: int
    card_id: str
    atk: int
    hp: int
    can_attack: bool = False


@dataclass
class PlayerState:
    hp: int = 20
    mana_max: int = 0
    mana: int = 0
    deck: list[str] = field(default_factory=list)       # card_id list
    hand: list[str] = field(default_factory=list)        # card_id list
    board: list[UnitInstance] = field(default_factory=list)
    graveyard: list[str] = field(default_factory=list)   # card_id list


# ---------------------------------------------------------------------------
# Game result
# ---------------------------------------------------------------------------

class GameResult(Enum):
    PLAYER_0_WIN = "player_0_win"
    PLAYER_1_WIN = "player_1_win"
    DRAW = "draw"


# ---------------------------------------------------------------------------
# Game state (mutable, modified in-place)
# ---------------------------------------------------------------------------

@dataclass
class GameState:
    turn: int
    active_player: int                    # 0 or 1
    players: list[PlayerState]
    next_uid: int
    result: GameResult | None
    rng: random.Random
    card_db: dict[str, Card]

    def opponent_idx(self) -> int:
        return 1 - self.active_player

    def active(self) -> PlayerState:
        return self.players[self.active_player]

    def opponent(self) -> PlayerState:
        return self.players[self.opponent_idx()]

    def alloc_uid(self) -> int:
        uid = self.next_uid
        self.next_uid += 1
        return uid


# ---------------------------------------------------------------------------
# Match log (returned after a game completes)
# ---------------------------------------------------------------------------

@dataclass
class MatchLog:
    seed: int
    deck_ids: tuple[str, str]
    winner: GameResult
    turns: int
    final_hp: tuple[int, int]
    play_trace: list[dict[str, Any]] | None = None
