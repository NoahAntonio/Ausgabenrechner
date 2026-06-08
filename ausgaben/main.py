#!/usr/bin/env python3
"""
Usage:
    python -m ausgaben.main csv/all_transactions_2026.csv

Reads .env from the project root for ANTHROPIC_API_KEY and GOOGLE_SHEETS_ID.
For Google Sheets auth see .env.example.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .classifier import classify
from .models import ClassificationResult, Transaction
from .parser import load_csv
from .sheets import write_to_sheets


def _print_summary(pairs: list[tuple[Transaction, ClassificationResult]]) -> None:
    from collections import Counter
    from decimal import Decimal

    counts: Counter[str] = Counter()
    totals: dict[str, Decimal] = {}
    for tx, result in pairs:
        counts[result.status] += 1
        totals[result.status] = totals.get(result.status, Decimal("0")) + tx.betrag

    print("\n── Classification summary ──────────────────────────────")
    for status in ("deductible", "unclear", "not_deductible", "skip"):
        n = counts[status]
        total = totals.get(status, Decimal("0"))
        print(f"  {status:<16} {n:>4} transactions   {total:>10.2f} €")
    print()


def main(argv: list[str] | None = None) -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Classify bank transactions and write to Google Sheets."
    )
    parser.add_argument("csv_file", help="Path to the semicolon-delimited CSV export")
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Disable LLM fallback (faster, uses no API credits)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Classify and print summary but do not write to Sheets",
    )
    args = parser.parse_args(argv)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    sheet_id = os.getenv("GOOGLE_SHEETS_ID")

    if not args.dry_run and not sheet_id:
        sys.exit("Error: GOOGLE_SHEETS_ID not set in .env")
    if not args.no_llm and not api_key:
        print("Warning: ANTHROPIC_API_KEY not set — LLM fallback disabled.")
        args.no_llm = True

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        sys.exit(f"Error: CSV file not found: {csv_path}")

    print(f"Loading {csv_path} …")
    transactions = load_csv(csv_path)
    print(f"  {len(transactions)} transactions loaded.")

    print("Classifying …")
    use_llm = not args.no_llm
    pairs: list[tuple[Transaction, ClassificationResult]] = []
    for i, tx in enumerate(transactions, 1):
        result = classify(tx, use_llm=use_llm)
        pairs.append((tx, result))
        if use_llm and result.source == "llm":
            print(f"  [{i}/{len(transactions)}] LLM: {tx.partnername!r} → {result.category} / {result.status}")

    _print_summary(pairs)

    if args.dry_run:
        print("Dry run — not writing to Sheets.")
        return

    print(f"Writing to Google Sheets (ID: {sheet_id}) …")
    url = write_to_sheets(sheet_id, pairs)  # type: ignore[arg-type]
    print(f"Done! Open: {url}")


if __name__ == "__main__":
    main()
