#!/usr/bin/env python3
"""Build a self-contained local HTML report from evals/results/*.json.

  python3 evals/report.py            → writes evals/results/report.html
  open evals/results/report.html

Reads every det-<sha>.json (deterministic) and beh-<sha>.json (behavior) dump
the runners leave behind and renders scenarios × runs, red/green, pass-rates,
judge reasoning, and a per-suite trend across runs. No dependencies, no network
— just open the file. Both runners call build() at the end, so it stays fresh.
"""
import glob
import html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "evals", "results")


def _normalize_beh(data):
    """Accept both the current {sha, scenarios:[...]} shape and the older flat
    list of single-run rows, so trend/history survives format changes."""
    if isinstance(data, dict) and "scenarios" in data:
        return data
    scen = []
    for r in data if isinstance(data, list) else []:
        passed = r.get("checks_frac") == 1.0 and (r.get("judge") or {}).get("pass")
        scen.append({"name": r.get("name", "?"), "model": r.get("model", "?"),
                     "pass_rate": 1.0 if passed else 0.0,
                     "n_pass": 1 if passed else 0, "n": 1, "flaky": False,
                     "reps": [{"rep": 0, "passed": bool(passed),
                               "checks_frac": r.get("checks_frac", 0),
                               "judge": r.get("judge", {}), "checks": r.get("checks", {})}]})
    return {"scenarios": scen, "repeat": 1}


def _load():
    det, beh = [], []
    for path in sorted(glob.glob(os.path.join(RESULTS, "*.json")),
                       key=os.path.getmtime):
        base = os.path.basename(path)
        try:
            data = json.load(open(path))
        except (OSError, ValueError):
            continue
        rec = {"sha": base[4:-5], "mtime": os.path.getmtime(path)}
        if base.startswith("det-"):
            rec["data"] = data
            det.append(rec)
        elif base.startswith("beh-"):
            rec["data"] = _normalize_beh(data)
            beh.append(rec)
    return det, beh


def _chip(ok, label):
    cls = "ok" if ok else "bad"
    return f'<span class="chip {cls}">{html.escape(label)}</span>'


def _behavior_section(beh):
    if not beh:
        return "<p class='muted'>No behavior runs yet.</p>"
    latest = beh[-1]
    scen = latest["data"].get("scenarios", [])
    rows = []
    for s in scen:
        rate = s["pass_rate"]
        status = "PASS" if rate == 1.0 else ("FLAKY" if s.get("flaky") else "FAIL")
        ok = rate == 1.0
        bar = f'<div class="bar"><i style="width:{rate*100:.0f}%"></i></div>'
        reps_html = []
        for x in s["reps"]:
            marks = []
            for k, v in x.get("checks", {}).items():
                marks.append(f'{"✓" if v["ok"] else "✗"} {html.escape(k)}'
                             + ("" if v["ok"] else f' — <span class="muted">'
                                f'{html.escape(str(v["detail"])[:160])}</span>'))
            j = x.get("judge", {})
            jj = ("✓" if j.get("pass") else "✗") + " judge — " + \
                 f'<span class="muted">{html.escape(str(j.get("reason",""))[:400])}</span>'
            reps_html.append(
                f'<div class="rep {"ok" if x["passed"] else "bad"}">'
                f'<b>rep {x["rep"]}</b> {"pass" if x["passed"] else "fail"}'
                f'<div class="checkline">{"<br>".join(marks + [jj])}</div></div>')
        rows.append(
            f'<details class="scen {"ok" if ok else "bad"}"><summary>'
            f'{_chip(ok, status)} <b>{html.escape(s["name"])}</b> '
            f'<span class="model">{html.escape(s["model"])}</span> {bar} '
            f'<span class="rate">{s["n_pass"]}/{s["n"]}</span></summary>'
            f'{"".join(reps_html)}</details>')
    trend = _trend(beh, behavior=True)
    return (f'<div class="meta">latest <code>beh-{html.escape(latest["sha"])}</code> · '
            f'{len(scen)} scenarios · repeat {latest["data"].get("repeat","?")}</div>'
            + "".join(rows) + trend)


def _deterministic_section(det):
    if not det:
        return "<p class='muted'>No deterministic runs yet.</p>"
    latest = det[-1]
    rows = []
    for r in latest["data"]:
        scores = r.get("scores", {})
        ok = all(v["score"] for v in scores.values()) if scores else False
        checks = "<br>".join(
            f'{"✓" if v["score"] else "✗"} {html.escape(k)}'
            + ("" if v["score"] else f' — <span class="muted">'
               f'{html.escape(str(v["detail"])[:160])}</span>')
            for k, v in scores.items())
        rows.append(
            f'<details class="scen {"ok" if ok else "bad"}"><summary>'
            f'{_chip(ok, "PASS" if ok else "FAIL")} <b>{html.escape(r["name"])}</b>'
            f'</summary><div class="checkline">{checks}</div></details>')
    trend = _trend(det, behavior=False)
    return (f'<div class="meta">latest <code>det-{html.escape(latest["sha"])}</code> · '
            f'{len(latest["data"])} scenarios</div>' + "".join(rows) + trend)


