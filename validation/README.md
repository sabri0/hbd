# S5 — Synthetic validation dataset and example output

A small, fully synthetic worked example that lets a reader confirm the HBD core
reproduces the published numbers. Inputs → expected indices, decisions and
rationale, end to end.

## Files

| File | What |
|---|---|
| `S5_validation_dataset.csv` | 5 synthetic athletes × 28 days ending **2026-03-31** (Sundays are rest days). English Google-Form-style headers. |
| `S5_example_output.txt` | The plain-text daily report the core produces from the dataset. |
| `S5_example_report.html` | The same run as the HTML coach report. |
| `S5_example_audit.csv` | The audit log for the run — one row per athlete with the computed indices. |

## The five cases (one per decision branch)

| Athlete | Construction | Expected decision |
|---|---|---|
| Athlete 1 | Load tapered in the final week | **INCREASE** — ACWR 0.57 (< 0.80) **and** wellness at/above baseline |
| Athlete 2 | Steady, balanced load and wellness | **MAINTAIN** |
| Athlete 3 | One very large session on the last day | **DECREASE** — acute load spike (2.73× recent mean) |
| Athlete 4 | Wellness collapses over the last 3 days | **DECREASE** — wellness −4.44 SD below personal baseline |
| Athlete 5 | Substantial OSTRC problem + daily pain in the final week | **DECREASE / REDUCE & REFER** — health override (OSTRC severity 47) |

Squad result: **INCREASE 1 · MAINTAIN 1 · DECREASE 3**, one health referral.

## Reproduce

From the repository root:

```bash
python core/hbd_agent.py --input validation/S5_validation_dataset.csv \
    --date 2026-03-31 --out validation/S5_example_report.html \
    --log validation/S5_example_audit.csv --mode daily
```

Every index and decision is deterministic, so re-running yields the same numbers
(only the audit log's `generated_at` wall-clock stamp differs). The dataset was
produced by a fixed generator with no randomness — see the header of this folder
in the manuscript's Supplementary Materials for the construction rules above.
