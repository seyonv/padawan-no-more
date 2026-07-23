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
                              "fixture": s.get("fixture"), "model": s.get("model"),
                              "blocking": s.get("blocking", True)}
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
                     "blocking": s.get("blocking", ym.get("blocking", True)),
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
                     "blocking": True,
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
            f'<td class="c-name">{esc(r["name"])}'
            + ("" if r.get("blocking", True)
               else ' <span class="nb" title="informational — does not gate the suite">non-blocking</span>')
            + "</td>"
            f'<td class="c-bucket">{esc(r["bucket"])}</td>'
            f'<td class="c-status"><span class="chip {stcls}">{esc(st)}</span></td>'
            f'<td class="c-rate">{bar}<span class="rn">{raten}</span></td></tr>'
            f'<tr class="det"><td colspan="6"><div class="detwrap">{r["detail"]}</div></td></tr>'
            f'</tbody>')
    return "".join(body)


# themes group the many fine-grained buckets into a handful of ideas a newcomer
# can hold in their head; each fine bucket string maps to one theme.
THEMES = [
    ("Getting the numbers right", "The whole map is built on counts — stops, "
     "waiting time, how often you picked the recommended option. If the parser "
     "miscounts, every conclusion downstream is wrong.",
     ["counting + first-option rate", "answer classification",
      "classification at scale", "cross-file dedup", "wait attribution",
      "builtin filtering + attribution", "core functionality"]),
    ("Not crying wolf", "The tool should only flag real interruptions. It must "
     "NOT invent an approval on a permissive machine, or count the words "
     "'has been denied' inside a quoted file as a real denial.",
     ["approval false-positive guard", "denial false-positive guard",
      "approval detection", "approval detection at scale"]),
    ("Telling the truth", "Every number shown must be real — pulled from your "
     "actual scan, never invented, and never the demo's example numbers "
     "presented as yours.",
     ["honesty"]),
    ("Security", "The tool reads your command history and hands you changes to "
     "paste back. It must scrub secrets from that history, escape hostile text "
     "so the map can't run code, and refuse a pasted 'fix' that would delete a "
     "safety rule, hand over broad permissions, or run a remote script.",
     ["security / secret redaction", "security / output escaping",
      "apply-time security"]),
    ("Good judgment, not just detection", "Finding a problem isn't enough — it "
     "must propose the RIGHT fix. Silence a gate that's real signal? No, batch "
     "it. Grant blanket Bash(*) to stop prompts? No, a narrow rule.",
     ["judgment quality"]),
    ("Knowing when to stop", "With too little data it should decline to build a "
     "thin, misleading map; if the transcript format changed, it should warn "
     "rather than silently report zero.",
     ["guardrail", "guardrail: sparse gate", "format-drift warning",
      "interruption dedup"]),
]


def _theme_for(bucket):
    for name, _desc, buckets in THEMES:
        if bucket in buckets:
            return name
    return "Other"


