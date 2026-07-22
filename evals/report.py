#!/usr/bin/env python3
"""Build a self-contained, interactive HTML report from evals/results/*.json.

  python3 evals/report.py            → writes evals/results/report.html
  open evals/results/report.html

One searchable, sortable table of every scenario across both suites. Click a row
to expand: what case it is and WHY it's tested, the INPUT (including the actual
fixture transcript, rendered readably), the EXPECTED behavior, the ACTUAL result,
and the GRADING broken down by criterion. No dependencies, no network.
"""
import glob
import html
import json
import os
import re

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
    try:
        return json.load(open(os.path.join(FIXTURES, name, "expected.json")))
    except (OSError, ValueError):
        return None


# ---------- html helpers ----------

def esc(x):
    return html.escape(str(x))


def _short(v, n=800):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " …"


def _kv(d):
    if not d:
        return '<span class="muted">—</span>'
    rows = "".join(f'<tr><td class="k">{esc(k)}</td><td class="v"><code>'
                   f'{esc(_short(v))}</code></td></tr>' for k, v in d.items())
    return f'<table class="kv">{rows}</table>'


def _field(label, body):
    return (f'<div class="field"><div class="flabel">{esc(label)}</div>'
            f'<div class="fbody">{body}</div></div>')


# ---------- fixture rendering ----------

_ANS_RE = re.compile(r'answered:\s*(.*?)\.\s*You can now', re.S)


def _fmt_row(o):
    """One transcript row → (icon, css, text, extra) or None."""
    t = o.get("type")
    content = (o.get("message") or {}).get("content")
    if t == "user" and isinstance(content, str):
        m = re.search(r"<command-name>/?([\w:-]+)</command-name>", content)
        if m:
            return ("»", "cmd", f"/{m.group(1)}", "")
        if "[Request interrupted" in content:
            return ("⎋", "esc", "user pressed Escape", "")
        return None
    if not isinstance(content, list):
        return None
    for c in content:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "tool_use":
            n, inp = c.get("name", ""), c.get("input") or {}
            if n == "AskUserQuestion":
                qs = inp.get("questions", [])
                q = "  ·  ".join(x.get("question", "") for x in qs)
                opts = " | ".join(o.get("label", "")
                                  for x in qs for o in x.get("options", []))
                return ("❓", "ask", q, opts)
            if n == "ExitPlanMode":
                return ("▤", "plan", "proposed a plan: " + inp.get("plan", "")[:120], "")
            if n == "Bash":
                return ("⌘", "bash", inp.get("command", "")[:200], "")
            if n in ("Write", "Edit", "MultiEdit"):
                return ("✎", "edit", f"{n} {inp.get('file_path','')}", "")
            if n == "Skill":
                return ("▸", "skill", "invoked skill: " + inp.get("skill", ""), "")
        elif c.get("type") == "tool_result":
            rc = c.get("content")
            text = rc if isinstance(rc, str) else (
                " ".join(x.get("text", "") for x in rc if isinstance(x, dict))
                if isinstance(rc, list) else "")
            if text.startswith("Your questions have been answered"):
                m = _ANS_RE.search(text)
                return ("↳", "ans", "answered: " + (m.group(1) if m else "")[:200], "")
            if text.startswith("Permission to use") or text.startswith(
                    "The user doesn't want"):
                return ("⛔", "deny", "denied by the user", "")
            if "approved your plan" in text:
                return ("↳", "ans", "user approved the plan", "")
    return None


