#!/usr/bin/env python3
"""
HBD — S3: generative-AI analysis prompt and data-block builder.

The deterministic core (hbd_agent.py) computes every metric, decision, health
tier and rationale. This module turns that computed output into a constrained
prompt so a language model can produce a plain-language narrative for the coach.

Design rule (from the HBD article): a constrained language model rephrases the
result under guardrails and never changes a number. Nothing here computes a
metric — it only formats the engine's output and, optionally, sends it to a
model for rephrasing.

The prompt-building path has NO third-party dependencies. The optional
`render_with_claude()` helper imports the Anthropic SDK lazily, so the core
stays portable.

    # emit the ready-to-send prompt (no model call, no network):
    python core/analysis_prompt.py --input data/cohort_football_100.csv --emit

    # build the prompt and call a model to produce the narrative:
    python core/analysis_prompt.py --input data/cohort_football_100.csv --run
    #   options: --athlete "Player 003"   --date YYYY-MM-DD
"""

import argparse
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(__file__))
import hbd_agent as core  # noqa: E402


# ----------------------------------------------------------------------------
# The constrained analysis prompt (S3). Kept in sync with S3_analysis_prompt.md.
# ----------------------------------------------------------------------------
ANALYSIS_PROMPT = """\
You are a sports-science writing assistant for the HBD (Hooper–Borg–Dergaa)
daily training-load and wellness monitor. A deterministic engine has ALREADY
computed every metric, the next-day training decision, the health tier and the
full rationale for each athlete. Your ONLY job is to turn that computed output
into a short, clear, plain-language brief for the coach.

HARD RULES — these are non-negotiable:
1. Never compute, recompute, estimate, round, or alter any number. Use the
   values given, verbatim. Do not derive new numbers from them.
2. Never change, second-guess, or override a decision or a health tier. Report
   the decision the engine made.
3. Never invent data. If a field is missing or null, say it is not available —
   do not guess.
4. The health override outranks load and wellness. If an athlete has a STOP,
   REDUCE & REFER, or HOLD action, lead with it and state that anything clinical
   is for the medical staff.
5. This is decision support, not a verdict. The coach decides. Never instruct;
   describe and explain.
6. No diagnosis, no treatment, no medication advice.

STYLE:
- Write for a busy coach: brief, concrete, jargon-light. Expand an index the
  first time it appears (e.g. "ACWR, the acute-to-chronic workload ratio").
- Group athletes by decision in this order: DECREASE, then MAINTAIN, then
  INCREASE. Within DECREASE, put health-flagged athletes first.
- For each athlete: one or two sentences — the decision, the main reason(s) in
  the engine's rationale, and the suggested strategy. Attribute numbers to the
  athlete plainly (e.g. "wellness 2.9 SD below her own baseline").
- Do not restate every metric; surface the ones that drove the decision.
- End with a one-line squad summary (counts per decision, number of health
  flags) and the reminder that the coach makes the final call.
- Produce only the brief. Do not narrate your process or explain these rules."""


def _fmt(v):
    """Format a value for the data block; null-safe and never fabricated."""
    return "n/a" if v is None else str(v)


def _athlete_block(r):
    """One deterministic, unambiguous record for a single athlete's result."""
    m, hs, ext = r["metrics"], r["health"], r["ext"]
    lines = [
        f"- Athlete: {r['athlete']}",
        f"  Decision: {r['decision']}",
        f"  Health action: {_fmt(hs.get('action'))}"
        + (f" (location {hs['location']})" if hs.get("location") else "")
        + (f", OSTRC severity {int(hs['severity'])}/100"
           if hs.get("severity") is not None else ""),
        f"  ACWR: {_fmt(m.get('acwr'))} (band 0.80-1.30, red >=1.50)"
        f" | acute spike: {_fmt(m.get('acute_spike'))}x recent mean",
        f"  Wellness composite: {_fmt(m.get('wellness'))}/7"
        f" (z {_fmt(m.get('wellness_z'))} vs 28-day personal baseline)",
        f"  Monotony: {_fmt(m.get('monotony'))} | strain: {_fmt(m.get('strain'))} AU"
        f" | weekly load: {_fmt(m.get('weekly_load'))} AU"
        f" | daily load: {_fmt(m.get('daily_load'))} AU",
        f"  Readiness (0-100): {_fmt(ext.get('readiness'))}"
        f" | weekly ramp: {_fmt(ext.get('weekly_ramp_pct'))}%"
        f" | data confidence: {_fmt(m.get('confidence'))}",
        f"  Rationale (engine): {'; '.join(r['reasons']) if r['reasons'] else 'none'}",
        f"  Suggested strategy (engine): {r['strategy']}",
    ]
    return "\n".join(lines)


