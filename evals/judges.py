"""LLM judge for behavior evals — shells out to `claude -p` (no separate key)."""
import json
import os
import re
import subprocess


def _parse_verdict(stdout):
    """Extract {pass, reason} from judge output, tolerating the JSON quirks LLMs
    emit — invalid `\\'` escapes, smart quotes, trailing prose. Returns None only
    when no verdict can be recovered at all."""
    try:
        chunk = stdout[stdout.index("{"):stdout.rindex("}") + 1]
    except ValueError:
        chunk = stdout
    for candidate in (chunk, chunk.replace("\\'", "'"), chunk.replace("\\'", "'")
                      .replace("‘", "'").replace("’", "'")):
        try:
            v = json.loads(candidate)
            return {"pass": bool(v.get("pass")), "reason": str(v.get("reason", ""))[:500]}
        except (ValueError, json.JSONDecodeError):
            continue
    # last resort: the boolean is unambiguous even when the string escaping isn't
    m = re.search(r'"pass"\s*:\s*(true|false)', chunk, re.I)
    if m:
        rm = re.search(r'"reason"\s*:\s*"(.+)', chunk, re.S)
        reason = re.sub(r'["\s]+$', "", rm.group(1))[:500] if rm else "(reason unparsed)"
        return {"pass": m.group(1).lower() == "true", "reason": reason}
    return None


def judge(rubric, transcript, model=None):
    model = model or os.environ.get("EVAL_JUDGE_MODEL", "sonnet")
    prompt = (
        "You are grading an AI assistant's transcript against a rubric.\n"
        f"RUBRIC:\n{rubric}\n\nTRANSCRIPT:\n{transcript[:100000]}\n\n"
        'Answer with ONLY a JSON object: {"pass": true|false, "reason": "..."}. '
        "Do not use backslash-escaped single quotes; use plain single quotes in prose."
    )
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    r = subprocess.run(["claude", "-p", prompt, "--model", model],
                       capture_output=True, text=True, timeout=300, env=env)
    v = _parse_verdict(r.stdout)
    if v is not None:
        return v
    return {"pass": False,
            "reason": f"judge output unparseable: {r.stdout[:200]!r} {r.stderr[:100]!r}"}
