#!/usr/bin/env python3
"""
organizer.py - Automated File Organizer & Cleanup Utility.

Features:
    - Colorful terminal interface with cards and progress indicators.
    - Folder path validation and confirmation.
    - File categorization and sorting (3 modes: type, type_date, date).
    - Categories load from an optional categories.json (built-ins otherwise).
    - Preview (dry-run) mode that shows every destination and collision.
    - Recursive scanning (on by default) and empty-folder cleanup.
    - Safe filename collision handling (never overwrites).
    - Undo the last run (repeatable, survives Ctrl+C and partial failures).
    - Logging and error handling.

Usage:
    python organizer.py
    python organizer.py Projects
    python organizer.py "D:\\MyFiles" --yes
    python organizer.py "D:\\MyFiles" --dry-run
    python organizer.py "D:\\MyFiles" --mode type_date
    python organizer.py "D:\\MyFiles" --no-recursive
    python organizer.py "D:\\MyFiles" --undo
    python organizer.py "D:\\MyFiles" --categories my_categories.json

Requires Python 3.9+. Log and history are stored in ~/.organizer/
(override with the ORGANIZER_HOME environment variable).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
)

__version__ = "8.0"


# ==================================================================
# FILE LOGIC (no printing)
# ==================================================================

# Log and history live in a per-user folder (override with ORGANIZER_HOME).
APP_DIR = Path(os.environ.get("ORGANIZER_HOME") or Path.home() / ".organizer")
LOG_FILE = APP_DIR / "organizer.log"
HISTORY_FILE = APP_DIR / "history.json"
SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_CATEGORY = "Other"
CATEGORY_FILE_NAME = "categories.json"

# Built-in categories. Override them with a categories.json file
# (see load_category_file) without editing this script.
BUILTIN_CATEGORIES: Dict[str, List[str]] = {
    name: exts.split()
    for name, exts in {
        "Documents": (
            ".pdf .doc .docx .txt .rtf .odt .xls .xlsx .csv .ppt .pptx .md"
        ),
        "Images": ".jpg .jpeg .png .gif .bmp .svg .webp .ico .tiff .heic",
        "Videos": ".mp4 .mkv .mov .avi .wmv .flv .webm .mpeg .mpg",
        "Audio": ".mp3 .wav .aac .ogg .flac .m4a .wma",
        "Archives": ".zip .rar .7z .tar .gz .bz2 .xz",
        "Code": (
            ".py .js .jsx .ts .tsx .html .css .java .c .cpp .h .hpp .cs "
            ".php .sql .json .xml .yaml .yml .sh .bat .ps1"
        ),
    }.items()
}

# Active tables; filled by set_categories() (called below at import).
EXTENSION_MAP: Dict[str, str] = {}
CATEGORY_ORDER: List[str] = []

MODES: Dict[str, Tuple[str, str]] = {
    "type": ("By file type", "Documents/, Images/, Videos/ ..."),
    "type_date": (
        "File type + month",
        "Documents/2026-10/, Images/2026-09/ ...",
    ),
    "date": ("By month only", "2026-10/, 2026-09/ ..."),
}

SKIP_SUFFIXES = {".crdownload", ".part", ".partial", ".tmp", ".download"}
DATE_DIR_RE = re.compile(r"^\d{4}(-\d{2})?$")


class CategoryError(ValueError):
    """The category configuration is invalid."""


def set_categories(categories: Dict[str, List[str]]) -> None:
    """Make `categories` the active category tables."""
    global EXTENSION_MAP, CATEGORY_ORDER
    EXTENSION_MAP = {
        ext: name for name, exts in categories.items() for ext in exts
    }
    CATEGORY_ORDER = list(categories) + [DEFAULT_CATEGORY]


def parse_categories(data: Any) -> Dict[str, List[str]]:
    """
    Validate category data: {"Folder name": [".ext", ...], ...}.

    Extensions are lower-cased and a missing leading dot is added.
    Raises CategoryError with a readable message when invalid.
    """
    if not isinstance(data, dict) or not data:
        raise CategoryError(
            'must be a JSON object like {"Ebooks": [".epub", ".mobi"]}'
        )

    result: Dict[str, List[str]] = {}
    owner: Dict[str, str] = {}
    names_seen = set()

    for raw_name, raw_exts in data.items():
        name = raw_name.strip()
        if not name or name.startswith("."):
            raise CategoryError(f"invalid category name {raw_name!r}")
        if any(ch in name for ch in '\\/:*?"<>|'):
            raise CategoryError(
                f"category name {name!r} has characters not allowed in "
                "folder names"
            )
        if name.lower() == DEFAULT_CATEGORY.lower():
            raise CategoryError(
                f"'{DEFAULT_CATEGORY}' is reserved for unmatched files"
            )
        if DATE_DIR_RE.match(name):
            raise CategoryError(
                f"category name {name!r} looks like a date folder"
            )
        if name.lower() in names_seen:
            raise CategoryError(f"category {name!r} is listed twice")
        names_seen.add(name.lower())

        if not isinstance(raw_exts, list) or not all(
            isinstance(e, str) for e in raw_exts
        ):
            raise CategoryError(
                f"category {name!r} needs a list of extensions"
            )

        cleaned: List[str] = []
        for raw in raw_exts:
            ext = raw.strip().lower()
            if ext.strip(".") == "":
                raise CategoryError(f"empty extension in {name!r}")
            if not ext.startswith("."):
                ext = "." + ext
            if ext in owner and owner[ext] != name:
                raise CategoryError(
                    f"extension {ext} is in both {owner[ext]!r} and {name!r}"
                )
            owner[ext] = name
            if ext not in cleaned:
                cleaned.append(ext)
        result[name] = cleaned

    return result


def load_category_file(path: Path) -> Dict[str, List[str]]:
    """Read and validate a categories JSON file."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise CategoryError(f"cannot read {path}: {error.strerror}") from error
    except ValueError as error:
        raise CategoryError(f"{path} is not valid JSON ({error})") from error
    try:
        return parse_categories(data)
    except CategoryError as error:
        raise CategoryError(f"{path}: {error}") from error