def _explainer(rows):
    # group actual scenarios under each theme so the list is always accurate
    by_theme = {}
    for r in rows:
        by_theme.setdefault(_theme_for(r["bucket"]), []).append(r)
    theme_html = []
    for name, desc, _b in THEMES:
        scen = by_theme.get(name, [])
        chips = " ".join(f'<span class="sc">{esc(s["name"])}</span>' for s in scen)
        theme_html.append(
            f'<div class="theme"><div class="thead">{esc(name)} '
            f'<span class="tcount">{len(scen)} scenario'
            f'{"s" if len(scen)!=1 else ""}</span></div>'
            f'<div class="tdesc">{esc(desc)}</div>'
            f'<div class="scs">{chips}</div></div>')
    return f"""
<details class="intro" open><summary>Start here — what is this page, and what is it testing? ▾</summary>
<div class="introbody">

<h3>1 · What the tool being tested actually does</h3>
<ul>
<li><b>padawan-no-more</b> is a Claude Code skill. You ask it something like
<i>"how often did you stop and wait for me this week?"</i></li>
<li>It reads your local Claude Code history and finds every moment Claude
<b>paused for a human</b> — a question dialog, a plan approval, a permission
prompt you approved, a permission it was denied, or an Escape you pressed.</li>
<li>It <b>traces each stop to its cause</b> (the exact line in a skill, a
settings file, or CLAUDE.md that forced it) and builds an interactive map with
ready-to-apply fix diffs you approve or reject — so Claude needs you less.</li>
<li>It reports hard numbers about <i>your</i> week ("stopped 129 times, 9h
waiting, 80% of the time you picked the option it recommended") and then
proposes config changes. Everything runs locally; nothing is uploaded.</li>
</ul>

<h3>2 · Why a tool like this needs evals</h3>
<ul>
<li>An <b>eval</b> is just an automated test for a behavior we care about —
like a unit test, but for "does it do the <i>right thing</i>," not only "does
the code run."</li>
<li>This tool is only useful if you can <b>trust its numbers</b> and its
proposed changes. A wrong count is misleading; an unsafe "fix" it applies to
your config is dangerous. Those are exactly the things a human reviewer would
eyeball — evals check them automatically, every time, so a change can't quietly
break them.</li>
<li>Each row in the table below is <b>one scenario</b>: a specific situation we
put the tool in, with a known right answer, that passes or fails.</li>
</ul>

<h3>3 · The two kinds of test (the two suites)</h3>
<ul>
<li><b>Deterministic</b> — tests the <i>math</i>. We hand-write a fake
transcript where we already know the correct answer (e.g. "exactly 10 questions,
9 recommended picks, 2 denials") and check the parser produces exactly that.
Fast, free, exact, run on every change.</li>
<li><b>Behavior</b> — tests the <i>judgment</i>. We actually run the whole skill
end-to-end with a real model and grade what it does — partly with automatic
checks, partly with an <b>LLM judge</b> that reads the transcript against a
written rubric. Slower and costs tokens, so it's run on demand. Because a real
model is involved, each scenario runs several times and reports a
<b>pass-rate</b> (e.g. 3/3); a 2/3 is <i>flaky</i> — right most of the time but
slips sometimes, which is a real weakness, not noise.</li>
</ul>

<h3>4 · What we're actually testing — the buckets</h3>
<p>Every scenario belongs to a <b>bucket</b> (shown in the table). Here are the
themes those buckets fall under, and which scenarios cover each:</p>
{"".join(theme_html)}

<h3>5 · How to read one scenario</h3>
<ul>
<li><b>Why this matters</b> — the risk or case it covers.</li>
<li><b>Input</b> — the prompt and the actual <i>fixture</i> (the fake transcript
history we feed in), rendered readably: ❓ questions, ↳ your answers, ⌘ commands,
⛔ denials, ⚙ the permission settings in effect.</li>
<li><b>Expected</b> — the rubric the judge grades against (behavior) or the exact
numbers required (deterministic).</li>
<li><b>Actual</b> — what happened, per run.</li>
<li><b>Grading</b> — pass/fail broken out by criterion, plus the judge's reasoning.</li>
</ul>
<p class="muted">Use the search box and the suite/status filters to slice the
table; click any column header to sort.</p>
</div></details>
"""


def build():
    det, beh = _load_results()
    ymeta = _yaml_scenarios()
    rows = _rows(det, beh, ymeta)
    graded = [r for r in rows if r["status"] != "pending"]
    # non-blocking (informational) scenarios never trigger "attention needed"
    gating = [r for r in graded if r.get("blocking", True)]
    overall_ok = bool(gating) and all(r["status"] == "PASS" for r in gating)
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
{_explainer(rows)}
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
.introbody{padding:0 20px 18px}.introbody p{margin:8px 0}.introbody ul{margin:8px 0;padding-left:20px}
.introbody li{margin:5px 0}
.introbody h3{font-size:14px;margin:20px 0 6px;color:var(--saber);font-weight:650}
.theme{background:var(--card2);border-radius:8px;padding:10px 13px;margin:8px 0}
.thead{font-weight:650;font-size:13.5px}
.tcount{color:var(--mut);font-weight:400;font-size:12px;margin-left:6px}
.tdesc{color:var(--ink);font-size:13px;margin:4px 0 7px}
.scs{display:flex;flex-wrap:wrap;gap:5px}
.sc{font-size:11.5px;background:rgba(91,200,255,.12);color:var(--saber);
padding:2px 8px;border-radius:10px;font-family:ui-monospace,monospace}
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
.nb{font-size:10px;font-weight:600;color:var(--mut);border:1px solid var(--edge);
border-radius:9px;padding:1px 6px;margin-left:6px;text-transform:uppercase;letter-spacing:.03em}
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
