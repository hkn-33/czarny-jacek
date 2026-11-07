"""Shoe composition, Hi-Lo count, and turning screen frames into counted cards."""
from collections import Counter

DECKS = 8
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
HI_LO = {"2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 0, "8": 0, "9": 0,
         "10": -1, "J": -1, "Q": -1, "K": -1, "A": -1}
# A frame must repeat this many times before its cards are counted (filters misreads mid-animation).
STABLE_FRAMES = 2
# The table must stay empty this long (frames, ~2 s) to end a round. A single empty frame
# (animation, popup) once reset the round and the same cards were counted twice.
ROUND_END_FRAMES = 10
# The felt is read every ~30 ms. The slot must look empty this many reads in a row to end a card.
FELT_EMPTY_READS = 8
# A felt card needs this many confident reads (one blurred frame once read an A as a 7).
FELT_MIN_VOTES = 2
# The game draws a card ~0.2-0.6 s after the dealer shows it on the felt.
TWIN_SECONDS = 1.5
# The same rank again this soon is the same card, uncovered after the dealer's hand passed over it.
SAME_CARD_SECONDS = 3.0


class Shoe:
    def __init__(self, decks: int = DECKS) -> None:
        self.decks = decks
        self.remaining = Counter({rank: 4 * decks for rank in RANKS})
        self.running_count = 0
        self.cards_seen = 0

    def see(self, rank: str) -> None:
        self.remaining[rank] -= 1
        self.running_count += HI_LO[rank]
        self.cards_seen += 1

    @property
    def cards_left(self) -> int:
        return sum(self.remaining.values())

    @property
    def true_count(self) -> float:
        decks_left = max(self.cards_left / 52, 0.5)
        return self.running_count / decks_left


class RoundTracker:
    """Counts every card on the table exactly once per round.

    Cards stay visible for many frames, and splits reshuffle them between hands, so a round
    is tracked as a multiset: a card is new only when its rank appears more times than before.
    """

    def __init__(self, shoe: Shoe) -> None:
        self.shoe = shoe
        self.counted = Counter()
        self.last_frame: Counter | None = None
        self.last_cards = Counter()
        self.repeats = 0
        self.empty_frames = 0

    def update(self, visible_ranks: list[str]) -> list[str]:
        """Returns the ranks counted in this frame."""
        frame = Counter(visible_ranks)
        if not frame:
            self.empty_frames += 1
            if self.empty_frames != ROUND_END_FRAMES:
                return []
            # The dealer's last card can be cleared before it was stable; count it at round end.
            new_ranks = self.count_new(self.last_cards)
            self.counted, self.last_cards, self.last_frame = Counter(), Counter(), None
            return new_ranks

        self.empty_frames = 0
        self.last_cards = frame
        if frame == self.last_frame:
            self.repeats += 1
        else:
            self.last_frame, self.repeats = frame, 1
        if self.repeats != STABLE_FRAMES:
            return []
        return self.count_new(frame)

    def count_new(self, frame: Counter) -> list[str]:
        new_ranks = []
        for rank, count in frame.items():
            for _ in range(count - self.counted[rank]):
                self.shoe.see(rank)
                new_ranks.append(rank)
            self.counted[rank] = max(self.counted[rank], count)
        return new_ranks


