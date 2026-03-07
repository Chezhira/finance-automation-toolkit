"""
13-Week Rolling Cash Flow Forecaster
Acacia Group — Multi-Entity, Multi-Currency
Author: Learning Python for Finance - Week 7

The 13-week cash flow forecast is the CFO's early warning system.
It answers one question: will we have enough cash, in the right entity,
in the right currency, at the right time?

This engine:
1. Takes opening cash balances per entity/currency
2. Layers in confirmed AR receipts (from sales ledger)
3. Layers in confirmed AP payments (from purchase ledger)
4. Layers in recurring fixed outflows (payroll, rent, statutory)
5. Projects week-by-week net cash position
6. Flags weeks below minimum cash threshold
7. Identifies peak funding requirements
8. Outputs a CFO-ready 13-week forecast with variance to prior week

Inputs:
- opening_balances.csv     : Cash balances per entity/currency
- ar_schedule.csv          : Confirmed receivables with expected dates
- ap_schedule.csv          : Confirmed payables with due dates
- recurring_items.csv      : Fixed recurring outflows (payroll, rent, etc.)

Output:
- 13-week forecast by entity and currency
- Weekly cash waterfall
- Minimum cash breach alerts
- Peak funding requirement summary
"""

import pandas as pd
import numpy as np
from datetime import timedelta, date


# ─────────────────────────────────────────────
# 1. CONFIG
# ─────────────────────────────────────────────

FORECAST_WEEKS   = 13
MIN_CASH_TZS     = 50_000_000    # Minimum acceptable cash balance (TZS)
MIN_CASH_USD     = 20_000        # Minimum acceptable cash balance (USD)

ENTITIES = ["Group HQ", "Entity A", "Entity B", "Entity C"]
CURRENCIES = ["TZS", "USD"]


# ─────────────────────────────────────────────
# 2. LOAD DATA
# ─────────────────────────────────────────────

def load_opening_balances(filepath: str) -> pd.DataFrame:
    """
    Opening cash balances per entity and currency.
    Expected: entity, currency, balance
    """
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    return df


