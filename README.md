# Stock Portfolio Performance Tracker

A command-line tool that tracks how a stock portfolio is performing. You enter the S&P 500 stocks you own, how many shares, and what you paid. The program looks up current prices, calculates your gains and losses, shows a colour dashboard in the terminal, and appends the results to a CSV history file.

Built with the Python standard library only (`yfinance` is an optional extra).

![Header and portfolio input](screenshots/input.png)

## Features

- **Dictionary-based portfolio:** holdings are stored as `{ticker: {shares, buy_price}}`. Buying the same ticker twice merges the positions using a weighted average cost.
- **S&P 500 ticker validation:** checks tickers against a local `constituents.csv`. The file is downloaded only if it is missing or invalid.
- **Automatic price lookup with fallbacks:** Yahoo Finance API (one retry), then optional `yfinance`, then manual entry.
- **Performance calculations:** invested amount, market value, gain/loss and percentage return for every holding and for the whole portfolio.
- **Terminal dashboard:** zebra-striped holdings table, summary cards, best/weakest performer, allocation bars and a price-source table. Colours are chosen by data type (green gain, red loss, and so on).
- **CSV history:** every run appends one row per holding plus a portfolio total to `portfolio_summary.csv`, and previous records are never overwritten.
- **Input validation:** rejects non-numeric, zero, negative, `NaN`, infinite and absurdly large values, and malformed tickers.
- **Error resilience:** handles a locked CSV (for example open in Excel) by saving to a timestamped backup, refuses to append to a CSV with the wrong headers, and exits cleanly on Ctrl+C.
- **Logging:** diagnostic messages are written to `portfolio.log` using Python's `logging` module.
- **Configurable:** URLs, timeouts, input limit and CSV fields live in `config.json`.
- **Tested:** `pytest` suite covering parsing, validation, calculations, CSV export and config loading.

## Screenshots

> The screenshots below show a sample session with illustrative prices. They were captured without internet access, so the prices were entered manually. With a connection, the **Price Source** column shows `Yahoo Finance API` instead.

**Looking up prices**

![Price lookup](screenshots/price-lookup.png)

**Holdings table and portfolio summary**

![Report and summary](screenshots/report-and-summary.png)

**Highlights, allocation and price sources**

![Highlights and allocation](screenshots/highlights-allocation.png)

**CSV export**

![CSV export](screenshots/csv-export.png)

## Requirements

- Python 3.9 or newer
- A terminal with 24-bit colour support (Windows Terminal, macOS Terminal, iTerm2, GNOME Terminal, VS Code terminal). Colours are switched off automatically when output is not a terminal or when the `NO_COLOR` environment variable is set.
- Optional: `yfinance` for a fallback price source
- Optional: `pytest` to run the tests

## Installation

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

# optional extras
pip install yfinance pytest
```

No other packages are needed.

## Usage

```bash
python portfolio.py
```

1. Enter a ticker symbol (for example `AAPL`), the number of shares, and the purchase price per share. Repeat for each stock.
2. Press Enter on a blank ticker when you have finished.
3. Review your entries and remove any mistake by typing its ticker, or press Enter to continue.
4. The program fetches prices and prints the report. If a price cannot be found automatically, you are asked to enter one manually.
5. Results are appended to `portfolio_summary.csv`.

Numbers can be typed with commas or a dollar sign (`1,250.50` or `$99.99`).

## Project structure

```
.
├── portfolio.py            # the application
├── config.json             # URLs, timeouts, limits, CSV fields
├── constituents.csv        # S&P 500 companies (ticker, name, sector)
├── test_portfolio.py       # pytest test suite
├── screenshots/            # images used in this README
├── portfolio.log           # created automatically (diagnostic log)
└── portfolio_summary.csv   # created automatically (results history)
```

## Configuration

Settings are read from `config.json`. If the file is missing or invalid, built-in defaults are used.

| Key                       | Meaning                                                                 |
| ------------------------- | ----------------------------------------------------------------------- |
| `dataset_url`             | Where `constituents.csv` is downloaded from if it is missing or invalid |
| `yahoo_url`               | Yahoo Finance chart endpoint (`{}` is replaced by the ticker)           |
| `max_input_value`         | Upper limit accepted for shares and prices                              |
| `request_timeout_seconds` | Timeout for price requests                                              |
| `dataset_timeout_seconds` | Timeout for the dataset download                                        |
| `summary_fields`          | Column names of `portfolio_summary.csv`                                 |

## How prices are found

1. **Yahoo Finance API:** regular market price, with one retry.
2. **yfinance** (if installed): the most recent closing price from the last five days.
3. **Manual entry:** you type a current or reference price.

The price source used is recorded for every holding, both in the on-screen report and in the CSV.

## Output files

**`portfolio_summary.csv`** contains one row per holding and one `TOTAL` row for each run:

`timestamp, ticker, company, sector, shares, buy_price, current_price, price_source, invested, market_value, gain_loss, gain_loss_pct`

**`portfolio.log`** records the program's events with timestamps, such as dataset loading, failed price lookups, and errors:

```
2026-10-21 22:46:20,077 INFO Portfolio tracker started.
2026-10-21 22:46:20,080 INFO Loaded 503 companies from constituents.csv.
2026-10-21 22:46:20,111 WARNING Yahoo lookup attempt 1 failed for AAPL: ...
```

## Running the tests

```bash
pip install pytest
pytest
```

The tests do not need an internet connection.

## Notes and limitations

- Only S&P 500 tickers are accepted when `constituents.csv` is available.
- The Yahoo Finance endpoint is unofficial and may rate-limit or change. The manual fallback exists for this reason.
- Prices are not guaranteed to be real-time.
- This tool is for tracking and learning purposes only and is not financial advice.