def _fixture_view(name):
    if not name:
        return None
    base = os.path.join(FIXTURES, name, "home", ".claude", "projects")
    if not os.path.isdir(base):
        return None
    settings = ""
    sp = os.path.join(FIXTURES, name, "home", ".claude", "settings.json")
    if os.path.isfile(sp):
        try:
            perms = json.load(open(sp)).get("permissions", {})
            settings = (f'<div class="ev cfg"><span class="evk">⚙</span>'
                        f'<span class="evt">settings.json permissions: '
                        f'<code>{esc(json.dumps(perms))}</code></span></div>')
        except (OSError, ValueError):
            pass
    files = sorted(glob.glob(os.path.join(base, "*", "*.jsonl")))
    lines, total = [], 0
    for f in files:
        proj = os.path.basename(os.path.dirname(f))
        if len(files) > 1:
            lines.append(f'<div class="evfile">project <code>{esc(proj)}</code></div>')
        for line in open(f):
            line = line.strip()
            if not line:
                continue
            try:
                fr = _fmt_row(json.loads(line))
            except ValueError:
                fr = None
            if not fr:
                continue
            total += 1
            if len(lines) < 60:
                icon, cls, text, extra = fr
                ex = f' <span class="evopt">⟨{esc(extra)}⟩</span>' if extra else ""
                lines.append(f'<div class="ev {cls}"><span class="evk">{esc(icon)}'
                             f'</span><span class="evt">{esc(text)}{ex}</span></div>')
    if total > 60:
        lines.append(f'<div class="evmore">+ {total - 60} more events…</div>')
    return settings + "".join(lines)


# ---------- grading blocks ----------

def _crit(ok, label, detail):
    d = "" if ok else f' — <span class="muted">{esc(_short(detail, 240))}</span>'
    return f'<div class="crit {"ok" if ok else "bad"}">{"✓" if ok else "✗"} <b>{esc(label)}</b>{d}</div>'


def _behavior_grading(reps):
    out = []
    for x in reps:
        crits = "".join(_crit(v["ok"], k, v["detail"])
                        for k, v in (x.get("checks") or {}).items())
        j = x.get("judge") or {}
        crits += _crit(bool(j.get("pass")), "LLM judge", j.get("reason", ""))
        tail = _short(x.get("stdout_tail", ""), 1400)
        out.append(f'<div class="rep {"ok" if x["passed"] else "bad"}">'
                   f'<div class="rephead">run {x["rep"]+1}: '
                   f'{"pass" if x["passed"] else "fail"}</div>'
                   f'<div class="grade">{crits}</div>'
                   f'<details class="raw"><summary>actual output (excerpt)</summary>'
                   f'<pre>{esc(tail)}</pre></details></div>')
    return "".join(out)


# ---------- unified rows ----------

