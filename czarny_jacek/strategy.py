"""Basic strategy (8 decks, dealer stands on soft 17, double after split) plus Illustrious 18 deviations."""
from collections import Counter

HIT, STAND, DOUBLE, SPLIT = "HIT", "STAND", "DOUBLE", "SPLIT"
INSURANCE_TRUE_COUNT = 3


def card_value(rank: str) -> int:
    if rank == "A":
        return 11
    if rank in ("J", "Q", "K"):
        return 10
    return int(rank)


def hand_total(ranks: list[str]) -> tuple[int, bool]:
    """Returns (best total, is_soft)."""
    total = sum(card_value(r) for r in ranks)
    aces = ranks.count("A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def bust_chance(ranks: list[str], remaining: Counter) -> float:
    total, soft = hand_total(ranks)
    if soft:
        return 0.0
    cards_left = sum(remaining.values())
    if cards_left == 0:
        return 0.0
    # An ace counts as 1 here, so it never busts a hard hand below 21.
    busting = sum(count for rank, count in remaining.items() if rank != "A" and card_value(rank) + total > 21)
    return busting / cards_left


# (hard total, dealer upcard value) -> (true count threshold, action at or above it, action below it)
DEVIATIONS = {
    (16, 10): (0, STAND, HIT),
    (15, 10): (4, STAND, HIT),
    (10, 10): (4, DOUBLE, HIT),
    (12, 3): (2, STAND, HIT),
    (12, 2): (3, STAND, HIT),
    (11, 11): (1, DOUBLE, HIT),
    (9, 2): (1, DOUBLE, HIT),
    (10, 11): (4, DOUBLE, HIT),
    (9, 7): (3, DOUBLE, HIT),
    (16, 9): (5, STAND, HIT),
    (13, 2): (-1, STAND, HIT),
    (12, 4): (0, STAND, HIT),
    (12, 5): (-2, STAND, HIT),
    (12, 6): (-1, STAND, HIT),
    (13, 3): (-2, STAND, HIT),
}
# Splitting tens vs 5 and 6 at high counts.
TEN_SPLIT_DEVIATIONS = {5: 5, 6: 4}


def basic_hard(total: int, dealer: int) -> str:
    if total <= 8:
        return HIT
    if total == 9:
        return DOUBLE if 3 <= dealer <= 6 else HIT
    if total == 10:
        return DOUBLE if dealer <= 9 else HIT
    if total == 11:
        return DOUBLE if dealer <= 10 else HIT
    if total == 12:
        return STAND if 4 <= dealer <= 6 else HIT
    if total <= 16:
        return STAND if dealer <= 6 else HIT
    return STAND


def basic_soft(total: int, dealer: int) -> str:
    if total in (13, 14):
        return DOUBLE if dealer in (5, 6) else HIT
    if total in (15, 16):
        return DOUBLE if 4 <= dealer <= 6 else HIT
    if total == 17:
        return DOUBLE if 3 <= dealer <= 6 else HIT
    if total == 18:
        if 3 <= dealer <= 6:
            return DOUBLE
        return STAND if dealer in (2, 7, 8) else HIT
    return STAND


def should_split(pair_value: int, dealer: int, true_count: float) -> bool:
    if pair_value in (11, 8):
        return True
    if pair_value in (2, 3, 7):
        return dealer <= 7
    if pair_value == 4:
        return dealer in (5, 6)
    if pair_value == 6:
        return dealer <= 6
    if pair_value == 9:
        return dealer not in (7, 10, 11)
    if pair_value == 10:
        return dealer in TEN_SPLIT_DEVIATIONS and true_count >= TEN_SPLIT_DEVIATIONS[dealer]
    return False


def advise(player: list[str], dealer_up: str, true_count: float) -> str:
    dealer = card_value(dealer_up)
    two_cards = len(player) == 2
    if two_cards and card_value(player[0]) == card_value(player[1]):
        if should_split(card_value(player[0]), dealer, true_count):
            return SPLIT

    total, soft = hand_total(player)
    if soft:
        action = basic_soft(total, dealer)
    elif (total, dealer) in DEVIATIONS:
        threshold, at_or_above, below = DEVIATIONS[(total, dealer)]
        action = at_or_above if true_count >= threshold else below
    else:
        action = basic_hard(total, dealer)

    if action == DOUBLE and not two_cards:
        # Soft 18 that cannot double stands; everything else hits.
        return STAND if soft and total == 18 else HIT
    return action


WIN, LOSS, PUSH, BLACKJACK = "WIN", "LOSS", "PUSH", "BLACKJACK"
DEALER_STANDS_ON = 17


def is_blackjack(ranks: list[str]) -> bool:
    return len(ranks) == 2 and hand_total(ranks)[0] == 21


def round_result(player: list[str], dealer: list[str], split: bool) -> str | None:
    """Outcome of one player hand, or None while the round is still being played."""
    player_total, _ = hand_total(player)
    if player_total > 21:
        return LOSS
    dealer_total, _ = hand_total(dealer)
    dealer_done = len(dealer) >= 2 and dealer_total >= DEALER_STANDS_ON
    if not dealer_done:
        return None
    # A two-card 21 after a split pays as a normal 21, not as blackjack.
    player_blackjack = is_blackjack(player) and not split
    if is_blackjack(dealer):
        return PUSH if player_blackjack else LOSS
    if player_blackjack:
        return BLACKJACK
    if dealer_total > 21 or player_total > dealer_total:
        return WIN
    return PUSH if player_total == dealer_total else LOSS


def play_by_advice(cards: list[str], dealer_up: str, true_count: float) -> tuple[list[str], bool, bool]:
    """The hand of a player who follows the advice, out of the shared hand's cards.

    All Bets: everyone gets the same cards, but each player decides alone. The table keeps drawing
    for players who still hit, so a player who stood earlier keeps fewer cards.
    Returns (your cards, doubled, finished deciding). A split the table did not make is played as a hit.
    """
    hand = cards[:2]
    next_card = 2
    while hand_total(hand)[0] < 21:
        action = advise(hand, dealer_up, true_count)
        if action == STAND:
            break
        if next_card >= len(cards):
            return hand, False, False
        hand = hand + [cards[next_card]]
        next_card += 1
        if action == DOUBLE:
            return hand, True, True
    return hand, False, True


def your_hands(table_hands: list[list[str]], dealer_up: str, true_count: float) -> list[list[str]]:
    """Your hands' cards out of the table's. When the table splits a pair you were told not to split,
    you keep the pair as one hand; the cards drawn to the split hands follow it in deal order."""
    if len(table_hands) < 2:
        return table_hands
    pair = [hand[0] for hand in table_hands[:2]]
    if advise(pair, dealer_up, true_count) == SPLIT:
        return table_hands
    later_cards = [card for hand in table_hands[:2] for card in hand[1:]]
    later_cards += [card for hand in table_hands[2:] for card in hand]
    return [pair + later_cards]


def bet_units(true_count: float) -> int:
    """Player edge is roughly (TC - 1) * 0.5%; bet 1 unit until the edge turns positive."""
    return max(1, min(8, int(true_count)))


if __name__ == "__main__":
    assert advise(["10", "6"], "10", -1) == HIT
    assert advise(["10", "6"], "K", 0) == STAND
    assert advise(["8", "8"], "A", 0) == SPLIT
    assert advise(["6", "5"], "Q", 0) == DOUBLE
    assert advise(["6", "3", "2"], "Q", 0) == HIT
    assert advise(["A", "7"], "4", 0) == DOUBLE
    assert advise(["A", "4", "3"], "4", 0) == STAND
    assert advise(["K", "Q"], "6", 4) == SPLIT
    assert advise(["K", "Q"], "6", 3) == STAND
    assert hand_total(["A", "A", "9"]) == (21, True)
    assert hand_total(["A", "K", "5"]) == (16, False)
    deck = Counter({"10": 4, "5": 4})
    assert bust_chance(["10", "6"], deck) == 0.5
    assert round_result(["10", "6", "K"], ["5"], False) == LOSS
    assert round_result(["10", "7"], ["5"], False) is None
    assert round_result(["10", "7"], ["5", "10", "8"], False) == WIN
    assert round_result(["10", "7"], ["10", "7"], False) == PUSH
    assert round_result(["A", "K"], ["10", "7"], False) == BLACKJACK
    assert round_result(["A", "K"], ["10", "7"], True) == WIN
    assert round_result(["10", "9"], ["A", "K"], False) == LOSS
    assert round_result(["10", "6"], ["A", "6"], False) == LOSS  # dealer stands on soft 17
    assert play_by_advice(["10", "6", "K"], "5", 0) == (["10", "6"], False, True)
    assert play_by_advice(["10", "2", "K"], "9", 0) == (["10", "2", "K"], False, True)
    assert play_by_advice(["10", "2"], "9", 0) == (["10", "2"], False, False)
    assert play_by_advice(["6", "5", "3", "9"], "Q", 0) == (["6", "5", "3"], True, True)
    # Live 21:03: you were told to stand on Q K, the table split anyway. You still hold Q K.
    assert your_hands([["Q", "J"], ["K", "J"]], "9", 0) == [["Q", "K", "J", "J"]]
    assert play_by_advice(your_hands([["Q", "6", "8"], ["10", "K"]], "J", 0)[0], "J", 0) == (["Q", "10"], False, True)
    assert your_hands([["8", "3"], ["8", "K"]], "6", 0) == [["8", "3"], ["8", "K"]], "a split you were told to make"
    assert your_hands([["10", "6", "K"]], "5", 0) == [["10", "6", "K"]]
    print("strategy ok")
