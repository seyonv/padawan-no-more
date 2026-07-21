#!/usr/bin/env python3
"""Scan Claude Code transcripts for human-intervention events.

Usage: python3 scan.py [--days 7] [--out interventions.json]

Emits one JSON file with:
  events[]   — every intervention: option dialogs (with which option was picked),
               plan approvals, permission denials, interruptions, dismissed dialogs.
               Each carries project, session, skill in effect, and wait_s (seconds
               between the blocking tool call and the human's answer).
  sessions[] — per-session intervention counts (for the per-project rate chart).
"""
import json, os, glob, re, sys, time, argparse, fnmatch
from datetime import datetime

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=7)
ap.add_argument("--out", default="interventions.json")
ap.add_argument("--no-approvals", action="store_true",
                help="skip the approved-prompt proxy (denials/gates only)")
args = ap.parse_args()

CUTOFF = time.time() - args.days * 86400
DISPLAY_CAP = 1800  # walk-away cap for the printed wait summary (build_page has its own --cap)
# builtin slash commands are not skills; capturing them steals attribution from
# the real gate skill, and /clear starts a fresh conversation
BUILTINS = {"clear", "compact", "context", "model", "help", "init", "review",
            "cost", "config", "doctor", "login", "logout", "resume", "status",
            "vim", "memory", "mcp", "agents", "add-dir", "terminal-setup"}
# a real permission/rejection message IS the entire tool_result and starts with
# one of these; matching the substring anywhere flags file dumps that merely
# quote scan output as denials
DENIAL_PREFIXES = ("Permission to use", "The user doesn't want to proceed")
# Approved permission prompts leave no marker in the transcript (only denials do),
# so we infer them: a mutating tool that ran successfully, in a mode where a prompt
# was possible, whose (tool,input) no allow-rule covers → you almost certainly saw
# a prompt and approved it. Conservative by design (a lower bound): we only look at
# clearly prompt-worthy tools and treat unparseable rules as covering (never flag
# when unsure), so on a permissive setup this yields ~zero.
MUTATING = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
NOPROMPT_MODES = {"bypassPermissions", "auto"}  # nothing prompts in these modes
HOME = os.path.expanduser("~")

# The map surfaces command history as card evidence, and the transmission block
# is copied between sessions — so any credential captured in a command must be
# masked here, at the source, before it can reach cards.json / map.html.
REDACTED = "‹redacted›"
_SECRET_PATTERNS = [
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}\b"),   # Stripe
    re.compile(r"\bsk-[A-Za-z0-9\-]{20,}\b"),                  # OpenAI/Anthropic-style
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),           # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}\b"),  # JWT
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}"),
]
# credentials embedded in a URL: scheme://user:SECRET@host
_URL_CRED = re.compile(r"(https?://[^:@/\s]+:)([^@/\s]+)(@)")
# key=VALUE / "token": "VALUE" style assignments with a long opaque value
_ASSIGN = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password|passwd|access[_-]?key|auth[_-]?token)"
    r"[\"'\s]*[=:]\s*[\"']?)([A-Za-z0-9._\-/+]{12,})")


def _redact(s):
    if not s or not isinstance(s, str):
        return s
    s = _URL_CRED.sub(r"\1" + REDACTED + r"\3", s)
    s = _ASSIGN.sub(lambda m: m.group(1) + REDACTED, s)
    for pat in _SECRET_PATTERNS:
        s = pat.sub(REDACTED, s)
    return s


_allow_cache = {}
def _load_allow(path):
    if path not in _allow_cache:
        try:
            d = json.load(open(path))
            _allow_cache[path] = (d.get("permissions") or {}).get("allow") or []
        except (OSError, ValueError, AttributeError):
            _allow_cache[path] = []
    return _allow_cache[path]

def effective_allow(cwd):
    """Union of global + project + local allow-rules in effect for a session."""
    rules = list(_load_allow(os.path.join(HOME, ".claude/settings.json")))
    rules += _load_allow(os.path.join(HOME, ".claude/settings.local.json"))
    if cwd:
        rules += _load_allow(os.path.join(cwd, ".claude/settings.json"))
        rules += _load_allow(os.path.join(cwd, ".claude/settings.local.json"))
    return rules

