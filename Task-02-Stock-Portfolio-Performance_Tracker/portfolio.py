#!/usr/bin/env python3
"""
Stock Portfolio Performance Tracker (portfolio.py)

Features:
- Dictionary-based portfolio storage
- S&P 500 company dataset validation (local constituents.csv first,
  downloaded only if missing or invalid)
- Automatic stock price lookup with retry and manual fallback
- Investment and market value calculations
- Gain/loss and return calculations
- CSV report logging using Python's built-in csv module
- Diagnostic logging to portfolio.log using the logging module
- Settings (URLs, limits, CSV fields) loaded from config.json
- Dark-dashboard terminal interface with colors chosen by data type

Uses Python's standard library. yfinance is optional.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# TYPE ALIASES
# ============================================================

Color = Tuple[int, int, int]
Segment = Tuple[str, int]                      # (painted text, visible length)
Cell = Tuple[str, Color, bool]                 # (text, color, bold)
Companies = Dict[str, Dict[str, str]]
Portfolio = Dict[str, Dict[str, float]]
Result = Dict[str, Any]
Totals = Dict[str, float]


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "dataset_url": (
        "https://raw.githubusercontent.com/"
        "datasets/s-and-p-500-companies/master/data/constituents.csv"
    ),
    "yahoo_url": "https://query1.finance.yahoo.com/v8/finance/chart/{}",
    "max_input_value": 1e12,
    "request_timeout_seconds": 10,
    "dataset_timeout_seconds": 15,
    "summary_fields": [
        "timestamp", "ticker", "company", "sector", "shares",
        "buy_price", "current_price", "price_source", "invested",
        "market_value", "gain_loss", "gain_loss_pct",
    ],
}

log = logging.getLogger("portfolio")


def load_config(path: str = CONFIG_FILE) -> Dict[str, Any]:
    """Load config.json; fall back to built-in defaults if unusable."""
    config = dict(DEFAULT_CONFIG)

    try:
        with open(path, "r", encoding="utf-8") as file:
            loaded = json.load(file)

        if not isinstance(loaded, dict):
            raise ValueError("config.json must contain a JSON object.")

        config.update(loaded)

    except FileNotFoundError:
        pass  # defaults are fine
    except (OSError, ValueError) as exc:
        # Logging is not configured yet at import time; stderr is enough.
        print(f"Warning: could not read config.json ({exc}). "
              "Using defaults.", file=sys.stderr)

    return config


CONFIG = load_config()

DATASET_URL: str = CONFIG["dataset_url"]
YAHOO_URL: str = CONFIG["yahoo_url"]
MAX_INPUT_VALUE: float = float(CONFIG["max_input_value"])
REQUEST_TIMEOUT: int = int(CONFIG["request_timeout_seconds"])
DATASET_TIMEOUT: int = int(CONFIG["dataset_timeout_seconds"])
SUMMARY_FIELDS: List[str] = list(CONFIG["summary_fields"])

DATASET_FILE = os.path.join(BASE_DIR, "constituents.csv")
SUMMARY_FILE = os.path.join(BASE_DIR, "portfolio_summary.csv")
LOG_FILE = os.path.join(BASE_DIR, "portfolio.log")


def setup_logging(path: str = LOG_FILE) -> None:
    """Send diagnostic messages to a log file (not to the terminal)."""
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


# ============================================================
# TERMINAL DESIGN AND COLORS
# ============================================================

RESET = "\033[0m"

USE_COLORS = (
    sys.stdout.isatty()
    and "NO_COLOR" not in os.environ
)

# Enable ANSI escape handling on older Windows consoles.
if USE_COLORS and os.name == "nt":
    os.system("")

# ---- surfaces ----
PANEL_BG: Color = (15, 23, 42)
CARD_BG: Color = (30, 41, 59)
ROW_ALT: Color = (20, 30, 48)
LINE_COLOR: Color = (51, 65, 85)

# ---- neutral text ----
TEXT_WHITE: Color = (255, 255, 255)
TEXT_SOFT: Color = (226, 232, 240)
SLATE: Color = (203, 213, 225)
MUTED: Color = (148, 163, 184)

# ---- colors by data type ----
C_TICKER: Color = (56, 189, 248)      # ticker symbols      (sky blue)
C_SHARES: Color = (167, 139, 250)     # share quantities    (violet)
C_PRICE: Color = (241, 245, 249)      # per-share prices    (near white)
C_INVESTED: Color = (96, 165, 250)    # money put in        (blue)
C_VALUE: Color = (45, 212, 191)       # market value        (teal)
C_SECTOR: Color = (244, 114, 182)     # sector / category   (pink)
C_TOTAL: Color = (251, 191, 36)       # totals              (amber)
C_GAIN: Color = (74, 222, 128)        # gains               (green)
C_LOSS: Color = (248, 113, 113)       # losses              (red)
C_FLAT: Color = (250, 204, 21)        # unchanged           (yellow)
C_WARN: Color = (251, 146, 60)        # warnings / manual   (orange)

ACCENT = C_TICKER

BAR_PALETTE: List[Color] = [
    (56, 189, 248), (167, 139, 250), (74, 222, 128), (251, 191, 36),
    (244, 114, 182), (45, 212, 191), (251, 146, 60), (96, 165, 250),
]

_cols = shutil.get_terminal_size((100, 24)).columns
PANEL_WIDTH = max(78, min(96, _cols - 4))
PANEL_PAD = 2
CARD_GAP = 2


def paint(
    text: Any,
    fg: Optional[Color] = None,
    bg: Optional[Color] = None,
    bold: bool = False,
) -> str:
    """Apply 24-bit foreground/background colors when supported."""
    if not USE_COLORS:
        return str(text)

    codes: List[str] = []

    if bold:
        codes.append("1")
    if fg:
        codes.append("38;2;{};{};{}".format(*fg))
    if bg:
        codes.append("48;2;{};{};{}".format(*bg))

    if not codes:
        return str(text)

    return f"\033[{';'.join(codes)}m{text}{RESET}"


def perf_color(value: float) -> Color:
    """Green for gains, red for losses, yellow when unchanged."""
    if value > 0:
        return C_GAIN
    if value < 0:
        return C_LOSS
    return C_FLAT


def arrow(value: float) -> str:
    if value > 0:
        return "▲"
    if value < 0:
        return "▼"
    return "●"


def money(value: float) -> str:
    return f"${value:,.2f}"


def signed_money(value: float) -> str:
    sign = "-" if value < 0 else "+" if value > 0 else ""
    return f"{sign}${abs(value):,.2f}"


def pct_text(value: float) -> str:
    return f"{arrow(value)} {value:+.2f}%"


def source_color(source: str) -> Color:
    """Color a price source by how trustworthy it is."""
    if source.startswith("Yahoo"):
        return C_GAIN
    if source.startswith("Recent"):
        return C_FLAT
    return C_WARN


# ---------- status messages (shown on screen and written to the log) ----------

def success(message: str) -> None:
    log.info(message)
    print(paint("  ✔ ", C_GAIN, bold=True) + paint(message, TEXT_SOFT))


def warning(message: str) -> None:
    log.warning(message)
    print(paint("  ▲ ", C_FLAT, bold=True) + paint(message, C_FLAT))


def error_message(message: str) -> None:
    log.error(message)
    print(paint("  ✖ ", C_LOSS, bold=True) + paint(message, C_LOSS))


def info(message: str, color: Color = MUTED) -> None:
    log.info(message)
    print(paint("  • ", color) + paint(message, color))


# ---------- panel building blocks ----------

def part(
    text: Any,
    fg: Color = MUTED,
    bg: Color = PANEL_BG,
    bold: bool = False,
    width: Optional[int] = None,
    align: str = "left",
) -> Segment:
    """Return one painted segment, padded to an exact visible width."""
    text = str(text)

    if width is not None:
        text = text[:width]
        text = text.rjust(width) if align == "right" else text.ljust(width)

    return paint(text, fg, bg, bold), len(text)


def inner_width() -> int:
    return PANEL_WIDTH - 2 * PANEL_PAD


def card_width() -> int:
    return (inner_width() - CARD_GAP) // 2


def panel_row(*parts: Segment, bg: Color = PANEL_BG) -> str:
    """Join painted segments into one full-width panel row."""
    body = "".join(p[0] for p in parts)
    used = sum(p[1] for p in parts)
    fill = max(0, inner_width() - used)

    return (
        "  "
        + paint(" " * PANEL_PAD, None, bg)
        + body
        + paint(" " * fill, None, bg)
        + paint(" " * PANEL_PAD, None, bg)
    )


def blank_row(bg: Color = PANEL_BG) -> str:
    return panel_row(bg=bg)


def divider_row() -> str:
    return panel_row(part("─" * inner_width(), LINE_COLOR))


def card_line(card_w: int, *items: Cell) -> List[Segment]:
    """One row inside a card: items are (text, fg, bold) tuples."""
    segs: List[Segment] = []
    used = 0

    for text, fg, bold in items:
        segs.append(part(text, fg, CARD_BG, bold))
        used += len(text)

    segs.append(part("", MUTED, CARD_BG, width=max(0, card_w - used)))
    return segs


def print_card_pair(
    left: List[List[Segment]], right: List[List[Segment]]
) -> None:
    """Print two equal-height cards side by side, then a spacer row."""
    for left_row, right_row in zip(left, right):
        print(panel_row(*left_row, part(" " * CARD_GAP), *right_row))
    print(blank_row())


def show_header() -> None:
    """Display the dashboard-style application header card."""
    icon_w = 7
    text_w = inner_width() - icon_w - 2
    stamp = datetime.now().strftime("%a %d %b %Y  %H:%M")

    print()
    print(blank_row())
    print(panel_row(
        part(" ▂▄▆█▇ ", ACCENT, CARD_BG, True, width=icon_w),
        part("  "),
        part("STOCK PORTFOLIO TRACKER", TEXT_WHITE, PANEL_BG, True,
             width=text_w),
    ))
    print(panel_row(
        part("", ACCENT, CARD_BG, width=icon_w),
        part("  "),
        part("Investment Performance Dashboard", MUTED, PANEL_BG,
             width=text_w - len(stamp)),
        part(stamp, C_TOTAL, PANEL_BG),
    ))
    print(blank_row())
    print(divider_row())
    print(blank_row())
    print(panel_row(
        part("ANALYZE HOLDINGS", C_TICKER, PANEL_BG, True),
        part("  •  ", LINE_COLOR),
        part("TRACK RETURNS", C_GAIN, PANEL_BG, True),
        part("  •  ", LINE_COLOR),
        part("EXPORT REPORTS", C_SECTOR, PANEL_BG, True),
    ))
    print(blank_row())
    print()


def show_section(title: str, icon: str = "◆", color: Color = ACCENT) -> None:
    """Section banner: colored accent bar, icon and bold title."""
    print()
    print(panel_row(
        part(" ▌", color, CARD_BG, True),
        part(f" {icon}  ", color, CARD_BG, True),
        part(title, TEXT_WHITE, CARD_BG, True),
        bg=CARD_BG,
    ))
    print()


def show_dashboard(total: Totals) -> None:
    """Render four portfolio metrics as a dark 2x2 card dashboard."""
    w = card_width()

    def card(label: str, value: str, value_fg: Color) -> List[List[Segment]]:
        return [
            card_line(w),
            card_line(w, ("  " + label, MUTED, False)),
            card_line(w, ("  " + value, value_fg, True)),
            card_line(w),
        ]

    gain_label = "NET LOSS" if total["gain_loss"] < 0 else "NET GAIN"
    gain_fg = perf_color(total["gain_loss"])
    pct_fg = perf_color(total["gain_loss_pct"])

    cards = [
        card("TOTAL INVESTED", money(total["invested"]), C_INVESTED),
        card("MARKET VALUE", money(total["market_value"]), C_VALUE),
        card(gain_label, signed_money(total["gain_loss"]), gain_fg),
        card("TOTAL RETURN", pct_text(total["gain_loss_pct"]), pct_fg),
    ]

    print_card_pair(cards[0], cards[1])
    print_card_pair(cards[2], cards[3])

    print(panel_row(
        part("Live calculations based on the prices retrieved for this run.",
             MUTED, PANEL_BG)
    ))
    print(blank_row())


def show_progress(current: int, total: int, width: int = 24) -> None:
    if total <= 0:
        return

    filled = int(width * current / total)
    percent = int(100 * current / total)

    print(
        "  "
        + paint("█" * filled, C_GAIN)
        + paint("░" * (width - filled), LINE_COLOR)
        + paint(f" {percent:3d}% ", TEXT_SOFT, bold=True)
        + paint(f"{current}/{total}", MUTED)
    )


def parse_number(raw: str) -> Optional[float]:
    """Return a finite positive number within the limit, or None."""
    cleaned = raw.strip().replace(",", "").replace("$", "")

    try:
        value = float(cleaned)
    except ValueError:
        return None

    if math.isfinite(value) and 0 < value <= MAX_INPUT_VALUE:
        return value

    return None


def ask_number(label: str) -> float:
    """Accept only finite, positive numbers within a sane limit."""
    while True:
        raw = input(
            paint("      ❯ ", C_SHARES, bold=True)
            + paint(f"{label}: ", TEXT_WHITE)
        )
        value = parse_number(raw)

        if value is not None:
            return value

        warning("Enter a valid number greater than zero.")


# ============================================================
# DATASET MANAGEMENT
# ============================================================

def parse_constituents(text: str) -> Companies:
    """Return {ticker: {'name': ..., 'sector': ...}}."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))

    if not reader.fieldnames:
        raise ValueError("Dataset is empty.")

    reader.fieldnames = [
        (header or "").strip() for header in reader.fieldnames
    ]

    required = {"Symbol", "Security", "GICS Sector"}
    missing = required - set(reader.fieldnames)

    if missing:
        raise ValueError(
            f"Missing dataset columns: {', '.join(sorted(missing))}. "
            f"Found: {reader.fieldnames}"
        )

    companies: Companies = {}

    for row in reader:
        ticker = (row.get("Symbol") or "").strip().upper()

        if ticker:
            companies[ticker] = {
                "name": (row.get("Security") or "").strip(),
                "sector": (row.get("GICS Sector") or "").strip(),
            }

    if not companies:
        raise ValueError("Dataset contains no company records.")

    return companies


