#!/usr/bin/env python3
"""
organizer.py - Automated File Organizer & Cleanup Utility.

Features:
    - Colorful terminal interface with cards and progress indicators.
    - Folder path validation and confirmation.
    - File categorization and sorting.
    - Preview (dry-run) mode.
    - Three sorting modes: type, type_date, and date.
    - Recursive scanning of directory trees (on by default).
    - Safe filename collision handling.
    - Undo the last organization run.
    - Logging and error handling.

Usage:
    python organizer.py
    python organizer.py Projects
    python organizer.py "D:\\MyFiles"
    python organizer.py "D:\\MyFiles" --yes
    python organizer.py "D:\\MyFiles" --dry-run
    python organizer.py "D:\\MyFiles" --mode type_date
    python organizer.py "D:\\MyFiles" --no-recursive
    python organizer.py "D:\\MyFiles" --undo
"""

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from collections import namedtuple
from datetime import datetime
from pathlib import Path

APP_NAME = "ORGANIZER"
VERSION = "7.2"
TITLE = "Automated File Organizer & Cleanup Utility"

# ==========================================================
# FILE CATEGORIES
# ==========================================================

_CATEGORY_EXTENSIONS = {
    "Documents": (
        ".pdf .doc .docx .txt .rtf .odt .xls .xlsx .csv "
        ".ppt .pptx .md"
    ),
    "Images": (
        ".jpg .jpeg .png .gif .bmp .svg .webp .ico "
        ".tiff .heic"
    ),
    "Videos": (
        ".mp4 .mkv .mov .avi .wmv .flv .webm .mpeg .mpg"
    ),
    "Audio": ".mp3 .wav .aac .ogg .flac .m4a .wma",
    "Archives": ".zip .rar .7z .tar .gz .bz2 .xz",
    "Code": (
        ".py .js .jsx .ts .tsx .html .css .java .c .cpp "
        ".h .hpp .cs .php .sql .json .xml .yaml .yml .sh "
        ".bat .ps1"
    ),
}

EXTENSION_MAP = {
    ext: category
    for category, extensions in _CATEGORY_EXTENSIONS.items()
    for ext in extensions.split()
}

DEFAULT_CATEGORY = "Other"
CATEGORY_ORDER = list(_CATEGORY_EXTENSIONS) + [DEFAULT_CATEGORY]

MODES = {
    "type": (
        "By file type",
        "Documents/, Images/, Videos/ ..."
    ),
    "type_date": (
        "File type + month",
        "Documents/2026-10/, Images/2026-09/ ..."
    ),
    "date": (
        "By month only",
        "2026-10/, 2026-09/ ..."
    ),
}

SKIP_SUFFIXES = {
    ".crdownload",
    ".part",
    ".partial",
    ".tmp",
    ".download",
}

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "organizer.log"
HISTORY_FILE = BASE_DIR / "organizer_history.json"

PROTECTED_FILES = {
    Path(__file__).resolve(),
    LOG_FILE,
    HISTORY_FILE,
}

DATE_DIR_RE = re.compile(r"^\d{4}(-\d{2})?$")
ANSI_RE = re.compile(r"\033\[[0-9;]*m")

FileItem = namedtuple("FileItem", "path name size mtime")

# ==========================================================
# COLOR SYSTEM
# ==========================================================

USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ

if os.name == "nt":
    os.system("")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass


def fg(number):
    return f"\033[38;5;{number}m" if USE_COLOR else ""


def bg(number):
    return f"\033[48;5;{number}m" if USE_COLOR else ""


RESET = "\033[0m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""

T_AMBER = 214
T_ORANGE = 208
T_GOLD = 220
T_BLUE = 75
T_PURPLE = 141
T_TEAL = 79
T_GREEN = 114
T_RED = 203
T_YELLOW = 221
T_GRAY = 245

INK = 16
BODY_BG = 236
BAR_BG = 235

GREEN = fg(T_GREEN)
RED = fg(T_RED)
YELLOW = fg(T_YELLOW)
WHITE = fg(255)
GRAY = fg(247)
DARK = fg(241)

CATEGORY_THEME = {
    "Documents": 111,
    "Images": 177,
    "Videos": 203,
    "Audio": 79,
    "Archives": 221,
    "Code": 114,
    DEFAULT_CATEGORY: 249,
}

# ==========================================================
# TERMINAL LAYOUT
# ==========================================================

WIDTH = max(
    64,
    min(shutil.get_terminal_size((80, 24)).columns - 2, 84)
)


def visible_len(text):
    return len(ANSI_RE.sub("", str(text)))


def pad(text, width):
    return str(text) + " " * max(
        0, width - visible_len(str(text))
    )


def center(text, width):
    text_width = visible_len(text)
    spaces = max(0, width - text_width)
    left = spaces // 2
    return " " * left + text + " " * (spaces - left)


def truncate(text, width):
    text = str(text)
    if len(text) <= width:
        return text
    return text[:max(0, width - 1)] + "…"


def keep_bg(text, background):
    if not USE_COLOR:
        return text
    return text.replace(RESET, RESET + background)


def fill_row(text, bg_n, align="left", fg_n=None):
    background = bg(bg_n)
    ink = fg(fg_n) if fg_n is not None else ""

    body = keep_bg(text, background + ink)
    body = (
        center(body, WIDTH)
        if align == "center"
        else pad(body, WIDTH)
    )

    print(f" {background}{ink}{body}{RESET}")


