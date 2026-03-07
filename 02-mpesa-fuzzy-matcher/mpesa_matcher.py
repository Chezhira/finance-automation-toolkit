"""
Mpesa Bulk Payment Fuzzy Matching Engine
Third Man Ltd — Beekeeper Honey Purchase Reconciliation
Author: Learning Python for Finance - Week 2

Problem: Mpesa bulk payment file has supplier names in inconsistent formats.
Purchase ledger has vendor names registered differently.
Previous manual match rate: 84.5% — this engine targets 95%+

Matching strategy:
1. Exact amount + exact phone number         → EXACT
2. Exact amount + fuzzy name (score ≥ 90)   → FUZZY-HIGH
3. Exact amount + fuzzy name (score 70–89)  → FUZZY-MED (review)
4. Amount tolerance ±1% + fuzzy name ≥ 85  → AMOUNT-FUZZY (review)
5. Remaining unmatched                       → EXCEPTION
"""

import pandas as pd
from difflib import SequenceMatcher
import re
import unicodedata


# ─────────────────────────────────────────────
# 1. NAME NORMALISATION
# ─────────────────────────────────────────────

def normalise_name(name: str) -> str:
    """
    Clean and standardise supplier names for fuzzy comparison.
    Handles: extra spaces, case, punctuation, common abbreviations,
    unicode accents, Swahili honorifics.
    """
    if not isinstance(name, str):
        return ""

    # Unicode normalisation (handles accented chars)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()

    name = name.upper().strip()

    # Remove common noise
    noise = [
        r"\bLTD\b", r"\bLIMITED\b", r"\bCO\b", r"\bCOMPANY\b",
        r"\bENTERPRISES?\b", r"\bTRADERS?\b", r"\bSUPPLIERS?\b",
        r"\bBEEKEEPER\b", r"\bFARMS?\b", r"\bAGRO\b",
        r"\bMR\b", r"\bMRS\b", r"\bMS\b", r"\bDR\b",
        r"\bBWANA\b", r"\bBI\b", r"\bMWE\b",   # Swahili honorifics
        r"[^A-Z0-9 ]"                            # non-alphanumeric
    ]
    for pattern in noise:
        name = re.sub(pattern, " ", name)

    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def fuzzy_score(a: str, b: str) -> int:
    """
    Returns similarity score 0–100 between two name strings.
    Uses SequenceMatcher (no external deps needed).
    """
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0
    return int(SequenceMatcher(None, na, nb).ratio() * 100)


# ─────────────────────────────────────────────
# 2. LOAD DATA
# ─────────────────────────────────────────────

