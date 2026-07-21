# HBD — Training-Load & Wellness Monitor

**Hooper–Borg–Dergaa (HBD)** is a daily training-load and wellness monitoring application for sports teams. Athletes submit a 60-second self-report each day; a deterministic decision core computes validated sport-science indices per athlete and recommends the next day's training direction — **INCREASE**, **MAINTAIN** or **DECREASE** — with a full, auditable rationale for the coach.

> Recommendations are decision support, not verdicts. The coach always judges. The tool never advises loading an athlete who reported a health problem.

---

## How it works — the daily cycle (BPMN)

```
ATHLETE          end of training day ──► complete daily self-report
                                          (duration · RPE · Hooper wellness · pain · weekly OSTRC-H)
FORM & STORAGE   response recorded in the responses sheet (CSV)
HBD SYSTEM       timer 20:00 ──► ingest ──► parse & map columns (multilingual headers)
                 ──► compute per-athlete metrics ──► health problem today? ──► apply health override
                 ──► decide next-day load (+ rationale & strategy)
                 ──► build daily report (HTML + text) ──► append audit log ──► email / serve to coach
COACH            review report & rationale ──► set tomorrow's session load ──► cycle complete
```

All metrics and decisions are computed **deterministically** in the core. The workflow layer (web app scheduler or n8n) only schedules, fetches, runs and sends. A language model, if used downstream, may only rephrase output — it never changes a metric.

## The science

| Index | Method | Reference |
|---|---|---|
| Session load (AU) | duration (min) × RPE (Borg CR-10) | Foster session-RPE |
| Weekly load, monotony, strain | 7-day window; monotony = mean/SD of daily loads; strain = weekly load × monotony | Foster 1998 |
| ACWR | 7-day acute mean ÷ 28-day chronic mean; band 0.80–1.30, red ≥ 1.50 | Hulin & Gabbett, BJSM 2019 |
| Wellness composite | 4 Hooper items (fatigue, stress, soreness, sleep; 1 = best … 7 = worst), direction-harmonised, z-scored against the athlete's own 28-day baseline | Hooper & Mackinnon |
| Health module | daily pain gate + weekly OSTRC-H severity (0–100); "substantial problem" = any participation/volume/performance item ≥ 17 | Clarsen 2014 |
| Extended | EWMA-ACWR (Williams 2017), weekly ramp % (Gabbett 2016), training stress balance, Hooper total, sleep index, 0–100 readiness heuristic | — |

### Decision logic (auditable thresholds)

- **DECREASE** — any red flag: ACWR ≥ 1.50 (or > 1.30 caution), wellness ≤ −1.0 SD below personal baseline, monotony ≥ 2.0, acute spike ≥ 1.5× recent mean.
- **INCREASE** — at least two green signals: ACWR < 0.80 **and** wellness at/above baseline.
- **MAINTAIN** — everything else.
- **Health override** (sits above load and wellness, three graded tiers):
  - *HOLD* — any reported pain/flag: never increase, monitor.
  - *REDUCE & REFER* — substantial OSTRC problem: cut load, refer to medical staff.
  - *STOP* — "could not participate": no training, urgent medical assessment.

Every run appends one row per athlete to `audit.csv` (timestamped, reproducible) — the coach can trace any recommendation back to its numbers.

## Architecture

```
HBDApp/
├── core/hbd_agent.py        # Deterministic decision core (portable, zero web deps, also a CLI)
├── app/
│   ├── main.py              # FastAPI layer: JSON API + check-in ingest + 20:00 scheduler
│   └── static/
│       ├── index.html       # Coach dashboard (Squad / Athletes / Reports / Audit log)
│       └── checkin.html     # Athlete mobile daily check-in form
├── data/cohort_football_100.csv   # Synthetic 100-player football cohort (seed data)
├── data/S6_HBD_Synthetic_Cohort_100players.xlsx  # Same cohort as workbook (raw · metrics · definitions)
├── n8n/hbd_n8n_workflow.json      # Alternative orchestration: n8n skeleton (Drive → core → Gmail)
├── output/                  # Generated reports + audit log (volume in Docker)
├── Dockerfile
├── docker-compose.yml
└── README.md
```

The core is intentionally standalone: the same `hbd_agent.py` runs inside this web app, from the command line, or inside an n8n `Execute Command` node.

## Quick start (Docker)

```bash
docker compose up -d --build
```

Then open:

| URL | What |
|---|---|
| http://localhost:8000 | Coach dashboard — squad overview, athlete detail, reports, audit log |
| http://localhost:8000/checkin | Athlete mobile check-in form |
| http://localhost:8000/report | Latest generated daily report (HTML email body) |
| http://localhost:8000/docs | Interactive API documentation (Swagger) |

