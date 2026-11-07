"""Reads the game's digital cards from a screenshot of the game area."""
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

# Every image is scaled to this width before reading, so templates work on any screen.
GAME_WIDTH = 1408
# Real indexes score 0.9+; a badge-covered first card ~0.83, table text below 0.8.
MIN_MATCH_SCORE = 0.8
# The simple J shape also fits the edge of the dealer's white shirt at ~0.80.
RANK_MIN_SCORE = {"J": 0.88}
WHITE_FRACTION = 0.5
TOP_ROW_TOLERANCE = 8
# Two matches closer than this (px) are the same glyph; the better score wins.
SAME_GLYPH_DISTANCE = 12
# Glyphs closer than this horizontally belong to the same hand (card step is ~29 px).
SAME_HAND_GAP = 45

# (x1, y1, x2, y2) in the normalized game area.
DEALER_REGION = (250, 330, 700, 420)
PLAYER_REGION = (450, 640, 1150, 740)
SHOE_BACK_REGION = (990, 480, 1040, 525)
# Center of the main-bet circle: an empty gray ring when watching, a colored chip when you bet.
BET_SPOT_REGION = (674, 800, 726, 852)
# Watching measured 0% colored pixels there, betting 20-50%.
MIN_CHIP_FRACTION = 0.1

# Physical cards: the dealer shows every card drawn for a player here, on the felt, for ~0.5 s.
# While you bet, cards drawn for others after you stand appear only here, never digitally.
FELT_REGION = (620, 545, 830, 650)
# A card is rectified to this size (px), so its rank corners are always at the same place.
FELT_CARD_WIDTH, FELT_CARD_HEIGHT = 60, 42
MIN_FELT_CARD_AREA = 800
# Leave-one-out on the first captures: right ranks scored 0.87+, wrong ones at most 0.84.
MIN_FELT_SCORE = 0.85
# Corners are matched with this much slack (px) for an imprecise card outline.
FELT_CORNER_SLACK = 3

# After a split the game draws both hands at ~80% size.
TEMPLATE_SCALES = (1.0, 0.8)
# (rank, scale, glyph image) for every rank at every scale.
Templates = list[tuple[str, float, np.ndarray]]

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "ranks"
FELT_TEMPLATES_DIR = TEMPLATES_DIR.parent / "felt"
# (rank, corner glyph) cut from rectified physical cards.
FeltTemplates = list[tuple[str, np.ndarray]]


@dataclass
class Glyph:
    rank: str
    x: int
    y: int
    score: float


@dataclass
class TableState:
    dealer: list[str]
    player: list[list[str]]
    # Every recognized index with its position in the normalized game area, for the debug picture.
    glyphs: list[Glyph] = field(default_factory=list)


def load_image(path: Path | str) -> np.ndarray:
    # np.fromfile handles non-ASCII paths (Polish "Zrzut ekranu ...") that cv2.imread cannot.
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


def load_templates() -> Templates:
    templates = []
    for path in TEMPLATES_DIR.glob("*.png"):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        for scale in TEMPLATE_SCALES:
            # "Q_live.png" is a second template for Q.
            rank = path.stem.split("_")[0]
            templates.append((rank, scale, cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)))
    return templates