def _rule_covers(tool, inp, rule):
    rt, ra = (rule[:rule.index("(")], rule[rule.index("(") + 1:-1]) \
        if "(" in rule and rule.endswith(")") else (rule, None)
    if not (rt == tool or ("*" in rt and fnmatch.fnmatch(tool, rt))):
        return False
    if ra in (None, "*"):
        return True
    if tool == "Bash":
        cmd = (inp or {}).get("command", "")
        return fnmatch.fnmatch(cmd, ra) or cmd.startswith(ra.rstrip("* "))
    p = (inp or {}).get("file_path") or (inp or {}).get("path") or ""
    return bool(p) and (fnmatch.fnmatch(p, ra) or fnmatch.fnmatch(p, ra.rstrip("*") + "*"))

def would_prompt(tool, inp, mode, allowset):
    """True if this successful tool call almost certainly required approval."""
    if mode in NOPROMPT_MODES:
        return False
    if mode == "acceptEdits" and tool in EDIT_TOOLS:
        return False
    return not any(_rule_covers(tool, inp, r) for r in allowset)
files = [f for f in glob.glob(os.path.join(HOME, ".claude/projects/*/*.jsonl"))
         if os.path.getmtime(f) >= CUTOFF]

_home_slug = HOME.replace("/", "-")

def proj_name(f):
    d = os.path.basename(os.path.dirname(f))
    if d.startswith(_home_slug):
        d = d[len(_home_slug):]
    d = d.lstrip("-")
    for prefix in ("Desktop-repos-", "Desktop-", "repos-", "src-", "code-"):
        if d.startswith(prefix):
            d = d[len(prefix):]
            break
    return d or "(home)"

def parse_ts(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))

events, sessions = [], {}
raw_dialog_uses = 0  # AskUserQuestion/ExitPlanMode tool_uses seen (for drift detection)

