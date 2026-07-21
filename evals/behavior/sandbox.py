"""Sandboxed $HOME for behavior evals: fixture archive + the skill installed.

make_sandbox(fixture_name) -> {"home": ..., "cwd": ...}
run_claude(prompt, sandbox)  -> {"stdout": ..., "stderr": ..., "code": ...}
"""
import json
import os
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(ROOT, "evals", "fixtures", "scenarios")
SKILL_FILES = ["SKILL.md", "scripts", "assets", "examples"]
REAL_HOME = os.path.expanduser("~")


def make_sandbox(fixture_name):
    """Build a temp HOME: fixture .claude/projects tree (optional), the skill
    under .claude/skills/padawan-no-more, seeded config + credentials, and an
    empty throwaway project cwd."""
    base = tempfile.mkdtemp(prefix="pnm-beh-")
    home = os.path.join(base, "home")
    cwd = os.path.join(base, "project")
    os.makedirs(cwd)
    if fixture_name:
        src = os.path.join(FIXTURES, fixture_name, "home")
        shutil.copytree(src, home)
    os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
    skill_dst = os.path.join(home, ".claude", "skills", "padawan-no-more")
    os.makedirs(skill_dst)
    for name in SKILL_FILES:
        src = os.path.join(ROOT, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(skill_dst, name),
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy(src, skill_dst)
    with open(os.path.join(home, ".claude.json"), "w") as fh:
        fh.write('{"hasCompletedOnboarding": true}')
    dst = os.path.join(home, ".claude", ".credentials.json")
    creds = os.path.join(REAL_HOME, ".claude", ".credentials.json")
    if os.path.isfile(creds):
        shutil.copy(creds, dst)
    else:
        # macOS stores them in the Keychain; the sandbox HOME can't see it
        p = subprocess.run(["security", "find-generic-password",
                            "-s", "Claude Code-credentials", "-w"],
                           capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            with open(dst, "w") as fh:
                fh.write(p.stdout.strip())
            os.chmod(dst, 0o600)
    # no-op `open`/`xdg-open` shims so eval runs never pop real browser tabs
    bindir = os.path.join(base, "bin")
    os.makedirs(bindir)
    for shim in ("open", "xdg-open"):
        sp = os.path.join(bindir, shim)
        with open(sp, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(sp, 0o755)
    return {"home": home, "cwd": cwd, "bin": bindir}


def _tool_summary(name, inp):
    inp = inp or {}
    if name == "Bash":
        return f"Bash: {str(inp.get('command',''))[:140]}"
    if name in ("Write", "Edit", "MultiEdit", "Read", "NotebookEdit"):
        return f"{name}: {inp.get('file_path') or inp.get('path','')}"
    if name == "Skill":
        return f"Skill: {inp.get('skill','')}"
    return f"{name}: {json.dumps(inp)[:120]}"


def _parse_stream(raw):
    """Reconstruct the assistant's narration text and the list of tools it ran
    from claude -p --output-format stream-json (JSONL)."""
    texts, tools = [], []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("type") == "assistant":
            for c in (obj.get("message") or {}).get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text":
                    texts.append(c.get("text", ""))
                elif c.get("type") == "tool_use":
                    tools.append(_tool_summary(c.get("name", ""), c.get("input")))
        elif obj.get("type") == "result" and obj.get("result"):
            texts.append(obj["result"])
    return "\n".join(t for t in texts if t), tools


def run_claude(prompt, sandbox, model=None, timeout=600):
    model = model or os.environ.get("EVAL_MODEL", "haiku")
    env = dict(os.environ, HOME=sandbox["home"],
               PATH=sandbox["bin"] + os.pathsep + os.environ.get("PATH", ""))
    env.pop("CLAUDECODE", None)  # allow nested runs
    # stream-json exposes the tool calls (scan.py, build_page.py, …) so the judge
    # can verify the work actually ran, not just the narration claiming it did
    p = subprocess.run(["claude", "-p", prompt, "--model", model,
                        "--dangerously-skip-permissions",
                        "--output-format", "stream-json", "--verbose"],
                       cwd=sandbox["cwd"], env=env,
                       capture_output=True, text=True, timeout=timeout)
    text, tools = _parse_stream(p.stdout)
    if not text:  # fall back to raw if the format ever changes, so checks don't break
        text = p.stdout
    return {"stdout": text, "tools": tools, "stderr": p.stderr, "code": p.returncode}
