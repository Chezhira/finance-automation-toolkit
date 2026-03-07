"""
Intercompany Reconciliation Engine
Acacia Group — Multi-Entity Consolidation
Author: Learning Python for Finance - Week 6

Problem: In a multi-entity group, intercompany transactions must be
eliminated on consolidation. But Entity A records a sale that Entity B
hasn't yet recorded as a purchase. Or amounts differ due to FX timing.
Or one side posts to the wrong intercompany account.

This engine:
1. Loads intercompany ledgers from all entities
2. Matches transactions by reference, amount, and counterparty
3. Identifies mismatches: missing mirror entries, amount differences, FX gaps
4. Produces an elimination schedule for group consolidation
5. Flags unreconciled items with aging and suggested action

Match types:
- MATCHED        : Both sides agree — safe to eliminate
- AMOUNT_DIFF    : Both sides posted but amounts differ (FX or error)
- MISSING_MIRROR : One side posted, other side has nothing
- TIMING         : One side posted, other side in next period

Output:
- Elimination schedule (group consolidation ready)
- Mismatch report with recommended actions
- Entity-level intercompany balances
- Aging of unreconciled items
"""

import pandas as pd
import numpy as np
from datetime import timedelta


# ─────────────────────────────────────────────
# 1. ENTITY CONFIG
# ─────────────────────────────────────────────

ENTITIES = ["Group HQ", "Entity A", "Entity B", "Entity C"]

# Intercompany account codes per entity
IC_ACCOUNTS = {
    "Group HQ": ["7001", "7002", "7003"],
    "Entity A":  ["7010", "7011"],
    "Entity B":  ["7020", "7021"],
    "Entity C":  ["7030"],
}

TOLERANCE = 100   # TZS — amount difference tolerance for FX rounding


# ─────────────────────────────────────────────
# 2. LOAD DATA
# ─────────────────────────────────────────────

