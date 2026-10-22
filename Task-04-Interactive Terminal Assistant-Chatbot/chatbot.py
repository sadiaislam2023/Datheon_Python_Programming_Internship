#!/usr/bin/env python3
"""
Task 4: Rule-Based Interactive Terminal Assistant / Chatbot

- Loads greetings and FAQs from faq.json (standard library only)
- Each FAQ may include optional "keywords" and "details" fields
- Handles greetings combined with questions
- Supports follow-ups, help, graceful exit, and bad/missing JSON
- Dashboard-style terminal UI: banner, help panels, status bar and
  timestamped chat bubbles (ANSI colors, ASCII fallback)
- Fully type-annotated (PEP 484) and logs diagnostics to chatbot.log

Run:
    python chatbot.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import textwrap
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple, TypedDict

APP_NAME = "Chatbot"
SUBTITLE = "Rule-based Interactive Terminal Assistant"
# Spaces between the title's letters (0 = none). Makes it look larger.
TITLE_SPACING = 1
# Letter style for the title and subtitle. "plain" uses ordinary letters
# in the terminal's own bold (clear and aligned everywhere). Alternatives:
# "bold" (bold sans-serif Unicode letters) or "fullwidth" (double-width
# letters); both need a terminal font that draws them at the right width.
TITLE_FONT = "plain"
# Title letters fade through these 256-colour codes, gold to teal.
TITLE_GRADIENT = (
    "38;5;221", "38;5;185", "38;5;149", "38;5;113", "38;5;78", "38;5;43",
)
FAQ_FILE = Path(__file__).with_name("faq.json")
LOG_FILE = Path(__file__).with_name("chatbot.log")

EXIT_COMMANDS = {"exit", "quit", "bye", "goodbye", "stop"}
HELP_COMMANDS = {"help", "commands", "what can you do"}

STOP_WORDS = {
    "what", "when", "where", "why", "how", "are", "is", "the", "a", "an",
    "do", "does", "i", "my", "me", "your", "you", "can", "could", "would",
    "please", "tell", "about", "and", "or", "to", "of", "for", "will",
    "be", "it", "we", "our", "get",
}

# Built-in synonyms, keyed by a word that may appear in an FAQ question.
# They let the bot understand rephrasings even when faq.json has no
# "keywords" field. Keys are singular; plurals are handled automatically.
SYNONYMS = {
    "hour": [
        "open", "opening", "close", "closing", "timing", "schedule",
        "what time", "working days", "office hours", "business hours",
    ],
    "submit": [
        "submission", "upload", "turn in", "hand in", "github",
        "repository", "repo",
    ],
    "certificate": ["certification", "certified"],
}

# Friendly names shown in the Quick Help panel. Questions without a known
# topic word are listed by their own text.
TOPIC_LABELS = {
    "hour": "Business hours",
    "submit": "Internship project submission",
    "certificate": "Certificate status and delivery",
}

TAGLINE = "Small steps today, big opportunities tomorrow!"

# 256-color ANSI palette (dark green and gold, like the web dashboard).
GOLD = "38;5;221"
GOLD_SOFT = "38;5;222"
GOLD_DEEP = "38;5;178"
TEAL = "38;5;43"
TEAL_DEEP = "38;5;36"
GREEN = "38;5;48"
FOREST = "38;5;29"
TEXT = "38;5;254"
DIM = "38;5;245"
BOLD = "1"
ITALIC = "3"

UNICODE_GLYPHS: Dict[str, str] = {
    "tl": "\u256d", "tr": "\u256e", "bl": "\u2570", "br": "\u256f",
    "h": "\u2500", "v": "\u2502", "bullet": "\u25b8", "dot": "\u25cf",
    "heart": "\u2665", "arrow": "\u27a4", "star": "\u2726",
    "sep": "\u2022", "avatar": "(\u2022\u203f\u2022)",
}
ASCII_GLYPHS: Dict[str, str] = {
    "tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-", "v": "|",
    "bullet": ">", "dot": "*", "heart": "<3", "arrow": ">", "star": "*",
    "sep": "-", "avatar": "(^_^)",
}
UNICODE_ROBOT = (
    "\u256d\u2500\u2500\u2500\u256e",
    "\u2502\u2022\u203f\u2022\u2502",
    "\u2570\u2500\u2500\u2500\u256f",
)
ASCII_ROBOT = ("+---+", "|o_o|", "+---+")

BULLETS = ("\u25b8", ">", "\u2022")
SEPARATOR = "<separator>"

# Share of an FAQ question's content words a message must contain to
# match when no strong term is present.
MIN_OVERLAP = 0.5

# Below MIN_OVERLAP the bot will not answer, but if at least this share
# of a question's content words appears it offers a "Did you mean...?".
SUGGEST_OVERLAP = 0.25

FOLLOW_UP_PATTERNS = [
    r"\btell me more\b", r"\bmore details?\b", r"\bexplain more\b",
    r"\bcan you elaborate\b", r"\bwhat about that\b",
    r"\bmore information\b",
]

logger = logging.getLogger("chatbot")


class FAQ(TypedDict):
    """One validated FAQ entry."""

    question: str
    answer: str
    details: Optional[str]
    keywords: List[str]
    normalized_question: str
    strong_terms: List[str]
    weak_terms: List[str]
    topic: str


class State(Enum):
    """Where the conversation is: greeting -> intent -> resolution -> exit."""

    GREETING = "greeting"          # nothing asked yet
    IDENTIFYING = "identifying"    # waiting for a question we can answer
    RESOLVED = "resolved"          # last question answered; follow-ups ok
    EXITED = "exited"              # user said bye/exit/quit


@dataclass
class Session:
    """Conversation state carried between turns."""

    state: State = State.GREETING
    last_faq: Optional[FAQ] = None

    def move(self, new_state: State) -> None:
        """Switch state and log the transition."""
        if new_state is not self.state:
            logger.debug(
                "State %s -> %s", self.state.value, new_state.value
            )
            self.state = new_state


def setup_logging(level: int = logging.INFO) -> None:
    """Log to chatbot.log, falling back to stderr if it is unwritable."""
    logger.setLevel(level)
    if logger.handlers:
        return

    handler: logging.Handler
    try:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()

    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
    )
    logger.addHandler(handler)
    logger.propagate = False


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def words(text: str) -> Set[str]:
    """Return the set of alphanumeric words in text."""
    return set(re.findall(r"[a-z0-9]+", text))


def build_terms(
    question: str, keywords: List[str]
) -> Tuple[List[str], List[str]]:
    """Split an FAQ's vocabulary into (strong_terms, weak_terms).

    Strong terms (explicit keywords plus built-in synonyms of words in
    the question) identify the topic by themselves. Weak terms are the
    remaining content words, which only count as supporting evidence.
    """
    content = words(question) - STOP_WORDS
    strong = set(keywords)
    for word in content:
        stem = word[:-1] if word.endswith("s") and len(word) > 3 else word
        if stem in SYNONYMS:
            strong.add(stem)
            strong.update(SYNONYMS[stem])

    weak = {
        w for w in content
        if w not in strong
        and (w[:-1] if w.endswith("s") else w) not in strong
    }
    return sorted(strong), sorted(weak)


def topic_for(question: str) -> str:
    """Short label for the Quick Help panel."""
    for word in re.findall(r"[a-z0-9]+", normalize(question)):
        stem = word[:-1] if word.endswith("s") and len(word) > 3 else word
        if stem in TOPIC_LABELS and word not in STOP_WORDS:
            return TOPIC_LABELS[stem]
    return question.strip().rstrip("?")


def load_faq_data() -> Tuple[List[str], List[FAQ]]:
    """Load and validate faq.json. Returns (greetings, faqs)."""
    if not FAQ_FILE.exists():
        raise FileNotFoundError(
            f"Could not find '{FAQ_FILE.name}'. "
            "Place faq.json in the same folder as chatbot.py."
        )

    try:
        with FAQ_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in {FAQ_FILE.name}: {error}"
        ) from error

    if not isinstance(data, dict):
        raise ValueError("The JSON root must be an object.")

    greetings = data.get("greetings", [])
    faqs = data.get("faqs", [])

    if not isinstance(greetings, list) or not all(
        isinstance(g, str) and g.strip() for g in greetings
    ):
        raise ValueError("'greetings' must be a list of non-empty strings.")
    if not isinstance(faqs, list):
        raise ValueError("'faqs' must be a list of objects.")

    validated: List[FAQ] = []
    for index, item in enumerate(faqs, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"FAQ entry {index} must be an object.")

        question = item.get("question")
        answer = item.get("answer")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(
                f"FAQ entry {index} needs a non-empty question."
            )
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"FAQ entry {index} needs a non-empty answer.")

        keywords = item.get("keywords", [])
        if not isinstance(keywords, list) or not all(
            isinstance(k, str) and k.strip() for k in keywords
        ):
            raise ValueError(
                f"FAQ entry {index}: 'keywords' must be a list of "
                "non-empty strings."
            )

        details = item.get("details")
        if details is not None and (
            not isinstance(details, str) or not details.strip()
        ):
            raise ValueError(
                f"FAQ entry {index}: 'details' must be a non-empty string."
            )

        clean_keywords = [normalize(k) for k in keywords]
        normalized_question = normalize(question)
        strong, weak = build_terms(normalized_question, clean_keywords)
        validated.append({
            "question": question.strip(),
            "answer": answer.strip(),
            "details": details.strip() if details else None,
            "keywords": clean_keywords,
            "normalized_question": normalized_question,
            "strong_terms": strong,
            "weak_terms": weak,
            "topic": topic_for(question),
        })

    return [normalize(g) for g in greetings], validated


def split_greeting(
    message: str, greetings: List[str]
) -> Tuple[bool, str]:
    """Return (had_greeting, remainder) after stripping a greeting."""
    for greeting in sorted(greetings, key=len, reverse=True):
        match = re.match(
            rf"^{re.escape(greeting)}\b[\s!.,?]*(.*)$", message
        )
        if match:
            return True, match.group(1).strip()
    return False, message


def term_present(term: str, message: str) -> bool:
    """True if term appears as a whole word/phrase (plural 's' allowed)."""
    return re.search(rf"\b{re.escape(term)}s?\b", message) is not None


def find_faq(message: str, faqs: List[FAQ]) -> Optional[FAQ]:
    """Match by exact question, strong terms, then word overlap."""
    cleaned = message.rstrip("?!. ")
    for faq in faqs:
        if cleaned == faq["normalized_question"].rstrip("?!. "):
            return faq

    # Strong terms identify a topic; weak terms break ties.
    best: Optional[FAQ] = None
    best_key = (0, 0)
    for faq in faqs:
        strong_hits = sum(
            term_present(t, message) for t in faq["strong_terms"]
        )
        weak_hits = sum(term_present(t, message) for t in faq["weak_terms"])
        if strong_hits and (strong_hits, weak_hits) > best_key:
            best, best_key = faq, (strong_hits, weak_hits)
    if best is not None:
        return best

    # No strong term: require most of the question's content words,
    # so a single shared word ("internship") is not enough.
    candidate, score = best_overlap(message, faqs)
    return candidate if score >= MIN_OVERLAP else None


def best_overlap(
    message: str, faqs: List[FAQ]
) -> Tuple[Optional[FAQ], float]:
    """Return the FAQ sharing the most content words, with its score.

    The score is the share of the FAQ question's content words that
    appear in the message (0.0 to 1.0): a simple confidence measure.
    """
    message_words = words(message)
    best: Optional[FAQ] = None
    best_score = 0.0
    for faq in faqs:
        q_words = words(faq["normalized_question"]) - STOP_WORDS
        if not q_words:
            continue
        score = len(message_words & q_words) / len(q_words)
        if score > best_score:
            best, best_score = faq, score
    return best, best_score


def topics(faqs: List[FAQ]) -> str:
    """Bullet list of the questions the assistant can answer."""
    return "\n".join(f"  \u2022 {faq['question']}" for faq in faqs)


def wrap_text(text: str, width: int) -> List[str]:
    """Wrap text to width, keeping indentation and bullet hanging."""
    width = max(width, 10)
    lines: List[str] = []
    for paragraph in text.split("\n"):
        stripped = paragraph.lstrip()
        indent = paragraph[: len(paragraph) - len(stripped)]
        if stripped.startswith(BULLETS):
            indent += "  "
        wrapped = textwrap.wrap(
            paragraph, width, subsequent_indent=indent
        )
        lines.extend(wrapped or [""])
    return lines


def display_width(text: str) -> int:
    """Terminal columns text occupies (full-width characters take two)."""
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in text
    )


def to_fullwidth(text: str) -> str:
    """Convert printable ASCII to full-width letters (two columns each)."""
    converted = []
    for char in text:
        if char == " ":
            converted.append("　")  # ideographic space, two columns
        elif "!" <= char <= "~":
            converted.append(chr(ord(char) + 0xFEE0))
        else:
            converted.append(char)
    return "".join(converted)


def to_bold_sans(text: str) -> str:
    """Convert letters and digits to bold sans-serif Unicode letters."""
    converted = []
    for char in text:
        if "A" <= char <= "Z":
            converted.append(chr(0x1D5D4 + ord(char) - ord("A")))
        elif "a" <= char <= "z":
            converted.append(chr(0x1D5EE + ord(char) - ord("a")))
        elif "0" <= char <= "9":
            converted.append(chr(0x1D7EC + ord(char) - ord("0")))
        else:
            converted.append(char)
    return "".join(converted)


def timestamp() -> str:
    """Return the current local time in 24-hour format."""
    return datetime.now().strftime("%H:%M")


class TerminalUI:
    """Dashboard-style terminal interface.

    Uses ANSI colors and rounded boxes when the terminal supports them,
    and degrades to plain ASCII when it does not (piped output, NO_COLOR,
    legacy encodings).
    """

    def __init__(
        self,
        color: Optional[bool] = None,
        width: Optional[int] = None,
        unicode: Optional[bool] = None,
        interactive: Optional[bool] = None,
    ) -> None:
        self.ansi = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
        if color is None:
            color = self.ansi and "NO_COLOR" not in os.environ
        if interactive is None:
            interactive = self.ansi and sys.stdin.isatty()
        if width is None:
            columns = shutil.get_terminal_size((100, 30)).columns
            width = max(50, min(columns, 100))
        if unicode is None:
            unicode = self._can_encode()

        self.color = color
        self.interactive = interactive
        self.wide = unicode  # full-width letters need Unicode output
        self.width = width
        self.g = UNICODE_GLYPHS if unicode else ASCII_GLYPHS
        self.robot = UNICODE_ROBOT if unicode else ASCII_ROBOT

        if self.ansi and os.name == "nt":
            os.system("")  # enables ANSI escape handling on Windows 10+

    @staticmethod
    def _can_encode() -> bool:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        sample = (
            "\u256d\u2500\u2502\u2022\u203f\u25b8\u25cf\u2665\u27a4\u2726"
            "\uff23\u3000\U0001d5d4"
        )
        try:
            sample.encode(encoding)
        except (UnicodeEncodeError, LookupError):
            return False
        return True

    # -- low-level helpers ------------------------------------------------

    def paint(self, text: str, *codes: str) -> str:
        """Wrap text in ANSI codes (no-op when color is off)."""
        if not self.color or not codes or not text:
            return text
        return f"\033[{';'.join(codes)}m{text}\033[0m"

    def _max_inner(self) -> int:
        """Widest text a chat bubble may hold."""
        return max(20, int(self.width * 0.72) - 4)

    def _bubble(
        self, text: str, border: str, body: str
    ) -> Tuple[List[str], int]:
        """Rounded chat bubble. Returns (rows, visible_width)."""
        g = self.g
        lines = wrap_text(text, self._max_inner())
        inner = max(len(line) for line in lines)
        edge = self.paint(g["v"], border)
        bar = g["h"] * (inner + 2)
        rows = [self.paint(g["tl"] + bar + g["tr"], border)]
        for line in lines:
            rows.append(
                edge + " " + self.paint(line.ljust(inner), body) + " " + edge
            )
        rows.append(self.paint(g["bl"] + bar + g["br"], border))
        return rows, inner + 4

    def _panel(
        self, title: str, rows: Sequence[Tuple[str, str]], width: int
    ) -> List[str]:
        """Titled, rounded panel of exactly `width` visible columns."""
        g = self.g
        inner = width - 4
        label = f"{g['star']} {title}"
        fill = max(0, width - 5 - len(label))
        edge = self.paint(g["v"], FOREST)
        out = [
            self.paint(g["tl"] + g["h"] + " ", FOREST)
            + self.paint(label, GOLD, BOLD)
            + self.paint(" " + g["h"] * fill + g["tr"], FOREST)
        ]
        for text, style in rows:
            if text == SEPARATOR:
                wrapped = [g["h"] * inner]
            else:
                wrapped = wrap_text(text, inner)
            for line in wrapped:
                out.append(
                    edge + " " + self.paint(line.ljust(inner), style)
                    + " " + edge
                )
        bottom = g["bl"] + g["h"] * (width - 2) + g["br"]
        out.append(self.paint(bottom, FOREST))
        return out

    def _style(self, text: str) -> str:
        """Apply TITLE_FONT to text (plain when Unicode is unavailable)."""
        if not self.wide:
            return text
        if TITLE_FONT == "bold":
            return to_bold_sans(text)
        if TITLE_FONT == "fullwidth":
            return to_fullwidth(text)
        return text

    def _fit_title(self, avail: int) -> str:
        """Most decorated form of the title that fits in `avail` columns.

        Tried in order: sparkles + styled spaced letters, styled spaced
        letters, plain spaced letters (with and without sparkles), and
        finally plain capitals.
        """
        letters = APP_NAME.upper()
        spacer = " " * TITLE_SPACING
        star = self.g["star"]
        styled = spacer.join(self._style(c) for c in letters)
        plain = spacer.join(letters)
        candidates = [
            f"{star} {styled} {star}", styled,
            f"{star} {plain} {star}", plain, letters,
        ]
        for title in candidates:
            if display_width(title) <= avail:
                return title
        return letters

    def _fit_subtitle(self, avail: int) -> str:
        """Styled subtitle if it fits, else plain text (shortened)."""
        styled = self._style(SUBTITLE)
        if display_width(styled) <= avail:
            return styled
        if len(SUBTITLE) > avail:
            return textwrap.shorten(SUBTITLE, avail, placeholder="...")
        return SUBTITLE

    def _paint_title(self, title: str) -> str:
        """Bold title with its letters fading through TITLE_GRADIENT."""
        letters = [i for i, char in enumerate(title) if char.isalpha()]
        if not letters:
            return self.paint(title, GOLD, BOLD)
        steps = len(TITLE_GRADIENT) - 1
        painted = []
        for index, char in enumerate(title):
            if char == " ":
                painted.append(char)
            elif index in letters:
                rank = letters.index(index)
                position = round(rank * steps / max(len(letters) - 1, 1))
                painted.append(
                    self.paint(char, TITLE_GRADIENT[position], BOLD)
                )
            else:  # sparkle: gold on the left, teal on the right
                edge = 0 if index < letters[0] else steps
                painted.append(
                    self.paint(char, TITLE_GRADIENT[edge], BOLD)
                )
        return "".join(painted)

    # -- screens ----------------------------------------------------------

    def banner(self) -> None:
        """Header with robot logo, title, subtitle and tagline."""
        g = self.g
        inner = self.width - 4
        avail = inner - 8  # robot (5) + gap (3)
        tag = f" {g['sep']} ".join(["Ask", "Get Answers", "Be Productive"])

        if len(tag) <= avail:
            tag_row = " " * (avail - len(tag)) + self.paint(tag, DIM)
            tag_len = avail
        else:
            tag_row, tag_len = "", 0

        # A terminal cannot scale fonts, so the text is made bigger with
        # full-width letters: normal letter shapes that take two columns
        # each. The title is capitals with spacing, so it stays the
        # dominant line. Each line falls back to a narrower form (spaced
        # capitals, then plain text) when the terminal is too narrow, or
        # cannot display full-width characters (ASCII mode).
        title = self._fit_title(avail)
        subtitle = self._fit_subtitle(avail)

        # One content row per row of the 3-row robot logo.
        contents: List[Tuple[str, int]] = [
            (tag_row, tag_len),
            (self._paint_title(title), display_width(title)),
            (self.paint(subtitle, GOLD, BOLD), display_width(subtitle)),
        ]
        offset = 0
        blank = " " * len(self.robot[0])

        edge = self.paint(g["v"], TEAL_DEEP)
        bar = g["h"] * (self.width - 2)
        print(self.paint(g["tl"] + bar + g["tr"], TEAL_DEEP))
        for index, (content, length) in enumerate(contents):
            robot_row = index - offset
            if 0 <= robot_row < len(self.robot):
                art = self.paint(self.robot[robot_row], TEAL)
            else:
                art = blank
            pad = " " * (avail - length)
            print(edge + " " + art + "   " + content + pad + " " + edge)
        print(self.paint(g["bl"] + bar + g["br"], TEAL_DEEP))

    def panels(self, faqs: List[FAQ]) -> None:
        """Quick Help and Sample Questions, side by side if there is room."""
        bullet = self.g["bullet"]
        help_rows: List[Tuple[str, str]] = [("You can ask about:", TEXT)]
        help_rows += [(f"{bullet} {faq['topic']}", TEXT) for faq in faqs]
        help_rows += [
            (SEPARATOR, FOREST),
            ("Type 'help' for more options.", DIM),
            ("Type 'bye', 'exit' or 'quit' to leave.", DIM),
        ]
        sample_rows: List[Tuple[str, str]] = [
            (bullet + ' "' + faq["question"] + '"', TEXT) for faq in faqs
        ]
        sample_rows.append((bullet + ' "Tell me more"', TEXT))

        if self.width >= 90:
            left_w = (self.width - 1) // 2
            right_w = self.width - left_w - 1
            left = self._panel("Quick Help", help_rows, left_w)
            right = self._panel("Sample Questions", sample_rows, right_w)
            height = max(len(left), len(right))
            left += [" " * left_w] * (height - len(left))
            right += [" " * right_w] * (height - len(right))
            for left_line, right_line in zip(left, right):
                print(left_line + " " + right_line)
        else:
            stacked = (("Quick Help", help_rows),
                       ("Sample Questions", sample_rows))
            for title, rows in stacked:
                for line in self._panel(title, rows, self.width):
                    print(line)

    def status_bar(self) -> None:
        """'Chatbot Online' divider above the conversation."""
        g = self.g
        left = f" {g['dot']} Chatbot Online "
        right = f" {g['heart']} Ready to help! "
        fill = max(1, self.width - 4 - len(left) - len(right))
        print(
            self.paint(g["h"] * 2, FOREST)
            + self.paint(f" {g['dot']}", GREEN)
            + self.paint(" Chatbot Online ", TEAL, BOLD)
            + self.paint(g["h"] * fill, FOREST)
            + self.paint(right, TEAL)
            + self.paint(g["h"] * 2, FOREST)
        )
        print()

    def welcome(self, faqs: List[FAQ]) -> None:
        """Clear the screen (interactive only) and draw the dashboard."""
        if self.interactive:
            sys.stdout.write("\033[2J\033[H")
        print()
        self.banner()
        print()
        self.panels(faqs)
        quote = f"{self.g['star']} {TAGLINE} {self.g['star']}"
        indent = " " * max(0, (self.width - len(quote)) // 2)
        print(indent + self.paint(quote, GOLD_DEEP, ITALIC))
        print()
        self.status_bar()

    # -- conversation -----------------------------------------------------

    def user_message(self, text: str) -> None:
        """Right-aligned gold bubble with a 'time  You' label."""
        stamp = timestamp()
        rows, bubble_width = self._bubble(text, GOLD_DEEP, GOLD_SOFT)
        label_len = len(stamp) + 2 + len("You")
        print(
            " " * (self.width - label_len - 1) + self.paint(stamp, DIM)
            + "  " + self.paint("You", GOLD, BOLD)
        )
        margin = " " * (self.width - bubble_width - 1)
        for row in rows:
            print(margin + row)
        print()

    def assistant_message(self, text: str) -> None:
        """Left-aligned teal bubble with an 'Assistant  time' label."""
        rows, _ = self._bubble(text, TEAL_DEEP, TEXT)
        print(
            "  " + self.paint(self.g["avatar"], TEAL) + " "
            + self.paint("Assistant", GOLD, BOLD) + "  "
            + self.paint(timestamp(), DIM)
        )
        for row in rows:
            print("  " + row)
        print()

    def read_input(self) -> str:
        """Read a message from a boxed input field (plain if piped)."""
        if not self.interactive:
            return input()

        g, width = self.g, self.width
        hint = "Type your message..."
        fill = width - 5 - len(hint)
        print(
            self.paint(g["tl"] + g["h"] + " ", FOREST)
            + self.paint(hint, DIM)
            + self.paint(" " + g["h"] * fill + g["tr"], FOREST)
        )
        print(
            self.paint(g["v"], FOREST) + " " * (width - 2)
            + self.paint(g["v"], FOREST)
        )
        print(self.paint(g["bl"] + g["h"] * (width - 2) + g["br"], FOREST))

        prompt = g["v"] + " " + g["arrow"] + " "
        # Move back up into the empty box and type inside it.
        sys.stdout.write("\033[2A\033[1G" + self.paint(prompt, TEAL))
        sys.stdout.flush()
        try:
            text = input()
        except (EOFError, KeyboardInterrupt):
            sys.stdout.write("\033[1B\033[1G\n")
            raise

        # Erase the input box; the message is redrawn as a chat bubble.
        columns = shutil.get_terminal_size((width, 30)).columns
        extra = (len(prompt) + len(text) - 1) // max(columns, 1)
        sys.stdout.write(f"\033[{2 + extra}A\033[1G\033[J")
        sys.stdout.flush()
        return text


def help_text(faqs: List[FAQ]) -> str:
    """Build the help message from the loaded FAQs."""
    return (
        "Here is what you can ask me:\n"
        f"{topics(faqs)}\n"
        "  \u2022 'tell me more' for extra detail on the last answer\n"
        "  \u2022 'exit', 'quit', or 'bye' to leave"
    )


def follow_up(last_faq: Optional[FAQ], faqs: List[FAQ]) -> str:
    """Answer 'tell me more' using the last FAQ's details."""
    if last_faq is None:
        return "What would you like more information about?\n" + topics(faqs)
    if last_faq["details"]:
        return last_faq["details"]
    return (
        "That's all the detail I have on that topic. "
        f"To recap: {last_faq['answer']}"
    )


