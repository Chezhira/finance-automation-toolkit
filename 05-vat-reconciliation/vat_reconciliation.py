"""
VAT Reconciliation Engine
Acacia Group — TRA VAT Return Reconciliation
Author: Learning Python for Finance - Week 5

Problem: Odoo posts VAT on invoice date. TRA submissions use
filing period (tax point date). This mismatch causes reconciling
items that look like errors but aren't — and real errors that
get buried in the noise.

This engine:
1. Loads Odoo VAT control account GL entries
2. Loads TRA VAT return submissions (per period)
3. Reconciles by methodology (bill date vs posting date)
4. Flags genuine mismatches vs timing differences
5. Produces audit-ready reconciliation schedules

Output tabs:
- Summary              : period-by-period match
- Matched              : confirmed items
- Timing Differences   : legitimate cross-period items
- Genuine Variances    : real errors needing correction
- Audit Schedule       : TRA-ready reconciliation
"""

import pandas as pd
import numpy as np
from datetime import timedelta


# ─────────────────────────────────────────────
# 1. TAX RATES
# ─────────────────────────────────────────────

VAT_STANDARD_RATE = 0.18   # Tanzania standard VAT rate
VAT_ZERO_RATE     = 0.00
VAT_EXEMPT        = None


# ─────────────────────────────────────────────
# 2. LOAD DATA
# ─────────────────────────────────────────────

