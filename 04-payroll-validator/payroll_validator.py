"""
Payroll Validation Engine
Acacia Group — Group Payroll (135–137 employees)
Author: Learning Python for Finance - Week 4

Validates monthly payroll against Tanzania statutory deduction rules:
- PAYE     : Progressive tax bands (TRA 2024/25)
- NSSF     : 10% employee + 10% employer (capped at TZS 8,000/month each side)
- NHIF     : Graduated bands based on gross salary
- WCF      : 0.5% of gross (employer only)
- SDL      : 4.5% of gross (employer only)

Outputs:
1. Per-employee variance vs submitted payroll
2. Statutory deduction summary by type
3. Exception report — over/under deductions
4. Prior month variance analysis
"""

import pandas as pd
import numpy as np


# ─────────────────────────────────────────────
# 1. STATUTORY RULES (TRA 2024/25)
# ─────────────────────────────────────────────

# PAYE bands — monthly (TZS)
# Source: TRA Income Tax Act CAP 332
PAYE_BANDS = [
    (0,       270_000,  0.00),
    (270_001, 520_000,  0.08),
    (520_001, 760_000,  0.20),
    (760_001, 1_000_000, 0.25),
    (1_000_001, float("inf"), 0.30),
]

# NSSF: 10% employee + 10% employer, capped at TZS 8,000 each side/month
NSSF_RATE_EE = 0.10
NSSF_RATE_ER = 0.10
NSSF_CAP_EE  = 8_000
NSSF_CAP_ER  = 8_000

# NHIF bands — monthly gross (TZS)
NHIF_BANDS = [
    (0,        999,       0),
    (1_000,    4_999,     400),
    (5_000,    9_999,     1_000),
    (10_000,   19_999,    1_500),
    (20_000,   29_999,    2_000),
    (30_000,   49_999,    2_500),
    (50_000,   99_999,    4_000),
    (100_000,  149_999,   5_000),
    (150_000,  199_999,   6_000),
    (200_000,  299_999,   7_500),
    (300_000,  399_999,   9_000),
    (400_000,  499_999,   10_000),
    (500_000,  599_999,   11_000),
    (600_000,  799_999,   12_000),
    (800_000,  999_999,   14_000),
    (1_000_000, float("inf"), 15_000),
]

WCF_RATE = 0.005   # 0.5% employer
SDL_RATE = 0.045   # 4.5% employer


# ─────────────────────────────────────────────
# 2. CALCULATION FUNCTIONS
# ─────────────────────────────────────────────

def calc_paye(gross: float) -> float:
    """Calculate PAYE using progressive bands."""
    tax = 0.0
    for lower, upper, rate in PAYE_BANDS:
        if gross <= lower:
            break
        taxable = min(gross, upper) - lower
        tax += taxable * rate
    return round(tax)


def calc_nssf(gross: float) -> dict:
    """Calculate NSSF employee and employer contributions."""
    ee = min(gross * NSSF_RATE_EE, NSSF_CAP_EE)
    er = min(gross * NSSF_RATE_ER, NSSF_CAP_ER)
    return {"nssf_ee": round(ee), "nssf_er": round(er)}


def calc_nhif(gross: float) -> float:
    """Calculate NHIF from graduated bands."""
    for lower, upper, amount in NHIF_BANDS:
        if lower <= gross <= upper:
            return float(amount)
    return 0.0


def calc_wcf(gross: float) -> float:
    return round(gross * WCF_RATE)


def calc_sdl(gross: float) -> float:
    return round(gross * SDL_RATE)


def calc_net(gross: float, paye: float, nssf_ee: float, nhif: float) -> float:
    return round(gross - paye - nssf_ee - nhif)