def _rows(det, beh, ymeta):
    """One dict per scenario across both suites, ready to render as a table row."""
    rows = []
    # behavior — every defined scenario, even if the latest run skipped it
    latest = beh[-1]["data"].get("scenarios", []) if beh else []
    have = {s["name"]: s for s in latest}
    names = list(have) + [n for n in ymeta if n not in have]
    for name in names:
        s = have.get(name, {"name": name, "pending": True})
        ym = ymeta.get(name, {})
        pending = s.get("pending")
        rate = 0.0 if pending else s["pass_rate"]
        status = ("pending" if pending else
                  "PASS" if rate == 1.0 else "FLAKY" if s.get("flaky") else "FAIL")
        fixture = ym.get("fixture")
        detail = (
            _field("Why this matters", esc(s.get("why") or ym.get("why", "")))
            + _field("Input — prompt",
                     f'<div class="muted">model <code>'
                     f'{esc((s.get("model") if not pending else ym.get("model")) or "haiku")}'
                     f'</code></div><div class="prompt">“'
                     f'{esc((s.get("input", {}) or {}).get("prompt") or ym.get("prompt",""))}”</div>')
            + _field(f"Input — fixture ({esc(fixture)})" if fixture
                     else "Input — fixture",
                     f'<div class="fixture">{_fixture_view(fixture)}</div>' if fixture
                     else '<span class="muted">no transcript fixture — the input is '
                     'the pasted transmission shown in the prompt above</span>')
            + _field("Expected — grading rubric",
                     f'<div class="rubric">{esc(s.get("expected_rubric") or ym.get("rubric",""))}</div>')
            + _field("Actual & grading",
                     _behavior_grading(s["reps"]) if not pending
                     else '<span class="muted">not included in the latest run</span>'))
        rows.append({"suite": "behavior", "name": name,
                     "bucket": s.get("bucket") or ym.get("bucket", ""),
                     "status": status, "rate": rate,
                     "npass": 0 if pending else s["n_pass"], "n": 0 if pending else s["n"],
                     "detail": detail})
    # deterministic
    for r in (det[-1]["data"] if det else []):
        name = r["name"]
        exp = _fixture_expected(name) or {}
        scores = r.get("scores", {})
        ok = bool(scores) and all(v["score"] for v in scores.values())
        expected = r.get("expected") or {k: v for k, v in exp.items()
                                          if k not in ("input", "bucket", "why", "days",
                                                       "build_map")}
        grading = "".join(_crit(bool(v["score"]), k, v["detail"])
                          for k, v in scores.items())
        detail = (
            _field("Why this matters", esc(r.get("why") or exp.get("why", "")))
            + _field("Input — description", esc(r.get("input") or exp.get("input", "")))
            + _field(f"Input — fixture ({esc(name)})",
                     f'<div class="fixture">{_fixture_view(name) or "<span class=muted>—</span>"}</div>')
            + _field("Expected — scan output", _kv(expected))
            + (_field("Actual — scan output", _kv(r["actual"])) if r.get("actual") else "")
            + _field("Grading — by criterion", f'<div class="grade">{grading}</div>'))
        rows.append({"suite": "deterministic", "name": name,
                     "bucket": r.get("bucket") or exp.get("bucket", ""),
                     "status": "PASS" if ok else "FAIL", "rate": 1.0 if ok else 0.0,
                     "npass": int(ok), "n": 1, "detail": detail})
    return rows


def _table(rows):
    body = []
    for i, r in enumerate(rows):
        st = r["status"]
        stcls = {"PASS": "ok", "FLAKY": "warn", "FAIL": "bad", "pending": "mut"}[st]
        raten = f'{r["npass"]}/{r["n"]}' if r["n"] else "—"
        bar = (f'<span class="bar"><i class="{stcls}" style="width:{r["rate"]*100:.0f}%">'
               f'</i></span>')
        body.append(
            f'<tbody class="grp" data-suite="{r["suite"]}" data-status="{st}" '
            f'data-name="{esc(r["name"])}" data-bucket="{esc(r["bucket"])}" '
            f'data-rate="{r["rate"]:.3f}">'
            f'<tr class="row" onclick="tog(this)">'
            f'<td class="c-exp"><span class="caret">▸</span></td>'
            f'<td class="c-suite"><span class="pill {r["suite"]}">{r["suite"][:4]}</span></td>'
            f'<td class="c-name">{esc(r["name"])}</td>'
            f'<td class="c-bucket">{esc(r["bucket"])}</td>'
            f'<td class="c-status"><span class="chip {stcls}">{esc(st)}</span></td>'
            f'<td class="c-rate">{bar}<span class="rn">{raten}</span></td></tr>'
            f'<tr class="det"><td colspan="6"><div class="detwrap">{r["detail"]}</div></td></tr>'
            f'</tbody>')
    return "".join(body)


INTRO = """
<details class="intro"><summary>New to evals? Read this first ▾</summary>
<div class="introbody">
<p>An <b>eval</b> is an automated test for behavior we care about. Each row is one
<b>scenario</b> — a specific case. Click it to expand a spec-like view:</p>
<ul>
<li><b>Why this matters</b> — the risk/case it covers (its <i>bucket</i>).</li>
<li><b>Input</b> — the prompt and the actual <i>fixture</i> (the transcript history
we feed the skill), rendered readably.</li>
<li><b>Expected</b> — a rubric an LLM judge grades against (behavior), or exact
numbers (the parser).</li>
<li><b>Actual</b> — what happened.</li>
<li><b>Grading</b> — pass/fail per criterion, plus the judge's reasoning.</li>
</ul>
<p><b>Behavior</b> runs the whole skill end-to-end (slow, real model); each runs
several times and the <b>pass-rate</b> (e.g. 3/3) guards against a lucky pass.
<b>Deterministic</b> checks the parser against known-answer fixtures (fast, free).
Use the search box and filters to slice the table; click a column header to sort.</p>
</div></details>
"""


