# 04 · Payroll Validator

Validates monthly payroll against Tanzania statutory deduction rules for 2024/25. Catches PAYE, NSSF, NHIF, WCF, and SDL errors before submission — and flags unusual salary movements month-on-month.

---

## The Problem

Processing payroll for 135+ employees across six entities means 135+ opportunities for statutory deduction errors each month. PAYE is progressive and easy to miscalculate at band boundaries. NHIF bands shift with salary changes. NSSF has a cap that catches out new staff. SDL and WCF are straightforward but easy to omit entirely on new cost centres.

Errors discovered by TRA are more expensive than errors caught internally.

---

## Statutory Rules Implemented

### PAYE — Progressive Bands (TRA CAP 332, 2024/25)

| Monthly Gross (TZS) | Rate |
|---------------------|------|
| 0 – 270,000 | 0% |
| 270,001 – 520,000 | 8% |
| 520,001 – 760,000 | 20% |
| 760,001 – 1,000,000 | 25% |
| 1,000,001+ | 30% |

### NSSF
- Employee: 10% of gross, capped at TZS 8,000/month
- Employer: 10% of gross, capped at TZS 8,000/month

### NHIF
Graduated bands based on gross salary (15 bands from TZS 0 to 1,000,000+). Output ranges from TZS 400 to TZS 15,000/month.

### WCF
0.5% of gross salary — employer contribution only.

### SDL
4.5% of gross salary — employer contribution only. Skills Development Levy payable to TRA.

---

## Validation Logic

For each employee the engine:
1. Computes the correct statutory deductions from gross salary
2. Compares to submitted figures
3. Flags any variance > TZS 5 (rounding tolerance)
4. Labels the exception field(s): PAYE / NSSF_EE / NSSF_ER / NHIF / WCF / SDL

### Month-on-Month Spike Detection

If the prior month gross is provided, the engine calculates the gross change percentage and flags any employee with a move > ±20%. This catches:
- Ghost employees added mid-month
- Promotions processed incorrectly
- Salary continuation errors after termination
- Data entry mistakes

---

## Input Format

**Payroll CSV** (`march_payroll.csv`):
```
emp_id,name,entity,department,gross,prev_gross,paye_submitted,nssf_ee_submitted,nssf_er_submitted,nhif_submitted,wcf_submitted,sdl_submitted,net_submitted
EMP001,Amina Rashid,Group HQ,Finance,320000,295000,4000,8000,8000,7500,1600,14400,294100
```

`prev_gross` is optional — omit if prior month comparison isn't needed.

---

## Output

6-tab Excel workbook `payroll_validation.xlsx`:

| Tab | Contents |
|-----|----------|
| Summary | Totals by deduction type, exception count |
| Full Validation | All employees with calculated vs submitted |
| Exceptions | Only employees with variances |
| Deduction Summary | Aggregate by deduction type with variance |
| Entity Breakdown | Totals per entity (Group HQ / Entity B / Entity A / Entity C) |
| MoM Variance | Gross movements sorted by % change |

---

## Usage

```python
from payroll_validator import run_payroll_validation

run_payroll_validation(
    payroll_path="march_payroll.csv",
    output_path="payroll_validation.xlsx"
)
```

---

## Quick Reference — Effective PAYE Rates

| Gross (TZS) | PAYE | Effective Rate |
|-------------|------|----------------|
| 200,000 | 0 | 0.0% |
| 400,000 | 10,400 | 2.6% |
| 600,000 | 41,600 | 6.9% |
| 900,000 | 91,600 | 10.2% |
| 1,500,000 | 241,600 | 16.1% |
| 3,000,000 | 691,600 | 23.1% |

---

## Sample Output

```
══════════════════════════════════════════════════
  PAYROLL VALIDATION SUMMARY
  Acacia Group Group — 20 employees
══════════════════════════════════════════════════
  Total gross:        TZS    16,585,000
  Total PAYE:         TZS     2,639,350
  Total NSSF (EE):    TZS       148,000
  Total NSSF (ER):    TZS       148,000
  Total NHIF:         TZS       199,000
  Total WCF:          TZS        82,925
  Total SDL:          TZS       746,325
  Total employer cost:TZS    17,562,250
  ──────────────────────────────────────────────
  Exceptions flagged: 5 / 20
  Gross spikes (>20%): 1
```