def find_category_file(explicit: Optional[str] = None) -> Optional[Path]:
    """--categories path, else categories.json next to the script or in
    the app folder, else None (use built-in categories)."""
    if explicit:
        return Path(explicit).expanduser()
    for folder in (SCRIPT_DIR, APP_DIR):
        candidate = folder / CATEGORY_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


def configure_categories(explicit: Optional[str] = None) -> Optional[Path]:
    """
    Apply the categories file if there is one, else the built-ins.

    Returns the file used (or None). Raises CategoryError if a file is
    present but invalid; the built-in categories stay active in that case.
    """
    set_categories(BUILTIN_CATEGORIES)
    path = find_category_file(explicit)
    if path is None:
        return None
    set_categories(load_category_file(path))
    return path


set_categories(BUILTIN_CATEGORIES)

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


@dataclass(frozen=True)
class FileItem:
    """A regular file found by the scanner."""

    path: Path
    size: int
    mtime: float

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class PlannedMove:
    """One file and where it is going to be moved."""

    item: FileItem
    category: str
    target_dir: Path
    destination: Path

    @property
    def renamed(self) -> bool:
        return self.destination.name != self.item.name


@dataclass(frozen=True)
class MoveResult:
    """Outcome of attempting one planned move."""

    planned: PlannedMove
    destination: Optional[Path]
    error: Optional[str]

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def renamed(self) -> bool:
        return self.ok and self.destination.name != self.planned.item.name


# ----------------------------------------------------------------------
# Folder validation
# ----------------------------------------------------------------------


def validate_folder(raw: str) -> Tuple[Optional[Path], Optional[str]]:
    """Return (resolved_folder, None) or (None, error_message)."""
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return None, "No path entered."

    candidate = Path(raw).expanduser()

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

    if folder in (SCRIPT_DIR, APP_DIR.resolve()):
        return None, "That is the script's own folder. Pick another."
    if folder.parent == folder:
        return None, "A drive root cannot be organized."

    try:
        if folder == Path.home().resolve():
            return None, (
                "Your whole home folder is too broad. Pick a subfolder."
            )
    except (OSError, RuntimeError):
        pass

    lowered = str(folder).lower()
    if os.name == "nt":
        protected, sep = _PROTECTED_WIN, "\\"
    else:
        protected, sep = _PROTECTED_UNIX, "/"
    for prefix in protected:
        if lowered == prefix or lowered.startswith(prefix + sep):
            return None, "System folders are protected."

    return folder, None


# ----------------------------------------------------------------------
# Scanning and planning
# ----------------------------------------------------------------------


def get_category(name: str) -> str:
    return EXTENSION_MAP.get(Path(name).suffix.lower(), DEFAULT_CATEGORY)


def _is_organizer_dir(name: str) -> bool:
    return name in CATEGORY_ORDER or bool(DATE_DIR_RE.match(name))


def scan_files(root: Path, recursive: bool = False) -> List[FileItem]:
    """
    Scan regular files under root.

    Skipped: hidden files, symlinks, temporary downloads, the organizer's
    own log/history, and (in recursive mode) top-level folders named like
    a category (``Images``) or a date (``2026-10``), because those are
    where organized files live.
    """
    root = Path(root)
    protected = {LOG_FILE.resolve(), HISTORY_FILE.resolve()}
    items: List[FileItem] = []

    def walk(folder: str, top: bool) -> None:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue

                if is_dir:
                    if not recursive:
                        continue
                    if top and _is_organizer_dir(entry.name):
                        continue
                    try:
                        walk(entry.path, False)
                    except OSError as error:
                        logging.warning(
                            "Cannot scan %s: %s", entry.path, error
                        )
                    continue

                if not is_file:
                    continue
                if Path(entry.name).suffix.lower() in SKIP_SUFFIXES:
                    continue
                try:
                    resolved = Path(entry.path).resolve()
                    stat = entry.stat(follow_symlinks=False)
                except (OSError, RuntimeError):
                    continue
                if resolved in protected:
                    continue
                items.append(
                    FileItem(Path(entry.path), stat.st_size, stat.st_mtime)
                )

    walk(str(root), True)
    return sorted(
        items,
        key=lambda i: (str(i.path.parent).lower(), i.name.lower()),
    )


def target_folder_for(item: FileItem, root: Path, mode: str) -> Path:
    category = get_category(item.name)
    month = datetime.fromtimestamp(item.mtime).strftime("%Y-%m")
    if mode == "type_date":
        return root / category / month
    if mode == "date":
        return root / month
    return root / category


def candidate_names(destination: Path) -> Iterator[Path]:
    """Yield the path itself, then name_1, name_2, ... forever."""
    yield destination
    counter = 1
    while True:
        yield destination.with_name(
            f"{destination.stem}_{counter}{destination.suffix}"
        )
        counter += 1


def plan_moves(
    items: Iterable[FileItem], root: Path, mode: str
) -> List[PlannedMove]:
    """
    Decide where every file goes, without touching the disk.

    Files already in their target folder are left out. Name collisions
    (on disk or between planned files) get numbered names, so a dry run
    shows exactly what a real run would do.
    """
    root = Path(root)
    reserved = set()
    plan: List[PlannedMove] = []

    for item in items:
        target_dir = target_folder_for(item, root, mode)
        if item.path.parent == target_dir:
            continue
        for destination in candidate_names(target_dir / item.name):
            if destination not in reserved and not destination.exists():
                break
        reserved.add(destination)
        plan.append(
            PlannedMove(item, get_category(item.name), target_dir, destination)
        )
    return plan


# ----------------------------------------------------------------------
# Moving
# ----------------------------------------------------------------------


def inside(parent: Path, child: Path) -> bool:
    """True when child resolves to parent or one of its descendants."""
    try:
        parent = Path(parent).resolve()
        child = Path(child).resolve()
    except (OSError, RuntimeError):
        return False
    return child == parent or parent in child.parents


