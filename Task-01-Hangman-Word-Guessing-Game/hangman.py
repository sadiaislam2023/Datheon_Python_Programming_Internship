#!/usr/bin/env python3
"""
Hangman  (Python 3.8+, standard library only)

Run:
    python hangman.py
    python hangman.py --words my_list.txt
    python hangman.py --no-color
    python hangman.py --force-color     (if colours do not show)

Best viewed in a terminal of roughly 100 columns x 50 rows.
(On shorter terminals the game drops the biggest extras so the screen never scrolls.)

Word list format (words.txt):
    # Sports            <- a "# Name" line sets the category for the words below
    tennis
    football
    cricket,Sports      <- or give a category per word: word,Category
If words.txt is missing, a small built-in word array is used.

Controls while playing:
    a letter or a full word + Enter     make a guess
    ?                                   use a hint (costs points)
    /s                                  change difficulty (applies next round)
    /q  (or "quit")                     end the game

Game features:
- Random word (random.choice) from words.txt, shown with its category
- Six incorrect attempts and seven gallows stages (ASCII art)
- Gallows color follows the last guess: yellow = start, green = correct,
  red = wrong, red = lost round, green = won round
- Correct letters tracked in a set, masked word display
- Letter and full-word guesses; no penalty for repeated guesses
- Easy, Medium, and Hard difficulty
- Limited hints with score penalties
- Winning-streak bonuses
- Session statistics, replay, and command-line options
"""

from __future__ import annotations

import argparse
import os
import random
import re
import shutil
import string
import sys
import textwrap
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

CLASSIC_ATTEMPTS = 6
WORD_LIST_MIN_LENGTH = 1
HINT_PENALTY = 10
DEFAULT_CATEGORY = "General"
DEFAULT_WORDS_FILE = Path(__file__).with_name("words.txt")
PANEL_HEIGHT = 15
COMPACT_PANEL_HEIGHT = 11
MIN_WIDTH = 60
MAX_WIDTH = 120
ICON_W = 5

# Neon terminal colour palette
CYAN = "#35D9FF"
BLUE = "#528BFF"
PURPLE = "#C084FC"
PINK = "#F472D0"
GREEN = "#39E58C"
YELLOW = "#FFE66D"
RED = "#FF5263"
WHITE = "#F4F7FF"
LIGHT = "#C9D3FF"
MUTED = "#9298AA"

KEY_BORDER = "#3B4A7A"
KEY_FILL = "#101637"
KEY_FILL_OK = "#0A2A22"
KEY_FILL_BAD = "#2E0F1D"
PILL_FILL = "#0E2A4A"

# Built-in secret word array, used when the default words.txt is missing
BUILTIN_WORDS = {
    "python": "Programming", "variable": "Programming", "function": "Programming",
    "keyboard": "Computers", "terminal": "Computers", "internet": "Computers",
    "elephant": "Animals", "giraffe": "Animals", "dolphin": "Animals", "penguin": "Animals",
    "football": "Sports", "cricket": "Sports", "tennis": "Sports", "swimming": "Sports",
    "mountain": "Nature", "river": "Nature", "forest": "Nature", "thunder": "Nature",
    "chocolate": "Food", "pancake": "Food", "sandwich": "Food", "pineapple": "Food",
}

USE_COLOR = True


@dataclass(frozen=True)
class Difficulty:
    name: str
    max_attempts: int
    hints: int
    min_length: int
    max_length: int
    multiplier: float
    description: str

    @property
    def summary(self) -> str:
        span = f"{self.min_length}+" if self.max_length >= 99 else f"{self.min_length}-{self.max_length}"
        return f"{span} letters, {self.hints} hints"


DIFFICULTIES = [
    Difficulty("Easy", 6, 3, 1, 6, 1.0, "Short words (1–6 letters), 3 hints"),
    Difficulty("Medium", 6, 2, 5, 8, 1.5, "Medium words (5–8 letters), 2 hints"),
    Difficulty("Hard", 6, 1, 8, 99, 2.0, "Long words (8+ letters), 1 hint"),
]
DEFAULT_DIFFICULTY_INDEX = 1

HANGMAN_STAGES = [
r"""
      +---+
      |   |
          |
          |
          |
          |
    =========""",
r"""
      +---+
      |   |
      O   |
          |
          |
          |
    =========""",
r"""
      +---+
      |   |
      O   |
      |   |
          |
          |
    =========""",
r"""
      +---+
      |   |
      O   |
     /|   |
          |
          |
    =========""",
r"""
      +---+
      |   |
      O   |
     /|\  |
          |
          |
    =========""",
r"""
      +---+
      |   |
      O   |
     /|\  |
     /    |
          |
    =========""",
r"""
      +---+
      |   |
      O   |
     /|\  |
     / \  |
          |
    =========""",
]

TITLE = r"""
██╗  ██╗ █████╗ ███╗   ██╗ ██████╗ ███╗   ███╗ █████╗ ███╗   ██╗
██║  ██║██╔══██╗████╗  ██║██╔════╝ ████╗ ████║██╔══██╗████╗  ██║
███████║███████║██╔██╗ ██║██║  ███╗██╔████╔██║███████║██╔██╗ ██║
██╔══██║██╔══██║██║╚██╗██║██║   ██║██║╚██╔╝██║██╔══██║██║╚██╗██║
██║  ██║██║  ██║██║ ╚████║╚██████╔╝██║ ╚═╝ ██║██║  ██║██║ ╚████║
╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝
"""

