# 05 · VAT Reconciliation Engine

Reconciles Odoo VAT control account GL against TRA VAT return submissions — with specific handling for the bill-date vs posting-date methodology mismatch that generates false variances in period-by-period comparisons.

---

## The Problem

Odoo posts VAT based on the invoice **posting date**. TRA VAT returns are filed based on the **tax point date** (bill date). These are often the same — but not always.

When a January invoice is posted in February:
- Odoo records the VAT in **February**
- TRA expects it declared in **January**

This creates a phantom variance in both periods — February looks over-declared, January looks under-declared. Neither is a real error. But they're buried alongside genuine errors (wrong tax rates, omitted invoices, duplicated entries).

This engine separates the two.

---

## Methodology

```
For each period:

  Odoo VAT (by posting date)
  − Cross-period timing items
  ─────────────────────────────
  = Adjusted Odoo VAT
  − TRA Declared VAT
  ─────────────────────────────
  = Net unexplained variance

  If net variance ≤ TZS 500 → RECONCILED
  If net variance > TZS 500 → GENUINE VARIANCE → investigate
```

---

## Health Checks

In addition to the period reconciliation, the engine runs four data quality checks:

| Check | What It Catches |
|-------|----------------|
| VAT Rate Mismatch | Lines where VAT ≠ tax base × 18% |
| Zero Base / Non-zero VAT | VAT posted with no tax base — coding error |
| Stale Cross-Period Items | Bill date > 2 periods from posting date — TRA exposure |
| Duplicate Invoice References | Same invoice ref appearing more than once |

---

## Input Format

**Odoo VAT GL** (`odoo_vat_gl.csv`):
```
bill_date,posting_date,invoice_ref,partner,vat_type,tax_base,vat_amount
2025-01-28,2025-02-03,INV-CROSS-001,EU Client A,OUTPUT,3000000,540000
2025-02-10,2025-02-10,INV-ERR-001,Domestic Buyer,OUTPUT,1000000,80000
```

**TRA VAT return** (`tra_returns.csv`):
```
period,vat_type,declared_base,declared_vat
2025-01,OUTPUT,4950000,891000
2025-01,INPUT,550000,99000
```

---

## Output

6-tab Excel workbook `vat_reconciliation.xlsx`:

| Tab | Contents |
|-----|----------|
| Summary | Net liability, cross-period count, genuine variances |
| Period Reconciliation | Odoo vs TRA by period and VAT type |
| Timing Differences | All cross-period items with timing note |
| Genuine Variances | Residuals after timing adjustment |
| Health Checks | Data quality findings with severity |
| Audit Schedule | TRA-ready reconciliation with adjustments shown |

---

## Usage

```python
from vat_reconciliation import run_vat_reconciliation

run_vat_reconciliation(
    odoo_path="odoo_vat_gl.csv",
    tra_path="tra_returns.csv",
    output_path="vat_reconciliation.xlsx"
)
```

---

## The Audit Schedule Tab

The Audit Schedule is designed to be handed directly to a TRA auditor or internal reviewer. It shows:

```
Period  | Type   | Odoo VAT | Less Cross-Period | Adjusted | Declared | Variance | Note
2025-01 | OUTPUT | 891,000  | (540,000)         | 351,000  | 351,000  |        0 | Reconciled
2025-02 | OUTPUT | 576,000  | +540,000          | 576,000  | 576,000  |        0 | Reconciled
```

The cross-period adjustment flows between periods, netting to zero across the full reconciliation window. This is the document that defends a TRA query without requiring the auditor to understand your ERP posting behaviour.

---

## Sample Output

```
════════════════════════════════════════════════════
  VAT RECONCILIATION SUMMARY
  Third Man Ltd — TRA Returns
════════════════════════════════════════════════════
  Total Output VAT (Odoo):  TZS    4,012,920
  Total Input VAT (Odoo):   TZS      782,640
  Net VAT Liability:        TZS    3,230,280
  Cross-period items:       2
  Genuine variances:        1

  Health Checks:
  ✗ [HIGH  ] VAT Rate Mismatch: 1 line(s) — VAT ≠ base × 18%
  ⚠ [INFO  ] Cross-Period Items: 2 invoice(s) span two periods
  ⚠ [MEDIUM] Unexplained Variances: 1 period/type combo after timing adj
```
