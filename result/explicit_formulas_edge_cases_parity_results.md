# HBD Results: Explicit Formulas, Edge-Case Handling, and Quantitative Parity Tests

Date: 2026-07-22
Project: HBDApp deterministic core
Primary sources: core/hbd_agent.py, validation/README.md, validation/S5_example_audit.csv, output/S5_regen_audit.csv

## 1. Explicit formulas

All metrics are deterministic and computed by the decision core.

### 1.1 Session and workload metrics

- Session load (AU):
  - session_load = duration_min \* RPE
- Daily load (AU):
  - daily_load(d) = sum(session_load on day d)
- 7-day weekly load (AU):
  - weekly*load(t) = sum*{i=0..6} daily_load(t - i)
- Acute mean (AU/day):
  - acute_mean(t) = weekly_load(t) / 7
- Chronic mean (AU/day):
  - chronic*mean(t) = (sum*{i=7..34} daily_load(t - i)) / 28

  (uncoupled: the acute 7-day period is excluded from the chronic denominator)

Note: missing/rest days are imputed as daily_load = 0 inside calendar windows.

### 1.2 Monotony and strain

- Let acute_window(t) be 7 daily loads ending at t.
- Population SD over acute_window:
  - sd_acute(t) = pstdev(acute_window(t))
- Monotony:
  - monotony(t) = acute_mean(t) / sd_acute(t), only if sd_acute > 0 and at least 2 days
- Strain:
  - strain(t) = weekly_load(t) \* monotony(t), only if monotony is defined

### 1.3 ACWR and acute spike

- ACWR:
  - acwr(t) = acute_mean(t) / chronic_mean(t), only if chronic_mean > 0
  - with uncoupled windows: acute uses [t-6..t], chronic uses [t-34..t-7]
- Acute spike (today vs prior 7-day mean):
  - prior_mean(t) = mean(daily_load(t-7) ... daily_load(t-1), available observed days)
  - acute_spike(t) = daily_load(t) / prior_mean(t), only if prior_mean > 0

### 1.4 Wellness composite and z-score

Input scale is Hooper 1..7 where 1 is best and 7 is worst. Core flips direction per item:

- transformed_item = 8 - raw_item
- Wellness composite (higher is better):
  - wellness(t) = mean(transformed sleep, fatigue, stress, soreness for day t)

Personal baseline z-score over prior 28 days:

- baseline = all non-null wellness values on [t-28, t-1]
- wellness_z(t) = (wellness(t) - mean(baseline)) / pstdev(baseline)
- wellness_z is defined only when:
  - wellness(t) exists
  - count(baseline) >= 3
  - pstdev(baseline) > 0

### 1.5 Decision thresholds

Constants:

- ACWR_LOW = 0.80
- ACWR_HIGH = 1.30
- ACWR_RED = 1.50
- MONOTONY_HIGH = 2.0
- WELLNESS_DROP_Z = -1.0
- WELLNESS_GOOD_Z = 0.0
- ACUTE_SPIKE_RATIO = 1.5

Rules:

- DECREASE if any red condition is present:
  - acwr >= 1.50, or acwr > 1.30 (caution red reason)
  - wellness_z <= -1.0
  - monotony >= 2.0
  - acute_spike >= 1.5
- INCREASE if at least 2 green conditions:
  - acwr < 0.80
  - wellness_z >= 0.0
- MAINTAIN otherwise.

### 1.6 Health override logic (priority over load/wellness)

OSTRC-derived terms:

- severity = OSTRC_Q1 + OSTRC_Q2 + OSTRC_Q3 + OSTRC_Q4
- substantial problem if any of Q1..Q3 >= 17
- cannot participate if any of Q1..Q3 >= 25

Override tiers:

- STOP: cannot participate => force DECREASE + urgent medical wording
- REFER: substantial problem => force DECREASE + reduce-and-refer wording
- HOLD: any health flag/pain => never allow INCREASE; INCREASE downgrades to MAINTAIN

## 2. Edge-case handling implemented in code

### 2.1 Input parsing and normalization

- Header mapping is substring-based and bilingual (French/English).
- Numeric parsing:
  - commas are normalized to decimal points
  - leading numeric token is extracted from mixed text (example pattern: "5 - Beaucoup")
  - invalid numeric text => null
- Yes/no parsing supports English, French, and Arabic tokens.
- Date parsing:
  - strips trailing timezone markers like UTC+1 or GMT+1
  - attempts multiple datetime formats
  - fallback: first 10 chars parsed as ISO date
  - unparsable dates => null

### 2.2 Row acceptance and missing data

- Blank rows are skipped.
- A record contributes session_load only if athlete, duration, and intensity are present.
- For per-day load windows, missing days are treated as zero load.
- Wellness composite is null if all wellness components are missing.

### 2.3 Safe metric guards

- Monotony is null when SD is zero or insufficient points.
- Strain is null when monotony is null.
- ACWR is null when chronic mean is zero.
- Acute spike is null when prior mean is zero.
- Wellness z-score is null unless baseline has at least 3 values and non-zero SD.

### 2.4 Data confidence tier

Using distinct logged days in last 28 days:

- high: >= 14 days
- moderate: >= 7 days
- low: < 7 days

Low confidence does not force a decision change, but adds caution text.

## 3. Quantitative parity and test results

### 3.1 Reproduction run

Command executed:

python core/hbd_agent.py --input validation/S5_validation_dataset.csv --date 2026-03-31 --out output/S5_regen_report.html --log output/S5_regen_audit.csv --mode daily

Observed decision distribution:

- DECREASE: 4
- MAINTAIN: 0
- INCREASE: 1

This no longer matches the legacy S5 expected branch coverage, because ACWR now uses the uncoupled denominator.

### 3.2 Field-level parity test against expected audit

Compared files:

- expected: validation/S5_example_audit.csv
- regenerated: output/S5_regen_audit.csv

Compared fields per athlete:

- decision
- acwr
- wellness
- wellness_z
- monotony
- strain
- weekly_load
- daily_load
- reasons

Quantitative result:

- TOTAL_COMPARISONS = 45
- MATCHED = 34
- MISMATCHED = 11
- Exact parity = 75.6%

Interpretation:

- Differences are expected after switching ACWR from coupled to uncoupled windows.
- Most drifts are ACWR values and rationale strings that include ACWR-driven thresholds.
- Legacy parity artifacts should be regenerated if uncoupled ACWR becomes the new baseline.

## 4. Artifact list generated in this run

- output/S5_regen_report.html
- output/S5_regen_audit.csv
- result/explicit_formulas_edge_cases_parity_results.md

## 5. Notes

- generated_at timestamps in audit logs are expected to differ by runtime clock and are not a deterministic metric output.
- This report reflects uncoupled ACWR; historical coupled-ACWR parity numbers are retained only as legacy context.
