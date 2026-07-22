#!/usr/bin/env python3
"""Build a self-contained, readable HTML report from evals/results/*.json.

  python3 evals/report.py            → writes evals/results/report.html
  open evals/results/report.html

Every scenario is shown as: what case it is and WHY it's worth testing, the
INPUT we gave, the EXPECTED behavior, the ACTUAL result, and the GRADING broken
down by criterion. No dependencies, no network — just open the file. Both runners
call build() at the end, so it stays fresh.
"""
import glob
import html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "evals", "results")
FIXTURES = os.path.join(ROOT, "evals", "fixtures", "scenarios")
SCENARIOS_YAML = os.path.join(ROOT, "evals", "behavior", "scenarios.yaml")


# ---------- data loading ----------

def _load_results():
    det, beh = [], []
    for path in sorted(glob.glob(os.path.join(RESULTS, "*.json")),
                       key=os.path.getmtime):
        base = os.path.basename(path)
        try:
            data = json.load(open(path))
        except (OSError, ValueError):
            continue
        rec = {"sha": base[4:-5], "mtime": os.path.getmtime(path), "data": data}
        if base.startswith("det-"):
            det.append(rec)
        elif base.startswith("beh-"):
            rec["data"] = _normalize_beh(data)
            beh.append(rec)
    return det, beh


def _normalize_beh(data):
    if isinstance(data, dict) and "scenarios" in data:
        return data
    scen = []
    for r in data if isinstance(data, list) else []:
        passed = r.get("checks_frac") == 1.0 and (r.get("judge") or {}).get("pass")
        scen.append({"name": r.get("name", "?"), "model": r.get("model", "?"),
                     "pass_rate": 1.0 if passed else 0.0, "n_pass": int(bool(passed)),
                     "n": 1, "flaky": False,
                     "reps": [{"rep": 0, "passed": bool(passed),
                               "checks_frac": r.get("checks_frac", 0),
                               "judge": r.get("judge", {}), "checks": r.get("checks", {}),
                               "stdout_tail": r.get("stdout", "")}]})
    return {"scenarios": scen, "repeat": 1}


def _yaml_scenarios():
    """name -> {prompt, rubric, bucket, why, fixture, model}. Best-effort: tries
    PyYAML, falls back to a tiny hand parse so the report never hard-depends on it."""
    try:
        import yaml
        out = {}
        for s in yaml.safe_load(open(SCENARIOS_YAML)) or []:
            cov = s.get("covers") or {}
            out[s["name"]] = {"prompt": s.get("prompt", ""),
                              "rubric": " ".join((s.get("judge") or "").split()),
                              "bucket": cov.get("bucket", ""),
                              "why": (cov.get("why") or "").strip(),
                              "fixture": s.get("fixture"), "model": s.get("model")}
        return out
    except Exception:
        return {}


def _fixture_expected(name):
    p = os.path.join(FIXTURES, name, "expected.json")
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return None


# ---------- html helpers ----------

def esc(x):
    return html.escape(str(x))


def _chip(text, cls):
    return f'<span class="chip {cls}">{esc(text)}</span>'


def _kv(d):
    """Render a dict as a compact key/value table."""
    if not d:
        return '<span class="muted">—</span>'
    rows = "".join(
        f'<tr><td class="k">{esc(k)}</td><td class="v"><code>{esc(_short(v))}'
        f'</code></td></tr>' for k, v in d.items())
    return f'<table class="kv">{rows}</table>'


def _short(v, n=600):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " …"


def _field(label, body):
    return (f'<div class="field"><div class="flabel">{esc(label)}</div>'
            f'<div class="fbody">{body}</div></div>')


def _passbar(rate, n_pass, n):
    cls = "ok" if rate == 1.0 else ("warn" if 0 < rate < 1 else "bad")
    return (f'<span class="passbar"><i class="{cls}" style="width:{rate*100:.0f}%">'
            f'</i></span><span class="rate">{n_pass}/{n}</span>')


# ---------- sections ----------

