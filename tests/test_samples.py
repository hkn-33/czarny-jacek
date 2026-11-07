"""Reads the screenshots in samples/ and checks cards and the count. Run: python -m tests.test_samples"""
from pathlib import Path

import cv2
import numpy as np

from czarny_jacek.calibration import find_game_area
from czarny_jacek.shoe import ROUND_END_FRAMES, RoundTracker, Shoe
from czarny_jacek.vision import (Glyph, dealer_row, felt_rank, has_bet, load_felt_templates, load_image, load_templates,
                                 read_felt_card, read_table, shoe_color)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
# Game area inside the author's 1920x1032 browser-window screenshots.
GAME_AREA = (slice(115, 1032), slice(285, 1693))

EXPECTED = {
    "164741": (["9"], [["2", "10", "J"]]),
    "164837": (["10"], [["2", "4", "10", "5"]]),
    "164919": (["10"], [["7", "3", "K"]]),
    "165029": (["3", "10"], [["8", "5", "6"]]),
    "165121": (["4", "4"], [["3", "10", "2"]]),
    "164748": ([], []),
}


# Live captures (already the game area). The first card's index is partly covered by the hand-total badge.
LIVE_EXPECTED = {
    "live-172729-365": (["7"], [["8", "5", "3"]]),
    "live-173108-171": (["3"], [["3", "A"]]),
    # Split: both hands drawn at ~80% size.
    "live-173723-961": (["3", "8"], [["10", "5", "3"], ["Q", "5"]]),
    "live-174430-493": (["K", "5"], [["Q", "9"], ["K", "7"]]),
    # Split with the first card's index mostly under the hand-total badge.
    "live-split-221415-595": (["7", "4"], [["J", "Q"], ["K", "8"]]),
    "live-split-221509-829": (["3"], [["Q", "2"], ["J", "K"]]),
    # A player with a bet: only their own hand is shown.
    "live-betting-201509-359": (["7"], [["2", "6", "6", "K"], ["2", "6", "A", "5"]]),
}


def read_sample(path: Path, templates):
    return read_table(load_image(path)[GAME_AREA], templates)


def test_reads_cards() -> None:
    templates = load_templates()
    for stamp, (dealer, player) in EXPECTED.items():
        table = read_sample(SAMPLES / f"Zrzut ekranu 2026-11-02 {stamp}.png", templates)
        assert (table.dealer, table.player) == (dealer, player), (stamp, table)
    for name, (dealer, player) in LIVE_EXPECTED.items():
        table = read_table(load_image(SAMPLES / f"{name}.png"), templates)
        assert (table.dealer, table.player) == (dealer, player), (name, table)


def test_counts_five_rounds() -> None:
    templates = load_templates()
    shoe = Shoe()
    tracker = RoundTracker(shoe)
    for path in sorted(SAMPLES.glob("Zrzut ekranu 2026-11-02 16*.png")):
        table = read_sample(path, templates)
        for _ in range(ROUND_END_FRAMES):
            tracker.update(table.dealer + [rank for hand in table.player for rank in hand])
    assert shoe.cards_seen == 23, shoe.cards_seen
    assert shoe.running_count == 4, shoe.running_count


def test_finds_game_on_other_screen_sizes() -> None:
    """The game is found and read on a smaller and a bigger screen than the author's."""
    templates = load_templates()
    screenshot = load_image(SAMPLES / "Zrzut ekranu 2026-11-02 165121.png")
    for scale in (0.7, 1.33):
        resized = cv2.resize(screenshot, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        screen = np.zeros((resized.shape[0] + 300, resized.shape[1] + 300, 3), np.uint8)
        screen[150:150 + resized.shape[0], 150:150 + resized.shape[1]] = resized
        found = find_game_area(screen)
        assert found is not None, scale
        rect, _ = found
        game = screen[rect["top"]:rect["top"] + rect["height"], rect["left"]:rect["left"] + rect["width"]]
        table = read_table(game, templates)
        assert (table.dealer, table.player) == (["4", "4"], [["3", "10", "2"]]), (scale, table)
        assert shoe_color(game) == "blue", scale


def test_detects_own_bet() -> None:
    assert has_bet(load_image(SAMPLES / "live-betting-201509-359.png"))
    for path in SAMPLES.glob("live-1*.png"):
        assert not has_bet(load_image(path)), path


# Felt spot crops, none of them used for the templates. None = no card there.
FELT_EXPECTED = {"222547-853": "10", "222827-626": "7", "222942-252": "7", "222653-389": "A", "223016-176": None}


def test_reads_felt_cards() -> None:
    templates = load_felt_templates()
    for stamp, rank in FELT_EXPECTED.items():
        reading = read_felt_card(load_image(SAMPLES / f"felt-{stamp}.png"), templates)
        assert (reading and reading[0]) == rank, (stamp, reading)


def test_dealer_row_ignores_shirt() -> None:
    """Live 20:50:54: a J matched on the dealer's white shirt, above and right of his real 4, hid the 4."""
    real_four = Glyph("4", 306, 364, 0.94)
    shirt_j = Glyph("J", 608, 330, 0.88)
    assert dealer_row([shirt_j, real_four]) == [real_four]
    assert dealer_row([shirt_j]) == []
    row = [Glyph(rank, x, 364, 0.95) for rank, x in (("4", 306), ("4", 334), ("2", 363), ("3", 392), ("9", 421))]
    upside_down_index = Glyph("9", 440, 405, 0.9)
    assert dealer_row(row + [upside_down_index, shirt_j]) == row


def test_felt_rank_needs_clear_winner() -> None:
    """Live 20:50:59: a finger-covered J of diamonds scored 0.88 as both 3 and J, and the 3 was counted."""
    assert felt_rank({"3": 0.88, "J": 0.88, "7": 0.74}) is None
    assert felt_rank({"7": 0.95, "2": 0.82}) == "7"
    # K and 10 look alike on the felt, but both are worth 10, so a close call between them is fine.
    assert felt_rank({"K": 0.93, "10": 0.91, "3": 0.6}) == "K"
    assert felt_rank({"8": 0.76, "K": 0.71}) is None


if __name__ == "__main__":
    test_felt_rank_needs_clear_winner()
    test_dealer_row_ignores_shirt()
    test_reads_cards()
    test_counts_five_rounds()
    test_finds_game_on_other_screen_sizes()
    test_detects_own_bet()
    test_reads_felt_cards()
    print("samples ok")
