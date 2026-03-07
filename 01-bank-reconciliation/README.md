# 01 · Bank Reconciliation Engine

Matches an Odoo GL export against a bank statement using a 3-pass algorithm that handles the real-world messiness of value date differences, reference format mismatches, and cross-system timing gaps.

---

## The Problem

Manual bank reconciliation across multi-currency Group Bank accounts was a recurring monthly task. The Odoo GL and bank statement rarely matched cleanly — value dates shifted by 1–3 days, references were truncated or reformatted by the bank, and unmatched items piled up requiring manual triage.

The process needed to be systematic, auditable, and fast.

---

## How It Works

```
Odoo GL Export          Bank Statement
     │                       │
     └──────────┬────────────┘
                │
         Pass 1: EXACT
         amount + date + reference
                │
         Pass 2: NEAR
         amount + date ±3 days
                │
         Pass 3: AMOUNT-ONLY
         amount, date ±10 days → flagged REVIEW
                │
         Exception report
         (unmatched both sides)
```

**Pass 1 — Exact** catches the majority of items cleanly.

**Pass 2 — Near** catches value date differences. When a payment is made on Jan 31 but the bank credits it Feb 1, Pass 1 misses it. Pass 2 finds it.

**Pass 3 — Amount Only** is the safety net. Items matched here are flagged `REVIEW` — they need a human eye but are better than leaving them unmatched.

---

## Input Format

**Odoo GL export** (`odoo_export.csv`):
```
date,reference,description,debit,credit,currency
2025-01-02,Group HQ-0001,Supplier Payment,1200,,USD
2025-01-05,Group HQ-0002,Export Receipt,,3400,USD
```

**Bank statement** (`bank_statement.csv`):
```
date,reference,description,debit,credit
2025-01-02,Group HQ-0001,CR Group HQ-0001,1200,
2025-01-06,Group HQ-0002,CR EXPORT EU,,3400
```

---

## Output

4-tab Excel workbook `recon_report.xlsx`:

| Tab | Contents |
|-----|----------|
| Summary | Match rate, counts by pass type |
| Matched | All matched pairs with match type and ID |
| Unmatched - Odoo | GL items with no bank counterpart |
| Unmatched - Bank | Bank items with no GL counterpart |

---

## Usage

```python
from recon_engine import run_reconciliation

run_reconciliation(
    odoo_path="odoo_export.csv",
    bank_path="bank_statement.csv",
    output_path="recon_report.xlsx"
)
```

Or run the built-in demo:
```bash
python recon_engine.py
```

---

## Tuning

| Parameter | Default | When to change |
|-----------|---------|----------------|
| `day_tolerance` (Pass 2) | 3 days | Increase if your bank has longer value date delays |
| `day_window` (Pass 3) | 10 days | Widen for slower-moving accounts |

---

## Sample Output

```
═══════════════════════════════════════════════
  BANK RECONCILIATION ENGINE
  Acacia Group — Multi-Currency
═══════════════════════════════════════════════

  Loading data...
  Odoo rows: 20 | Bank rows: 18

  Running matching passes...
  Pass 1 - Exact matches:       14
  Pass 2 - Near matches (±3d):   2
  Pass 3 - Amount-only matches:  1

  ─────────────────────────────────────────────
  RECONCILIATION SUMMARY
  ─────────────────────────────────────────────
  Odoo GL lines:      20
  Bank Stmt lines:    18
  Match rate (Odoo):  85.0%
  Match rate (Bank):  94.4%
  Unmatched Odoo:     3
  Unmatched Bank:     1
  ─────────────────────────────────────────────

  Report saved to: recon_report.xlsx
```
