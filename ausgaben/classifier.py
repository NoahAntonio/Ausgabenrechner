"""
Rule-based classifier for Austrian tax deductibility.
Rules are conservative: when in doubt → unclear → flag for human review.

Jurisdiction: Austria (Einkommensteuer / Werbungskosten & Betriebsausgaben).
This is a first-pass tool, not a tax determination.
"""
from __future__ import annotations

import os
import re
from datetime import time
from typing import Optional

import anthropic

from .models import ClassificationResult, Transaction

# ---------------------------------------------------------------------------
# Rule tables — edit these to extend coverage
# ---------------------------------------------------------------------------

# Transactions that should be silently skipped (income, ATM, bank system, investments)
_SKIP_RULES: list[tuple[str, list[str]]] = [
    ("atm_withdrawal",  ["SB-AUSZAHLUNG", "AUTOMAT "]),
    ("bank_system",     ["ABSCHLUSSBUCHUNG", "KONTOFÜHRUNG", "PLUG-IN ENTGELT",
                         "INFORMATION GEM", "GUTHABEN AUF"]),
    ("investment",      ["TRADE REPUBLIC", "COINBASE", "REVOLUT**"]),
    # Self-transfer
    ("self_transfer",   ["NOAH ANTONIO SEYHAN"]),
    # Personal transfers with known names
    ("personal_transfer", ["PAUL LIND", "JAN MICHAEL DRUBA", "HANNA REBEKA TRYBULA",
                            "JONA GENC", "SEBASTIAN STÜRZER", "MICHAEL PETERS",
                            "NERIK HAVASOV", "MAG. KEMAL SEYHAN", "EDUARD HRUBESCH"]),
    # Payment processors without further identifying info
    ("photo_booth",     ["BLITZKABINE"]),
]

