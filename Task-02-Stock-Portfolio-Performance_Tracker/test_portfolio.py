"""Automated tests for portfolio.py (run with: pytest)."""

import csv
import os

import pytest

import portfolio
from portfolio import (
    C_FLAT,
    C_GAIN,
    C_LOSS,
    build_summary_rows,
    calculate_position,
    calculate_totals,
    is_valid_ticker_format,
    merge_position,
    money,
    parse_constituents,
    parse_number,
    pct_text,
    perf_color,
    signed_money,
    validate_summary_file,
    write_rows,
)

VALID_DATASET = (
    "Symbol,Security,GICS Sector\n"
    "AAPL,Apple Inc.,Information Technology\n"
    "msft,Microsoft,Information Technology\n"
)


# ---------- dataset parsing ----------

def test_parse_valid_dataset():
    companies = parse_constituents(VALID_DATASET)
    assert companies["AAPL"]["name"] == "Apple Inc."
    assert companies["MSFT"]["sector"] == "Information Technology"  # upper-cased


def test_parse_handles_bom():
    assert "AAPL" in parse_constituents("\ufeff" + VALID_DATASET)


def test_parse_missing_columns():
    with pytest.raises(ValueError, match="Missing dataset columns"):
        parse_constituents("Foo,Bar\n1,2\n")


def test_parse_empty_dataset():
    with pytest.raises(ValueError):
        parse_constituents("")


def test_parse_no_records():
    with pytest.raises(ValueError, match="no company records"):
        parse_constituents("Symbol,Security,GICS Sector\n")


# ---------- input validation ----------

@pytest.mark.parametrize("raw, expected", [
    ("10", 10.0),
    ("  1,250.50 ", 1250.5),
    ("$99.99", 99.99),
])
def test_parse_number_valid(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "abc", "0", "-5", "nan", "inf", "-inf", "1e99",
])
def test_parse_number_rejects_bad_input(raw):
    assert parse_number(raw) is None


@pytest.mark.parametrize("ticker", ["AAPL", "BRK.B", "BF-B", "A"])
def test_valid_ticker_formats(ticker):
    assert is_valid_ticker_format(ticker)


@pytest.mark.parametrize("ticker", ["", "AAPL$", "A B", "TOOLONGTICKER", "AA/PL"])
def test_invalid_ticker_formats(ticker):
    assert not is_valid_ticker_format(ticker)


# ---------- calculations ----------

def test_merge_position_average_cost():
    old = {"shares": 10.0, "buy_price": 100.0}
    merged = merge_position(old, 10.0, 200.0)
    assert merged["shares"] == 20.0
    assert merged["buy_price"] == 150.0


def test_calculate_position_gain():
    row = calculate_position(
        "AAPL", {"shares": 10.0, "buy_price": 100.0}, 150.0,
        "Manual entry", {"name": "Apple", "sector": "Tech"},
    )
    assert row["invested"] == 1000.0
    assert row["market_value"] == 1500.0
    assert row["gain_loss"] == 500.0
    assert row["gain_loss_pct"] == 50.0


def test_calculate_position_loss_and_missing_info():
    row = calculate_position(
        "XYZ", {"shares": 5.0, "buy_price": 100.0}, 80.0, "Manual entry", {}
    )
    assert row["gain_loss"] == -100.0
    assert row["gain_loss_pct"] == -20.0
    assert row["company"] == "N/A" and row["sector"] == "N/A"


def test_totals_empty_portfolio():
    totals = calculate_totals([])
    assert totals["invested"] == 0
    assert totals["gain_loss_pct"] == 0.0  # no division by zero


def test_totals_multiple_holdings():
    rows = [
        {"invested": 100.0, "market_value": 150.0},
        {"invested": 100.0, "market_value": 50.0},
    ]
    totals = calculate_totals(rows)
    assert totals["invested"] == 200.0
    assert totals["market_value"] == 200.0
    assert totals["gain_loss"] == 0.0
    assert totals["gain_loss_pct"] == 0.0


# ---------- formatting helpers ----------

def test_perf_color():
    assert perf_color(5) == C_GAIN
    assert perf_color(-5) == C_LOSS
    assert perf_color(0) == C_FLAT


def test_money_formats():
    assert money(1234.5) == "$1,234.50"
    assert signed_money(50) == "+$50.00"
    assert signed_money(-50) == "-$50.00"
    assert signed_money(0) == "$0.00"


def test_pct_text():
    assert pct_text(12.345) == "▲ +12.35%"
    assert pct_text(-1) == "▼ -1.00%"


# ---------- CSV export ----------

def sample_results():
    return [calculate_position(
        "AAPL", {"shares": 10.0, "buy_price": 100.0}, 150.0,
        "Manual entry", {"name": "Apple", "sector": "Tech"},
    )]


def test_build_summary_rows_has_total_row():
    results = sample_results()
    rows = build_summary_rows(results, calculate_totals(results))
    assert len(rows) == 2
    assert rows[-1]["ticker"] == "TOTAL"
    assert rows[-1]["gain_loss"] == 500.0


def test_write_rows_creates_header_then_appends(tmp_path):
    path = str(tmp_path / "summary.csv")
    results = sample_results()
    rows = build_summary_rows(results, calculate_totals(results))

    write_rows(rows, path)
    write_rows(rows, path)  # second run must not repeat the header

    with open(path, newline="", encoding="utf-8") as file:
        lines = list(csv.reader(file))

    assert lines[0] == portfolio.SUMMARY_FIELDS
    assert len(lines) == 1 + 2 * len(rows)


def test_validate_summary_rejects_wrong_headers(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("wrong,headers\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Incompatible headers"):
        validate_summary_file(str(path))


def test_validate_summary_accepts_missing_file(tmp_path):
    validate_summary_file(str(tmp_path / "does_not_exist.csv"))


# ---------- config ----------

def test_load_config_missing_file_uses_defaults(tmp_path):
    config = portfolio.load_config(str(tmp_path / "nope.json"))
    assert config["summary_fields"] == portfolio.DEFAULT_CONFIG["summary_fields"]


def test_load_config_overrides_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"max_input_value": 500}', encoding="utf-8")
    config = portfolio.load_config(str(path))
    assert config["max_input_value"] == 500
    assert "dataset_url" in config  # defaults still present


def test_load_config_bad_json_falls_back(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    config = portfolio.load_config(str(path))
    assert config == portfolio.DEFAULT_CONFIG


# ---------- dataset file ----------

def test_save_dataset_atomically(tmp_path):
    path = str(tmp_path / "constituents.csv")
    portfolio.save_dataset_atomically(VALID_DATASET, path)
    assert os.path.exists(path)
    assert not os.path.exists(path + ".tmp")


def test_real_dataset_if_present():
    path = os.path.join(portfolio.BASE_DIR, "constituents.csv")
    if not os.path.exists(path):
        pytest.skip("constituents.csv not in project folder")
    with open(path, encoding="utf-8-sig") as file:
        companies = parse_constituents(file.read())
    assert "AAPL" in companies
    assert len(companies) > 400