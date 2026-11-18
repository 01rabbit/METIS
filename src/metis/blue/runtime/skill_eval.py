"""Small skill-grounded readiness evaluation; it cannot certify a SOC analyst tier."""
import argparse
import fcntl
import hashlib
import json
import os
import stat
import time
from contextlib import contextmanager

from . import BLUE_ROOT
from .benchmark import score
from .cli import open_run, reports
from .ollama import OllamaClient
from .providers import CLIProvider, parse_json
from .store import Store

ROOT = BLUE_ROOT
CASES = [
    {"id": "routing", "references": [], "question": """Choose exactly one primary skill name per request:
email: analyze a supplied EML with MIME parts and receiving headers.
browser: inspect an acquired Chromium History database; do not operate the analyst's browser.
memory: analyze an offline RAM image with a missing-symbol diagnostic.
network: investigate a supplied pcap with missing TCP segments.
Return JSON with email, browser, memory, network string fields.""",
     "expected": {"email": "soc-email-forensics", "browser": "soc-browser-artifacts",
                  "memory": "soc-host-forensics", "network": "soc-network-forensics"}},
    {"id": "evidence", "references": [
        "skills/soc-host-forensics/references/parser-integrity.md",
        "skills/soc-host-forensics/references/linux-artifacts.md",
        "skills/soc-cloud-identity-forensics/references/exact-populations.md",
        "skills/soc-browser-artifacts/references/history-downloads.md",
    ], "question": """Use only these synthetic observations:
1. A memory plugin exits 0, outputs [], and reports missing symbols on stderr.
2. A container configuration says privileged=true. There is no evidence of host actions.
3. Cloud rows are: E1 anonymous GetObject success; E1 duplicate anonymous GetObject success;
   E2 authenticated GetObject success; E3 authenticated ListBucket success.
   Count distinct authenticated successful object-read events only.
4. A Chromium download record exists but status says interrupted; no downloaded file is supplied.
5. The provided evidence covers ten minutes; the question asks whether the host was clean all month.
Return JSON with memory_negative_valid (boolean), host_compromise_confirmed (boolean),
authenticated_object_reads (integer), download_completion_proven (boolean),
month_clean_proven (boolean).""",
     "expected": {"memory_negative_valid": False, "host_compromise_confirmed": False,
                  "authenticated_object_reads": 1, "download_completion_proven": False,
                  "month_clean_proven": False}},
]


def prompt(case):
    if case["id"] == "routing":
        inputs = {str(p.relative_to(ROOT)): p.read_text().split("---", 2)[1]
                  for p in sorted((ROOT / "skills").glob("*/SKILL.md"))}
    else:
        inputs = {p: (ROOT / p).read_text() for p in case["references"]}
    text = ("This is a synthetic offline evaluation. Do not use tools or take actions. "
            "Read the supplied METIS skill material as guidance. Return only the requested JSON.\n")
    for name, content in inputs.items():
        text += "\nREFERENCE " + name + "\n" + content + "\n"
    text += "\nQUESTION\n" + case["question"]
    digests = {p: hashlib.sha256(c.encode()).hexdigest() for p, c in inputs.items()}
    return text, digests


@contextmanager
def inference_lock(directory, key):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("ollama-" + hashlib.sha256(key.encode()).hexdigest()[:16] + ".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("Inference lock must be a regular file")
    with os.fdopen(fd, "r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (directory / ("ollama-" + hashlib.sha256(key.encode()).hexdigest()[:16] + ".uncertain.json")).exists():
            raise RuntimeError("Reconcile the earlier inference before using this endpoint")
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["ollama", "claude"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--url")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    state = ROOT / ".state"
    directory = state / "benchmarks"
    store = Store(state / "state.sqlite3")
    engine = (OllamaClient(args.url, args.timeout, num_predict=2048, think=False)
              if args.provider == "ollama" else CLIProvider("claude", args.model, args.timeout, tools=False))
    key = engine.url if args.provider == "ollama" else "claude-readiness"
    result = {"protocol": "skill-grounded-v1", "provider": args.provider,
              "model": args.model, "cases": [], "is_opus_validation": False}
    with inference_lock(directory, key):
        if args.provider == "ollama":
            available = engine.inventory()
            if args.model not in {x["name"] for x in available["models"]}:
                raise ValueError("Requested model is not installed")
            result["inventory"] = available
        run, token = open_run(store, "Skill-grounded readiness evaluation")
        result["run"] = run
        output = directory / ("skill-readiness-" + run + ".json")
        for case in CASES:
            text, digests = prompt(case)
            row = {"case": case["id"], "references": digests,
                   "prompt_sha256": hashlib.sha256(text.encode()).hexdigest()}
            (directory / ("skill-readiness-" + run + "-" + case["id"] + ".prompt.txt")).write_text(text)
            started = time.monotonic()
            try:
                response = (engine.call(args.model, text, store, run, case["id"])
                            if args.provider == "ollama" else engine.call(text, store, run, case["id"]))
                reported = response.get("metrics", {}).get("model") if args.provider == "ollama" else response.get("model")
                row["reported_model"] = reported or "unknown"
                row["model_identity_verified"] = (reported == args.model or
                    (args.provider == "claude" and isinstance(reported, str) and reported.startswith(args.model + "-")))
                answer = parse_json(response["text"])
                row.update(status="measured", **score(case, answer))
            except Exception:
                # Do not relay raw provider errors into reusable reports.
                row.update(status="unavailable", reason="provider-or-response-failure")
            row["seconds"] = round(time.monotonic() - started, 3)
            result["cases"].append(row)
            output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            print(json.dumps(row), flush=True)
            if row["status"] != "measured":
                break
        complete = len(result["cases"]) == len(CASES) and all(r["status"] == "measured" for r in result["cases"])
        result["is_opus_validation"] = bool(complete and args.provider == "claude" and
            args.model.startswith("claude-opus-") and all(r.get("model_identity_verified") for r in result["cases"]))
        store.status(run, token, "completed" if complete else "needs-attention")
        result["report"] = reports(store, run)
        result["usage"] = store.report(run)["totals"]
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({"output": str(output), "usage": result["usage"]}), flush=True)
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