# (category, status, note, patterns_ANY_of)
# First matching rule wins. Patterns checked case-insensitively against
# Partnername + " " + Buchungs-Details.
_CATEGORY_RULES: list[tuple[str, str, str, list[str]]] = [

    # ── PHONE ──────────────────────────────────────────────────────────────
    (
        "phone", "deductible",
        "Mobile phone bill — proportional work-use share is deductible (Werbungskosten).",
        ["T-MOBILE AUSTRIA", "MAGENTA MOBIL"],
    ),

    # ── SOFTWARE SUBS (deductible) ─────────────────────────────────────────
    (
        "software_subs", "deductible",
        "AI productivity tool — deductible if used for work.",
        ["CLAUDE.AI"],
    ),

    # ── SOFTWARE SUBS (not deductible — personal entertainment/games) ──────
    (
        "software_subs", "not_deductible",
        "Personal entertainment subscription — not deductible.",
        ["GOOGLE YOUTUBEPREMIUM", "CHESS.COM", "ONLYFANS", "OF LONDON"],
    ),

    # ── SOFTWARE SUBS (unclear — could be work) ────────────────────────────
    (
        "software_subs", "unclear",
        "Software/cloud sub — deductible only if primarily used for work. "
        "Document work-use share.",
        ["PROTON* PROTON", "GOOGLE ONE"],
    ),

    # ── GROCERIES (not deductible for employees) ───────────────────────────
    (
        "groceries", "not_deductible",
        "Supermarket/grocery purchase — private living cost, not deductible "
        "for employees (§ 20 EStG).",
        ["HOFER DANKT", "BILLA DANKT", "SPAR DANKT", "LIDL DANKT",
         "INTERSPAR DANKT", "INTERSPAR ", "EDEKA ", "REWE ", "PENNY ",
         "KAUFLAND", "FENEBERG"],
    ),

    # ── PERSONAL CARE / DRUGSTORE (not deductible) ─────────────────────────
    (
        "groceries", "not_deductible",
        "Drugstore/personal care — private living cost, not deductible.",
        ["BIPA DANKT", "DM DROGERIE", "DM-FIL."],
    ),

    # ── PHARMACY (not deductible as Werbungskosten) ─────────────────────────
    (
        "groceries", "not_deductible",
        "Pharmacy — health expenses are not deductible as Werbungskosten "
        "(may qualify as außergewöhnliche Belastung separately).",
        ["APOTHEKE", "APO ZUM"],
    ),

    # ── FITNESS / SPORTS (not deductible) ──────────────────────────────────
    (
        "groceries", "not_deductible",
        "Fitness/sports — private lifestyle expense, not deductible.",
        ["RSG GROUP OESTERREICH", "S.C. HAKOAH", "HAKOAH"],
    ),

    # ── WELLNESS / SPA (not deductible) ────────────────────────────────────
    (
        "groceries", "not_deductible",
        "Wellness/spa — private leisure expense, not deductible.",
        ["ALBTHERME", "THERMEN & BADEWELT", "SOLEMAR", "AQUASOL",
         "BADENER BAEDER"],
    ),

    # ── CLUBS / DISCOS (excluded from hospitality per rules) ───────────────
    (
        "hospitalities", "not_deductible",
        "Club/disco — excluded from deductible hospitality per project rules.",
        ["GRELLE FORELLE", "VOLKSGARTEN", "X CLUB", " B72 ", "B72\n",
         "CLUB PRATERSTRASSE", "DAS WERK WIEN", "FLUCC", "TANZMOT"],
    ),

    # ── PERSONAL FLOWERS / GIFTS ───────────────────────────────────────────
    (
        "groceries", "not_deductible",
        "Flowers/personal gift — not deductible.",
        ["BLUMEN BAJER"],
    ),

    # ── PERSONAL ACCOMMODATION (Airbnb — personal travel) ──────────────────
    (
        "travel", "not_deductible",
        "Private accommodation — not deductible unless demonstrably work travel.",
        ["AIRBNB"],
    ),

    # ── LOTTERY / GAMES ────────────────────────────────────────────────────
    (
        "groceries", "not_deductible",
        "Lottery/game — not deductible.",
        ["QUICK-PICK"],
    ),

    # ── ENTERTAINMENT TICKETS ──────────────────────────────────────────────
    (
        "hospitalities", "not_deductible",
        "Event ticket — private entertainment, not deductible.",
        ["WWW OETICKET COM", "OETICKET"],
    ),

    # ── TRAVEL — always (trains, flights, ridesharing) ─────────────────────
    (
        "travel", "unclear",
        "Transport cost — deductible only if work travel. Confirm business purpose "
        "and document destination/reason.",
        ["DB VERTRIEB", "WESTBAHN.AT", "OEBB PERSONENVERKEHR", "OEBB ",
         "TRAINLINE", "AUSTRIAN.COM", "MYTRIP", "BLABLACAR", "KOLEJE",
         "UBER *LIME"],
    ),

    # ── TRAVEL — fuel (unclear: work vs private) ───────────────────────────
    (
        "travel", "unclear",
        "Fuel — deductible only if used for business travel. Document trip purpose.",
        ["TANKENERGIE", "TANKSTELLE", "JET-TANKSTELLE", "ARAL ", "ESSO ",
         "AGIP ", "AVIA TANKSTELLE", "AVIA AUTOMATEN", "AVIA-XPRESS"],
    ),

    # ── HOME OFFICE / EQUIPMENT (unclear work use) ─────────────────────────
    (
        "home_office", "unclear",
        "Electronics/equipment — deductible if used ≥ 50% for work. "
        "Document work-use share.",
        ["MEDIA MARKT", "HANDYSTORE.AT"],
    ),

    # ── BOOKS (unclear — could be professional literature) ─────────────────
    (
        "home_office", "unclear",
        "Bookstore — deductible if professional/work literature. "
        "Document title and work relevance.",
        ["THALIA"],
    ),

    # ── WORK CLOTHING (unclear for Birkenstock) ────────────────────────────
    (
        "work_clothing", "unclear",
        "Footwear — deductible only if required specifically for work "
        "(Berufskleidung). Ordinary shoes are not deductible.",
        ["BIRKENSTOCK"],
    ),

    # ── HOSPITALITIES — restaurants, cafés, bars ──────────────────────────
    # (broad patterns — must come AFTER club exclusions above)
    (
        "hospitalities", "unclear",
        "Restaurant/café/bar — deductible only if a documented business "
        "meeting (Bewirtungsaufwand, § 20 Abs 1 Z 3 EStG, 50% rule). "
        "Note the attendees and business purpose.",
        [
            "OFFERL ", "RESTAURANT ", "CAFE ", "CAFÉ ", "GASTHAUS",
            "BISTRO", "HEURIGER", "BAECKEREI", "BACKEREI", "BÄCKEREI",
            "ANKERBROT", "WOLT", "FOODORA", "MEIN GARTEN GASTRONOM",
            "COCKTAIL BISTR", "AMERLINGBEISL", "BIBIM", "EL BURRO",
            "ALL REIS", "KRAZY KITCHEN", "BROTH 3RS", "BROSL",
            "MADO GMBH", "CAFE BAR", "I BELLISSIMI", "RESTAURANT CHAMPION",
            "NYX*ANKER", "PORGY & BESS", "ANDREW'S", "FASSHALLE",
            "ARENA 01 KEBAB", "MCDONALDS", "MCDONALD S", "ZUR WANDERLUST",
            "TANTE-M", "MEYER FEINKOST", "HEUGARTA", "SELINAS CAFE",
            "LS JULES", "KIOSK AM ROTTACH", "HEIDERSBACHER MUEHLE",
            "DITSCH", "SCHWITZERS BISTRO", "SCHWITZERS HOTEL",
            "HOTEL AM BRILLANTENG", "BELVEDERE MARKET",
            "SUMUP  *ART CAFE", "SUMUP  *CAPHE", "SUMUP  *COCKTAIL",
            "SUMUP  *HARAN KEBAP", "SUMUP  *MANJA LEE",
            "KIAN ", "FELDHASE", "KRAWALL BAR",
        ],
    ),
]