def load_odoo_vat_gl(filepath: str) -> pd.DataFrame:
    """
    Load Odoo VAT control account GL.
    Expected: bill_date, posting_date, period, invoice_ref,
              partner, vat_type (OUTPUT/INPUT), tax_base, vat_amount
    """
    df = pd.read_csv(filepath, parse_dates=["bill_date", "posting_date"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df["period"] = df["posting_date"].dt.to_period("M").astype(str)
    df["bill_period"] = df["bill_date"].dt.to_period("M").astype(str)
    df["cross_period"] = df["period"] != df["bill_period"]
    return df


def load_tra_return(filepath: str) -> pd.DataFrame:
    """
    Load TRA VAT return submission data.
    Expected: period, vat_type, declared_base, declared_vat
    """
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    return df


# ─────────────────────────────────────────────
# 3. RECONCILIATION LOGIC
# ─────────────────────────────────────────────

def reconcile_by_period(odoo: pd.DataFrame, tra: pd.DataFrame) -> pd.DataFrame:
    """
    Compare Odoo VAT GL (by posting period) vs TRA declared amounts.
    Returns period-level reconciliation.
    """
    # Odoo summary by period and VAT type
    odoo_summary = (
        odoo.groupby(["period", "vat_type"])
        .agg(odoo_base=("tax_base", "sum"), odoo_vat=("vat_amount", "sum"))
        .reset_index()
    )

    # Merge with TRA
    merged = pd.merge(
        odoo_summary, tra,
        on=["period", "vat_type"],
        how="outer"
    ).fillna(0)

    merged["base_variance"] = merged["odoo_base"] - merged["declared_base"]
    merged["vat_variance"]  = merged["odoo_vat"]  - merged["declared_vat"]
    merged["status"] = merged.apply(
        lambda r: "MATCH" if abs(r["vat_variance"]) <= 500
        else ("OVER_Entity CLARED" if r["vat_variance"] < 0 else "UNDER_Entity CLARED"),
        axis=1
    )
    return merged


def identify_timing_differences(odoo: pd.DataFrame) -> pd.DataFrame:
    """
    Isolate cross-period items — invoices where bill_date period
    differs from posting_date period. These explain many apparent
    mismatches between Odoo and TRA.
    """
    cross = odoo[odoo["cross_period"]].copy()
    cross["timing_note"] = (
        "Bill period: " + cross["bill_period"] +
        " | Posted period: " + cross["period"]
    )
    return cross


def find_genuine_variances(odoo: pd.DataFrame, tra: pd.DataFrame,
                            recon: pd.DataFrame) -> pd.DataFrame:
    """
    After accounting for timing differences, isolate variances
    that cannot be explained by cross-period posting.
    """
    # Periods with meaningful variance
    problem_periods = recon[recon["status"] != "MATCH"][["period","vat_type","vat_variance"]]

    if problem_periods.empty:
        return pd.DataFrame()

    # For each problem period, check if timing differences explain the gap
    timing = identify_timing_differences(odoo)
    timing_impact = (
        timing.groupby(["period", "vat_type"])["vat_amount"]
        .sum()
        .reset_index()
        .rename(columns={"vat_amount": "timing_vat_impact"})
    )

    explained = pd.merge(problem_periods, timing_impact,
                         on=["period","vat_type"], how="left").fillna(0)

    explained["residual_variance"] = (
        explained["vat_variance"] - explained["timing_vat_impact"]
    )
    explained["explained"] = explained["residual_variance"].abs() <= 500
    explained["verdict"] = explained["explained"].map(
        {True: "TIMING DIFFERENCE — no action needed",
         False: "GENUINE VARIANCE — investigate"}
    )
    return explained


# ─────────────────────────────────────────────
# 4. VAT HEALTH CHECKS
# ─────────────────────────────────────────────

def vat_health_checks(odoo: pd.DataFrame) -> list:
    """
    Run a set of data quality checks on the Odoo VAT GL.
    Returns list of findings.
    """
    findings = []

    # Check 1: VAT amount matches expected rate on base
    odoo["expected_vat"] = odoo["tax_base"] * VAT_STANDARD_RATE
    odoo["rate_mismatch"] = (
        (odoo["vat_amount"] - odoo["expected_vat"]).abs() > 10
    )
    rate_issues = odoo[odoo["rate_mismatch"]]
    if not rate_issues.empty:
        findings.append({
            "check": "VAT Rate Mismatch",
            "count": len(rate_issues),
            "detail": f"{len(rate_issues)} lines where VAT ≠ base × 18%",
            "severity": "HIGH"
        })

    # Check 2: Zero-base with non-zero VAT
    zero_base = odoo[(odoo["tax_base"] == 0) & (odoo["vat_amount"] != 0)]
    if not zero_base.empty:
        findings.append({
            "check": "Zero Base / Non-zero VAT",
            "count": len(zero_base),
            "detail": "VAT posted with no tax base — likely coding error",
            "severity": "HIGH"
        })

    # Check 3: Cross-period items older than 2 periods
    odoo["period_lag"] = (
        odoo["posting_date"].dt.to_period("M") -
        odoo["bill_date"].dt.to_period("M")
    ).apply(lambda x: x.n if hasattr(x, 'n') else 0)
    old_cross = odoo[odoo["period_lag"].abs() > 2]
    if not old_cross.empty:
        findings.append({
            "check": "Stale Cross-Period Items",
            "count": len(old_cross),
            "detail": f"Bill date > 2 periods from posting — TRA exposure",
            "severity": "MEDIUM"
        })

    # Check 4: Duplicate invoice refs
    dupes = odoo[odoo.duplicated(subset=["invoice_ref","vat_type"], keep=False)]
    if not dupes.empty:
        findings.append({
            "check": "Duplicate Invoice References",
            "count": len(dupes) // 2,
            "detail": f"{len(dupes)//2} invoice refs appear more than once",
            "severity": "MEDIUM"
        })

    if not findings:
        findings.append({"check": "All checks passed", "count": 0,
                         "detail": "No issues found", "severity": "OK"})
    return findings


# ─────────────────────────────────────────────
# 5. AUDIT SCHEDULE
# ─────────────────────────────────────────────

def build_audit_schedule(odoo: pd.DataFrame, recon: pd.DataFrame) -> pd.DataFrame:
    """
    Produce TRA-ready audit schedule showing:
    - Odoo per-period VAT
    - Declared VAT
    - Timing differences
    - Net unexplained variance
    """
    timing = (
        identify_timing_differences(odoo)
        .groupby(["period","vat_type"])["vat_amount"]
        .sum().reset_index()
        .rename(columns={"vat_amount":"timing_adjustment"})
    )
    schedule = pd.merge(recon, timing, on=["period","vat_type"], how="left").fillna(0)
    schedule["adjusted_odoo_vat"] = schedule["odoo_vat"] - schedule["timing_adjustment"]
    schedule["net_variance"] = schedule["adjusted_odoo_vat"] - schedule["declared_vat"]
    schedule["audit_note"] = schedule.apply(lambda r:
        "Reconciled" if abs(r["net_variance"]) <= 500
        else f"Unexplained TZS {abs(r['net_variance']):,.0f} — {"over" if r["net_variance"]<0 else "under"} declared",
        axis=1
    )
    return schedule


# ─────────────────────────────────────────────
# 6. REPORTING
# ─────────────────────────────────────────────

def build_vat_report(odoo, tra, recon, timing, variances,
                     health, schedule, output_path="vat_reconciliation.xlsx"):

    total_odoo_output = odoo[odoo["vat_type"]=="OUTPUT"]["vat_amount"].sum()
    total_odoo_input  = odoo[odoo["vat_type"]=="INPUT"]["vat_amount"].sum()
    net_vat_liability = total_odoo_output - total_odoo_input
    cross_period_count = odoo["cross_period"].sum()
    genuine_issues = len(variances[~variances.get("explained", pd.Series([True]*len(variances)))]) if not variances.empty else 0

    print(f"\n{'═'*52}")
    print(f"  VAT RECONCILIATION SUMMARY")
    print(f"  Acacia Group — TRA Returns")
    print(f"{'═'*52}")
    print(f"  Total Output VAT (Odoo):  TZS {total_odoo_output:>12,.0f}")
    print(f"  Total Input VAT (Odoo):   TZS {total_odoo_input:>12,.0f}")
    print(f"  Net VAT Liability:        TZS {net_vat_liability:>12,.0f}")
    print(f"  Cross-period items:       {int(cross_period_count)}")
    print(f"  Genuine variances:        {genuine_issues}")
    print(f"\n  Health Checks:")
    for h in health:
        icon = "✓" if h["severity"]=="OK" else ("⚠" if h["severity"]=="MEDIUM" else "✗")
        print(f"  {icon} [{h['severity']:<6}] {h['check']}: {h['detail']}")
    print(f"{'═'*52}\n")

    summary_df = pd.DataFrame({
        "Metric": ["Output VAT (Odoo)","Input VAT (Odoo)","Net VAT Liability",
                   "Cross-period items","Genuine variances"],
        "Value": [f"TZS {total_odoo_output:,.0f}", f"TZS {total_odoo_input:,.0f}",
                  f"TZS {net_vat_liability:,.0f}", int(cross_period_count), genuine_issues]
    })

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        recon.to_excel(writer, sheet_name="Period Reconciliation", index=False)
        timing.to_excel(writer, sheet_name="Timing Differences", index=False)
        if not variances.empty:
            variances.to_excel(writer, sheet_name="Genuine Variances", index=False)
        pd.DataFrame(health).to_excel(writer, sheet_name="Health Checks", index=False)
        schedule.to_excel(writer, sheet_name="Audit Schedule", index=False)

    print(f"  Report saved → {output_path}")


# ─────────────────────────────────────────────
# 7. MAIN RUNNER
# ─────────────────────────────────────────────

def run_vat_reconciliation(odoo_path, tra_path, output_path="vat_reconciliation.xlsx"):
    print(f"\n{'═'*52}")
    print(f"  VAT RECONCILIATION ENGINE")
    print(f"  Acacia Group — Bill Date vs Posting Date")
    print(f"{'═'*52}\n")

    odoo = load_odoo_vat_gl(odoo_path)
    tra  = load_tra_return(tra_path)
    print(f"  Odoo VAT lines: {len(odoo)} | TRA return lines: {len(tra)}\n")

    print("  Running reconciliation...")
    recon    = reconcile_by_period(odoo, tra)
    timing   = identify_timing_differences(odoo)
    variance = find_genuine_variances(odoo, tra, recon)
    health   = vat_health_checks(odoo)
    schedule = build_audit_schedule(odoo, recon)

    build_vat_report(odoo, tra, recon, timing, variance,
                     health, schedule, output_path)


# ─────────────────────────────────────────────
# 8. DEMO
# ─────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(11)

    periods = ["2025-01","2025-02","2025-03"]
    partners_out = ["EU Client A","EU Client B","Domestic Buyer","Export - Germany","Local Distributor"]
    partners_in  = ["Supplier Kamau","Group Bank Bank","Fuel Supplier","Packaging Ltd","Logistics Co"]

    odoo_rows = []
    ref = 1

    for period in periods:
        base_month = pd.Timestamp(period + "-01")

        # Normal output VAT — bill date = posting date (same period)
        for _ in range(6):
            bill = base_month + timedelta(days=np.random.randint(0,20))
            base = np.random.choice([800_000, 1_200_000, 2_500_000, 450_000])
            odoo_rows.append({
                "bill_date": bill, "posting_date": bill,
                "invoice_ref": f"INV-{ref:04d}",
                "partner": np.random.choice(partners_out),
                "vat_type": "OUTPUT",
                "tax_base": base,
                "vat_amount": round(base * VAT_STANDARD_RATE),
            })
            ref += 1

        # Input VAT — same period
        for _ in range(4):
            bill = base_month + timedelta(days=np.random.randint(0,20))
            base = np.random.choice([200_000, 350_000, 500_000])
            odoo_rows.append({
                "bill_date": bill, "posting_date": bill,
                "invoice_ref": f"PUR-{ref:04d}",
                "partner": np.random.choice(partners_in),
                "vat_type": "INPUT",
                "tax_base": base,
                "vat_amount": round(base * VAT_STANDARD_RATE),
            })
            ref += 1

    # Introduce cross-period items (bill in Jan, posted in Feb)
    odoo_rows.append({
        "bill_date": pd.Timestamp("2025-01-28"),
        "posting_date": pd.Timestamp("2025-02-03"),   # cross-period
        "invoice_ref": "INV-CROSS-001",
        "partner": "EU Client A",
        "vat_type": "OUTPUT",
        "tax_base": 3_000_000,
        "vat_amount": 540_000,
    })
    odoo_rows.append({
        "bill_date": pd.Timestamp("2025-02-25"),
        "posting_date": pd.Timestamp("2025-03-02"),   # cross-period
        "invoice_ref": "PUR-CROSS-001",
        "partner": "Supplier Kamau",
        "vat_type": "INPUT",
        "tax_base": 600_000,
        "vat_amount": 108_000,
    })

    # Introduce a genuine error — wrong VAT rate coded
    odoo_rows.append({
        "bill_date": pd.Timestamp("2025-02-10"),
        "posting_date": pd.Timestamp("2025-02-10"),
        "invoice_ref": "INV-ERR-001",
        "partner": "Domestic Buyer",
        "vat_type": "OUTPUT",
        "tax_base": 1_000_000,
        "vat_amount": 80_000,   # should be 180,000 — wrong rate
    })

    odoo_df = pd.DataFrame(odoo_rows)
    odoo_df.to_csv("/tmp/odoo_vat_demo.csv", index=False)

    # TRA returns — based on bill dates (different from Odoo posting periods)
    # Simulate what was actually declared
    tra_rows = []
    for period in periods:
        base_month = pd.Timestamp(period+"-01")
        # TRA declared based on bill date filter
        period_odoo = odoo_df[odoo_df["bill_date"].dt.to_period("M").astype(str)==period]
        for vtype in ["OUTPUT","INPUT"]:
            sub = period_odoo[period_odoo["vat_type"]==vtype]
            if not sub.empty:
                # Declare slightly different (common in practice)
                declared_vat = sub["vat_amount"].sum() + np.random.randint(-5000,5000)
                tra_rows.append({
                    "period": period,
                    "vat_type": vtype,
                    "declared_base": sub["tax_base"].sum(),
                    "declared_vat": declared_vat,
                })

    tra_df = pd.DataFrame(tra_rows)
    tra_df.to_csv("/tmp/tra_return_demo.csv", index=False)

    run_vat_reconciliation("/tmp/odoo_vat_demo.csv", "/tmp/tra_return_demo.csv",
                           "/tmp/vat_reconciliation_demo.xlsx")