def bar(value, total, width=22, color_n=T_AMBER):
    filled = round(value / max(total, 1) * width)

    return (
        f"{fg(color_n)}{'█' * filled}{RESET}"
        f"{fg(239)}{'░' * (width - filled)}{RESET}"
    )


def badge(text, color_n):
    if USE_COLOR:
        return (
            f"{bg(color_n)}{fg(INK)}{BOLD} "
            f"{text} {RESET}"
        )
    return f"[{text}]"


def fmt_size(number):
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            if unit == "B":
                return f"{number:.0f} {unit}"
            return f"{number:.1f} {unit}"
        number /= 1024


def category_rows(counts, total):
    rows = []

    for category in CATEGORY_ORDER:
        if category not in counts:
            continue

        number = counts[category]
        tone = CATEGORY_THEME[category]

        rows.append(
            f"{fg(tone)}●{RESET} "
            f"{WHITE}{pad(category, 11)}{RESET}"
            f"{bar(number, total, 22, tone)} "
            f"{fg(T_GOLD)}{BOLD}{number:>4}{RESET} "
            f"{GRAY}file(s){RESET} "
            f"{DARK}{number / max(total, 1) * 100:>5.1f}%{RESET}"
        )

    return rows


# ==========================================================
# CARD LAYOUT
# ==========================================================

def phase_card(lines, num, title, caption, theme):
    if USE_COLOR:
        left_a = f"  {num}  "
        left_b = f"  {title.upper()}  "

        room = WIDTH - len(left_a) - len(left_b)
        cap = (
            f"{caption}  "
            if caption and len(caption) + 2 < room
            else ""
        )
        gap = " " * max(0, room - len(cap))

        print(
            f" {bg(BAR_BG)}{fg(theme)}{BOLD}{left_a}{RESET}"
            f"{bg(theme)}{fg(INK)}{BOLD}{left_b}{gap}{RESET}"
            f"{bg(theme)}{fg(52)}{cap}{RESET}"
        )
    else:
        print(
            f" [{num}] {title.upper()}"
            + (f"  - {caption}" if caption else "")
        )
        print(" " + "─" * (WIDTH - 1))

    background = bg(BODY_BG)
    accent = f"{background}{fg(theme)}▌{RESET}{background}"

    for text in [""] + list(lines) + [""]:
        row = pad(
            keep_bg(str(text), background),
            WIDTH - 5
        )
        print(f" {accent}  {row}  {RESET}")


def stat_tiles(items):
    number_of_tiles = len(items)
    base = (WIDTH - (number_of_tiles - 1)) // number_of_tiles

    widths = [base] * number_of_tiles
    widths[-1] += (
        WIDTH - (
            base * number_of_tiles + number_of_tiles - 1
        )
    )

    rows = ["", "", "", ""]

    for index, ((label, value, theme), width) in enumerate(
        zip(items, widths)
    ):
        active = theme is not None
        background = bg(theme if active else 238)
        ink = fg(INK if active else 250)
        gap = " " if index < number_of_tiles - 1 else ""

        cells = [
            "",
            f"{BOLD}{label.upper()}{RESET}{background}{ink}",
            f"{BOLD}{value}{RESET}{background}{ink}",
            "",
        ]

        for row_index, cell in enumerate(cells):
            rows[row_index] += (
                f"{background}{ink}{center(cell, width)}"
                f"{RESET}{gap}"
            )

    for row in rows:
        print(" " + row)


def show_banner(label, theme):
    print()

    fill_row("", T_AMBER)
    fill_row(f"{BOLD}{TITLE}{RESET}", T_AMBER, "center", INK)
    fill_row(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        T_AMBER,
        "center",
        94,
    )
    fill_row(
        "Sorts any folder into smart category folders - safely",
        T_AMBER,
        "center",
        94,
    )
    fill_row("", T_AMBER)

    if USE_COLOR:
        shades = [222, 220, 214, 208, 202, 166]
        segment_width = WIDTH // len(shades)
        strip = ""

        for index, shade in enumerate(shades):
            width = (
                segment_width
                if index < len(shades) - 1
                else WIDTH - segment_width * (len(shades) - 1)
            )
            strip += f"{bg(shade)}{' ' * width}"

        print(f" {strip}{RESET}")
    else:
        print(" " + "━" * WIDTH)

    info = (
        f"{fg(T_AMBER)}{BOLD}v{VERSION}{RESET}"
        f"{fg(247)}   │   "
        f"{WHITE}{datetime.now():%Y-%m-%d  %H:%M}{RESET}"
        f"{fg(247)}   │   "
        f"{badge(label, theme)}"
    )

    fill_row(info, BAR_BG, "center")


def error_card(message):
    print()
    phase_card(
        [f"{RED}{message}{RESET}"],
        "!!",
        "Error",
        "action required",
        T_RED,
    )


def info_card(
    message,
    title="Notice",
    caption="",
    theme=T_YELLOW,
):
    print()
    phase_card(
        [f"{fg(theme)}{message}{RESET}"],
        "--",
        title,
        caption,
        theme,
    )


# ==========================================================
# FOLDER VALIDATION
# ==========================================================

_PROTECTED_UNIX = (
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib64",
    "/proc",
    "/root",
    "/run",
    "/sbin",
    "/sys",
    "/usr",
    "/var",
)

_PROTECTED_WIN = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
)