def save_dataset_atomically(text: str, path: str = DATASET_FILE) -> None:
    """Write to a temp file first so a crash can't corrupt the dataset."""
    temp_path = path + ".tmp"

    with open(temp_path, "w", newline="", encoding="utf-8") as file:
        file.write(text)

    os.replace(temp_path, path)


def load_constituents() -> Companies:
    """Use the local constituents.csv if valid; download only if needed."""
    show_section("LOADING COMPANY DATA", "◆", C_TICKER)

    # 1. Local file first.
    if os.path.exists(DATASET_FILE):
        try:
            with open(DATASET_FILE, "r", encoding="utf-8-sig") as file:
                companies = parse_constituents(file.read())

            success(f"Loaded {len(companies)} companies from "
                    f"{os.path.basename(DATASET_FILE)}.")
            return companies

        except (OSError, ValueError, csv.Error) as exc:
            warning(f"Local dataset is invalid: {exc}")

    # 2. Download only if the local file is missing or broken.
    try:
        request = urllib.request.Request(
            DATASET_URL, headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(
            request, timeout=DATASET_TIMEOUT
        ) as response:
            text = response.read().decode("utf-8-sig")

        companies = parse_constituents(text)
        save_dataset_atomically(text)

        success(f"Downloaded and saved {len(companies)} companies.")
        return companies

    except Exception as exc:  # network, parsing or disk problems
        warning(f"Online dataset unavailable: {exc}")

    warning("S&P 500 ticker validation is disabled.")
    warning("Only use known ticker symbols if you continue.")

    return {}


# ============================================================
# STOCK PRICE LOOKUP
# ============================================================

def price_from_yahoo_api(symbol: str) -> Optional[float]:
    """Get Yahoo Finance regular-market price (one retry on failure)."""
    request = urllib.request.Request(
        YAHOO_URL.format(symbol),
        headers={"User-Agent": "Mozilla/5.0"},
    )

    for attempt in range(2):
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT
            ) as response:
                data = json.loads(response.read().decode("utf-8"))

            results = data.get("chart", {}).get("result")

            if not results:
                log.info("Yahoo returned no result for %s", symbol)
                return None

            price = results[0].get("meta", {}).get("regularMarketPrice")

            if price is not None:
                price = float(price)

                if math.isfinite(price) and price > 0:
                    return price

            return None

        except (OSError, ValueError, TypeError, AttributeError) as exc:
            log.warning("Yahoo lookup attempt %d failed for %s: %s",
                        attempt + 1, symbol, exc)

            if attempt == 0:
                time.sleep(1)  # temporary errors (e.g. HTTP 429)

    return None