class HiddenCards:
    """Finds the cards the dealer shows on the felt that the game never draws.

    Every card drawn for players is shown on the felt for ~0.5 s, and the game draws it digitally
    a moment later, unless it went to players still hitting after you stood (you bet: the game
    shows only your hand). A felt card with no digital twin within TWIN_SECONDS is such a card.
    """

    def __init__(self) -> None:
        self.votes = Counter()
        self.first_seen = 0.0
        self.empty_reads = 0
        self.last_card: tuple[float, str] = (-SAME_CARD_SECONDS, "")
        self.felt: list[tuple[float, str]] = []
        self.digital: list[tuple[float, str]] = []

    def read_felt(self, reading: tuple[str | None, float] | None, now: float) -> str | None:
        """One felt read: None = no card, (None, score) = card but unreadable. Returns the rank of a finished card."""
        if reading is not None:
            self.empty_reads = 0
            rank = reading[0]
            if rank is not None:
                if not self.votes:
                    self.first_seen = now
                self.votes[rank] += 1
            return None
        self.empty_reads += 1
        if self.empty_reads != FELT_EMPTY_READS or not self.votes:
            return None
        rank, votes = self.votes.most_common(1)[0]
        self.votes.clear()
        if votes < FELT_MIN_VOTES:
            return None
        last_time, last_rank = self.last_card
        self.last_card = (now, rank)
        if rank == last_rank and now - last_time < SAME_CARD_SECONDS:
            return None
        self.felt.append((self.first_seen, rank))
        return rank

    def drawn_digitally(self, ranks: list[str], now: float) -> None:
        self.digital += [(now, rank) for rank in ranks]

    def take_hidden(self, now: float) -> list[str]:
        """Felt cards whose twin never came, in the order they were dealt."""
        self.pair(lambda felt_rank, digital_rank: felt_rank == digital_rank)
        hidden = []
        for felt_time, rank in list(self.felt):
            if now - felt_time < TWIN_SECONDS:
                continue
            self.felt.remove((felt_time, rank))
            # A digital card with no felt twin right next to it is this card, misread on the felt.
            twin = next((d for d in self.digital if abs(d[0] - felt_time) <= TWIN_SECONDS), None)
            if twin is None:
                hidden.append(rank)
            else:
                self.digital.remove(twin)
        self.digital = [d for d in self.digital if now - d[0] < 2 * TWIN_SECONDS]
        return hidden

    def pair(self, same) -> None:
        for felt_card in list(self.felt):
            twin = next((d for d in self.digital if same(felt_card[1], d[1]) and abs(d[0] - felt_card[0]) <= TWIN_SECONDS), None)
            if twin is not None:
                self.felt.remove(felt_card)
                self.digital.remove(twin)


def check_hidden_cards() -> None:
    hidden = HiddenCards()
    no_card, unreadable = None, (None, 0.6)

    def show(rank: str, start: float) -> float:
        """Card on the felt for 0.5 s (with one finger-covered read), then gone; returns the time after."""
        now = start
        for reading in [(rank, 0.95), unreadable] + [(rank, 0.95)] * 15 + [no_card] * FELT_EMPTY_READS:
            hidden.read_felt(reading, now)
            now += 0.03
        return now

    # Your hit (digital twin), a card for someone else (no twin), and a misread with a digital twin.
    now = show("5", 0.0)
    hidden.drawn_digitally(["5"], 0.3)
    k_shown = now + 1
    now = show("K", k_shown)
    assert hidden.take_hidden(now) == [], "the K still waits for its twin"
    seven_shown = now + 1
    now = show("7", seven_shown)
    hidden.drawn_digitally(["A"], seven_shown + 0.4)
    assert hidden.take_hidden(k_shown + 2) == ["K"]
    assert hidden.take_hidden(now + 5) == [], "the 7 was the digital A, misread"
    # A 4 drawn for you, covered by the dealer's hand for a moment, then seen again.
    four_shown = now + 10
    now = show("4", show("4", four_shown))
    hidden.drawn_digitally(["4"], four_shown + 0.3)
    assert hidden.take_hidden(now + 5) == [], "one card, not two"


if __name__ == "__main__":
    check_hidden_cards()
    # Replays the first live session log: one empty frame mid-round, and a last card shown only briefly.
    shoe = Shoe()
    tracker = RoundTracker(shoe)
    frames = [["4"]] * 3 + [["4", "4"]] * 3 + [["4", "4", "K"]] * 3 + [[]] + [["4", "4", "K"]] * 3
    frames += [["4", "4", "K", "4"]] * 3 + [["4", "10", "4", "K", "4"]] * 3 + [["4", "10", "Q", "4", "K", "4"]]
    frames += [[]] * ROUND_END_FRAMES
    for frame in frames:
        tracker.update(frame)
    assert shoe.cards_seen == 6, shoe.cards_seen
    assert shoe.running_count == 0, shoe.running_count  # 4 4 K 4 10 Q
    print("shoe ok")