def build():
    det, beh = _load_results()
    ymeta = _yaml_scenarios()
    rows = _rows(det, beh, ymeta)
    graded = [r for r in rows if r["status"] != "pending"]
    overall_ok = bool(graded) and all(r["status"] == "PASS" for r in graded)
    n_pass = sum(1 for r in graded if r["status"] == "PASS")
    meta = []
    if beh:
        meta.append(f'beh <code>{esc(beh[-1]["sha"])}</code>×'
                    f'{beh[-1]["data"].get("repeat","?")}')
    if det:
        meta.append(f'det <code>{esc(det[-1]["sha"])}</code>')
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Padawan-No-More — eval results</title><style>{CSS}</style></head><body>
<header><div><h1>⚔ Eval results</h1><div class="sub">{" · ".join(meta)} · {len(rows)} scenarios · {n_pass}/{len(graded)} passing</div></div>
<div class="overall {'ok' if overall_ok else 'bad'}">{'All green' if overall_ok else 'Attention needed'}</div></header>
<main>
{INTRO}
<div class="controls">
<input id="q" placeholder="search scenarios, buckets…" oninput="flt()">
<span class="fg" id="fsuite"><b>suite</b>
<button class="on" data-v="all" onclick="pick('suite',this)">all</button>
<button data-v="behavior" onclick="pick('suite',this)">behavior</button>
<button data-v="deterministic" onclick="pick('suite',this)">deterministic</button></span>
<span class="fg" id="fstatus"><b>status</b>
<button class="on" data-v="all" onclick="pick('status',this)">all</button>
<button data-v="pass" onclick="pick('status',this)">passing</button>
<button data-v="notpass" onclick="pick('status',this)">not passing</button></span>
</div>
<table id="tbl"><thead><tr>
<th class="c-exp"></th>
<th class="c-suite sortable" onclick="srt('suite')">suite</th>
<th class="c-name sortable" onclick="srt('name')">scenario</th>
<th class="c-bucket sortable" onclick="srt('bucket')">bucket / what it covers</th>
<th class="c-status sortable" onclick="srt('status')">status</th>
<th class="c-rate sortable" onclick="srt('rate')">pass-rate</th>
</tr></thead>
{_table(rows)}
</table>
<div id="empty" class="muted" style="display:none;padding:20px">No scenarios match.</div>
<footer>Regenerated on every eval run. Braintrust holds full history &amp; cross-run diffs.</footer>
</main>
<script>{JS}</script></body></html>"""
    os.makedirs(RESULTS, exist_ok=True)
    out = os.path.join(RESULTS, "report.html")
    with open(out, "w") as fh:
        fh.write(page)
    return out


JS = r"""
var F={suite:'all',status:'all'};
function tog(tr){var b=tr.parentNode;b.classList.toggle('open');}
function pick(k,btn){F[k]=btn.dataset.v;
  btn.parentNode.querySelectorAll('button').forEach(function(x){x.classList.remove('on')});
  btn.classList.add('on');flt();}
function flt(){var q=(document.getElementById('q').value||'').toLowerCase();var any=0;
  document.querySelectorAll('tbody.grp').forEach(function(b){
    var okS=F.suite=='all'||b.dataset.suite==F.suite;
    var st=b.dataset.status;
    var okT=F.status=='all'||(F.status=='pass'?st=='PASS':(st!='PASS'&&st!='pending')||st=='FLAKY'||st=='FAIL');
    if(F.status=='notpass')okT=(st=='FAIL'||st=='FLAKY');
    if(F.status=='pass')okT=(st=='PASS');
    var hay=(b.dataset.name+' '+b.dataset.bucket+' '+b.dataset.suite).toLowerCase();
    var okQ=!q||hay.indexOf(q)>=0;
    var show=okS&&okT&&okQ;b.style.display=show?'':'none';if(show)any++;});
  document.getElementById('empty').style.display=any?'none':'';}
