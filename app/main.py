#!/usr/bin/env python3
"""
HBOD web application: FastAPI layer over the deterministic HBOD core.

The core (core/hbd_agent.py) computes every metric and decision. This layer only:
  - exposes the squad / athlete / audit data as JSON for the dashboard,
  - accepts daily check-ins and appends them to the responses CSV,
  - schedules the daily 20:00 (Africa/Tunis) report run,
  - serves the generated HTML report and the audit log.

No number is computed here that the core does not compute.
"""

import csv
import os
import sys
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import hbd_agent as core  # noqa: E402

DATA_CSV = os.environ.get("HBD_DATA", "/data/cohort_football_100.csv")
OUTPUT_DIR = os.environ.get("HBD_OUTPUT", "/output")
REPORT_HTML = os.path.join(OUTPUT_DIR, "hbd_report.html")
AUDIT_CSV = os.path.join(OUTPUT_DIR, "audit.csv")
TZ = os.environ.get("HBD_TZ", "Africa/Tunis")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="HBOD — Training-Load & Wellness Monitor", version="1.0")

BADGE = core.BADGE


def _ref_date(d: Optional[str]) -> Optional[date]:
    if not d:
        return None
    parsed = core._parse_date(d)
    if parsed is None:
        raise HTTPException(400, f"Unparseable date: {d}")
    return parsed


def _run_results(ref: Optional[date] = None):
    """Run the core pipeline in-memory (no files written)."""
    results, html, text = core.run(DATA_CSV, ref)
    return results, html, text


def _squad_payload(ref: Optional[date]):
    recs = core.load_records(DATA_CSV)
    dates = [r["date"] for r in recs if r["date"]]
    if not dates:
        raise HTTPException(404, "No data")
    ref = ref or max(dates)
    results, _, _ = _run_results(ref)
    order = {"DECREASE": 0, "MAINTAIN": 1, "INCREASE": 2}
    rows = []
    for r in sorted(results, key=lambda x: order[x["decision"]]):
        m, hs = r["metrics"], r["health"]
        health = f"Pain — {hs['location']}" if hs["pain"] and hs["location"] else ("Pain" if hs["pain"] else "—")
        rows.append({
            "name": r["athlete"], "decision": r["decision"], "badge": BADGE[r["decision"]],
            "acwr": m["acwr"], "wellness": m["wellness"], "wz": m["wellness_z"],
            "monotony": m["monotony"], "strain": m["strain"], "weekly": m["weekly_load"],
            "health": health, "healthAction": hs.get("action"),
            "conf": m["confidence"], "why": "; ".join(r["reasons"][:3]),
            "readiness": r["ext"]["readiness"],
        })
    counts = {"INCREASE": 0, "MAINTAIN": 0, "DECREASE": 0}
    for r in results:
        counts[r["decision"]] += 1
    alerts = [f"{x['name']} — {x['why'].split(';')[0]}" for x in rows
              if x["decision"] == "DECREASE" or x["healthAction"] in ("HOLD", "REFER", "STOP")]
    return {"date": ref.isoformat(), "recommendFor": (ref + timedelta(days=1)).isoformat(),
            "counts": counts, "n": len(results), "alerts": alerts[:4],
            "healthFlags": sum(1 for x in rows if x["health"] != "—"), "squad": rows}


@app.get("/api/squad")
def api_squad(date: Optional[str] = None):
    return _squad_payload(_ref_date(date))


@app.get("/api/athletes")
def api_athletes():
    recs = core.load_records(DATA_CSV)
    return sorted({r["athlete"] for r in recs if r["athlete"]})


@app.get("/api/athlete/{name}")
def api_athlete(name: str, date: Optional[str] = None):
    recs = core.load_records(DATA_CSV)
    if not any(r["athlete"] == name for r in recs):
        raise HTTPException(404, f"Unknown athlete: {name}")
    dates = [r["date"] for r in recs if r["date"]]
    ref = _ref_date(date) or max(dates)
    series = core.daily_series(recs, name)
    comp = core.component_daily(recs, name)
    m = core.compute_metrics(series, ref)
    if m is None:
        # no entry on ref day: still return history so charts render
        m = {}
    decision = reasons = strat = None
    ext = hs = None
    if m:
        decision, reasons = core.decide(m)
        reasons = reasons + core.wellness_flags(comp, ref)
        sr = core.soreness_reason(comp, series, ref)
        if sr:
            reasons.append(sr)
        strat = core.strategy(decision, m)
        hs = core.health_status(recs, name, ref)
        decision, strat, reasons = core.apply_health_override(decision, strat, reasons, hs)
        ext = core.extended_metrics(series, comp, ref, m)

    # 28-day load bars
    loads = []
    for i in range(27, -1, -1):
        d = ref - timedelta(days=i)
        loads.append({"date": d.isoformat(), "load": series.get(d, {}).get("load", 0.0)})
    # 14-day ACWR + wellness lines (uncoupled ACWR over calendar windows)
    acwr_series, wellness_series = [], []
    for i in range(13, -1, -1):
        d = ref - timedelta(days=i)
        aw = core.window_loads(series, d, core.ACUTE_DAYS)
        cw = core.window_loads(series, d - timedelta(days=core.ACUTE_DAYS), core.CHRONIC_DAYS)
        am = sum(aw) / len(aw) if aw else 0.0
        cm = sum(cw) / len(cw) if cw else 0.0
        acwr_series.append({"date": d.isoformat(), "acwr": round(am / cm, 2) if cm > 0 else None})
        wellness_series.append({"date": d.isoformat(), "wellness": series.get(d, {}).get("wellness")})
    # wellness 28-day baseline for the dashed line
    wb = [series[d]["wellness"] for d in series
          if ref - timedelta(days=core.WELLNESS_BASELINE_DAYS) <= d < ref and series[d]["wellness"] is not None]
    baseline = round(sum(wb) / len(wb), 2) if wb else None
    email = next((r0.get("email") for r0 in recs if r0["athlete"] == name and r0.get("email")), None)

    return {"name": name, "email": email, "date": ref.isoformat(),
            "metrics": m or None, "decision": decision,
            "badge": BADGE.get(decision), "reasons": reasons, "strategy": strat,
            "health": hs, "ext": ext, "hooperToday": comp.get(ref),
            "loads28": loads, "acwr14": acwr_series, "wellness14": wellness_series,
            "wellnessBaseline": baseline}


