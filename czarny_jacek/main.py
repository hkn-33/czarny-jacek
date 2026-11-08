"""Control panel finds the game on screen and shows a log; the overlay counts cards and shows the suggested move."""
import ctypes
import os
import re
import sys
import time
import traceback
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import cv2
import mss
import numpy as np
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from czarny_jacek.calibration import find_game_area
from czarny_jacek.explain import why
from czarny_jacek.shoe import HiddenCards, RoundTracker, Shoe
from czarny_jacek.strategy import (
    BLACKJACK,
    DOUBLE,
    HIT,
    LOSS,
    PUSH,
    WIN,
    INSURANCE_TRUE_COUNT,
    SPLIT,
    STAND,
    advise,
    bet_units,
    hand_total,
    is_blackjack,
    play_by_advice,
    round_result,
    your_hands,
)
from czarny_jacek.vision import (
    FELT_REGION,
    GAME_WIDTH,
    TableState,
    draw_debug,
    has_bet,
    load_felt_templates,
    load_templates,
    normalize,
    read_felt_card,
    read_table,
    shoe_color,
)

FRAME_INTERVAL_MS = 200
# Each run gets a folder with log.txt, raw game screenshots (to re-test reading) and described ones.
# Next to the .exe when frozen (PyInstaller unpacks the code to a temp folder that is deleted on exit).
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
CAPTURES_DIR = APP_DIR / "captures"
# The shoe color must hold this long (frames) before we believe a shoe swap happened.
SHOE_SWAP_FRAMES = 10
# During a swap both shoes are on the table and the color flips back and forth; ignore changes this long after a swap.
SHOE_SWAP_COOLDOWN_SECONDS = 120
# A card lies on the felt for only ~0.5 s, so that small spot is read much more often than the table.
FELT_INTERVAL_MS = 25
# Felt cards are saved (at most this often) to check the reading and to add templates for unseen ranks.
FELT_SAVE_SECONDS = 0.1
CALIBRATION_ATTEMPTS = 5
CALIBRATION_RETRY_SECONDS = 0.5
WDA_EXCLUDEFROMCAPTURE = 0x11
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOMOVE_NOSIZE_NOACTIVATE = 0x0002 | 0x0001 | 0x0010

# UI text is Polish for the end user.
MOVE_NAMES = {HIT: "DOBIERZ", STAND: "STÓJ", DOUBLE: "PODWÓJ", SPLIT: "ROZDZIEL"}
RESULT_NAMES = {WIN: "WYGRANA", BLACKJACK: "BLACKJACK!", LOSS: "PRZEGRANA", PUSH: "REMIS"}
# One hue per answer, readable on dark glass over a busy video.
MOVE_COLORS = {HIT: "#6cb4ff", STAND: "#4ade94", DOUBLE: "#fbbf3c", SPLIT: "#c79bff"}
RESULT_COLORS = {WIN: "#4ade94", BLACKJACK: "#4ade94", LOSS: "#ff7a7a", PUSH: "#d6dae4"}
IDLE_COLOR = "#8b92a5"
POSITIVE, NEGATIVE, NEUTRAL = "#4ade94", "#ff7a7a", "#eef0f5"
# Sizes below are for a game 1408 px wide; the overlay grows with the game (big screens, Windows scaling).
# It never changes size while running: a window that jumps while you read it is worse than a cut-off long hand.
OVERLAY_WIDTH = 316
MAX_UI_SCALE = 2.5
# Room for two hands (a split) below the dealer.
PLAYER_ROWS_SHOWN = 2
CARD_ROW_HEIGHT = 32
# Counted cards that fit on one line; more are summed up as "+N".
ROUND_CARDS_SHOWN = 12
# Gap between the overlay and the game's bottom-left corner when it first appears.
OVERLAY_MARGIN = 16
SHOE_COLOR_NAMES = {"red": "czerwona", "blue": "niebieska"}
# The card backs' color in the shoe, shown as a swatch: a new shoe is a new color.
SHOE_SWATCH_COLORS = {"red": "#e5484d", "blue": "#4c8dff"}
UNKNOWN_SHOE_COLOR = "rgba(238, 240, 245, 60)"
# How long the overlay flags a shoe swap.
NEW_SHOE_BADGE_SECONDS = 90
BAND_TEXT = "#0b0d12"

