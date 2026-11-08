# Czarny Jacek — plan

Windows overlay for **Total Casino All Bets Blackjack** (live dealer, played in a browser).
It reads cards from the screen, counts cards, and suggests the best move plus the odds.

Goal: play mathematically optimally, i.e. lose as little as possible. Not "always win" — that does not exist.

## Status: v0.1

Done: rank reading (template matching, all 13 ranks), Hi-Lo count with round dedupe, auto new-shoe on back color change, basic strategy + Illustrious 18, a one-line reason for each move, insurance, bet units, overlay window.
Not yet: suits (needed for side bet EV), dealer outcome / EV per move, disconnect popup detection + sound, round CSV log, status bar reading.

Run:
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m czarny_jacek.main
```
Or double-click `uruchom.bat` (keeps a console with the log). A control panel (log hidden behind "Pokaż log") stays open; "Uruchom" finds the game automatically (template match of the felt text "BLACKJACK PAYS 3 TO 2" at any scale) and opens the overlay in the game's bottom-left corner. UI text is Polish.
Joining mid-shoe is fine: earlier cards act like burn cards, only the true count is understated until the next shoe.
Checks: `python -m tests.test_samples`, `python -m czarny_jacek.strategy`.

Build a single exe for other people (no Python needed, no console; `captures/` is created next to the exe):
```
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name CzarnyJacek --paths . --add-data "templates;templates" czarny_jacek/main.py
```
Result: `dist/CzarnyJacek.exe` (~100 MB).

---

## 1. What we know about the game (from screenshots)

| Item | Value |
|---|---|
| Format | **All Bets** — one shared hand for all players (26–29 people at the table) |
| Limits | Main bet 2–5000 PLN |
| Dealer | Draws to 16, **stands on all 17s** (S17) |
| Blackjack | 3:2 |
| Insurance | 2:1 |
| Split | Yes (split 4♠ 4♥ seen) |
| Hole card | Dealer has a face-down second card (card back next to the upcard) |
| Shoe | Cards dealt from the shoe on the right → discard tray on the left after the round |
| Number of decks | **Unknown — probably 8. Check the game rules** |
| Penetration | There is a cut card: the dealer pulls it out, sets it aside, finishes the round and swaps the shoe. A shoe lasts over 1h (~70+ rounds) — measure exactly |
| Shuffling | **Two shoes alternating + a shuffling machine.** At some point the dealer swaps the whole shoe for a new, shuffled one. A second employee loads the used cards into the machine (device with the green LED on the left). Discard tray and shoe are emptied / replaced at that moment |
| Dealer change | Every ~30 min. Popup "Proszę czekać, trwa zmiana krupiera" (please wait, dealer change). **The shoe stays — do NOT reset the count** |

### Shoe swap = count reset
- After a shoe swap the count starts from zero; the new shoe is **full and unknown** (not the same cards that were collected).
- **Simplest swap signal: the back color of the physical cards in the shoe on the right.** Shoes alternate colors (red ↔ blue). Color change = new shoe → reset count. The mean color of a small rectangle inside the shoe is enough.
- Note: the game's digital face-down dealer card is always red — check the color of the **physical shoe in the video**, not the graphic.
- Other signals: empty discard tray on the left, two shoes on the table for a moment, a pause with no cards.
- Rounds between swaps = penetration. This decides whether counting gives anything at all.

### How the game shows cards (key for reading)
The game draws **digital cards** as an overlay on the video — much easier than recognizing physical cards from the camera.

Reference capture: 1920×1032 browser window (author's 1080p screen). Game area ≈ x 285–1693 (black bars on the sides, browser chrome on top).

- **Dealer**: left side, next to the shoe (~x 570–680, y 475–550 in the 1920×1032 capture). A circle with the total next to it (`7`, `15`, `1/11`, red `24` = bust).
- **Player**: center, above the chip circle (~x 930–1045, y 780–855). Circle with the total (`14`, `5/15`, `10/20`, `24`).
- **Split**: two hands side by side, each with its own total circle.
- **Round status** in the top bar: `OBSTAW ZAKŁADY` (place bets), `OSTATNIE ZAKŁADY` (last bets), `KONIEC ZAKŁADÓW` (bets closed), `POCZEKAJ NA NASTĘPNĄ RUNDĘ` (wait for next round).
- **Side bet results**: green/yellow `×25`, `×15`, `×5`, `×2` above the icons.

Conclusion: read the **digital cards** (card corner: rank + suit), not the table video.

### Side bets (paytable)
- **Top 3** (2–62.50): suited three of a kind 270:1, straight flush 180:1, three of a kind 90:1
- **Lucky Lucky** (2–100): suited 777 200:1, suited 678 100:1, 777 50:1, 678 25:1, suited 21 15:1, 21 3:1, any 19/20 2:1
- **Buster** (2–25): dealer busts — 8+ cards + player BJ 2000:1, 7 cards + BJ 800:1, 8+ cards 250:1, 7 cards 50:1, 6 cards 18:1, 5 cards 4:1, 3–4 cards 2:1
- **21+3** (2–125): suited three of a kind 100:1, straight flush 40:1, three of a kind 30:1, straight 10:1, flush 5:1
- **Perfect Pairs** player/dealer (2–500): perfect 25:1, colored pair 12:1, red/black pair 6:1

---

## 2. Stack (simplest that works)

- **Python 3.12**
- **mss** — fast screen region capture
- **OpenCV** — template matching of card corners
- **PySide6** — transparent always-on-top click-through window
- **numpy** — math

No database, no server, no ML to start. Template matching is enough because the cards are digital and always look the same.

---

## 3. Modules

```
czarny_jacek/
  capture.py     # screenshot of the selected window/region
  vision.py      # detect cards (rank+suit), totals, round status
  shoe.py        # shoe state: remaining cards per rank, running/true count
  strategy.py    # basic strategy + deviations (Illustrious 18) by true count
  odds.py        # probabilities: bust, next card, dealer outcome, move EV, side bet EV
  overlay.py     # overlay window (PySide6)
  main.py        # loop: capture → vision → shoe → strategy/odds → overlay
