"""Shared fixtures for the padawan-no-more test suite.

The scripts are stdlib-only and run end-to-end, so tests drive the real
entry points as subprocesses against a synthetic $HOME containing crafted
transcripts and settings. That validates the actual parser behavior, not a
reimplementation of it.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(ROOT, "scripts", "scan.py")
BUILD = os.path.join(ROOT, "scripts", "build_page.py")
TEMPLATE = os.path.join(ROOT, "assets", "template.html")


def assistant(tool_uses, cwd="/proj/app", ts="2026-07-19T10:00:00.000Z", extra=None):
    """A transcript line holding one or more tool_use blocks."""
    o = {"type": "assistant", "timestamp": ts, "cwd": cwd,
         "message": {"content": [{"type": "tool_use", **tu} for tu in tool_uses]}}
    if extra:
        o.update(extra)
    return o


def result(tool_use_id, content, ts="2026-07-19T10:00:08.000Z", is_error=False):
    blk = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        blk["is_error"] = True
    return {"type": "user", "timestamp": ts, "message": {"content": [blk]}}


def user_text(text, ts="2026-07-19T10:00:00.000Z"):
    return {"type": "user", "timestamp": ts, "message": {"content": text}}


def mode_line(mode):
    return {"type": "permission-mode", "permissionMode": mode}


def run_scan(sessions, settings=None, project_settings=None, days=3650, extra_args=()):
    """Write a fake $HOME, run scan.py against it, return parsed interventions.json.

    sessions: dict of {relative_project_dir: [rows...]} — each list is one .jsonl.
    settings: dict written to ~/.claude/settings.json (permissions block).
    project_settings: dict of {abs_cwd_path: permissions-dict} for project settings.
    """
    home = tempfile.mkdtemp(prefix="pnm-home-")
    cdir = os.path.join(home, ".claude")
    os.makedirs(os.path.join(cdir, "projects"))
    if settings is not None:
        with open(os.path.join(cdir, "settings.json"), "w") as fh:
            json.dump({"permissions": settings}, fh)
    for cwd, perms in (project_settings or {}).items():
        pc = os.path.join(cwd, ".claude")
        os.makedirs(pc, exist_ok=True)
        with open(os.path.join(pc, "settings.json"), "w") as fh:
            json.dump({"permissions": perms}, fh)
    for projdir, rows in sessions.items():
        d = os.path.join(cdir, "projects", projdir)
        os.makedirs(d, exist_ok=True)
        sess = f"{abs(hash(projdir)) % 10 ** 8:08d}"
        with open(os.path.join(d, f"{sess}.jsonl"), "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows))
    out = os.path.join(home, "interventions.json")
    env = dict(os.environ, HOME=home)
    subprocess.run([sys.executable, SCAN, "--days", str(days), "--out", out,
                    *extra_args], env=env, check=True, capture_output=True, text=True)
    with open(out) as fh:
        return json.load(fh)


def types(data):
    from collections import Counter
    return dict(Counter(e["type"] for e in data["events"]))


def of_type(data, t):
    return [e for e in data["events"] if e["type"] == t]