OVERLAY_STYLE = """
#glass { background: rgba(11, 13, 18, 150); border: 1px solid rgba(255, 255, 255, 22); border-radius: 16px; }
QLabel { color: #eef0f5; font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; background: transparent; }
#move { font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-weight: 800; border-radius: 10px; }
#situation { color: rgba(238, 240, 245, 215); font-size: 13px; }
#side { color: rgba(238, 240, 245, 130); font-size: 11px; font-weight: 600; min-width: 46px; }
#total { font-size: 15px; font-weight: 700; }
#card { background: #f5f2ea; color: #15171c; font-size: 15px; font-weight: 800; border-radius: 4px;
        min-width: 21px; max-width: 21px; min-height: 29px; max-height: 29px; qproperty-alignment: AlignCenter; }
#miniCard { background: rgba(245, 242, 234, 215); color: #15171c; font-size: 10px; font-weight: 800; border-radius: 3px;
            min-width: 14px; max-width: 14px; min-height: 19px; max-height: 19px; qproperty-alignment: AlignCenter; }
#empty { color: rgba(238, 240, 245, 90); font-size: 13px; }
#statLabel { color: rgba(238, 240, 245, 130); font-size: 11px; font-weight: 600; }
#statValue { font-size: 15px; font-weight: 700; }
#rule { background: rgba(255, 255, 255, 20); min-height: 1px; max-height: 1px; }
#detail { color: rgba(238, 240, 245, 185); font-size: 12px; }
#swatch { border-radius: 3px; min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px; }
#badge { background: #fbbf3c; color: #0b0d12; font-size: 10px; font-weight: 800; border-radius: 4px; padding: 1px 6px; }
QToolTip { color: #eef0f5; background: #171a21; border: 1px solid #2a2e38; padding: 6px; }
QMenu { background: #171a21; color: #eef0f5; border: 1px solid #2a2e38; padding: 4px; font-family: 'Segoe UI'; font-size: 13px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #262a34; }
"""

PANEL_STYLE = """
QWidget { background: #0f1115; color: #eef0f5; font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 14px; }
#title { font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 28px; font-weight: 700; }
#lead { color: #a3a9b8; font-size: 14px; }
#stepNumber { background: #1d2028; color: #eef0f5; border-radius: 13px; font-size: 13px; font-weight: 700;
              min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; qproperty-alignment: AlignCenter; }
#stepText { color: #d6dae4; padding-top: 3px; }
#start { background: #4ade94; color: #0b1a12; border: none; border-radius: 10px; padding: 13px;
         font-size: 15px; font-weight: 700; }
#start:hover { background: #6ae8a8; }
#start:pressed { background: #36c47e; }
#status { color: #a3a9b8; font-size: 13px; }
#status[state="error"] { color: #ff7a7a; }
#status[state="ok"] { color: #4ade94; }
#link { background: transparent; color: #a3a9b8; border: none; padding: 4px 0; font-size: 13px; text-align: left; }
#link:hover { color: #eef0f5; }
QPlainTextEdit { background: #090a0d; color: #a3a9b8; border: 1px solid #1d2028; border-radius: 10px;
                 font-family: 'Cascadia Mono', Consolas; font-size: 12px; padding: 6px; }
"""


def exclude_from_capture(widget: QWidget) -> bool:
    """Our own windows stay out of screenshots, so they can sit on top of the game.
    Fails on older Windows (before 10 version 2004); then the window is captured like the game."""
    return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE))


def locate_game(log: Callable[[str], None]) -> dict | None:
    """Takes a few screenshots of all monitors and returns the game rect, or None."""
    with mss.MSS() as screen:
        desktop = screen.monitors[0]
        log(f"Ekran (wszystkie monitory): {desktop['width']}x{desktop['height']}")
        for attempt in range(1, CALIBRATION_ATTEMPTS + 1):
            image = np.array(screen.grab(desktop))[:, :, :3]
            found = find_game_area(image)
            if found is not None:
                rect, score = found
                rect["left"] += desktop["left"]
                rect["top"] += desktop["top"]
                log(f"Gra znaleziona (próba {attempt}, dopasowanie {score:.2f}): {rect}")
                return rect
            log(f"Próba {attempt}: nie widzę gry")
            time.sleep(CALIBRATION_RETRY_SECONDS)
    return None


def hand_text(hand: list[str], split: bool = False) -> str:
    # A two-card 21 after a split is a plain 21, not a blackjack.
    if is_blackjack(hand) and not split:
        return "BLACKJACK"
    total, soft = hand_total(hand)
    if total > 21:
        return "fura"
    return f"{'miękkie ' if soft else ''}{total}"


STEPS = (
    "Otwórz stół Total Casino All Bets Blackjack.",
    "Włącz pełny ekran przeglądarki (F11), żeby cały stół był widoczny.",
    "Kliknij Uruchom. Nakładka pojawi się w lewym dolnym rogu gry.",
)