def load_ar_schedule(filepath: str) -> pd.DataFrame:
    """
    Confirmed AR receipts — money coming in.
    Expected: entity, currency, expected_date, amount, customer, ref, confidence
    confidence: HIGH / MEDIUM / LOW
    """
    df = pd.read_csv(filepath, parse_dates=["expected_date"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    # Apply confidence haircut
    haircut = {"HIGH": 1.0, "MEDIUM": 0.85, "LOW": 0.60}
    df["confidence"] = df["confidence"].str.upper().fillna("MEDIUM")
    df["adjusted_amount"] = df["amount"] * df["confidence"].map(haircut)
    return df


def load_ap_schedule(filepath: str) -> pd.DataFrame:
    """
    Confirmed AP payments — money going out.
    Expected: entity, currency, due_date, amount, supplier, ref, category
    """
    df = pd.read_csv(filepath, parse_dates=["due_date"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df["adjusted_amount"] = df["amount"]  # AP is certain — no haircut
    return df


def load_recurring_items(filepath: str) -> pd.DataFrame:
    """
    Fixed recurring outflows.
    Expected: entity, currency, description, amount, frequency (WEEKLY/MONTHLY),
              day_of_week (0=Mon for WEEKLY) or day_of_month (1-28 for MONTHLY)
    """
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    return df


# ─────────────────────────────────────────────
# 3. BUILD WEEKLY BUCKETS
# ─────────────────────────────────────────────

def get_week_start(forecast_start: date) -> list:
    """Return list of 13 week-start dates (Monday)."""
    # Start from next Monday
    days_ahead = (7 - forecast_start.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    first_monday = forecast_start + timedelta(days=days_ahead)
    return [first_monday + timedelta(weeks=i) for i in range(FORECAST_WEEKS)]


def assign_week(txn_date, week_starts: list) -> int:
    """Return week index (0-12) for a transaction date."""
    for i, ws in enumerate(week_starts):
        week_end = ws + timedelta(days=6)
        if ws <= txn_date.date() <= week_end:
            return i
    if txn_date.date() < week_starts[0]:
        return 0   # overdue — put in week 1
    return -1      # beyond forecast window


def expand_recurring(recurring: pd.DataFrame,
                     week_starts: list) -> pd.DataFrame:
    """
    Expand recurring items into individual weekly occurrences.
    """
    rows = []
    for _, item in recurring.iterrows():
        for i, ws in enumerate(week_starts):
            week_end = ws + timedelta(days=6)

            if item["frequency"].upper() == "WEEKLY":
                # Falls in every week
                rows.append({
                    "entity":    item["entity"],
                    "currency":  item["currency"],
                    "week":      i,
                    "amount":    item["amount"],
                    "flow_type": "OUTFLOW",
                    "description": item["description"],
                    "category":  "RECURRING",
                })

            elif item["frequency"].upper() == "MONTHLY":
                dom = int(item.get("day_of_month", 25))
                # Check if this day falls within the week
                for d in range(7):
                    candidate = ws + timedelta(days=d)
                    if candidate.day == dom:
                        rows.append({
                            "entity":    item["entity"],
                            "currency":  item["currency"],
                            "week":      i,
                            "amount":    item["amount"],
                            "flow_type": "OUTFLOW",
                            "description": item["description"],
                            "category":  "RECURRING",
                        })
                        break

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["entity","currency","week","amount","flow_type","description","category"])


# ─────────────────────────────────────────────
# 4. BUILD FORECAST
# ─────────────────────────────────────────────

def build_forecast(opening: pd.DataFrame,
                   ar: pd.DataFrame,
                   ap: pd.DataFrame,
                   recurring: pd.DataFrame,
                   forecast_start: date = None) -> dict:
    """
    Build 13-week cash flow forecast per entity and currency.
    Returns dict of DataFrames keyed by (entity, currency).
    """
    if forecast_start is None:
        forecast_start = date.today()

    week_starts = get_week_start(forecast_start)
    week_labels = [ws.strftime("W/E %d %b") for ws in
                   [ws + timedelta(days=6) for ws in week_starts]]

    # Expand recurring into weekly rows
    rec_expanded = expand_recurring(recurring, week_starts)

    # Assign weeks to AR and AP
    ar = ar.copy()
    ap = ap.copy()
    ar["week"] = ar["expected_date"].apply(lambda d: assign_week(d, week_starts))
    ap["week"] = ap["due_date"].apply(lambda d: assign_week(d, week_starts))

    # Filter to forecast window
    ar = ar[ar["week"] >= 0]
    ap = ap[ap["week"] >= 0]

    forecasts = {}

    for entity in ENTITIES:
        for currency in CURRENCIES:
            # Opening balance
            ob_row = opening[(opening["entity"] == entity) &
                             (opening["currency"] == currency)]
            opening_bal = ob_row["balance"].values[0] if len(ob_row) else 0

            weekly = []
            running_bal = opening_bal

            for w in range(FORECAST_WEEKS):
                # Inflows from AR
                inflows = ar[
                    (ar["entity"] == entity) &
                    (ar["currency"] == currency) &
                    (ar["week"] == w)
                ]["adjusted_amount"].sum()

                # Outflows from AP
                outflows_ap = ap[
                    (ap["entity"] == entity) &
                    (ap["currency"] == currency) &
                    (ap["week"] == w)
                ]["adjusted_amount"].sum()

                # Recurring outflows
                outflows_rec = rec_expanded[
                    (rec_expanded["entity"] == entity) &
                    (rec_expanded["currency"] == currency) &
                    (rec_expanded["week"] == w)
                ]["amount"].sum() if not rec_expanded.empty else 0

                total_outflows = outflows_ap + outflows_rec
                net = inflows - total_outflows
                closing_bal = running_bal + net

                min_threshold = MIN_CASH_USD if currency == "USD" else MIN_CASH_TZS
                breach = closing_bal < min_threshold

                weekly.append({
                    "week":          w,
                    "week_label":    week_labels[w],
                    "opening":       running_bal,
                    "inflows":       inflows,
                    "outflows_ap":   outflows_ap,
                    "outflows_rec":  outflows_rec,
                    "total_outflows":total_outflows,
                    "net":           net,
                    "closing":       closing_bal,
                    "min_threshold": min_threshold,
                    "breach":        breach,
                    "headroom":      closing_bal - min_threshold,
                })
                running_bal = closing_bal

            forecasts[(entity, currency)] = pd.DataFrame(weekly)

    return forecasts, week_labels, week_starts


# ─────────────────────────────────────────────
# 5. SUMMARY VIEWS
# ─────────────────────────────────────────────

def build_group_summary(forecasts: dict) -> pd.DataFrame:
    """
    Group-level weekly cash summary across all entities (TZS only).
    """
    rows = []
    sample_weeks = None
    for (entity, currency), df in forecasts.items():
        if currency != "TZS":
            continue
        if sample_weeks is None:
            sample_weeks = df["week_label"].tolist()
        for _, row in df.iterrows():
            rows.append({
                "entity": entity,
                "week": row["week_label"],
                "closing": row["closing"],
                "breach": row["breach"],
            })

    if not rows:
        return pd.DataFrame()

    pivot = pd.DataFrame(rows).pivot_table(
        index="entity", columns="week", values="closing", aggfunc="sum"
    ).reset_index()
    return pivot


def find_breaches(forecasts: dict) -> pd.DataFrame:
    """Collect all minimum cash breaches across entities and currencies."""
    breaches = []
    for (entity, currency), df in forecasts.items():
        for _, row in df[df["breach"]].iterrows():
            breaches.append({
                "entity":        entity,
                "currency":      currency,
                "week":          row["week_label"],
                "closing_bal":   row["closing"],
                "min_threshold": row["min_threshold"],
                "shortfall":     row["closing"] - row["min_threshold"],
            })
    return pd.DataFrame(breaches)


def peak_funding_requirement(forecasts: dict) -> pd.DataFrame:
    """Identify the worst-case cash position per entity."""
    rows = []
    for (entity, currency), df in forecasts.items():
        min_row = df.loc[df["closing"].idxmin()]
        rows.append({
            "entity":      entity,
            "currency":    currency,
            "worst_week":  min_row["week_label"],
            "min_balance": min_row["closing"],
            "threshold":   min_row["min_threshold"],
            "headroom":    min_row["headroom"],
            "action_needed": min_row["headroom"] < 0,
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# 6. REPORTING
# ─────────────────────────────────────────────

def build_cashflow_report(forecasts, week_labels, breaches, peak,
                          group_summary, output_path="cashflow_forecast.xlsx"):

    total_breaches = len(breaches)
    entities_at_risk = breaches["entity"].nunique() if not breaches.empty else 0

    print(f"\n{'═'*54}")
    print(f"  13-WEEK CASH FLOW FORECAST")
    print(f"  Acacia Group — Multi-Entity")
    print(f"{'═'*54}")
    print(f"  Forecast horizon:    {week_labels[0]} → {week_labels[-1]}")
    print(f"  Entities modelled:   {len(ENTITIES)}")
    print(f"  Currencies:          {', '.join(CURRENCIES)}")
    print(f"  Cash breaches:       {total_breaches} week/entity instances")
    print(f"  Entities at risk:    {entities_at_risk}")
    print(f"\n  Peak funding requirements:")
    for _, row in peak.iterrows():
        flag = "⚠ " if row["action_needed"] else "✓ "
        print(f"  {flag}{row['entity']:<12} {row['currency']}  "
              f"worst: {row['min_balance']:>14,.0f}  "
              f"headroom: {row['headroom']:>14,.0f}")
    print(f"{'═'*54}\n")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Summary sheet
        summary_data = pd.DataFrame({
            "Metric": ["Forecast weeks", "Entities", "Cash breaches", "Entities at risk"],
            "Value":  [FORECAST_WEEKS, len(ENTITIES), total_breaches, entities_at_risk]
        })
        summary_data.to_excel(writer, sheet_name="Summary", index=False)

        # Per entity/currency forecasts
        for (entity, currency), df in forecasts.items():
            sheet_name = f"{entity[:8]} {currency}"
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # Group summary
        if not group_summary.empty:
            group_summary.to_excel(writer, sheet_name="Group TZS Summary", index=False)

        # Breaches
        if not breaches.empty:
            breaches.to_excel(writer, sheet_name="Cash Breaches", index=False)

        # Peak funding
        peak.to_excel(writer, sheet_name="Peak Funding", index=False)

    print(f"  Report saved → {output_path}")


# ─────────────────────────────────────────────
# 7. MAIN RUNNER
# ─────────────────────────────────────────────

def run_cashflow_forecast(opening_path, ar_path, ap_path, recurring_path,
                          output_path="cashflow_forecast.xlsx",
                          forecast_start: date = None):

    print(f"\n{'═'*54}")
    print(f"  13-WEEK CASH FLOW FORECASTER")
    print(f"  Acacia Group — Multi-Entity, Multi-Currency")
    print(f"{'═'*54}\n")

    opening   = load_opening_balances(opening_path)
    ar        = load_ar_schedule(ar_path)
    ap        = load_ap_schedule(ap_path)
    recurring = load_recurring_items(recurring_path)

    print(f"  AR receipts loaded:  {len(ar)}")
    print(f"  AP payments loaded:  {len(ap)}")
    print(f"  Recurring items:     {len(recurring)}\n")

    forecasts, week_labels, _ = build_forecast(
        opening, ar, ap, recurring, forecast_start)

    breaches      = find_breaches(forecasts)
    peak          = peak_funding_requirement(forecasts)
    group_summary = build_group_summary(forecasts)

    build_cashflow_report(forecasts, week_labels, breaches,
                          peak, group_summary, output_path)


# ─────────────────────────────────────────────
# 8. DEMO
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import os
    np.random.seed(7)
    os.makedirs("/tmp/cf_demo", exist_ok=True)
    START = date(2025, 3, 3)  # Monday

    # Opening balances
    pd.DataFrame([
        {"entity":"Group HQ", "currency":"TZS", "balance": 280_000_000},
        {"entity":"Group HQ", "currency":"USD", "balance":     85_000},
        {"entity":"Entity A", "currency":"TZS", "balance": 120_000_000},
        {"entity":"Entity A", "currency":"USD", "balance":     42_000},
        {"entity":"Entity B", "currency":"TZS", "balance":  95_000_000},
        {"entity":"Entity B", "currency":"USD", "balance":     18_000},
        {"entity":"Entity C", "currency":"TZS", "balance":  45_000_000},
        {"entity":"Entity C", "currency":"USD", "balance":      8_500},
    ]).to_csv("/tmp/cf_demo/opening_balances.csv", index=False)

    # AR schedule — confirmed receivables
    ar_rows = []
    customers = ["EU Client A","EU Client B","Domestic Buyer","Export DE","Local Dist"]
    for i in range(18):
        entity = np.random.choice(ENTITIES)
        currency = np.random.choice(["TZS","USD"], p=[0.6,0.4])
        days_out = np.random.randint(3, 85)
        amount = int(np.random.choice([
            8_000_000, 15_000_000, 22_000_000, 5_000_000, 30_000_000
        ]) if currency=="TZS" else np.random.choice([
            8_000, 15_000, 22_000, 5_000, 30_000
        ]))
        ar_rows.append({
            "entity": entity, "currency": currency,
            "expected_date": (START + timedelta(days=days_out)).strftime("%Y-%m-%d"),
            "amount": amount,
            "customer": np.random.choice(customers),
            "ref": f"AR-{i+1:03d}",
            "confidence": np.random.choice(["HIGH","HIGH","MEDIUM","LOW"])
        })
    pd.DataFrame(ar_rows).to_csv("/tmp/cf_demo/ar_schedule.csv", index=False)

    # AP schedule — confirmed payables
    ap_rows = []
    suppliers = ["Supplier Alpha","Supplier Beta","Logistics Co","Packaging Ltd","Fuel Co"]
    for i in range(22):
        entity = np.random.choice(ENTITIES)
        currency = np.random.choice(["TZS","USD"], p=[0.7,0.3])
        days_out = np.random.randint(2, 80)
        amount = int(np.random.choice([
            3_000_000, 7_000_000, 12_000_000, 4_500_000, 18_000_000
        ]) if currency=="TZS" else np.random.choice([
            3_000, 7_000, 12_000, 4_500, 18_000
        ]))
        ap_rows.append({
            "entity": entity, "currency": currency,
            "due_date": (START + timedelta(days=days_out)).strftime("%Y-%m-%d"),
            "amount": amount,
            "supplier": np.random.choice(suppliers),
            "ref": f"AP-{i+1:03d}",
            "category": np.random.choice(["SUPPLIER","LOGISTICS","UTILITIES"])
        })
    pd.DataFrame(ap_rows).to_csv("/tmp/cf_demo/ap_schedule.csv", index=False)

    # Recurring items
    pd.DataFrame([
        {"entity":"Group HQ", "currency":"TZS", "description":"Group payroll",         "amount":45_000_000, "frequency":"MONTHLY", "day_of_month":25},
        {"entity":"Entity A", "currency":"TZS", "description":"Entity A payroll",       "amount":28_000_000, "frequency":"MONTHLY", "day_of_month":25},
        {"entity":"Entity B", "currency":"TZS", "description":"Entity B payroll",       "amount":22_000_000, "frequency":"MONTHLY", "day_of_month":25},
        {"entity":"Entity C", "currency":"TZS", "description":"Entity C payroll",       "amount":12_000_000, "frequency":"MONTHLY", "day_of_month":25},
        {"entity":"Group HQ", "currency":"TZS", "description":"Office rent",            "amount": 8_500_000, "frequency":"MONTHLY", "day_of_month":1},
        {"entity":"Entity A", "currency":"TZS", "description":"Processing facility rent","amount": 5_200_000, "frequency":"MONTHLY", "day_of_month":1},
        {"entity":"Entity B", "currency":"TZS", "description":"Cold storage lease",     "amount": 3_800_000, "frequency":"MONTHLY", "day_of_month":1},
        {"entity":"Group HQ", "currency":"TZS", "description":"TRA VAT payment",        "amount":18_000_000, "frequency":"MONTHLY", "day_of_month":20},
        {"entity":"Group HQ", "currency":"USD", "description":"USD loan repayment",     "amount":     5_000, "frequency":"MONTHLY", "day_of_month":15},
        {"entity":"Entity A", "currency":"USD", "description":"Equipment lease USD",    "amount":     2_500, "frequency":"MONTHLY", "day_of_month":10},
    ]).to_csv("/tmp/cf_demo/recurring_items.csv", index=False)

    run_cashflow_forecast(
        opening_path="/tmp/cf_demo/opening_balances.csv",
        ar_path="/tmp/cf_demo/ar_schedule.csv",
        ap_path="/tmp/cf_demo/ap_schedule.csv",
        recurring_path="/tmp/cf_demo/recurring_items.csv",
        output_path="/tmp/cashflow_forecast_demo.xlsx",
        forecast_start=START
    )