def validate_folder(raw):
    """
    Validate the user-provided path.

    Returns:
        (resolved_folder, None) on success.
        (None, error_message) on failure.
    """
    raw = raw.strip().strip('"').strip("'")

    if not raw:
        return None, "No path entered."

    candidate = Path(raw).expanduser()

    # Allow a relative folder path from the script directory.
    if (
        not candidate.exists()
        and not candidate.is_absolute()
        and (BASE_DIR / candidate).exists()
    ):
        candidate = BASE_DIR / candidate

    if not candidate.exists():
        return None, "That folder does not exist."

    if candidate.is_symlink():
        return None, "Symbolic-link folders are not supported."

    if not candidate.is_dir():
        return None, "That path is a file, not a folder."

    try:
        folder = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "Could not resolve that folder path."

    lowered = str(folder).lower()

    if folder == BASE_DIR:
        return None, (
            "That is the script's own folder. "
            "Pick a different one."
        )

    if folder.parent == folder:
        return None, "A drive root cannot be organized."

    try:
        if folder == Path.home().resolve():
            return None, (
                "Your whole home folder is too broad. "
                "Pick a subfolder."
            )
    except OSError:
        pass

    if os.name == "nt":
        for protected in _PROTECTED_WIN:
            if (
                lowered == protected
                or lowered.startswith(protected + "\\")
            ):
                return None, "System folders are protected."
    else:
        for protected in _PROTECTED_UNIX:
            if (
                lowered == protected
                or lowered.startswith(protected + "/")
            ):
                return None, "System folders are protected."

    return folder, None


# ==========================================================
# CORE FILE OPERATIONS
# ==========================================================

def get_category(name):
    return EXTENSION_MAP.get(
        Path(name).suffix.lower(),
        DEFAULT_CATEGORY,
    )


def scan_files(root, recursive=False):
    """
    Scan regular files in the selected folder.

    Hidden files, symlinks, temporary downloads and the script's
    own log/history files are skipped.
    """
    items = []

    def walk(folder, top):
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue

                if entry.name.startswith("."):
                    continue

                if is_dir:
                    if recursive:
                        if top and (
                            entry.name in CATEGORY_ORDER
                            or DATE_DIR_RE.match(entry.name)
                        ):
                            continue

                        try:
                            walk(Path(entry.path), False)
                        except PermissionError:
                            logging.warning(
                                "Cannot read folder: %s",
                                entry.path,
                            )
                        except OSError as error:
                            logging.warning(
                                "Cannot scan folder %s: %s",
                                entry.path,
                                error,
                            )
                    continue

                if not is_file:
                    continue

                try:
                    resolved = Path(entry.path).resolve()
                except (OSError, RuntimeError):
                    continue

                if resolved in PROTECTED_FILES:
                    continue

                if Path(entry.name).suffix.lower() in SKIP_SUFFIXES:
                    continue

                try:
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue

                items.append(
                    FileItem(
                        Path(entry.path),
                        entry.name,
                        stat.st_size,
                        stat.st_mtime,
                    )
                )

    walk(Path(root), True)

    return sorted(
        items,
        key=lambda item: (
            str(item.path.parent).lower(),
            item.name.lower(),
        ),
    )


def target_folder_for(item, root, mode):
    category = get_category(item.name)

    month = datetime.fromtimestamp(item.mtime).strftime("%Y-%m")

    if mode == "type_date":
        return root / category / month

    if mode == "date":
        return root / month

    return root / category


def candidate_names(destination):
    """Generate collision-free names without overwriting existing files."""
    yield destination

    counter = 1

    while True:
        yield destination.with_name(
            f"{destination.stem}_{counter}{destination.suffix}"
        )
        counter += 1


def inside(parent, child):
    """Return whether child resolves to parent or a descendant."""
    try:
        parent = Path(parent).resolve()
        child = Path(child).resolve()
        return child == parent or parent in child.parents
    except (OSError, RuntimeError):
        return False


def safe_move(source, target_folder, root):
    """
    Move a file into a destination inside root.

    Never intentionally overwrites an existing destination.
    """
    source = Path(source)
    target_folder = Path(target_folder)
    root = Path(root).resolve()

    if not inside(root, target_folder):
        raise PermissionError(
            "Refusing to move outside the chosen folder: "
            f"{target_folder}"
        )

    target_folder.mkdir(parents=True, exist_ok=True)

    for destination in candidate_names(target_folder / source.name):
        if destination.exists():
            continue

        try:
            # Prevent overwriting a destination that already exists.
            # os.rename is atomic on the same filesystem, but does not
            # have identical collision semantics on every platform.
            if destination.exists():
                continue

            shutil.move(str(source), str(destination))
            return destination

        except FileExistsError:
            continue

    raise OSError("Could not find an available destination filename.")


# ==========================================================
# HISTORY AND UNDO
# ==========================================================

def load_history():
    try:
        data = json.loads(
            HISTORY_FILE.read_text(encoding="utf-8")
        )
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_history(history):
    try:
        HISTORY_FILE.write_text(
            json.dumps(history[-20:], indent=1),
            encoding="utf-8",
        )
    except OSError:
        logging.exception("Could not write history file")


def record_run(folder, mode, moves):
    history = load_history()

    history.append({
        "time": datetime.now().isoformat(timespec="seconds"),
        "folder": str(folder),
        "mode": mode,
        "moves": moves,
        "undone": False,
    })

    save_history(history)