def safe_move(source: Path, target_folder: Path, root: Path) -> Path:
    """Move source into target_folder (inside root) without overwriting."""
    source = Path(source)
    target_folder = Path(target_folder)

    if not inside(root, target_folder):
        raise PermissionError(
            f"Refusing to move outside the chosen folder: {target_folder}"
        )

    target_folder.mkdir(parents=True, exist_ok=True)

    for destination in candidate_names(target_folder / source.name):
        if destination.exists():
            continue
        try:
            shutil.move(str(source), str(destination))
        except FileExistsError:
            continue
        return destination

    raise OSError("Could not find an available destination filename.")


def execute_plan(
    plan: List[PlannedMove],
    root: Path,
    moves: List[List[str]],
    on_result: Optional[Callable[[int, int, MoveResult], None]] = None,
) -> List[MoveResult]:
    """
    Carry out the plan.

    Every successful move is appended to ``moves`` immediately, so if the
    run is interrupted (Ctrl+C) the caller still knows what was moved and
    can save it to the undo history.
    """
    results: List[MoveResult] = []
    total = len(plan)

    for index, planned in enumerate(plan, start=1):
        try:
            destination = safe_move(
                planned.item.path, planned.target_dir, root
            )
        except PermissionError as error:
            logging.error(
                "Permission denied: %s (%s)", planned.item.path, error
            )
            result = MoveResult(
                planned, None, "permission denied (file open or protected)"
            )
        except OSError as error:
            logging.error("Move failed: %s (%s)", planned.item.path, error)
            result = MoveResult(planned, None, str(error))
        else:
            moves.append([str(planned.item.path), str(destination)])
            logging.info("Moved %s -> %s", planned.item.path, destination)
            result = MoveResult(planned, destination, None)

        results.append(result)
        if on_result is not None:
            on_result(index, total, result)

    return results


def remove_empty_dirs(dirs: Iterable[Path], root: Path) -> int:
    """Remove empty folders (and empty parents) below root. Returns count."""
    removed = 0
    root = Path(root).resolve()
    for start in set(dirs):
        parent = Path(start)
        while parent.resolve() != root and inside(root, parent):
            try:
                os.rmdir(parent)
            except OSError:
                break
            removed += 1
            parent = parent.parent
    return removed


# ==================================================================
# HISTORY AND UNDO
# ==================================================================

MAX_RUNS = 20


def _history_path(path: Optional[Path]) -> Path:
    return Path(path) if path else HISTORY_FILE