Data (`/data`) and outputs (`/output`) live in named volumes, so check-ins, reports and the audit log survive container restarts. The scheduler runs the full pipeline every day at **20:00 Africa/Tunis**, mirroring the BPMN timer event; you can also trigger it any time from the *Reports* tab or with `POST /api/run`.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/squad?date=YYYY-MM-DD` | Per-athlete decisions + metrics for the squad (defaults to latest data day) |
| GET | `/api/athletes` | Athlete names |
| GET | `/api/athlete/{name}?date=` | Full detail: metrics, decision, rationale, strategy, health, 28-day loads, 14-day ACWR/wellness series |
| POST | `/api/checkin` | Append one self-report (JSON) to the responses CSV |
| POST | `/api/run?date=` | Run the pipeline now: write HTML report + append audit log |
| GET | `/api/audit` / `/api/audit.csv` | Audit log as JSON / CSV download |
| GET | `/api/report/text` | Plain-text report |
| GET | `/health` | Container healthcheck |

Example check-in:

```bash
curl -X POST http://localhost:8000/api/checkin \
  -H "Content-Type: application/json" \
  -d '{"athlete":"Player 001","moment":"Morning","duration_min":90,"rpe":7,
       "fatigue":4,"stress":3,"soreness":4,"sleep":2,"pain":false}'
```

## Running the core without Docker

The core has no web dependencies (`openpyxl` only for `.xlsx` input):

```bash
python core/hbd_agent.py --input data/cohort_football_100.csv \
    --out output/hbd_report.html --log output/audit.csv
# options: --date YYYY-MM-DD   --mode auto|daily|weekly|monthly|quarterly
```

`auto` mode issues the daily report plus any due weekly (Saturday), monthly (last Saturday) or quarterly (last Saturday of Mar/Jun/Sep/Dec) review.

## Data format

Input is a Google-Form-style responses CSV/XLSX. Column matching is by substring and multilingual (English **or** French headers; yes/no accepts French, English and Arabic). The shipped `data/cohort_football_100.csv` uses English headers:

```
Timestamp, Athlete ID, Player, Session timing, Session duration (min),
Intensity (CR-10), Fatigue, Stress, Soreness, Sleep, Specific pain,
Location, OSTRC_Q1..OSTRC_Q4
```

French Google-Form exports work unchanged (`Horodateur, Nom d'utilisateur, Qui es tu?, Moment de la seance, Duree …, Intensite RPE, fatigue, stress, courbatures, sommeil, Douleur specifique, Localisation, ostrc_q1..4`).

To use your own data, replace the CSV (or point `HBD_DATA` at it) — no code change needed as long as headers contain the recognisable keywords.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `HBD_DATA` | `/data/cohort_football_100.csv` | Responses CSV/XLSX path |
| `HBD_OUTPUT` | `/output` | Reports + audit log directory |
| `HBD_TZ` | `Africa/Tunis` | Scheduler timezone (daily 20:00 run) |

## n8n alternative

`n8n/hbd_n8n_workflow.json` is an importable skeleton for a self-hosted n8n: schedule trigger (20:00) → download responses from Google Drive → run `hbd_agent.py` → email the coach via Gmail. Replace the credential IDs, Drive file ID and coach email. Business logic stays in the portable core.

## Supplementary Materials

Files accompanying the article. Every metric is computed deterministically; generative AI, where used, only rephrases output and never alters a value.

| Item | File(s) | Description |
|---|---|---|
| **S1** | `HBD_App.html` | Free, standalone web application. Runs in any browser and computes entirely on the client — no server, no install, no data upload. Athlete self-reports are entered locally and the deterministic core produces per-athlete indices and the next-day load recommendation (INCREASE / MAINTAIN / DECREASE) with full rationale. |
| **S2** | `hbd_agent.py`, `HBD_Supplementary_Code.html` | The deterministic decision core and a rendered, human-readable listing of its source. `hbd_agent.py` is the portable, zero-web-dependency implementation of every index and threshold; `HBD_Supplementary_Code.html` is the same code as a syntax-highlighted listing for review and reproducibility. |
| **S3** | *(analysis prompt)* | The generative-AI analysis prompt used to produce a narrative interpretation of the computed data. Constrains the model to describing and contextualising the deterministic outputs — it cannot recompute, override, or invent metrics. |
| **S4** | *(monitoring form template)* | The daily monitoring form template: all fields and their response scales — session duration (min), RPE (Borg CR-10, 0–10), the four Hooper wellness items (fatigue, stress, soreness, sleep; 1 = best … 7 = worst), the daily pain gate, and the weekly OSTRC-H health items (0–100 severity). |
| **S5** | *(synthetic dataset + example output)* | A small synthetic dataset with the corresponding worked example output, used to validate the pipeline: given inputs → expected indices, decision, and rationale. Lets a reader confirm the core reproduces the published numbers. |
| **S6** | `data/cohort_football_100.csv`, *(Excel workbook)* | A synthetic 100-player football cohort, provided as a comma-separated file and as an Excel workbook. The workbook holds three sheets — raw data, computed per-player metrics, and variable definitions — plus the supplementary figures: the squad wellness heatmap, the exponentially weighted vs. rolling workload (ACWR) ratio, and the readiness-score distribution. |


