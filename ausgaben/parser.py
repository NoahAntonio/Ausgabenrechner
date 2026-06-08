import csv
import re
from datetime import date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

from .models import Transaction

# "02.06. 17:38" or "02.06.2026 17:38" embedded in Buchungs-Details
_TIME_PATTERN = re.compile(r'\d{2}\.\d{2}\.(?:\d{4})?\s+(\d{2}:\d{2})')

_COLUMNS = [
    "Buchungsdatum",
    "Partnername",
    "Partner IBAN",
    "BIC/SWIFT",
    "Partner Kontonummer",
    "Bankleitzahl",
    "Betrag",
    "Währung",
    "Buchungs-Details",
    "Buchungsreferenz",
    "App",
    "Empfänger-Überprüfung",
    "Diese IBAN ist registriert auf",
]


def _parse_date(value: str) -> date:
    # DD.MM.YYYY
    day, month, year = value.strip().split(".")
    return date(int(year), int(month), int(day))


def _parse_amount(value: str) -> Decimal:
    # Austrian comma decimal: "-6,47" → Decimal("-6.47")
    normalized = value.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse amount: {value!r}") from exc


def _extract_time(details: str) -> Optional[time]:
    match = _TIME_PATTERN.search(details)
    if not match:
        return None
    hh, mm = match.group(1).split(":")
    return time(int(hh), int(mm))


def _detect_encoding(path: Path) -> str:
    """Try UTF-16 (BOM-detected) first; then UTF-8 variants; fall back to cp1252."""
    for enc in ("utf-16", "utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            path.read_text(encoding=enc)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "utf-8"


def load_csv(path: str | Path) -> List[Transaction]:
    path = Path(path)
    encoding = _detect_encoding(path)

    transactions: List[Transaction] = []
    with path.open(encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";", quotechar='"')
        for row_num, row in enumerate(reader, start=2):  # 2 = first data row
            missing = [c for c in _COLUMNS if c not in row]
            if missing:
                raise ValueError(
                    f"Row {row_num}: missing columns {missing}. "
                    f"Found: {list(row.keys())}"
                )
            details = row["Buchungs-Details"]
            transactions.append(
                Transaction(
                    buchungsdatum=_parse_date(row["Buchungsdatum"]),
                    partnername=row["Partnername"].strip(),
                    partner_iban=row["Partner IBAN"].strip(),
                    bic_swift=row["BIC/SWIFT"].strip(),
                    partner_kontonummer=row["Partner Kontonummer"].strip(),
                    bankleitzahl=row["Bankleitzahl"].strip(),
                    betrag=_parse_amount(row["Betrag"]),
                    waehrung=row["Währung"].strip(),
                    buchungs_details=details.strip(),
                    buchungsreferenz=row["Buchungsreferenz"].strip(),
                    app=row["App"].strip(),
                    empfaenger_pruefung=row["Empfänger-Überprüfung"].strip(),
                    iban_registriert_auf=row["Diese IBAN ist registriert auf"].strip(),
                    buchungs_time=_extract_time(details),
                )
            )
    return transactions
