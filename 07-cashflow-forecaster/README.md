# 07 · 13-Week Rolling Cash Flow Forecaster

Projects a 13-week rolling cash position per entity and currency, layering confirmed AR receipts, AP payments, and recurring outflows onto opening balances. Flags weeks where cash falls below a minimum threshold and identifies peak funding requirements.

---

## The Problem

Month-end tells you where you were. The 13-week forecast tells you where you're going.

In a multi-entity group with payroll hitting on the 25th, VAT due on the 20th, and export receipts arriving unpredictably, you need to know three weeks in advance which entity will be short — and by how much. Finding out on the day is too late.

This tool gives the CFO an early warning system, updated weekly.

---

## How It Works

```
Opening Balances (per entity/currency)
           +
AR Schedule  →  Confidence haircut applied
           -
AP Schedule  →  100% (certain obligations)
           -
Recurring    →  Payroll / Rent / VAT / Loan repayments
           =
Weekly net cash position × 13 weeks
           →
Breach alerts where closing < minimum threshold
Peak funding requirement summary
```

### Confidence Haircuts on AR

Not all expected receipts are equally certain. The engine applies haircuts before projecting:

| Confidence | Haircut | Use when |
|------------|---------|----------|
| `HIGH` | 100% | Signed contract, invoice accepted |
| `MEDIUM` | 85% | Invoice sent, no disputes |
| `LOW` | 60% | Verbal commitment, early stage |

AP payments get no haircut — if it's due, it goes out.

---

## Input Files

**`opening_balances.csv`**
```
entity,currency,balance
Group HQ,TZS,280000000
Group HQ,USD,85000
```

**`ar_schedule.csv`** — confirmed receivables
```
entity,currency,expected_date,amount,customer,ref,confidence
Group HQ,TZS,2025-03-15,30000000,EU Client A,AR-001,HIGH
Entity A,USD,2025-03-22,15000,Domestic Buyer,AR-002,MEDIUM
```

**`ap_schedule.csv`** — confirmed payables
```
entity,currency,due_date,amount,supplier,ref,category
Group HQ,TZS,2025-03-10,12000000,Supplier Alpha,AP-001,SUPPLIER
```

**`recurring_items.csv`** — fixed outflows
```
entity,currency,description,amount,frequency,day_of_month
Group HQ,TZS,Group payroll,45000000,MONTHLY,25
Group HQ,TZS,TRA VAT payment,18000000,MONTHLY,20
Group HQ,USD,USD loan repayment,5000,MONTHLY,15
```

---

## Output

Excel workbook `cashflow_forecast.xlsx`:

| Tab | Contents |
|-----|----------|
| Summary | Horizon, breach count, entities at risk |
| Group HQ TZS | 13-week weekly waterfall |
| Group HQ USD | 13-week weekly waterfall |
| Entity A TZS | ... (one tab per entity/currency) |
| Group TZS Summary | Pivot — all entities × 13 weeks |
| Cash Breaches | All breach weeks with shortfall amount |
| Peak Funding | Worst-case position per entity with action flag |

---

## Usage

```python
from cashflow_forecaster import run_cashflow_forecast
from datetime import date

run_cashflow_forecast(
    opening_path="sample_data/opening_balances.csv",
    ar_path="sample_data/ar_schedule.csv",
    ap_path="sample_data/ap_schedule.csv",
    recurring_path="sample_data/recurring_items.csv",
    output_path="cashflow_forecast.xlsx",
    forecast_start=date(2025, 3, 3)
)
```

---

## Minimum Cash Thresholds

| Currency | Default Minimum | Rationale |
|----------|----------------|-----------|
| TZS | 50,000,000 | ~1 week payroll buffer |
| USD | 20,000 | ~1 month FX obligations |

Change these in the script config section to match your group's liquidity policy.

---

## Sample Data

Ready-to-run synthetic data in `sample_data/` (opening_balances.csv + ar_schedule.csv + ap_schedule.csv + recurring_items.csv).

```bash
cd 07-cashflow-forecaster
python cashflow_forecaster.py
```

---

## Sample Output

```
══════════════════════════════════════════════════════
  13-WEEK CASH FLOW FORECAST
  Acacia Group — Multi-Entity
══════════════════════════════════════════════════════
  Forecast horizon:    W/E 16 Mar → W/E 08 Jun
  Entities modelled:   4
  Currencies:          TZS, USD
  Cash breaches:       3 week/entity instances
  Entities at risk:    2

  Peak funding requirements:
  ✓ Group HQ     TZS  worst:   212,500,000  headroom:   162,500,000
  ✓ Group HQ     USD  worst:        68,000  headroom:        48,000
  ✓ Entity A     TZS  worst:    78,300,000  headroom:    28,300,000
  ✓ Entity A     USD  worst:        32,500  headroom:        12,500
  ⚠ Entity B     TZS  worst:    38,100,000  headroom:   -11,900,000
  ⚠ Entity C     TZS  worst:    19,400,000  headroom:   -30,600,000
  ⚠ Entity C     USD  worst:         3,200  headroom:   -16,800
```
