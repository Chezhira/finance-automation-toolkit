# 02 · Mpesa Fuzzy Matcher

Reconciles Mpesa bulk payment exports against a purchase ledger where supplier names are formatted inconsistently — a common problem in East African agricultural supply chains where vendor names are registered formally in the ERP but appear informally (or truncated) in mobile money records.

---

## The Problem

Third Man's Upendo Honey group pays 100+ beekeepers monthly via Mpesa bulk disbursement. The Mpesa file contains names as typed at payment time — abbreviated, without honorifics stripped, sometimes just initials. The Odoo purchase ledger has names as formally registered.

Manual matching was achieving **84.5%**. The unmatched 15.5% required hours of manual lookup every month.

---

## Root Cause Analysis

Three categories of mismatch:

| Type | Example (Ledger → Mpesa) | Cause |
|------|--------------------------|-------|
| Abbreviation | `John Mwangi Kamau` → `JOHN M KAMAU` | Middle name shortened |
| Suffix dropped | `Grace Wanjiku Ltd` → `Grace Wanjiku` | Business suffix omitted |
| Honorific dropped | `Fatuma Binti Salim` → `Fatuma Salim` | Binti / Mr / Mrs stripped |
| Wrong phone | Correct name, wrong registered number | Sim swap / dual SIM |

---

## How It Works

### Step 1 — Name Normalisation

Before any comparison, both names are passed through `normalise_name()`:

```
"Hassan Juma Enterprises"  →  "HASSAN JUMA"
"HASSAN JUMA"              →  "HASSAN JUMA"
```

Strips: Ltd, Limited, Co, Enterprises, Traders, Suppliers, Farms, Agro,
Mr, Mrs, Ms, Dr, Bwana, Bi, Binti (Swahili honorifics), punctuation, unicode accents.

### Step 2 — 3-Pass Matching

```
Pass 1: Exact phone + exact amount         → EXACT
Pass 2: Exact amount + fuzzy name ≥ 90    → FUZZY-HIGH
        Exact amount + fuzzy name 70–89   → FUZZY-MED (review)
Pass 3: Amount ±1% + fuzzy name ≥ 85     → AMOUNT-FUZZY (review)
```

Fuzzy scoring uses `difflib.SequenceMatcher` — no external dependencies.

### Step 3 — Exception Suggestions

For items that fall through all passes, instead of a blank exception row, the engine produces a ranked shortlist of the 3 closest candidates from the ledger with their similarity scores. The reviewer sees options, not a blank page.

---

## Input Format

**Mpesa bulk export** (`mpesa_bulk.csv`):
```
receipt_no,phone,name,amount,status,timestamp
MP0001,0712345601,JOHN M KAMAU,45000,SUCCESS,2025-03-01 10:23:00
MP0002,0712345602,Mary Akinyi,32000,SUCCESS,2025-03-01 10:24:00
```

**Purchase ledger** (`purchase_ledger.csv`):
```
vendor_id,vendor_name,phone,invoice_no,amount,invoice_date
V001,John Mwangi Kamau,0712345601,INV-V001,45000,2025-03-01
V002,Mary Akinyi Odhiambo,0712345602,INV-V002,32000,2025-03-01
```

---

## Output

6-tab Excel workbook `mpesa_recon.xlsx`:

| Tab | Contents |
|-----|----------|
| Summary | Match rate, counts by type |
| Mpesa - All | Full Mpesa file with match results |
| Matched | Matched payments with scores and types |
| Unmatched Mpesa | Payments with no ledger match |
| Unmatched Ledger | Ledger items with no payment found |
| Exception Suggestions | Ranked candidates for manual review |

---

## Usage

```python
from mpesa_matcher import run_mpesa_reconciliation

run_mpesa_reconciliation(
    mpesa_path="mpesa_bulk.csv",
    ledger_path="purchase_ledger.csv",
    output_path="mpesa_recon.xlsx"
)
```

---

## Tuning

| Parameter | Default | Notes |
|-----------|---------|-------|
| `high_threshold` | 90 | Lower to 85 if names are consistently heavily abbreviated |
| `med_threshold` | 70 | Items in 70–89 range go to FUZZY-MED for human review |
| `tolerance_pct` (Pass 3) | 1% | Amount tolerance — covers minor deductions/rounding |

---

## Sample Output

```
════════════════════════════════════════════════
  MPESA FUZZY MATCHING ENGINE
  Third Man Ltd — Beekeeper Honey Purchases
════════════════════════════════════════════════

  Mpesa rows:  10 | Ledger rows: 10

  Running matching passes...
  Pass 1 — Exact (phone+amount):      7
  Pass 2 — Fuzzy-High (≥90):          1
  Pass 2 — Fuzzy-Med  (70–89):        1
  Pass 3 — Amount±1% + fuzzy:         1

  ════════════════════════════════════════════════
  MPESA RECONCILIATION SUMMARY
  ════════════════════════════════════════════════
  Total Mpesa payments:    10
  Matched:                 10
  Unmatched:               0
  Match rate:              100.0%
```