def get_response(
    message: str,
    greetings: List[str],
    faqs: List[FAQ],
    session: Session,
) -> str:
    """Return the reply for message and advance the session state.

    Flow: GREETING -> IDENTIFYING -> RESOLVED -> EXITED. A matched FAQ
    resolves the conversation; the user can then ask a follow-up or
    another question, which re-enters identification and resolution.
    """
    text = normalize(message)

    if not text:
        return "Please enter a message so I can help you."
    if text in EXIT_COMMANDS:
        session.move(State.EXITED)
        return "Goodbye! Thank you for chatting. Have a great day!"
    if text in HELP_COMMANDS:
        return help_text(faqs)

    had_greeting, text = split_greeting(text, greetings)
    if had_greeting and not text:
        session.move(State.IDENTIFYING)
        return (
            "Hello! Welcome to the Interactive Terminal Assistant. "
            "How can I help you today?"
        )

    if any(re.search(p, text) for p in FOLLOW_UP_PATTERNS):
        logger.debug(
            "Follow-up request (state: %s)", session.state.value
        )
        return follow_up(session.last_faq, faqs)

    # FAQ intent comes first so mixed messages ("thanks, but ...") work.
    faq = find_faq(text, faqs)
    if faq is not None:
        logger.info("Matched FAQ %r for input %r", faq["question"], text)
        session.last_faq = faq
        session.move(State.RESOLVED)
        prefix = "Hello! " if had_greeting else ""
        return prefix + faq["answer"]

    # Anything below is small talk or a miss: no FAQ was resolved.
    if session.state is State.GREETING:
        session.move(State.IDENTIFYING)

    if re.search(r"\b(thank you|thanks|thankyou|thx)\b", text):
        return "You're welcome! Let me know if you need anything else."
    if re.search(r"\b(who are you|your name|what are you)\b", text):
        return f"I'm {APP_NAME}, a simple rule-based chatbot."
    if re.search(r"\bhow are you\b", text):
        return "I'm functioning properly and ready to help!"
    if re.fullmatch(r"(okay|ok|got it|understood)[!. ]*", text):
        return "Great! Feel free to ask if you have another question."

    # Low confidence: offer the closest question instead of guessing.
    closest, score = best_overlap(text, faqs)
    if closest is not None and score >= SUGGEST_OVERLAP:
        logger.info(
            "Low confidence (%.2f) for %r; suggesting %r",
            score, text, closest["question"],
        )
        return (
            "I'm not sure I understood. Did you mean: "
            f"\"{closest['question'].rstrip('?')}\"? "
            "Ask it again to confirm, or type 'help' to see all topics."
        )

    logger.warning("No match for input %r", text)
    return (
        "Sorry, I couldn't find a matching answer. "
        "Type 'help' to see what I can answer."
    )


def main() -> None:
    """Run the interactive terminal chatbot."""
    setup_logging()
    logger.info("Starting %s", APP_NAME)

    try:
        greetings, faqs = load_faq_data()
    except (FileNotFoundError, ValueError) as error:
        logger.error("Could not load %s: %s", FAQ_FILE.name, error)
        print(f"Error: {error}")
        return
    except OSError as error:
        logger.exception("Could not read %s", FAQ_FILE.name)
        print(f"Error reading {FAQ_FILE.name}: {error}")
        return

    logger.info(
        "Loaded %d greetings and %d FAQs", len(greetings), len(faqs)
    )
    ui = TerminalUI()
    ui.welcome(faqs)
    session = Session()

    while session.state is not State.EXITED:
        try:
            message = ui.read_input()
        except (EOFError, KeyboardInterrupt):
            logger.info("Session ended by EOF or Ctrl-C")
            ui.assistant_message("Goodbye! Take care.")
            break

        if message.strip():
            ui.user_message(message)
        ui.assistant_message(
            get_response(message, greetings, faqs, session)
        )

    if session.state is State.EXITED:
        logger.info("Session ended by user command")


if __name__ == "__main__":
    main()