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
import json, os, glob, re, sys, time, argparse
from datetime import datetime

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=7)
ap.add_argument("--out", default="interventions.json")
args = ap.parse_args()

CUTOFF = time.time() - args.days * 86400
HOME = os.path.expanduser("~")
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

for f in files:
    proj, sess = proj_name(f), os.path.basename(f)[:8]
    key = f"{proj}/{sess}"
    sessions[key] = {"project": proj, "session": sess, "interventions": 0}
    pending, cur_skill, ts = {}, None, None
    try:
        fh = open(f)
    except OSError:
        continue
    for line in fh:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        ts = obj.get("timestamp", ts)
        typ = obj.get("type")
        content = (obj.get("message") or {}).get("content")
        if typ == "user" and isinstance(content, str):
            m = re.search(r"<command-name>/?([\w:-]+)</command-name>", content)
            if m: cur_skill = m.group(1)
            if "[Request interrupted by user" in content:
                events.append(dict(type="interruption", project=proj, session=sess, ts=ts,
                                   skill=cur_skill, detail=content[:200], wait_s=None))
                sessions[key]["interventions"] += 1
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict): continue
            if c.get("type") == "text" and typ == "user" and "[Request interrupted by user" in c.get("text", ""):
                events.append(dict(type="interruption", project=proj, session=sess, ts=ts,
                                   skill=cur_skill, detail=c.get("text", "")[:200], wait_s=None))
                sessions[key]["interventions"] += 1
            if c.get("type") == "tool_use":
                if c.get("name") == "Skill":
                    cur_skill = (c.get("input") or {}).get("skill", cur_skill)
                pending[c.get("id")] = (c.get("name", ""), c.get("input"), cur_skill, ts)
            elif c.get("type") == "tool_result":
                tid = c.get("tool_use_id")
                if tid not in pending: continue
                name, inp, skill_at, ts_use = pending[tid]
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
                    if "doesn't want to proceed" in text:
                        events.append(dict(type="ask_rejected", project=proj, session=sess, ts=ts,
                                           skill=skill_at, wait_s=wait_s,
                                           questions=[q.get("question", "")[:200] for q in (inp or {}).get("questions", [])]))
                        sessions[key]["interventions"] += 1
                        continue
                    qs = (inp or {}).get("questions", [])
                    qpos = [(text.find(q.get("question", "")), q.get("question", "")) for q in qs]
                    bounds = sorted(i for i, _ in qpos if i >= 0)
                    endmark = text.find(". You can now continue")
                    for (i, qt), q in zip(qpos, qs):
                        opts = [o.get("label", "") for o in q.get("options", [])]
                        ans = None
                        if i >= 0:
                            start = i + len(qt)
                            if text[start:start + 3] == '"="':
                                start += 3
                                nxt = [b for b in bounds if b > i]
                                end = (nxt[0] if nxt else (endmark if endmark > start else len(text)))
                                ans = re.sub(r'"\s*,\s*"?$', '', text[start:end]).rstrip()
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
                        events.append(dict(type="ask_question", project=proj, session=sess, ts=ts,
                                           skill=skill_at, wait_s=wait_s, question=qt[:250], options=opts,
                                           selected=(ans or "")[:250], selected_rank=rank, kind=kind,
                                           multi=bool(q.get("multiSelect"))))
                        sessions[key]["interventions"] += 1
                elif name == "ExitPlanMode":
                    approved = "approved" in text.lower()[:200] and "doesn't want" not in text
                    events.append(dict(type="plan_approval", project=proj, session=sess, ts=ts,
                                       skill=skill_at, wait_s=wait_s,
                                       outcome="approved" if approved else "rejected",
                                       plan_head=((inp or {}).get("plan", "") or "")[:150]))
                    sessions[key]["interventions"] += 1
                elif "has been denied" in text or "doesn't want to proceed" in text:
                    detail = (inp or {}).get("command", "")[:250] if name == "Bash" else json.dumps(inp or {})[:200]
                    events.append(dict(type="denial", project=proj, session=sess, ts=ts,
                                       skill=skill_at, wait_s=wait_s, tool=name, detail=detail,
                                       result=text[:250]))
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
nq = tc.get("ask_question", 0)


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
print(f"  ├─ time kept waiting   {fdur(sum(waits))} across {len(waits)} timed stops")
if nq:
    print(f"  ├─ 'yes, do that'      {first}/{nq} answers took the recommended option")
if top:
    print(f"  ├─ loudest gate        {top[0][0]} ({top[0][1]} dialogs)")
print(f"  └─ wrote               {args.out}")
if len(events) < 15:
    print()
    print("  Sparse archives — fewer than 15 stops in this window. The map will be thin;")
    print("  consider a wider window (--days 30) or the training simulation:")
    print("  build_page.py --scan examples/interventions.example.json "
          "--cards examples/cards.example.json --demo")
print()
