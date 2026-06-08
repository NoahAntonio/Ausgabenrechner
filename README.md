# AusgabenRechner

A command-line tool that reads a CSV of Austrian bank transactions, classifies each one for tax deductibility, and writes the results to a Google Sheets file — categorised and summed per category.

**Jurisdiction:** Austria (Einkommensteuer / Werbungskosten & Betriebsausgaben)

> **Disclaimer:** This tool produces a first-pass categorisation to support review, not a filing-ready tax determination. Always verify with a tax advisor.

## What it does

- Loads a semicolon-delimited CSV export (UTF-8 or UTF-16) from an Austrian bank
- Classifies each transaction as **deductible**, **not deductible**, or **unclear (needs review)** using rule-based matching across ~165 known merchants
- Falls back to Claude Haiku (LLM) for unrecognised merchants — always routed to "needs review"
- Writes four tabs to Google Sheets: **Summary**, **Deductible**, **Needs Review**, **Not Deductible**

## Categories

| Category | Examples |
|---|---|
| `home_office` | Electronics, equipment, books for work |
| `groceries` | Supermarkets, drugstores (not deductible for employees) |
| `hospitalities` | Restaurants, cafés, bars (excluding clubs/discos) |
| `travel` | Trains, flights, Bolt/Uber (08:00–24:00 only) |
| `phone` | Mobile phone bills |
| `software_subs` | SaaS tools, cloud services |
| `work_clothing` | Work-specific clothing |

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure `.env`

Copy `.env.example` to `.env` and fill in your values:

```
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_SHEETS_ID=your-spreadsheet-id
# Optional: GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
```

### 3. Google Sheets auth

**Option A — OAuth2 (personal use):**
1. Google Cloud Console → APIs & Services → Credentials → Create OAuth 2.0 Desktop Client
2. Download the JSON and save to `~/.config/gspread/credentials.json`
3. Add your Google account as a test user under OAuth consent screen → Test users
4. First run opens a browser for authorisation; token is cached after that

**Option B — Service account:**
1. Create a service account in Google Cloud Console, download the JSON key
2. Share your spreadsheet with the service account email
3. Set `GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json` in `.env`

## Usage

```bash
# Full run — classify and write to Sheets
python -m ausgaben.main csv/transactions.csv

# Dry run — classify only, no Sheets write
python -m ausgaben.main csv/transactions.csv --dry-run

# Skip LLM fallback (faster, no API credits used)
python -m ausgaben.main csv/transactions.csv --no-llm
```

## CSV format

Semicolon-delimited, all fields quoted. Supports UTF-8 and UTF-16 (common in Austrian bank exports). Decimal separator in `Betrag` is a comma (e.g. `-6,47`). Date format: `DD.MM.YYYY`.

## Running tests

```bash
pytest tests/
```