def load_history(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return saved runs; a missing or corrupt file gives an empty list."""
    try:
        data = json.loads(_history_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def save_history(
    history: List[Dict[str, Any]], path: Optional[Path] = None
) -> bool:
    """Write history atomically. Returns False if it could not be saved."""
    target = _history_path(path)
    temp = target.with_suffix(".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(history[-MAX_RUNS:], indent=1), encoding="utf-8"
        )
        os.replace(temp, target)
        return True
    except OSError:
        logging.exception("Could not write history file")
        return False


def record_run(
    folder: Path,
    mode: str,
    moves: List[List[str]],
    path: Optional[Path] = None,
) -> None:
    history = load_history(path)
    history.append(
        {
            "time": datetime.now().isoformat(timespec="seconds"),
            "folder": str(Path(folder).resolve()),
            "mode": mode,
            "moves": moves,
            "done": [],
            "undone": False,
        }
    )
    save_history(history, path)


def find_last_run(
    history: List[Dict[str, Any]], folder: Path
) -> Optional[Dict[str, Any]]:
    """Most recent run for this folder that has not been fully undone."""
    key = str(Path(folder).resolve())
    for entry in reversed(history):
        if entry.get("folder") == key and not entry.get("undone", False):
            return entry
    return None


def valid_moves(run: Dict[str, Any]) -> List[Tuple[Path, Path]]:
    """Moves from a run, ignoring malformed entries."""
    result = []
    for move in run.get("moves", []):
        if (
            isinstance(move, (list, tuple))
            and len(move) == 2
            and all(isinstance(p, str) for p in move)
        ):
            result.append((Path(move[0]), Path(move[1])))
    return result


@dataclass
class UndoResult:
    restored: int = 0
    already_done: int = 0
    failed: int = 0
    tidied: int = 0
    problems: List[Tuple[str, str]] = field(default_factory=list)


def _restore(destination: Path, original: Path) -> Path:
    """Move destination back to original, or to a numbered name."""
    original.parent.mkdir(parents=True, exist_ok=True)
    for candidate in candidate_names(original):
        if candidate.exists():
            continue
        try:
            shutil.move(str(destination), str(candidate))
        except FileExistsError:
            continue
        return candidate
    raise OSError("Could not find an available restoration filename.")


def undo_run(folder: Path, run: Dict[str, Any]) -> UndoResult:
    """
    Restore the files of one run.

    Progress is stored in ``run["done"]`` so a retry after a partial
    failure skips files that are already back (idempotent). The caller
    must save the history afterwards.
    """
    folder = Path(folder).resolve()
    done = set(run.get("done", []))
    result = UndoResult()
    moves = valid_moves(run)

    for original, destination in moves:
        key = str(destination)
        if key in done:
            result.already_done += 1
            continue
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
            restored_path = _restore(destination, original)
        except OSError as error:
            result.failed += 1
            result.problems.append((destination.name, str(error)))
            logging.error("Undo failed for %s: %s", destination, error)
            continue

        done.add(key)
        result.restored += 1
        logging.info("Restored %s -> %s", destination, restored_path)

    result.tidied = remove_empty_dirs(
        [destination.parent for _, destination in moves], folder
    )
    run["done"] = sorted(done)
    if result.failed == 0:
        run["undone"] = True
    return result


# ==================================================================
# FOLDER SEARCH BY NAME
# ==================================================================

_SEARCH_SKIP = {
    "appdata",
    "node_modules",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
    "library",
    "proc",
    "sys",
    "dev",
    "snap",
    "__pycache__",
}


def looks_like_path(raw: str) -> bool:
    """True when the input is a path rather than a bare folder name."""
    return any(ch in raw for ch in ("/", "\\", ":")) or raw.startswith(
        ("~", ".")
    )


def search_roots() -> List[Tuple[Path, int]]:
    """Places to search, each with the depth to search to."""
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
    return roots


def find_folders_by_name(
    name: str,
    time_limit: float = 10.0,
    roots: Optional[Iterable[Tuple[Path, int]]] = None,
) -> Tuple[List[Path], List[Path]]:
    """Return (exact_matches, partial_matches), case-insensitive."""
    target = name.lower()
    exact: List[Path] = []
    partial: List[Path] = []
    seen = set()
    deadline = time.monotonic() + time_limit

    def walk(folder: str, depth: int) -> None:
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

    for root, depth in roots if roots is not None else search_roots():
        walk(str(root), depth)
    return exact, partial


def usable_folders(paths: Iterable[Path], limit: int = 20) -> List[Path]:
    """Keep only folders that pass validation; shortest paths first."""
    usable: List[Path] = []
    for path in sorted(paths, key=lambda p: (len(p.parts), str(p).lower())):
        folder, _ = validate_folder(str(path))
        if folder is not None and folder not in usable:
            usable.append(folder)
        if len(usable) >= limit:
            break
    return usable


# ==================================================================
# TERMINAL RENDERING
# ==================================================================

APP_TITLE = "Automated File Organizer & Cleanup Utility"

# Layout constants (no magic numbers in the code below).
NAME_COL = 28
LABEL_COL = 24
PROGRESS_BAR_WIDTH = 14
CATEGORY_BAR_WIDTH = 22
CARD_PADDING = 5

USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def setup_terminal() -> None:
    """Enable ANSI on Windows and UTF-8 output. Call once from main()."""
    if os.name == "nt":
        os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass


def fg(number: int) -> str:
    return f"\033[38;5;{number}m" if USE_COLOR else ""


def bg(number: int) -> str:
    return f"\033[48;5;{number}m" if USE_COLOR else ""


RESET = "\033[0m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""

T_AMBER, T_ORANGE, T_GOLD = 214, 208, 220
T_BLUE, T_PURPLE, T_TEAL = 75, 141, 79
T_GREEN, T_RED, T_YELLOW, T_GRAY = 114, 203, 221, 245
INK, BODY_BG, BAR_BG = 16, 236, 235

GREEN, RED, YELLOW = fg(T_GREEN), fg(T_RED), fg(T_YELLOW)
WHITE, GRAY, DARK = fg(255), fg(247), fg(241)

_BASE_THEME: Dict[str, int] = {
    "Documents": 111,
    "Images": 177,
    "Videos": 203,
    "Audio": 79,
    "Archives": 221,
    "Code": 114,
    DEFAULT_CATEGORY: 249,
}
_EXTRA_PALETTE = [75, 141, 208, 220, 166, 37, 175, 150]


def category_theme(name: str) -> int:
    """Colour for a category; custom categories cycle through a palette."""
    if name in _BASE_THEME:
        return _BASE_THEME[name]
    try:
        index = CATEGORY_ORDER.index(name)
    except ValueError:
        index = 0
    return _EXTRA_PALETTE[index % len(_EXTRA_PALETTE)]


WIDTH = max(64, min(shutil.get_terminal_size((80, 24)).columns - 2, 84))


# ----------------------------------------------------------------------
# Text helpers
# ----------------------------------------------------------------------


def visible_len(text: object) -> int:
    return len(ANSI_RE.sub("", str(text)))


def pad(text: object, width: int) -> str:
    return str(text) + " " * max(0, width - visible_len(text))


def center(text: str, width: int) -> str:
    spaces = max(0, width - visible_len(text))
    left = spaces // 2
    return " " * left + text + " " * (spaces - left)


def truncate(text: object, width: int) -> str:
    text = str(text)
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def wrap_text(text: object, width: int) -> List[str]:
    text = str(text)
    return [text[i : i + width] for i in range(0, len(text), width)] or [""]


def fmt_size(number: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            return (
                f"{number:.0f} {unit}"
                if unit == "B"
                else f"{number:.1f} {unit}"
            )
        number /= 1024
    return ""


def keep_bg(text: str, background: str) -> str:
    return text.replace(RESET, RESET + background) if USE_COLOR else text


def bar(
    value: float, total: float, width: int = 22, color_n: int = T_AMBER
) -> str:
    filled = round(value / max(total, 1) * width)
    return (
        f"{fg(color_n)}{'█' * filled}{RESET}"
        f"{fg(239)}{'░' * (width - filled)}{RESET}"
    )


def badge(text: str, color_n: int) -> str:
    if USE_COLOR:
        return f"{bg(color_n)}{fg(INK)}{BOLD} {text} {RESET}"
    return f"[{text}]"


# ----------------------------------------------------------------------
# Building blocks
# ----------------------------------------------------------------------


def fill_row(
    text: str, bg_n: int, align: str = "left", fg_n: Optional[int] = None
) -> None:
    background = bg(bg_n)
    ink = fg(fg_n) if fg_n is not None else ""
    body = keep_bg(text, background + ink)
    body = center(body, WIDTH) if align == "center" else pad(body, WIDTH)
    print(f" {background}{ink}{body}{RESET}")


def phase_card(
    lines: Iterable[str], num: str, title: str, caption: str, theme: int
) -> None:
    if USE_COLOR:
        left_a = f"  {num}  "
        left_b = f"  {title.upper()}  "
        room = WIDTH - len(left_a) - len(left_b)
        cap = f"{caption}  " if caption and len(caption) + 2 < room else ""
        gap = " " * max(0, room - len(cap))
        print(
            f" {bg(BAR_BG)}{fg(theme)}{BOLD}{left_a}{RESET}"
            f"{bg(theme)}{fg(INK)}{BOLD}{left_b}{gap}{RESET}"
            f"{bg(theme)}{fg(52)}{cap}{RESET}"
        )
    else:
        print(
            f" [{num}] {title.upper()}" + (f"  - {caption}" if caption else "")
        )
        print(" " + "─" * (WIDTH - 1))

    background = bg(BODY_BG)
    accent = f"{background}{fg(theme)}▌{RESET}{background}"
    for text in [""] + list(lines) + [""]:
        row = pad(keep_bg(str(text), background), WIDTH - CARD_PADDING)
        print(f" {accent}  {row}  {RESET}")


def stat_tiles(items: Sequence[Tuple[str, object, Optional[int]]]) -> None:
    count = len(items)
    base = (WIDTH - (count - 1)) // count
    widths = [base] * count
    widths[-1] += WIDTH - (base * count + count - 1)
    rows = ["", "", "", ""]

    for index, ((label, value, theme), width) in enumerate(zip(items, widths)):
        active = theme is not None
        background = bg(theme if active else 238)
        ink = fg(INK if active else 250)
        gap = " " if index < count - 1 else ""
        cells = [
            "",
            f"{BOLD}{label.upper()}{RESET}{background}{ink}",
            f"{BOLD}{value}{RESET}{background}{ink}",
            "",
        ]
        for row_index, cell in enumerate(cells):
            rows[row_index] += (
                f"{background}{ink}{center(cell, width)}{RESET}{gap}"
            )
    for row in rows:
        print(" " + row)


def category_rows(counts: Dict[str, int], total: int) -> List[str]:
    rows = []
    for category in CATEGORY_ORDER:
        if category not in counts:
            continue
        number = counts[category]
        tone = category_theme(category)
        rows.append(
            f"{fg(tone)}●{RESET} {WHITE}{pad(category, 11)}{RESET}"
            f"{bar(number, total, CATEGORY_BAR_WIDTH, tone)} "
            f"{fg(T_GOLD)}{BOLD}{number:>4}{RESET} {GRAY}file(s){RESET} "
            f"{DARK}{number / max(total, 1) * 100:>5.1f}%{RESET}"
        )
    return rows


def error_table(rows: Iterable[Tuple[str, str]]) -> List[str]:
    """Lines for a card listing (file name, reason) pairs."""
    return [
        f"{RED}✖{RESET} {WHITE}{pad(truncate(name, NAME_COL), NAME_COL + 1)}"
        f"{RESET}{GRAY}{truncate(reason, WIDTH - 42)}{RESET}"
        for name, reason in rows
    ]


def show_banner(label: str, theme: int) -> None:
    print()
    fill_row("", T_AMBER)
    fill_row(f"{BOLD}{APP_TITLE}{RESET}", T_AMBER, "center", INK)
    fill_row("━" * 28, T_AMBER, "center", 94)
    fill_row(
        "Sorts any folder into smart category folders - safely",
        T_AMBER,
        "center",
        94,
    )
    fill_row("", T_AMBER)

    if USE_COLOR:
        shades = [222, 220, 214, 208, 202, 166]
        seg = WIDTH // len(shades)
        strip = ""
        for index, shade in enumerate(shades):
            width = (
                seg
                if index < len(shades) - 1
                else WIDTH - seg * (len(shades) - 1)
            )
            strip += f"{bg(shade)}{' ' * width}"
        print(f" {strip}{RESET}")
    else:
        print(" " + "━" * WIDTH)

    info = (
        f"{fg(T_AMBER)}{BOLD}v{__version__}{RESET}{fg(247)}   │   "
        f"{WHITE}{datetime.now():%Y-%m-%d  %H:%M}{RESET}{fg(247)}   │   "
        f"{badge(label, theme)}"
    )
    fill_row(info, BAR_BG, "center")


def error_card(message: str) -> None:
    print()
    phase_card(
        [f"{RED}{message}{RESET}"], "!!", "Error", "action required", T_RED
    )


def info_card(
    message: str,
    title: str = "Notice",
    caption: str = "",
    theme: int = T_YELLOW,
) -> None:
    print()
    phase_card([f"{fg(theme)}{message}{RESET}"], "--", title, caption, theme)


def invalid(message: str) -> None:
    print(f"\n  {badge('INVALID', T_RED)} {RED}{message}{RESET}")


# ==================================================================
# COMMAND-LINE AND INTERACTIVE INTERFACE
# ==================================================================

DRY_RUN_PREVIEW_LIMIT = 25
CARD_PAD = CARD_PADDING
Settings = Dict[str, object]


def setup_logging() -> None:
    """Log to the per-user log file; fall back quietly if not writable."""
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(LOG_FILE),
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
            encoding="utf-8",
        )
    except OSError:
        logging.basicConfig(level=logging.WARNING)


def confirm(prompt: str, theme: int) -> bool:
    try:
        answer = input(
            f"\n  {fg(theme)}{BOLD}❯{RESET} {WHITE}{prompt}{RESET} "
        ).strip()
    except EOFError:
        answer = ""
    return answer.upper() == "YES"


# ----------------------------------------------------------------------
# Organize
# ----------------------------------------------------------------------


def show_dry_run(plan: List[PlannedMove], folder: Path) -> None:
    """List each file's destination and flag collision renames."""
    lines = []
    for planned in plan[:DRY_RUN_PREVIEW_LIMIT]:
        where = str(planned.destination.parent.relative_to(folder))
        where = where.replace("\\", "/")
        note = (
            f" {YELLOW}(renamed → {truncate(planned.destination.name, 22)})"
            f"{RESET}"
            if planned.renamed
            else ""
        )
        lines.append(
            f"{WHITE}{pad(truncate(planned.item.name, NAME_COL), NAME_COL + 1)}"
            f"{RESET}{GRAY}→ {where}/{RESET}{note}"
        )
    hidden = len(plan) - DRY_RUN_PREVIEW_LIMIT
    if hidden > 0:
        lines.append(f"{DARK}… and {hidden} more file(s){RESET}")
    collisions = sum(1 for p in plan if p.renamed)
    lines += [
        "",
        f"{fg(T_YELLOW)}{BOLD}Preview complete.{RESET} "
        f"{GRAY}No files were moved. "
        f"{collisions} name collision(s) would be renamed.{RESET}",
    ]
    print()
    phase_card(lines, "03", "◆ Dry run", "preview only", T_YELLOW)
    print()


def print_progress(
    index: int, total: int, result: MoveResult, folder: Path
) -> None:
    planned = result.planned
    name_width = WIDTH - 46
    progress = (
        f"{bar(index, total, PROGRESS_BAR_WIDTH, T_PURPLE)} "
        f"{DARK}{index / total * 100:>3.0f}%{RESET}"
    )
    name = pad(truncate(planned.item.name, name_width), name_width)
    if not result.ok:
        print(
            f"  {RED}✖ Failed: {truncate(planned.item.name, name_width)}"
            f" — {result.error}{RESET}"
        )
        return
    where = str(result.destination.parent.relative_to(folder)).replace(
        "\\", "/"
    )
    tone = category_theme(planned.category)
    note = (
        f" {YELLOW}(→ {truncate(result.destination.name, 22)}){RESET}"
        if result.renamed
        else ""
    )
    print(
        f"  {GREEN}✔{RESET} {progress}  {WHITE}{name}{RESET}{GRAY}→{RESET} "
        f"{fg(tone)}{truncate(where, 18)}/{RESET}{note}"
    )


def organize(
    folder: Path,
    settings: Settings,
    dry_run: bool = False,
    assume_yes: bool = False,
) -> int:
    started = time.perf_counter()
    folder = Path(folder).resolve()
    mode = str(settings["mode"])
    recursive = bool(settings["recursive"])

    try:
        items = scan_files(folder, recursive)
    except OSError as error:
        error_card(
            f"Cannot read selected folder: {truncate(str(folder), WIDTH - 32)}"
        )
        logging.exception("Cannot scan %s: %s", folder, error)
        return 2

    plan = plan_moves(items, folder, mode)
    if not plan:
        info_card(
            "No files to organize in this folder.",
            "Nothing to do",
            "folder is already clean",
        )
        print()
        return 0

    counts: Dict[str, int] = {}
    for planned in plan:
        counts[planned.category] = counts.get(planned.category, 0) + 1
    total_size = sum(p.item.size for p in plan)

    print()
    phase_card(
        [
            f"{GRAY}{pad('Directory', 13)}{RESET}"
            f"{WHITE}{truncate(str(folder), WIDTH - 22)}{RESET}",
            f"{GRAY}{pad('Files found', 13)}{RESET}"
            f"{fg(T_GOLD)}{BOLD}{len(plan)}{RESET}"
            f"{GRAY}  ({fmt_size(total_size)}){RESET}",
            f"{GRAY}{pad('Sort mode', 13)}{RESET}{WHITE}{MODES[mode][0]}{RESET}",
            f"{GRAY}{pad('Subfolders', 13)}{RESET}"
            f"{WHITE}{'included' if recursive else 'not scanned'}{RESET}",
        ],
        "01",
        "◆ Target",
        "scanned with os.scandir",
        T_BLUE,
    )
    print()
    phase_card(
        category_rows(counts, len(plan)),
        "02",
        "◆ Organization plan",
        "files per category",
        T_ORANGE,
    )

    if dry_run:
        show_dry_run(plan, folder)
        return 0

    if not assume_yes:
        print()
        phase_card(
            [
                f"{WHITE}{BOLD}{len(plan)} file(s){RESET}{GRAY} will be moved "
                f"inside {WHITE}{truncate(folder.name, 30)}{RESET}{GRAY}.{RESET}",
                f"{GRAY}Existing files are never overwritten.{RESET}",
                f"{GRAY}You can use Undo last run to restore files.{RESET}",
            ],
            "03",
            "◆ Confirmation",
            "safety check",
            T_YELLOW,
        )
        if not confirm("Type YES to continue:", T_YELLOW):
            info_card(
                "No files were moved.", "Cancelled", "no changes made", T_GRAY
            )
            print()
            logging.info("User cancelled organization of %s", folder)
            return 1

    print()
    phase_card(
        [
            f"{GRAY}Moving {WHITE}{BOLD}{len(plan)}{RESET}{GRAY} file(s)…{RESET}"
        ],
        "04",
        "◆ Processing",
        "live progress",
        T_PURPLE,
    )
    print()

    moves: List[List[str]] = []
    results: List[MoveResult] = []
    try:
        results = execute_plan(
            plan,
            folder,
            moves,
            on_result=lambda i, n, r: print_progress(i, n, r, folder),
        )
    finally:
        # Runs even on Ctrl+C, so everything moved so far can be undone.
        if moves:
            record_run(folder, mode, moves)

    done = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    renamed = sum(1 for r in done if r.renamed)
    moved_size = sum(r.planned.item.size for r in done)
    tidied = remove_empty_dirs(
        {r.planned.item.path.parent for r in done}, folder
    )
    elapsed = time.perf_counter() - started
    total = len(plan)

    print()
    stat_tiles(
        [
            ("Scanned", total, T_BLUE),
            ("Relocated", len(done), T_GREEN),
            ("Renamed", renamed, T_YELLOW if renamed else None),
            ("Failed", len(failed), T_RED if failed else None),
        ]
    )

    status = (
        f"{YELLOW}Completed with errors{RESET}"
        if failed
        else f"{GREEN}{BOLD}All files organized{RESET}"
    )
    print()
    phase_card(
        [
            f"{GRAY}{pad('Status', LABEL_COL)}{RESET}{status}",
            f"{GRAY}{pad('Total files relocated', LABEL_COL)}{RESET}"
            f"{GREEN}{BOLD}{len(done):>5}{RESET}",
            f"{GRAY}{pad('Renamed (collisions)', LABEL_COL)}{RESET}"
            f"{YELLOW}{renamed:>5}{RESET}",
            f"{GRAY}{pad('Empty folders removed', LABEL_COL)}{RESET}"
            f"{WHITE}{tidied:>5}{RESET}",
            f"{GRAY}{pad('Data organized', LABEL_COL)}{RESET}"
            f"{WHITE}{fmt_size(moved_size):>9}{RESET}",
            f"{GRAY}{pad('Success rate', LABEL_COL)}{RESET}"
            f"{bar(len(done), total, CATEGORY_BAR_WIDTH, T_GREEN)} "
            f"{WHITE}{len(done) / total * 100:>5.1f}%{RESET}",
            f"{GRAY}{pad('Elapsed', LABEL_COL)}{RESET}{WHITE}{elapsed:>5.2f}s{RESET}",
            f"{GRAY}{pad('Log file', LABEL_COL)}{RESET}"
            f"{WHITE}{truncate(str(LOG_FILE), WIDTH - 36)}{RESET}",
        ],
        "05",
        "✓ Execution summary",
        "total files relocated",
        T_GREEN,
    )

    per_category: Dict[str, int] = {}
    for r in done:
        per_category[r.planned.category] = (
            per_category.get(r.planned.category, 0) + 1
        )
    if per_category:
        print()
        phase_card(
            category_rows(per_category, len(done)),
            "06",
            "◆ By category",
            "where files went",
            T_TEAL,
        )

    if failed:
        print()
        phase_card(
            error_table((r.planned.item.name, r.error or "") for r in failed),
            "!!",
            "Needs attention",
            f"{len(failed)} file(s) not moved",
            T_RED,
        )
    print()

    logging.info(
        "Finished | folder=%s | mode=%s | scanned=%d | moved=%d | "
        "renamed=%d | failed=%d",
        folder,
        mode,
        total,
        len(done),
        renamed,
        len(failed),
    )
    return 1 if failed else 0


# ----------------------------------------------------------------------
# Undo
# ----------------------------------------------------------------------


def undo_last(folder: Path, assume_yes: bool = False) -> int:
    folder = Path(folder).resolve()
    runs = load_history()
    run = find_last_run(runs, folder)

    if run is None:
        info_card(
            "There is no organization run to undo for this folder.",
            "Nothing to undo",
            "history is empty",
        )
        return 0

    count = len(valid_moves(run)) - len(run.get("done", []))
    print()
    phase_card(
        [
            f"{WHITE}{BOLD}{max(count, 0)} file(s){RESET}{GRAY} from the run at "
            f"{WHITE}{str(run.get('time', 'unknown')).replace('T', ' ')}{RESET}"
            f"{GRAY} will go back to their original locations.{RESET}",
            f"{GRAY}Empty category folders left behind will be tidied up.{RESET}",
            f"{GRAY}Files will not be deleted.{RESET}",
        ],
        "01",
        "◆ Undo last run",
        "restore original locations",
        T_PURPLE,
    )

    if not assume_yes and not confirm("Type YES to undo:", T_PURPLE):
        info_card(
            "No files were moved.", "Cancelled", "no changes made", T_GRAY
        )
        print()
        return 1

    result = undo_run(folder, run)
    save_history(runs)  # saved even after partial failure

    print()
    stat_tiles(
        [
            ("Restored", result.restored, T_GREEN),
            ("Failed", result.failed, T_RED if result.failed else None),
            (
                "Folders tidied",
                result.tidied,
                T_TEAL if result.tidied else None,
            ),
        ]
    )
    if result.problems:
        print()
        phase_card(
            error_table(result.problems),
            "!!",
            "Needs attention",
            f"{len(result.problems)} file(s) not restored",
            T_RED,
        )
    print()
    return 1 if result.failed else 0


# ----------------------------------------------------------------------
# Folder selection
# ----------------------------------------------------------------------


def ask(label: str, theme: int = T_AMBER) -> str:
    return input(
        f"\n  {fg(theme)}{BOLD}❯{RESET} {WHITE}{label}{RESET} "
    ).strip()


def choose_match(
    matches: Sequence[Path], similar: bool = False
) -> Optional[Path]:
    """Numbered picker showing full (wrapped) paths. None means go back."""
    title = (
        "Similar folders found"
        if similar
        else "Multiple matching folders found"
    )
    last = len(matches)
    num_w = len(str(last))
    prefix_w = num_w + 4
    room = max(20, WIDTH - CARD_PAD - prefix_w - 1)

    lines: List[str] = []
    for index, path in enumerate(matches, start=1):
        chunks = wrap_text(path, room)
        lines.append(
            f"{badge(pad(str(index), num_w), T_BLUE)}  {WHITE}{chunks[0]}{RESET}"
        )
        lines += [f"{' ' * prefix_w}{WHITE}{c}{RESET}" for c in chunks[1:]]
        lines.append("")
    lines.append(f"{DARK}Press Enter to search again.{RESET}")

    print()
    phase_card(lines, "00", f"◆ {title}", f"{last} result(s)", T_BLUE)

    while True:
        choice = ask(f"Choose the folder number (1–{last}):", T_BLUE)
        if choice.lower() in ("", "b", "back", "q"):
            return None
        if choice.isdigit() and 1 <= int(choice) <= last:
            return matches[int(choice) - 1]
        invalid(f"Enter a number from 1 to {last}.")


def resolve_folder(
    raw: str, allow_prompt: bool = True, time_limit: float = 10.0
) -> Tuple[Optional[Path], Optional[str]]:
    """
    Turn typed input into one folder.

    Returns (Path, None) when chosen, (None, message) when invalid and
    (None, None) when the user backed out of the picker.
    """
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return None, "No folder name or path entered."
    if looks_like_path(raw):
        return validate_folder(raw)

    print(f"\n  {GRAY}Searching for folders named {WHITE}{raw}{GRAY} …{RESET}")
    exact, partial = find_folders_by_name(raw, time_limit)
    matches = usable_folders(exact)
    similar = False
    if not matches:
        matches = usable_folders(partial)
        similar = bool(matches)
    if not matches:
        return None, f"No folder named '{raw}' was found."
    if len(matches) == 1 and not similar:
        return matches[0], None
    if not allow_prompt:
        listing = "; ".join(str(m) for m in matches[:5])
        return None, (
            f"'{raw}' matches several folders ({listing}). "
            "Use the full path instead."
        )
    return choose_match(matches, similar), None


def folder_confirmed_card(folder: Path, headline: str) -> None:
    print()
    phase_card(
        [
            f"{GREEN}{BOLD}{headline}{RESET}",
            f"{GRAY}{pad('Full path', 16)}{RESET}{WHITE}{folder}{RESET}",
            f"{GRAY}This exact folder will be used for the operation.{RESET}",
        ],
        "✓",
        "◆ Folder confirmed",
        "path validated",
        T_GREEN,
    )


def ask_folder() -> Optional[Path]:
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
            folder_confirmed_card(folder, "Folder selected successfully.")
            return folder
        if problem is None:
            continue
        invalid(problem)
        print(
            f"  {GRAY}Please enter a valid folder name or path and try again.{RESET}"
        )


# ----------------------------------------------------------------------
# Interactive menu
# ----------------------------------------------------------------------


def settings_card(folder: Path, settings: Settings) -> None:
    mode_name, mode_hint = MODES[str(settings["mode"])]
    on = (
        f"{GREEN}{BOLD}ON {RESET}"
        f"{GRAY}(files inside subfolders are included){RESET}"
    )
    off = f"{GRAY}OFF (only files directly inside the folder){RESET}"
    print()
    phase_card(
        [
            f"{GRAY}{pad('Folder', 12)}{RESET}"
            f"{WHITE}{truncate(str(folder), WIDTH - 22)}{RESET}",
            f"{GRAY}{pad('Sort mode', 12)}{RESET}"
            f"{fg(T_GOLD)}{BOLD}{mode_name}{RESET}{DARK}  {mode_hint}{RESET}",
            f"{GRAY}{pad('Subfolders', 12)}{RESET}{on if settings['recursive'] else off}",
        ],
        "01",
        "◆ Current settings",
        "what will be used",
        T_TEAL,
    )


def menu_card() -> None:
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
        f"{badge(k, tone)}  {WHITE}{BOLD}{pad(name, 15)}{RESET}{GRAY}{hint}{RESET}"
        for k, name, hint, tone in items
    ]
    print()
    phase_card(lines, "02", "◆ Main menu", "choose an action", T_AMBER)


