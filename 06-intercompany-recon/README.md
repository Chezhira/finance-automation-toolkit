# 06 · Intercompany Reconciliation Engine

Matches intercompany transactions across all group entities and produces a consolidation-ready elimination schedule. Built for multi-entity groups where one side posts and the other doesn't — or amounts differ due to FX timing.

---

## The Problem

In a group with 4+ entities, intercompany transactions must net to zero before consolidation. But Entity A records a management fee receivable that Entity B hasn't yet posted as payable. Or the amounts differ by TZS 3,500 because of a mid-month FX revaluation. Or a year-end accrual is posted January 28 by HQ and February 2 by the subsidiary.

Manual IC reconciliation is one of the most error-prone parts of month-end close. This engine automates it.

---

## How It Works

```
All Entity GL Exports (4 entities)
           │
    Pass 1: REF + COUNTERPARTY MATCH
    Same reference, mirrored entity/counterparty pair
    Amount within tolerance → MATCHED (safe to eliminate)
    Amount within 5% → AMOUNT_DIFF (FX review needed)
           │
    Pass 2: TIMING DIFFERENCE
    Same reference, date within ±35 days
    Cross-period posting → TIMING (review before eliminating)
           │
    Pass 3: FLAG MISSING MIRRORS
    No counterpart found → MISSING_MIRROR (action required)
           │
    Elimination Schedule + Mismatch Report
```

---

## Match Types

| Type | Meaning | Action |
|------|---------|--------|
| `MATCHED` | Both sides agree — nets to zero | Eliminate in consolidation |
| `AMOUNT_DIFF` | Both sides posted, amounts differ ≤5% | Review FX rate — adjust smaller side |
| `TIMING` | Same ref, different period (≤35 days) | Check cutoff — may need accrual |
| `MISSING_MIRROR` | One side only — no counterpart found | Request posting from counterparty |

---

## Input Format

One CSV per entity (`group_hq.csv`, `entity_a.csv`, etc.):
```
date,counterparty,account_code,ref,description,debit,credit,currency
2025-01-02,Entity A,7001,IC-2025-001,Management fee charge,500000,,TZS
2025-01-05,Entity B,7002,IC-2025-002,Shared services recharge,320000,,TZS
```

**Key column:** `ref` — this is your matching key. Use a consistent IC reference format across all entities (e.g. `IC-YYYY-NNN`).

---

## Output

7-tab Excel workbook `intercompany_recon.xlsx`:

| Tab | Contents |
|-----|----------|
| Summary | Matched pairs, missing mirrors, elimination value |
| Full IC Ledger | All entries with match type and ID |
| Elimination Schedule | Consolidation journal — matched pairs only |
| Entity Balances | IC balance per entity pair |
| Amount Differences | FX/rounding mismatches for review |
| Timing Differences | Cross-period entries |
| Unreconciled Aging | Missing mirrors with age and recommended action |

---

## Usage

```python
from intercompany_recon import run_intercompany_recon

run_intercompany_recon(
    file_map={
        "Group HQ": "sample_data/group_hq.csv",
        "Entity A":  "sample_data/entity_a.csv",
        "Entity B":  "sample_data/entity_b.csv",
        "Entity C":  "sample_data/entity_c.csv",
    },
    output_path="intercompany_recon.xlsx"
)
```

---

## Sample Data

Ready-to-run synthetic data is in `sample_data/` (group_hq.csv + entity_a.csv + entity_b.csv + entity_c.csv).

```bash
cd 06-intercompany-recon
python intercompany_recon.py
```

---

## Sample Output

```
════════════════════════════════════════════════════
  INTERCOMPANY RECONCILIATION ENGINE
  Acacia Group — Multi-Entity
════════════════════════════════════════════════════

  Total IC entries loaded: 16

  Running matching passes...
  Pass 1 — Ref match (exact):    5 pairs
  Pass 1 — Ref match (amt diff): 1 pairs
  Pass 2 — Timing differences:   1 pairs
  Pass 3 — Missing mirrors:      3 entries

  ════════════════════════════════════════════════════
  INTERCOMPANY RECONCILIATION SUMMARY
  Acacia Group — Consolidation Period
  ════════════════════════════════════════════════════
  Total IC entries:        16
  Matched pairs:           5
  Timing differences:      1
  Amount differences:      1
  Missing mirrors:         3
  Elimination value:       TZS    1,965,000
  ────────────────────────────────────────────────────
  ⚠  3 entries cannot be eliminated — action required
```
