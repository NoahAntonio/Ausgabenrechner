import io
import textwrap
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from ausgaben.parser import (
    _extract_time,
    _parse_amount,
    _parse_date,
    load_csv,
)

# ---------------------------------------------------------------------------
# Unit tests for parsing helpers
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_basic(self):
        assert _parse_date("03.06.2026") == date(2026, 6, 3)

    def test_leading_zeros(self):
        assert _parse_date("01.01.2025") == date(2025, 1, 1)

    def test_end_of_year(self):
        assert _parse_date("31.12.2024") == date(2024, 12, 31)


class TestParseAmount:
    def test_negative_expense(self):
        assert _parse_amount("-6,47") == Decimal("-6.47")

    def test_positive_income(self):
        assert _parse_amount("1.234,56") == Decimal("1234.56")

    def test_zero(self):
        assert _parse_amount("0,00") == Decimal("0.00")

    def test_large_negative(self):
        assert _parse_amount("-11,60") == Decimal("-11.60")

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_amount("not-a-number")


class TestExtractTime:
    def test_embedded_short_date(self):
        details = "POS 6,47 AT K5 02.06. 17:38 BIPA DANKT 0300338 WIEN"
        assert _extract_time(details) == time(17, 38)

    def test_embedded_full_date(self):
        details = "POS 11,60 AT K5 02.06.2026 14:32 OFFERL SCHOTTENGASSE"
        assert _extract_time(details) == time(14, 32)

    def test_midnight(self):
        details = "POS AT K5 01.01. 00:00 SOME MERCHANT"
        assert _extract_time(details) == time(0, 0)

    def test_no_time_returns_none(self):
        assert _extract_time("DAUERAUFTRAG MIETE") is None

    def test_empty_string(self):
        assert _extract_time("") is None


# ---------------------------------------------------------------------------
# Integration test: round-trip through load_csv
# ---------------------------------------------------------------------------

_SAMPLE_CSV = textwrap.dedent("""\
    "Buchungsdatum";"Partnername";"Partner IBAN";"BIC/SWIFT";"Partner Kontonummer";"Bankleitzahl";"Betrag";"Währung";"Buchungs-Details";"Buchungsreferenz";"App";"Empfänger-Überprüfung";"Diese IBAN ist registriert auf"
    "03.06.2026";"BIPA DANKT 0300338";"";"";"40100101600";"20111";"-6,47";"EUR";"POS 6,47 AT K5 02.06. 17:38 BIPA DANKT 0300338 WIEN 1030 040";"201112606032ALB-00EAJQU96LG8";"Apple Pay";"";""\n\
    "03.06.2026";"OFFERL SCHOTTENGASSE";"";"";"40100101600";"20111";"-11,60";"EUR";"POS 11,60 AT K5 02.06. 14:32 OFFERL SCHOTTENGASSE WIEN 1010 040";"201112606032ALB-00AFG6MNTQSS";"Apple Pay";"";""\n\
""")


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    p = tmp_path / "transactions.csv"
    p.write_text(_SAMPLE_CSV, encoding="utf-8")
    return p


def test_load_csv_row_count(sample_csv):
    rows = load_csv(sample_csv)
    assert len(rows) == 2


def test_load_csv_first_row(sample_csv):
    tx = load_csv(sample_csv)[0]
    assert tx.buchungsdatum == date(2026, 6, 3)
    assert tx.partnername == "BIPA DANKT 0300338"
    assert tx.betrag == Decimal("-6.47")
    assert tx.waehrung == "EUR"
    assert tx.app == "Apple Pay"
    assert tx.buchungs_time == time(17, 38)


def test_load_csv_second_row(sample_csv):
    tx = load_csv(sample_csv)[1]
    assert tx.partnername == "OFFERL SCHOTTENGASSE"
    assert tx.betrag == Decimal("-11.60")
    assert tx.buchungs_time == time(14, 32)


def test_load_csv_frozen_dataclass(sample_csv):
    tx = load_csv(sample_csv)[0]
    with pytest.raises(Exception):
        tx.partnername = "mutated"  # type: ignore[misc]
