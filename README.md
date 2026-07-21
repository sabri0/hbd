# HBD — Training-Load & Wellness Monitor

**Supplementary Materials** for the manuscript *Hooper–Borg–Dergaa (HBD): a deterministic, auditable framework for daily training-load and wellness monitoring in team sport.*

This repository is the reference implementation described in the article. It bundles the free web application, the deterministic decision core and its code listing, the synthetic validation data, and the orchestration/deployment assets — everything needed to reproduce every number, figure and recommendation reported in the paper.

**HBD** is a daily training-load and wellness monitor for sports teams. Each athlete submits a 60-second self-report; a **deterministic** decision core computes validated sport-science indices per athlete and recommends the next day's training direction — **INCREASE**, **MAINTAIN** or **DECREASE** — with a full, auditable rationale for the coach.

> Recommendations are decision support, not verdicts. The coach always judges. The tool never advises loading an athlete who reported a health problem.

---

## Contents

1. [Supplementary Materials index (S1–S6)](#1-supplementary-materials-index-s1s6)
2. [The daily cycle (BPMN)](#2-the-daily-cycle-bpmn)
3. [The science — indices and definitions](#3-the-science--indices-and-definitions)
4. [Decision logic](#4-decision-logic-auditable-thresholds)
5. [Health module and override](#5-health-module-and-override)
6. [Wellness flags and coaching advice](#6-wellness-flags-and-coaching-advice)
7. [Extended metrics](#7-extended-metrics)
8. [Reporting cadence](#8-reporting-cadence)
9. [Data model and input format](#9-data-model-and-input-format)
10. [Repository layout](#10-repository-layout)
11. [The deterministic core (`hbd_agent.py`)](#11-the-deterministic-core-hbd_agentpy)
12. [The web application](#12-the-web-application)
13. [Running it](#13-running-it)
14. [Configuration](#14-configuration)
15. [Orchestration alternative (n8n)](#15-orchestration-alternative-n8n)
16. [Reproducibility, audit and governance](#16-reproducibility-audit-and-governance)
17. [License and attribution](#17-license-and-attribution)

---

## 1. Supplementary Materials index (S1–S6)

Every metric is computed **deterministically**. Generative AI, where used, only rephrases already-computed output — it never alters a value.

| Item | File(s) | Description |
|---|---|---|
| **S1** | `HBD_App.html` | Free, standalone single-file web application. Runs in any browser and computes entirely on the client — no server, no install, no data upload. The same deterministic logic as the core; suitable for a single coach with no infrastructure. *(The `app/` + `core/` in this repo is the full server-backed equivalent with a multi-athlete dashboard, scheduler and audit log.)* |
| **S2** | `core/hbd_agent.py`, `HBD_Supplementary_Code.html` | The deterministic decision core and a rendered, syntax-highlighted listing of its source. `hbd_agent.py` is the portable, zero-web-dependency implementation of every index, threshold and decision; the HTML listing is the same code for review and reproducibility. |
| **S3** | *analysis prompt* | The generative-AI analysis prompt used to produce a narrative interpretation of the computed data. Constrains the model to describing and contextualising the deterministic outputs — it cannot recompute, override or invent metrics. |
| **S4** | `S4_HBOD_Monitoring_Form.docx` | The daily monitoring form template: every field and its response scale (see [§9](#9-data-model-and-input-format)). |
| **S5** | *synthetic dataset + example output* | A small synthetic dataset with its corresponding worked example output, used to validate the pipeline: given inputs → expected indices, decision and rationale. Lets a reader confirm the core reproduces the published numbers. |
| **S6** | `data/cohort_football_100.csv`, `data/S6_HBD_Synthetic_Cohort_100players.xlsx` | A synthetic 100-player football cohort, as a comma-separated file and as an Excel workbook. The workbook holds three sheets — raw data, computed per-player metrics, and variable definitions — plus the supplementary figures: the squad wellness heatmap, the exponentially-weighted vs. rolling workload (ACWR) ratio, and the readiness-score distribution. |

Companion documents also provided: `HBOD_Manuscript_BiologyOfSport - ID.docx` (the manuscript). Items marked *italic* are external artifacts referenced by the article; the code, data and deployment assets they describe are all in this repository.

---

## 2. The daily cycle (BPMN)

```
ATHLETE          end of training day ──► complete daily self-report
                                          (duration · RPE · Hooper wellness · pain · weekly OSTRC-H)
FORM & STORAGE   response recorded in the responses sheet (CSV)
HBD SYSTEM       timer 20:00 ──► ingest ──► parse & map columns (bilingual headers)
                 ──► compute per-athlete metrics ──► health problem today? ──► apply health override
                 ──► decide next-day load (+ rationale & strategy)
                 ──► build daily report (HTML + text) ──► append audit log ──► email / serve to coach
COACH            review report & rationale ──► set tomorrow's session load ──► cycle complete
```

All metrics and decisions are computed **deterministically** in the core. The workflow layer (web-app scheduler or n8n) only schedules, fetches, runs and sends. A language model, if used downstream, may only rephrase output — it never changes a metric.

---

## 3. The science — indices and definitions

Every index below is computed per athlete on a reference day from that athlete's own history. Rest days count as a load of 0, as required for Foster monotony/strain and for ACWR baselines.

| Index | Definition | Units / range | Reference |
|---|---|---|---|
| **Session load** | session duration (min) × RPE | AU | Foster session-RPE |
| **Daily load** | sum of that day's session loads | AU | — |
| **Weekly load** | sum of daily loads over the 7-day acute window | AU | Foster 1998 |
| **Acute mean** | mean daily load over 7 days | AU/day | — |
| **Chronic mean** | mean daily load over 28 days | AU/day | — |
| **Monotony** | acute mean ÷ SD of the 7 daily loads (population SD; needs ≥2 days, SD > 0) | ratio | Foster 1998 |
| **Strain** | weekly load × monotony | AU | Foster 1998 |
| **ACWR** | acute mean ÷ chronic mean; reference band 0.80–1.30, red ≥ 1.50 | ratio | Hulin & Gabbett, BJSM 2019 |
| **Acute spike** | today's load ÷ mean of the prior 7 days (today excluded) | ratio | — |
| **Wellness composite** | mean of the 4 Hooper items (fatigue, stress, soreness, sleep), each recorded 1 = best … 7 = worst and flipped to `8 − x` so **higher = better** | ~1–7 | Hooper & Mackinnon |
| **Wellness z-score** | (today's composite − 28-day personal baseline mean) ÷ baseline SD (needs ≥3 baseline days, SD > 0) | SD | — |
| **Data confidence** | days logged in the last 28: ≥14 = *high*, ≥7 = *moderate*, else *low* (adds a caution note) | tier | — |

All windows are **calendar** windows anchored on the reference day, so a missed day lowers the mean rather than being skipped.

---

## 4. Decision logic (auditable thresholds)

The next-day direction is chosen from explicit, named thresholds (all defined at the top of `core/hbd_agent.py`):

- **DECREASE** — any red flag:
  - ACWR ≥ **1.50** (or > **1.30**, caution band),
  - wellness ≤ **−1.0 SD** below personal baseline,
  - monotony ≥ **2.0**,
  - acute spike ≥ **1.5×** the recent mean.
- **INCREASE** — at least **two** green signals: ACWR < **0.80** **and** wellness at/above baseline (z ≥ 0).
- **MAINTAIN** — everything else.

Low data confidence never changes the direction on its own; it appends an *"interpret with caution"* note to the rationale. Each firing threshold is written into the rationale in plain language (e.g. *"acute load spike (2.0x recent mean)"*), so the coach can trace any call back to its numbers. A deterministic **strategy** string (concrete coaching action) is attached to every decision.

---

## 5. Health module and override

Health sits **above** load and wellness in three graded tiers. The tool never advises loading an athlete who flagged a health problem.

- **Daily pain gate** — a per-day yes/no pain flag with optional location.
- **Weekly OSTRC-H** (Clarsen 2014) — four items scored 0–25; **severity = sum(Q1..Q4)**, range **0–100**. A *substantial problem* = any of the first three items (participation, training volume, performance) ≥ **17**. *Could not participate* = any of those three ≥ **25**.

| Tier | Trigger | Action |
|---|---|---|
| **HOLD** | any reported pain / minor flag | never increase (INCREASE → MAINTAIN), monitor |
| **REDUCE & REFER** | substantial OSTRC problem (item ≥ 17) | cut load, refer to medical staff |
| **STOP** | "could not participate" (item ≥ 25) | no training, urgent medical assessment |

The override rewrites both the decision and the strategy, and prepends the health reason to the rationale.

---

## 6. Wellness flags and coaching advice

So that wellness — not only load — can drive the call, the core raises plain-language flags from the Hooper items and maps each to a concrete, evidence-based, **advisory** behavioural suggestion (anything clinical goes to the medical staff):

- **Sleep** — flagged if last night ≥ 5/7, or the 7-day mean ≥ 4.5/7 → sleep-hygiene guidance.
- **Fatigue** — flagged if ≥ 6/7 → recovery-day / extended-sleep guidance.
- **Stress** — flagged if ≥ 6/7 → check school/home/competition load, consider psychological support.
- **Soreness** — distinguishes a likely recent-load (DOMS) pattern from a persistent niggle worth checking.

---

## 7. Extended metrics

Derived from the same inputs and surfaced in the report and dashboard:

| Metric | Definition | Reference |
|---|---|---|
| **EWMA-ACWR** | exponentially-weighted ACWR (acute span 7, chronic span 28, 42-day look-back) | Williams 2017 |
| **Weekly ramp %** | (this week − last week) ÷ last week × 100 | Gabbett 2016 |
| **Training stress balance (TSB)** | chronic mean − acute mean (positive = freshening, negative = fatiguing) | — |
| **Hooper total** | sum of the four Hooper items as recorded (range 4–28, higher = worse) | Hooper & Mackinnon |
| **Sleep index** | today's value, 7-day mean, and a "sleep debt" flag when the weekly mean ≥ 4.5/7 | — |
| **Readiness score** | 0–100 heuristic blending wellness-vs-baseline and the workload ratio (documented in code) | — |

---

## 8. Reporting cadence

Mirrors the BPMN timer (daily 20:00). In `auto` mode the agent issues the daily report plus any review that is due:

- **Daily** — always.
- **Weekly** — Saturdays (7-day load, sleep, fatigue, trend per athlete).
- **Monthly** — the last Saturday of the month (28-day review).
- **Quarterly** — the last Saturday of Mar/Jun/Sep/Dec (90-day review + a next-mesocycle draft: deload / build / hold per athlete).

---

## 9. Data model and input format

Input is a Google-Form-style responses **CSV or XLSX**. Column matching is by **substring** and **bilingual** (English **or** French headers); yes/no answers accept French, English and Arabic. The timestamp parser tolerates many date formats and trailing time-zones (e.g. `UTC+1`). The shipped `data/cohort_football_100.csv` uses English headers:

```
Timestamp, Athlete ID, Player, Session timing, Session duration (min),
Intensity (CR-10), Fatigue, Stress, Soreness, Sleep, Specific pain,
Location, OSTRC_Q1..OSTRC_Q4
```

French Google-Form exports work unchanged (`Horodateur, Nom d'utilisateur, Qui es tu?, Moment de la seance, Duree …, Intensite RPE, fatigue, stress, courbatures, sommeil, Douleur specifique, Localisation, ostrc_q1..4`).

**Fields and scales (S4 monitoring form):**

| Field | Scale | Notes |
|---|---|---|
| Timestamp | date-time | day of the entry |
| Athlete ID / email | text | grouping key |
| Player / name | text | display name |
| Session timing | Morning / Afternoon / Evening | descriptive |
| Session duration | minutes | > 0 |
| Intensity (RPE) | Borg CR-10, 0–10 | session RPE |
| Fatigue, Stress, Soreness, Sleep | 1 = best … 7 = worst | four Hooper items |
| Specific pain | yes / no (+ location) | daily pain gate |
| OSTRC_Q1..Q4 | 0–25 each | weekly OSTRC-H (participation, volume, performance, symptoms) |

To use your own data, replace the CSV (or point `HBD_DATA` at it) — no code change is needed as long as headers contain the recognisable keywords.

**Synthetic cohort (S6).** `data/cohort_football_100.csv` and `data/S6_HBD_Synthetic_Cohort_100players.xlsx` provide 100 synthetic football players over several weeks (~2,500 daily entries). The workbook adds computed per-player metrics, variable definitions, and the supplementary figures (squad wellness heatmap; EWMA vs. rolling ACWR; readiness-score distribution). This is the dataset used to validate the pipeline and generate the example report.

---

## 10. Repository layout

```
HBDApp/
├── core/hbd_agent.py        # Deterministic decision core (portable, zero web deps, also a CLI) — S2
├── app/
│   ├── main.py              # FastAPI layer: JSON API + check-in ingest + 20:00 scheduler
│   └── static/
│       ├── index.html       # Coach dashboard (Squad / Athletes / Reports / Audit log)
│       └── checkin.html     # Athlete mobile daily check-in form
├── data/
│   ├── cohort_football_100.csv                 # Synthetic 100-player football cohort — S6
│   └── S6_HBD_Synthetic_Cohort_100players.xlsx # Same cohort as workbook (raw · metrics · definitions)
├── n8n/hbd_n8n_workflow.json # Alternative orchestration: n8n skeleton (Drive → core → Gmail)
├── output/                  # Generated reports + audit log (Docker volume; git-ignored)
├── Dockerfile               # python:3.12-slim image
├── docker-compose.yml       # Service + named volumes for /data and /output
├── requirements.txt         # fastapi · uvicorn · pydantic · apscheduler · openpyxl
└── README.md
```

The core is intentionally standalone: the same `hbd_agent.py` runs inside this web app, from the command line, or inside an n8n `Execute Command` node.

---

## 11. The deterministic core (`hbd_agent.py`)

A single, dependency-light module (`openpyxl` only for `.xlsx` input). Pipeline:

1. **Ingest** — `load_records()` reads the CSV/XLSX, maps columns via the bilingual `COLMAP`, parses dates, numbers and yes/no answers, and computes each row's session load.
2. **Aggregate** — `daily_series()` sums load and averages the wellness composite per day; `component_daily()` keeps per-item Hooper means.
3. **Compute** — `compute_metrics()` returns the load/wellness indices of [§3](#3-the-science--indices-and-definitions); `extended_metrics()` adds the [§7](#7-extended-metrics) variables.
4. **Decide** — `decide()` applies the [§4](#4-decision-logic-auditable-thresholds) thresholds; `strategy()` attaches a concrete action; `wellness_flags()` / `soreness_reason()` add plain-language wellness reasons.
5. **Health override** — `health_status()` + `apply_health_override()` apply the [§5](#5-health-module-and-override) tiers.
6. **Report & audit** — `build_report()` (HTML + text) and `build_periodic()` (weekly/monthly/quarterly); `append_audit()` writes one timestamped row per athlete.

**CLI:**

```bash
python core/hbd_agent.py --input data/cohort_football_100.csv \
    --out output/hbd_report.html --log output/audit.csv
# options: --date YYYY-MM-DD   --mode auto|daily|weekly|monthly|quarterly
```

`auto` issues the daily report plus any due weekly (Saturday), monthly (last Saturday) or quarterly (last Saturday of Mar/Jun/Sep/Dec) review.

**Audit log columns:** `generated_at, data_through, recommend_for, athlete, decision, acwr, wellness, wellness_z, monotony, strain, weekly_load, daily_load, reasons` — every recommendation is timestamped and reproducible.

---

## 12. The web application

A thin **FastAPI** layer over the core (`app/main.py`). It computes no number the core does not; it only exposes data, ingests check-ins, schedules the daily run and serves the report.

**Dashboard** (`app/static/index.html`) — a single-page coach console with tabs:

- **Squad** — decision counts, health-flag count, red-flag alerts, and a sortable per-athlete table (decision badge, ACWR, wellness + z, monotony, strain, weekly load, health, confidence, top reasons, readiness).
- **Athletes** — per-athlete detail with a 28-day daily-load bar chart, 14-day ACWR line (band 0.80–1.30, red ≥ 1.50), 14-day wellness line vs. the dashed 28-day baseline, today's Hooper items, and the health module.
- **Reports** — the generated HTML daily report; a button triggers a run.
- **Audit log** — the append-only audit table with a CSV download.
- **Check-in ↗** — the athlete form (`checkin.html`), a 60-second mobile self-report.

**API:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/squad?date=YYYY-MM-DD` | Per-athlete decisions + metrics for the squad (defaults to latest data day) |
| GET | `/api/athletes` | Athlete names |
| GET | `/api/athlete/{name}?date=` | Full detail: metrics, decision, rationale, strategy, health, 28-day loads, 14-day ACWR/wellness series |
| POST | `/api/checkin` | Append one self-report (JSON) to the responses CSV |
| POST | `/api/run?date=` | Run the pipeline now: write HTML report + append audit log |
| GET | `/api/audit` / `/api/audit.csv` | Audit log as JSON / CSV download |
| GET | `/api/report/text` | Plain-text report |
| GET | `/report` | Latest generated HTML report |
| GET | `/health` | Container healthcheck |

Example check-in:

```bash
curl -X POST http://localhost:8000/api/checkin \
  -H "Content-Type: application/json" \
  -d '{"athlete":"Player 001","moment":"Morning","duration_min":90,"rpe":7,
       "fatigue":4,"stress":3,"soreness":4,"sleep":2,"pain":false}'
```

**Scheduler.** On startup the app registers an APScheduler cron job at **20:00 `HBD_TZ`** (default Africa/Tunis) that runs the full pipeline — mirroring the BPMN timer. You can also trigger it any time from the *Reports* tab or with `POST /api/run`.

---

## 13. Running it

**Docker (recommended):**

```bash
docker compose up -d --build
```

| URL | What |
|---|---|
| http://localhost:8000 | Coach dashboard |
| http://localhost:8000/checkin | Athlete mobile check-in form |
| http://localhost:8000/report | Latest generated daily report |
| http://localhost:8000/docs | Interactive API docs (Swagger) |

`/data` and `/output` are named volumes, so check-ins, reports and the audit log survive restarts. The image is `python:3.12-slim`, ships the seed data baked in, and exposes a `/health` container healthcheck.

**Core only, no Docker** — see the CLI in [§11](#11-the-deterministic-core-hbd_agentpy). `pip install openpyxl` only if you need `.xlsx` input; the core otherwise has no third-party dependencies.

---

## 14. Configuration

| Env var | Default | Meaning |
|---|---|---|
| `HBD_DATA` | `/data/cohort_football_100.csv` | Responses CSV/XLSX path |
| `HBD_OUTPUT` | `/output` | Reports + audit-log directory |
| `HBD_TZ` | `Africa/Tunis` | Scheduler time-zone (daily 20:00 run) |

---

## 15. Orchestration alternative (n8n)

`n8n/hbd_n8n_workflow.json` is an importable skeleton for a self-hosted n8n:

```
Schedule trigger (20:00) → Google Drive: download responses (Excel)
    → Execute Command: run hbd_agent.py → Gmail: email the coach
```

Replace the credential IDs, the Drive file ID and the coach email. The business logic stays entirely in the portable core — n8n only schedules, fetches, runs and sends.

---

## 16. Reproducibility, audit and governance

- **Deterministic by design.** Given the same input and reference day, the core always produces the same indices, decision and rationale. No randomness, no hidden state.
- **Auditable.** Every run appends one timestamped row per athlete to `audit.csv`; every threshold that fired is written into the rationale in plain language.
- **AI is downstream only.** A language model may rephrase the report for readability; it can never recompute, override or invent a metric. The analysis prompt (S3) is constrained accordingly.
- **Safety.** The health module sits above load and wellness, in three graded tiers; the tool never advises increasing load for an athlete who reported a health problem. Recommendations are decision support — the coach always judges, and anything clinical goes to the medical staff.