def undo_last(folder, assume_yes=False):
    folder = Path(folder).resolve()
    history = load_history()

    run = next(
        (
            entry
            for entry in reversed(history)
            if entry.get("folder") == str(folder)
            and not entry.get("undone", False)
        ),
        None,
    )

    if run is None:
        info_card(
            "There is no organization run to undo for this folder.",
            "Nothing to undo",
            "history is empty",
        )
        return 0

    moves = run.get("moves", [])

    print()
    phase_card(
        [
            f"{WHITE}{BOLD}{len(moves)} file(s){RESET}"
            f"{GRAY} from the run at "
            f"{WHITE}{run.get('time', 'unknown').replace('T', ' ')}"
            f"{RESET}{GRAY} will go back to their original locations.{RESET}",
            f"{GRAY}Empty category folders left behind will be tidied up.{RESET}",
            f"{GRAY}Files will not be deliberately deleted.{RESET}",
        ],
        "01",
        "◆ Undo last run",
        "restore original locations",
        T_PURPLE,
    )

    if not assume_yes:
        try:
            answer = input(
                f"\n  {fg(T_PURPLE)}{BOLD}❯{RESET} "
                f"{WHITE}Type YES to undo:{RESET} "
            ).strip()
        except EOFError:
            answer = ""

        if answer.upper() != "YES":
            info_card(
                "No files were moved.",
                "Cancelled",
                "no changes made",
                T_GRAY,
            )
            print()
            return 1

    restored = 0
    failed = 0
    problems = []

    for original, destination in moves:
        original = Path(original)
        destination = Path(destination)

        try:
            if not inside(folder, original.parent):
                raise PermissionError(
                    "Original location is outside the selected folder."
                )

            if not inside(folder, destination):
                raise PermissionError(
                    "Current file location is outside the selected folder."
                )

            if not destination.exists():
                raise FileNotFoundError(
                    "The organized file is no longer at its recorded location."
                )

            original.parent.mkdir(parents=True, exist_ok=True)

            # Restore to the original path when possible. If another
            # file now occupies that name, choose a numbered filename.
            if original.exists():
                restored_path = None

                for candidate in candidate_names(original):
                    if candidate.exists():
                        continue

                    try:
                        shutil.move(
                            str(destination),
                            str(candidate),
                        )
                        restored_path = candidate
                        break
                    except FileExistsError:
                        continue

                if restored_path is None:
                    raise OSError(
                        "Could not find an available restoration filename."
                    )
            else:
                shutil.move(
                    str(destination),
                    str(original),
                )
                restored_path = original

            restored += 1

            logging.info(
                "Restored %s -> %s",
                destination,
                restored_path,
            )

        except (OSError, shutil.Error) as error:
            failed += 1
            problems.append((destination.name, str(error)))

            logging.error(
                "Undo failed for %s: %s",
                destination,
                error,
            )

    # Remove only empty folders created by organization.
    tidied = 0

    for _, destination in moves:
        parent = Path(destination).parent

        while parent != folder and inside(folder, parent):
            try:
                os.rmdir(parent)
                tidied += 1
            except OSError:
                break

            parent = parent.parent

    if failed == 0:
        run["undone"] = True
        save_history(history)

    print()
    stat_tiles([
        ("Restored", restored, T_GREEN),
        ("Failed", failed, T_RED if failed else None),
        ("Folders tidied", tidied, T_TEAL if tidied else None),
    ])

    if problems:
        print()
        phase_card(
            [
                f"{RED}✖{RESET} "
                f"{WHITE}{pad(truncate(name, 28), 29)}{RESET}"
                f"{GRAY}{truncate(reason, WIDTH - 42)}{RESET}"
                for name, reason in problems
            ],
            "!!",
            "Needs attention",
            f"{len(problems)} file(s) not restored",
            T_RED,
        )

    print()
    return 1 if failed else 0


# ==========================================================
# ORGANIZE FILES
# ==========================================================