def build_data_block(results, ref_date):
    """Assemble the deterministic user turn: computed facts only, no prose.

    Athletes are ordered DECREASE -> MAINTAIN -> INCREASE, health flags first,
    so the model receives them in the order it must write them."""
    order = {"DECREASE": 0, "MAINTAIN": 1, "INCREASE": 2}
    ordered = sorted(
        results,
        key=lambda r: (order.get(r["decision"], 9),
                       0 if r["health"].get("action") else 1,
                       r["athlete"]),
    )
    counts = {"DECREASE": 0, "MAINTAIN": 0, "INCREASE": 0}
    flags = 0
    for r in results:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
        if r["health"].get("action"):
            flags += 1
    header = (
        f"HBD computed output — data through {ref_date.isoformat()}, "
        f"recommendation for {(ref_date + timedelta(days=1)).isoformat()}.\n"
        f"Squad: {len(results)} athletes | "
        f"DECREASE {counts['DECREASE']} · MAINTAIN {counts['MAINTAIN']} · "
        f"INCREASE {counts['INCREASE']} | health flags {flags}.\n"
        "All numbers below are final. Write the coach brief per the rules; "
        "do not alter any value.\n"
    )
    return header + "\n\n".join(_athlete_block(r) for r in ordered)


def build_prompt(input_csv, ref_date=None, athlete=None):
    """Run the deterministic engine and return {system, data} ready to send.

    If `athlete` is given, the block is restricted to that one athlete."""
    results, _, _ = core.run(input_csv, ref_date)
    if not results:
        raise ValueError("No results for the reference day.")
    if athlete:
        results = [r for r in results if r["athlete"] == athlete]
        if not results:
            raise ValueError(f"Unknown athlete for this day: {athlete}")
    # recover the reference day the engine used (latest data day by default)
    recs = core.load_records(input_csv)
    dates = [r["date"] for r in recs if r["date"]]
    ref = ref_date or (max(dates) if dates else None)
    return {"system": ANALYSIS_PROMPT, "data": build_data_block(results, ref)}


def render_with_claude(input_csv, ref_date=None, athlete=None,
                       model="claude-opus-4-8", max_tokens=2000):
    """Optional: send the constrained prompt to Claude and return the narrative.

    Lazily imports the Anthropic SDK so the core has no LLM dependency. The model
    only rephrases the deterministic block — it cannot change a number."""
    try:
        import anthropic
    except ImportError as e:
        raise ImportError("Live rephrasing needs the Anthropic SDK: "
                          "pip install anthropic") from e
    p = build_prompt(input_csv, ref_date, athlete)
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY / profile
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        output_config={"effort": "medium"},
        system=p["system"],
        messages=[{"role": "user", "content": p["data"]}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def main():
    ap = argparse.ArgumentParser(
        description="HBD S3 — build the analysis prompt (and optionally run it)")
    ap.add_argument("--input", required=True, help="responses CSV/XLSX")
    ap.add_argument("--date", help="reference day YYYY-MM-DD (default: latest)")
    ap.add_argument("--athlete", help="restrict to one athlete by name")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--emit", action="store_true",
                   help="print the ready-to-send prompt; no model call (default)")
    g.add_argument("--run", action="store_true",
                   help="call Claude and print the narrative (needs anthropic + key)")
    args = ap.parse_args()
    ref = core._parse_date(args.date) if args.date else None

    if args.run:
        print(render_with_claude(args.input, ref, args.athlete))
        return
    p = build_prompt(args.input, ref, args.athlete)
    print("===== SYSTEM PROMPT (S3) =====\n")
    print(p["system"])
    print("\n\n===== DATA BLOCK (deterministic) =====\n")
    print(p["data"])


if __name__ == "__main__":
    main()