def load_entity_ledger(filepath: str, entity: str) -> pd.DataFrame:
    """
    Load one entity's intercompany GL entries.
    Expected: date, entity, counterparty, account_code, ref,
              description, debit, credit, currency
    """
    df = pd.read_csv(filepath, parse_dates=["date"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df["entity"] = entity
    df["amount"] = df["debit"].fillna(0) - df["credit"].fillna(0)
    df["period"] = df["date"].dt.to_period("M").astype(str)
    return df


def load_all_entities(file_map: dict) -> pd.DataFrame:
    """
    Load and combine ledgers from all entities.
    file_map: { "Group HQ": "path/to/hq.csv", "Entity A": "path/to/ea.csv", ... }
    """
    frames = []
    for entity, path in file_map.items():
        df = load_entity_ledger(path, entity)
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    combined["row_id"] = range(1, len(combined) + 1)
    combined["matched"] = False
    combined["match_type"] = None
    combined["match_ref"] = None
    return combined


# ─────────────────────────────────────────────
# 3. MATCHING ENGINE
# ─────────────────────────────────────────────

def match_by_reference(gl: pd.DataFrame) -> pd.DataFrame:
    """
    Pass 1: Match on reference + counterparty pair.
    Entity A posts ref TML-IC-001 to Entity B.
    Entity B should have a mirror entry with same ref.
    """
    count = 0
    unmatched = gl[~gl["matched"]].copy()

    for i, row in unmatched.iterrows():
        if gl.at[i, "matched"]:
            continue
        # Find mirror: same ref, opposite entity/counterparty, opposite sign
        mirrors = gl[
            (~gl["matched"]) &
            (gl["ref"] == row["ref"]) &
            (gl["entity"] == row["counterparty"]) &
            (gl["counterparty"] == row["entity"]) &
            (gl["row_id"] != row["row_id"])
        ]
        if mirrors.empty:
            continue

        # Check amount — exact or within tolerance
        for j, mirror in mirrors.iterrows():
            amt_diff = abs(row["amount"] + mirror["amount"])  # should net to 0
            if amt_diff <= TOLERANCE:
                match_id = f"MATCH-{count+1:04d}"
                gl.at[i, "matched"] = True
                gl.at[i, "match_type"] = "MATCHED"
                gl.at[i, "match_ref"] = match_id
                gl.at[j, "matched"] = True
                gl.at[j, "match_type"] = "MATCHED"
                gl.at[j, "match_ref"] = match_id
                count += 1
                break
            elif amt_diff <= abs(row["amount"]) * 0.05:  # within 5% — FX diff
                match_id = f"FXDIFF-{count+1:04d}"
                gl.at[i, "matched"] = True
                gl.at[i, "match_type"] = "AMOUNT_DIFF"
                gl.at[i, "match_ref"] = match_id
                gl.at[j, "matched"] = True
                gl.at[j, "match_type"] = "AMOUNT_DIFF"
                gl.at[j, "match_ref"] = match_id
                count += 1
                break

    matched = (gl["match_type"] == "MATCHED").sum() // 2
    fx_diff = (gl["match_type"] == "AMOUNT_DIFF").sum() // 2
    print(f"  Pass 1 — Ref match (exact):    {matched} pairs")
    print(f"  Pass 1 — Ref match (amt diff): {fx_diff} pairs")
    return gl


def find_timing_differences(gl: pd.DataFrame, day_window: int = 35) -> pd.DataFrame:
    """
    Pass 2: Same ref exists in counterparty but in adjacent period.
    Common at month-end when one entity posts before cutoff, other after.
    """
    count = 0
    unmatched = gl[~gl["matched"]].copy()

    for i, row in unmatched.iterrows():
        if gl.at[i, "matched"]:
            continue
        window_min = row["date"] - timedelta(days=day_window)
        window_max = row["date"] + timedelta(days=day_window)

        mirrors = gl[
            (~gl["matched"]) &
            (gl["ref"] == row["ref"]) &
            (gl["entity"] == row["counterparty"]) &
            (gl["date"] >= window_min) &
            (gl["date"] <= window_max) &
            (gl["row_id"] != row["row_id"])
        ]
        if not mirrors.empty:
            j = mirrors.index[0]
            match_id = f"TIMING-{count+1:04d}"
            gl.at[i, "matched"] = True
            gl.at[i, "match_type"] = "TIMING"
            gl.at[i, "match_ref"] = match_id
            gl.at[j, "matched"] = True
            gl.at[j, "match_type"] = "TIMING"
            gl.at[j, "match_ref"] = match_id
            count += 1

    print(f"  Pass 2 — Timing differences:   {count} pairs")
    return gl


def flag_missing_mirrors(gl: pd.DataFrame) -> pd.DataFrame:
    """
    Pass 3: Remaining unmatched = missing mirror entries.
    These need action before consolidation can proceed.
    """
    unmatched = gl[~gl["matched"]]
    gl.loc[unmatched.index, "match_type"] = "MISSING_MIRROR"
    print(f"  Pass 3 — Missing mirrors:      {len(unmatched)} entries")
    return gl


# ─────────────────────────────────────────────
# 4. ELIMINATION SCHEDULE
# ─────────────────────────────────────────────

def build_elimination_schedule(gl: pd.DataFrame) -> pd.DataFrame:
    """
    Build consolidation elimination journal.
    Only MATCHED pairs are safe to eliminate.
    Returns one elimination entry per matched pair.
    """
    matched = gl[gl["match_type"] == "MATCHED"].copy()

    # One row per pair (take one side of each match)
    seen = set()
    elim_rows = []
    for _, row in matched.iterrows():
        if row["match_ref"] in seen:
            continue
        seen.add(row["match_ref"])
        # Get both sides
        pair = matched[matched["match_ref"] == row["match_ref"]]
        if len(pair) != 2:
            continue
        a, b = pair.iloc[0], pair.iloc[1]
        elim_rows.append({
            "elimination_ref":  row["match_ref"],
            "entity_dr":        a["entity"] if a["amount"] > 0 else b["entity"],
            "entity_cr":        b["entity"] if a["amount"] > 0 else a["entity"],
            "ic_ref":           row["ref"],
            "description":      a["description"],
            "amount":           abs(a["amount"]),
            "currency":         a.get("currency", "TZS"),
            "period":           a["period"],
            "status":           "ELIMINATE",
        })

    return pd.DataFrame(elim_rows)


# ─────────────────────────────────────────────
# 5. ENTITY BALANCE SUMMARY
# ─────────────────────────────────────────────

def entity_ic_balances(gl: pd.DataFrame) -> pd.DataFrame:
    """
    Summarise intercompany balances per entity pair.
    In a fully reconciled group, each pair should net to zero.
    """
    summary = (
        gl.groupby(["entity", "counterparty"])
        .agg(
            total_amount=("amount", "sum"),
            transaction_count=("row_id", "count"),
            matched_count=("matched", "sum"),
            unmatched_count=("matched", lambda x: (~x).sum()),
        )
        .reset_index()
    )
    summary["reconciled"] = summary["unmatched_count"] == 0
    summary["net_exposure"] = summary["total_amount"].abs()
    return summary


# ─────────────────────────────────────────────
# 6. AGING OF UNRECONCILED ITEMS
# ─────────────────────────────────────────────

def age_unreconciled(gl: pd.DataFrame,
                     report_date: pd.Timestamp = None) -> pd.DataFrame:
    """Age unreconciled items and assign recommended action."""
    if report_date is None:
        report_date = gl["date"].max()

    unmatched = gl[gl["match_type"] == "MISSING_MIRROR"].copy()
    if unmatched.empty:
        return pd.DataFrame()

    unmatched["age_days"] = (report_date - unmatched["date"]).dt.days
    unmatched["age_bucket"] = pd.cut(
        unmatched["age_days"],
        bins=[-1, 30, 60, 90, float("inf")],
        labels=["0–30d", "31–60d", "61–90d", "90d+"]
    )
    unmatched["recommended_action"] = unmatched["age_days"].apply(
        lambda x:
        "Request mirror entry from counterparty" if x <= 30
        else "Escalate to group finance — overdue" if x <= 60
        else "Journal adjustment required — contact CFO" if x <= 90
        else "URGENT: Pre-consolidation adjustment needed"
    )
    return unmatched[[
        "entity", "counterparty", "ref", "description",
        "amount", "date", "age_days", "age_bucket", "recommended_action"
    ]]


# ─────────────────────────────────────────────
# 7. REPORTING
# ─────────────────────────────────────────────

def build_ic_report(gl, elimination, balances, aging,
                    output_path="intercompany_recon.xlsx"):

    total = len(gl)
    matched_pairs  = (gl["match_type"] == "MATCHED").sum() // 2
    timing_pairs   = (gl["match_type"] == "TIMING").sum() // 2
    fx_pairs       = (gl["match_type"] == "AMOUNT_DIFF").sum() // 2
    missing        = (gl["match_type"] == "MISSING_MIRROR").sum()
    elim_value     = elimination["amount"].sum() if not elimination.empty else 0

    print(f"\n{'═'*52}")
    print(f"  INTERCOMPANY RECONCILIATION SUMMARY")
    print(f"  Acacia Group — Consolidation Period")
    print(f"{'═'*52}")
    print(f"  Total IC entries:        {total}")
    print(f"  Matched pairs:           {matched_pairs}")
    print(f"  Timing differences:      {timing_pairs}")
    print(f"  Amount differences:      {fx_pairs}")
    print(f"  Missing mirrors:         {missing}")
    print(f"  Elimination value:       TZS {elim_value:>12,.0f}")
    print(f"{'─'*52}")
    if missing > 0:
        print(f"  ⚠  {missing} entries cannot be eliminated — action required")
    else:
        print(f"  ✓  All entries reconciled — consolidation clear")
    print(f"{'═'*52}\n")

    summary_df = pd.DataFrame({
        "Metric": ["Total IC entries", "Matched pairs", "Timing differences",
                   "Amount differences", "Missing mirrors", "Elimination value (TZS)"],
        "Value":  [total, matched_pairs, timing_pairs,
                   fx_pairs, missing, f"{elim_value:,.0f}"]
    })

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        gl.to_excel(writer, sheet_name="Full IC Ledger", index=False)
        if not elimination.empty:
            elimination.to_excel(writer, sheet_name="Elimination Schedule", index=False)
        balances.to_excel(writer, sheet_name="Entity Balances", index=False)
        gl[gl["match_type"] == "AMOUNT_DIFF"].to_excel(
            writer, sheet_name="Amount Differences", index=False)
        gl[gl["match_type"] == "TIMING"].to_excel(
            writer, sheet_name="Timing Differences", index=False)
        if not aging.empty:
            aging.to_excel(writer, sheet_name="Unreconciled Aging", index=False)

    print(f"  Report saved → {output_path}")


# ─────────────────────────────────────────────
# 8. MAIN RUNNER
# ─────────────────────────────────────────────

def run_intercompany_recon(file_map: dict,
                           output_path="intercompany_recon.xlsx"):
    print(f"\n{'═'*52}")
    print(f"  INTERCOMPANY RECONCILIATION ENGINE")
    print(f"  Acacia Group — Multi-Entity")
    print(f"{'═'*52}\n")

    gl = load_all_entities(file_map)
    print(f"  Total IC entries loaded: {len(gl)}\n")
    print("  Running matching passes...")

    gl = match_by_reference(gl)
    gl = find_timing_differences(gl)
    gl = flag_missing_mirrors(gl)

    elimination = build_elimination_schedule(gl)
    balances    = entity_ic_balances(gl)
    aging       = age_unreconciled(gl)

    build_ic_report(gl, elimination, balances, aging, output_path)


# ─────────────────────────────────────────────
# 9. DEMO
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import os
    np.random.seed(5)
    BASE = pd.Timestamp("2025-01-01")

    def d(n): return BASE + pd.Timedelta(days=n)

    os.makedirs("/tmp/ic_demo", exist_ok=True)

    # ── Group HQ ledger ──────────────────────
    hq = pd.DataFrame([
        # Normal matched transactions
        {"date":d(2),  "counterparty":"Entity A","account_code":"7001","ref":"IC-2025-001","description":"Management fee charge",          "debit":500000,"credit":0,      "currency":"TZS"},
        {"date":d(5),  "counterparty":"Entity B","account_code":"7002","ref":"IC-2025-002","description":"Shared services recharge",        "debit":320000,"credit":0,      "currency":"TZS"},
        {"date":d(8),  "counterparty":"Entity C","account_code":"7003","ref":"IC-2025-003","description":"Carbon project advance",          "debit":750000,"credit":0,      "currency":"TZS"},
        {"date":d(12), "counterparty":"Entity A","account_code":"7001","ref":"IC-2025-004","description":"Loan interest receivable",         "debit":185000,"credit":0,      "currency":"TZS"},
        {"date":d(15), "counterparty":"Entity B","account_code":"7002","ref":"IC-2025-005","description":"Logistics recharge Q1",            "debit":210000,"credit":0,      "currency":"TZS"},
        # FX amount difference
        {"date":d(10), "counterparty":"Entity A","account_code":"7001","ref":"IC-2025-006","description":"USD export proceeds allocation",   "debit":0,     "credit":892000,"currency":"TZS"},
        # Timing difference (HQ posts Jan 29, Entity B posts Feb 2)
        {"date":d(28), "counterparty":"Entity B","account_code":"7002","ref":"IC-2025-007","description":"Year-end recharge accrual",        "debit":430000,"credit":0,      "currency":"TZS"},
        # Missing mirror — Entity C never posted
        {"date":d(18), "counterparty":"Entity C","account_code":"7003","ref":"IC-2025-008","description":"Equipment lease cross-charge",     "debit":275000,"credit":0,      "currency":"TZS"},
    ])

    # ── Entity A ledger ──────────────────────
    ea = pd.DataFrame([
        {"date":d(2),  "counterparty":"Group HQ","account_code":"7010","ref":"IC-2025-001","description":"Management fee payable",           "debit":0,     "credit":500000,"currency":"TZS"},
        {"date":d(12), "counterparty":"Group HQ","account_code":"7010","ref":"IC-2025-004","description":"Loan interest payable",             "debit":0,     "credit":185000,"currency":"TZS"},
        # FX diff — slightly different amount (revaluation)
        {"date":d(10), "counterparty":"Group HQ","account_code":"7011","ref":"IC-2025-006","description":"USD export proceeds — HQ share",   "debit":895500,"credit":0,      "currency":"TZS"},
        # Missing mirror — Entity A owes Entity B but hasn't posted
        {"date":d(7),  "counterparty":"Entity B","account_code":"7011","ref":"IC-2025-010","description":"Processing fee payable to Entity B","debit":0,    "credit":160000,"currency":"TZS"},
    ])

    # ── Entity B ledger ──────────────────────
    eb = pd.DataFrame([
        {"date":d(5),  "counterparty":"Group HQ","account_code":"7020","ref":"IC-2025-002","description":"Shared services payable",          "debit":0,     "credit":320000,"currency":"TZS"},
        {"date":d(15), "counterparty":"Group HQ","account_code":"7020","ref":"IC-2025-005","description":"Logistics recharge payable",        "debit":0,     "credit":210000,"currency":"TZS"},
        # Timing diff — posts Feb 2
        {"date":d(32), "counterparty":"Group HQ","account_code":"7021","ref":"IC-2025-007","description":"Year-end recharge payable",         "debit":0,     "credit":430000,"currency":"TZS"},
        # No mirror for IC-2025-010 from Entity A
    ])

    # ── Entity C ledger ──────────────────────
    ec = pd.DataFrame([
        {"date":d(8),  "counterparty":"Group HQ","account_code":"7030","ref":"IC-2025-003","description":"Carbon project funding received",   "debit":0,     "credit":750000,"currency":"TZS"},
        # IC-2025-008 (equipment lease) — Entity C never posted it
    ])

    for df in [hq, ea, eb, ec]:
        df["debit"]  = df["debit"].fillna(0)
        df["credit"] = df["credit"].fillna(0)

    hq.to_csv("/tmp/ic_demo/group_hq.csv",  index=False)
    ea.to_csv("/tmp/ic_demo/entity_a.csv",  index=False)
    eb.to_csv("/tmp/ic_demo/entity_b.csv",  index=False)
    ec.to_csv("/tmp/ic_demo/entity_c.csv",  index=False)

    run_intercompany_recon(
        file_map={
            "Group HQ": "/tmp/ic_demo/group_hq.csv",
            "Entity A":  "/tmp/ic_demo/entity_a.csv",
            "Entity B":  "/tmp/ic_demo/entity_b.csv",
            "Entity C":  "/tmp/ic_demo/entity_c.csv",
        },
        output_path="/tmp/intercompany_recon_demo.xlsx"
    )