def price_from_yfinance(symbol: str) -> Optional[float]:
    """Optional fallback: latest available closing price."""
    try:
        import yfinance as yf
    except ImportError:
        log.info("yfinance is not installed; skipping fallback.")
        return None

    try:
        history = yf.Ticker(symbol).history(period="5d")

        if not history.empty:
            closes = history["Close"].dropna()

            if not closes.empty:
                price = float(closes.iloc[-1])

                if math.isfinite(price) and price > 0:
                    return price

    except Exception as exc:  # yfinance raises many different errors
        info(f"yfinance lookup failed for {symbol}: {exc}", MUTED)

    return None


def get_current_price(ticker: str) -> Tuple[float, str]:
    """Return a price and an accurate description of its source."""
    symbol = ticker.replace(".", "-")

    price = price_from_yahoo_api(symbol)

    if price is not None:
        return price, "Yahoo Finance API"

    price = price_from_yfinance(symbol)

    if price is not None:
        return price, "Recent close (yfinance)"

    warning(f"Automatic price lookup failed for {ticker}.")

    price = ask_number(
        f"Enter current/reference price for {ticker} ($)"
    )

    return price, "Manual entry"


# ============================================================
# PORTFOLIO INPUT
# ============================================================

def is_valid_ticker_format(ticker: str) -> bool:
    """Ticker must be 1-10 characters: letters, digits, '.' or '-'."""
    return (
        0 < len(ticker) <= 10
        and all(char.isalnum() or char in ".-" for char in ticker)
    )


