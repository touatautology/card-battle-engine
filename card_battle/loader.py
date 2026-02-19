"""Phase 4: JSON data loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

from card_battle.models import Card, DeckDef, DeckEntry
from card_battle.effects import EFFECT_REGISTRY


def load_cards(path: str | Path) -> dict[str, Card]:
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    card_db: dict[str, Card] = {}
    for entry in raw:
        card = Card(
            id=entry["id"],
            name=entry["name"],
            cost=entry["cost"],
            card_type=entry["card_type"],
            tags=tuple(entry.get("tags", ())),
            template=entry["template"],
            params=entry.get("params", {}),
            rarity=entry.get("rarity", "common"),
        )
        _validate_card(card)
        card_db[card.id] = card
    return card_db


def _validate_card(card: Card) -> None:
    if card.cost < 0 or card.cost > 10:
        raise ValueError(f"Card {card.id}: cost {card.cost} out of range [0,10]")
    if card.card_type not in ("unit", "spell"):
        raise ValueError(f"Card {card.id}: invalid card_type '{card.card_type}'")
    if card.template not in EFFECT_REGISTRY:
        raise ValueError(f"Card {card.id}: unknown template '{card.template}'")
    if card.is_unit:
        if "atk" not in card.params or "hp" not in card.params:
            raise ValueError(f"Card {card.id}: unit must have atk and hp in params")


def load_deck(path: str | Path, card_db: dict[str, Card]) -> DeckDef:
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    deck_id = raw["deck_id"]
    entries: list[DeckEntry] = []
    total = 0
    for e in raw["entries"]:
        card_id = e["card_id"]
        count = e["count"]
        if card_id not in card_db:
            raise ValueError(f"Deck {deck_id}: unknown card_id '{card_id}'")
        if count < 1 or count > 3:
            raise ValueError(f"Deck {deck_id}: card '{card_id}' count {count} not in [1,3]")
        total += count
        entries.append(DeckEntry(card_id=card_id, count=count))

    if total != 30:
        raise ValueError(f"Deck {deck_id}: total cards {total}, expected 30")

    return DeckDef(deck_id=deck_id, entries=tuple(entries))
