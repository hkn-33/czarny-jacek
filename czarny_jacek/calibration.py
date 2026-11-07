"""Finds the game area on screen by locating text printed on the table felt at any scale."""
from pathlib import Path

import cv2
import numpy as np

from czarny_jacek.vision import GAME_WIDTH

ANCHOR_PATH = Path(__file__).resolve().parent.parent / "templates" / "felt_anchor.png"
# Anchor = "BLACKJACK PAYS 3 TO 2" on the felt. The top bar can't be the anchor: it keeps its size in full screen
# while the table and cards grow (measured 1.17x), so the game area came out too small and shifted.
# Position and game height are in the normalized game area (width GAME_WIDTH).
ANCHOR_POSITION = (830, 658)
GAME_HEIGHT = 917
MIN_ANCHOR_SCORE = 0.7
# Game width from about 700 px (half of the reference) to 3500 px (full screen on 4K).
COARSE_SCALES = np.arange(0.5, 2.51, 0.05)
FINE_STEP = 0.005
COARSE_DOWNSCALE = 0.5


def best_match(gray: np.ndarray, anchor: np.ndarray, scales) -> tuple[float, float, tuple[int, int]]:
    """Returns (score, scale, top-left of the anchor) for the best scale."""
    best = (-1.0, 1.0, (0, 0))
    for scale in scales:
        template = cv2.resize(anchor, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
            continue
        scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(scores)
        if score > best[0]:
            best = (float(score), float(scale), location)
    return best


def find_game_area(screen: np.ndarray) -> tuple[dict, float] | None:
    """Returns the game rect in screen pixels and the match score, or None if the game is not visible."""
    anchor = cv2.imread(str(ANCHOR_PATH), cv2.IMREAD_GRAYSCALE)
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)

    # Coarse search on a half-size screenshot keeps calibration around a second.
    small = cv2.resize(gray, None, fx=COARSE_DOWNSCALE, fy=COARSE_DOWNSCALE, interpolation=cv2.INTER_AREA)
    _, coarse_scale, (cx, cy) = best_match(small, anchor, COARSE_SCALES * COARSE_DOWNSCALE)
    coarse_scale /= COARSE_DOWNSCALE
    cx, cy = int(cx / COARSE_DOWNSCALE), int(cy / COARSE_DOWNSCALE)

    # Fine search at full resolution, only around the coarse hit.
    margin = 40
    x1, y1 = max(cx - margin, 0), max(cy - margin, 0)
    x2 = cx + int(anchor.shape[1] * (coarse_scale + 0.05)) + margin
    y2 = cy + int(anchor.shape[0] * (coarse_scale + 0.05)) + margin
    fine_scales = np.arange(coarse_scale - 0.05, coarse_scale + 0.05, FINE_STEP)
    score, scale, (fx, fy) = best_match(gray[y1:y2, x1:x2], anchor, fine_scales)
    if score < MIN_ANCHOR_SCORE:
        return None

    anchor_x, anchor_y = ANCHOR_POSITION
    rect = {
        "left": int(round(x1 + fx - anchor_x * scale)),
        "top": int(round(y1 + fy - anchor_y * scale)),
        "width": int(round(GAME_WIDTH * scale)),
        "height": int(round(GAME_HEIGHT * scale)),
    }
    return rect, score
