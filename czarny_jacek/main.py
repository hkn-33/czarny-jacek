"""Control panel finds the game on screen and shows a log; the overlay counts cards and shows the suggested move."""
import ctypes
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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from czarny_jacek.calibration import find_game_area
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
    bust_chance,
    hand_total,
    play_by_advice,
    round_result,
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
MOVE_COLORS = {HIT: "#3d9bff", STAND: "#2ecc71", DOUBLE: "#ffa726", SPLIT: "#b07cff"}
# Short on purpose: the reader is a casual player, not a card counter.
MOVE_HINTS = {HIT: "Weź kartę", STAND: "Nie dobieraj", DOUBLE: "Podwój, jedna karta", SPLIT: "Rozdziel parę"}
RESULT_NAMES = {WIN: "WYGRANA", BLACKJACK: "BLACKJACK!", LOSS: "PRZEGRANA", PUSH: "REMIS"}
RESULT_COLORS = {WIN: "#2ecc71", BLACKJACK: "#2ecc71", LOSS: "#ff5c5c", PUSH: "#9aa0b4"}
RESULT_HINTS = {WIN: "Gra wg podpowiedzi", BLACKJACK: "Płaci 3:2", LOSS: "Gra wg podpowiedzi", PUSH: "Zwrot stawki"}
IDLE_COLOR = "#3a3f4f"
# The overlay never changes size: a window that jumps while you read it is worse than a cut-off long hand.
OVERLAY_WIDTH = 540
ROW_HEIGHT = 40
# Room for two hands (a split) below the dealer.
PLAYER_ROWS_SHOWN = 2
SHOE_COLOR_NAMES = {"red": "czerwona", "blue": "niebieska"}
POSITIVE, NEGATIVE, NEUTRAL = "#2ecc71", "#ff5c5c", "#f2f3f7"

OVERLAY_STYLE = """
#card { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1b1f2c, stop:1 #0f1118);
        border: 1px solid #2c3244; border-radius: 22px; }
QLabel { color: #f2f3f7; font-family: 'Segoe UI'; font-size: 14px; background: transparent; }
#title { color: #8a90a6; font-size: 12px; font-weight: 800; letter-spacing: 3px; }
#pill { color: #cfd3e0; background: #262b3b; border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 800; }
#move { font-size: 40px; font-weight: 900; color: #0b0c10; border-radius: 16px; padding: 10px 18px; }
#hint { color: #b9bdcc; font-size: 14px; font-weight: 600; qproperty-alignment: AlignCenter; }
#tile { background: #1c2030; border: 1px solid #272c3d; border-radius: 14px; }
#tileLabel { color: #9aa0b4; font-size: 12px; font-weight: 700; }
#tileValue { font-size: 28px; font-weight: 800; }
#tileHint { color: #6f7590; font-size: 11px; }
#rowLabel { color: #8a90a6; font-size: 12px; font-weight: 800; letter-spacing: 1px; min-width: 70px; }
#chip { background: #fbfbf7; color: #111; font-size: 20px; font-weight: 800; border-radius: 7px;
        border-bottom: 3px solid #c8c8bd; padding: 2px 8px; min-width: 18px; qproperty-alignment: AlignCenter; }
#total { font-size: 18px; font-weight: 800; }
#risk { color: #9aa0b4; font-size: 13px; font-weight: 600; }
#stat { background: #1c2030; border-radius: 10px; padding: 6px 4px; font-size: 13px; font-weight: 700;
        qproperty-alignment: AlignCenter; }
#detail { color: #6f7590; font-size: 12px; }
#note { color: #ffa726; font-size: 12px; font-weight: 600; }
QPushButton { color: #cfd3e0; background: #1c2030; border: 1px solid #2c3244; border-radius: 10px;
              padding: 6px 14px; font-family: 'Segoe UI'; font-size: 13px; font-weight: 600; }
QPushButton:hover { background: #262b3b; }
QPushButton:checked { background: #1d3a5c; border-color: #3d9bff; }
#close { padding: 4px 10px; }
QToolTip { color: #f2f3f7; background: #1c2030; border: 1px solid #2c3244; padding: 6px; }
"""