def _trend(runs, behavior):
    """Little bar-per-run of how many scenarios were fully green."""
    cells = []
    for rec in runs[-12:]:
        if behavior:
            scen = rec["data"].get("scenarios", [])
            green = sum(1 for s in scen if s["pass_rate"] == 1.0)
            total = len(scen)
        else:
            green = sum(1 for r in rec["data"]
                        if all(v["score"] for v in r.get("scores", {}).values()))
            total = len(rec["data"])
        h = int(4 + (green / total * 44)) if total else 4
        full = total and green == total
        cells.append(f'<div class="tcol" title="{html.escape(rec["sha"])}: '
                     f'{green}/{total}"><i class="{"ok" if full else "bad"}" '
                     f'style="height:{h}px"></i><span>{html.escape(rec["sha"][:5])}'
                     f'</span></div>')
    return f'<div class="trend"><div class="tlabel">green scenarios per run →</div>' \
           f'<div class="trow">{"".join(cells)}</div></div>'


def build():
    det, beh = _load()
    beh_all_green = (beh and all(s["pass_rate"] == 1.0
                                 for s in beh[-1]["data"].get("scenarios", [])))
    det_all_green = (det and all(all(v["score"] for v in r.get("scores", {}).values())
                                 for r in det[-1]["data"]))
    overall = "All green" if (beh_all_green and det_all_green) else "Attention needed"
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Padawan-No-More — eval results</title><style>{CSS}</style></head><body>
<header><h1>⚔ Eval results</h1><div class="overall {'ok' if beh_all_green and det_all_green else 'bad'}">{overall}</div></header>
<section><h2>Behavior <span class="muted">— skill run end-to-end via claude -p, N runs each</span></h2>
{_behavior_section(beh)}</section>
<section><h2>Deterministic <span class="muted">— scan.py / build_page.py vs known-answer fixtures</span></h2>
{_deterministic_section(det)}</section>
<footer>Regenerated on each run. Click a scenario to see every run's checks and judge reasoning.
Braintrust holds the full history &amp; cross-run diffs.</footer></body></html>"""
    os.makedirs(RESULTS, exist_ok=True)
    out = os.path.join(RESULTS, "report.html")
    with open(out, "w") as fh:
        fh.write(page)
    return out


CSS = """
:root{--bg:#12100e;--card:#1c1916;--ink:#efe7db;--mut:#9a8f80;--ok:#4caf6d;
--bad:#d0555a;--saber:#5bc8ff;--edge:#2c2621}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:0 0 60px}
header{display:flex;align-items:center;gap:16px;padding:24px 32px;border-bottom:1px solid var(--edge)}
h1{font-size:22px;margin:0}h2{font-size:16px;margin:28px 0 8px;font-weight:650}
section{padding:0 32px}.muted{color:var(--mut);font-weight:400}
.overall{margin-left:auto;padding:6px 14px;border-radius:20px;font-weight:650;font-size:13px}
.overall.ok{background:rgba(76,175,109,.16);color:var(--ok)}
.overall.bad{background:rgba(208,85,90,.16);color:var(--bad)}
.meta{color:var(--mut);font-size:13px;margin:4px 0 12px}code{color:var(--saber)}
.scen{background:var(--card);border:1px solid var(--edge);border-left:3px solid var(--edge);
border-radius:8px;margin:6px 0;padding:0}.scen.ok{border-left-color:var(--ok)}
.scen.bad{border-left-color:var(--bad)}
summary{cursor:pointer;padding:11px 14px;display:flex;align-items:center;gap:10px;list-style:none}
summary::-webkit-details-marker{display:none}
.chip{font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;letter-spacing:.03em}
.chip.ok{background:rgba(76,175,109,.16);color:var(--ok)}
.chip.bad{background:rgba(208,85,90,.16);color:var(--bad)}
.model{font-size:11px;color:var(--mut);border:1px solid var(--edge);padding:1px 7px;border-radius:10px}
.bar{flex:1;max-width:160px;height:6px;background:#332c26;border-radius:4px;overflow:hidden;margin-left:auto}
.bar i{display:block;height:100%;background:var(--ok)}
.scen.bad .bar i{background:var(--bad)}.rate{font-variant-numeric:tabular-nums;color:var(--mut);font-size:13px}
.rep{margin:0 14px 8px;padding:8px 12px;border-radius:6px;background:#241f1b;font-size:13px}
.rep.bad{background:rgba(208,85,90,.08)}
.checkline{margin-top:6px;color:var(--ink);font-size:13px}.checkline .muted{font-size:12px}
.trend{margin:14px 0 8px}.tlabel{font-size:12px;color:var(--mut);margin-bottom:6px}
.trow{display:flex;gap:10px;align-items:flex-end;height:60px}
.tcol{display:flex;flex-direction:column;align-items:center;gap:4px}
.tcol i{width:22px;border-radius:3px 3px 0 0;display:block}.tcol i.ok{background:var(--ok)}
.tcol i.bad{background:var(--bad)}.tcol span{font-size:10px;color:var(--mut)}
footer{color:var(--mut);font-size:12px;padding:24px 32px 0}
@media(prefers-color-scheme:light){:root{--bg:#faf7f2;--card:#fff;--ink:#2a2521;
--mut:#877c6d;--edge:#e7ddd0}}
"""


if __name__ == "__main__":
    print("wrote", build())
