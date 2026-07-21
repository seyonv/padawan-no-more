"""LLM judge for behavior evals — shells out to `claude -p` (no separate key)."""
import json
import os
import subprocess


def judge(rubric, transcript, model=None):
    model = model or os.environ.get("EVAL_JUDGE_MODEL", "sonnet")
    prompt = (
        "You are grading an AI assistant's transcript against a rubric.\n"
        f"RUBRIC:\n{rubric}\n\nTRANSCRIPT:\n{transcript[:100000]}\n\n"
        'Answer with ONLY a JSON object: {"pass": true|false, "reason": "..."}'
    )
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    r = subprocess.run(["claude", "-p", prompt, "--model", model],
                       capture_output=True, text=True, timeout=300, env=env)
    try:
        s = r.stdout[r.stdout.index("{"):r.stdout.rindex("}") + 1]
        v = json.loads(s)
        return {"pass": bool(v.get("pass")), "reason": str(v.get("reason", ""))[:500]}
    except (ValueError, json.JSONDecodeError):
        return {"pass": False,
                "reason": f"judge output unparseable: {r.stdout[:200]!r} {r.stderr[:100]!r}"}
