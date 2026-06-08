from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class Transaction:
    buchungsdatum: date
    partnername: str
    partner_iban: str
    bic_swift: str
    partner_kontonummer: str
    bankleitzahl: str
    betrag: Decimal        # negative = expense, positive = income
    waehrung: str
    buchungs_details: str
    buchungsreferenz: str
    app: str
    empfaenger_pruefung: str
    iban_registriert_auf: str

    # Extracted from buchungs_details when present (e.g. "02.06. 17:38")
    buchungs_time: Optional[time] = None


@dataclass
class ClassificationResult:
    category: Optional[str]   # None for income/skipped entries
    status: str                # "deductible" | "not_deductible" | "unclear" | "skip"
    note: str
    source: str                # "rule" | "llm"