def step_row(number: int, text: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    row.addWidget(QLabel(str(number), objectName="stepNumber"), 0, Qt.AlignmentFlag.AlignTop)
    row.addWidget(QLabel(text, objectName="stepText", wordWrap=True), 1, Qt.AlignmentFlag.AlignTop)
    return row


class ControlPanel(QWidget):
    """Stays open (e.g. on a second monitor): start button, status, and a log hidden until asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Czarny Jacek")
        self.setStyleSheet(PANEL_STYLE)
        self.setFixedWidth(480)
        self.overlay: Overlay | None = None
        self.session_dir = CAPTURES_DIR / f"{datetime.now():%Y%m%d-%H%M%S}"
        self.session_dir.mkdir(parents=True)

        title = QLabel("Czarny Jacek", objectName="title")
        lead = QLabel("Podpowiada, kiedy dobrać, a kiedy stać, i liczy karty, żebyś wiedział, kiedy grać wyżej.",
                      objectName="lead", wordWrap=True)
        start = QPushButton("Uruchom", objectName="start", cursor=Qt.CursorShape.PointingHandCursor)
        start.clicked.connect(self.start)
        self.status = QLabel("", objectName="status", wordWrap=True)
        self.log_box = QPlainTextEdit(readOnly=True)
        self.log_box.setMaximumBlockCount(2000)
        self.log_box.setFixedHeight(200)
        self.log_box.hide()
        self.log_toggle = QPushButton("Pokaż log", objectName="link", cursor=Qt.CursorShape.PointingHandCursor)
        self.log_toggle.clicked.connect(self.toggle_log)
        folder = QPushButton("Otwórz folder z logami i zrzutami", objectName="link",
                             cursor=Qt.CursorShape.PointingHandCursor)
        folder.clicked.connect(lambda: os.startfile(self.session_dir))
        links = QHBoxLayout()
        links.addWidget(self.log_toggle)
        links.addStretch()
        links.addWidget(folder)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(0)
        layout.addWidget(title)
        layout.addSpacing(6)
        layout.addWidget(lead)
        layout.addSpacing(24)
        for number, text in enumerate(STEPS, 1):
            layout.addLayout(step_row(number, text))
            layout.addSpacing(12)
        layout.addSpacing(12)
        layout.addWidget(start)
        layout.addSpacing(10)
        layout.addWidget(self.status)
        layout.addSpacing(14)
        layout.addLayout(links)
        layout.addWidget(self.log_box)

    def toggle_log(self) -> None:
        self.log_box.setVisible(not self.log_box.isVisible())
        self.log_toggle.setText("Ukryj log" if self.log_box.isVisible() else "Pokaż log")
        self.adjustSize()

    def show_status(self, text: str, state: str) -> None:
        self.status.setText(text)
        self.status.setProperty("state", state)
        self.status.style().polish(self.status)

    def log(self, message: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {message}"
        if sys.stdout:  # None in the windowed .exe
            print(line, flush=True)
        self.log_box.appendPlainText(line)
        with open(self.session_dir / "log.txt", "a", encoding="utf-8") as file:
            file.write(line + "\n")

    def showEvent(self, event) -> None:
        exclude_from_capture(self)
        super().showEvent(event)
        QTimer.singleShot(0, self.bring_to_front)

    def bring_to_front(self) -> None:
        """The .exe starts the app from an unpacking process, so Windows opens the window behind the
        active one (only the taskbar icon shows). A short topmost flip puts it in front."""
        window = int(self.winId())
        ctypes.windll.user32.SetWindowPos(window, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE_NOACTIVATE)
        ctypes.windll.user32.SetWindowPos(window, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE_NOACTIVATE)
        self.raise_()
        self.activateWindow()

    def start(self) -> None:
        self.show_status("Szukam gry na ekranie…", "busy")
        QApplication.processEvents()
        rect = locate_game(self.log)
        if rect is None:
            self.show_status("Nie widzę stołu. Sprawdź, czy gra jest na pełnym ekranie i nic jej nie zasłania, "
                             "potem kliknij Uruchom jeszcze raz.", "error")
            return
        self.show_status("Działa. Nakładkę przesuniesz myszką, prawy klik otwiera menu.", "ok")
        if self.overlay is None:
            self.overlay = Overlay(rect, self.log, self.session_dir)
            self.overlay.show()
        else:
            self.overlay.game_rect = rect


def to_logical(x: int, y: int) -> tuple[QPoint, float]:
    """A screen point in physical pixels (as mss sees it) in Qt's coordinates, plus that screen's scaling.
    Qt keeps each screen's top-left in physical pixels but measures inside it in scaled (logical) pixels."""
    for screen in QApplication.screens():
        origin, ratio = screen.geometry().topLeft(), screen.devicePixelRatio()
        size = screen.geometry().size() * ratio
        if origin.x() <= x < origin.x() + size.width() and origin.y() <= y < origin.y() + size.height():
            return QPoint(round(origin.x() + (x - origin.x()) / ratio), round(origin.y() + (y - origin.y()) / ratio)), ratio
    return QPoint(x, y), 1.0


def scaled_style(style: str, scale: float) -> str:
    return re.sub(r"(\d+)px", lambda match: f"{round(int(match.group(1)) * scale)}px", style)


def clear_layout(layout: QHBoxLayout) -> None:
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget:
            widget.setParent(None)  # Detach now; deleteLater alone leaves it on screen until the next event loop pass.
            widget.deleteLater()


class CardRow(QWidget):
    """Side label + card faces + total, e.g. "ty  [10][6]  16". One row per hand."""

    def __init__(self, side: str, height: int) -> None:
        super().__init__()
        self.setFixedHeight(height)
        self.shown_hand: list[str] | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(QLabel(side, objectName="side"))
        self.cards = QHBoxLayout()
        self.cards.setSpacing(3)
        layout.addLayout(self.cards)
        layout.addStretch()
        self.total = QLabel(objectName="total")
        layout.addWidget(self.total)

    def show_hand(self, hand: list[str], total: str) -> None:
        self.total.setText(total)
        # Rebuilding cards at 5 fps would flicker; only rebuild when they change.
        if hand == self.shown_hand:
            return
        self.shown_hand = hand
        clear_layout(self.cards)
        for rank in hand:
            self.cards.addWidget(QLabel(rank, objectName="card"))
        if not hand:
            self.cards.addWidget(QLabel("–", objectName="empty"))


class Overlay(QWidget):
    def __init__(self, rect: dict, log: Callable[[str], None], session_dir: Path) -> None:
        super().__init__()
        self.log = log
        self.session_dir = session_dir
        self.last_table: tuple | None = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        corner, ratio = to_logical(rect["left"], rect["top"] + rect["height"])
        self.scale = min(max(rect["width"] / ratio / GAME_WIDTH, 1.0), MAX_UI_SCALE)
        self.style_sheet = scaled_style(OVERLAY_STYLE, self.scale)
        self.setStyleSheet(self.style_sheet)
        self.drag_start: QPoint | None = None
        px = self.px

        glass = QFrame(objectName="glass")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(glass)
        self.setToolTip("Przeciągnij, aby przesunąć. Prawy klik: nowa talia, zamknij.")

        self.move_label = QLabel(objectName="move", alignment=Qt.AlignmentFlag.AlignCenter)
        self.move_label.setFixedHeight(px(52))
        self.move_label.setGraphicsEffect(
            QGraphicsDropShadowEffect(blurRadius=px(16), offset=QPoint(0, px(2)), color=QColor(0, 0, 0, 150)))
        self.situation = QLabel(objectName="situation", wordWrap=True,
                                alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        # Two lines always reserved, so a longer reason does not push the cards down.
        self.situation.setFixedHeight(px(36))

        self.dealer_row = CardRow("krupier", px(CARD_ROW_HEIGHT))
        player_area = QWidget()
        player_area.setFixedHeight(PLAYER_ROWS_SHOWN * px(CARD_ROW_HEIGHT) + px(4))
        self.player_box = QVBoxLayout(player_area)
        self.player_box.setContentsMargins(0, 0, 0, 0)
        self.player_box.setSpacing(px(4))
        self.player_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.player_rows: list[CardRow] = []

        rule = QFrame(objectName="rule")
        self.edge_value = QLabel(objectName="statValue")
        self.bet_value = QLabel(objectName="statValue")
        edge = QLabel("przewaga", objectName="statLabel")
        edge.setToolTip("Kto ma przewagę w tej talii. Od +1 w górę Ty, poniżej zera kasyno.")
        bet = QLabel("stawka", objectName="statLabel")
        bet.setToolTip("Ile razy postawić najmniejszą stawkę. Rośnie tylko przy przewadze.")
        stats = QHBoxLayout()
        stats.setSpacing(px(6))
        stats.addWidget(edge)
        stats.addWidget(self.edge_value)
        stats.addSpacing(px(14))
        stats.addWidget(bet)
        stats.addWidget(self.bet_value)
        stats.addStretch()

        round_label = QLabel("w rundzie", objectName="statLabel")
        round_label.setToolTip("Karty policzone w tej rundzie, w kolejności. Porównaj je ze stołem.")
        self.round_box = QHBoxLayout()
        self.round_box.setSpacing(px(2))
        self.shown_round_cards: list[str] | None = None
        round_row = QHBoxLayout()
        round_row.setSpacing(px(8))
        round_row.addWidget(round_label)
        round_row.addLayout(self.round_box)
        round_row.addStretch()

        self.shoe_swatch = QLabel(objectName="swatch")
        self.shoe_swatch.setToolTip("Kolor rewersów w bucie. Nowy kolor = nowy but, licznik od zera.")
        self.cards_left = QLabel(objectName="detail")
        self.cards_left.setToolTip("Ile kart zostało w bucie.")
        self.new_shoe_badge = QLabel("NOWY BUT", objectName="badge")
        self.tally_text = QLabel(objectName="statValue")
        self.tally_text.setToolTip("Dziś: wygrane / przegrane / remisy, gdybyś grał dokładnie wg podpowiedzi.")
        shoe_row = QHBoxLayout()
        shoe_row.setSpacing(px(6))
        shoe_row.addWidget(self.shoe_swatch)
        shoe_row.addWidget(self.cards_left)
        shoe_row.addWidget(self.new_shoe_badge)
        shoe_row.addStretch()
        shoe_row.addWidget(self.tally_text)

        layout = QVBoxLayout(glass)
        layout.setContentsMargins(px(14), px(12), px(14), px(12))
        layout.setSpacing(0)
        layout.addWidget(self.move_label)
        layout.addSpacing(px(8))
        layout.addWidget(self.situation)
        layout.addSpacing(px(6))
        layout.addWidget(self.dealer_row)
        layout.addSpacing(px(4))
        layout.addWidget(player_area)
        layout.addSpacing(px(6))
        layout.addWidget(rule)
        layout.addSpacing(px(8))
        layout.addLayout(stats)
        layout.addSpacing(px(6))
        layout.addLayout(round_row)
        layout.addSpacing(px(6))
        layout.addLayout(shoe_row)
        self.setFixedWidth(px(OVERLAY_WIDTH))

        self.game_rect = rect
        self.templates = load_templates()
        self.screen = mss.MSS()
        self.shoe_changed_at: float | None = None
        self.tally = {WIN: 0, BLACKJACK: 0, LOSS: 0, PUSH: 0}
        self.new_shoe()
        # Joined mid-shoe: cards dealt before are unknown, like burn cards. The count still works,
        # but the true count is understated because we assume a full shoe.
        self.started_mid_shoe = True
        self.shoe_color: str | None = None
        self.color_candidate: str | None = None
        self.color_frames = 0
        self.last_swap_time = 0.0
        self.betting = False
        self.felt_templates = load_felt_templates()
        self.hidden = HiddenCards()
        # Felt cards of this round that the game never drew.
        self.round_hidden: list[str] = []
        # Most of each rank visible at once this round: a higher number means the game just drew a card.
        self.round_visible = Counter()
        # The true count the round's advice uses, fixed at the first advice: once told STÓJ, you stay told.
        self.round_true_count: float | None = None
        # Every card counted this round, in order, shown so you can check the count. Kept until the next round starts.
        self.round_cards: list[str] = []
        self.last_felt_save = 0.0
        self.round_logged = False
        self.render(TableState([], []))
        self.adjustSize()
        self.setFixedSize(self.size())
        self.move(corner.x() + self.px(OVERLAY_MARGIN), corner.y() - self.height() - self.px(OVERLAY_MARGIN))

        timer = QTimer(self)
        timer.timeout.connect(self.tick)
        timer.start(FRAME_INTERVAL_MS)
        felt_timer = QTimer(self)
        felt_timer.timeout.connect(self.felt_tick)
        felt_timer.start(FELT_INTERVAL_MS)

    def showEvent(self, event) -> None:
        if not exclude_from_capture(self):
            self.log("UWAGA: ten Windows nie ukrywa nakładki przed zrzutem ekranu – trzymaj ją poza stołem.")
        super().showEvent(event)

    def apply_topmost(self) -> None:
        # Re-asserted every frame: a full-screen browser that gets a click can push itself above us.
        ctypes.windll.user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE_NOACTIVATE)

    def new_shoe(self) -> None:
        if hasattr(self, "shoe"):
            self.log("=== NOWY BUT – licznik od zera ===")
            self.shoe_changed_at = time.monotonic()
        self.shoe = Shoe()
        self.tracker = RoundTracker(self.shoe)
        self.started_mid_shoe = False

    def track_shoe_color(self, color: str | None) -> None:
        if color is None:
            return
        if color != self.color_candidate:
            self.color_candidate, self.color_frames = color, 0
        self.color_frames += 1
        if self.color_frames == SHOE_SWAP_FRAMES and color != self.shoe_color:
            if time.monotonic() - self.last_swap_time < SHOE_SWAP_COOLDOWN_SECONDS:
                return
            if self.shoe_color is not None:
                self.new_shoe()
                self.last_swap_time = time.monotonic()
            self.log(f"Kolor talii: {SHOE_COLOR_NAMES[color]}")
            self.shoe_color = color

    def full_hands(self, table: TableState) -> list[list[str]]:
        """The table's hands plus the felt cards the game did not draw. All players share one hand,
        so those cards continue it. After a split we cannot tell which hand they went to."""
        if len(table.player) == 1:
            return [table.player[0] + self.round_hidden]
        return table.player

    def decision_count(self) -> float:
        if self.round_true_count is None:
            self.round_true_count = self.shoe.true_count
        return self.round_true_count

    def your_cards(self, table: TableState) -> list[list[str]]:
        if not table.dealer:
            return self.full_hands(table)
        return your_hands(self.full_hands(table), table.dealer[0], self.decision_count())

    def my_hands(self, table: TableState) -> list[tuple[list[str], bool, bool]]:
        """(your cards, doubled, finished) per hand, played exactly as advised: after STÓJ the hand
        is scored as it was then, even if other players took more cards or split it."""
        if not table.dealer:
            return []
        return [play_by_advice(hand, table.dealer[0], self.decision_count())
                for hand in self.your_cards(table) if len(hand) >= 2]

    def advice(self, table: TableState) -> list[str]:
        """Only while you decide: the dealer shows one card and your hand (2+ cards) is not finished.
        With one card the answer is always "take another", so there is nothing to show."""
        if len(table.dealer) != 1:
            return []
        return [advise(hand, table.dealer[0], self.decision_count())
                for hand, _, finished in self.my_hands(table) if not finished]

    def results(self, table: TableState) -> list[str]:
        """Your outcome per hand once it is decided, otherwise empty."""
        mine = self.my_hands(table)
        if not mine or len(mine) != len(self.your_cards(table)):
            return []
        split = len(mine) > 1
        outcomes = [round_result(hand, table.dealer, split) for hand, _, _ in mine]
        return [] if None in outcomes else outcomes

    def log_round_result(self, table: TableState) -> None:
        results = self.results(table)
        if not table.dealer and not table.player:
            self.round_logged = False
            return
        if not results or self.round_logged:
            return
        self.round_logged = True
        for result in results:
            self.tally[result] += 1
        mine = self.my_hands(table)
        split = len(mine) > 1
        hands = " | ".join(f"{' '.join(h)} ({hand_text(h, split)}{', podwojone' if doubled else ''}): {RESULT_NAMES[r]}"
                           for (h, doubled, _), r in zip(mine, results))
        self.log(f"WYNIK RUNDY: krupier {' '.join(table.dealer)} ({hand_text(table.dealer)}) → Ty wg podpowiedzi: {hands}")

    def tick(self) -> None:
        game = np.array(self.screen.grab(self.game_rect))[:, :, :3]
        table = read_table(game, self.templates)
        visible = Counter(table.dealer + [rank for hand in table.player for rank in hand])
        if visible and not self.round_visible:
            self.round_cards = []
        new_ranks = self.tracker.update(list(visible.elements()))
        self.round_cards += new_ranks
        self.hidden.drawn_digitally(list((visible - self.round_visible).elements()), time.monotonic())
        self.round_visible |= visible
        if not visible:
            self.round_visible = Counter()
            self.round_hidden = []
            self.round_true_count = None
        self.track_shoe_color(shoe_color(game))
        betting = has_bet(game)
        if betting != self.betting and (table.dealer or table.player):
            self.log('Tryb: grasz (pokazana jest Twoja ręka)' if betting else 'Tryb: obserwujesz')
        # The chip disappears between rounds; keep the mode until the next round shows cards.
        if table.dealer or table.player:
            self.betting = betting

        state = (tuple(table.dealer), tuple(tuple(hand) for hand in table.player))
        if state != self.last_table:
            self.last_table = state
            capture = self.save_capture(game, table)
            self.log(f"Stół: krupier {' '.join(table.dealer) or '–'} | gracz {' / '.join(' '.join(h) for h in table.player) or '–'}  [{capture}]")
            self.log_round_result(table)
        if new_ranks:
            shoe = self.shoe
            self.log(f"Policzone: {' '.join(new_ranks)} → RC {shoe.running_count:+d}, TC {shoe.true_count:+.1f}, widziane {shoe.cards_seen}")

        self.render(table)
        self.apply_topmost()

    def felt_tick(self) -> None:
        felt = self.grab_felt()
        reading = read_felt_card(felt, self.felt_templates)
        now = time.monotonic()
        rank = self.hidden.read_felt(reading, now)
        if rank:
            self.log(f"Karta na stole: {rank}")
        if reading is not None:
            self.save_felt(felt, reading)
        for rank in self.hidden.take_hidden(now):
            self.shoe.see(rank)
            self.round_hidden.append(rank)
            self.round_cards.append(rank)
            shoe = self.shoe
            self.log(f"Policzone ze stołu (gra jej nie pokazała): {rank} → RC {shoe.running_count:+d}, "
                     f"TC {shoe.true_count:+.1f}, widziane {shoe.cards_seen}")

    def grab_felt(self) -> np.ndarray:
        """Only the felt spot, at the normalized scale (a whole-table grab is too slow for 40 reads a second)."""
        scale = self.game_rect["width"] / GAME_WIDTH
        x1, y1, x2, y2 = FELT_REGION
        area = {"left": self.game_rect["left"] + round(x1 * scale), "top": self.game_rect["top"] + round(y1 * scale),
                "width": round((x2 - x1) * scale), "height": round((y2 - y1) * scale)}
        image = np.array(self.screen.grab(area))[:, :, :3]
        return cv2.resize(image, (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)

    def save_felt(self, felt: np.ndarray, reading: tuple[str | None, float]) -> None:
        if time.monotonic() - self.last_felt_save < FELT_SAVE_SECONDS:
            return
        self.last_felt_save = time.monotonic()
        felt_dir = self.session_dir / "felt"
        felt_dir.mkdir(exist_ok=True)
        rank, score = reading
        name = f"{datetime.now():%H%M%S-%f}"[:-3] + f"_{rank or 'x'}_{score * 100:.0f}.png"
        cv2.imwrite(str(felt_dir / name), felt)

    def save_capture(self, game: np.ndarray, table: TableState) -> str:
        """Saves the raw game area (to re-test reading) and a described copy (what the program saw and advised)."""
        stamp = f"{datetime.now():%H%M%S-%f}"[:-3]
        game = normalize(game)
        shoe = self.shoe
        moves = " / ".join(MOVE_NAMES[m] for m in self.advice(table))
        moves = moves or " / ".join(RESULT_NAMES[r] for r in self.results(table)) or "–"
        player = " | ".join(f"{' '.join(h)} ({hand_text(h, len(table.player) > 1)})" for h in table.player) or "–"
        caption = [
            f"{datetime.now():%H:%M:%S}   Krupier: {' '.join(table.dealer) or '–'}   Gracz: {player}   Ruch: {moves}",
            f"RC {shoe.running_count:+d}   TC {shoe.true_count:+.1f}   widziane {shoe.cards_seen}   "
            f"zostało {shoe.cards_left}   Talia: {SHOE_COLOR_NAMES.get(self.shoe_color, '?')}",
        ]
        # Fast PNG compression: saving must not slow the 5 fps loop.
        options = [cv2.IMWRITE_PNG_COMPRESSION, 1]
        cv2.imwrite(str(self.session_dir / f"{stamp}.png"), game, options)
        cv2.imwrite(str(self.session_dir / f"{stamp}_opis.png"), draw_debug(game, table, caption), options)
        return stamp

    def px(self, size: float) -> int:
        return round(size * self.scale)

    def headline(self, table: TableState) -> tuple[str, str | None, str]:
        """(big text, band color or None for a quiet state, the line under it) for this moment of the round."""
        moves = self.advice(table)
        mine = self.my_hands(table)
        split = len(mine) > 1
        if moves:
            dealer_up = table.dealer[0]
            deciding = [hand for hand, _, finished in mine if not finished]
            reason = why(deciding[0], dealer_up, self.decision_count())
            if split:
                reason = f"Ręka {1 + [h for h, _, _ in mine].index(deciding[0])}: {reason}"
            if dealer_up == "A":
                reason += f" Ubezpieczenie: {'TAK' if self.shoe.true_count >= INSURANCE_TRUE_COUNT else 'nie'}."
            if len(moves) == 1:
                return MOVE_NAMES[moves[0]], MOVE_COLORS[moves[0]], reason
            return "  ".join(f"{i}: {MOVE_NAMES[m]}" for i, m in enumerate(moves, 1)), MOVE_COLORS[moves[0]], reason
        results = self.results(table)
        if results:
            yours = " · ".join(hand_text(hand, split) for hand, _, _ in mine)
            situation = f"Krupier {hand_text(table.dealer)}, Ty {yours}."
            if len(results) == 1:
                return RESULT_NAMES[results[0]], RESULT_COLORS[results[0]], situation
            return "  ".join(f"{i}: {RESULT_NAMES[r]}" for i, r in enumerate(results, 1)), RESULT_COLORS[results[0]], situation
        if mine and all(finished for _, _, finished in mine):
            stood = " · ".join(f"{hand_text(hand, split)}{' ×2' if doubled else ''}" for hand, doubled, _ in mine)
            if stood == "BLACKJACK":
                return "BLACKJACK!", RESULT_COLORS[BLACKJACK], "Wypłata 3:2, chyba że krupier też ma blackjacka."
            if len(table.dealer) == 1 and not split:
                # Still your turn at the table: say the move and why, not just the state.
                return MOVE_NAMES[STAND], MOVE_COLORS[STAND], why(mine[0][0], table.dealer[0], self.decision_count())
            return "STOISZ", None, f"Masz {stood}. Dobiera krupier."
        if table.player or table.dealer:
            return "ROZDAJĄ", None, ""
        return "CZEKAM", None, ""

    def render(self, table: TableState) -> None:
        text, band, situation = self.headline(table)
        self.move_label.setText(text)
        if band:
            font_size = 34 if len(text) <= 11 else 20
            self.move_label.setStyleSheet(f"background: {band}; color: {BAND_TEXT}; font-size: {self.px(font_size)}px;")
        else:
            self.move_label.setStyleSheet(f"background: transparent; color: {IDLE_COLOR}; font-size: {self.px(26)}px;")
        self.situation.setText(situation)

        self.dealer_row.show_hand(table.dealer, hand_text(table.dealer) if table.dealer else "")
        # Your cards as you played them, not the table's: after STÓJ others' hits and splits are not yours.
        played = [hand for hand, _, _ in self.my_hands(table)]
        hands = played if played and len(played) == len(self.your_cards(table)) else self.your_cards(table) or [[]]
        if len(hands) != len(self.player_rows):
            for row in self.player_rows:
                row.setParent(None)  # Detach now; deleteLater alone leaves it on screen until the next event loop pass.
                row.deleteLater()
            sides = ["ty"] if len(hands) == 1 else [f"ręka {i}" for i in range(1, len(hands) + 1)]
            self.player_rows = [CardRow(side, self.px(CARD_ROW_HEIGHT)) for side in sides]
            for row in self.player_rows:
                self.player_box.addWidget(row)
        for row, hand in zip(self.player_rows, hands):
            row.show_hand(hand, hand_text(hand, len(hands) > 1) if hand else "")

        true_count = self.shoe.true_count
        edge_color = POSITIVE if true_count >= 1 else NEGATIVE if true_count <= -1 else NEUTRAL
        # Joined mid-shoe: the true count is understated, so it is shown as approximate.
        approximate = "≈ " if self.started_mid_shoe else ""
        self.edge_value.setText(f"{approximate}{true_count:+.1f}")
        self.edge_value.setStyleSheet(f"color: {edge_color};")
        self.edge_value.setToolTip("Dołączono w trakcie buta, więc przewaga jest zaniżona." if self.started_mid_shoe else "")
        self.bet_value.setText(f"×{bet_units(true_count)}")
        self.show_round_cards()
        self.show_shoe()
        tally = self.tally
        slash = f"<span style='color: {IDLE_COLOR}'> / </span>"
        self.tally_text.setText(f"<span style='color: {POSITIVE}'>{tally[WIN] + tally[BLACKJACK]}</span>{slash}"
                                f"<span style='color: {NEGATIVE}'>{tally[LOSS]}</span>{slash}"
                                f"<span style='color: {NEUTRAL}'>{tally[PUSH]}</span>")

    def show_shoe(self) -> None:
        swatch = SHOE_SWATCH_COLORS.get(self.shoe_color, UNKNOWN_SHOE_COLOR)
        self.shoe_swatch.setStyleSheet(f"background: {swatch};")
        self.cards_left.setText(f"{self.shoe.cards_left} kart")
        recent = self.shoe_changed_at is not None and time.monotonic() - self.shoe_changed_at < NEW_SHOE_BADGE_SECONDS
        self.new_shoe_badge.setVisible(recent)

    def show_round_cards(self) -> None:
        if self.round_cards == self.shown_round_cards:
            return
        self.shown_round_cards = list(self.round_cards)
        clear_layout(self.round_box)
        for rank in self.round_cards[:ROUND_CARDS_SHOWN]:
            self.round_box.addWidget(QLabel(rank, objectName="miniCard"))
        hidden = len(self.round_cards) - ROUND_CARDS_SHOWN
        if hidden > 0:
            self.round_box.addWidget(QLabel(f"+{hidden}", objectName="statLabel"))
        if not self.round_cards:
            self.round_box.addWidget(QLabel("–", objectName="empty"))

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(self.style_sheet)
        menu.addAction("Nowa talia (licz od zera)", self.new_shoe)
        menu.addSeparator()
        menu.addAction("Zamknij Czarnego Jacka", QApplication.quit)
        menu.exec(event.globalPos())

    def mousePressEvent(self, event) -> None:
        self.drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self.drag_start is not None:
            self.move(event.globalPosition().toPoint() - self.drag_start)


def main() -> None:
    # A console that is not UTF-8 must not crash logging on "→" or Polish letters.
    if sys.stdout:
        sys.stdout.reconfigure(errors="replace")
    app = QApplication(sys.argv)
    panel = ControlPanel()
    sys.excepthook = lambda *error: panel.log("BŁĄD:\n" + "".join(traceback.format_exception(*error)))
    panel.show()
    panel.log("Start. Otwórz grę na pełnym ekranie i kliknij przycisk.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