var SD={};
function srt(k){SD[k]=!SD[k];var dir=SD[k]?1:-1;var t=document.getElementById('tbl');
  var gs=Array.prototype.slice.call(t.querySelectorAll('tbody.grp'));
  var ord={PASS:0,FLAKY:1,FAIL:2,pending:3};
  gs.sort(function(a,b){var x,y;
    if(k=='rate'){x=parseFloat(a.dataset.rate);y=parseFloat(b.dataset.rate);}
    else if(k=='status'){x=ord[a.dataset.status];y=ord[b.dataset.status];}
    else{x=a.dataset[k]||'';y=b.dataset[k]||'';}
    return x<y?-dir:x>y?dir:0;});
  gs.forEach(function(g){t.appendChild(g);});}
"""


CSS = """
:root{--bg:#12100e;--card:#1b1815;--card2:#232019;--ink:#efe7db;--mut:#9a8f80;
--ok:#57b874;--warn:#e0a33c;--bad:#d0555a;--saber:#5bc8ff;--edge:#2c2621}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14.5px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:20px 28px;border-bottom:1px solid var(--edge);position:sticky;top:0;background:var(--bg);z-index:9}
h1{font-size:20px;margin:0}.sub{color:var(--mut);font-size:12.5px;margin-top:2px}
main{max-width:1120px;margin:0 auto;padding:0 24px 70px}.muted{color:var(--mut)}
.overall{margin-left:auto;padding:6px 14px;border-radius:20px;font-weight:650;font-size:13px}
.overall.ok{background:rgba(87,184,116,.16);color:var(--ok)}
.overall.bad{background:rgba(208,85,90,.16);color:var(--bad)}
code{color:var(--saber);font-size:.92em}
.intro{background:var(--card);border:1px solid var(--edge);border-radius:10px;margin:16px 0}
.intro>summary{cursor:pointer;padding:12px 16px;font-weight:600;list-style:none}
.intro>summary::-webkit-details-marker{display:none}
.introbody{padding:0 18px 14px}.introbody p{margin:8px 0}.introbody ul{margin:8px 0;padding-left:18px}
.controls{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:14px 0}
#q{flex:1;min-width:220px;background:var(--card);border:1px solid var(--edge);border-radius:8px;
color:var(--ink);padding:9px 12px;font-size:14px}
#q::placeholder{color:var(--mut)}
.fg{display:inline-flex;align-items:center;gap:4px;font-size:12px;color:var(--mut)}
.fg b{margin-right:4px;font-weight:600}
.fg button{background:var(--card);border:1px solid var(--edge);color:var(--mut);border-radius:14px;
padding:4px 11px;cursor:pointer;font-size:12px}
.fg button.on{background:rgba(91,200,255,.16);color:var(--saber);border-color:transparent}
table{width:100%;border-collapse:collapse}
thead th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);
font-weight:600;padding:8px 10px;border-bottom:1px solid var(--edge);position:sticky;top:63px;background:var(--bg)}
th.sortable{cursor:pointer}th.sortable:hover{color:var(--ink)}
.c-exp{width:26px}.c-suite{width:78px}.c-status{width:78px}.c-rate{width:130px}
tbody.grp{border-bottom:1px solid var(--edge)}
tr.row{cursor:pointer}tr.row:hover td{background:var(--card)}
tr.row td{padding:10px;vertical-align:middle}
.caret{color:var(--mut);display:inline-block;transition:transform .15s}
tbody.grp.open .caret{transform:rotate(90deg)}
.c-name{font-weight:600}.c-bucket{color:var(--mut);font-size:13px}
.pill{font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:6px;text-transform:uppercase;letter-spacing:.03em}
.pill.behavior{background:rgba(91,200,255,.14);color:var(--saber)}
.pill.deterministic{background:rgba(160,140,255,.16);color:#b8a6ff}
.chip{font-size:11px;font-weight:700;padding:2px 9px;border-radius:6px}
.chip.ok{background:rgba(87,184,116,.16);color:var(--ok)}
.chip.warn{background:rgba(224,163,60,.16);color:var(--warn)}
.chip.bad{background:rgba(208,85,90,.16);color:var(--bad)}
.chip.mut{background:var(--card2);color:var(--mut)}
.bar{display:inline-block;width:70px;height:6px;background:#332c26;border-radius:4px;overflow:hidden;vertical-align:middle}
.bar i{display:block;height:100%}.bar i.ok{background:var(--ok)}.bar i.warn{background:var(--warn)}
.bar i.bad{background:var(--bad)}.bar i.mut{background:#4a4038}
.rn{font-variant-numeric:tabular-nums;color:var(--mut);font-size:12px;margin-left:7px}
tr.det{display:none}tbody.grp.open tr.det{display:table-row}
.detwrap{background:var(--card);border:1px solid var(--edge);border-radius:9px;margin:2px 4px 12px;padding:4px 16px 14px}
.field{display:grid;grid-template-columns:170px 1fr;gap:14px;padding:11px 0;border-top:1px solid var(--edge)}
.field:first-child{border-top:none}
.flabel{color:var(--mut);font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;font-weight:600}
.prompt{margin-top:5px;font-style:italic}.rubric{color:var(--ink)}
.kv{border-collapse:collapse;width:100%}.kv td{padding:3px 8px;vertical-align:top;border-bottom:1px solid var(--edge)}
.kv .k{color:var(--mut);white-space:nowrap;width:1%}.kv .v code{color:var(--ink);white-space:pre-wrap;word-break:break-word}
.fixture{background:#0f0d0b;border:1px solid var(--edge);border-radius:8px;padding:8px 10px;max-height:340px;overflow:auto}
.ev{display:flex;gap:9px;padding:3px 0;font-size:13px;align-items:baseline}
.evk{width:16px;text-align:center;color:var(--mut);flex-shrink:0}
.evt{word-break:break-word}.evopt{color:var(--mut);font-size:12px}
.ev.ask .evk{color:var(--saber)}.ev.bash .evk,.ev.edit .evk{color:var(--warn)}
.ev.deny .evk{color:var(--bad)}.ev.ans .evt{color:var(--mut)}
.ev.cfg{color:var(--mut);padding-bottom:6px;margin-bottom:4px;border-bottom:1px dashed var(--edge)}
.evfile{color:var(--mut);font-size:11px;margin:6px 0 2px;text-transform:uppercase;letter-spacing:.04em}
.evmore{color:var(--mut);font-size:12px;padding-top:4px}
.rep{background:var(--card2);border-radius:7px;padding:9px 12px;margin:7px 0}
.rep.bad{background:rgba(208,85,90,.07)}.rephead{font-weight:650;font-size:13px;margin-bottom:5px}
.grade{display:flex;flex-direction:column;gap:3px}.crit{font-size:13px}.crit .muted{font-size:12px}
.raw{margin-top:7px}.raw>summary{cursor:pointer;color:var(--mut);font-size:12px}
.raw pre{white-space:pre-wrap;word-break:break-word;background:#0f0d0b;border:1px solid var(--edge);
border-radius:6px;padding:10px;font-size:12px;max-height:260px;overflow:auto;color:var(--mut)}
footer{color:var(--mut);font-size:12px;padding:26px 0 0}
@media(prefers-color-scheme:light){:root{--bg:#faf7f2;--card:#fff;--card2:#f4efe7;
--ink:#2a2521;--mut:#877c6d;--edge:#e7ddd0}.fixture,.raw pre{background:#f4efe7}}
@media(max-width:660px){.field{grid-template-columns:1fr;gap:4px}.c-bucket{display:none}}
"""


if __name__ == "__main__":
    print("wrote", build())