def choose_mode(settings: Settings) -> None:
    keys = list(MODES)
    lines = []
    for index, key in enumerate(keys, start=1):
        name, hint = MODES[key]
        current = (
            f" {GREEN}◄ current{RESET}" if key == settings["mode"] else ""
        )
        lines.append(
            f"{badge(str(index), T_ORANGE)}  {WHITE}{BOLD}{pad(name, 19)}{RESET}"
            f"{GRAY}{hint}{RESET}{current}"
        )
    print()
    phase_card(lines, "04", "◆ Sort mode", "how files are grouped", T_ORANGE)

    choice = ask("Choose 1-3 (Enter to keep):", T_ORANGE)
    if choice in ("1", "2", "3"):
        settings["mode"] = keys[int(choice) - 1]
    elif choice:
        invalid("Please enter 1, 2 or 3. Sort mode unchanged.")


def goodbye() -> None:
    print()
    phase_card(
        [
            f"{fg(T_AMBER)}{BOLD}Thank you for using the File Organizer!{RESET}",
            f"{GRAY}Stay organized. Stay productive.{RESET}",
        ],
        "--",
        "Goodbye",
        "see you soon",
        T_AMBER,
    )
    print()


def pause() -> None:
    input(f"\n  {DARK}Press Enter to continue…{RESET}")