def organize(folder, settings, dry_run=False, assume_yes=False):
    started = time.perf_counter()

    folder = Path(folder).resolve()
    mode = settings["mode"]
    recursive = settings["recursive"]

    try:
        items = scan_files(folder, recursive)
    except (PermissionError, OSError) as error:
        error_card(
            f"Cannot read selected folder: "
            f"{truncate(str(folder), WIDTH - 32)}"
        )
        logging.exception("Cannot scan %s: %s", folder, error)
        return 2

    # Skip files already in their intended destination directory.
    items = [
        item
        for item in items
        if item.path.parent.resolve()
        != target_folder_for(item, folder, mode).resolve()
    ]

    if not items:
        info_card(
            "No files to organize in this folder.",
            "Nothing to do",
            "folder is already clean",
        )
        print()
        return 0

    counts = {}

    for item in items:
        category = get_category(item.name)
        counts[category] = counts.get(category, 0) + 1

    total_size = sum(item.size for item in items)

    # 01: Selected folder
    print()
    phase_card(
        [
            f"{GRAY}{pad('Directory', 13)}{RESET}"
            f"{WHITE}{truncate(str(folder), WIDTH - 22)}{RESET}",
            f"{GRAY}{pad('Files found', 13)}{RESET}"
            f"{fg(T_GOLD)}{BOLD}{len(items)}{RESET}"
            f"{GRAY}  ({fmt_size(total_size)}){RESET}",
            f"{GRAY}{pad('Sort mode', 13)}{RESET}"
            f"{WHITE}{MODES[mode][0]}{RESET}",
            f"{GRAY}{pad('Subfolders', 13)}{RESET}"
            f"{WHITE}{'included' if recursive else 'not scanned'}{RESET}",
        ],
        "01",
        "◆ Target",
        "scanned with os.scandir",
        T_BLUE,
    )

    # 02: Plan
    print()
    phase_card(
        category_rows(counts, len(items)),
        "02",
        "◆ Organization plan",
        "files per category",
        T_ORANGE,
    )

    # Preview mode makes no intentional file moves.
    if dry_run:
        print()
        phase_card(
            [
                f"{fg(T_YELLOW)}{BOLD}Preview complete.{RESET}",
                f"{GRAY}No files were moved.{RESET}",
                f"{GRAY}The selected folder remains unchanged by the organizer.{RESET}",
            ],
            "03",
            "◆ Dry run",
            "preview only",
            T_YELLOW,
        )
        print()
        return 0

    # Confirmation
    if not assume_yes:
        print()
        phase_card(
            [
                f"{WHITE}{BOLD}{len(items)} file(s){RESET}"
                f"{GRAY} will be moved inside "
                f"{WHITE}{truncate(folder.name, 30)}{RESET}{GRAY}.{RESET}",
                f"{GRAY}Existing files are not intentionally overwritten.{RESET}",
                f"{GRAY}You can use Undo last run to restore files.{RESET}",
            ],
            "03",
            "◆ Confirmation",
            "safety check",
            T_YELLOW,
        )

        try:
            answer = input(
                f"\n  {fg(T_YELLOW)}{BOLD}❯{RESET} "
                f"{WHITE}Type YES to continue:{RESET} "
            ).strip()
        except EOFError:
            answer = ""

        if answer.upper() != "YES":
            info_card(
                "No files were moved.",
                "Cancelled",
                "no changes made",
                T_GRAY,
            )
            print()
            logging.info(
                "User cancelled organization of %s",
                folder,
            )
            return 1

    # Processing
    moved = 0
    failed = 0
    renamed = 0
    moved_size = 0

    per_category = {}
    errors = []
    moves = []

    total = len(items)
    name_width = WIDTH - 46

    print()
    phase_card(
        [
            f"{GRAY}Moving {WHITE}{BOLD}{total}{RESET}"
            f"{GRAY} file(s) with shutil.move…{RESET}"
        ],
        "04",
        "◆ Processing",
        "live progress",
        T_PURPLE,
    )
    print()

    for index, item in enumerate(items, start=1):
        category = get_category(item.name)
        tone = CATEGORY_THEME[category]

        progress = (
            f"{bar(index, total, 14, T_PURPLE)} "
            f"{DARK}{index / total * 100:>3.0f}%{RESET}"
        )

        try:
            destination = safe_move(
                item.path,
                target_folder_for(item, folder, mode),
                folder,
            )

            moved += 1
            moved_size += item.size

            per_category[category] = (
                per_category.get(category, 0) + 1
            )

            moves.append([
                str(item.path),
                str(destination),
            ])

            was_renamed = destination.name != item.name

            if was_renamed:
                renamed += 1

            where = destination.parent.relative_to(folder)

            note = (
                f" {YELLOW}(→ "
                f"{truncate(destination.name, 22)}){RESET}"
                if was_renamed
                else ""
            )

            print(
                f"  {GREEN}✔{RESET} {progress}  "
                f"{WHITE}{pad(truncate(item.name, name_width), name_width)}"
                f"{RESET}{GRAY}→{RESET} "
                f"{fg(tone)}"
                f"{truncate(str(where).replace(os.sep, '/'), 18)}/"
                f"{RESET}{note}"
            )

            logging.info(
                "Moved %s -> %s",
                item.path,
                destination,
            )

        except PermissionError as error:
            failed += 1

            errors.append((
                item.name,
                "permission denied (file open or protected)",
            ))

            print(
                f"  {RED}✖ Permission denied: "
                f"{truncate(item.name, name_width)}{RESET}"
            )

            logging.error(
                "Permission denied: %s (%s)",
                item.path,
                error,
            )

        except (shutil.Error, OSError) as error:
            failed += 1
            errors.append((item.name, str(error)))

            print(
                f"  {RED}✖ Failed: "
                f"{truncate(item.name, name_width)} "
                f"— {error}{RESET}"
            )

            logging.error(
                "Move failed: %s (%s)",
                item.path,
                error,
            )

    if moves:
        record_run(folder, mode, moves)

    elapsed = time.perf_counter() - started
    success_rate = moved / max(total, 1) * 100

    # Statistics
    print()
    stat_tiles([
        ("Scanned", total, T_BLUE),
        ("Relocated", moved, T_GREEN),
        ("Renamed", renamed, T_YELLOW if renamed else None),
        ("Failed", failed, T_RED if failed else None),
    ])

    # Execution summary
    print()
    phase_card(
        [
            f"{GRAY}{pad('Total files relocated', 24)}{RESET}"
            f"{GREEN}{BOLD}{moved:>5}{RESET}",
            f"{GRAY}{pad('Files scanned', 24)}{RESET}"
            f"{WHITE}{total:>5}{RESET}",
            f"{GRAY}{pad('Renamed (collisions)', 24)}{RESET}"
            f"{YELLOW}{renamed:>5}{RESET}",
            f"{GRAY}{pad('Failed', 24)}{RESET}"
            f"{RED}{failed:>5}{RESET}",
            "",
            f"{GRAY}{pad('Data organized', 24)}{RESET}"
            f"{WHITE}{fmt_size(moved_size):>9}{RESET}",
            f"{GRAY}{pad('Success rate', 24)}{RESET}"
            f"{bar(moved, total, 22, T_GREEN)} "
            f"{WHITE}{success_rate:>5.1f}%{RESET}",
            f"{GRAY}{pad('Elapsed', 24)}{RESET}"
            f"{WHITE}{elapsed:>5.2f}s{RESET}",
        ],
        "05",
        "✓ Execution summary",
        "total files relocated",
        T_GREEN,
    )

    # Category summary
    if per_category:
        print()
        phase_card(
            category_rows(per_category, moved),
            "06",
            "◆ By category",
            "where files went",
            T_TEAL,
        )

    # Errors
    if errors:
        print()
        phase_card(
            [
                f"{RED}✖{RESET} "
                f"{WHITE}{pad(truncate(name, 28), 29)}{RESET}"
                f"{GRAY}{truncate(reason, WIDTH - 42)}{RESET}"
                for name, reason in errors
            ],
            "!!",
            "Needs attention",
            f"{len(errors)} file(s) not moved",
            T_RED,
        )

    # Session
    status = (
        f"{YELLOW}Completed with errors{RESET}"
        if failed
        else f"{GREEN}{BOLD}All files organized{RESET}"
    )

    print()
    phase_card(
        [
            f"{GRAY}{pad('Status', 11)}{RESET}{status}",
            f"{GRAY}{pad('Log file', 11)}{RESET}"
            f"{WHITE}{truncate(str(LOG_FILE), WIDTH - 22)}{RESET}",
            f"{GRAY}{pad('Finished', 11)}{RESET}"
            f"{WHITE}{datetime.now():%Y-%m-%d %H:%M:%S}{RESET}",
        ],
        "07",
        "◆ Session",
        "audit trail",
        T_GRAY,
    )
    print()

    logging.info(
        "Finished | folder=%s | mode=%s | scanned=%d | "
        "moved=%d | renamed=%d | failed=%d",
        folder,
        mode,
        total,
        moved,
        renamed,
        failed,
    )

    return 1 if failed else 0