class CheckIn(BaseModel):
    athlete: str
    email: Optional[str] = None
    moment: str = "Morning"
    duration_min: float = Field(gt=0, le=600)
    rpe: float = Field(ge=0, le=10)
    fatigue: Optional[int] = Field(None, ge=1, le=7)
    stress: Optional[int] = Field(None, ge=1, le=7)
    soreness: Optional[int] = Field(None, ge=1, le=7)
    sleep: Optional[int] = Field(None, ge=1, le=7)
    pain: bool = False
    pain_location: Optional[str] = None
    ostrc_q1: Optional[int] = Field(None, ge=0, le=25)
    ostrc_q2: Optional[int] = Field(None, ge=0, le=25)
    ostrc_q3: Optional[int] = Field(None, ge=0, le=25)
    ostrc_q4: Optional[int] = Field(None, ge=0, le=25)
    date: Optional[str] = None  # YYYY-MM-DD, default today


@app.post("/api/checkin")
def api_checkin(c: CheckIn):
    """Append one self-report row to the responses CSV (same columns as the Google Form export)."""
    d = _ref_date(c.date) or date.today()
    ts = f"{d.isoformat()} {datetime.now().strftime('%H:%M:%S')}"
    with open(DATA_CSV, newline="", encoding="utf-8-sig") as f:
        header = next(csv.reader(f))
    row = {h: "" for h in header}

    def put(substr_list, val):
        for h in header:
            if any(s in h.lower() for s in substr_list) and row[h] == "":
                row[h] = "" if val is None else str(val)
                return

    put(["horodat", "timestamp"], ts)
    put(["utilisateur", "athlete id", "email"], c.email or "")
    put(["qui es", "player"], c.athlete)
    put(["moment", "timing"], c.moment)
    put(["duree", "duration"], c.duration_min)
    put(["intensite", "intensity", "cr-10", "rpe"], c.rpe)
    put(["fatigu"], c.fatigue)
    put(["stress"], c.stress)
    put(["courbatur", "soreness"], c.soreness)
    put(["sommeil", "sleep"], c.sleep)
    put(["douleur", "pain"], "Yes" if c.pain else "No")
    put(["localis", "location"], c.pain_location if c.pain else "")
    put(["ostrc_q1"], c.ostrc_q1)
    put(["ostrc_q2"], c.ostrc_q2)
    put(["ostrc_q3"], c.ostrc_q3)
    put(["ostrc_q4"], c.ostrc_q4)
    with open(DATA_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([row[h] for h in header])
    return {"ok": True, "date": d.isoformat(), "athlete": c.athlete,
            "session_load": round(c.duration_min * c.rpe, 1)}


@app.post("/api/run")
def api_run(date: Optional[str] = None):
    """Run the full pipeline now: write the HTML report and append the audit log."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results, html, text = core.run(DATA_CSV, _ref_date(date), REPORT_HTML, AUDIT_CSV)
    return {"ok": True, "athletes": len(results), "report": "/report", "audit": "/api/audit.csv"}


@app.get("/api/audit")
def api_audit(limit: int = 200):
    if not os.path.exists(AUDIT_CSV):
        return {"entries": []}
    with open(AUDIT_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {"entries": rows[-limit:][::-1]}


@app.get("/api/audit.csv")
def api_audit_csv():
    if not os.path.exists(AUDIT_CSV):
        raise HTTPException(404, "No audit log yet — POST /api/run first")
    return FileResponse(AUDIT_CSV, media_type="text/csv", filename="audit.csv")


@app.get("/report")
def report():
    if not os.path.exists(REPORT_HTML):
        # generate on first visit
        api_run()
    return FileResponse(REPORT_HTML, media_type="text/html")


@app.get("/api/report/text")
def report_text(date: Optional[str] = None):
    _, _, text = _run_results(_ref_date(date))
    return HTMLResponse(f"<pre>{text}</pre>")


@app.get("/checkin")
def checkin_page():
    return FileResponse(os.path.join(STATIC_DIR, "checkin.html"), media_type="text/html")


@app.get("/health")
def health():
    return {"status": "ok", "data": os.path.exists(DATA_CSV)}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


# ----------------------------------------------------------------------------
# Scheduler: daily 20:00 Africa/Tunis — mirrors the BPMN timer event.
# ----------------------------------------------------------------------------
@app.on_event("startup")
def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        return
    sched = BackgroundScheduler(timezone=TZ)
    sched.add_job(lambda: api_run(), CronTrigger(hour=20, minute=0),
                  id="hbod-daily", name="HBOD daily report 20:00")
    sched.start()
    app.state.scheduler = sched