def merge_position(
    old: Dict[str, float], shares: float, buy_price: float
) -> Dict[str, float]:
    """Combine a new purchase with an existing holding (average cost)."""
    total_shares = old["shares"] + shares
    average_cost = (
        old["shares"] * old["buy_price"] + shares * buy_price
    ) / total_shares

    return {"shares": total_shares, "buy_price": average_cost}


def collect_positions(companies: Companies) -> Portfolio:
    """
    Store holdings in a dictionary.

    Example:
    {
        'AAPL': {'shares': 10.0, 'buy_price': 180.0}
    }
    """
    portfolio: Portfolio = {}

    show_section("BUILD YOUR PORTFOLIO", "✚", C_SHARES)

    info("Enter the ticker symbol, quantity, and purchase price.", SLATE)
    info("Enter a blank ticker when you have finished.", MUTED)

    while True:
        ticker = input(
            paint("\n  ❯ ", C_TICKER, bold=True)
            + paint("Ticker symbol: ", TEXT_WHITE, bold=True)
        ).strip().upper()

        if not ticker:
            if portfolio:
                break

            warning("Enter at least one stock.")
            continue

        if not is_valid_ticker_format(ticker):
            warning("Invalid ticker format.")
            continue

        if companies and ticker not in companies:
            warning(f"{ticker} is not in the S&P 500 dataset.")
            continue

        shares = ask_number("Share quantity")
        buy_price = ask_number("Purchase price per share ($)")

        if ticker in portfolio:
            portfolio[ticker] = merge_position(
                portfolio[ticker], shares, buy_price
            )
            updated = portfolio[ticker]

            log.info("Updated %s: %.4f shares, avg cost %.2f",
                     ticker, updated["shares"], updated["buy_price"])

            print(
                paint("  ✔ ", C_GAIN, bold=True)
                + paint("Updated ", TEXT_SOFT)
                + paint(ticker, C_TICKER, bold=True)
                + paint(f"  {updated['shares']:,.4f} shares", C_SHARES)
                + paint("  avg cost ", MUTED)
                + paint(money(updated["buy_price"]), C_PRICE, bold=True)
            )

        else:
            portfolio[ticker] = {
                "shares": shares,
                "buy_price": buy_price,
            }

            company_name = companies.get(ticker, {}).get("name", "")

            log.info("Added %s: %.4f shares @ %.2f",
                     ticker, shares, buy_price)

            print(
                paint("  ✔ ", C_GAIN, bold=True)
                + paint("Added ", TEXT_SOFT)
                + paint(ticker, C_TICKER, bold=True)
                + (paint(f"  {company_name}", MUTED) if company_name else "")
                + paint(f"  {shares:,.4f} sh", C_SHARES)
                + paint(" @ ", MUTED)
                + paint(money(buy_price), C_PRICE, bold=True)
            )

    return portfolio