def compute_statutory(gross: float) -> dict:
    """Full statutory computation for one employee."""
    paye = calc_paye(gross)
    nssf = calc_nssf(gross)
    nhif = calc_nhif(gross)
    wcf  = calc_wcf(gross)
    sdl  = calc_sdl(gross)
    net  = calc_net(gross, paye, nssf["nssf_ee"], nhif)
    total_er_cost = gross + nssf["nssf_er"] + wcf + sdl

    return {
        "gross":          gross,
        "paye_calc":      paye,
        "nssf_ee_calc":   nssf["nssf_ee"],
        "nssf_er_calc":   nssf["nssf_er"],
        "nhif_calc":      nhif,
        "wcf_calc":       wcf,
        "sdl_calc":       sdl,
        "net_calc":       net,
        "total_er_calc":  total_er_cost,
    }


# ─────────────────────────────────────────────
# 3. LOAD PAYROLL DATA
# ─────────────────────────────────────────────

def load_payroll(filepath: str) -> pd.DataFrame:
    """
    Load payroll CSV.
    Expected columns: emp_id, name, entity, department, gross,
                      paye_submitted, nssf_ee_submitted, nssf_er_submitted,
                      nhif_submitted, wcf_submitted, sdl_submitted,
                      net_submitted
    Optional: prev_gross (for month-on-month variance)
    """
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    return df


# ─────────────────────────────────────────────
# 4. VALIDATE PAYROLL
# ─────────────────────────────────────────────

TOLERANCE = 5   # TZS rounding tolerance