def clear_screen() -> None:
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def interactive() -> int:
    settings: Settings = {"mode": "type", "recursive": True}
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
            invalid("Please choose a number from 1 to 7.")
            pause()


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="organizer.py",
        description=f"{APP_TITLE}. Run without arguments for the menu.",
        epilog=(
            "Note: with --recursive (default) top-level folders named like "
            "a category (Images, Code ...) or a year/month (2026-10) are "
            "treated as already organized and are not scanned."
        ),
    )
    parser.add_argument(
        "folder", nargs="?", help="folder name or path (omit to be asked)"
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="preview only; change nothing",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="skip the confirmation prompt"
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
        help="include files inside subfolders "
        "(use --no-recursive to turn off)",
    )
    parser.add_argument(
        "-u",
        "--undo",
        action="store_true",
        help="undo the last run for this folder",
    )
    parser.add_argument(
        "-c",
        "--categories",
        metavar="FILE",
        help="JSON file mapping category names to extensions "
        f"(default: {CATEGORY_FILE_NAME} next to the script, if present)",
    )
    parser.add_argument(
        "--search-limit",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="max seconds to search when a bare folder name "
        "is given (default: 10)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    if sys.version_info < (3, 9):
        print("organizer needs Python 3.9 or newer.", file=sys.stderr)
        return 2

    args = build_parser().parse_args(argv)
    setup_terminal()
    setup_logging()

    try:
        configure_categories(args.categories)
    except CategoryError as error:
        if args.categories:  # the user asked for this file explicitly
            error_card(f"Category file problem: {error}")
            print()
            return 2
        logging.warning("Ignoring categories file: %s", error)
        print(
            f"Warning: {error}. Using the built-in categories.",
            file=sys.stderr,
        )

    try:
        if args.folder is None:
            return interactive()

        label = (
            "UNDO" if args.undo else ("DRY RUN" if args.dry_run else "LIVE")
        )
        theme = (
            T_PURPLE if args.undo else (T_YELLOW if args.dry_run else T_GREEN)
        )
        show_banner(label, theme)

        folder, problem = resolve_folder(
            args.folder,
            allow_prompt=sys.stdin.isatty(),
            time_limit=args.search_limit,
        )
        if folder is None:
            error_card(problem or "Folder selection was cancelled.")
            print()
            return 2

        folder_confirmed_card(folder, "Selected folder validated.")

        if args.undo:
            return undo_last(folder, assume_yes=args.yes)

        settings: Settings = {"mode": args.mode, "recursive": args.recursive}
        return organize(
            folder, settings, dry_run=args.dry_run, assume_yes=args.yes
        )

    except (KeyboardInterrupt, EOFError):
        print()
        info_card(
            "Stopped by user. Files moved so far can be undone.",
            "Exit",
            "operation interrupted",
        )
        print()
        return 130
    except Exception:
        logging.exception("Unexpected error")
        error_card(f"Unexpected error. See {LOG_FILE} for details.")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())