def review_portfolio(portfolio: Portfolio) -> None:
    """Let the user remove a wrong entry before prices are fetched."""
    while portfolio:
        show_section("REVIEW YOUR PORTFOLIO", "✎", C_TOTAL)

        for ticker, pos in portfolio.items():
            print(
                "  "
                + paint(f"{ticker:<8}", C_TICKER, bold=True)
                + paint(f"{pos['shares']:>14,.4f} sh", C_SHARES)
                + paint(" @ ", MUTED)
                + paint(money(pos["buy_price"]), C_PRICE, bold=True)
            )

        choice = input(
            paint("\n  ❯ ", C_TOTAL, bold=True)
            + paint("Ticker to remove (blank to continue): ", TEXT_WHITE)
        ).strip().upper()

        if not choice:
            return

        if choice in portfolio:
            del portfolio[choice]
            success(f"Removed {choice}.")
        else:
            warning(f"{choice} is not in your portfolio.")

    warning("Your portfolio is now empty.")


# ============================================================
# CALCULATIONS
# ============================================================

def calculate_position(
    ticker: str,
    position: Dict[str, float],
    current_price: float,
    source: str,
    company_info: Dict[str, str],
) -> Result:
    """Calculate performance figures for one holding."""
    invested = position["shares"] * position["buy_price"]
    market_value = position["shares"] * current_price
    gain_loss = market_value - invested
    gain_loss_pct = (gain_loss / invested) * 100 if invested else 0.0

    return {
        "ticker": ticker,
        "company": company_info.get("name") or "N/A",
        "sector": company_info.get("sector") or "N/A",
        "shares": position["shares"],
        "buy_price": position["buy_price"],
        "current_price": current_price,
        "price_source": source,
        "invested": invested,
        "market_value": market_value,
        "gain_loss": gain_loss,
        "gain_loss_pct": gain_loss_pct,
    }