def _behavior_card(s, ymeta):
    ym = ymeta.get(s["name"], {})
    if s.get("pending"):  # defined in scenarios.yaml but not in the latest run
        body = (
            _field("Why this matters",
                   f'{_chip(ym.get("bucket",""),"bucket")} {esc(ym.get("why",""))}')
            + _field("Input", f'<div class="muted">fixture: '
                     f'<code>{esc(ym.get("fixture"))}</code> · model: '
                     f'<code>{esc(ym.get("model") or "haiku")}</code></div>'
                     f'<div class="prompt">“{esc(ym.get("prompt",""))}”</div>')
            + _field("Expected (grading rubric)",
                     f'<div class="rubric">{esc(ym.get("rubric",""))}</div>')
            + _field("Actual &amp; grading",
                     '<span class="muted">not included in the latest run</span>'))
        return _card("—", s["name"], ym.get("bucket", ""),
                     '<span class="rate muted">pending</span>', body, True)
    rate, ok = s["pass_rate"], s["pass_rate"] == 1.0
    status = "PASS" if ok else ("FLAKY" if s.get("flaky") else "FAIL")
    bucket = s.get("bucket") or ym.get("bucket", "")
    why = s.get("why") or ym.get("why", "")
    prompt = (s.get("input") or {}).get("prompt") or ym.get("prompt", "")
    rubric = s.get("expected_rubric") or ym.get("rubric", "")
    fixture = ym.get("fixture")
    # actual + grading per rep
    reps_html = []
    for x in s["reps"]:
        checks = "".join(
            f'<div class="crit {"ok" if v["ok"] else "bad"}">'
            f'{"✓" if v["ok"] else "✗"} <b>{esc(k)}</b>'
            + ("" if v["ok"] else f' — <span class="muted">{esc(_short(v["detail"],200))}'
               "</span>") + "</div>"
            for k, v in (x.get("checks") or {}).items())
        j = x.get("judge") or {}
        checks += (f'<div class="crit {"ok" if j.get("pass") else "bad"}">'
                   f'{"✓" if j.get("pass") else "✗"} <b>LLM judge</b> — '
                   f'<span class="muted">{esc(_short(j.get("reason",""),360))}</span></div>')
        tail = _short(x.get("stdout_tail", ""), 900)
        reps_html.append(
            f'<div class="rep {"ok" if x["passed"] else "bad"}">'
            f'<div class="rephead">run {x["rep"]+1}: '
            f'{"pass" if x["passed"] else "fail"}</div>'
            f'<div class="grade">{checks}</div>'
            f'<details class="raw"><summary>actual output (excerpt)</summary>'
            f'<pre>{esc(tail)}</pre></details></div>')
    body = (
        _field("Why this matters", f'{_chip(bucket,"bucket")} {esc(why)}' if bucket
               else esc(why))
        + _field("Input", f'<div class="muted">fixture: <code>{esc(fixture)}</code> · '
                 f'model: <code>{esc(s.get("model"))}</code></div>'
                 f'<div class="prompt">“{esc(prompt)}”</div>')
        + _field("Expected (grading rubric)", f'<div class="rubric">{esc(rubric)}</div>')
        + _field("Actual &amp; grading (per run)", "".join(reps_html)))
    return _card(status, s["name"], bucket, _passbar(rate, s["n_pass"], s["n"]), body, ok)


def _det_card(r, name):
    scores = r.get("scores", {})
    ok = bool(scores) and all(v["score"] for v in scores.values())
    exp = _fixture_expected(name) or {}
    inp = r.get("input") or exp.get("input", "")
    bucket = r.get("bucket") or exp.get("bucket", "")
    why = r.get("why") or exp.get("why", "")
    expected = r.get("expected") or {k: v for k, v in exp.items()
                                      if k not in ("input", "bucket", "why", "days",
                                                   "build_map")}
    actual = r.get("actual")
    grading = "".join(
        f'<div class="crit {"ok" if v["score"] else "bad"}">'
        f'{"✓" if v["score"] else "✗"} <b>{esc(k)}</b> — '
        f'<span class="muted">{esc(_short(v["detail"],200))}</span></div>'
        for k, v in scores.items())
    body = (
        _field("Why this matters", f'{_chip(bucket,"bucket")} {esc(why)}' if bucket
               else esc(why))
        + _field("Input", esc(inp) or '<span class="muted">synthetic transcript archive</span>')
        + _field("Expected (scan output)", _kv(expected))
        + (_field("Actual (scan output)", _kv(actual)) if actual else "")
        + _field("Grading (by criterion)", f'<div class="grade">{grading}</div>'))
    passbar = _passbar(1.0 if ok else 0.0, int(ok), 1)
    return _card("PASS" if ok else "FAIL", name, bucket, passbar, body, ok)


def _card(status, name, bucket, passbar, body, ok):
    return (
        f'<details class="scen {"ok" if ok else "bad"}"><summary>'
        f'{_chip(status, "ok" if ok else ("warn" if status=="FLAKY" else "bad"))} '
        f'<b>{esc(name)}</b>'
        + (f' <span class="tag">{esc(bucket)}</span>' if bucket else "")
        + f'<span class="spacer"></span>{passbar}</summary>'
        f'<div class="cardbody">{body}</div></details>')


