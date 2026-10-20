"""
Hangman Word Guessing Game
A polished terminal-based Hangman game.

Core requirements:
- Random English word selection from words.txt
- Six incorrect attempts
- ASCII gallows with seven stages
- Masked word and guessed-letter tracking
- No penalty for repeated guesses
- Clear victory and defeat screens

Additional features:
- Easy, Medium, and Hard difficulty levels
- Limited hints and score penalties
- Winning streak bonuses
- Session statistics and replay
- Optional terminal colours

Usage:
    python hangman.py
    python hangman.py --words my_list.txt
    python hangman.py --no-color
"""

from __future__ import annotations

import argparse
import os
import random
import string
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

CLASSIC_ATTEMPTS = 6
WORD_LIST_MIN_LENGTH = 4
DEFAULT_WORDS_FILE = Path(__file__).with_name("words.txt")


@dataclass(frozen=True)
class Difficulty:
    name: str
    max_attempts: int
    hints: int
    min_length: int
    max_length: int
    multiplier: float
    description: str


DIFFICULTIES = [
    Difficulty(
        "Easy", 6, 3, 4, 6, 1.0,
        "Short words (4-6 letters), 3 hints"
    ),
    Difficulty(
        "Medium", 6, 2, 5, 8, 1.5,
        "Medium words (5-8 letters), 2 hints"
    ),
    Difficulty(
        "Hard", 6, 1, 8, 99, 2.0,
        "Long words (8+ letters), 1 hint"
    ),
]

DEFAULT_DIFFICULTY_INDEX = 1


# ============================================================
# TERMINAL COLOURS
# ============================================================

USE_COLOR = False
USE_UNICODE = True


class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


def paint(text: str, *styles: str) -> str:
    """Apply terminal colours when colour output is enabled."""
    if not USE_COLOR or not styles:
        return text

    return f"{''.join(styles)}{text}{Ansi.RESET}"


def init_terminal(force_no_color: bool = False) -> None:
    """Configure terminal colours and Unicode support."""
    global USE_COLOR, USE_UNICODE

    USE_COLOR = (
        not force_no_color
        and "NO_COLOR" not in os.environ
        and sys.stdout.isatty()
    )

    if USE_COLOR and os.name == "nt":
        os.system("")

    try:
        "\u2665\u2661\u2588\u2591".encode(
            sys.stdout.encoding or "ascii"
        )
    except (UnicodeEncodeError, LookupError):
        USE_UNICODE = False


def symbols() -> tuple[str, str, str, str]:
    """Return life and progress-bar symbols."""
    if USE_UNICODE:
        return "\u2665", "\u2661", "\u2588", "\u2591"

    return "*", "-", "#", "."


# ============================================================
# ASCII GALLOWS
# Seven stages: 0 through 6 incorrect guesses
# ============================================================

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
  _   _    _    _   _  ____ __  __    _    _   _
 | | | |  / \  | \ | |/ ___|  \/  |  / \  | \ | |
 | |_| | / _ \ |  \| | |  _| |\/| | / _ \ |  \| |
 |  _  |/ ___ \| |\  | |_| | |  | |/ ___ \| |\  |
 |_| |_/_/   \_\_| \_|\____|_|  |_/_/   \_\_| \_|