DECO_WIDTH = 13


# --------------------------------------------------------------------------- #
# Tiny terminal toolkit (ANSI colours, boxes, layout) - standard library only
# --------------------------------------------------------------------------- #

RESET = "\x1b[0m"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
BOX_ROUND = "╭╮╰╯─│"
BOX_DOUBLE = "╔╗╚╝═║"


TRUECOLOR = True  # False -> use the basic 16 ANSI colours (works in every terminal)

# Basic-colour equivalents of the palette (used when the terminal has no 24-bit colour)
BASIC_FG = {
    CYAN: 96, BLUE: 94, PURPLE: 95, PINK: 95, GREEN: 92, YELLOW: 93,
    RED: 91, WHITE: 97, LIGHT: 37, MUTED: 90, KEY_BORDER: 34,
}
BASIC_RGB = [(30, (0, 0, 0)), (31, (205, 0, 0)), (32, (0, 205, 0)), (33, (205, 205, 0)),
             (34, (0, 0, 238)), (35, (205, 0, 205)), (36, (0, 205, 205)), (37, (229, 229, 229)),
             (90, (127, 127, 127)), (91, (255, 0, 0)), (92, (0, 255, 0)), (93, (255, 255, 0)),
             (94, (92, 92, 255)), (95, (255, 0, 255)), (96, (0, 255, 255)), (97, (255, 255, 255))]


def supports_truecolor() -> bool:
    """Best guess whether the terminal understands 24-bit colour."""
    override = os.environ.get("HANGMAN_TRUECOLOR")
    if override in {"0", "1"}:
        return override == "1"
    if os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
        return True
    if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM") in {
            "vscode", "iTerm.app", "WezTerm", "Hyper"}:
        return True
    if "truecolor" in os.environ.get("TERM", "") or "direct" in os.environ.get("TERM", ""):
        return True
    return os.name == "nt"  # Windows 10+ consoles support it


def init_terminal(force_no_color: bool = False, force_color: bool = False) -> None:
    global USE_COLOR, TRUECOLOR
    USE_COLOR = (not force_no_color and "NO_COLOR" not in os.environ
                 and (force_color or sys.stdout.isatty()))
    TRUECOLOR = supports_truecolor()
    if os.name == "nt":
        os.system("")  # enables ANSI escape codes in the Windows console


def _rgb(hex_colour: str) -> tuple:
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def _basic_code(hex_colour: str) -> int:
    """Nearest basic ANSI foreground code for any colour."""
    if hex_colour in BASIC_FG:
        return BASIC_FG[hex_colour]
    r, g, b = _rgb(hex_colour)
    return min(BASIC_RGB, key=lambda c: (c[1][0] - r) ** 2 + (c[1][1] - g) ** 2 + (c[1][2] - b) ** 2)[0]


def blend(start: str, end: str, t: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        *(round(a + (b - a) * t) for a, b in zip(_rgb(start), _rgb(end)))
    )


def style(text: str, fg: str | None = None, bg: str | None = None,
          bold: bool = False, strike: bool = False) -> str:
    if not USE_COLOR or not text:
        return text
    codes = []
    if bold:
        codes.append("1")
    if strike:
        codes.append("9")
    if fg:
        codes.append("38;2;%d;%d;%d" % _rgb(fg) if TRUECOLOR else str(_basic_code(fg)))
    if bg and TRUECOLOR:  # dark backgrounds are skipped in basic-colour mode
        codes.append("48;2;%d;%d;%d" % _rgb(bg))
    if not codes:
        return text
    return f"\x1b[{';'.join(codes)}m{text}{RESET}"


def vlen(text: str) -> int:
    """Visible length (ignores colour codes)."""
    return len(ANSI_RE.sub("", text))


def clip(text: str, width: int) -> str:
    """Cut text to a visible width while keeping colour codes intact."""
    if vlen(text) <= width:
        return text
    out, count, pos = [], 0, 0
    for match in ANSI_RE.finditer(text):
        chunk = text[pos:match.start()]
        take = max(width - count, 0)
        out.append(chunk[:take])
        count += min(len(chunk), take)
        out.append(match.group())
        pos = match.end()
    out.append(text[pos:][:max(width - count, 0)])
    return "".join(out) + (RESET if USE_COLOR else "")