def load_mpesa_file(filepath: str) -> pd.DataFrame:
    """
    Load Mpesa bulk payment export.
    Expected: receipt_no, phone, name, amount, status, timestamp
    """
    df = pd.read_csv(filepath, parse_dates=["timestamp"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df = df[df["status"].str.upper() == "SUCCESS"].copy()  # only successful payments
    df["matched"] = False
    df["match_type"] = None
    df["match_score"] = None
    df["matched_vendor_id"] = None
    return df.reset_index(drop=True)


def load_purchase_ledger(filepath: str) -> pd.DataFrame:
    """
    Load purchase ledger / vendor master from Odoo export.
    Expected: vendor_id, vendor_name, phone, invoice_no, amount, invoice_date
    """
    df = pd.read_csv(filepath, parse_dates=["invoice_date"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df["matched"] = False
    df["match_type"] = None
    df["match_score"] = None
    df["matched_receipt"] = None
    return df.reset_index(drop=True)


# ─────────────────────────────────────────────
# 3. MATCHING PASSES
# ─────────────────────────────────────────────

def pass_exact_phone_amount(mpesa: pd.DataFrame, ledger: pd.DataFrame) -> tuple:
    """Pass 1: Exact phone number + exact amount."""
    count = 0
    for i, m in mpesa[~mpesa["matched"]].iterrows():
        candidates = ledger[
            (~ledger["matched"]) &
            (ledger["amount"] == m["amount"]) &
            (ledger["phone"].astype(str).str[-9:] == str(m["phone"])[-9:])
        ]
        if not candidates.empty:
            j = candidates.index[0]
            mid = f"EXACT-{count+1:04d}"
            mpesa.at[i, "matched"] = True
            mpesa.at[i, "match_type"] = "EXACT"
            mpesa.at[i, "match_score"] = 100
            mpesa.at[i, "matched_vendor_id"] = ledger.at[j, "vendor_id"]
            ledger.at[j, "matched"] = True
            ledger.at[j, "match_type"] = "EXACT"
            ledger.at[j, "match_score"] = 100
            ledger.at[j, "matched_receipt"] = m["receipt_no"]
            count += 1
    print(f"  Pass 1 — Exact (phone+amount):     {count}")
    return mpesa, ledger


def pass_fuzzy_name_exact_amount(mpesa: pd.DataFrame, ledger: pd.DataFrame,
                                  high_threshold: int = 90,
                                  med_threshold: int = 70) -> tuple:
    """Pass 2: Exact amount + fuzzy name matching."""
    high_count = med_count = 0
    for i, m in mpesa[~mpesa["matched"]].iterrows():
        candidates = ledger[
            (~ledger["matched"]) &
            (ledger["amount"] == m["amount"])
        ].copy()
        if candidates.empty:
            continue

        # Score all candidates
        candidates["_score"] = candidates["vendor_name"].apply(
            lambda v: fuzzy_score(m["name"], v)
        )
        best = candidates.nlargest(1, "_score").iloc[0]
        score = int(best["_score"])

        if score >= high_threshold:
            mtype = "FUZZY-HIGH"
            high_count += 1
        elif score >= med_threshold:
            mtype = "FUZZY-MED"
            med_count += 1
        else:
            continue

        j = best.name
        mpesa.at[i, "matched"] = True
        mpesa.at[i, "match_type"] = mtype
        mpesa.at[i, "match_score"] = score
        mpesa.at[i, "matched_vendor_id"] = ledger.at[j, "vendor_id"]
        ledger.at[j, "matched"] = True
        ledger.at[j, "match_type"] = mtype
        ledger.at[j, "match_score"] = score
        ledger.at[j, "matched_receipt"] = m["receipt_no"]

    print(f"  Pass 2 — Fuzzy-High (≥{high_threshold}):        {high_count}")
    print(f"  Pass 2 — Fuzzy-Med  ({med_threshold}–{high_threshold-1}):       {med_count}")
    return mpesa, ledger


def pass_amount_tolerance_fuzzy(mpesa: pd.DataFrame, ledger: pd.DataFrame,
                                 tolerance_pct: float = 0.01,
                                 name_threshold: int = 85) -> tuple:
    """Pass 3: Amount ±1% tolerance + strong name match."""
    count = 0
    for i, m in mpesa[~mpesa["matched"]].iterrows():
        amt_min = m["amount"] * (1 - tolerance_pct)
        amt_max = m["amount"] * (1 + tolerance_pct)
        candidates = ledger[
            (~ledger["matched"]) &
            (ledger["amount"] >= amt_min) &
            (ledger["amount"] <= amt_max)
        ].copy()
        if candidates.empty:
            continue

        candidates["_score"] = candidates["vendor_name"].apply(
            lambda v: fuzzy_score(m["name"], v)
        )
        best = candidates.nlargest(1, "_score").iloc[0]
        score = int(best["_score"])
        if score < name_threshold:
            continue

        j = best.name
        mpesa.at[i, "matched"] = True
        mpesa.at[i, "match_type"] = "AMOUNT-FUZZY"
        mpesa.at[i, "match_score"] = score
        mpesa.at[i, "matched_vendor_id"] = ledger.at[j, "vendor_id"]
        ledger.at[j, "matched"] = True
        ledger.at[j, "match_type"] = "AMOUNT-FUZZY"
        ledger.at[j, "match_score"] = score
        ledger.at[j, "matched_receipt"] = m["receipt_no"]
        count += 1

    print(f"  Pass 3 — Amount±1% + fuzzy:        {count}")
    return mpesa, ledger


# ─────────────────────────────────────────────
# 4. SUGGEST CANDIDATES FOR EXCEPTIONS
# ─────────────────────────────────────────────

def suggest_candidates(mpesa: pd.DataFrame, ledger: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    """
    For each unmatched Mpesa row, suggest top N closest ledger candidates.
    Gives the reviewer a shortlist instead of a blank page.
    """
    rows = []
    unmatched_mpesa = mpesa[~mpesa["matched"]]
    unmatched_ledger = ledger[~ledger["matched"]]

    for _, m in unmatched_mpesa.iterrows():
        if unmatched_ledger.empty:
            rows.append({
                "receipt_no": m["receipt_no"],
                "mpesa_name": m["name"],
                "mpesa_amount": m["amount"],
                "suggestion_rank": None,
                "suggested_vendor": "NO CANDIDATES",
                "suggested_vendor_id": None,
                "suggested_amount": None,
                "name_score": 0,
            })
            continue

        scored = unmatched_ledger.copy()
        scored["_score"] = scored["vendor_name"].apply(lambda v: fuzzy_score(m["name"], v))
        top = scored.nlargest(top_n, "_score")

        for rank, (_, c) in enumerate(top.iterrows(), 1):
            rows.append({
                "receipt_no": m["receipt_no"],
                "mpesa_name": m["name"],
                "mpesa_amount": m["amount"],
                "suggestion_rank": rank,
                "suggested_vendor": c["vendor_name"],
                "suggested_vendor_id": c["vendor_id"],
                "suggested_amount": c["amount"],
                "name_score": int(c["_score"]),
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# 5. REPORTING
# ─────────────────────────────────────────────

def build_report(mpesa: pd.DataFrame, ledger: pd.DataFrame, output_path: str = "mpesa_recon.xlsx"):
    total_m = len(mpesa)
    matched_m = mpesa["matched"].sum()
    match_rate = matched_m / total_m * 100 if total_m > 0 else 0

    print(f"\n{'═'*48}")
    print(f"  MPESA RECONCILIATION SUMMARY")
    print(f"{'═'*48}")
    print(f"  Total Mpesa payments:    {total_m}")
    print(f"  Matched:                 {matched_m}")
    print(f"  Unmatched:               {total_m - matched_m}")
    print(f"  Match rate:              {match_rate:.1f}%")
    for mtype in ["EXACT", "FUZZY-HIGH", "FUZZY-MED", "AMOUNT-FUZZY"]:
        n = (mpesa["match_type"] == mtype).sum()
        if n:
            print(f"    └─ {mtype:<18} {n}")
    print(f"{'═'*48}\n")

    suggestions = suggest_candidates(mpesa, ledger)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        pd.DataFrame({
            "Metric": ["Total Mpesa", "Matched", "Unmatched", "Match Rate"],
            "Value": [total_m, matched_m, total_m - matched_m, f"{match_rate:.1f}%"]
        }).to_excel(writer, sheet_name="Summary", index=False)

        mpesa.to_excel(writer, sheet_name="Mpesa - All", index=False)
        mpesa[mpesa["matched"]].to_excel(writer, sheet_name="Matched", index=False)
        mpesa[~mpesa["matched"]].to_excel(writer, sheet_name="Unmatched Mpesa", index=False)
        ledger[~ledger["matched"]].to_excel(writer, sheet_name="Unmatched Ledger", index=False)
        suggestions.to_excel(writer, sheet_name="Exception Suggestions", index=False)

    print(f"  Report saved → {output_path}")


# ─────────────────────────────────────────────
# 6. MAIN RUNNER
# ─────────────────────────────────────────────

def run_mpesa_reconciliation(mpesa_path: str, ledger_path: str, output_path: str = "mpesa_recon.xlsx"):
    print(f"\n{'═'*48}")
    print(f"  MPESA FUZZY MATCHING ENGINE")
    print(f"  Third Man Ltd — Beekeeper Honey Purchases")
    print(f"{'═'*48}\n")

    mpesa = load_mpesa_file(mpesa_path)
    ledger = load_purchase_ledger(ledger_path)
    print(f"  Mpesa rows:  {len(mpesa)} | Ledger rows: {len(ledger)}\n")
    print("  Running matching passes...")

    mpesa, ledger = pass_exact_phone_amount(mpesa, ledger)
    mpesa, ledger = pass_fuzzy_name_exact_amount(mpesa, ledger)
    mpesa, ledger = pass_amount_tolerance_fuzzy(mpesa, ledger)

    build_report(mpesa, ledger, output_path)


# ─────────────────────────────────────────────
# 7. DEMO WITH SYNTHETIC BEEKEEPER DATA
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import numpy as np
    from datetime import datetime, timedelta

    np.random.seed(7)

    # Beekeeper names with real-world inconsistency patterns
    beekeepers = [
        ("V001", "John Mwangi Kamau",       "0712345601", 45000),
        ("V002", "Mary Akinyi Odhiambo",    "0712345602", 32000),
        ("V003", "Peter Otieno",             "0712345603", 28500),
        ("V004", "Grace Wanjiku Ltd",        "0712345604", 61000),
        ("V005", "Hassan Juma Enterprises",  "0712345605", 19000),
        ("V006", "Fatuma Binti Salim",       "0712345606", 42000),
        ("V007", "Joseph Kipchoge Farms",    "0712345607", 55000),
        ("V008", "Agnes Mutua Traders",      "0712345608", 23500),
        ("V009", "Rashid Omar Beekeeper",    "0712345609", 37000),
        ("V010", "Eunice Atieno Suppliers",  "0712345610", 48000),
    ]

    # Purchase ledger (clean, as registered in Odoo)
    ledger_rows = []
    base_date = datetime(2025, 3, 1)
    for vid, name, phone, amt in beekeepers:
        ledger_rows.append({
            "vendor_id": vid, "vendor_name": name, "phone": phone,
            "invoice_no": f"INV-{vid}", "amount": amt,
            "invoice_date": base_date + timedelta(days=np.random.randint(0,5))
        })
    ledger_df = pd.DataFrame(ledger_rows)
    ledger_df.to_csv("/tmp/ledger_demo.csv", index=False)

    # Mpesa file — same people, messy names, some phone variants
    mpesa_names = [
        "JOHN M KAMAU",              # abbreviated middle name
        "Mary Akinyi",               # surname dropped
        "PETER OTIENO",              # exact
        "Grace Wanjiku",             # Ltd dropped
        "HASSAN JUMA",               # Enterprises dropped
        "Fatuma Salim",              # Binti dropped
        "J KIPCHOGE",                # Joseph → J, Farms dropped
        "Agnes Mutua",               # Traders dropped
        "Rashid Omar",               # Beekeeper dropped
        "EUNICE A SUPPLIERS",        # middle → initial
    ]
    mpesa_phones = [b[2] for b in beekeepers]
    # Introduce some phone mismatches
    mpesa_phones[2] = "0799999999"   # Peter: wrong phone — needs name match
    mpesa_phones[6] = "0799999998"   # Joseph: wrong phone — needs name match

    mpesa_rows = []
    for idx, (name, (vid, _, phone, amt)) in enumerate(zip(mpesa_names, beekeepers)):
        mpesa_rows.append({
            "receipt_no": f"MP{str(idx+1).zfill(4)}",
            "phone": mpesa_phones[idx],
            "name": name,
            "amount": amt if idx != 4 else amt + 500,  # Hassan: ±amount diff
            "status": "SUCCESS",
            "timestamp": base_date + timedelta(days=np.random.randint(0,3))
        })
    mpesa_df = pd.DataFrame(mpesa_rows)
    mpesa_df.to_csv("/tmp/mpesa_demo.csv", index=False)

    run_mpesa_reconciliation("/tmp/mpesa_demo.csv", "/tmp/ledger_demo.csv", "/tmp/mpesa_recon_demo.xlsx")
    print("\n  Normalisation demo:")
    test_pairs = [
        ("John Mwangi Kamau", "JOHN M KAMAU"),
        ("Grace Wanjiku Ltd", "Grace Wanjiku"),
        ("Hassan Juma Enterprises", "HASSAN JUMA"),
        ("Fatuma Binti Salim", "Fatuma Salim"),
    ]
    for a, b in test_pairs:
        score = fuzzy_score(a, b)
        print(f"    {a:<30} ↔ {b:<25} score: {score}")