def evaluate(portfolio: Portfolio, companies: Companies) -> List[Result]:
    """Fetch prices and calculate investment performance per holding."""
    results: List[Result] = []

    show_section("FETCHING STOCK PRICES", "◈", C_FLAT)

    total_positions = len(portfolio)

    for index, (ticker, position) in enumerate(
        portfolio.items(), start=1
    ):
        company_info = companies.get(ticker, {})

        print(
            paint(f"  ◈ {index}/{total_positions}  ", C_FLAT, bold=True)
            + paint("Checking ", MUTED)
            + paint(ticker, C_TICKER, bold=True)
            + (paint(f"  {company_info['name']}", MUTED)
               if company_info.get("name") else "")
        )

        current_price, source = get_current_price(ticker)
        row = calculate_position(
            ticker, position, current_price, source, company_info
        )
        results.append(row)

        log.info("%s price %.2f via %s", ticker, current_price, source)

        show_progress(index, total_positions)

        print(
            paint("  ✔ ", C_GAIN, bold=True)
            + paint(ticker, C_TICKER, bold=True)
            + paint("  price ", MUTED)
            + paint(money(current_price), C_PRICE, bold=True)
            + paint("  via ", MUTED)
            + paint(source, source_color(source))
            + paint("  return ", MUTED)
            + paint(pct_text(row["gain_loss_pct"]),
                    perf_color(row["gain_loss_pct"]), bold=True)
        )
        print()

    return results


def calculate_totals(results: List[Result]) -> Totals:
    """Calculate total portfolio performance."""
    invested = sum(row["invested"] for row in results)
    market_value = sum(row["market_value"] for row in results)
    gain_loss = market_value - invested

    return_pct = (gain_loss / invested * 100) if invested else 0.0

    return {
        "invested": invested,
        "market_value": market_value,
        "gain_loss": gain_loss,
        "gain_loss_pct": return_pct,
    }


# ============================================================
# PERFORMANCE REPORT
# ============================================================

def print_holdings_table(results: List[Result], total: Totals) -> None:
    """Zebra-striped table; optional columns are dropped if too wide."""
    headers = [
        "Ticker", "Shares", "Buy Price", "Current",
        "Invested", "Market Value", "Gain/Loss", "Return",
    ]

    def cells(row: Result) -> List[Cell]:
        gain_fg = perf_color(row["gain_loss"])
        pct_fg = perf_color(row["gain_loss_pct"])

        return [
            (row["ticker"], C_TICKER, True),
            (f'{row["shares"]:,.2f}', C_SHARES, False),
            (f'{row["buy_price"]:,.2f}', SLATE, False),
            (f'{row["current_price"]:,.2f}', C_PRICE, True),
            (f'{row["invested"]:,.2f}', C_INVESTED, False),
            (f'{row["market_value"]:,.2f}', C_VALUE, False),
            (f'{row["gain_loss"]:+,.2f}', gain_fg, True),
            (pct_text(row["gain_loss_pct"]), pct_fg, True),
        ]

    body = [cells(row) for row in results]

    total_cells: List[Cell] = [
        ("TOTAL", C_TOTAL, True),
        ("", MUTED, False),
        ("", MUTED, False),
        ("", MUTED, False),
        (f'{total["invested"]:,.2f}', C_INVESTED, True),
        (f'{total["market_value"]:,.2f}', C_VALUE, True),
        (f'{total["gain_loss"]:+,.2f}', perf_color(total["gain_loss"]), True),
        (pct_text(total["gain_loss_pct"]),
         perf_color(total["gain_loss_pct"]), True),
    ]

    all_rows = body + [total_cells]

    def column_widths(keep: List[int]) -> List[int]:
        return [
            max(len(headers[i]), *(len(r[i][0]) for r in all_rows))
            for i in keep
        ]

    def table_width(keep: List[int]) -> int:
        return sum(column_widths(keep)) + 2 * (len(keep) - 1)

    # Drop the least important columns until the table fits the panel.
    keep = list(range(len(headers)))

    for droppable in (2, 4):  # Buy Price, then Invested
        if table_width(keep) > inner_width():
            keep.remove(droppable)

    widths = column_widths(keep)

    def print_line(row_cells: List[Cell], bg: Color) -> None:
        segs: List[Segment] = []

        for position, i in enumerate(keep):
            text, fg, bold = row_cells[i]

            if position:
                segs.append(part("  ", MUTED, bg))

            segs.append(part(
                text, fg, bg, bold, width=widths[position],
                align="left" if position == 0 else "right",
            ))

        print(panel_row(*segs, bg=bg))

    header_cells: List[Cell] = [(h, SLATE, True) for h in headers]

    print_line(header_cells, CARD_BG)

    for number, row_cells in enumerate(body):
        print_line(row_cells, PANEL_BG if number % 2 == 0 else ROW_ALT)

    print_line(total_cells, CARD_BG)
    print(blank_row())

    print(panel_row(
        part("LEGEND  ", MUTED, PANEL_BG, True),
        part("● ticker  ", C_TICKER),
        part("● shares  ", C_SHARES),
        part("● price  ", C_PRICE),
        part("● invested  ", C_INVESTED),
        part("● value  ", C_VALUE),
        part("▲ gain  ", C_GAIN),
        part("▼ loss", C_LOSS),
    ))
    print(blank_row())