# ==========================================================
# INTERACTIVE INTERFACE
# ==========================================================

def ask(label, theme=T_AMBER):
    return input(
        f"\n  {fg(theme)}{BOLD}❯{RESET} "
        f"{WHITE}{label}{RESET} "
    ).strip()


def pause():
    input(f"\n  {DARK}Press Enter to continue…{RESET}")


def clear_screen():
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


# ==========================================================
# FOLDER SELECTION (NAME OR PATH)
# ==========================================================

# Folders never searched when looking for a folder by name.
_SEARCH_SKIP = {
    "appdata", "node_modules", "windows", "program files",
    "program files (x86)", "programdata", "$recycle.bin",
    "system volume information", "library", "proc", "sys", "dev",
    "snap", "__pycache__",
}


def looks_like_path(raw):
    """True when the input is a path rather than a bare folder name."""
    return any(ch in raw for ch in ("/", "\\", ":")) or raw.startswith(("~", "."))


def _search_roots():
    """Places searched for a folder name, with the depth to search in each."""
    roots = [(Path.home(), 4)]

    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            try:
                if drive.exists():
                    roots.append((drive, 4))
            except OSError:
                pass
    else:
        for mount in ("/mnt", "/media", "/Volumes"):
            if Path(mount).is_dir():
                roots.append((Path(mount), 4))

    roots.append((Path.cwd(), 3))
    roots.append((BASE_DIR, 3))
    return roots


def find_folders_by_name(name, time_limit=10.0):
    """
    Search for folders called `name` (case-insensitive).

    Returns (exact_matches, partial_matches). Hidden and system folders
    are skipped, and the search stops after `time_limit` seconds.
    """
    target = name.lower()
    exact, partial = [], []
    seen = set()
    deadline = time.monotonic() + time_limit

    def walk(folder, depth):
        if time.monotonic() > deadline:
            return

        try:
            with os.scandir(folder) as entries:
                children = list(entries)
        except OSError:
            return

        for entry in children:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue

            low = entry.name.lower()

            if low.startswith(".") or low in _SEARCH_SKIP:
                continue

            key = os.path.normcase(os.path.abspath(entry.path))

            if key in seen:
                continue

            seen.add(key)

            if low == target:
                exact.append(Path(entry.path))
            elif target in low:
                partial.append(Path(entry.path))

            if depth > 1:
                walk(entry.path, depth - 1)

    for root, depth in _search_roots():
        walk(root, depth)

    return exact, partial


def _usable(paths, limit=20):
    """Keep only folders that pass validation; shortest paths first."""
    usable = []

    for path in sorted(paths, key=lambda p: (len(p.parts), str(p).lower())):
        folder, _ = validate_folder(str(path))

        if folder is not None and folder not in usable:
            usable.append(folder)

        if len(usable) >= limit:
            break

    return usable


def _wrap_text(text, width):
    """Split text into chunks of at most `width` characters."""
    text = str(text)
    return [text[i:i + width] for i in range(0, len(text), width)] or [""]


