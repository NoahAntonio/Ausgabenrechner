"""
Write classification results to Google Sheets.

Auth: service account if GOOGLE_SERVICE_ACCOUNT_FILE is set in env,
      otherwise OAuth2 (opens browser on first run, caches token).

Sheet layout:
  Tab "Summary"        — category × status totals
  Tab "Deductible"     — transactions classified as deductible
  Tab "Needs Review"   — unclear transactions requiring human review
  Tab "Not Deductible" — transactions classified as not deductible
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Optional

import gspread
from gspread.exceptions import WorksheetNotFound

from .models import ClassificationResult, Transaction

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _open_sheet(sheet_id: str) -> gspread.Spreadsheet:
    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if sa_file:
        gc = gspread.service_account(filename=sa_file)
    else:
        gc = gspread.oauth()
    return gc.open_by_key(sheet_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_amount(amount: Decimal) -> str:
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _get_or_create_tab(
    spreadsheet: gspread.Spreadsheet, title: str, clear: bool = True
) -> gspread.Worksheet:
    try:
        ws = spreadsheet.worksheet(title)
        if clear:
            ws.clear()
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=2000, cols=10)
    return ws


def _batch_write(ws: gspread.Worksheet, rows: list[list]) -> None:
    if rows:
        ws.update(rows, "A1")


# ---------------------------------------------------------------------------
# Tab builders
# ---------------------------------------------------------------------------

_TX_HEADER = ["Date", "Merchant", "Amount (€)", "Category", "Status", "Note", "Source"]


def _tx_row(tx: Transaction, result: ClassificationResult) -> list:
    return [
        tx.buchungsdatum.strftime("%d.%m.%Y"),
        tx.partnername,
        _fmt_amount(tx.betrag),
        result.category or "",
        result.status,
        result.note,
        result.source,
    ]


def _write_deductible(
    spreadsheet: gspread.Spreadsheet,
    pairs: list[tuple[Transaction, ClassificationResult]],
) -> None:
    ws = _get_or_create_tab(spreadsheet, "Deductible")
    rows: list[list] = [_TX_HEADER]

    # Group by category, sort within each group by date
    from itertools import groupby

    sorted_pairs = sorted(pairs, key=lambda p: (p[1].category or "", p[0].buchungsdatum))
    current_cat: Optional[str] = None

    for tx, result in sorted_pairs:
        if result.category != current_cat:
            if current_cat is not None:
                rows.append([])  # blank separator between categories
            current_cat = result.category
            rows.append([f"── {(current_cat or '').upper()} ──"])
        rows.append(_tx_row(tx, result))

    # Category subtotals
    rows.append([])
    rows.append(["── SUBTOTALS ──"])
    rows.append(["Category", "Total (€)", "# Transactions"])
    by_cat: dict[str, list[Decimal]] = {}
    for tx, result in pairs:
        by_cat.setdefault(result.category or "", []).append(tx.betrag)
    for cat, amounts in sorted(by_cat.items()):
        rows.append([cat, _fmt_amount(sum(amounts)), len(amounts)])
    rows.append(["TOTAL", _fmt_amount(sum(tx.betrag for tx, _ in pairs)), len(pairs)])

    _batch_write(ws, rows)


def _write_not_deductible(
    spreadsheet: gspread.Spreadsheet,
    pairs: list[tuple[Transaction, ClassificationResult]],
) -> None:
    ws = _get_or_create_tab(spreadsheet, "Not Deductible")
    rows: list[list] = [_TX_HEADER]
    sorted_pairs = sorted(pairs, key=lambda p: (p[1].category or "", p[0].buchungsdatum))
    for tx, result in sorted_pairs:
        rows.append(_tx_row(tx, result))
    rows.append([])
    rows.append(["TOTAL", _fmt_amount(sum(tx.betrag for tx, _ in pairs)), len(pairs)])
    _batch_write(ws, rows)


def _write_needs_review(
    spreadsheet: gspread.Spreadsheet,
    pairs: list[tuple[Transaction, ClassificationResult]],
) -> None:
    ws = _get_or_create_tab(spreadsheet, "Needs Review")
    rows: list[list] = [_TX_HEADER]
    sorted_pairs = sorted(pairs, key=lambda p: (p[1].category or "zzz", p[0].buchungsdatum))
    for tx, result in sorted_pairs:
        rows.append(_tx_row(tx, result))
    rows.append([])
    rows.append(["TOTAL", _fmt_amount(sum(tx.betrag for tx, _ in pairs)), len(pairs)])
    _batch_write(ws, rows)


def _write_summary(
    spreadsheet: gspread.Spreadsheet,
    all_pairs: list[tuple[Transaction, ClassificationResult]],
) -> None:
    ws = _get_or_create_tab(spreadsheet, "Summary")

    # Aggregate by (category, status)
    totals: dict[tuple[str, str], Decimal] = {}
    counts: dict[tuple[str, str], int] = {}
    for tx, result in all_pairs:
        key = (result.category or "(none)", result.status)
        totals[key] = totals.get(key, Decimal("0")) + tx.betrag
        counts[key] = counts.get(key, 0) + 1

    statuses = ["deductible", "not_deductible", "unclear", "skip"]
    categories = sorted({cat for cat, _ in totals})

    header = ["Category"] + statuses + ["Total (€)", "# Transactions"]
    rows: list[list] = [header]

    grand_totals = {s: Decimal("0") for s in statuses}
    grand_count = 0

    for cat in categories:
        row: list = [cat]
        cat_total = Decimal("0")
        cat_count = 0
        for s in statuses:
            amt = totals.get((cat, s), Decimal("0"))
            cnt = counts.get((cat, s), 0)
            row.append(_fmt_amount(amt) if amt else "")
            grand_totals[s] += amt
            cat_total += amt
            cat_count += cnt
        row.extend([_fmt_amount(cat_total), cat_count])
        grand_count += cat_count
        rows.append(row)

    rows.append([])
    grand_row = ["GRAND TOTAL"] + [_fmt_amount(grand_totals[s]) for s in statuses]
    grand_row.extend([_fmt_amount(sum(grand_totals.values())), grand_count])
    rows.append(grand_row)

    _batch_write(ws, rows)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def write_to_sheets(
    sheet_id: str,
    pairs: list[tuple[Transaction, ClassificationResult]],
) -> str:
    """Write classified results to Google Sheets. Returns the spreadsheet URL."""
    spreadsheet = _open_sheet(sheet_id)

    expense_pairs = [(tx, r) for tx, r in pairs if r.status != "skip"]
    deductible = [(tx, r) for tx, r in expense_pairs if r.status == "deductible"]
    not_deductible = [(tx, r) for tx, r in expense_pairs if r.status == "not_deductible"]
    needs_review = [(tx, r) for tx, r in expense_pairs if r.status == "unclear"]

    _write_summary(spreadsheet, pairs)
    _write_deductible(spreadsheet, deductible)
    _write_needs_review(spreadsheet, needs_review)
    _write_not_deductible(spreadsheet, not_deductible)

    return spreadsheet.url
