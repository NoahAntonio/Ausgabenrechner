# CLAUDE.md

## Project overview

A command-line tool that reads a CSV of bank transactions, classifies each one as
**tax-deductible**, **not deductible**, or **unclear (needs human review)**, then writes the
results to a Google Sheets file — categorized and summed per category. Transactions that
can't be confidently classified are flagged for manual review rather than guessed.

**Jurisdiction:** Austria (Einkommensteuer / Werbungskosten & Betriebsausgaben).
**Language:** Python.

## Tech stack

- Python 3.11+
- CSV parsing: standard `csv` module (input is `;`-delimited, see schema below)
- Google Sheets: write via the Sheets API (Google Sheets MCP server during development;
  `gspread` or `google-api-python-client` if wiring it up directly)
- Classification: rule-based first; optionally an LLM fallback for unclear cases
- Dependency management: use a virtualenv + `requirements.txt` (or `uv` if preferred)

## Build order

Work incrementally — one bounded task at a time, review the diff, then continue.

1. **CSV parsing + data model** — load the file into a typed `Transaction` model.
2. **Classification logic** — rules that map each transaction to a category + a
   deductible/not/unclear status.
3. **Google Sheets integration** — write classified results, grouped and summed by category.
4. **Flagging layer** — separate output (tab or column) for "needs review" items.

Do not jump ahead. Don't implement Sheets writing before parsing + classification are solid.

## CSV input schema

- Delimiter: `;`  — all fields quoted with `"`
- Encoding: assume UTF-8 (verify; Austrian bank exports are sometimes Latin-1 / cp1252)
- Decimal separator in `Betrag` is a **comma** (e.g. `-6,47`), not a period — parse accordingly.
- Date format in `Buchungsdatum`: `DD.MM.YYYY`.
- Negative `Betrag` = money out (an expense); positive = money in.

Columns:

| Column | Meaning | Notes |
|---|---|---|
| `Buchungsdatum` | Booking date | `DD.MM.YYYY` |
| `Partnername` | Merchant / counterparty name | primary signal for classification |
| `Partner IBAN` | Counterparty IBAN | often empty |
| `BIC/SWIFT` | | often empty |
| `Partner Kontonummer` | | |
| `Bankleitzahl` | Bank routing code | |
| `Betrag` | Amount | comma decimal, negative = expense |
| `Währung` | Currency | usually `EUR` |
| `Buchungs-Details` | Free-text detail | contains POS time + location, useful for time-based rules |
| `Buchungsreferenz` | Transaction reference | unique-ish id |
| `App` | Payment method | e.g. `Apple Pay` |
| `Empfänger-Überprüfung` | Recipient verification | often empty |
| `Diese IBAN ist registriert auf` | | often empty |

### Example rows

```
"Buchungsdatum";"Partnername";"Partner IBAN";"BIC/SWIFT";"Partner Kontonummer";"Bankleitzahl";"Betrag";"Währung";"Buchungs-Details";"Buchungsreferenz";"App";"Empfänger-Überprüfung";"Diese IBAN ist registriert auf"
"03.06.2026";"BIPA DANKT 0300338";"";"";"40100101600";"20111";"-6,47";"EUR";"POS 6,47 AT K5 02.06. 17:38 BIPA DANKT 0300338 WIEN 1030 040";"201112606032ALB-00EAJQU96LG8";"Apple Pay";"";""
"03.06.2026";"OFFERL SCHOTTENGASSE";"";"";"40100101600";"20111";"-11,60";"EUR";"POS 11,60 AT K5 02.06. 14:32 OFFERL SCHOTTENGASSE WIEN 1010 040";"201112606032ALB-00AFG6MNTQSS";"Apple Pay";"";""
```

Note: `Buchungs-Details` embeds the transaction time (e.g. `02.06. 17:38`). Extract it when a
category rule depends on time of day (see travel rule below).

## Categories

Each transaction should be assigned to exactly one category when deductible. Categories:

- **home office** — equipment, furniture, supplies used for working from home
- **groceries** — supermarket / food shopping
- **hospitalities** — restaurants, cafés, bars. **Excludes** clubs / discos.
- **travel** — transport. Includes Bolt/Uber rides **only when the ride time is between
  08:00 and 24:00** (use the time in `Buchungs-Details`). Rides outside that window are not
  travel.
- **phone** — mobile / telecom bills
- **software subs** — software subscriptions (SaaS, dev tools, cloud services)
- **work clothing** — clothing required for work

Anything that doesn't match a category, or matches ambiguously, → **unclear → flag for review**.

## Classification approach

- Start **rule-based**: keyword/merchant matching on `Partnername` and `Buchungs-Details`.
  Keep rules in a single editable config (e.g. a dict or YAML) so they're easy to extend.
- Be conservative. The cost of a wrong "deductible" is worse than a missed one — when in
  doubt, **flag rather than classify**. Better to over-flag than over-claim.
- Time-dependent rules (travel) must parse the time out of `Buchungs-Details`.
- Optionally add an LLM fallback for transactions the rules can't resolve, but always route
  its output through the "unclear → human review" path rather than auto-accepting.

## Important caveats

- **I am not a tax advisor and neither is this tool.** Deductibility under Austrian law
  depends on individual circumstances (employment vs. self-employment, business use share,
  documentation requirements, etc.). This tool produces a *first-pass categorization to
  support review*, not a filing-ready determination. The "flag for review" path exists
  precisely because many of these calls genuinely require human/professional judgment.
- Categories like groceries and work clothing are frequently **not** deductible for
  employees in Austria (private living costs / "Kosten der privaten Lebensführung").
  Keep the rules conservative and lean on flagging.

## Working conventions

- One focused task per request; review every diff before accepting.
- Use `/clear` between unrelated tasks to keep context clean.
- Keep functions small and testable; add a few unit tests around amount/date/time parsing
  (the comma-decimal and `DD.MM.` parsing are the easiest places to introduce bugs).
- Never commit the real transaction CSV or Google credentials. Add them to `.gitignore`.
