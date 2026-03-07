"""
GL Forensics & Duplicate Detection Engine
Third Man Ltd — Upendo Honey Group
Author: Learning Python for Finance - Week 3

Problem: GL has duplicate transactions, uncleared suspense balances,
and ghost entries that distort financials.

Detection layers:
1. Exact duplicates     — same amount, date, account, narration
2. Near duplicates      — same amount + account, dates within ±N days
3. Suspense aging       — uncleared suspense items by age bucket
4. Round-number flags   — suspiciously round amounts (fraud indicator)
5. Reversed entries     — equal and opposite postings (netting to zero)
"""

import pandas as pd
import numpy as np
from datetime import timedelta


# ─────────────────────────────────────────────
# 1. LOAD DATA
# ─────────────────────────────────────────────

def load_gl(filepath: str) -> pd.DataFrame:
    """
    Load Odoo GL export CSV.
    Expected columns: date, account_code, account_name, narration,
                      debit, credit, ref, journal, partner
    """
    df = pd.read_csv(filepath, parse_dates=["date"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df["amount"] = df["debit"].fillna(0) - df["credit"].fillna(0)
    df["row_id"] = range(1, len(df) + 1)
    df["flag"] = None
    df["flag_detail"] = None
    return df


# ─────────────────────────────────────────────
# 2. EXACT DUPLICATE DETECTION
# ─────────────────────────────────────────────

def find_exact_duplicates(gl: pd.DataFrame) -> pd.DataFrame:
    """
    Exact duplicates: same date + account + amount + narration.
    First occurrence is kept; subsequent ones flagged.
    """
    key_cols = ["date", "account_code", "amount", "narration"]
    dupes = gl.duplicated(subset=key_cols, keep="first")
    gl.loc[dupes, "flag"] = "EXACT_DUPLICATE"
    gl.loc[dupes, "flag_detail"] = "Same date/account/amount/narration as earlier row"

    count = dupes.sum()
    print(f"  Exact duplicates found:        {count}")
    return gl


# ─────────────────────────────────────────────
# 3. NEAR DUPLICATE DETECTION
# ─────────────────────────────────────────────

def find_near_duplicates(gl: pd.DataFrame, day_window: int = 5) -> pd.DataFrame:
    """
    Near duplicates: same account + amount, dates within ±N days.
    Skips rows already flagged as exact duplicates.
    """
    clean = gl[gl["flag"].isna()].copy()
    flagged_ids = []

    for i, row in clean.iterrows():
        if row["row_id"] in flagged_ids:
            continue
        window_min = row["date"] - timedelta(days=day_window)
        window_max = row["date"] + timedelta(days=day_window)
        candidates = clean[
            (clean["account_code"] == row["account_code"]) &
            (clean["amount"] == row["amount"]) &
            (clean["date"] >= window_min) &
            (clean["date"] <= window_max) &
            (clean["row_id"] != row["row_id"]) &
            (~clean["row_id"].isin(flagged_ids))
        ]
        if not candidates.empty:
            for j in candidates.index:
                flagged_ids.append(clean.at[j, "row_id"])
                gl.at[j, "flag"] = "NEAR_DUPLICATE"
                gl.at[j, "flag_detail"] = (
                    f"Same account/amount as row {row['row_id']}, "
                    f"date diff ≤{day_window}d"
                )

    count = len(flagged_ids)
    print(f"  Near duplicates found:         {count}")
    return gl


# ─────────────────────────────────────────────
# 4. REVERSED ENTRY DETECTION
# ─────────────────────────────────────────────

def find_reversals(gl: pd.DataFrame, day_window: int = 10) -> pd.DataFrame:
    """
    Reversed entries: a debit and credit of equal absolute amount
    on the same account within a date window — nets to zero.
    Legitimate reversals exist but should be reviewed.
    """
    clean = gl[gl["flag"].isna()].copy()
    flagged_pairs = []
    count = 0

    for i, row in clean.iterrows():
        if i in flagged_pairs:
            continue
        window_min = row["date"] - timedelta(days=day_window)
        window_max = row["date"] + timedelta(days=day_window)
        # Look for the mirror entry (opposite sign, same absolute amount, same account)
        mirror = clean[
            (clean["account_code"] == row["account_code"]) &
            (clean["amount"] == -row["amount"]) &
            (clean["date"] >= window_min) &
            (clean["date"] <= window_max) &
            (clean.index != i) &
            (~clean.index.isin(flagged_pairs))
        ]
        if not mirror.empty:
            j = mirror.index[0]
            flagged_pairs.extend([i, j])
            gl.at[i, "flag"] = "REVERSAL"
            gl.at[i, "flag_detail"] = f"Mirrors row {gl.at[j, 'row_id']} — net zero pair"
            gl.at[j, "flag"] = "REVERSAL"
            gl.at[j, "flag_detail"] = f"Mirrors row {gl.at[i, 'row_id']} — net zero pair"
            count += 2

    print(f"  Reversal pairs found:          {count // 2} pairs ({count} rows)")
    return gl


# ─────────────────────────────────────────────
# 5. SUSPENSE ACCOUNT AGING
# ─────────────────────────────────────────────

SUSPENSE_KEYWORDS = ["suspense", "clearing", "transit", "unallocated", "control"]

def analyze_suspense(gl: pd.DataFrame, report_date: pd.Timestamp = None) -> pd.DataFrame:
    """
    Identify uncleared suspense/clearing balances and bucket by age.
    Returns a suspense aging summary DataFrame.
    """
    if report_date is None:
        report_date = gl["date"].max()

    suspense_mask = gl["account_name"].str.lower().str.contains(
        "|".join(SUSPENSE_KEYWORDS), na=False
    )
    suspense = gl[suspense_mask].copy()

    if suspense.empty:
        print(f"  Suspense items found:          0")
        return pd.DataFrame()

    suspense["age_days"] = (report_date - suspense["date"]).dt.days
    suspense["age_bucket"] = pd.cut(
        suspense["age_days"],
        bins=[-1, 30, 60, 90, 180, float("inf")],
        labels=["0–30d", "31–60d", "61–90d", "91–180d", "180d+"]
    )

    # Flag old uncleared items
    gl.loc[suspense[suspense["age_days"] > 60].index, "flag"] = gl.loc[
        suspense[suspense["age_days"] > 60].index, "flag"
    ].fillna("SUSPENSE_OLD")
    gl.loc[suspense[suspense["age_days"] > 60].index, "flag_detail"] = (
        suspense[suspense["age_days"] > 60]["age_days"].astype(str) + " days uncleared"
    )

    aging_summary = (
        suspense.groupby("age_bucket", observed=True)
        .agg(count=("amount", "count"), balance=("amount", "sum"))
        .reset_index()
    )
    print(f"  Suspense items found:          {len(suspense)}")
    return aging_summary


# ─────────────────────────────────────────────
# 6. ROUND NUMBER FLAG (FRAUD INDICATOR)
# ─────────────────────────────────────────────

def flag_round_numbers(gl: pd.DataFrame, threshold: float = 10000) -> pd.DataFrame:
    """
    Flag unusually round numbers above a threshold.
    Round numbers in large transactions can indicate estimates or fraud.
    """
    mask = (
        (gl["amount"].abs() >= threshold) &
        (gl["amount"].abs() % 1000 == 0) &
        (gl["flag"].isna())
    )
    gl.loc[mask, "flag"] = "ROUND_NUMBER"
    gl.loc[mask, "flag_detail"] = "Round amount ≥ threshold — verify supporting doc"
    count = mask.sum()
    print(f"  Round number flags:            {count}")
    return gl


# ─────────────────────────────────────────────
# 7. REPORTING
# ─────────────────────────────────────────────

def build_report(gl: pd.DataFrame, suspense_aging: pd.DataFrame,
                 output_path: str = "gl_forensics.xlsx"):
    """
    Excel report with 6 tabs:
    Summary | All Flagged | Exact Dupes | Near Dupes | Suspense Aging | Clean GL
    """
    total = len(gl)
    flagged = gl["flag"].notna().sum()
    clean = total - flagged

    print(f"\n{'═'*48}")
    print(f"  GL FORENSICS SUMMARY — Upendo Honey")
    print(f"{'═'*48}")
    print(f"  Total GL lines:          {total}")
    print(f"  Flagged:                 {flagged}  ({flagged/total*100:.1f}%)")
    print(f"  Clean:                   {clean}")
    for flag_type in ["EXACT_DUPLICATE","NEAR_DUPLICATE","REVERSAL","SUSPENSE_OLD","ROUND_NUMBER"]:
        n = (gl["flag"] == flag_type).sum()
        if n:
            print(f"    └─ {flag_type:<20} {n}")
    print(f"{'═'*48}\n")

    summary = pd.DataFrame({
        "Metric": ["Total GL lines", "Flagged", "Clean",
                   "Exact Duplicates", "Near Duplicates", "Reversals",
                   "Suspense (old)", "Round Numbers"],
        "Count": [
            total, flagged, clean,
            (gl["flag"]=="EXACT_DUPLICATE").sum(),
            (gl["flag"]=="NEAR_DUPLICATE").sum(),
            (gl["flag"]=="REVERSAL").sum(),
            (gl["flag"]=="SUSPENSE_OLD").sum(),
            (gl["flag"]=="ROUND_NUMBER").sum(),
        ]
    })

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        gl[gl["flag"].notna()].to_excel(writer, sheet_name="All Flagged", index=False)
        gl[gl["flag"]=="EXACT_DUPLICATE"].to_excel(writer, sheet_name="Exact Duplicates", index=False)
        gl[gl["flag"]=="NEAR_DUPLICATE"].to_excel(writer, sheet_name="Near Duplicates", index=False)
        if not suspense_aging.empty:
            suspense_aging.to_excel(writer, sheet_name="Suspense Aging", index=False)
        gl[gl["flag"].isna()].to_excel(writer, sheet_name="Clean GL", index=False)

    print(f"  Report saved → {output_path}")


# ─────────────────────────────────────────────
# 8. MAIN RUNNER
# ─────────────────────────────────────────────

def run_gl_forensics(gl_path: str, output_path: str = "gl_forensics.xlsx"):
    print(f"\n{'═'*48}")
    print(f"  GL FORENSICS ENGINE")
    print(f"  Third Man Ltd — Upendo Honey Group")
    print(f"{'═'*48}\n")

    gl = load_gl(gl_path)
    print(f"  GL rows loaded: {len(gl)}\n")
    print("  Running detection layers...")

    gl = find_exact_duplicates(gl)
    gl = find_near_duplicates(gl)
    gl = find_reversals(gl)
    gl = flag_round_numbers(gl)
    suspense_aging = analyze_suspense(gl)

    build_report(gl, suspense_aging, output_path)


# ─────────────────────────────────────────────
# 9. DEMO WITH SYNTHETIC UPENDO HONEY DATA
# ─────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(3)
    base = pd.Timestamp("2025-01-01")

    accounts = [
        ("1001", "Cash - NBC USD"),
        ("2001", "Accounts Payable"),
        ("3001", "Honey Sales Revenue"),
        ("4001", "Suspense Clearing Account"),
        ("5001", "Processing Costs"),
        ("6001", "Beekeeper Payables Suspense"),
    ]

    rows = []

    def add(date_offset, acc_i, narration, debit=0, credit=0, ref=None, partner=None):
        ac = accounts[acc_i]
        rows.append({
            "date": base + timedelta(days=date_offset),
            "account_code": ac[0],
            "account_name": ac[1],
            "narration": narration,
            "debit": debit,
            "credit": credit,
            "ref": ref or f"JNL{len(rows)+1:04d}",
            "journal": "MISC",
            "partner": partner or "—",
        })

    # Normal transactions
    add(1,  0, "Receipt from EU client",           debit=85000)
    add(2,  1, "Honey purchase - Kamau",            credit=45000)
    add(3,  2, "Revenue recognition - Feb batch",   credit=120000)
    add(4,  4, "Processing cost - wax extraction",  debit=8500)
    add(5,  1, "Supplier payment - Otieno",         credit=28500)

    # EXACT DUPLICATE (same as row 2)
    add(2,  1, "Honey purchase - Kamau",            credit=45000)

    # NEAR DUPLICATE (same account+amount, 3 days later)
    add(5,  1, "Supplier payment - Otieno",         credit=28500)

    # REVERSAL PAIR
    add(8,  2, "Accrual - March honey revenue",     credit=60000)
    add(12, 2, "Reversal - March honey revenue",    debit=60000)

    # SUSPENSE entries — some old, some recent
    add(5,  3, "Unallocated receipt ref TML-882",   debit=15000)   # recent
    add(85, 5, "Beekeeper advance unallocated",      debit=7500)   # OLD — 85 days
    add(95, 3, "Transit clearing - NBC transfer",    debit=22000)  # OLD — 95 days

    # ROUND NUMBERS (large, suspicious)
    add(10, 0, "Cash advance - field ops",          debit=50000)
    add(15, 4, "Processing cost estimate",          debit=20000)

    # More normal transactions
    for i in range(20):
        amt = int(np.random.choice([3400, 7800, 12500, 4200, 9100]))
        add(np.random.randint(1,60), np.random.randint(0,4),
            f"Transaction {i+1}", debit=amt)

    gl_df = pd.DataFrame(rows)
    gl_df.to_csv("/tmp/gl_upendo_demo.csv", index=False)

    run_gl_forensics("/tmp/gl_upendo_demo.csv", "/tmp/gl_forensics_demo.xlsx")