for f in files:
    proj, sess = proj_name(f), os.path.basename(f)[:8]
    key = f"{proj}/{sess}"
    sessions[key] = {"project": proj, "session": sess, "interventions": 0}
    pending, cur_skill, ts = {}, None, None
    cur_mode, cwd, allowset, approved_seen = "default", None, None, set()
    try:
        fh = open(f)
    except OSError:
        continue
    for line in fh:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("isSidechain"):  # subagent activity, not a human intervention
            continue
        if obj.get("cwd"): cwd = obj["cwd"]
        if obj.get("permissionMode"): cur_mode = obj["permissionMode"]
        ts = obj.get("timestamp", ts)
        typ = obj.get("type")
        content = (obj.get("message") or {}).get("content")
        if typ == "user" and isinstance(content, str):
            m = re.search(r"<command-name>/?([\w:-]+)</command-name>", content)
            if m:
                name = m.group(1)
                if name == "clear": cur_skill = None       # fresh conversation
                elif name not in BUILTINS: cur_skill = name
            # skip "for tool use" interruptions — they always accompany the
            # denial/dismissal tool_result they belong to (double counting)
            if "[Request interrupted by user" in content and "for tool use" not in content:
                events.append(dict(type="interruption", project=proj, session=sess, ts=ts,
                                   skill=cur_skill, detail=content[:200], wait_s=None))
                sessions[key]["interventions"] += 1
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict): continue
            if (c.get("type") == "text" and typ == "user"
                    and "[Request interrupted by user" in c.get("text", "")
                    and "for tool use" not in c.get("text", "")):
                events.append(dict(type="interruption", project=proj, session=sess, ts=ts,
                                   skill=cur_skill, detail=c.get("text", "")[:200], wait_s=None))
                sessions[key]["interventions"] += 1
            if c.get("type") == "tool_use":
                if c.get("name") == "Skill":
                    cur_skill = (c.get("input") or {}).get("skill", cur_skill)
                if c.get("name") in ("AskUserQuestion", "ExitPlanMode"):
                    raw_dialog_uses += 1
                pending[c.get("id")] = (c.get("name", ""), c.get("input"), cur_skill, ts, cur_mode)
            elif c.get("type") == "tool_result":
                tid = c.get("tool_use_id")
                if tid not in pending: continue
                name, inp, skill_at, ts_use, mode_use = pending[tid]
                wait_s = None
                try:
                    if ts_use and ts:
                        wait_s = max(0, (parse_ts(ts) - parse_ts(ts_use)).total_seconds())
                except ValueError:
                    pass
                rc = c.get("content")
                text = rc if isinstance(rc, str) else (
                    " ".join(x.get("text", "") for x in rc if isinstance(x, dict)) if isinstance(rc, list) else "")
                if name == "AskUserQuestion":
                    if text.strip().startswith("The user doesn't want to proceed"):
                        events.append(dict(type="ask_rejected", project=proj, session=sess, ts=ts,
                                           skill=skill_at, wait_s=wait_s,
                                           questions=[q.get("question", "")[:200] for q in (inp or {}).get("questions", [])]))
                        sessions[key]["interventions"] += 1
                        continue
                    qs = (inp or {}).get("questions", [])
                    qpos = [(text.find(q.get("question", "")), q.get("question", "")) for q in qs]
                    bounds = sorted(i for i, _ in qpos if i >= 0)
                    endmark = text.find(". You can now continue")
                    for qi, ((i, qt), q) in enumerate(zip(qpos, qs)):
                        opts = [o.get("label", "") for o in q.get("options", [])]
                        ans = None
                        if i >= 0:
                            start = i + len(qt)
                            if text[start:start + 3] == '"="':
                                start += 3
                                nxt = [b for b in bounds if b > i]
                                end = (nxt[0] if nxt else (endmark if endmark > start else len(text)))
                                seg = text[start:end]
                                # a preview-style option echoes `Label" selected preview:…`
                                # after the label; drop it before matching the label
                                cut = seg.find('" selected preview:')
                                if cut >= 0: seg = seg[:cut]
                                ans = re.sub(r'"\s*,\s*"?$', '', seg).rstrip()
                                if ans.endswith('"'): ans = ans[:-1]
                        rank, kind = None, "unanswered"
                        if ans is not None:
                            if ans in opts:
                                rank, kind = opts.index(ans), "option"
                            else:
                                parts = [p.strip() for p in ans.split(",")]
                                if parts and all(p in opts for p in parts):
                                    rank, kind = min(opts.index(p) for p in parts), "option"
                                else:
                                    kind = "freetext"
                        # one dialog = one wait; charge it to the first question only
                        # so a 3-question dialog isn't counted as 3× the blocked time
                        events.append(dict(type="ask_question", project=proj, session=sess, ts=ts,
                                           skill=skill_at, wait_s=(wait_s if qi == 0 else None),
                                           question=qt[:250], options=opts,
                                           selected=(ans or "")[:250], selected_rank=rank, kind=kind,
                                           multi=bool(q.get("multiSelect"))))
                        sessions[key]["interventions"] += 1
                elif name == "ExitPlanMode":
                    head = text.lower()[:200]
                    approved = "approved" in head and "doesn't want" not in head
                    events.append(dict(type="plan_approval", project=proj, session=sess, ts=ts,
                                       skill=skill_at, wait_s=wait_s,
                                       outcome="approved" if approved else "rejected",
                                       plan_head=((inp or {}).get("plan", "") or "")[:150]))
                    sessions[key]["interventions"] += 1
                elif text.strip().startswith(DENIAL_PREFIXES):
                    detail = (inp or {}).get("command", "")[:250] if name == "Bash" else json.dumps(inp or {})[:200]
                    events.append(dict(type="denial", project=proj, session=sess, ts=ts,
                                       skill=skill_at, wait_s=wait_s, tool=name, detail=detail,
                                       result=text[:250]))
                    sessions[key]["interventions"] += 1
                elif (not args.no_approvals and name in MUTATING
                      and not c.get("is_error")):
                    # inferred approved prompt: a mutating tool that ran with no
                    # allow-rule covering it, in a mode where a prompt was possible
                    if allowset is None:
                        allowset = effective_allow(cwd)
                    if would_prompt(name, inp, mode_use, allowset):
                        detail = ((inp or {}).get("command")
                                  or (inp or {}).get("file_path")
                                  or (inp or {}).get("url") or "")[:250]
                        # one grant covers a repeated command for the session; count
                        # each distinct (tool, command-family) once → a lower bound
                        fam = detail if name != "Bash" else " ".join(detail.split()[:3])
                        if (name, fam) not in approved_seen:
                            approved_seen.add((name, fam))
                            events.append(dict(type="approval", project=proj, session=sess,
                                               ts=ts, skill=skill_at, wait_s=wait_s, tool=name,
                                               detail=detail, mode=mode_use))
                            sessions[key]["interventions"] += 1
    fh.close()