def print_highlights(results: List[Result]) -> None:
    best = max(results, key=lambda row: row["gain_loss_pct"])
    worst = min(results, key=lambda row: row["gain_loss_pct"])

    w = card_width()

    def card(
        title: str, row: Result, title_fg: Color
    ) -> List[List[Segment]]:
        fg = perf_color(row["gain_loss_pct"])
        company = row["company"][: max(0, w - 4)]
        gain_text = signed_money(row["gain_loss"])
        sector_room = max(0, w - 4 - len(gain_text) - 2)

        return [
            card_line(w),
            card_line(w, (f"  {title}", title_fg, True)),
            card_line(
                w,
                ("  ", MUTED, False),
                (row["ticker"], C_TICKER, True),
                ("   ", MUTED, False),
                (pct_text(row["gain_loss_pct"]), fg, True),
            ),
            card_line(w, ("  " + company, MUTED, False)),
            card_line(
                w,
                ("  ", MUTED, False),
                (gain_text, fg, False),
                ("  " + row["sector"][:sector_room], C_SECTOR, False),
            ),
            card_line(w),
        ]

    print_card_pair(
        card("▲ BEST PERFORMER", best, C_GAIN),
        card("▼ WEAKEST PERFORMER", worst, C_LOSS),
    )


def print_allocation(results: List[Result], total: Totals) -> None:
    """Bar chart of each holding's share of the portfolio's market value."""
    bar_width = 24
    value_w = 16
    percent_w = 8
    sector_w = max(0, inner_width() - (8 + bar_width + percent_w + value_w))
    market_total = total["market_value"] or 1.0

    ordered = sorted(
        results, key=lambda row: row["market_value"], reverse=True
    )

    for number, row in enumerate(ordered):
        share = row["market_value"] / market_total
        filled = max(1, round(bar_width * share)) if share > 0 else 0
        color = BAR_PALETTE[number % len(BAR_PALETTE)]

        print(panel_row(
            part(row["ticker"], C_TICKER, PANEL_BG, True, width=8),
            part("█" * filled, color),
            part("░" * (bar_width - filled), LINE_COLOR),
            part(f"  {share * 100:5.1f}%", TEXT_SOFT, PANEL_BG, True,
                 width=percent_w),
            part("  " + money(row["market_value"]), C_VALUE,
                 PANEL_BG, width=value_w, align="right"),
            part("  " + row["sector"], C_SECTOR, PANEL_BG, width=sector_w),
        ))

    print(blank_row())


def print_sources(results: List[Result]) -> None:
    source_w = 26  # "● " plus the longest source label
    avail = max(10, inner_width() - 8 - source_w)
    company_w = avail // 2
    sector_w = avail - company_w

    print(panel_row(
        part("TICKER", MUTED, PANEL_BG, True, width=8),
        part("COMPANY", MUTED, PANEL_BG, True, width=company_w),
        part("SECTOR", MUTED, PANEL_BG, True, width=sector_w),
        part("PRICE SOURCE", MUTED, PANEL_BG, True),
    ))
    print(divider_row())

    for row in results:
        print(panel_row(
            part(row["ticker"], C_TICKER, PANEL_BG, True, width=8),
            part(row["company"][: company_w - 2], SLATE, PANEL_BG,
                 width=company_w),
            part(row["sector"][: sector_w - 2], C_SECTOR, PANEL_BG,
                 width=sector_w),
            part("● ", source_color(row["price_source"]), PANEL_BG, True),
            part(row["price_source"], source_color(row["price_source"])),
        ))

    print(blank_row())
    print(panel_row(
        part("● ", C_GAIN), part("live API   ", MUTED),
        part("● ", C_FLAT), part("recent close   ", MUTED),
        part("● ", C_WARN), part("manual entry", MUTED),
    ))
    print(blank_row())


def print_report(results: List[Result], total: Totals) -> None:
    """Display the formatted portfolio performance report."""
    show_section("HOLDINGS PERFORMANCE", "▤", C_INVESTED)

    print(panel_row(
        part("Report generated  ", MUTED),
        part(f"{datetime.now():%Y-%m-%d %H:%M:%S}", C_TOTAL, PANEL_BG, True),
        part("     Holdings  ", MUTED),
        part(str(len(results)), C_SHARES, PANEL_BG, True),
    ))
    print(blank_row())

    print_holdings_table(results, total)

    show_section("PORTFOLIO SUMMARY", "◉", C_VALUE)
    show_dashboard(total)

    show_section("PERFORMANCE HIGHLIGHTS", "★", C_TOTAL)
    print_highlights(results)

    show_section("PORTFOLIO ALLOCATION", "◔", C_SECTOR)
    print_allocation(results, total)

    show_section("PRICE SOURCES", "⌗", C_SHARES)
    print_sources(results)

    print(blank_row())
    print(panel_row(
        part("END OF PORTFOLIO REPORT".center(inner_width()),
             ACCENT, PANEL_BG, True)
    ))
    print(blank_row())