def choose_match(matches, similar=False):
    """
    Show numbered matches with their FULL paths.

    Long paths are wrapped over several lines instead of being cut,
    so folders with the same name can be told apart.
    Returns the chosen Path, or None to go back.
    """
    title = "Similar folders found" if similar else "Multiple matching folders found"
    last = len(matches)
    num_w = len(str(last))

    # Visible width of the "[ n ]  " prefix, used to indent wrapped lines.
    prefix_w = num_w + 4
    room = max(20, WIDTH - 5 - prefix_w - 1)

    lines = []

    for index, path in enumerate(matches, start=1):
        chunks = _wrap_text(path, room)

        lines.append(
            f"{badge(pad(str(index), num_w), T_BLUE)}  "
            f"{WHITE}{chunks[0]}{RESET}"
        )

        for chunk in chunks[1:]:
            lines.append(f"{' ' * prefix_w}{WHITE}{chunk}{RESET}")

        lines.append("")  # blank line between entries

    lines.append(f"{DARK}Press Enter to search again.{RESET}")

    print()
    phase_card(lines, "00", f"◆ {title}", f"{last} result(s)", T_BLUE)

    while True:
        choice = ask(f"Choose the folder number (1–{last}):", T_BLUE)

        if choice.lower() in ("", "b", "back", "q"):
            return None

        if choice.isdigit() and 1 <= int(choice) <= last:
            return matches[int(choice) - 1]

        print(
            f"\n  {badge('INVALID', T_RED)} "
            f"{RED}Enter a number from 1 to {last}.{RESET}"
        )


def resolve_folder(raw, allow_prompt=True):
    """
    Turn what the user typed into one exact folder.

    A path is validated as-is. A bare name is searched for; if several
    folders match, the user picks one by number.

    Returns (folder, problem):
        (Path, None)  - folder selected
        (None, text)  - invalid input
        (None, None)  - user went back to search again
    """
    raw = raw.strip().strip('"').strip("'")

    if not raw:
        return None, "No folder name or path entered."

    if looks_like_path(raw):
        return validate_folder(raw)

    print(
        f"\n  {GRAY}Searching for folders named "
        f"{WHITE}{raw}{GRAY} …{RESET}"
    )

    exact, partial = find_folders_by_name(raw)
    matches = _usable(exact)
    similar = False

    if not matches:
        matches = _usable(partial)
        similar = bool(matches)

    if not matches:
        return None, f"No folder named '{raw}' was found."

    if len(matches) == 1 and not similar:
        return matches[0], None

    if not allow_prompt:
        listing = "; ".join(str(match) for match in matches[:5])
        return None, (
            f"'{raw}' matches several folders ({listing}). "
            "Use the full path instead."
        )

    return choose_match(matches, similar), None


def ask_folder():
    """
    Ask for a folder name or path.

    A bare name is searched for and, when several folders match, the user
    chooses one by number. The exact chosen path is then shown.
    """
    print()

    phase_card(
        [
            f"{WHITE}{BOLD}Which folder would you like to organize?{RESET}",
            f"{GRAY}Enter a folder name or folder path.{RESET}",
            f"{GRAY}Examples: Projects   or   C:\\Users\\YourName\\Downloads{RESET}",
            f"{DARK}Only files inside the selected folder will be considered.{RESET}",
            f"{DARK}Type 'q' to quit.{RESET}",
        ],
        "00",
        "◆ Select folder",
        "step 1",
        T_BLUE,
    )

    while True:
        raw = ask("Enter folder name or folder path:", T_BLUE)

        if raw.lower() in ("q", "quit", "exit"):
            return None

        folder, problem = resolve_folder(raw)

        if folder is not None:
            print()

            phase_card(
                [
                    f"{GREEN}{BOLD}Folder selected successfully.{RESET}",
                    f"{GRAY}{pad('Selected folder', 16)}{RESET}"
                    f"{WHITE}{str(folder)}{RESET}",
                    f"{GRAY}This exact folder will be used for the operation.{RESET}",
                ],
                "✓",
                "◆ Folder confirmed",
                "path validated",
                T_GREEN,
            )

            return folder

        if problem is None:
            continue  # user chose to search again

        print(
            f"\n  {badge('INVALID', T_RED)} "
            f"{RED}{problem}{RESET}"
        )
        print(
            f"  {GRAY}Please enter a valid folder name or path and try again.{RESET}"
        )


def settings_card(folder, settings):
    mode_name, mode_hint = MODES[settings["mode"]]

    on = (
        f"{GREEN}{BOLD}ON {RESET}"
        f"{GRAY}(files inside subfolders are included){RESET}"
    )

    off = (
        f"{GRAY}OFF "
        f"(only files directly inside the folder){RESET}"
    )

    print()
    phase_card(
        [
            f"{GRAY}{pad('Folder', 12)}{RESET}"
            f"{WHITE}{truncate(str(folder), WIDTH - 22)}{RESET}",
            f"{GRAY}{pad('Sort mode', 12)}{RESET}"
            f"{fg(T_GOLD)}{BOLD}{mode_name}{RESET}"
            f"{DARK}  {mode_hint}{RESET}",
            f"{GRAY}{pad('Subfolders', 12)}{RESET}"
            f"{on if settings['recursive'] else off}",
        ],
        "01",
        "◆ Current settings",
        "what will be used",
        T_TEAL,
    )