templates/       # cropped rank and suit images (from real screenshots)
samples/         # test screenshots
```

---

## 4. Stages

### Stage 0 — Data collection (manual)
- [ ] Check the game rules: number of decks, double (on which totals? after split?), resplit, split aces, surrender, dealer peek on A/10
- [x] First 28 screenshots in `samples/` (1920×1032 browser window, PNG)
- [ ] More screenshots until covered:
  - every rank A, 2–10, J, Q, K (red and black), for dealer and player
  - split (two hands), 4+ cards in a hand
  - shoe with red and with blue backs
  - every round status in the top bar + both disconnect popups + dealer change popup
- [ ] Measure penetration: rounds from shoe swap to shoe swap (2–3 full shoes)

### Stage 1 — Card reading from screenshots (offline)
- [ ] Crop templates: 13 ranks × 2 text colors (red/black) + 4 suit symbols
- [ ] `vision.py`: for a screenshot returns `{dealer: [...], player: [[...], ...], status: "..."}`
- [ ] Read the total circle as a cross-check (sum of cards must match the circle)
- [ ] Test: every screenshot in `samples/` is read correctly

### Stage 2 — Card counting
- [ ] `shoe.py`: N-deck shoe, subtract seen cards
- [ ] Hi-Lo: running count, true count = RC / remaining decks
- [ ] Count every card **exactly once** (cards stay on the table for many frames — dedupe by position + round)
- [ ] New shoe reset: automatic on shoe back color change (red ↔ blue) + `F9` hotkey as fallback
- [ ] Dealer change must not reset the count
- [ ] Round counter since last swap → logged = measured penetration
- [ ] Test: simulated round sequence → correct count

### Stage 3 — Strategy and odds
- [ ] Basic strategy for these rules (S17, N decks, DAS?)
- [ ] Deviations from basic strategy by true count (Illustrious 18 + Fab 4 surrender if available)
- [ ] Insurance: only when TC ≥ +3
- [ ] Probabilities from the **exact shoe composition** (not just the count):
  - bust chance when hitting
  - dealer outcome distribution (17/18/19/20/21/bust)
  - EV: stand / hit / double / split
- [ ] Side bet EV from current shoe composition (21+3, Perfect Pairs, Lucky Lucky, Top 3, Buster) — show only when EV > 0
- [ ] Bet suggestion: player edge ≈ (TC − 1) × 0.5%. TC ≤ 1 → minimum (2 PLN) or sit out

### Stage 4 — Overlay
- [ ] Transparent always-on-top click-through window, draggable to a free spot (e.g. left side over the curtains)
- [ ] `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` — overlay invisible to screen capture, so it can sit over the cards without breaking reading
- [ ] Manual calibration: user selects the game area rectangle (card positions relative to it)
- [ ] **Different resolutions**: always scale the selected game area to one fixed width (e.g. 1400 px) before reading. Templates and positions are made once for that width → works on any screen
- Author's reference: 1920×1080, game in a full-screen browser (with browser chrome)
- [ ] Shows: running/true count, remaining cards, **move (HIT/STAND/DOUBLE/SPLIT)** in large font, bust %, EV, suggested bet, profitable side bets
- [ ] Hotkeys: reset shoe, pause, hide

### Stage 5 — Live
- [ ] Loop at 5–10 fps, reacts to round status changes
- [ ] Round log to CSV (cards, decision, outcome) — for correctness checks and stats
- [ ] Testing by observation only (balance 0 PLN, as in the screenshots)

---

## 5. Risks and limitations (important)

- **Casino terms**: most online casinos forbid assistance software. Detection = account ban and possible confiscation of winnings. Check Total Casino's terms before playing for money.
- **The edge is small**: even perfect counting gives ~0.5–1% edge and only at high TC. Variance is huge — you can lose a lot despite correct play.
- **Shallow penetration** (shuffle at ~50% of the shoe) cuts counting gains heavily. If the shoe is swapped early, counting gives almost nothing; only basic strategy remains.
- **All Bets = one hand**: only ~4–6 cards per round → the count moves slowly, but every card is easy to read.
- **Betting hides cards**: with a chip on the main bet the game shows only your own hand. Cards drawn for players who keep hitting after you stand are never drawn digitally, but the dealer shows every player card face up in the middle of the felt (over "DEALER MUST DRAW…") for ~0.5 s before sliding it away. The app reads that spot ~40×/s (physical-card templates in `templates/felt/`, rank from the card's index corner after rectifying the card) and counts a felt card when no digital card follows within 1.5 s. Missing templates: J, Q, 6 (not seen yet) — felt crops are saved to `captures/<session>/felt/` to add them. The round result is always scored as if you played exactly by the advice.
- **Time**: one shoe takes over 1h. The edge appears only in a few rounds near the end of the shoe. The program must count on its own in the background for the whole shoe.
- **Inactivity kick** (after ~18 min without a bet):
  1. Popup "Nieaktywność trwała zbyt długo — wkrótce nastąpi przekierowanie do lobby gier" (inactivity too long, redirecting to lobby) + OK
  2. Popup "Nastąpiło rozłączenie z powodu długiego okresu nieaktywności" (disconnected due to inactivity) + OK
  3. Lobby → "Total Casino All Bets Blackjack" tile → loading screen → back at the table
  - The user reconnects manually (~30–60 s, i.e. ~1 missed round).
  - Cards from unseen rounds are treated like burned cards: **they do not change the running count**, they only reduce the estimated remaining cards. The count stays valid, just slightly less precise.
  - The program detects both popups and plays a sound so the user clicks.
  - After reconnecting it compares the shoe back color with the one before the disconnect. Different color → a swap happened → reset count.
- **Joining mid-shoe**: the count is unknown → wait for a new shoe.
- **Game layout / window size changes** break templates → calibration + relative coordinates.
- **Privacy**: screenshots show the casino session id (`tpi_id=...`) in the browser address bar. Crop them or keep `samples/` out of any public repo.

---

## 6. MVP definition of done
1. The overlay reads dealer and player cards live without errors through a whole shoe.
2. Shows the true count and the correct move per basic strategy + deviations.
3. Shows bust % when hitting and the suggested bet.
4. Count reset with one key.
