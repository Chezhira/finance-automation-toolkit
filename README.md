# Finance Automation Toolkit

**Python tools built to automate reconciliation, payroll validation, and audit workflows across a 6-entity manufacturing and agribusiness group in East Africa.**

Each tool in this repository replaced a manual Excel process — and was built to solve a real operational problem, not as a learning exercise.

---

## Disclaimer

All data in this repository is entirely synthetic and generated for demonstration purposes. No proprietary, confidential, or real business information is included. The tools were built independently to solve common finance automation problems.

---

## Background

I'm a Group Finance Lead overseeing finance across six entities spanning manufacturing, processing, agro commodity processing, and carbon projects in Tanzania. The work involves multi-currency operations, TRA compliance, ERP systems (Odoo 18), and group-level reporting for 135+ employees.

These scripts grew out of the day-to-day — reconciliation processes that were taking hours, payroll checks that were error-prone, VAT returns that kept generating audit queries. Python turned each of those into a reliable, repeatable process.

---

## Toolkit Overview

| # | Module | Problem Solved | Key Technique |
|---|--------|---------------|---------------|
| 01 | [Bank Reconciliation Engine](#01-bank-reconciliation-engine) | Odoo GL vs bank statement matching | 3-pass matching with date tolerance |
| 02 | [Mpesa Fuzzy Matcher](#02-mpesa-fuzzy-matcher) | Supplier bulk payment reconciliation | Name normalisation + fuzzy scoring |
| 03 | [GL Forensics](#03-gl-forensics) | Duplicate & anomaly detection in Odoo GL | Multi-layer flag engine |
| 04 | [Payroll Validator](#04-payroll-validator) | Tanzania statutory deductions validation | PAYE/NSSF/NHIF/WCF/SDL rules engine |
| 05 | [VAT Reconciliation](#05-vat-reconciliation) | TRA VAT return vs Odoo GL | Bill date vs posting date methodology |

---

## 01 Bank Reconciliation Engine

**`/01-bank-reconciliation/recon_engine.py`**

Matches an Odoo GL export against a bank statement using three passes:

1. **Exact match** — amount + date + reference
2. **Near match** — amount + date within ±3 days (catches value date differences)
3. **Amount-only** — amount within a ±10 day window (flagged for review)

Unmatched items on both sides are exported with a suggested-candidates list for the reviewer.

**Output:** 4-tab Excel report — Summary, Matched, Unmatched GL, Unmatched Bank

```bash
python recon_engine.py --odoo odoo_export.csv --bank bank_statement.csv
```

---

## 02 Mpesa Fuzzy Matcher

**`/02-mpesa-fuzzy-matcher/mpesa_matcher.py`**

Reconciles Mpesa bulk payment files against a purchase ledger where supplier names are inconsistently formatted — a common problem in East African agricultural supply chains.

**The problem:** "John Mwangi Kamau" in Odoo becomes "JOHN M KAMAU" in Mpesa. "Hassan Juma Enterprises" becomes "HASSAN JUMA". Manual matching was achieving ~84.5%.

**The solution:**
- Name normaliser strips noise (Ltd, Enterprises, Bwana, Binti, Farms, honorifics)
- 3-pass fuzzy matching: exact phone → fuzzy name → amount tolerance
- Exception report with top-3 candidate suggestions for unmatched items

**Result:** Match rate improved from 84.5% to 95%+

```bash
python mpesa_matcher.py --mpesa mpesa_bulk.csv --ledger purchase_ledger.csv
```

---

## 03 GL Forensics

**`/03-gl-forensics/gl_forensics.py`**

Five-layer anomaly detection engine for Odoo GL exports. Designed after identifying duplicate transactions and uncleared suspense balances distorting financials in a subsidiary.

**Detection layers:**
1. **Exact duplicates** — same date, account, amount, narration
2. **Near duplicates** — same account + amount, dates within ±5 days
3. **Reversal pairs** — equal and opposite postings netting to zero
4. **Round number flags** — large round amounts (fraud/estimate indicator)
5. **Suspense aging** — uncleared suspense/clearing items bucketted by age

**Output:** 6-tab Excel — Summary, All Flagged, Exact Dupes, Near Dupes, Suspense Aging, Clean GL

```bash
python gl_forensics.py --gl odoo_gl_export.csv
```

---

## 04 Payroll Validator

**`/04-payroll-validator/payroll_validator.py`**

Validates monthly payroll against Tanzania statutory deduction rules for 2024/25. Catches over/under deductions before submission to TRA and relevant authorities.

**Statutory rules implemented:**
- **PAYE** — progressive bands: 0% / 8% / 20% / 25% / 30% (TRA CAP 332)
- **NSSF** — 10% employee + 10% employer, capped at TZS 8,000/month each
- **NHIF** — graduated bands by gross salary
- **WCF** — 0.5% of gross (employer)
- **SDL** — 4.5% of gross (employer)

**Bonus layer:** Month-on-month gross variance flags salary spikes >20% — catches ghost employees, mid-month additions, and data entry errors.

```bash
python payroll_validator.py --payroll march_payroll.csv
```

---

## 05 VAT Reconciliation

**`/05-vat-reconciliation/vat_reconciliation.py`**

Reconciles Odoo VAT control account GL against TRA VAT return submissions. Designed specifically to address the bill-date vs posting-date methodology mismatch that generates false variances.

**The core insight:** Odoo posts VAT on the invoice posting date. TRA returns are filed on the tax point (bill) date. A January invoice posted in February appears as a variance in both periods — unless you strip it out first.

**Engine flow:**
1. Separate cross-period items (bill date ≠ posting period)
2. Compute timing-adjusted Odoo VAT per period
3. Compare adjusted figures to TRA declared amounts
4. Classify residuals as genuine variances vs timing differences
5. Run health checks: rate mismatches, zero-base anomalies, stale cross-period items

**Output:** Audit-ready schedule with cross-period adjustments shown — TRA-defensible.

```bash
python vat_reconciliation.py --odoo odoo_vat_gl.csv --tra tra_returns.csv
```

---

## Running the demos

Each module includes a self-contained demo in its `if __name__ == "__main__"` block using synthetic data that mirrors real operational scenarios:

```bash
cd 01-bank-reconciliation && python recon_engine.py
cd 02-mpesa-fuzzy-matcher && python mpesa_matcher.py
cd 03-gl-forensics        && python gl_forensics.py
cd 04-payroll-validator   && python payroll_validator.py
cd 05-vat-reconciliation  && python vat_reconciliation.py
```

---

## Requirements

```
pandas>=2.0
openpyxl>=3.1
numpy>=1.24
```

```bash
pip install pandas openpyxl numpy
```

No external fuzzy-matching libraries required — the name normaliser and similarity scorer use Python's standard library only (`difflib`, `re`, `unicodedata`).

---

## About

**Zahidah Murira** · Group Finance Lead · CMA · CGBA · CFA Level I

Multi-entity finance operations, ERP systems (Odoo 18, Sage Pastel), Tanzania statutory compliance, and building the tools that make month-end close faster and audit-ready.

[LinkedIn](https://linkedin.com/in/zahidahmurira) · ziddmurira@gmail.com