# ============================================================
# CSV EXPORT
# ============================================================

def validate_summary_file(path: str) -> None:
    """Prevent appending to a CSV with incompatible headers."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return

    with open(path, "r", newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        existing_headers = next(reader, [])

    if existing_headers != SUMMARY_FIELDS:
        raise ValueError(
            f"Incompatible headers in {path}.\n"
            f"Expected: {SUMMARY_FIELDS}\n"
            f"Found: {existing_headers}\n"
            "Back up the file and correct or rename it before rerunning."
        )


def build_summary_rows(
    results: List[Result], total: Totals
) -> List[Dict[str, Any]]:
    """Create the CSV rows: one per holding plus a portfolio total."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    numeric_fields = {
        "shares", "buy_price", "current_price", "invested",
        "market_value", "gain_loss", "gain_loss_pct",
    }

    rows: List[Dict[str, Any]] = []

    for result in results:
        row = {"timestamp": timestamp, **result}

        for field in numeric_fields:
            precision = 4 if field == "shares" else 2
            row[field] = round(row[field], precision)

        rows.append(row)

    rows.append({
        "timestamp": timestamp,
        "ticker": "TOTAL",
        "company": "PORTFOLIO TOTAL",
        "sector": "",
        "shares": "",
        "buy_price": "",
        "current_price": "",
        "price_source": "",
        "invested": round(total["invested"], 2),
        "market_value": round(total["market_value"], 2),
        "gain_loss": round(total["gain_loss"], 2),
        "gain_loss_pct": round(total["gain_loss_pct"], 2),
    })

    return rows


def write_rows(rows: List[Dict[str, Any]], path: str) -> None:
    """Append rows to the CSV, writing the header for a new file."""
    validate_summary_file(path)

    new_file = not os.path.exists(path) or os.path.getsize(path) == 0

    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file, fieldnames=SUMMARY_FIELDS, extrasaction="raise"
        )

        if new_file:
            writer.writeheader()

        writer.writerows(rows)


def save_summary(
    results: List[Result], total: Totals, path: str = SUMMARY_FILE
) -> None:
    """Append all holding records and a portfolio total record."""
    rows = build_summary_rows(results, total)

    try:
        write_rows(rows, path)

    except PermissionError:
        backup = os.path.join(
            BASE_DIR, f"portfolio_summary_{datetime.now():%Y%m%d_%H%M%S}.csv"
        )
        warning(f"{os.path.basename(path)} is locked "
                "(is it open in Excel?). Saving to a backup file instead.")
        write_rows(rows, backup)
        path = backup

    log.info("Saved %d records to %s", len(rows), path)
    show_section("CSV EXPORT SUCCESS", "✔", C_GAIN)

    full_path = os.path.abspath(path)
    room = inner_width() - 26

    if len(full_path) > room:
        full_path = "…" + full_path[-(room - 1):]

    def kv(label: str, value: str, fg: Color, bold: bool = False) -> None:
        print(panel_row(
            part(label, MUTED, PANEL_BG, width=24),
            part(value, fg, PANEL_BG, bold),
        ))

    kv("Status", "Portfolio results saved successfully", C_GAIN, True)
    kv("Report file", full_path, C_TICKER)
    kv("Holding records", str(len(results)), C_SHARES, True)
    kv("Portfolio total record", "1", C_TOTAL, True)
    kv("History", "Previous records have been preserved", C_GAIN)
    print(blank_row())


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    setup_logging()
    log.info("Portfolio tracker started.")

    show_header()

    # Fail fast: check the CSV log before asking for any input.
    validate_summary_file(SUMMARY_FILE)

    companies = load_constituents()

    portfolio: Portfolio = {}
    while not portfolio:
        portfolio = collect_positions(companies)
        review_portfolio(portfolio)

    results = evaluate(portfolio, companies)
    total = calculate_totals(results)

    print_report(results, total)
    save_summary(results, total)

    log.info("Portfolio tracker finished normally.")

    print()
    print(paint("  ✦ ", C_TOTAL, bold=True)
          + paint("Thank you for using Stock Portfolio Tracker!",
                  TEXT_WHITE, bold=True))
    print()


if __name__ == "__main__":
    try:
        main()

    except (KeyboardInterrupt, EOFError):
        print()
        warning("Program cancelled by user.")

    except (OSError, ValueError, csv.Error) as exc:
        print()
        error_message(str(exc))
        sys.exit(1)