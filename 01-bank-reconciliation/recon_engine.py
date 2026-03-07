"""
Bank Reconciliation Matching Engine
Third Man Ltd - Multi-Currency Account Reconciliation
Author: Learning Python for Finance - Week 1

Matches Odoo GL export against bank statement using:
1. Exact matching  (amount + date + reference)
2. Near matching   (amount + date within ±3 days)
3. Amount-only     (amount match, wider date window)
4. Exception report for unmatched rows
"""

import pandas as pd
from datetime import timedelta


# ─────────────────────────────────────────────
# 1. LOAD DATA
# ─────────────────────────────────────────────

def load_odoo_export(filepath: str) -> pd.DataFrame:
    """
    Load Odoo GL export CSV.
    Expected columns: date, reference, description, debit, credit, currency
    """
    df = pd.read_csv(filepath, parse_dates=["date"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df["amount"] = df["debit"].fillna(0) - df["credit"].fillna(0)
    df["source"] = "odoo"
    df["matched"] = False
    df["match_type"] = None
    df["match_id"] = None
    return df


def load_bank_statement(filepath: str) -> pd.DataFrame:
    """
    Load bank statement CSV.
    Expected columns: date, reference, description, debit, credit
    """
    df = pd.read_csv(filepath, parse_dates=["date"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df["amount"] = df["debit"].fillna(0) - df["credit"].fillna(0)
    df["source"] = "bank"
    df["matched"] = False
    df["match_type"] = None
    df["match_id"] = None
    return df


# ─────────────────────────────────────────────
# 2. MATCHING LOGIC
# ─────────────────────────────────────────────

def exact_match(odoo: pd.DataFrame, bank: pd.DataFrame) -> tuple:
    """
    Pass 1: Exact match on amount + date + reference.
    Returns updated odoo and bank DataFrames.
    """
    match_count = 0

    for i, o_row in odoo[~odoo["matched"]].iterrows():
        candidates = bank[
            (~bank["matched"]) &
            (bank["amount"] == o_row["amount"]) &
            (bank["date"] == o_row["date"]) &
            (bank["reference"].str.strip().str.upper() ==
             str(o_row["reference"]).strip().upper())
        ]
        if not candidates.empty:
            j = candidates.index[0]
            match_id = f"EXACT-{match_count+1:04d}"
            odoo.at[i, "matched"] = True
            odoo.at[i, "match_type"] = "EXACT"
            odoo.at[i, "match_id"] = match_id
            bank.at[j, "matched"] = True
            bank.at[j, "match_type"] = "EXACT"
            bank.at[j, "match_id"] = match_id
            match_count += 1

    print(f"  Pass 1 - Exact matches:       {match_count}")
    return odoo, bank


def near_match(odoo: pd.DataFrame, bank: pd.DataFrame, day_tolerance: int = 3) -> tuple:
    """
    Pass 2: Near match — same amount, date within ±N days.
    """
    match_count = 0

    for i, o_row in odoo[~odoo["matched"]].iterrows():
        date_min = o_row["date"] - timedelta(days=day_tolerance)
        date_max = o_row["date"] + timedelta(days=day_tolerance)

        candidates = bank[
            (~bank["matched"]) &
            (bank["amount"] == o_row["amount"]) &
            (bank["date"] >= date_min) &
            (bank["date"] <= date_max)
        ]
        if not candidates.empty:
            # Pick closest date
            j = (candidates["date"] - o_row["date"]).abs().idxmin()
            match_id = f"NEAR-{match_count+1:04d}"
            odoo.at[i, "matched"] = True
            odoo.at[i, "match_type"] = f"NEAR (±{day_tolerance}d)"
            odoo.at[i, "match_id"] = match_id
            bank.at[j, "matched"] = True
            bank.at[j, "match_type"] = f"NEAR (±{day_tolerance}d)"
            bank.at[j, "match_id"] = match_id
            match_count += 1

    print(f"  Pass 2 - Near matches (±{day_tolerance}d):    {match_count}")
    return odoo, bank


def amount_only_match(odoo: pd.DataFrame, bank: pd.DataFrame, day_window: int = 10) -> tuple:
    """
    Pass 3: Amount-only match within a wider date window.
    Flags as REVIEW — human eye needed.
    """
    match_count = 0

    for i, o_row in odoo[~odoo["matched"]].iterrows():
        date_min = o_row["date"] - timedelta(days=day_window)
        date_max = o_row["date"] + timedelta(days=day_window)

        candidates = bank[
            (~bank["matched"]) &
            (bank["amount"] == o_row["amount"]) &
            (bank["date"] >= date_min) &
            (bank["date"] <= date_max)
        ]
        if not candidates.empty:
            j = (candidates["date"] - o_row["date"]).abs().idxmin()
            match_id = f"REVIEW-{match_count+1:04d}"
            odoo.at[i, "matched"] = True
            odoo.at[i, "match_type"] = f"AMOUNT-ONLY (±{day_window}d)"
            odoo.at[i, "match_id"] = match_id
            bank.at[j, "matched"] = True
            bank.at[j, "match_type"] = f"AMOUNT-ONLY (±{day_window}d)"
            bank.at[j, "match_id"] = match_id
            match_count += 1

    print(f"  Pass 3 - Amount-only matches: {match_count}")
    return odoo, bank


# ─────────────────────────────────────────────
# 3. REPORTING
# ─────────────────────────────────────────────

def build_report(odoo: pd.DataFrame, bank: pd.DataFrame, output_path: str = "recon_report.xlsx"):
    """
    Outputs a 4-tab Excel reconciliation report:
    - Summary
    - Matched (all passes)
    - Unmatched Odoo
    - Unmatched Bank
    """
    total_odoo = len(odoo)
    total_bank = len(bank)
    matched_odoo = odoo["matched"].sum()
    matched_bank = bank["matched"].sum()
    unmatched_odoo = total_odoo - matched_odoo
    unmatched_bank = total_bank - matched_bank

    match_rate_odoo = matched_odoo / total_odoo * 100 if total_odoo > 0 else 0
    match_rate_bank = matched_bank / total_bank * 100 if total_bank > 0 else 0

    # Summary table
    summary = pd.DataFrame({
        "Metric": [
            "Total Odoo GL lines",
            "Total Bank Statement lines",
            "Matched (Odoo side)",
            "Matched (Bank side)",
            "Unmatched Odoo",
            "Unmatched Bank",
            "Match Rate (Odoo)",
            "Match Rate (Bank)",
        ],
        "Value": [
            total_odoo,
            total_bank,
            matched_odoo,
            matched_bank,
            unmatched_odoo,
            unmatched_bank,
            f"{match_rate_odoo:.1f}%",
            f"{match_rate_bank:.1f}%",
        ]
    })

    # Matched pairs
    matched = odoo[odoo["matched"]].copy()

    # Unmatched
    unmatched_o = odoo[~odoo["matched"]].copy()
    unmatched_b = bank[~bank["matched"]].copy()

    print(f"\n{'─'*45}")
    print(f"  RECONCILIATION SUMMARY")
    print(f"{'─'*45}")
    print(f"  Odoo GL lines:      {total_odoo}")
    print(f"  Bank Stmt lines:    {total_bank}")
    print(f"  Match rate (Odoo):  {match_rate_odoo:.1f}%")
    print(f"  Match rate (Bank):  {match_rate_bank:.1f}%")
    print(f"  Unmatched Odoo:     {unmatched_odoo}")
    print(f"  Unmatched Bank:     {unmatched_bank}")
    print(f"{'─'*45}\n")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        matched.to_excel(writer, sheet_name="Matched", index=False)
        unmatched_o.to_excel(writer, sheet_name="Unmatched - Odoo", index=False)
        unmatched_b.to_excel(writer, sheet_name="Unmatched - Bank", index=False)

    print(f"  Report saved to: {output_path}\n")


# ─────────────────────────────────────────────
# 4. MAIN RUNNER
# ─────────────────────────────────────────────

def run_reconciliation(odoo_path: str, bank_path: str, output_path: str = "recon_report.xlsx"):
    print(f"\n{'═'*45}")
    print(f"  BANK RECONCILIATION ENGINE")
    print(f"  Third Man Ltd — Multi-Currency")
    print(f"{'═'*45}\n")

    print("  Loading data...")
    odoo = load_odoo_export(odoo_path)
    bank = load_bank_statement(bank_path)
    print(f"  Odoo rows: {len(odoo)} | Bank rows: {len(bank)}\n")

    print("  Running matching passes...")
    odoo, bank = exact_match(odoo, bank)
    odoo, bank = near_match(odoo, bank, day_tolerance=3)
    odoo, bank = amount_only_match(odoo, bank, day_window=10)

    build_report(odoo, bank, output_path)


# ─────────────────────────────────────────────
# 5. USAGE EXAMPLE (with sample data)
# ─────────────────────────────────────────────

if __name__ == "__main__":

    # Quick demo with synthetic data
    import numpy as np

    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=20, freq="B")
    amounts = np.random.choice([500, 1200, 3400, 750, 2100, 980], size=20)
    refs = [f"TML-{str(i).zfill(4)}" for i in range(1, 21)]

    # Simulate Odoo export
    odoo_demo = pd.DataFrame({
        "date": dates,
        "reference": refs,
        "description": [f"Payment {r}" for r in refs],
        "debit": amounts,
        "credit": 0,
        "currency": "USD"
    })
    odoo_demo.to_csv("/tmp/odoo_demo.csv", index=False)

    # Simulate bank statement (some exact, some shifted by 1-2 days, some missing)
    bank_dates = dates.copy().tolist()
    bank_dates[3] = bank_dates[3] + timedelta(days=2)   # near match
    bank_dates[7] = bank_dates[7] + timedelta(days=1)   # near match
    bank_refs = refs.copy()
    bank_refs[5] = "UNKNOWN"                             # ref mismatch
    bank_refs[10] = "UNKNOWN"                            # ref mismatch

    bank_demo = pd.DataFrame({
        "date": bank_dates[:18],           # 2 missing from bank
        "reference": bank_refs[:18],
        "description": [f"TXN {r}" for r in bank_refs[:18]],
        "debit": amounts[:18],
        "credit": 0,
    })
    bank_demo.to_csv("/tmp/bank_demo.csv", index=False)

    run_reconciliation("/tmp/odoo_demo.csv", "/tmp/bank_demo.csv", "/tmp/recon_demo.xlsx")
    print("  Demo complete. Check /tmp/recon_demo.xlsx")