def _trend(runs, behavior):
    cells = []
    for rec in runs[-14:]:
        if behavior:
            scen = rec["data"].get("scenarios", [])
            green = sum(1 for s in scen if s["pass_rate"] == 1.0)
            total = len(scen)
        else:
            green = sum(1 for r in rec["data"]
                        if all(v["score"] for v in r.get("scores", {}).values()))
            total = len(rec["data"])
        h = int(4 + (green / total * 42)) if total else 4
        full = total and green == total
        cells.append(f'<div class="tcol" title="{esc(rec["sha"])}: {green}/{total}">'
                     f'<i class="{"ok" if full else "bad"}" style="height:{h}px"></i>'
                     f'<span>{esc(rec["sha"][:5])}</span></div>')
    return (f'<div class="trend"><div class="tlabel">fully-green scenarios per run →'
            f'</div><div class="trow">{"".join(cells)}</div></div>')


INTRO = """
<details class="intro"><summary>New to evals? Read this first ▾</summary>
<div class="introbody">
<p>An <b>eval</b> is an automated test for behavior we care about. Each row below
is one <b>scenario</b> — a specific case — and reads like a spec:</p>
<ul>
<li><b>Why this matters</b> — the risk or case this scenario covers (its
<i>bucket</i>), so you can see why it's worth a test at all.</li>
<li><b>Input</b> — the exact situation we hand the skill.</li>
<li><b>Expected</b> — what a correct result looks like (for behavior runs this is a
<i>rubric</i> an LLM judge grades against; for the parser it's exact numbers).</li>
<li><b>Actual</b> — what actually happened.</li>
<li><b>Grading</b> — pass/fail broken down by criterion, plus the judge's reasoning.</li>
</ul>
<p>The two suites: <b>Behavior</b> runs the whole skill end-to-end (slow, real
model) and grades what it does; <b>Deterministic</b> checks the parser against
fixtures whose right answer is known exactly (fast, free). Behavior scenarios run
several times — the <b>pass-rate</b> (e.g. 3/3) guards against a lucky single pass.</p>
</div></details>
"""