def validate_payroll(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run statutory calculations and compare to submitted figures.
    Flags variances outside tolerance.
    """
    computed = df["gross"].apply(lambda g: pd.Series(compute_statutory(g)))
    df = pd.concat([df, computed], axis=1)

    # Variance columns
    for field in ["paye", "nssf_ee", "nssf_er", "nhif", "wcf", "sdl", "net"]:
        submitted_col = f"{field}_submitted"
        calc_col      = f"{field}_calc"
        var_col       = f"{field}_variance"
        if submitted_col in df.columns:
            df[var_col] = df[calc_col] - df[submitted_col]
        else:
            df[var_col] = 0   # not provided — skip variance

    # Exception flag
    variance_cols = [c for c in df.columns if c.endswith("_variance")]
    df["has_exception"] = df[variance_cols].abs().gt(TOLERANCE).any(axis=1)
    df["exception_fields"] = df.apply(
        lambda row: ", ".join([
            c.replace("_variance","").upper()
            for c in variance_cols
            if abs(row[c]) > TOLERANCE
        ]), axis=1
    )

    # Month-on-month gross variance
    if "prev_gross" in df.columns:
        df["gross_mom_var"] = df["gross"] - df["prev_gross"]
        df["gross_mom_pct"] = (df["gross_mom_var"] / df["prev_gross"].replace(0, np.nan) * 100).round(1)
        df["gross_spike"] = df["gross_mom_pct"].abs() > 20   # flag >20% change

    return df


# ─────────────────────────────────────────────
# 5. REPORTING
# ─────────────────────────────────────────────

def build_payroll_report(df: pd.DataFrame, output_path: str = "payroll_validation.xlsx"):
    """
    6-tab Excel report:
    Summary | Full Validation | Exceptions | Deduction Summary |
    Entity Breakdown | MoM Variance
    """
    total = len(df)
    exceptions = df["has_exception"].sum()

    # Statutory totals
    stat_summary = pd.DataFrame({
        "Deduction": ["PAYE", "NSSF (EE)", "NSSF (ER)", "NHIF", "WCF", "SDL"],
        "Submitted (TZS)": [
            df.get("paye_submitted", pd.Series([0]*total)).sum(),
            df.get("nssf_ee_submitted", pd.Series([0]*total)).sum(),
            df.get("nssf_er_submitted", pd.Series([0]*total)).sum(),
            df.get("nhif_submitted", pd.Series([0]*total)).sum(),
            df.get("wcf_submitted", pd.Series([0]*total)).sum(),
            df.get("sdl_submitted", pd.Series([0]*total)).sum(),
        ],
        "Calculated (TZS)": [
            df["paye_calc"].sum(),
            df["nssf_ee_calc"].sum(),
            df["nssf_er_calc"].sum(),
            df["nhif_calc"].sum(),
            df["wcf_calc"].sum(),
            df["sdl_calc"].sum(),
        ],
    })
    stat_summary["Variance (TZS)"] = stat_summary["Calculated (TZS)"] - stat_summary["Submitted (TZS)"]

    # Entity breakdown
    entity_cols = ["gross","paye_calc","nssf_ee_calc","nssf_er_calc",
                   "nhif_calc","wcf_calc","sdl_calc","total_er_calc"]
    entity_breakdown = df.groupby("entity")[entity_cols].sum().reset_index()

    # Summary
    summary = pd.DataFrame({
        "Metric": [
            "Total employees", "Exceptions flagged", "Exception rate",
            "Total gross payroll", "Total PAYE", "Total NSSF (EE)",
            "Total NSSF (ER)", "Total NHIF", "Total WCF", "Total SDL",
            "Total employer cost"
        ],
        "Value": [
            total, int(exceptions), f"{exceptions/total*100:.1f}%",
            f"TZS {df['gross'].sum():,.0f}",
            f"TZS {df['paye_calc'].sum():,.0f}",
            f"TZS {df['nssf_ee_calc'].sum():,.0f}",
            f"TZS {df['nssf_er_calc'].sum():,.0f}",
            f"TZS {df['nhif_calc'].sum():,.0f}",
            f"TZS {df['wcf_calc'].sum():,.0f}",
            f"TZS {df['sdl_calc'].sum():,.0f}",
            f"TZS {df['total_er_calc'].sum():,.0f}",
        ]
    })

    print(f"\n{'═'*50}")
    print(f"  PAYROLL VALIDATION SUMMARY")
    print(f"  Acacia Group Group — {total} employees")
    print(f"{'═'*50}")
    print(f"  Total gross:        TZS {df['gross'].sum():>14,.0f}")
    print(f"  Total PAYE:         TZS {df['paye_calc'].sum():>14,.0f}")
    print(f"  Total NSSF (EE):    TZS {df['nssf_ee_calc'].sum():>14,.0f}")
    print(f"  Total NSSF (ER):    TZS {df['nssf_er_calc'].sum():>14,.0f}")
    print(f"  Total NHIF:         TZS {df['nhif_calc'].sum():>14,.0f}")
    print(f"  Total WCF:          TZS {df['wcf_calc'].sum():>14,.0f}")
    print(f"  Total SDL:          TZS {df['sdl_calc'].sum():>14,.0f}")
    print(f"  Total employer cost:TZS {df['total_er_calc'].sum():>14,.0f}")
    print(f"{'─'*50}")
    print(f"  Exceptions flagged: {int(exceptions)} / {total}")
    if "gross_spike" in df.columns:
        spikes = df["gross_spike"].sum()
        print(f"  Gross spikes (>20%): {int(spikes)}")
    print(f"{'═'*50}\n")

    print("  Statutory variance check:")
    for _, row in stat_summary.iterrows():
        status = "✓" if abs(row["Variance (TZS)"]) <= TOLERANCE * total else "⚠"
        print(f"  {status} {row['Deduction']:<12} variance: TZS {row['Variance (TZS)']:>10,.0f}")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        df.to_excel(writer, sheet_name="Full Validation", index=False)
        df[df["has_exception"]].to_excel(writer, sheet_name="Exceptions", index=False)
        stat_summary.to_excel(writer, sheet_name="Deduction Summary", index=False)
        entity_breakdown.to_excel(writer, sheet_name="Entity Breakdown", index=False)
        if "gross_mom_var" in df.columns:
            mom = df[["emp_id","name","entity","prev_gross","gross",
                       "gross_mom_var","gross_mom_pct","gross_spike"]].sort_values(
                "gross_mom_pct", key=abs, ascending=False)
            mom.to_excel(writer, sheet_name="MoM Variance", index=False)

    print(f"\n  Report saved → {output_path}")


# ─────────────────────────────────────────────
# 6. MAIN RUNNER
# ─────────────────────────────────────────────

def run_payroll_validation(payroll_path: str, output_path: str = "payroll_validation.xlsx"):
    print(f"\n{'═'*50}")
    print(f"  PAYROLL VALIDATION ENGINE")
    print(f"  Acacia Group — Tanzania Statutory Rules 2024/25")
    print(f"{'═'*50}\n")
    df = load_payroll(payroll_path)
    print(f"  Employees loaded: {len(df)}")
    df = validate_payroll(df)
    build_payroll_report(df, output_path)


# ─────────────────────────────────────────────
# 7. DEMO — 20 synthetic employees across entities
# ─────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(9)

    entities = ["Group HQ", "Group HQ", "Entity B", "Entity B", "Entity A",
                "Entity A", "Entity C", "Group HQ", "Entity A", "Entity B"]
    departments = ["Finance","Operations","Processing","Processing","Agro Commodity Proc",
                   "Agro Commodity Proc","Carbon","Management","Logistics","Processing"]

    gross_salaries = [
        180_000, 320_000, 450_000, 620_000, 850_000,
        1_200_000, 280_000, 2_500_000, 390_000, 510_000,
        175_000, 730_000, 960_000, 1_450_000, 290_000,
        440_000, 680_000, 1_100_000, 370_000, 555_000,
    ]

    rows = []
    for i, gross in enumerate(gross_salaries):
        stat = compute_statutory(gross)
        # Introduce deliberate errors in some submitted figures
        paye_sub = stat["paye_calc"]
        nssf_ee_sub = stat["nssf_ee_calc"]
        nhif_sub = stat["nhif_calc"]
        wcf_sub = stat["wcf_calc"]
        sdl_sub = stat["sdl_calc"]

        if i == 3:  paye_sub += 5_000       # over-deducted PAYE
        if i == 7:  nssf_ee_sub = 6_000     # NSSF capped wrong
        if i == 11: nhif_sub = 8_000        # wrong NHIF band
        if i == 14: sdl_sub = 0             # SDL missing entirely
        if i == 17: paye_sub -= 12_000      # under-deducted PAYE

        prev_gross = gross * np.random.uniform(0.85, 1.15)
        if i == 5: prev_gross = gross * 0.60   # big spike — new hire / promotion

        rows.append({
            "emp_id": f"EMP{str(i+1).zfill(3)}",
            "name": f"Employee {i+1}",
            "entity": entities[i % len(entities)],
            "department": departments[i % len(departments)],
            "gross": gross,
            "prev_gross": round(prev_gross),
            "paye_submitted": paye_sub,
            "nssf_ee_submitted": nssf_ee_sub,
            "nssf_er_submitted": stat["nssf_er_calc"],
            "nhif_submitted": nhif_sub,
            "wcf_submitted": wcf_sub,
            "sdl_submitted": sdl_sub,
            "net_submitted": stat["net_calc"],
        })

    df_demo = pd.DataFrame(rows)
    df_demo.to_csv("/tmp/payroll_demo.csv", index=False)
    run_payroll_validation("/tmp/payroll_demo.csv", "/tmp/payroll_validation_demo.xlsx")

    # Quick band test
    print("\n  PAYE band test:")
    test_grosses = [200_000, 400_000, 600_000, 900_000, 1_500_000, 3_000_000]
    for g in test_grosses:
        s = compute_statutory(g)
        eff = s["paye_calc"] / g * 100
        print(f"    Gross {g:>10,.0f}  →  PAYE {s['paye_calc']:>8,.0f}  eff rate {eff:.1f}%"
              f"  NSSF(EE) {s['nssf_ee_calc']:>5,.0f}  NHIF {s['nhif_calc']:>5,.0f}")