def normalize(game_area: np.ndarray) -> np.ndarray:
    scale = GAME_WIDTH / game_area.shape[1]
    return cv2.resize(game_area, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def is_on_white_card(gray: np.ndarray, glyph: Glyph, template: np.ndarray) -> bool:
    """Rejects matches on table text (e.g. the J in "BLACKJACK"): around a real index the card is white.

    Checks only where the template itself is white, so a black glyph or the hand-total badge
    covering part of the first card's index does not reject it.
    """
    height, width = template.shape
    box = gray[glyph.y:glyph.y + height, glyph.x:glyph.x + width]
    background = template > 200
    return (box[background] > 200).mean() >= WHITE_FRACTION


def find_glyphs(gray: np.ndarray, templates: Templates) -> list[Glyph]:
    candidates = []
    for rank, _, template in templates:
        scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(scores >= RANK_MIN_SCORE.get(rank, MIN_MATCH_SCORE))
        for x, y in zip(xs, ys):
            glyph = Glyph(rank, int(x), int(y), float(scores[y, x]))
            if is_on_white_card(gray, glyph, template):
                candidates.append(glyph)

    kept: list[Glyph] = []
    for glyph in sorted(candidates, key=lambda g: -g.score):
        overlaps = any(abs(glyph.x - k.x) < SAME_GLYPH_DISTANCE and abs(glyph.y - k.y) < SAME_GLYPH_DISTANCE for k in kept)
        if not overlaps:
            kept.append(glyph)
    if not kept:
        return []

    # The last card also shows an upside-down index in its bottom corner; only the top row is real.
    top = min(g.y for g in kept)
    return sorted((g for g in kept if g.y - top <= TOP_ROW_TOLERANCE), key=lambda g: g.x)


def group_hands(glyphs: list[Glyph]) -> list[list[str]]:
    hands: list[list[Glyph]] = []
    for glyph in glyphs:
        if hands and glyph.x - hands[-1][-1].x < SAME_HAND_GAP:
            hands[-1].append(glyph)
        else:
            hands.append([glyph])
    return [[g.rank for g in hand] for hand in hands]


def read_region(game: np.ndarray, region: tuple[int, int, int, int], templates: Templates) -> list[Glyph]:
    x1, y1, x2, y2 = region
    gray = cv2.cvtColor(game[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    return [Glyph(g.rank, g.x + x1, g.y + y1, g.score) for g in find_glyphs(gray, templates)]


def shoe_color(game_area: np.ndarray) -> str | None:
    """Back color of the physical cards in the shoe; shoes alternate red/blue, so a change means a new shoe."""
    x1, y1, x2, y2 = SHOE_BACK_REGION
    hsv = cv2.cvtColor(normalize(game_area)[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    colored = hsv[..., 1] > 30
    hue = hsv[..., 0]
    red = (colored & (hue >= 160)).sum()
    blue = (colored & (hue >= 110) & (hue < 160)).sum()
    if red > 2 * blue:
        return "red"
    if blue > 2 * red:
        return "blue"
    return None  # Dealer's hand in front of the shoe, or a swap in progress.


def has_bet(game_area: np.ndarray) -> bool:
    """You have a chip on the main bet. Then the game shows only your own hand: after you stand,
    the cards drawn for players who still hit are not shown."""
    x1, y1, x2, y2 = BET_SPOT_REGION
    hsv = cv2.cvtColor(normalize(game_area)[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    colored = (hsv[..., 1] > 80) & (hsv[..., 2] > 90)
    return colored.mean() >= MIN_CHIP_FRACTION


def rectify_card(felt: np.ndarray) -> np.ndarray | None:
    """The biggest white card in the felt region, warped flat to FELT_CARD_WIDTH x FELT_CARD_HEIGHT (BGR).

    The camera sees the card as a rotated parallelogram; its 4 corners are mapped so the long
    edge is horizontal. None when no card is there (or only a sleeve or a covered scrap).
    """
    hsv = cv2.cvtColor(felt, cv2.COLOR_BGR2HSV)
    white = ((hsv[..., 1] < 60) & (hsv[..., 2] > 160)).astype(np.uint8)
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    outline = max(contours, key=cv2.contourArea)
    if cv2.contourArea(outline) < MIN_FELT_CARD_AREA:
        return None
    hull = cv2.convexHull(outline)
    corners = cv2.approxPolyDP(hull, 0.04 * cv2.arcLength(hull, True), True).reshape(-1, 2).astype(np.float32)
    if len(corners) != 4:
        corners = cv2.boxPoints(cv2.minAreaRect(outline))
    center = corners.mean(axis=0)
    corners = np.array(sorted(corners, key=lambda p: np.arctan2(p[1] - center[1], p[0] - center[0])), np.float32)
    # The top edge: the highest one of the edges that run left to right.
    top_edges = [(corners[i][1] + corners[(i + 1) % 4][1], i) for i in range(4)
                 if corners[(i + 1) % 4][0] - corners[i][0] > abs(corners[(i + 1) % 4][1] - corners[i][1])]
    if not top_edges:
        return None
    first = min(top_edges)[1]
    source = np.float32([corners[(first + k) % 4] for k in range(4)])
    width, height = FELT_CARD_WIDTH, FELT_CARD_HEIGHT
    target = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    return cv2.warpPerspective(felt, cv2.getPerspectiveTransform(source, target), (width, height))


def rank_corners(card: np.ndarray) -> list[np.ndarray]:
    """Both rank indexes of a rectified card (grayscale), turned the same way up."""
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    return [gray[20:42, 36:60], cv2.rotate(gray[0:22, 0:24], cv2.ROTATE_180)]


def load_felt_templates() -> FeltTemplates:
    """Each file is a rectified card ("K_222032.png" is a K); its bottom-right index is the template."""
    templates = []
    slack = FELT_CORNER_SLACK
    for path in FELT_TEMPLATES_DIR.glob("*.png"):
        corner = rank_corners(cv2.imread(str(path)))[0]
        templates.append((path.stem.split("_")[0], corner[slack:-slack, slack:-slack]))
    return templates


def read_felt_card(felt: np.ndarray, templates: FeltTemplates) -> tuple[str | None, float] | None:
    """(rank, score) of the physical card on the felt; rank None when a card is there but unreadable
    (finger, motion blur). None when there is no card."""
    card = rectify_card(felt)
    if card is None:
        return None
    corners = rank_corners(card)
    score, rank = max((float(cv2.matchTemplate(corner, template, cv2.TM_CCOEFF_NORMED).max()), rank)
                      for rank, template in templates for corner in corners)
    return (rank if score >= MIN_FELT_SCORE else None), score


def read_table(game_area: np.ndarray, templates: Templates) -> TableState:
    game = normalize(game_area)
    # The dealer never splits, so the small split-size templates would only add false matches there.
    dealer_glyphs = read_region(game, DEALER_REGION, [t for t in templates if t[1] == 1.0])
    player_glyphs = read_region(game, PLAYER_REGION, templates)
    dealer = [g.rank for g in dealer_glyphs]
    return TableState(dealer, group_hands(player_glyphs), dealer_glyphs + player_glyphs)


# cv2.putText draws ASCII only.
ASCII_LETTERS = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ–→×·", "acelnoszzACELNOSZZ->x.")
GLYPH_BOX = (22, 25)
CAPTION_LINE_HEIGHT = 26


def draw_debug(game: np.ndarray, table: TableState, caption: list[str]) -> np.ndarray:
    """Normalized game picture with what the program saw: search regions, read indexes, and a caption below."""
    picture = game.copy()
    for (x1, y1, x2, y2), color, label in (
        (DEALER_REGION, (0, 220, 255), "krupier"),
        (PLAYER_REGION, (255, 200, 0), "gracz"),
        (SHOE_BACK_REGION, (255, 0, 255), "but"),
    ):
        cv2.rectangle(picture, (x1, y1), (x2, y2), color, 1)
        cv2.putText(picture, label, (x1 + 3, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    width, height = GLYPH_BOX
    for glyph in table.glyphs:
        cv2.rectangle(picture, (glyph.x - 2, glyph.y - 2), (glyph.x + width, glyph.y + height), (0, 255, 0), 2)
        cv2.putText(picture, glyph.rank, (glyph.x, glyph.y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)

    bar = np.full((CAPTION_LINE_HEIGHT * len(caption) + 12, picture.shape[1], 3), 20, np.uint8)
    for index, line in enumerate(caption):
        y = CAPTION_LINE_HEIGHT * (index + 1)
        cv2.putText(bar, line.translate(ASCII_LETTERS), (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (235, 235, 235), 1, cv2.LINE_AA)
    return np.vstack([picture, bar])