PANEL_STYLE = """
QWidget { background: #12141b; color: #f2f3f7; font-family: 'Segoe UI'; font-size: 14px; }
#steps { color: #b9bdcc; font-size: 14px; }
#status { color: #ffa726; font-weight: 600; }
QPushButton { background: #2ecc71; color: #0b0c10; border: none; border-radius: 10px; padding: 12px;
              font-size: 16px; font-weight: 800; }
QPushButton:hover { background: #3ddc80; }
QPlainTextEdit { background: #0b0c10; color: #cfd3e0; border: 1px solid #2a2f3d; border-radius: 10px;
                 font-family: Consolas; font-size: 12px; padding: 6px; }
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


def hand_text(hand: list[str]) -> str:
    total, soft = hand_total(hand)
    return f"{'miękkie ' if soft else ''}{total}"


class ControlPanel(QWidget):
    """Stays open (e.g. on a second monitor): start button and a live log."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Czarny Jacek")
        self.setStyleSheet(PANEL_STYLE)
        self.resize(720, 560)
        self.overlay: Overlay | None = None
        self.session_dir = CAPTURES_DIR / f"{datetime.now():%Y%m%d-%H%M%S}"
        self.session_dir.mkdir(parents=True)

        title = QLabel("Czarny Jacek")
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        steps = QLabel(
            "1. Otwórz stół Total Casino All Bets Blackjack.\n"
            "2. Ustaw przeglądarkę na pełny ekran (F11) – cały stół musi być widoczny.\n"
            "3. Kliknij „Uruchom Czarnego Jacka”. Program sam znajdzie grę na ekranie.",
            objectName="steps",
        )
        self.status = QLabel("", objectName="status")
        start = QPushButton("Uruchom Czarnego Jacka")
        start.clicked.connect(self.start)
        self.log_box = QPlainTextEdit(readOnly=True)
        self.log_box.setMaximumBlockCount(2000)
        folder = QLabel(f"Log i screeny: {self.session_dir}", objectName="steps")
        folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(steps)
        layout.addWidget(start)
        layout.addWidget(self.status)
        layout.addWidget(self.log_box)
        layout.addWidget(folder)

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
        self.status.setText("Szukam gry na ekranie…")
        QApplication.processEvents()
        rect = locate_game(self.log)
        if rect is None:
            self.status.setText("Nie znaleziono gry. Sprawdź, czy stół jest widoczny na pełnym ekranie, i spróbuj ponownie.")
            return
        self.status.setText("Działa. Nakładkę możesz przesunąć myszką.")
        if self.overlay is None:
            self.overlay = Overlay(rect, self.log, self.session_dir)
            self.overlay.show()
        else:
            self.overlay.game_rect = rect


def tile(label: str, hint: str, tooltip: str) -> tuple[QFrame, QLabel]:
    frame = QFrame(objectName="tile")
    frame.setToolTip(tooltip)
    value = QLabel("–", objectName="tileValue")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(0)
    layout.addWidget(QLabel(label, objectName="tileLabel"))
    layout.addWidget(value)
    layout.addWidget(QLabel(hint, objectName="tileHint"))
    return frame, value


