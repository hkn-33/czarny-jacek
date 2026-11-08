"""One Polish sentence on why the advised move is right, for a casual player who sees the cards anyway."""
from czarny_jacek.strategy import DEVIATIONS, DOUBLE, HIT, SPLIT, STAND, advise, card_value, hand_total

# How often the dealer busts, by upcard (%): 8 decks, stands on soft 17, no hole card (rounded, Wizard of Odds).
DEALER_BUST_PERCENT = {2: 35, 3: 38, 4: 40, 5: 43, 6: 42, 7: 26, 8: 24, 9: 23, 10: 21, 11: 17}
VERBS = {HIT: "dobrać", STAND: "stać", DOUBLE: "podwoić", SPLIT: "rozdzielić"}


def bust_percent(hard_total: int) -> int:
    """Chance that one more card busts a hard hand, for a fresh shoe: 2-9 are 1/13 each, ten-valued cards 4/13."""
    busting_values = [value for value in range(2, 11) if value > 21 - hard_total]
    weight = sum(4 if value == 10 else 1 for value in busting_values)
    return round(100 * weight / 13)


def deviation_reason(total: int, dealer: int, action: str, true_count: float) -> str | None:
    if (total, dealer) not in DEVIATIONS:
        return None
    threshold, at_or_above, _ = DEVIATIONS[(total, dealer)]
    if true_count < threshold or action != at_or_above:
        return None
    return f"Wyjątek przy przewadze od {threshold_text(threshold)}: opłaca się {VERBS[action]}."


def threshold_text(threshold: int) -> str:
    return "0" if threshold == 0 else f"{threshold:+d}"


def why(hand: list[str], dealer_up: str, true_count: float) -> str:
    action = advise(hand, dealer_up, true_count)
    dealer = card_value(dealer_up)
    dealer_bust = DEALER_BUST_PERCENT[dealer]
    total, soft = hand_total(hand)

    if action == SPLIT:
        if hand[0] in ("A", "8"):
            return "Asy i ósemki zawsze rozdzielaj."
        if card_value(hand[0]) == 10:
            return "Wyjątek przy dużej przewadze: rozdziel dziesiątki."
        return f"Dwie ręce od {hand[0]} są lepsze niż {total}."
    if not soft:
        reason = deviation_reason(total, dealer, action, true_count)
        if reason:
            return reason
    if action == DOUBLE:
        if soft:
            return f"Nie spalisz się, a krupier z {dealer_up} furuje w {dealer_bust}%."
        return f"Z {total} duża karta da 19–21. Dostaniesz jedną kartę."
    if soft:
        if action == HIT:
            return "Miękka ręka: As stanie się 1, nie spalisz się."
        return f"Miękkie {total} to dobra ręka."
    if action == HIT:
        if total <= 11:
            return "Żadna karta Cię nie spali."
        if dealer <= 6:
            return f"Spalisz się tylko w {bust_percent(total)}%, a {total} rzadko wygrywa."
        return f"Krupier z {dealer_up} zwykle ma 17+. Z {total} przegrasz."
    if total >= 17:
        return f"Dobierając spalisz się w {bust_percent(total)}%."
    return f"Krupier z {dealer_up} furuje w {dealer_bust}%, Ty po dobraniu w {bust_percent(total)}%."


if __name__ == "__main__":
    # 16 against a 10 with a positive count is a deviation: the reason must say so.
    assert "przewad" in why(["10", "6"], "10", 1.0)
    assert "42%" in why(["10", "4"], "6", 0.0), why(["10", "4"], "6", 0.0)
    assert "As" in why(["A", "7"], "10", 0.0)
    assert "nie spali" in why(["6", "3"], "10", 0.0)
    # Short enough for one or two overlay lines.
    for hand, up in ((["10", "4"], "6"), (["A", "7"], "4"), (["10", "2"], "3"), (["10", "6"], "10")):
        assert len(why(hand, up, 0.0)) <= 60, why(hand, up, 0.0)
    assert "17+" in why(["10", "6"], "9", -1.0)
    assert "Asy i ósemki" in why(["8", "8"], "10", 0.0)
    assert why(["6", "5"], "10", 0.0).startswith("Z 11"), why(["6", "5"], "10", 0.0)
    for hand, up in ((["10", "7"], "10"), (["10", "2"], "3"), (["A", "6"], "5"), (["9", "9"], "8")):
        assert why(hand, up, 0.0), (hand, up)
    print("explain ok")
