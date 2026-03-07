# 03 · GL Forensics Engine

Five-layer anomaly detection for Odoo GL exports. Built after identifying duplicate transactions and uncleared suspense balances distorting subsidiary financials — and needing a systematic way to find them across hundreds of journal entries.

---

## The Problem

Manual GL review at month-end was inconsistent. Some months duplicates slipped through. Suspense accounts aged unnoticed. Reversal pairs were posted but never cleared. The problem wasn't competence — it was volume and the lack of a systematic check.

This engine runs in under a second and flags every category of anomaly with a full audit trail.

---

## Detection Layers

### Layer 1 — Exact Duplicates
Same date + account code + amount + narration. First occurrence kept; subsequent ones flagged `EXACT_DUPLICATE`. These are clean errors — usually double-posting or import reruns.

### Layer 2 — Near Duplicates
Same account + amount, dates within ±5 days, different narration. These are subtler — often the same transaction posted twice with slightly different descriptions or value dates. Flagged `NEAR_DUPLICATE`.

### Layer 3 — Reversal Pairs
Equal and opposite amounts on the same account within 10 days. Legitimate reversals exist (accrual reversals, correction entries) but every net-zero pair should be documented. Flagged `REVERSAL` on both lines.

### Layer 4 — Round Number Flags
Amounts ≥ TZS 10,000 in exact round thousands. Round numbers in large transactions indicate estimates rather than actuals — a common sign that a supporting document wasn't obtained. Flagged `ROUND_NUMBER` for verification.

### Layer 5 — Suspense Aging
Any account with "suspense", "clearing", "transit", or "unallocated" in its name is identified and aged from the transaction date. Items over 60 days are flagged `SUSPENSE_OLD`. Outputs an aging bucket summary: 0–30d, 31–60d, 61–90d, 91–180d, 180d+.

---

## Input Format

**Odoo GL export** (`odoo_gl_export.csv`):
```
date,account_code,account_name,narration,debit,credit,ref,journal,partner
2025-01-02,2001,Accounts Payable,Honey purchase - Kamau,,45000,JNL0001,MISC,Kamau
2025-01-02,2001,Accounts Payable,Honey purchase - Kamau,,45000,JNL0006,MISC,Kamau
```
*(The second row above would be caught as an exact duplicate)*

---

## Output

6-tab Excel workbook `gl_forensics.xlsx`:

| Tab | Contents |
|-----|----------|
| Summary | Total lines, flagged count, by flag type |
| All Flagged | Every anomaly in one view |
| Exact Duplicates | Layer 1 results |
| Near Duplicates | Layer 2 results |
| Suspense Aging | Aging bucket summary by account |
| Clean GL | Unflagged lines only |

---

## Usage

```python
from gl_forensics import run_gl_forensics

run_gl_forensics(
    gl_path="odoo_gl_export.csv",
    output_path="gl_forensics.xlsx"
)
```

---

## Tuning

| Parameter | Default | Notes |
|-----------|---------|-------|
| `day_window` (near dup) | 5 days | Widen for slow-posting environments |
| `day_window` (reversal) | 10 days | Month-end reversals may need 30+ |
| `threshold` (round num) | TZS 10,000 | Lower for tighter controls |
| `SUSPENSE_KEYWORDS` | see script | Add entity-specific account name patterns |

---

## Sample Output

```
════════════════════════════════════════════════
  GL FORENSICS ENGINE
  Third Man Ltd — Upendo Honey Group
════════════════════════════════════════════════

  GL rows loaded: 32

  Running detection layers...
  Exact duplicates found:        1
  Near duplicates found:         1
  Reversal pairs found:          1 pairs (2 rows)
  Round number flags:            2
  Suspense items found:          3

  ════════════════════════════════════════════════
  GL FORENSICS SUMMARY
  ════════════════════════════════════════════════
  Total GL lines:          32
  Flagged:                  7  (21.9%)
  Clean:                   25
    └─ EXACT_DUPLICATE      1
    └─ NEAR_DUPLICATE       1
    └─ REVERSAL             2
    └─ SUSPENSE_OLD         2
    └─ ROUND_NUMBER         2

  Report saved → gl_forensics.xlsx
```
