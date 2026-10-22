# Datheon Python Programming Internship

Python programming internship projects and task submissions for Datheon. The four tasks progress from a Hangman game to a stock portfolio tracker, a file organizer, and a rule-based chatbot, all built as command-line applications.

**Language:** Python 3.9 or newer (standard library only; optional extras are noted per task)

---

## Tasks at a Glance

| # | Task | Summary | Folder |
|---|------|---------|--------|
| 1 | Hangman Word Guessing Game | Terminal word-guessing game | [`Task-01-Hangman-Word-Guessing-Game`](./Task-01-Hangman-Word-Guessing-Game) |
| 2 | Stock Portfolio Performance Tracker | Tracks gains and losses for S&P 500 holdings and saves a CSV history | [`Task-02-Stock-Portfolio-Performance_Tracker`](./Task-02-Stock-Portfolio-Performance_Tracker) |
| 3 | Automated File Organizer & Cleanup Utility | Sorts a messy folder into category folders, with dry-run preview and undo | [`Task-03-Automated-File-Organizer`](./Task-03-Automated-File-Organizer) |
| 4 | Rule-Based Interactive Terminal Assistant | Terminal chatbot that answers FAQs from a JSON file | [`Task-04-Interactive Terminal Assistant-Chatbot`](./Task-04-Interactive%20Terminal%20Assistant-Chatbot) |

---

## Task 1: Hangman Word Guessing Game

A command-line version of the classic Hangman game. The player guesses a hidden word one letter at a time before running out of attempts.

**Key skills:** loops and conditionals, string handling, input validation, functions, and game state tracking

**Run:**
```bash
cd Task-01-Hangman-Word-Guessing-Game
python hangman.py
```

Full details: [Task 1 folder](./Task-01-Hangman-Word-Guessing-Game)

---

## Task 2: Stock Portfolio Performance Tracker

A command-line tool that tracks how a stock portfolio is performing. You enter the S&P 500 stocks you own, the number of shares, and your purchase price. The program looks up current prices, calculates gains and losses, shows a color dashboard in the terminal, and appends the results to a CSV history file.

**Highlights**
- Dictionary-based portfolio; buying the same ticker twice merges positions with a weighted average cost
- S&P 500 ticker validation against a local `constituents.csv`
- Price lookup with fallbacks: Yahoo Finance API, then optional `yfinance`, then manual entry
- Invested amount, market value, gain/loss, and percentage return per holding and for the whole portfolio
- Terminal dashboard with summary cards, best and weakest performers, and allocation bars
- CSV history that appends every run and never overwrites earlier records
- Strict input validation, a safe fallback when the CSV is locked, and `portfolio.log` diagnostics
- Settings in `config.json`, plus a `pytest` suite that runs offline

**Key skills:** dictionaries, API requests, CSV handling, input validation, error handling, logging, configuration files, and unit testing

**Run:**
```bash
cd Task-02-Stock-Portfolio-Performance_Tracker
python portfolio.py
```

**Test:**
```bash
python -m pytest -v
```

Full details: [Task 2 folder](./Task-02-Stock-Portfolio-Performance_Tracker)

---

## Task 3: Automated File Organizer & Cleanup Utility

A command-line tool that safely organizes a messy folder into tidy category folders. It never overwrites existing files, previews every planned move, and can undo the last run.

**Highlights**
- Three sorting modes: by file type, by type and month, or by month only
- Dry-run preview that shows planned destinations and filename conflicts
- Collision-safe naming (`report.pdf` becomes `report_1.pdf` instead of being overwritten)
- Undo for the last run, including partial failures and interrupted runs
- Custom categories through an optional `categories.json`
- Safety checks that refuse system folders, drive roots, and symlinked folders
- Logging, colored output, and progress bars

**Key skills:** file system operations (`pathlib`, `shutil`), `argparse` CLI design, JSON configuration, logging, defensive programming, and unit testing

**Run:**
```bash
cd Task-03-Automated-File-Organizer
python organizer.py "TestFiles" --dry-run
python organizer.py "TestFiles"
python organizer.py "TestFiles" --undo
```

**Test:**
```bash
python -m pytest -v
```

Full details: [Task 3 folder](./Task-03-Automated-File-Organizer)

---

## Task 4: Rule-Based Interactive Terminal Assistant

A customer-support chatbot that runs in the terminal. It answers business-hours and product FAQs loaded from `faq.json`, understands greetings, rephrasings, and follow-ups, and falls back gracefully when it is unsure.

**Highlights**
- Input normalization with keyword and regular-expression matching
- Tiered matching: exact question, then keywords and synonyms, then word overlap
- Conversation states: greeting, identifying, resolved, exited
- Contextual follow-ups: "tell me more" uses the last answered FAQ
- "Did you mean...?" suggestion when confidence is low
- Dashboard-style terminal UI with an ASCII fallback
- Clear errors for a missing or invalid `faq.json`, plus diagnostics in `chatbot.log`

**Key skills:** regular expressions, state machines, JSON validation, type annotations, logging, terminal UI design, and unit testing

**Run:**
```bash
cd "Task-04-Interactive Terminal Assistant-Chatbot"
python chatbot.py
```

**Test:**
```bash
python -m unittest -v
```

Full details: [Task 4 folder](./Task-04-Interactive%20Terminal%20Assistant-Chatbot)

---

## Repository Structure

```text
.
├── Task-01-Hangman-Word-Guessing-Game/
├── Task-02-Stock-Portfolio-Performance_Tracker/
├── Task-03-Automated-File-Organizer/
├── Task-04-Interactive Terminal Assistant-Chatbot/
└── README.md
```

## Getting Started

```bash
git clone https://github.com/sadiaislam2023/Datheon_Python_Programming_Internship.git
cd Datheon_Python_Programming_Internship
```

Then open any task folder and follow the run instructions above.

Optional packages:

```bash
python -m pip install pytest yfinance
```

`pytest` runs the Task 2 and Task 3 tests. `yfinance` is an optional price source for Task 2.

## Skills Demonstrated

- Writing clean, modular Python with only the standard library
- Command-line interfaces and interactive terminal UIs
- File system automation with safety checks and undo
- Working with JSON and CSV data
- Input validation and defensive error handling
- Logging and configuration files
- Automated testing with `pytest` and `unittest`
- Clear documentation with screenshots

## Author

**Sadia Islam**
GitHub: [@sadiaislam2023](https://github.com/sadiaislam2023)
