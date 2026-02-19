"""v0.3: Deck mutation operators for evolutionary search."""

from __future__ import annotations

import random

from card_battle.models import Card, DeckDef, DeckEntry

# Internal mutable representation: card_id -> count
DeckCounts = dict[str, int]

DECK_SIZE = 30
MAX_COPIES = 3


def deck_to_counts(deck: DeckDef) -> DeckCounts:
    """Convert a frozen DeckDef to a mutable dict[str, int]."""
    return {e.card_id: e.count for e in deck.entries}


def counts_to_deck(deck_id: str, counts: DeckCounts) -> DeckDef:
    """Convert counts back to a DeckDef, with validation."""
    entries: list[DeckEntry] = []
    total = 0
    for card_id, count in sorted(counts.items()):
        if count < 1 or count > MAX_COPIES:
            raise ValueError(f"Card '{card_id}' count {count} not in [1,{MAX_COPIES}]")
        entries.append(DeckEntry(card_id=card_id, count=count))
        total += count
    if total != DECK_SIZE:
        raise ValueError(f"Deck total {total}, expected {DECK_SIZE}")
    return DeckDef(deck_id=deck_id, entries=tuple(entries))


def validate_counts(counts: DeckCounts) -> bool:
    """Check if counts satisfy deck constraints (30 cards, 1-3 each)."""
    total = sum(counts.values())
    if total != DECK_SIZE:
        return False
    return all(1 <= c <= MAX_COPIES for c in counts.values())


def swap_one(
    counts: DeckCounts,
    card_db: dict[str, Card],
    rng: random.Random,
) -> DeckCounts:
    """Remove 1 copy of a random card and add 1 copy of a card not at max."""
    counts = dict(counts)
    pool = list(card_db.keys())

    # Pick a card to remove (weighted by count)
    cards_in = list(counts.keys())
    weights = [counts[c] for c in cards_in]
    remove_card = rng.choices(cards_in, weights=weights, k=1)[0]

    # Find candidates to add (cards below max copies or absent from deck)
    add_candidates = [
        c for c in pool
        if c != remove_card and counts.get(c, 0) < MAX_COPIES
    ]
    if not add_candidates:
        return counts  # no swap possible

    add_card = rng.choice(add_candidates)

    # Apply
    counts[remove_card] -= 1
    if counts[remove_card] == 0:
        del counts[remove_card]
    counts[add_card] = counts.get(add_card, 0) + 1

    return counts


def swap_n(
    counts: DeckCounts,
    card_db: dict[str, Card],
    rng: random.Random,
    n_range: tuple[int, int] = (2, 5),
) -> DeckCounts:
    """Apply swap_one n times (n drawn uniformly from n_range inclusive)."""
    n = rng.randint(n_range[0], n_range[1])
    for _ in range(n):
        counts = swap_one(counts, card_db, rng)
    return counts


def tweak_counts(
    counts: DeckCounts,
    card_db: dict[str, Card],
    rng: random.Random,
) -> DeckCounts:
    """Adjust card counts: pick one card to +1 and another to -1."""
    counts = dict(counts)
    pool = list(card_db.keys())

    # Candidates for +1: cards below MAX_COPIES (including absent cards)
    plus_candidates = [c for c in pool if counts.get(c, 0) < MAX_COPIES]
    # Candidates for -1: cards with count >= 1
    minus_candidates = list(counts.keys())

    if not plus_candidates or not minus_candidates:
        return counts

    plus_card = rng.choice(plus_candidates)
    # -1 candidate must differ from +1 card (otherwise net zero on same card)
    minus_options = [c for c in minus_candidates if c != plus_card]
    if not minus_options:
        return counts

    minus_card = rng.choice(minus_options)

    # Apply
    counts[plus_card] = counts.get(plus_card, 0) + 1
    counts[minus_card] -= 1
    if counts[minus_card] == 0:
        del counts[minus_card]

    return counts


def random_deck(
    deck_id: str,
    card_db: dict[str, Card],
    rng: random.Random,
) -> DeckDef:
    """Generate a random valid 30-card deck from the card pool."""
    pool = list(card_db.keys())
    counts: DeckCounts = {}
    remaining = DECK_SIZE

    while remaining > 0:
        # Cards that can still receive copies
        available = [c for c in pool if counts.get(c, 0) < MAX_COPIES]
        card = rng.choice(available)
        counts[card] = counts.get(card, 0) + 1
        remaining -= 1

    return counts_to_deck(deck_id, counts)


def mutate_deck(
    deck: DeckDef,
    card_db: dict[str, Card],
    rng: random.Random,
    weights: dict[str, float],
    swap_n_range: tuple[int, int] = (2, 5),
) -> DeckDef:
    """Apply one weighted-random mutation operator to a deck."""
    counts = deck_to_counts(deck)

    operators = list(weights.keys())
    w = [weights[op] for op in operators]
    chosen = rng.choices(operators, weights=w, k=1)[0]

    if chosen == "swap_one":
        counts = swap_one(counts, card_db, rng)
    elif chosen == "swap_n":
        counts = swap_n(counts, card_db, rng, swap_n_range)
    elif chosen == "tweak_counts":
        counts = tweak_counts(counts, card_db, rng)
    else:
        raise ValueError(f"Unknown mutation operator: {chosen}")

    return counts_to_deck(deck.deck_id, counts)