# ---------------------------------------------------------------------------
# Bolt time-of-day rule (travel only 08:00–24:00)
# ---------------------------------------------------------------------------

def _classify_bolt(tx: Transaction) -> ClassificationResult:
    t = tx.buchungs_time
    if t is None:
        return ClassificationResult(
            category="travel", status="unclear",
            note="Bolt ride — no time extracted from Buchungs-Details; "
                 "deductible only for rides 08:00–24:00 and work purpose.",
            source="rule",
        )
    in_window = time(8, 0) <= t <= time(23, 59)
    if in_window:
        return ClassificationResult(
            category="travel", status="unclear",
            note=f"Bolt ride at {t.strftime('%H:%M')} (within 08:00–24:00 window). "
                 "Deductible only if work travel — confirm business purpose.",
            source="rule",
        )
    return ClassificationResult(
        category="travel", status="not_deductible",
        note=f"Bolt ride at {t.strftime('%H:%M')} — outside 08:00–24:00 window, "
             "not classifiable as work travel.",
        source="rule",
    )


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an Austrian tax assistant. Classify a bank transaction into exactly one of these
categories: home_office, groceries, hospitalities, travel, phone, software_subs,
work_clothing, or OTHER.

Also suggest whether it is: deductible, not_deductible, or unclear (needs review).

Respond in this exact format (no extra text):
CATEGORY: <category>
STATUS: <status>
NOTE: <one-sentence explanation>
"""

_FALLBACK_NOTE = "(LLM suggestion — flagged for human review)"

_llm_client: Optional[anthropic.Anthropic] = None


def _get_llm_client() -> Optional[anthropic.Anthropic]:
    global _llm_client
    if _llm_client is None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if key:
            _llm_client = anthropic.Anthropic(api_key=key)
    return _llm_client


def _llm_classify(tx: Transaction) -> ClassificationResult:
    client = _get_llm_client()
    if client is None:
        return ClassificationResult(
            category=None, status="unclear",
            note="No ANTHROPIC_API_KEY set — could not auto-classify.",
            source="rule",
        )

    user_msg = (
        f"Partnername: {tx.partnername}\n"
        f"Buchungs-Details: {tx.buchungs_details}\n"
        f"Betrag: {tx.betrag} {tx.waehrung}\n"
        f"Date: {tx.buchungsdatum}"
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
    except Exception as exc:  # noqa: BLE001
        return ClassificationResult(
            category=None, status="unclear",
            note=f"LLM call failed: {exc}",
            source="llm",
        )

    category = None
    status = "unclear"
    note = _FALLBACK_NOTE

    for line in raw.splitlines():
        if line.startswith("CATEGORY:"):
            val = line.split(":", 1)[1].strip().lower()
            if val != "other":
                category = val
        elif line.startswith("STATUS:"):
            val = line.split(":", 1)[1].strip().lower()
            if val in ("deductible", "not_deductible", "unclear"):
                status = val
        elif line.startswith("NOTE:"):
            note = line.split(":", 1)[1].strip() + " " + _FALLBACK_NOTE

    # LLM output always routes through "unclear" (never auto-accepted)
    return ClassificationResult(
        category=category, status="unclear", note=note, source="llm",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _haystack(tx: Transaction) -> str:
    return (tx.partnername + " " + tx.buchungs_details).upper()


def classify(tx: Transaction, use_llm: bool = True) -> ClassificationResult:
    """Classify a single transaction. Income is auto-skipped."""

    # Skip zero-amount entries (bank info lines)
    if tx.betrag == 0:
        return ClassificationResult(
            category=None, status="skip",
            note="Zero-amount bank information entry.", source="rule",
        )

    # Income → skip
    if tx.betrag > 0:
        return ClassificationResult(
            category=None, status="skip",
            note="Income entry — not an expense.", source="rule",
        )

    hay = _haystack(tx)

    # Skip rules (ATM, investments, personal transfers, etc.)
    for reason, patterns in _SKIP_RULES:
        if any(p.upper() in hay for p in patterns):
            return ClassificationResult(
                category=None, status="skip",
                note=f"Skipped: {reason}.", source="rule",
            )

    # Bolt time-of-day rule
    if re.search(r"BOLT\.EU", hay):
        return _classify_bolt(tx)

    # Category rules
    for category, status, note, patterns in _CATEGORY_RULES:
        if any(p.upper() in hay for p in patterns):
            return ClassificationResult(
                category=category, status=status, note=note, source="rule",
            )

    # LLM fallback for unmatched transactions
    if use_llm:
        return _llm_classify(tx)

    return ClassificationResult(
        category=None, status="unclear",
        note="No rule matched — needs manual review.", source="rule",
    )
