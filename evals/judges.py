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


def judge_once(rubric, transcript, model=None):
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
    return {"pass": None,  # unparseable → don't let it count as a real "fail" vote
            "reason": f"judge output unparseable: {r.stdout[:160]!r}"}


def judge(rubric, transcript, model=None, votes=None):
    """Ensemble judge: grade `votes` times and take the majority. An LLM judge is
    itself non-deterministic, so a lone grumpy sample can flip a borderline-good
    answer to fail — majority voting removes that as a flakiness source. Ties and
    unparseable ballots are excluded from the count; default vote count comes from
    EVAL_JUDGE_VOTES (falls back to 3)."""
    votes = votes or int(os.environ.get("EVAL_JUDGE_VOTES", "3"))
    ballots = [judge_once(rubric, transcript, model) for _ in range(votes)]
    valid = [b for b in ballots if b["pass"] is not None]
    if not valid:
        return {"pass": False, "reason": ballots[0]["reason"], "votes": "0/0"}
    n_pass = sum(1 for b in valid if b["pass"])
    verdict = n_pass * 2 > len(valid)  # strict majority of parseable ballots
    # surface a reason from a judge that agreed with the verdict
    reason = next((b["reason"] for b in valid if b["pass"] == verdict), valid[0]["reason"])
    return {"pass": verdict, "votes": f"{n_pass}/{len(valid)}",
            "reason": f"[{n_pass}/{len(valid)} judges say pass] {reason}"}