def menu_card():
    items = [
        ("1", "Preview", "see the plan, change nothing", T_YELLOW),
        ("2", "Organize now", "move the files", T_GREEN),
        ("3", "Undo last run", "put moved files back", T_PURPLE),
        ("4", "Sort mode", "type / type + month / month", T_ORANGE),
        ("5", "Subfolders", "include files in subfolders: on/off", T_TEAL),
        ("6", "Change folder", "pick another folder", T_BLUE),
        ("7", "Exit", "close the program", T_GRAY),
    ]

    lines = [
        f"{badge(key, tone)}  "
        f"{WHITE}{BOLD}{pad(name, 15)}{RESET}"
        f"{GRAY}{hint}{RESET}"
        for key, name, hint, tone in items
    ]

    print()
    phase_card(
        lines,
        "02",
        "◆ Main menu",
        "choose an action",
        T_AMBER,
    )


def choose_mode(settings):
    lines = []
    keys = list(MODES)

    for index, key in enumerate(keys, start=1):
        name, hint = MODES[key]

        current = (
            f" {GREEN}◄ current{RESET}"
            if key == settings["mode"]
            else ""
        )

        lines.append(
            f"{badge(str(index), T_ORANGE)}  "
            f"{WHITE}{BOLD}{pad(name, 19)}{RESET}"
            f"{GRAY}{hint}{RESET}{current}"
        )

    print()
    phase_card(
        lines,
        "04",
        "◆ Sort mode",
        "how files are grouped",
        T_ORANGE,
    )

    choice = ask("Choose 1-3 (Enter to keep):", T_ORANGE)

    if choice in ("1", "2", "3"):
        settings["mode"] = keys[int(choice) - 1]


def interactive():
    settings = {
        "mode": "type",
        "recursive": True,
    }

    show_banner("INTERACTIVE", T_BLUE)

    folder = ask_folder()

    if folder is None:
        goodbye()
        return 0

    while True:
        clear_screen()
        show_banner("INTERACTIVE", T_BLUE)

        settings_card(folder, settings)
        menu_card()

        choice = ask("Select an option [1-7]:")

        if choice == "1":
            organize(folder, settings, dry_run=True)
            pause()

        elif choice == "2":
            organize(folder, settings)
            pause()

        elif choice == "3":
            undo_last(folder)
            pause()

        elif choice == "4":
            choose_mode(settings)

        elif choice == "5":
            settings["recursive"] = not settings["recursive"]

        elif choice == "6":
            new_folder = ask_folder()

            if new_folder is not None:
                folder = new_folder

        elif choice in ("7", "q", "quit", "exit"):
            goodbye()
            return 0

        else:
            print(
                f"\n  {badge('INVALID', T_RED)} "
                f"{RED}Please choose a number from 1 to 7.{RESET}"
            )
            pause()


def goodbye():
    print()

    phase_card(
        [
            f"{fg(T_AMBER)}{BOLD}"
            f"Thank you for using the File Organizer!{RESET}",
            f"{GRAY}Stay organized. Stay productive.{RESET}",
        ],
        "--",
        "Goodbye",
        "see you soon",
        T_AMBER,
    )

    print()


# ==========================================================
# COMMAND-LINE ENTRY POINT
# ==========================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            f"{TITLE}. "
            "Run without arguments for the interactive menu."
        )
    )

    parser.add_argument(
        "folder",
        nargs="?",
        help="folder to organize (omit to be asked)",
    )

    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="preview only; change nothing",
    )

    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip the confirmation prompt",
    )

    parser.add_argument(
        "-m",
        "--mode",
        choices=list(MODES),
        default="type",
        help="type (default), type_date, or date",
    )

    parser.add_argument(
        "-r",
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="include files inside subfolders (default: on; "
             "use --no-recursive to turn off)",
    )

    parser.add_argument(
        "-u",
        "--undo",
        action="store_true",
        help="undo the last run for this folder",
    )

    args = parser.parse_args()

    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        encoding="utf-8",
    )

    try:
        # Interactive mode
        if args.folder is None:
            return interactive()

        # Command-line mode
        label = (
            "UNDO"
            if args.undo
            else ("DRY RUN" if args.dry_run else "LIVE")
        )

        theme = (
            T_PURPLE
            if args.undo
            else (T_YELLOW if args.dry_run else T_GREEN)
        )

        show_banner(label, theme)

        # A bare name is searched for; a path is validated as given.
        folder, problem = resolve_folder(
            args.folder,
            allow_prompt=sys.stdin.isatty(),
        )

        if folder is None and problem is None:
            problem = "Folder selection was cancelled."

        if folder is None:
            error_card(problem)
            print()
            return 2

        # Display the exact resolved folder path before execution.
        print()
        phase_card(
            [
                f"{GREEN}{BOLD}Selected folder validated.{RESET}",
                f"{GRAY}{pad('Full path', 12)}{RESET}"
                f"{WHITE}{str(folder)}{RESET}",
            ],
            "✓",
            "◆ Folder confirmed",
            "path validated",
            T_GREEN,
        )

        if args.undo:
            return undo_last(folder, assume_yes=args.yes)

        settings = {
            "mode": args.mode,
            "recursive": args.recursive,
        }

        return organize(
            folder,
            settings,
            dry_run=args.dry_run,
            assume_yes=args.yes,
        )

    except (KeyboardInterrupt, EOFError):
        print()

        info_card(
            "Stopped by user.",
            "Exit",
            "operation interrupted",
        )

        print()
        return 130

    except Exception:
        logging.exception("Unexpected error")

        error_card(
            "Unexpected error. See organizer.log for details."
        )

        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())