def fit(text: str, width: int, align: str = "left") -> str:
    text = clip(text, width)
    gap = width - vlen(text)
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def center_block(lines: list, width: int) -> list:
    """Centre a multi-line block as a whole (keeps its shape)."""
    block_width = max((vlen(line) for line in lines), default=0)
    left = max((width - block_width) // 2, 0)
    return [" " * left + line for line in lines]


def split_widths(total: int, n: int, gap: int = 1) -> list:
    base, extra = divmod(total - gap * (n - 1), n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def hstack(blocks: list, widths: list, gap: int = 1) -> list:
    rows = max(len(block) for block in blocks)
    return [
        (" " * gap).join(block[i] if i < len(block) else " " * w for block, w in zip(blocks, widths))
        for i in range(rows)
    ]


def card_row(total: int, *makers) -> list:
    """Lay cards (functions taking a width) side by side with equal widths."""
    widths = split_widths(total, len(makers))
    return hstack([make(w) for make, w in zip(makers, widths)], widths)


def panel(lines: list, width: int, colour: str, height: int | None = None,
          title: str | None = None, double: bool = False, pad: int = 1) -> list:
    tl, tr, bl, br, h, v = BOX_DOUBLE if double else BOX_ROUND
    inner = width - 2
    if title:
        label = f" {title} "
        room = max(inner - vlen(label), 0)
        left = room // 2
        top = style(tl + h * left, colour) + label + style(h * (room - left) + tr, colour)
    else:
        top = style(tl + h * inner + tr, colour)
    body = list(lines)
    if height is not None:
        body = body[:max(height - 2, 0)]
        body += [""] * max(height - 2 - len(body), 0)
    side = style(v, colour)
    rows = [side + " " * pad + fit(line, inner - 2 * pad) + " " * pad + side for line in body]
    return [top] + rows + [style(bl + h * inner + br, colour)]


def rule(label: str, width: int, colour: str, char: str = "─") -> str:
    if not label:
        return style(char * width, colour)
    label = clip(label, width)
    left = (width - vlen(label)) // 2
    return style(char * left, colour) + label + style(char * (width - left - vlen(label)), colour)


def frame_width() -> int:
    cols = shutil.get_terminal_size((100, 50)).columns
    return max(MIN_WIDTH, min(cols - 1, MAX_WIDTH))


def frame_height() -> int:
    return shutil.get_terminal_size((100, 50)).lines


def out(lines: list) -> None:
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def say(text: str) -> None:
    out([text])


def ask(prompt: str, default: str | None = None) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    raw = input().strip()
    return default if (not raw and default is not None) else raw


def clear_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()
    else:
        sys.stdout.write("\n")


# --------------------------------------------------------------------------- #
# Word list
# --------------------------------------------------------------------------- #

def load_words(path: Path, min_length: int = WORD_LIST_MIN_LENGTH) -> dict:
    """Return {word: category}. See the module docstring for the file format."""
    try:
        raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        if path == DEFAULT_WORDS_FILE:
            return dict(BUILTIN_WORDS)
        say(style("Error:", RED, bold=True) + f" Could not read word list {path}.\n"
            "Place words.txt beside hangman.py, or run:\n"
            "  python hangman.py --words path/to/list.txt")
        raise SystemExit(1)

    words: dict = {}
    category = DEFAULT_CATEGORY
    for raw in raw_lines:
        line = raw.strip()
        if line.startswith("#"):
            category = line.lstrip("#").strip().title() or DEFAULT_CATEGORY
            continue
        word, _, own_category = line.partition(",")
        word = word.strip().lower()
        if word.isascii() and word.isalpha() and len(word) >= min_length:
            words.setdefault(word, own_category.strip().title() or category)

    if not words:
        say(style("Error:", RED, bold=True) + f" No usable words found in '{path}'.")
        raise SystemExit(1)
    return words


def choose_word(difficulty: Difficulty, word_list: dict, used: set) -> str:
    candidates = [
        word for word in word_list
        if difficulty.min_length <= len(word) <= difficulty.max_length
    ] or list(word_list)
    fresh = [word for word in candidates if word not in used]
    word = random.choice(fresh or candidates)
    used.add(word)
    return word


# --------------------------------------------------------------------------- #
# Game logic
# --------------------------------------------------------------------------- #

class GuessResult(Enum):
    CORRECT = auto()
    INCORRECT = auto()
    REPEAT = auto()


@dataclass
class HangmanGame:
    secret_word: str
    difficulty: Difficulty
    correct_letters: set = field(default_factory=set)
    wrong_letters: set = field(default_factory=set)
    wrong_word_guesses: set = field(default_factory=set)
    wrong_words: int = 0
    hints_used: int = 0
    category: str = DEFAULT_CATEGORY
    last_result: GuessResult | None = None  # drives the gallows colour

    @property
    def max_attempts(self) -> int:
        return self.difficulty.max_attempts

    @property
    def mistakes(self) -> int:
        return len(self.wrong_letters) + self.wrong_words

    @property
    def attempts_left(self) -> int:
        return max(self.max_attempts - self.mistakes, 0)

    @property
    def hints_left(self) -> int:
        return self.difficulty.hints - self.hints_used

    @property
    def hidden_letters(self) -> set:
        return set(self.secret_word) - self.correct_letters

    @property
    def is_won(self) -> bool:
        return not self.hidden_letters

    @property
    def is_lost(self) -> bool:
        return self.mistakes >= self.max_attempts

    @property
    def is_over(self) -> bool:
        return self.is_won or self.is_lost

    @property
    def stage(self) -> int:
        return min(self.mistakes, CLASSIC_ATTEMPTS)

    def masked_word(self, reveal: bool = False) -> list:
        return [
            (letter.upper(), True) if reveal or letter in self.correct_letters else ("_", False)
            for letter in self.secret_word
        ]

    def guess_letter(self, letter: str) -> GuessResult:
        letter = letter.lower()
        if letter in self.correct_letters or letter in self.wrong_letters:
            return GuessResult.REPEAT
        if letter in self.secret_word:
            self.correct_letters.add(letter)
            return GuessResult.CORRECT
        self.wrong_letters.add(letter)
        return GuessResult.INCORRECT

    def guess_word(self, word: str) -> GuessResult:
        word = word.lower()
        if word == self.secret_word:
            self.correct_letters.update(self.secret_word)
            return GuessResult.CORRECT
        if word in self.wrong_word_guesses:
            return GuessResult.REPEAT
        self.wrong_word_guesses.add(word)
        self.wrong_words += 1
        return GuessResult.INCORRECT

    def use_hint(self) -> str | None:
        if self.hints_left <= 0 or len(self.hidden_letters) <= 1:
            return None
        letter = random.choice(sorted(self.hidden_letters))
        self.correct_letters.add(letter)
        self.hints_used += 1
        return letter


@dataclass(frozen=True)
class ScoreBreakdown:
    base: int
    hint_penalty: int
    streak_bonus: int

    @property
    def total(self) -> int:
        return max(self.base - self.hint_penalty, 10) + self.streak_bonus


def calculate_score(game: HangmanGame, streak: int) -> ScoreBreakdown:
    base = int(
        (50 + 10 * len(game.secret_word) + 15 * game.attempts_left)
        * game.difficulty.multiplier
    )
    return ScoreBreakdown(base, HINT_PENALTY * game.hints_used, 20 * max(streak - 1, 0))


@dataclass
class SessionStats:
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    wins: int = 0
    losses: int = 0

    def record_win(self, points: int) -> None:
        self.wins += 1
        self.streak += 1
        self.best_streak = max(self.best_streak, self.streak)
        self.score += points

    def record_loss(self) -> None:
        self.losses += 1
        self.streak = 0


class Outcome(Enum):
    WON = auto()
    LOST = auto()
    QUIT = auto()


@dataclass
class Settings:
    difficulty: Difficulty = DIFFICULTIES[DEFAULT_DIFFICULTY_INDEX]


# --------------------------------------------------------------------------- #
# UI components
# --------------------------------------------------------------------------- #

def neon_title(line: str, width: int) -> str:
    """Cyan at the edges fading to pink in the middle."""
    out_chars = []
    for col, char in enumerate(line):
        t = 1 - abs(2 * col / max(width - 1, 1) - 1)
        out_chars.append(style(char, blend(CYAN, PINK, t), bold=True) if char != " " else " ")
    return "".join(out_chars)


def speed_lines(row: int, side: str) -> str:
    lengths = [5, 9, 13, 13, 9, 5]
    colours = [PURPLE, PURPLE, CYAN, CYAN, PURPLE, PURPLE]
    bar = style("━" * lengths[row], colours[row])
    pad = " " * (DECO_WIDTH - lengths[row])
    return pad + bar if side == "left" else bar + pad


def title_panel(width: int) -> list:
    art = TITLE.strip("\n").splitlines()
    art_width = max(len(line) for line in art)
    inner = width - 6

    if width >= art_width + 2 * DECO_WIDTH + 10:
        rows = [
            speed_lines(i, "left")
            + fit(neon_title(line, art_width), inner - 2 * DECO_WIDTH, "center")
            + speed_lines(i, "right")
            for i, line in enumerate(art)
        ]
    elif width >= art_width + 8:
        rows = [fit(neon_title(line, art_width), inner, "center") for line in art]
    else:
        rows = [fit(style("H A N G M A N", CYAN, bold=True), inner, "center")]
    return panel(rows, width, CYAN, double=True, pad=2)


def icon_lines(icon: str, texts: list, colour: str) -> list:
    lines = []
    for i, text in enumerate(texts):
        if i == 1:
            lead = style(icon, colour, bold=True) + " " * (ICON_W - vlen(icon))
        else:
            lead = " " * ICON_W
        lines.append(lead + text)
    return lines


def stat_card(icon: str, label: str, value: str, note: str, colour: str):
    def make(width: int) -> list:
        return panel(icon_lines(icon, [
            style(label, colour, bold=True),
            style(value, colour, bold=True),
            style(note, MUTED),
        ], colour), width, colour)
    return make


def action_card(icon: str, key: str, label: str, note: str, colour: str):
    def make(width: int) -> list:
        return panel(icon_lines(icon, [
            style(key, colour, bold=True),
            style(label, WHITE),
            style(note, MUTED),
        ], colour), width, colour)
    return make


def banner(width: int, stats: SessionStats, difficulty: Difficulty | None = None,
           hints_left: int | None = None, show_title: bool = True) -> list:
    lines = title_panel(width) if show_title else [
        rule(style(" H A N G M A N ", CYAN, bold=True), width, CYAN)
    ]
    lines += card_row(
        width,
        stat_card("★", "SCORE", str(stats.score), "Current points", YELLOW),
        stat_card("↑", "STREAK", str(stats.streak), "Consecutive wins", PURPLE),
        stat_card("♛", "BEST STREAK", str(stats.best_streak), "Highest streak", CYAN),
        stat_card("▂▄▆", "WIN / LOSS", f"{stats.wins} / {stats.losses}", "Games record", GREEN),
    )
    if difficulty:
        left = difficulty.hints if hints_left is None else hints_left
        lines += card_row(
            width,
            stat_card("◎", "DIFFICULTY", difficulty.name, difficulty.summary, CYAN),
            stat_card("◈", "HINTS LEFT", f"{left} / {difficulty.hints}", "Use ? for a hint", PURPLE),
            stat_card("▦", "GUESS TYPE", "Letter / Word", "Type a letter or the word", GREEN),
        )
    return lines


def panel_header(icon: str, title: str, colour: str, inner: int, right: str = "") -> list:
    left = style(f"{icon} {title}", colour, bold=True)
    gap = max(inner - vlen(left) - vlen(right), 1)
    return [left + " " * gap + right, style("─" * inner, colour)]


def gallows(stage: int, colour: str | None = None) -> list:
    """Draw the gallows. Without an explicit colour, colour it by stage (used on the intro)."""
    if colour is None:
        colour = GREEN if stage <= 1 else YELLOW if stage <= 3 else RED
    art = textwrap.dedent(HANGMAN_STAGES[max(0, min(stage, CLASSIC_ATTEMPTS))]).strip("\n")
    return [style(line, colour, bold=True) for line in art.splitlines()]


def gallows_colour(game: HangmanGame) -> str:
    """Yellow at start, green after a correct guess, red after a wrong one,
    red on loss, green on victory."""
    if game.is_won:
        return GREEN
    if game.is_lost:
        return RED
    if game.last_result is GuessResult.CORRECT:
        return GREEN
    if game.last_result is GuessResult.INCORRECT:
        return RED
    return YELLOW  # nothing guessed yet


def render_word(game: HangmanGame, reveal: bool = False, colour: str = WHITE,
                width: int = 60) -> str:
    """Draw the word as wide blanks, shrinking the spacing for long words."""
    count = len(game.secret_word)
    cell, gap = next(
        ((c, g) for c, g in ((3, 2), (2, 1), (1, 1)) if count * c + (count - 1) * g <= width),
        (1, 1),
    )
    parts = []
    for char, shown in game.masked_word(reveal):
        if shown:
            parts.append(style(char.center(cell), colour, bold=True))
        else:
            parts.append(style("_" * cell, CYAN, bold=True))
    return (" " * gap).join(parts)


def hangman_panel(game: HangmanGame, height: int = PANEL_HEIGHT):
    def make(width: int) -> list:
        inner = width - 6
        hearts = [style("♥", RED, bold=True)] * game.attempts_left + \
                 [style("♡", MUTED, bold=True)] * (game.max_attempts - game.attempts_left)
        room = inner - len("╥ HANGMAN") - 1
        label = style(f"{game.attempts_left} LIVES LEFT   ", MUTED, bold=True)
        short = style(f"{game.attempts_left} ", MUTED, bold=True)
        # Use the longest lives line that fits, so the hearts are never cut off
        for lives in (label + " ".join(hearts), short + " ".join(hearts), "".join(hearts)):
            if vlen(lives) <= room:
                break
        art = center_block(gallows(game.stage, gallows_colour(game)), inner)
        room = height - 2 - 2
        top = max((room - len(art)) // 2, 0)
        body = panel_header("╥", "HANGMAN", CYAN, inner, lives) + [""] * top + art
        # fixed border colour, so it never clashes with the gallows colour
        return panel(body, width, CYAN, height=height, pad=2)
    return make


def letters_box(icon: str, title: str, letters: list, colour: str):
    def make(width: int) -> list:
        shown = " ".join(letter.upper() for letter in letters) or "—"
        return panel([style(f"{icon} {title}", colour, bold=True),
                      style(shown, colour, bold=True)], width, colour)
    return make


def word_panel(game: HangmanGame, height: int = PANEL_HEIGHT, compact: bool = False):
    def make(width: int) -> list:
        inner = width - 6
        category = style("CATEGORY  ", MUTED, bold=True) + \
            style(f" {game.category} ", CYAN, bg=PILL_FILL, bold=True)
        dashes = style("╌" * inner, PURPLE)
        word = fit(render_word(game, width=inner), inner, "center")
        letters = card_row(
            inner,
            letters_box("✔", "CORRECT LETTERS", sorted(game.correct_letters), GREEN),
            letters_box("✖", "WRONG LETTERS", sorted(game.wrong_letters), RED),
        )
        header = panel_header("◎", "WORD CHALLENGE", PURPLE, inner)
        if compact:
            body = header + [category, word, ""] + letters
        else:
            body = header + [category, dashes, "", word, "", dashes] + letters
        return panel(body, width, PURPLE, height=height, pad=2)
    return make


def key_cell(game: HangmanGame, letter: str, width: int) -> list:
    lower = letter.lower()
    if lower in game.correct_letters:
        border, text, fill, strike = GREEN, GREEN, KEY_FILL_OK, False
    elif lower in game.wrong_letters:
        border, text, fill, strike = RED, RED, KEY_FILL_BAD, True
    else:
        border, text, fill, strike = KEY_BORDER, LIGHT, KEY_FILL, False
    shown = "·" if (lower in game.wrong_letters and not USE_COLOR) else letter
    inner = width - 2
    left = (inner - 1) // 2
    middle = (style(" " * left, bg=fill) + style(shown, text, fill, bold=True, strike=strike)
              + style(" " * (inner - left - 1), bg=fill))
    side = style("│", border)
    return [
        style("╭" + "─" * inner + "╮", border),
        side + middle + side,
        style("╰" + "─" * inner + "╯", border),
    ]


def keyboard_panel(game: HangmanGame, width: int) -> list:
    inner = width - 4
    rows = []
    for chunk in (string.ascii_uppercase[:13], string.ascii_uppercase[13:]):
        widths = split_widths(inner, len(chunk))
        rows += hstack([key_cell(game, letter, w) for letter, w in zip(chunk, widths)], widths)
    return panel(rows, width, CYAN)


def action_bar(width: int) -> list:
    return card_row(
        width,
        action_card("▶", "ENTER", "Make a guess", "", GREEN),
        action_card("?", "?", "Get a hint", f"(costs {HINT_PENALTY} pts)", PURPLE),
        action_card("≡", "/S", "Settings", "(difficulty)", CYAN),
        action_card("✕", "/Q", "Quit game", "(end game)", RED),
    )


def footer(width: int) -> str:
    return rule(style(" —  T H I N K  •  G U E S S  •  W I N  — ", CYAN, bold=True), width, PURPLE)


# Layouts tried in order; the first one that fits the terminal height is used.
# Every layout keeps the same panels (score cards, keyboard, action buttons);
# only the tallest extras are dropped on short terminals.
FRAME_TIERS = [
    dict(full_title=True,  show_difficulty=True,  panel_height=PANEL_HEIGHT,         show_footer=True),
    dict(full_title=False, show_difficulty=True,  panel_height=PANEL_HEIGHT,         show_footer=True),
    dict(full_title=False, show_difficulty=False, panel_height=PANEL_HEIGHT,         show_footer=True),
    dict(full_title=False, show_difficulty=False, panel_height=COMPACT_PANEL_HEIGHT, show_footer=False),
]


def build_frame(game: HangmanGame, stats: SessionStats, message: str, message_style: str,
                full_title: bool, show_difficulty: bool, panel_height: int,
                show_footer: bool, width: int | None = None) -> list:
    width = width or frame_width()
    lines = banner(width, stats, game.difficulty if show_difficulty else None,
                   game.hints_left, show_title=full_title)
    lines += card_row(
        width,
        hangman_panel(game, panel_height),
        word_panel(game, panel_height, compact=panel_height < PANEL_HEIGHT),
    )
    lines += keyboard_panel(game, width)
    lines.append(rule(style(f" {message} ", message_style, bold=True), width, message_style))
    lines += action_bar(width)
    if show_footer:
        lines.append(footer(width))
    return lines


def render(game: HangmanGame, stats: SessionStats,
           message: str = "Welcome! Guess the hidden word.", message_style: str = CYAN) -> None:
    """Redraw the game screen in place, picking the richest layout that fits."""
    tty = sys.stdout.isatty()
    height = frame_height()
    lines: list = []
    for tier in FRAME_TIERS:
        lines = build_frame(game, stats, message, message_style, **tier)
        # keep 2 spare rows: one for the prompt, one so pressing Enter never scrolls
        if not tty or len(lines) <= height - 2:
            break

    if tty:
        lines = lines[: max(height - 2, 1)]
        frame = "\x1b[K\n".join(lines) + "\x1b[K\n"
        sys.stdout.write("\x1b[H" + frame + "\x1b[J")
        sys.stdout.flush()
    else:
        out(lines)


# --------------------------------------------------------------------------- #
# Prompts + screens
# --------------------------------------------------------------------------- #

def prompt_action(game: HangmanGame) -> tuple:
    """Return (kind, value). kind 'invalid' carries a message to show on redraw."""
    raw = ask(style("❯ Your guess: ", CYAN, bold=True)).lower()
    if raw in {"quit", "/q", "/quit"}:
        return "quit", ""
    if raw in {"/s", "/settings"}:
        return "settings", ""
    if raw == "?":
        return "hint", ""
    if not raw:
        return "invalid", "Please enter something."
    if not (raw.isascii() and raw.isalpha()):
        return "invalid", "Letters only, please (a-z)."
    if len(raw) == 1:
        return "letter", raw
    return "word", raw


def choose_option(title: str, options: list, default: int = 0) -> int:
    width = min(frame_width(), 90)
    lines = [""]
    for i, option in enumerate(options, start=1):
        line = style(f"{i}. ", YELLOW, bold=True) + option
        if i - 1 == default:
            line += style(" (current)", MUTED)
        lines.append(line)
    lines.append("")
    out(panel(lines, width, PURPLE, title=style(title, CYAN, bold=True), pad=3))
    while True:
        raw = ask(style(f"Choose option [{default + 1}]: ", CYAN, bold=True), str(default + 1))
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        say(style(f"Choose a number from 1 to {len(options)}.", YELLOW))


def settings_menu(settings: Settings, stats: SessionStats) -> None:
    clear_screen()
    out(banner(frame_width(), stats))
    labels = [f"{d.name} — {d.description}" for d in DIFFICULTIES]
    current = DIFFICULTIES.index(settings.difficulty)
    settings.difficulty = DIFFICULTIES[choose_option("GAME SETTINGS · DIFFICULTY", labels, current)]


def show_end_screen(game: HangmanGame, outcome: Outcome, stats: SessionStats,
                    breakdown: ScoreBreakdown | None = None) -> None:
    clear_screen()
    width = frame_width()
    out(banner(width, stats, game.difficulty, game.hints_left))
    inner = width - 8
    if outcome is Outcome.WON:
        text, colour = "✦  VICTORY! YOU SAVED THE DAY!  ✦", GREEN
    elif outcome is Outcome.LOST:
        text, colour = "GAME OVER! BETTER LUCK NEXT TIME!", RED
    else:
        text, colour = "ROUND QUIT", YELLOW

    def centred(line: str) -> str:
        return fit(line, inner, "center")

    body = [""] + center_block(gallows(game.stage, gallows_colour(game)), inner) + [
        "",
        centred(style(text, colour, bold=True)),
        "",
        centred(style("CATEGORY  ", MUTED, bold=True) + style(game.category, CYAN, bold=True)),
        centred(style("THE WORD WAS  ", MUTED, bold=True)
                + render_word(game, reveal=True, colour=colour, width=inner - 20)),
    ]
    if breakdown:
        def score_row(label: str, value: str) -> str:
            return centred(fit(label, 16) + fit(value, 8, "right"))
        body += [
            "",
            score_row(style("Base score", WHITE), style(str(breakdown.base), YELLOW)),
            score_row(style("Hint penalty", WHITE), style(f"-{breakdown.hint_penalty}", RED)),
            score_row(style("Streak bonus", WHITE), style(f"+{breakdown.streak_bonus}", PURPLE)),
            score_row(style("ROUND TOTAL", WHITE, bold=True),
                      style(str(breakdown.total), YELLOW, bold=True)),
        ]
    if outcome is Outcome.LOST:
        body += ["", centred(style("Your winning streak has been reset.", MUTED))]
    body.append("")
    out(panel(body, width, colour, title=style("ROUND RESULT", colour, bold=True),
              double=True, pad=3))


def show_session_summary(stats: SessionStats) -> None:
    width = min(frame_width(), 90)
    inner = width - 10
    rounds = stats.wins + stats.losses

    def centred(line: str) -> str:
        return fit(line, inner, "center")

    body = ["", "", centred(style("THANKS FOR PLAYING!", CYAN, bold=True)), "",
            centred(style(f"Rounds played: {rounds}", WHITE)),
            centred(style(f"Wins: {stats.wins}     Losses: {stats.losses}", GREEN, bold=True)),
            centred(style(f"Final score: {stats.score}", YELLOW, bold=True)),
            centred(style(f"Best streak: {stats.best_streak}", PURPLE, bold=True)), "", ""]
    out(panel(body, width, CYAN, title=style("SESSION SUMMARY", CYAN, bold=True),
              double=True, pad=4))
    say(footer(width))


INTRO_COLOURS = {"yellow": YELLOW, "green": GREEN, "red": RED}


def intro_gallows_panel(width: int, detail: int = 2) -> list:
    """Gallows stages coloured exactly like the real game.
    detail: 2 = roomy, 1 = strip + caption, 0 = strip only."""
    inner = width - 6
    art_w = 9
    stages = list(range(CLASSIC_ATTEMPTS + 1)) if inner >= 7 * art_w + 6 else [0, 3, 6]
    gap = max(1, min(4, (inner - art_w * len(stages)) // max(len(stages) - 1, 1)))
    blocks = []
    for stage in stages:
        # In the real game: yellow before any guess, red after a wrong guess
        colour = YELLOW if stage == 0 else RED
        label = "START" if stage == 0 else "GAME OVER" if stage == CLASSIC_ATTEMPTS else f"{stage} wrong"
        blocks.append([fit(line, art_w) for line in gallows(stage, colour)]
                      + ["", fit(style(label, colour, bold=True), art_w, "center")])
    strip = center_block(hstack(blocks, [art_w] * len(stages), gap), inner)
    caption = fit(style("Every wrong guess draws one more part of the gallows.", MUTED),
                  inner, "center")
    if detail >= 2:
        body = [""] + strip + ["", caption]
    elif detail == 1:
        body = strip + [caption]
    else:
        body = strip
    return panel(body, width, CYAN, title=style("THE GALLOWS", CYAN, bold=True), pad=2)


def intro_rules_panel(width: int, short: bool = False) -> list:
    inner = width - 6
    colours_rule = ("Colors", "Gallows is yellow at the start, green after a correct guess, "
                              "red after a wrong guess. Victory is green, loss is red.")
    if short:
        rules = [
            ("Goal", f"Guess the word. You have {CLASSIC_ATTEMPTS} lives; repeats cost nothing."),
            ("Guess", "Type a letter or the whole word, then press Enter."),
            ("Menu", f"? hint (costs {HINT_PENALTY} pts), /s difficulty, /q quit."),
            colours_rule,
        ]
    else:
        rules = [
            ("Goal", "Guess the hidden word one letter at a time."),
            ("Lives", f"You have {CLASSIC_ATTEMPTS}. Each wrong guess costs one life."),
            ("Guess", "Type a letter, or the whole word, then press Enter."),
            ("Repeats", "Guessing the same letter again costs nothing."),
            ("Hints", f"Type ? for a hint (costs {HINT_PENALTY} points)."),
            ("Menu", "/s changes difficulty, /q quits the game."),
            ("Score", "Bonus points for lives left, long words and win streaks."),
            colours_rule,
        ]
    lines = []
    for name, text in rules:
        wrapped = textwrap.wrap(text, max(inner - 10, 10)) or [""]
        for number, chunk in enumerate(wrapped):
            if name == "Colors":  # colour the words yellow / green / red
                chunk = re.sub(r"\b(yellow|green|red)\b",
                               lambda m: style(m.group(1), INTRO_COLOURS[m.group(1)], bold=True)
                               + (style("", LIGHT)), chunk)
                shown = chunk
            else:
                shown = style(chunk, LIGHT)
            lead = style(name.ljust(10), CYAN, bold=True) if number == 0 else " " * 10
            lines.append(lead + shown)
    return panel(lines, width, CYAN, title=style("HOW TO PLAY", CYAN, bold=True), pad=2)


def show_intro() -> None:
    """Welcome screen: the big title comes first, then the gallows stages and the rules.
    On short terminals the lower sections shrink so the title is never pushed off screen."""
    clear_screen()
    width = frame_width()
    tty = sys.stdout.isatty()
    height = frame_height()
    one_line = [rule(style(" H A N G M A N ", CYAN, bold=True), width, CYAN)]

    tiers = [
        lambda: title_panel(width) + intro_gallows_panel(width, 2) + intro_rules_panel(width),
        lambda: title_panel(width) + intro_gallows_panel(width, 1) + intro_rules_panel(width),
        lambda: title_panel(width) + intro_gallows_panel(width, 0) + intro_rules_panel(width),
        lambda: title_panel(width) + intro_gallows_panel(width, 0) + intro_rules_panel(width, True),
        lambda: title_panel(width) + intro_rules_panel(width),
        lambda: one_line + intro_rules_panel(width),
    ]
    lines: list = []
    for build in tiers:
        lines = build()
        # leave room for the blank line + the "Press Enter" prompt
        if not tty or len(lines) <= height - 3:
            break
    out(lines)
    ask(style("\n  ▶ Press Enter to start ", GREEN, bold=True))


def post_round_choice() -> str:
    out(card_row(
        frame_width(),
        action_card("▶", "ENTER", "Play again", "", GREEN),
        action_card("≡", "S", "Settings", "(difficulty)", PURPLE),
        action_card("✕", "Q", "Quit", "(see summary)", RED),
    ))
    while True:
        raw = ask(style("❯ Choose action: ", CYAN, bold=True), "").lower()
        if raw in {"", "y", "yes"}:
            return "again"
        if raw in {"s", "settings"}:
            return "settings"
        if raw in {"q", "quit", "n", "no"}:
            return "quit"
        say(style("Press Enter, 's', or 'q'.", YELLOW))


def play_round(settings: Settings, stats: SessionStats, word_list: dict,
               used_words: set) -> Outcome:
    word = choose_word(settings.difficulty, word_list, used_words)
    game = HangmanGame(word, settings.difficulty, category=word_list[word])
    message = "Welcome! Guess the hidden word."
    message_style = CYAN

    # One full clear at the start of the round; after that, render() redraws in place
    clear_screen()

    while not game.is_over:
        render(game, stats, message, message_style)
        kind, value = prompt_action(game)

        if kind == "quit":
            show_end_screen(game, Outcome.QUIT, stats)
            return Outcome.QUIT

        if kind == "invalid":
            message, message_style = value, YELLOW

        elif kind == "settings":
            previous = settings.difficulty
            settings_menu(settings, stats)
            clear_screen()  # the settings screen is a different layout, so start clean
            if settings.difficulty == previous:
                message, message_style = "Settings unchanged.", CYAN
            else:
                message = f"{settings.difficulty.name} difficulty will apply from the next round."
                message_style = BLUE

        elif kind == "hint":
            if game.hints_left <= 0:
                message, message_style = "No hints left this round!", YELLOW
            elif len(game.hidden_letters) <= 1:
                message, message_style = "Too close to the finish for a hint. You've got this!", YELLOW
            else:
                letter = game.use_hint()
                message = f"Hint: the word contains '{letter.upper()}'. (-{HINT_PENALTY} points)"
                message_style = BLUE

        elif kind == "letter":
            result = game.guess_letter(value)
            if result is not GuessResult.REPEAT:
                game.last_result = result
            if result is GuessResult.REPEAT:
                message, message_style = f"You already guessed '{value.upper()}'. No penalty!", YELLOW
            elif result is GuessResult.CORRECT:
                message, message_style = f"Nice! '{value.upper()}' is in the word.", GREEN
            else:
                message, message_style = f"Sorry, '{value.upper()}' is not in the word.", RED
        else:
            result = game.guess_word(value)
            if result is not GuessResult.REPEAT:
                game.last_result = result
            if result is GuessResult.CORRECT:
                message, message_style = "Brilliant! You guessed the word.", GREEN
            elif result is GuessResult.REPEAT:
                message, message_style = f"You already tried '{value.upper()}'. No penalty!", YELLOW
            else:
                message, message_style = f"'{value.upper()}' is not the word. One attempt lost.", RED

    if game.is_won:
        breakdown = calculate_score(game, stats.streak + 1)
        stats.record_win(breakdown.total)
        show_end_screen(game, Outcome.WON, stats, breakdown)
        return Outcome.WON

    stats.record_loss()
    show_end_screen(game, Outcome.LOST, stats)
    return Outcome.LOST


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play Hangman in a neon terminal interface.")
    parser.add_argument("--words", type=Path, default=DEFAULT_WORDS_FILE,
                        help="Word list file (one word per line, optional '# Category' headers "
                             "or 'word,Category'); default: words.txt")
    parser.add_argument("--no-color", action="store_true", help="Disable coloured output.")
    parser.add_argument("--force-color", action="store_true",
                        help="Use colours even if the output does not look like a terminal.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_terminal(args.no_color, args.force_color)
    word_list = load_words(args.words)
    stats = SessionStats()
    settings = Settings()
    used_words: set = set()

    try:
        show_intro()
        settings_menu(settings, stats)
        while True:
            outcome = play_round(settings, stats, word_list, used_words)
            if outcome is Outcome.QUIT:
                break
            choice = post_round_choice()
            if choice == "quit":
                break
            if choice == "settings":
                settings_menu(settings, stats)
    except (KeyboardInterrupt, EOFError):
        say("\n" + style("Game interrupted.", RED, bold=True))

    show_session_summary(stats)


if __name__ == "__main__":
    main()