# drop events older than the window (a long-lived session file can hold months
# of history yet still be recently modified), then recount per-session
def _in_window(e):
    t = e.get("ts")
    if not t:
        return True
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() >= CUTOFF
    except ValueError:
        return True

events = [e for e in events if _in_window(e)]

# redact secrets from every human-readable text field before anything downstream
# (build_page.py, the transmission) can render them
_TEXT_FIELDS = ("detail", "command", "result", "plan_head", "selected", "question")
for e in events:
    for k in _TEXT_FIELDS:
        if isinstance(e.get(k), str):
            e[k] = _redact(e[k])
    if isinstance(e.get("questions"), list):
        e["questions"] = [_redact(q) for q in e["questions"]]

# resuming a conversation copies its earlier history into a NEW session file, so
# the same event can appear in two files — dedupe by (type, timestamp, subject),
# ignoring session id, so one stop isn't counted (and its wait summed) twice
def _sig(e):
    subj = (e.get("question") or e.get("detail") or e.get("plan_head")
            or " ".join(e.get("questions") or []) or "")
    return (e["type"], e.get("ts"), subj[:120])

_seen, _deduped = set(), []
for e in events:
    s = _sig(e)
    if s in _seen:
        continue
    _seen.add(s)
    _deduped.append(e)
events = _deduped

for s in sessions.values():
    s["interventions"] = 0
for e in events:
    sessions[f"{e['project']}/{e['session']}"]["interventions"] += 1

json.dump({"events": events, "sessions": list(sessions.values()),
           "meta": {"days": args.days, "files": len(files)}}, open(args.out, "w"))

from collections import Counter
tc = Counter(e["type"] for e in events)
sk = Counter(e.get("skill") or "(direct)" for e in events if e["type"] == "ask_question")
first = sum(1 for e in events if e["type"] == "ask_question" and e.get("selected_rank") == 0)
waits = [e["wait_s"] for e in events if e.get("wait_s")]
capped_wait = sum(min(w, DISPLAY_CAP) for w in waits)
nq = tc.get("ask_question", 0)
n_over = sum(1 for w in waits if w > DISPLAY_CAP)


def fdur(s):
    if s >= 3600:
        return f"{int(s // 3600)}h {int(s % 3600 // 60):02d}m"
    return f"{int(s // 60)}m {int(s % 60):02d}s" if s >= 60 else f"{int(s)}s"


top = sk.most_common(1)
kinds = " · ".join(f"{v} {k.replace('_', ' ')}s" for k, v in tc.most_common())
print()
print("  ⚔  SCANNING THE ARCHIVES " + "─" * 30)
print(f"  ├─ session logs read   {len(files)} (last {args.days} days)")
print(f"  ├─ stops found         {len(events)}  ({kinds})")
over_note = f" (+{n_over} capped at {DISPLAY_CAP // 60}m — walk-aways)" if n_over else ""
print(f"  ├─ time kept waiting   {fdur(capped_wait)} across {len(waits)} timed stops{over_note}")
if nq:
    print(f"  ├─ 'yes, do that'      {first}/{nq} answers took the recommended option")
if top:
    print(f"  ├─ loudest gate        {top[0][0]} ({top[0][1]} dialogs)")
print(f"  └─ wrote               {args.out}")
# format drift: we saw dialog tool_uses but parsed almost no answers → the
# transcript strings we key on likely changed; a clean zero would be misleading
answered = sum(1 for e in events if e["type"] == "ask_question" and e.get("kind") != "unanswered")
if raw_dialog_uses >= 5 and answered <= raw_dialog_uses * 0.2:
    print()
    print(f"  ⚠  Saw {raw_dialog_uses} question/plan dialogs but parsed only {answered} answers —")
    print("     the transcript format may have changed. Treat these numbers as unreliable")
    print("     and check for a Claude Code update before trusting the map.")
if len(events) < 15:
    print()
    print("  Sparse archives — fewer than 15 stops in this window. The map will be thin;")
    print("  consider a wider window (--days 30) or the training simulation:")
    print("  build_page.py --scan examples/interventions.example.json "
          "--cards examples/cards.example.json --demo")
print()