class CardRow(QWidget):
    """Label + white card chips + total, e.g. "TY  [2][10]  12  ryzyko fury 31%". One row per hand."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.setFixedHeight(ROW_HEIGHT)
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(5)
        self.layout_.addWidget(QLabel(label, objectName="rowLabel"))
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        self.layout_.addLayout(self.chips)
        self.total = QLabel(objectName="total")
        self.risk = QLabel(objectName="risk")
        self.layout_.addSpacing(8)
        self.layout_.addWidget(self.total)
        self.layout_.addSpacing(6)
        self.layout_.addWidget(self.risk)
        self.layout_.addStretch()

    def show_hand(self, hand: list[str], total: str, risk: str = "") -> None:
        self.total.setText(total)
        self.risk.setText(risk)
        # Rebuilding chips at 5 fps would flicker; only rebuild when the cards change.
        if hand == getattr(self, "shown_hand", None):
            return
        self.shown_hand = hand
        while self.chips.count():
            self.chips.takeAt(0).widget().deleteLater()
        for rank in hand:
            self.chips.addWidget(QLabel(rank, objectName="chip"))
        if not hand:
            self.chips.addWidget(QLabel("–", objectName="detail"))


class Overlay(QWidget):
    def __init__(self, rect: dict, log: Callable[[str], None], session_dir: Path) -> None:
        super().__init__()
        self.log = log
        self.session_dir = session_dir
        self.last_table: tuple | None = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(OVERLAY_STYLE)
        self.drag_start: QPoint | None = None

        self.card = QFrame(objectName="card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)

        self.pin = QPushButton("📌", checkable=True, checked=True, toolTip="Zawsze na wierzchu")
        self.pin.toggled.connect(self.apply_topmost)
        close = QPushButton("✕", objectName="close", toolTip="Zamknij")
        close.clicked.connect(QApplication.quit)
        self.mode_pill = QLabel(objectName="pill")
        header = QHBoxLayout()
        header.addWidget(QLabel("CZARNY JACEK", objectName="title"))
        header.addSpacing(6)
        header.addWidget(self.mode_pill)
        header.addStretch()
        header.addWidget(self.pin)
        header.addWidget(close)

        self.move_label = QLabel(objectName="move")
        self.move_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.move_label.setFixedHeight(78)
        self.hint = QLabel(objectName="hint")
        self.hint.setFixedHeight(22)

        tiles = QGridLayout()
        tiles.setSpacing(8)
        tc_tile, self.tc_value = tile(
            "Przewaga", "plus = dla Ciebie",
            "Kto ma przewagę w tej talii. Od +1 w górę Ty, poniżej 0 kasyno.")
        rc_tile, self.rc_value = tile(
            "Licznik kart", "małe minus duże",
            "Ile małych kart (2–6) wyszło więcej niż dużych (10, J, Q, K, A).\n"
            "Dużo małych za nami = więcej dużych w talii = dobrze dla Ciebie.")
        bet_tile, self.bet_value = tile(
            "Stawka", "× najmniejsza",
            "Ile razy Twoją najmniejszą stawkę postawić. Rośnie tylko przy przewadze.")
        tiles.addWidget(tc_tile, 0, 0)
        tiles.addWidget(rc_tile, 0, 1)
        tiles.addWidget(bet_tile, 0, 2)

        self.dealer_row = CardRow("KRUPIER")
        player_area = QWidget()
        player_area.setFixedHeight(PLAYER_ROWS_SHOWN * ROW_HEIGHT + 6)
        self.player_box = QVBoxLayout(player_area)
        self.player_box.setContentsMargins(0, 0, 0, 0)
        self.player_box.setSpacing(6)
        self.player_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.player_rows: list[CardRow] = []
        stats = QHBoxLayout()
        stats.setSpacing(6)
        self.stat_labels = {}
        for key, color in ((WIN, POSITIVE), (LOSS, NEGATIVE), (PUSH, NEUTRAL)):
            self.stat_labels[key] = QLabel(objectName="stat")
            self.stat_labels[key].setStyleSheet(f"color: {color};")
            stats.addWidget(self.stat_labels[key])
        self.detail = QLabel(objectName="detail")
        self.detail.setFixedHeight(34)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.note = QLabel(objectName="note")
        self.note.setFixedHeight(18)
        new_shoe = QPushButton("Nowa talia", toolTip="Krupier wymienił karty: licz od zera")
        new_shoe.clicked.connect(self.new_shoe)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.move_label)
        layout.addWidget(self.hint)
        layout.addLayout(tiles)
        layout.addWidget(self.dealer_row)
        layout.addWidget(player_area)
        layout.addLayout(stats)
        layout.addWidget(self.detail)
        layout.addWidget(self.note)
        layout.addWidget(new_shoe)
        self.setFixedWidth(OVERLAY_WIDTH)

        self.game_rect = rect
        self.templates = load_templates()
        self.screen = mss.MSS()
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
        self.last_felt_save = 0.0
        self.round_logged = False
        self.tally = {WIN: 0, BLACKJACK: 0, LOSS: 0, PUSH: 0}
        self.render(TableState([], []))
        self.adjustSize()
        self.setFixedSize(self.size())

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
        order = HWND_TOPMOST if self.pin.isChecked() else HWND_NOTOPMOST
        ctypes.windll.user32.SetWindowPos(int(self.winId()), order, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE_NOACTIVATE)

    def new_shoe(self) -> None:
        if hasattr(self, "shoe"):
            self.log("=== NOWY BUT – licznik od zera ===")
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

    def my_hands(self, table: TableState) -> list[tuple[list[str], bool, bool]]:
        """(your cards, doubled, finished) per hand, played exactly as advised: after STÓJ the hand
        is scored as it was then, even if you or other players took more cards."""
        if not table.dealer:
            return []
        return [play_by_advice(hand, table.dealer[0], self.shoe.true_count) for hand in self.full_hands(table) if len(hand) >= 2]

    def advice(self, table: TableState) -> list[str]:
        """Only while you decide: the dealer shows one card and your hand (2+ cards) is not finished.
        With one card the answer is always "take another", so there is nothing to show."""
        if len(table.dealer) != 1:
            return []
        return [advise(hand, table.dealer[0], self.shoe.true_count)
                for hand, _, finished in self.my_hands(table) if not finished]

    def results(self, table: TableState) -> list[str]:
        """Your outcome per hand once it is decided, otherwise empty."""
        mine = self.my_hands(table)
        if not mine or len(mine) != len(table.player):
            return []
        split = len(table.player) > 1
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
        hands = " | ".join(f"{' '.join(h)} ({hand_text(h)}{', podwojone' if doubled else ''}): {RESULT_NAMES[r]}"
                           for (h, doubled, _), r in zip(mine, results))
        self.log(f"WYNIK RUNDY: krupier {' '.join(table.dealer)} ({hand_text(table.dealer)}) → Ty wg podpowiedzi: {hands}")

    def tick(self) -> None:
        game = np.array(self.screen.grab(self.game_rect))[:, :, :3]
        table = read_table(game, self.templates)
        visible = Counter(table.dealer + [rank for hand in table.player for rank in hand])
        new_ranks = self.tracker.update(list(visible.elements()))
        self.hidden.drawn_digitally(list((visible - self.round_visible).elements()), time.monotonic())
        self.round_visible |= visible
        if not visible:
            self.round_visible = Counter()
            self.round_hidden = []
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
        if self.pin.isChecked():
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
        player = " | ".join(f"{' '.join(h)} ({hand_text(h)})" for h in table.player) or "–"
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

    def render(self, table: TableState) -> None:
        shoe = self.shoe
        moves = self.advice(table)
        results = self.results(table)
        if moves:
            names, colors, hints, shown = MOVE_NAMES, MOVE_COLORS, MOVE_HINTS, moves
        elif results:
            names, colors, hints, shown = RESULT_NAMES, RESULT_COLORS, RESULT_HINTS, results
        else:
            shown = []
        if len(shown) == 1:
            text, font_size, hint = names[shown[0]], 38, hints[shown[0]]
        elif shown:
            text = "   ".join(f"{i}: {names[m]}" for i, m in enumerate(shown, 1))
            font_size, hint = 22, " ".join(f"{i}: {hints[m]}" for i, m in enumerate(shown, 1))
        elif self.my_hands(table) and all(finished for _, _, finished in self.my_hands(table)):
            stood = " | ".join(f"{hand_text(h)}{' ×2' if doubled else ''}" for h, doubled, _ in self.my_hands(table))
            text, font_size, hint = f"STOISZ: {stood}", 22, "Ruch krupiera"
        elif table.player or table.dealer:
            text, font_size, hint = "ROZDAJĄ…", 22, "Czekaj na 2 karty"
        else:
            text, font_size, hint = "CZEKAM", 22, "Nowa runda wkrótce"
        color = colors[shown[0]] if shown else IDLE_COLOR
        self.move_label.setText(text)
        top, bottom = QColor(color).lighter(115).name(), QColor(color).darker(115).name()
        self.move_label.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {top}, stop:1 {bottom});"
            f" color: {'#0b0c10' if shown else '#c9cddb'}; font-size: {font_size}px;")
        self.hint.setText(hint)
        self.card.setStyleSheet(f"#card {{ border-color: {color if shown else '#2c3244'}; }}")

        true_count = shoe.true_count
        tc_color = POSITIVE if true_count >= 1 else NEGATIVE if true_count <= -1 else NEUTRAL
        self.tc_value.setText(f"{true_count:+.1f}")
        self.tc_value.setStyleSheet(f"color: {tc_color};")
        self.rc_value.setText(f"{shoe.running_count:+d}")
        self.bet_value.setText(f"×{bet_units(true_count)}")

        self.dealer_row.show_hand(table.dealer, hand_text(table.dealer) if table.dealer else "")
        hands = self.full_hands(table) or [[]]
        if len(hands) != len(self.player_rows):
            for row in self.player_rows:
                row.setParent(None)  # Detach now; deleteLater alone leaves it on screen until the next event loop pass.
                row.deleteLater()
            labels = ["TY"] if len(hands) == 1 else [f"RĘKA {i}" for i in range(1, len(hands) + 1)]
            self.player_rows = [CardRow(label) for label in labels]
            for row in self.player_rows:
                self.player_box.addWidget(row)
        for row, hand in zip(self.player_rows, hands):
            total, risk = (hand_text(hand) if hand else ""), ""
            if hand and hand_total(hand)[0] > 21:
                risk = "FURA"
            elif hand and hand_total(hand)[0] < 21 and moves:  # Only while you still decide.
                risk = f"ryzyko fury {bust_chance(hand, shoe.remaining):.0%}"
            row.show_hand(hand, total, risk)

        tally = self.tally
        self.mode_pill.setText("GRASZ" if self.betting else "OBSERWUJESZ")
        self.mode_pill.setStyleSheet("background: #1d3a5c; color: #8cc4ff;" if self.betting else "")
        self.stat_labels[WIN].setText(f"Wygrane {tally[WIN] + tally[BLACKJACK]}")
        self.stat_labels[LOSS].setText(f"Przegrane {tally[LOSS]}")
        self.stat_labels[PUSH].setText(f"Remisy {tally[PUSH]}")
        details = [f"Talia {SHOE_COLOR_NAMES.get(self.shoe_color, '?')} · zostało {shoe.cards_left} kart"]
        if table.dealer[:1] == ["A"] and len(table.dealer) == 1:
            details.insert(0, f"Ubezpieczenie: {'TAK' if true_count >= INSURANCE_TRUE_COUNT else 'nie'}")
        self.detail.setText("\n".join(details))

        self.note.setText("Dołączono w trakcie talii – przewaga zaniżona" if self.started_mid_shoe else "")

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