"""


# ============================================================
# WORD LIST HANDLING
# ============================================================

def load_words(
    path: Path,
    min_length: int = WORD_LIST_MIN_LENGTH
) -> list[str]:
    """
    Load and clean the supplied English word list.

    - Converts words to lowercase.
    - Accepts ASCII alphabetic words only.
    - Removes duplicates.
    - Enforces the minimum word length.
    - Does not apply an additional blocked-word list.
    """
    try:
        raw_lines = path.read_text(
            encoding="utf-8-sig"
        ).splitlines()
    except (OSError, UnicodeDecodeError):
        sys.exit(
            f"Error: could not read the word list '{path}'.\n"
            "Place words.txt beside hangman.py, or run:\n"
            "python hangman.py --words path/to/list.txt"
        )

    words = {
        line.strip().lower()
        for line in raw_lines
        if line.strip().isascii()
        and line.strip().isalpha()
        and len(line.strip()) >= min_length
    }

    if not words:
        sys.exit(
            f"Error: no usable words found in '{path}'."
        )

    return sorted(words)


def choose_word(
    difficulty: Difficulty,
    word_list: list[str],
    used: set[str]
) -> str:
    """Choose a random word appropriate for the difficulty."""

    in_range = [
        word
        for word in word_list
        if difficulty.min_length
        <= len(word)
        <= difficulty.max_length
    ]

    # Fall back to the complete list if no words match the range.
    candidates = in_range or word_list

    # Avoid repeats until all eligible words have been used.
    fresh = [
        word for word in candidates
        if word not in used
    ]

    word = random.choice(fresh or candidates)
    used.add(word)

    return word


# ============================================================
# GAME LOGIC
# ============================================================

class GuessResult(Enum):
    CORRECT = auto()
    INCORRECT = auto()
    REPEAT = auto()


@dataclass
class HangmanGame:
    secret_word: str
    difficulty: Difficulty

    correct_letters: set[str] = field(default_factory=set)
    wrong_letters: set[str] = field(default_factory=set)
    wrong_word_guesses: set[str] = field(default_factory=set)

    wrong_words: int = 0
    hints_used: int = 0

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
    def hidden_letters(self) -> set[str]:
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
    def guessed_letters(self) -> set[str]:
        return self.correct_letters | self.wrong_letters

    @property
    def stage(self) -> int:
        """Return the gallows stage, from 0 to 6."""
        return min(self.mistakes, CLASSIC_ATTEMPTS)

    @property
    def progress(self) -> float:
        """Calculate the fraction of distinct letters revealed."""
        total = len(set(self.secret_word))
        revealed = total - len(self.hidden_letters)

        return revealed / total

    def masked_word(
        self,
        reveal: bool = False
    ) -> list[tuple[str, bool]]:
        """Return displayed letters and their visibility."""
        return [
            (letter.upper(), True)
            if reveal or letter in self.correct_letters
            else ("_", False)
            for letter in self.secret_word
        ]

    def guess_letter(self, letter: str) -> GuessResult:
        """Guess a letter without penalising repeated guesses."""
        letter = letter.lower()

        if letter in self.guessed_letters:
            return GuessResult.REPEAT

        if letter in self.secret_word:
            self.correct_letters.add(letter)
            return GuessResult.CORRECT

        self.wrong_letters.add(letter)
        return GuessResult.INCORRECT

    def guess_word(self, word: str) -> GuessResult:
        """Guess the entire word without duplicate penalties."""
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
        """Reveal one hidden letter if a hint is available."""
        if self.hints_left <= 0:
            return None

        if len(self.hidden_letters) <= 1:
            return None

        letter = random.choice(sorted(self.hidden_letters))
        self.correct_letters.add(letter)
        self.hints_used += 1

        return letter


# ============================================================
# SCORING AND SESSION STATISTICS
# ============================================================

@dataclass(frozen=True)
class ScoreBreakdown:
    base: int
    hint_penalty: int
    streak_bonus: int

    @property
    def total(self) -> int:
        return (
            max(self.base - self.hint_penalty, 10)
            + self.streak_bonus
        )


def calculate_score(
    game: HangmanGame,
    streak: int
) -> ScoreBreakdown:
    """Calculate the score for a winning round."""
    base = int(
        (
            50
            + 10 * len(game.secret_word)
            + 15 * game.attempts_left
        )
        * game.difficulty.multiplier
    )

    return ScoreBreakdown(
        base=base,
        hint_penalty=25 * game.hints_used,
        streak_bonus=20 * max(streak - 1, 0),
    )


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
        self.best_streak = max(
            self.best_streak,
            self.streak
        )
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
    difficulty: Difficulty = DIFFICULTIES[
        DEFAULT_DIFFICULTY_INDEX
    ]


# ============================================================
# DISPLAY HELPERS
# ============================================================

def clear_screen() -> None:
    """Clear interactive terminals without affecting redirected output."""
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")
    else:
        print()


def banner(
    stats: SessionStats,
    settings: Settings | None = None
) -> None:
    """Display the title and session information."""
    print(paint(TITLE, Ansi.CYAN, Ansi.BOLD))

    print(
        f"  Score: {paint(str(stats.score), Ansi.YELLOW, Ansi.BOLD)}"
        f"   Streak: {paint(str(stats.streak), Ansi.MAGENTA, Ansi.BOLD)}"
        f"   Best: {stats.best_streak}"
        f"   W/L: {paint(str(stats.wins), Ansi.GREEN)}"
        f"/{paint(str(stats.losses), Ansi.RED)}"
    )

    if settings:
        print(
            f"  Mode: "
            f"{paint(settings.difficulty.name, Ansi.BOLD)}"
        )


def gallows(stage: int) -> str:
    """Display the appropriate ASCII gallows stage."""
    stage = max(0, min(stage, CLASSIC_ATTEMPTS))
    ratio = stage / CLASSIC_ATTEMPTS

    colour = (
        Ansi.GREEN if ratio < 0.34
        else Ansi.YELLOW if ratio < 0.67
        else Ansi.RED
    )

    return paint(HANGMAN_STAGES[stage], colour)


def lives_bar(game: HangmanGame) -> str:
    """Display remaining and used attempts."""
    full, empty, _, _ = symbols()

    hearts = (
        paint(full * game.attempts_left, Ansi.RED)
        + paint(
            empty * (game.max_attempts - game.attempts_left),
            Ansi.DIM
        )
    )

    return f"{hearts}  ({game.attempts_left}/{game.max_attempts})"


def progress_bar(
    fraction: float,
    width: int = 20
) -> str:
    """Display a compact progress bar."""
    _, _, bar_full, bar_empty = symbols()
    filled = round(fraction * width)

    bar = (
        paint(bar_full * filled, Ansi.GREEN)
        + paint(
            bar_empty * (width - filled),
            Ansi.DIM
        )
    )

    return f"{bar} {int(fraction * 100)}%"


def alphabet_display(game: HangmanGame) -> str:
    """Display correct, incorrect and unused letters."""
    cells = []

    for letter in string.ascii_lowercase:
        if letter in game.correct_letters:
            cells.append(
                paint(letter.upper(), Ansi.GREEN, Ansi.BOLD)
            )
        elif letter in game.wrong_letters:
            cells.append(paint(letter.upper(), Ansi.RED))
        else:
            cells.append(paint(letter.upper(), Ansi.DIM))

    return (
        "  " + " ".join(cells[:13])
        + "\n  " + " ".join(cells[13:])
    )


def render_word(
    game: HangmanGame,
    reveal: bool = False,
    colour: str = Ansi.CYAN
) -> str:
    """Format the hidden or revealed word."""
    parts = []

    for char, shown in game.masked_word(reveal):
        if shown:
            parts.append(paint(char, colour, Ansi.BOLD))
        else:
            parts.append(paint(char, Ansi.DIM))

    return " ".join(parts)


def render(
    game: HangmanGame,
    stats: SessionStats,
    settings: Settings,
    message: str = "",
    message_style: str = Ansi.YELLOW
) -> None:
    """Render the complete gameplay screen."""
    clear_screen()
    banner(stats, settings)

    print(gallows(game.stage))
    print(f"  Lives:    {lives_bar(game)}")
    print(
        f"  Hints:    "
        f"{paint(str(game.hints_left), Ansi.BLUE, Ansi.BOLD)} left"
    )
    print(f"  Progress: {progress_bar(game.progress)}")

    print()
    print(f"  Word:     {render_word(game)}")
    print()
    print(alphabet_display(game))
    print()

    if message:
        print(f"  >> {paint(message, message_style)}\n")


# ============================================================
# INPUT HANDLING
# ============================================================

def prompt_action(
    game: HangmanGame
) -> tuple[str, str]:
    """Ask for a letter, word, hint or quit command."""
    prompt = (
        "  Enter a letter or the whole word "
        f"({paint('?', Ansi.BLUE)} = hint, "
        f"{paint('quit', Ansi.RED)} = exit): "
    )

    while True:
        raw = input(prompt).strip().lower()

        if raw == "quit":
            return "quit", ""

        if raw == "?":
            return "hint", ""

        if not raw:
            print(paint("  Please enter something.", Ansi.YELLOW))
            continue

        if not (raw.isascii() and raw.isalpha()):
            print(
                paint(
                    "  Letters only, please (a-z).",
                    Ansi.YELLOW
                )
            )
            continue

        if len(raw) == 1:
            return "letter", raw

        # FIX: Accept a full-word guess of any length.
        # A wrong full-word guess costs one attempt.
        return "word", raw


def choose_option(
    title: str,
    options: list[str],
    default: int = 0
) -> int:
    """Display a numbered menu and return the selected option."""
    print(f"\n  {paint(title, Ansi.BOLD, Ansi.CYAN)}")

    for i, option in enumerate(options, start=1):
        marker = (
            paint(" (default)", Ansi.DIM)
            if i - 1 == default
            else ""
        )

        print(
            f"    {paint(str(i), Ansi.YELLOW)}. "
            f"{option}{marker}"
        )

    while True:
        raw = input("  > ").strip()

        if not raw:
            return default

        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1

        print(
            paint(
                f"  Please choose a number from 1 to {len(options)}.",
                Ansi.YELLOW
            )
        )


def settings_menu(
    settings: Settings,
    stats: SessionStats
) -> None:
    """Allow the player to choose a difficulty."""
    clear_screen()
    banner(stats)

    diff_labels = [
        f"{d.name:<7} - {d.description}"
        for d in DIFFICULTIES
    ]

    current = DIFFICULTIES.index(settings.difficulty)

    selected = choose_option(
        "Select difficulty",
        diff_labels,
        current
    )

    settings.difficulty = DIFFICULTIES[selected]


# ============================================================
# END SCREENS AND SESSION SUMMARY
# ============================================================

def show_end_screen(
    game: HangmanGame,
    outcome: Outcome,
    stats: SessionStats,
    settings: Settings,
    breakdown: ScoreBreakdown | None = None
) -> None:
    """Display the result of the current round."""
    clear_screen()
    banner(stats, settings)

    print(gallows(game.stage))
    bar = "=" * 44

    if outcome is Outcome.WON and breakdown:
        print(f"\n  {paint(bar, Ansi.GREEN)}")
        print(
            paint(
                "        VICTORY! You saved the day!",
                Ansi.GREEN,
                Ansi.BOLD
            )
        )
        print(f"  {paint(bar, Ansi.GREEN)}")

        print(
            f"  The word was: "
            f"{render_word(game, reveal=True, colour=Ansi.GREEN)}"
        )

        print(f"\n  Base score:     {breakdown.base:>5}")
        print(f"  Hint penalty:   {-breakdown.hint_penalty:>5}")
        print(f"  Streak bonus:   {breakdown.streak_bonus:>5}")

        print(
            f"  {paint('Round total:', Ansi.BOLD)}"
            f"   {paint(str(breakdown.total), Ansi.YELLOW, Ansi.BOLD):>5}\n"
        )

    elif outcome is Outcome.LOST:
        print(f"\n  {paint(bar, Ansi.RED)}")
        print(
            paint(
                "        GAME OVER! Better luck next time!",
                Ansi.RED,
                Ansi.BOLD
            )
        )
        print(f"  {paint(bar, Ansi.RED)}")

        print(
            f"  The word was: "
            f"{render_word(game, reveal=True, colour=Ansi.RED)}"
        )

        print(
            paint(
                "  Your winning streak has been reset.\n",
                Ansi.DIM
            )
        )

    else:
        print(
            f"\n  You quit. The word was: "
            f"{render_word(game, reveal=True, colour=Ansi.YELLOW)}\n"
        )


def show_session_summary(stats: SessionStats) -> None:
    """Display the final session statistics."""
    rounds = stats.wins + stats.losses

    print(f"\n  {paint('SESSION SUMMARY', Ansi.BOLD, Ansi.CYAN)}")
    print(
        f"  Rounds played: {rounds}"
        f"   Wins: {stats.wins}"
        f"   Losses: {stats.losses}"
    )

    print(
        f"  Final score:   "
        f"{paint(str(stats.score), Ansi.YELLOW, Ansi.BOLD)}"
        f"   Best streak: {stats.best_streak}"
    )

    print(
        f"\n  {paint('Thanks for playing. Goodbye!', Ansi.CYAN)}\n"
    )


def post_round_choice() -> str:
    """Return 'again', 'settings' or 'quit'."""
    while True:
        raw = input(
            f"  {paint('[Enter]', Ansi.GREEN)} play again   "
            f"{paint('[s]', Ansi.YELLOW)} change settings   "
            f"{paint('[q]', Ansi.RED)} quit: "
        ).strip().lower()

        if raw in {"", "y", "yes"}:
            return "again"

        if raw in {"s", "settings"}:
            return "settings"

        if raw in {"q", "quit", "n", "no"}:
            return "quit"

        print(
            paint(
                "  Please press Enter, 's' or 'q'.",
                Ansi.YELLOW
            )
        )


# ============================================================
# ROUND LOOP
# ============================================================

def play_round(
    settings: Settings,
    stats: SessionStats,
    word_list: list[str],
    used_words: set[str]
) -> Outcome:
    """Run one complete round of Hangman."""
    word = choose_word(
        settings.difficulty,
        word_list,
        used_words
    )

    game = HangmanGame(
        word,
        settings.difficulty
    )

    message = "Welcome! Guess the hidden word."
    style = Ansi.CYAN

    while not game.is_over:
        render(
            game,
            stats,
            settings,
            message,
            style
        )

        kind, value = prompt_action(game)

        if kind == "quit":
            show_end_screen(
                game,
                Outcome.QUIT,
                stats,
                settings
            )
            return Outcome.QUIT

        if kind == "hint":
            if game.hints_left <= 0:
                message = "No hints left this round!"
                style = Ansi.YELLOW

            elif len(game.hidden_letters) <= 1:
                message = (
                    "Too close to the finish for a hint. "
                    "You've got this!"
                )
                style = Ansi.YELLOW

            else:
                letter = game.use_hint()

                if letter is not None:
                    message = (
                        f"Hint: the word contains "
                        f"'{letter.upper()}'. (-25 points)"
                    )
                    style = Ansi.BLUE

        elif kind == "letter":
            result = game.guess_letter(value)

            if result is GuessResult.REPEAT:
                message = (
                    f"You already guessed '{value.upper()}'. "
                    "No penalty!"
                )
                style = Ansi.YELLOW

            elif result is GuessResult.CORRECT:
                message = (
                    f"Nice! '{value.upper()}' "
                    "is in the word."
                )
                style = Ansi.GREEN

            else:
                message = (
                    f"Sorry, '{value.upper()}' "
                    "is not in the word."
                )
                style = Ansi.RED

        else:
            result = game.guess_word(value)

            if result is GuessResult.CORRECT:
                message = "Brilliant! You guessed the word."
                style = Ansi.GREEN

            elif result is GuessResult.REPEAT:
                message = (
                    f"You already tried '{value.upper()}'. "
                    "No penalty!"
                )
                style = Ansi.YELLOW

            else:
                message = (
                    f"'{value.upper()}' is not the word. "
                    "-1 attempt."
                )
                style = Ansi.RED

    if game.is_won:
        breakdown = calculate_score(
            game,
            stats.streak + 1
        )

        stats.record_win(breakdown.total)

        show_end_screen(
            game,
            Outcome.WON,
            stats,
            settings,
            breakdown
        )

        return Outcome.WON

    stats.record_loss()

    show_end_screen(
        game,
        Outcome.LOST,
        stats,
        settings
    )

    return Outcome.LOST


# ============================================================
# COMMAND-LINE OPTIONS
# ============================================================

def parse_args() -> argparse.Namespace:
    """Parse optional command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Play Hangman 2.0 in your terminal."
    )

    parser.add_argument(
        "--words",
        type=Path,
        default=DEFAULT_WORDS_FILE,
        help="Word list file (one word per line); default: words.txt"
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable coloured output."
    )

    return parser.parse_args()


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main() -> None:
    """Start the game and manage the session."""
    args = parse_args()

    init_terminal(
        force_no_color=args.no_color
    )

    word_list = load_words(args.words)

    stats = SessionStats()
    settings = Settings()
    used_words: set[str] = set()

    try:
        settings_menu(settings, stats)

        while True:
            outcome = play_round(
                settings,
                stats,
                word_list,
                used_words
            )

            if outcome is Outcome.QUIT:
                break

            choice = post_round_choice()

            if choice == "quit":
                break

            if choice == "settings":
                settings_menu(settings, stats)

    except (KeyboardInterrupt, EOFError):
        print("\n\nGame interrupted.")

    show_session_summary(stats)


if __name__ == "__main__":
    main()