"""Run ZipCrypto known-plaintext recovery inside the bounded sandbox."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from metis.core.ctf_sandbox import Sandbox, SandboxRequest

MEMORY_LIMIT = 512 * 1024 * 1024

_WORKER = r'''
if __name__ == "__main__":
    import json, os, sys
    from pathlib import Path
    allowed_phases = {"worker-imports", "worker-startup", "archive-parsing",
                      "candidate-reduction", "candidate-key-search"}
    def mark_phase(name):
        if name in allowed_phases:
            print("METIS_PHASE:" + name, flush=True)
    mark_phase("worker-startup")
    request = json.loads(Path(os.environ["METIS_STDIN"]).read_text())
    if (not isinstance(request, dict) or not isinstance(request.get("member"), str)
            or not 1 <= len(request["member"]) <= 256
            or not isinstance(request.get("plaintext_hex"), str)
            or len(request["plaintext_hex"]) > 4096
            or type(request.get("offset")) is not int or not 0 <= request["offset"] <= 268435456
            or type(request.get("seconds")) is not int or not 1 <= request["seconds"] <= 300):
        print(json.dumps({"reason": "invalid_input"}))
        raise SystemExit(0)
    try:
        memory_max = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        swap_max = Path("/sys/fs/cgroup/memory.swap.max").read_text().strip()
        cpu_max = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        pids_max = Path("/sys/fs/cgroup/pids.max").read_text().strip()
        memory_events = dict(line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines())
        limits_ok = (memory_max.isdigit() and int(memory_max) <= 2147483648
                     and swap_max.isdigit() and int(swap_max) <= 2147483648
                     and len(cpu_max) == 2 and all(value.isdigit() for value in cpu_max)
                     and int(cpu_max[0]) > 0 and int(cpu_max[1]) > 0
                     and int(cpu_max[0]) <= 4 * int(cpu_max[1])
                     and pids_max.isdigit() and int(pids_max) <= 128
                     and "oom_kill" in memory_events)
    except (OSError, ValueError):
        limits_ok = False
    if not limits_ok:
        print(json.dumps({"reason": "isolation_unavailable"}))
        raise SystemExit(0)
    mark_phase("archive-parsing")
    archive = Path(os.environ["METIS_TARGET"]).read_bytes()
    entries = {entry["name"]: entry for entry in members(archive)
               if entry["encrypted"]}
    name = request["member"]
    if name not in entries:
        print(json.dumps({"reason": "invalid_member"}))
        raise SystemExit(0)
    entry = entries[name]
    try:
        plaintext = bytes.fromhex(request["plaintext_hex"])
    except ValueError:
        print(json.dumps({"reason": "invalid_input"}))
        raise SystemExit(0)
    offset = request["offset"]
    if len(plaintext) > 2048 or offset < 0 or offset + len(plaintext) > entry["compressed_size"]:
        print(json.dumps({"reason": "invalid_input"}))
        raise SystemExit(0)
    result = known_plaintext_attack(
        member_bytes(archive, entry), plaintext, 12 + offset,
        extra={11: check_bytes(entry)[11]}, seconds=request["seconds"], workers=8,
        phase_callback=mark_phase)
    print(json.dumps({"result": result}, separators=(",", ":")))
'''


def run_zipcrypto_attack(database: Path, run_id: str, artifact: str, options: dict[str, Any],
                         *, _profile: str = "zipcrypto") -> dict[str, Any]:
    """Fixed-purpose route: no caller-controlled script, image, or resource settings."""
    if _profile not in {"zipcrypto", "zipcrypto_test_lowmem"}:
        return {"found": False, "reason": "isolation_unavailable", "stage": "sandbox-profile"}
    source = Path(__file__).with_name("ctf_zipcrypto.py").read_text(encoding="utf-8")
    bootstrap = ("import sys\n"
                 "print('METIS_PHASE:worker-imports', flush=True)\n"
                 f"exec(compile({source!r}, '<metis-zipcrypto>', 'exec'), globals())\n")
    script = bootstrap + _WORKER
    if len(script.encode()) > 262_144:
        return {"found": False, "reason": "isolation_unavailable", "stage": "worker-package"}
    seconds = options["seconds"]
    request_data = {
        "member": options.get("member"),
        "plaintext_hex": options.get("plaintext_hex", ""),
        "offset": options.get("offset", 0),
        "seconds": seconds,
    }
    try:
        result = Sandbox(database).execute(run_id, SandboxRequest(
            target=artifact, mode="script", script=script, stdin=json.dumps(request_data).encode(),
            timeout=seconds), _reserved=True, _profile=_profile)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"found": False, "reason": "isolation_unavailable", "stage": "sandbox",
                "detail": f"{type(exc).__name__}: {str(exc)[:160]}"}
    failure = _sandbox_failure(result)
    if failure is not None:
        return failure
    try:
        worker_lines = result["stdout"]["text"].splitlines()
        payload_line = next(line for line in reversed(worker_lines)
                            if line and not line.startswith("METIS_PHASE:"))
        payload = json.loads(payload_line)
    except (KeyError, TypeError, ValueError):
        return {"found": False, "reason": "worker_failed", "stage": "worker-output"}
    if payload.get("reason") == "isolation_unavailable":
        return {"found": False, "reason": "isolation_unavailable", "stage": "cgroup-check"}
    if payload.get("reason"):
        raise ValueError(payload["reason"])
    attack = payload.get("result")
    if not isinstance(attack, dict):
        return {"found": False, "reason": "worker_failed", "stage": "worker-output"}
    return attack


def _sandbox_failure(result: dict[str, Any]) -> dict[str, Any] | None:
    """Map isolated execution failures to stable ZipCrypto reason codes."""
    stdout = result.get("stdout")
    text = stdout.get("text", "") if isinstance(stdout, dict) else ""
    # Spawned multiprocessing workers re-import the bootstrap and can print an
    # older phase after the parent has reached candidate search. Preserve the
    # furthest phase observed instead of letting a child import downgrade it.
    phase_order = ("worker-imports", "worker-startup", "archive-parsing",
                   "candidate-reduction", "candidate-key-search")
    phase_rank = {phase: rank for rank, phase in enumerate(phase_order)}
    observed_phases = (line.removeprefix("METIS_PHASE:") for line in text.splitlines()
                       if line.startswith("METIS_PHASE:")
                       and line.removeprefix("METIS_PHASE:") in phase_rank)
    worker_phase = max(observed_phases, key=phase_rank.__getitem__, default=None)
    if result.get("memory_limit_exceeded"):
        failure = {"found": False, "reason": "memory_limit_exceeded", "stage": "sandbox-oom",
                   "seconds": result.get("elapsed")}
        if worker_phase is not None:
            failure["phase"] = worker_phase
        return failure
    if result.get("timed_out"):
        failure = {"found": False, "reason": "work_exceeds_budget", "stage": "sandbox-timeout",
                   "seconds": result.get("elapsed")}
        if worker_phase is not None:
            failure["phase"] = worker_phase
        return failure
    if result.get("engine_timed_out"):
        return {"found": False, "reason": "worker_failed", "stage": result.get("failure_stage", "sandbox-engine"),
                "detail": "container engine operation exceeded its timeout"}
    if not result.get("ok"):
        return {"found": False, "reason": "worker_failed", "stage": "sandbox",
                "exit_code": result.get("exit_code")}
    return None