def build():
    det, beh = _load_results()
    ymeta = _yaml_scenarios()
    beh_green = (beh and all(s["pass_rate"] == 1.0
                             for s in beh[-1]["data"].get("scenarios", [])))
    det_green = (det and all(all(v["score"] for v in r.get("scores", {}).values())
                             for r in det[-1]["data"]))
    overall_ok = bool(beh_green and det_green)

    # show every DEFINED scenario, even if the latest run didn't include it
    latest_scen = beh[-1]["data"].get("scenarios", []) if beh else []
    have = {s["name"] for s in latest_scen}
    ordered = list(latest_scen) + [{"name": n, "pending": True}
                                   for n in ymeta if n not in have]
    beh_cards = "".join(_behavior_card(s, ymeta) for s in ordered) if ordered else \
        "<p class='muted'>No behavior runs yet.</p>"
    det_cards = "".join(_det_card(r, r["name"]) for r in det[-1]["data"]) if det else \
        "<p class='muted'>No deterministic runs yet.</p>"
    beh_meta = (f'latest <code>beh-{esc(beh[-1]["sha"])}</code> · '
                f'{len(beh[-1]["data"].get("scenarios",[]))} scenarios · '
                f'repeat {beh[-1]["data"].get("repeat","?")}' if beh else "")
    det_meta = (f'latest <code>det-{esc(det[-1]["sha"])}</code> · '
                f'{len(det[-1]["data"])} scenarios' if det else "")

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Padawan-No-More — eval results</title><style>{CSS}</style></head><body>
<header><div><h1>⚔ Eval results</h1><div class="sub">padawan-no-more · click any scenario to expand</div></div>
<div class="overall {'ok' if overall_ok else 'bad'}">{'All green' if overall_ok else 'Attention needed'}</div></header>
<main>
{INTRO}
<section><h2>Behavior <span class="muted">— the whole skill run end-to-end, graded by checks + an LLM judge</span></h2>
<div class="meta">{beh_meta}</div>{beh_cards}{_trend(beh, True) if beh else ""}</section>
<section><h2>Deterministic <span class="muted">— the parser vs. fixtures whose answer is known exactly</span></h2>
<div class="meta">{det_meta}</div>{det_cards}{_trend(det, False) if det else ""}</section>
<footer>Regenerated on every eval run. Braintrust holds full history &amp; cross-run diffs.</footer>
</main></body></html>"""
    os.makedirs(RESULTS, exist_ok=True)
    out = os.path.join(RESULTS, "report.html")
    with open(out, "w") as fh:
        fh.write(page)
    return out


CSS = """
:root{--bg:#12100e;--card:#1b1815;--card2:#232019;--ink:#efe7db;--mut:#9a8f80;
--ok:#57b874;--warn:#e0a33c;--bad:#d0555a;--saber:#5bc8ff;--edge:#2c2621}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:22px 30px;border-bottom:1px solid var(--edge);position:sticky;top:0;background:var(--bg);z-index:5}
h1{font-size:21px;margin:0}.sub{color:var(--mut);font-size:13px;margin-top:2px}
main{max-width:1000px;margin:0 auto;padding:0 30px 70px}
h2{font-size:16px;margin:30px 0 6px;font-weight:650}.muted{color:var(--mut);font-weight:400}
.overall{margin-left:auto;padding:6px 14px;border-radius:20px;font-weight:650;font-size:13px}
.overall.ok{background:rgba(87,184,116,.16);color:var(--ok)}
.overall.bad{background:rgba(208,85,90,.16);color:var(--bad)}
.meta{color:var(--mut);font-size:13px;margin:2px 0 12px}code{color:var(--saber);font-size:.92em}
.intro{background:var(--card);border:1px solid var(--edge);border-radius:10px;margin:16px 0 6px}
.intro>summary{cursor:pointer;padding:12px 16px;font-weight:600;list-style:none}
.intro>summary::-webkit-details-marker{display:none}
.introbody{padding:0 18px 14px;color:var(--ink)}.introbody p{margin:8px 0}
.introbody ul{margin:8px 0;padding-left:18px}.introbody li{margin:4px 0}
.scen{background:var(--card);border:1px solid var(--edge);border-left:3px solid var(--edge);
border-radius:9px;margin:7px 0}.scen.ok{border-left-color:var(--ok)}.scen.bad{border-left-color:var(--bad)}
.scen>summary{cursor:pointer;padding:12px 15px;display:flex;align-items:center;gap:10px;list-style:none}
.scen>summary::-webkit-details-marker{display:none}.spacer{flex:1}
.chip{font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;letter-spacing:.03em;white-space:nowrap}
.chip.ok{background:rgba(87,184,116,.16);color:var(--ok)}
.chip.warn{background:rgba(224,163,60,.16);color:var(--warn)}
.chip.bad{background:rgba(208,85,90,.16);color:var(--bad)}
.chip.bucket{background:rgba(91,200,255,.14);color:var(--saber)}
.tag{font-size:11px;color:var(--mut);border:1px solid var(--edge);padding:1px 8px;border-radius:10px}
.passbar{display:inline-block;width:120px;height:6px;background:#332c26;border-radius:4px;overflow:hidden;vertical-align:middle}
.passbar i{display:block;height:100%}.passbar i.ok{background:var(--ok)}
.passbar i.warn{background:var(--warn)}.passbar i.bad{background:var(--bad)}
.rate{font-variant-numeric:tabular-nums;color:var(--mut);font-size:13px;margin-left:8px}
.cardbody{padding:4px 15px 15px}
.field{display:grid;grid-template-columns:150px 1fr;gap:14px;padding:11px 0;border-top:1px solid var(--edge)}
.flabel{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.05em;font-weight:600}
.prompt{margin-top:5px;font-style:italic}.rubric{color:var(--ink)}
.kv{border-collapse:collapse;width:100%}.kv td{padding:3px 8px;vertical-align:top;border-bottom:1px solid var(--edge)}
.kv .k{color:var(--mut);white-space:nowrap;width:1%}.kv .v code{color:var(--ink);white-space:pre-wrap;word-break:break-word}
.rep{background:var(--card2);border-radius:7px;padding:9px 12px;margin:7px 0}
.rep.bad{background:rgba(208,85,90,.07)}
.rephead{font-weight:650;font-size:13px;margin-bottom:5px}
.grade{display:flex;flex-direction:column;gap:3px}
.crit{font-size:13px}.crit.ok{color:var(--ink)}.crit .muted{font-size:12px}
.raw{margin-top:7px}.raw>summary{cursor:pointer;color:var(--mut);font-size:12px}
.raw pre{white-space:pre-wrap;word-break:break-word;background:#0f0d0b;border:1px solid var(--edge);
border-radius:6px;padding:10px;font-size:12px;max-height:280px;overflow:auto;color:var(--mut)}
.trend{margin:14px 0 4px}.tlabel{font-size:12px;color:var(--mut);margin-bottom:6px}
.trow{display:flex;gap:9px;align-items:flex-end;height:58px;overflow-x:auto}
.tcol{display:flex;flex-direction:column;align-items:center;gap:4px}
.tcol i{width:20px;border-radius:3px 3px 0 0;display:block}.tcol i.ok{background:var(--ok)}
.tcol i.bad{background:var(--bad)}.tcol span{font-size:10px;color:var(--mut)}
footer{color:var(--mut);font-size:12px;padding:26px 0 0}
@media(prefers-color-scheme:light){:root{--bg:#faf7f2;--card:#fff;--card2:#f4efe7;
--ink:#2a2521;--mut:#877c6d;--edge:#e7ddd0}.raw pre{background:#f4efe7}}
@media(max-width:640px){.field{grid-template-columns:1fr;gap:4px}}
"""


if __name__ == "__main__":
    print("wrote", build())
