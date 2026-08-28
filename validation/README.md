# S5 — Synthetic validation dataset and example output

A small, fully synthetic worked example that lets a reader confirm the HBOD core
reproduces the published numbers. Inputs → expected indices, decisions and
rationale, end to end.

## Files

| File                        | What                                                                                                             |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `S5_validation_dataset.csv` | 5 synthetic athletes × 28 days ending **2026-03-31** (Sundays are rest days). English Google-Form-style headers. |
| `S5_example_output.txt`     | The plain-text daily report the core produces from the dataset.                                                  |
| `S5_example_report.html`    | The same run as the HTML coach report.                                                                           |
| `S5_example_audit.csv`      | The audit log for the run — one row per athlete with the computed indices.                                       |

## The five cases (one per decision branch)

| Athlete   | Construction                                                   | Expected decision                                                    |
| --------- | -------------------------------------------------------------- | -------------------------------------------------------------------- |
| Athlete 1 | Load tapered in the final week                                 | **INCREASE** — ACWR 0.67 (< 0.80) **and** wellness at/above baseline |
| Athlete 2 | Steady, balanced load and wellness with uncoupled chronic mean | **DECREASE** — ACWR 1.33 (> 1.30)                                    |
| Athlete 3 | One very large session on the last day                         | **DECREASE** — ACWR 1.81 (> 1.30) and acute load spike               |
| Athlete 4 | Wellness collapses over the last 3 days                        | **DECREASE** — wellness −4.44 SD below personal baseline             |
| Athlete 5 | Substantial OSTRC problem + daily pain in the final week       | **DECREASE / REDUCE & REFER** — health override (OSTRC severity 47)  |

Squad result: **INCREASE 1 · MAINTAIN 0 · DECREASE 4**, one health referral.

## Reproduce

From the repository root. Write the regenerated run to `output/` and leave the
shipped reference files untouched, so the check compares against a clean copy:

```bash
mkdir -p output
rm -f output/S5_regen_audit.csv
python core/hbd_agent.py --input validation/S5_validation_dataset.csv \
    --date 2026-03-31 --out output/S5_regen_report.html \
    --log output/S5_regen_audit.csv --mode daily
```

`--log` **appends** to its target rather than overwriting it. Always point it at
a fresh path (or delete the file first, as above); re-running with `--log
validation/S5_example_audit.csv` would duplicate rows into the reference file
and a positional comparison against a stale log can appear to pass when it has
not been rerun at all.

Then compare against the reference, ignoring the first column
(`generated_at`, a wall-clock stamp that differs by design):

```bash
diff <(cut -d, -f2- validation/S5_example_audit.csv) \
     <(cut -d, -f2- output/S5_regen_audit.csv)
```

Expected: no output. The regenerated audit holds 5 rows — one per athlete —
matching the reference on all 12 non-timestamp fields, with squad decisions
**INCREASE 1 · MAINTAIN 0 · DECREASE 4**.

Every index and decision is deterministic, so re-running yields the same numbers.
The dataset was produced by a fixed generator with no randomness — see the header
of this folder in the manuscript's Supplementary Materials for the construction
rules above.
