"""Run ZipCrypto known-plaintext recovery inside the bounded sandbox."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from metis.core.ctf_sandbox import Sandbox, SandboxRequest

MEMORY_LIMIT = 512 * 1024 * 1024

_CGROUP_GUARD = r'''
def cgroup_limits_ok():
    from pathlib import Path
    try:
        memory_max = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        swap_max = Path("/sys/fs/cgroup/memory.swap.max").read_text().strip()
        cpu_max = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        pids_max = Path("/sys/fs/cgroup/pids.max").read_text().strip()
        memory_events = dict(line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines())
        return (memory_max.isdigit() and int(memory_max) <= 2147483648
                and swap_max.isdigit() and int(swap_max) <= 2147483648
                and len(cpu_max) == 2 and all(value.isdigit() for value in cpu_max)
                and int(cpu_max[0]) > 0 and int(cpu_max[1]) > 0
                and int(cpu_max[0]) <= 4 * int(cpu_max[1])
                and pids_max.isdigit() and int(pids_max) <= 128
                and "oom_kill" in memory_events)
    except (OSError, ValueError):
        return False
'''

_WORKER = _CGROUP_GUARD + r'''
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
    if not cgroup_limits_ok():
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


_STAY_C_SOURCE = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MULT 0x08088405u
static uint32_t crc_table[256];

static int from_hex(const char *s, uint8_t *out, size_t cap) {
    size_t n = strlen(s);
    if ((n & 1u) || n / 2 > cap) return -1;
    for (size_t i = 0; i < n / 2; i++) {
        unsigned value;
        if (sscanf(s + 2 * i, "%2x", &value) != 1) return -1;
        out[i] = (uint8_t)value;
    }
    return (int)(n / 2);
}

static uint8_t predict(uint8_t random_first, uint8_t first_stream,
                       uint8_t key0_low, uint8_t product_high,
                       uint16_t key2_bits, unsigned carry1, unsigned carry2) {
    uint8_t low1 = key0_low ^ (uint8_t)crc_table[random_first];
    uint8_t low2 = key0_low ^ (uint8_t)crc_table[random_first ^ first_stream];
    uint64_t add1 = (uint64_t)low1 * MULT + 1;
    uint64_t add2 = (uint64_t)low2 * MULT + 1;
    uint8_t high1 = (uint8_t)(product_high + (add1 >> 24) + carry1);
    uint8_t high2 = (uint8_t)(product_high + (add2 >> 24) + carry2);
    uint32_t key2a = (key2_bits ^ crc_table[high1]) & 0xfffcu;
    uint32_t key2b = (key2_bits ^ crc_table[high2]) & 0xfffcu;
    uint32_t value1 = key2a | 2u, value2 = key2b | 2u;
    uint8_t stream1 = (uint8_t)((value1 * (value1 ^ 1u)) >> 8);
    uint8_t stream2 = (uint8_t)((value2 * (value2 ^ 1u)) >> 8);
    return stream1 ^ stream2;
}

int main(int argc, char **argv) {
    if (argc != 7) return 2;
    uint64_t start = strtoull(argv[1], NULL, 10), stop = strtoull(argv[2], NULL, 10);
    double seconds = strtod(argv[3], NULL);
    unsigned max_hits = (unsigned)strtoul(argv[4], NULL, 10);
    uint8_t random_firsts[64], observed[64];
    int count = from_hex(argv[5], random_firsts, sizeof(random_firsts));
    int obs_count = from_hex(argv[6], observed, sizeof(observed));
    if (count < 5 || count > 64 || obs_count != count || start > stop || stop > (1ULL << 40)
        || seconds <= 0 || max_hits < 1 || max_hits > 4096) return 3;
    for (unsigned i = 0; i < 256; i++) {
        uint32_t c = i;
        for (unsigned j = 0; j < 8; j++) c = (c >> 1) ^ (0xedb88320u & (uint32_t)-(int32_t)(c & 1u));
        crc_table[i] = c;
    }
    struct timespec begin, now;
    clock_gettime(CLOCK_MONOTONIC, &begin);
    uint64_t cursor = start, scanned = 0;
    unsigned hits = 0;
    printf("{\"hits\":[");
    int comma = 0;
    for (uint64_t index = start; index < stop; index++) {
        if ((index & 0xfffffu) == 0) {
            clock_gettime(CLOCK_MONOTONIC, &now);
            double elapsed = (double)(now.tv_sec - begin.tv_sec) + (double)(now.tv_nsec - begin.tv_nsec) / 1e9;
            if (elapsed >= seconds) { cursor = index; break; }
        }
        uint8_t stream = (uint8_t)index;
        uint8_t key0_low = (uint8_t)(index >> 8);
        uint8_t product_high = (uint8_t)(index >> 16);
        unsigned first_carry = (unsigned)(index >> 24) & 1u;
        uint16_t key2_bits = (uint16_t)((((index >> 25) & 0x3fu) << 10)
                                         | (((index >> 31) & 0xffu) << 2));
        unsigned second_carry = (unsigned)(index >> 39) & 1u;
        if (predict(random_firsts[0], stream, key0_low, product_high, key2_bits,
                    first_carry, second_carry) != observed[0]) { scanned++; cursor = index + 1; continue; }
        uint8_t masks[64] = {0};
        masks[0] = (uint8_t)(1u << (first_carry * 2u + second_carry));
        int keep = 1;
        for (int member = 1; member < count && keep; member++) {
            for (unsigned c1 = 0; c1 < 2; c1++) for (unsigned c2 = 0; c2 < 2; c2++) {
                if (predict(random_firsts[member], stream, key0_low, product_high, key2_bits, c1, c2)
                    == observed[member]) masks[member] |= (uint8_t)(1u << (c1 * 2u + c2));
            }
            if (!masks[member]) keep = 0;
        }
        scanned++; cursor = index + 1;
        if (keep) {
            if (comma) putchar(',');
            comma = 1;
            printf("[%llu,[", (unsigned long long)index);
            for (int member = 0; member < count; member++) printf("%s%u", member ? "," : "", masks[member]);
            printf("]]");
            hits++;
            if (hits >= max_hits) break;
        }
    }
    clock_gettime(CLOCK_MONOTONIC, &now);
    double elapsed = (double)(now.tv_sec - begin.tv_sec) + (double)(now.tv_nsec - begin.tv_nsec) / 1e9;
    printf("],\"next_index\":%llu,\"complete\":%s,\"scanned\":%llu,\"seconds\":%.3f}\n",
           (unsigned long long)cursor, cursor >= stop ? "true" : "false",
           (unsigned long long)scanned, elapsed);
    return 0;
}
'''


_STAY_SCAN_WORKER = _CGROUP_GUARD + r'''
if __name__ == "__main__":
    import json, os, subprocess, sys, time
    from pathlib import Path
    allowed_phases = {"worker-startup", "archive-parsing", "stay-first-stage-scan"}
    def mark_phase(name):
        if name in allowed_phases:
            print("METIS_PHASE:" + name, flush=True)
    mark_phase("worker-startup")
    request = json.loads(Path(os.environ["METIS_STDIN"]).read_text())
    if (not isinstance(request, dict)
            or not isinstance(request.get("random_header_bytes_hex"), str)
            or len(request["random_header_bytes_hex"]) > 1280
            or type(request.get("start")) is not int or not 0 <= request["start"] <= 1 << 40
            or type(request.get("stop")) is not int or not request["start"] <= request["stop"] <= 1 << 40
            or type(request.get("max_candidates")) is not int or not 1 <= request["max_candidates"] <= 1 << 40
            or type(request.get("seconds")) is not int or not 10 <= request["seconds"] <= 300
            or type(request.get("max_hits")) is not int or not 1 <= request["max_hits"] <= 4096):
        print(json.dumps({"reason": "invalid_input"}))
        raise SystemExit(0)
    if not cgroup_limits_ok():
        print(json.dumps({"reason": "isolation_unavailable"}))
        raise SystemExit(0)
    mark_phase("archive-parsing")
    archive = Path(os.environ["METIS_TARGET"]).read_bytes()
    encrypted = [entry for entry in members(archive) if entry["encrypted"]]
    try:
        random_headers = bytes.fromhex(request["random_header_bytes_hex"])
    except ValueError:
        print(json.dumps({"reason": "invalid_input"}))
        raise SystemExit(0)
    if (len(encrypted) < 5 or len(encrypted) > 64
            or len(random_headers) != len(encrypted) * 10):
        print(json.dumps({"reason": "observation_count_mismatch"}))
        raise SystemExit(0)
    random_firsts = []
    observed_differences = []
    for index, entry in enumerate(encrypted):
        expected = random_headers[index * 10:index * 10 + 10]
        encrypted_header = member_bytes(archive, entry)[:12]
        if len(encrypted_header) != 12 or encrypted_header[0] != expected[0]:
            print(json.dumps({"reason": "header_observation_mismatch"}))
            raise SystemExit(0)
        random_firsts.append(expected[0])
        observed_differences.append(encrypted_header[1] ^ expected[1])
    mark_phase("stay-first-stage-scan")
    source = Path("/work/stay_scan.c")
    binary = Path("/work/stay_scan")
    source.write_text(STAY_C_SOURCE)
    compiled = subprocess.run(["gcc", "-O3", "-march=native", "-o", str(binary), str(source)],
                              capture_output=True, timeout=max(1, min(30, request["seconds"] - 2)))
    if compiled.returncode:
        print(json.dumps({"reason": "native_worker_build_failed"}))
        raise SystemExit(0)
    random_firsts_hex = bytes(random_firsts).hex()
    observed_hex = bytes(observed_differences).hex()
    safe_max_hits = min(request["max_hits"], max(1, 180000 // (24 + 3 * len(encrypted))))
    bounded_stop = min(request["stop"], request["start"] + request["max_candidates"])
    result = subprocess.run([str(binary), str(request["start"]), str(bounded_stop),
                             str(max(1, request["seconds"] - 5)), str(safe_max_hits),
                             random_firsts_hex, observed_hex],
                            capture_output=True, text=True, timeout=max(1, request["seconds"] - 1))
    if result.returncode:
        print(json.dumps({"reason": "native_worker_failed"}))
        raise SystemExit(0)
    scan = json.loads(result.stdout)
    scan["complete"] = scan["next_index"] >= request["stop"]
    print(json.dumps({"result": scan}, separators=(",", ":")))
'''


_STAY_STAGE2_WORKER = _CGROUP_GUARD + r'''
if __name__ == "__main__":
    import json, os, time
    from pathlib import Path
    print("METIS_PHASE:stay-second-stage-scan", flush=True)
    request = json.loads(Path(os.environ["METIS_STDIN"]).read_text())
    if not cgroup_limits_ok():
        print(json.dumps({"reason": "isolation_unavailable"}))
        raise SystemExit(0)
    archive = Path(os.environ["METIS_TARGET"]).read_bytes()
    entries = [entry for entry in members(archive) if entry["encrypted"]]
    headers = bytes.fromhex(request["random_header_bytes_hex"])
    if len(entries) < 5 or len(entries) > 64 or len(headers) != 10 * len(entries):
        print(json.dumps({"reason": "observation_count_mismatch"}))
        raise SystemExit(0)
    firsts, seconds, third = [], [], []
    for member, entry in enumerate(entries):
        expected = headers[10 * member:10 * member + 10]
        stored = member_bytes(archive, entry)[:12]
        if len(stored) != 12 or stored[0] != expected[0]:
            print(json.dumps({"reason": "header_observation_mismatch"}))
            raise SystemExit(0)
        firsts.append(expected[0])
        seconds.append(expected[1])
        third.append(stored[2] ^ expected[2])
    observed_second = tuple(member_bytes(archive, entry)[1] ^ headers[10 * member + 1]
                            for member, entry in enumerate(entries))
    index = request["candidate_index"]
    masks = _stay_first_stage_candidate(index, tuple(firsts), observed_second)
    if masks is None or list(masks) != request["carry_masks"]:
        print(json.dumps({"reason": "stage1_observation_mismatch"}))
        raise SystemExit(0)
    started = time.monotonic()
    chunk = _stay_stage2_scan_chunk(index, masks, tuple(firsts), tuple(seconds), tuple(third),
                                    start=request["start"], stop=request["stop"],
                                    max_candidates=request["max_candidates"],
                                    max_hits=request["max_hits"], seconds=max(1, request["seconds"] - 2))
    print(json.dumps({"result": {"next_index": chunk.next_index, "reason": chunk.reason,
                                  "scanned": chunk.next_index - request["start"],
                                  "complete": chunk.next_index >= request["stop"],
                                  "seconds": round(time.monotonic() - started, 3),
                                  "hits": chunk.hits}}, separators=(",", ":")))
'''


def run_zipcrypto_attack(database: Path, run_id: str, artifact: str, options: dict[str, Any],
                         *, _profile: str = "zipcrypto", _operation_id: str | None = None) -> dict[str, Any]:
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
            timeout=seconds), _reserved=_operation_id is not None, _profile=_profile,
            _operation_id=_operation_id)
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


def run_zipcrypto_stay_scan(database: Path, run_id: str, artifact: str, options: dict[str, Any],
                            *, _profile: str = "zipcrypto",
                            _operation_id: str | None = None) -> dict[str, Any]:
    """Run one bounded Stay Stage 1 chunk and retain hit IDs in a private shard."""
    if _profile != "zipcrypto":
        return {"reason": "isolation_unavailable", "stage": "sandbox-profile"}
    source = Path(__file__).with_name("ctf_zipcrypto.py").read_text(encoding="utf-8")
    bootstrap = ("import sys\n"
                 "print('METIS_PHASE:worker-imports', flush=True)\n"
                 f"exec(compile({source!r}, '<metis-zipcrypto>', 'exec'), globals())\n")
    script = bootstrap + f"\nSTAY_C_SOURCE={_STAY_C_SOURCE!r}\n" + _STAY_SCAN_WORKER
    if len(script.encode()) > 262_144:
        return {"reason": "isolation_unavailable", "stage": "worker-package"}
    seconds = options["seconds"]
    request_data = {key: options[key] for key in (
        "random_header_bytes_hex", "start", "stop", "max_candidates", "seconds", "max_hits")}
    try:
        result = Sandbox(database).execute(run_id, SandboxRequest(
            target=artifact, mode="script", script=script, stdin=json.dumps(request_data).encode(),
            timeout=seconds), _reserved=_operation_id is not None, _profile=_profile,
            _operation_id=_operation_id)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"reason": "isolation_unavailable", "stage": "sandbox",
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
        return {"reason": "worker_failed", "stage": "worker-output"}
    if payload.get("reason"):
        return {"reason": payload["reason"], "stage": "input-validation"}
    scan = payload.get("result")
    if not isinstance(scan, dict) or not isinstance(scan.get("hits"), (list, tuple)):
        return {"reason": "worker_failed", "stage": "worker-output"}
    hits = scan.pop("hits")
    shard_ref = None
    if hits:
        private_root = database.parent / "private-stay"
        private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        shard_root = private_root / run_id
        shard_root.mkdir(mode=0o700, exist_ok=True)
        if (private_root.is_symlink() or shard_root.is_symlink()
                or private_root.stat().st_mode & 0o077 or shard_root.stat().st_mode & 0o077):
            return {"reason": "private_state_unavailable", "stage": "candidate-shard"}
        shard = shard_root / f"{uuid4().hex}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(shard, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"start": options["start"], "next_index": scan.get("next_index"),
                           "hits": hits}, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            shard.unlink(missing_ok=True)
            raise
        shard_ref = str(shard.relative_to(database.parent))
    return {**scan, "hits_count": len(hits), "candidate_shard": shard_ref}


def run_zipcrypto_stay_stage2(database: Path, run_id: str, artifact: str, options: dict[str, Any],
                              *, _profile: str = "zipcrypto",
                              _operation_id: str | None = None) -> dict[str, Any]:
    """Scan one Stage 1 hit within a bounded isolated Stage 2 chunk."""
    if _profile != "zipcrypto":
        return {"reason": "isolation_unavailable", "stage": "sandbox-profile"}
    shard_ref = options.get("stage1_shard")
    if not isinstance(shard_ref, str) or not re.fullmatch(
            rf"private-stay/{re.escape(run_id)}/[0-9a-f]{{32}}\.json", shard_ref):
        return {"reason": "private_state_unavailable", "stage": "candidate-shard"}
    shard_root = database.parent / "private-stay" / run_id
    shard = database.parent / shard_ref
    if (shard_root.parent.is_symlink() or shard_root.is_symlink()
            or not shard_root.is_dir() or shard_root.stat().st_mode & 0o077
            or shard_root.parent.stat().st_mode & 0o077
            or shard.is_symlink() or not shard.is_file()
            or shard.stat().st_mode & 0o077 or shard.stat().st_size > 262_144):
        return {"reason": "private_state_unavailable", "stage": "candidate-shard"}
    try:
        hits = json.loads(shard.read_text(encoding="utf-8"))["hits"]
        index, masks = hits[options["hit_index"]]
        count = len(bytes.fromhex(options["random_header_bytes_hex"])) // 10
        if (type(index) is not int or not 0 <= index < 1 << 40
                or not isinstance(masks, list) or len(masks) != count
                or any(type(mask) is not int or not 1 <= mask <= 15 for mask in masks)):
            raise ValueError("invalid Stage 1 shard")
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return {"reason": "private_state_unavailable", "stage": "candidate-shard"}
    source = Path(__file__).with_name("ctf_zipcrypto.py").read_text(encoding="utf-8")
    script = ("import sys\nprint('METIS_PHASE:worker-imports', flush=True)\n"
              f"exec(compile({source!r}, '<metis-zipcrypto>', 'exec'), globals())\n"
              + _STAY_STAGE2_WORKER)
    if len(script.encode()) > 262_144:
        return {"reason": "isolation_unavailable", "stage": "worker-package"}
    seconds = options["seconds"]
    request = {key: options[key] for key in (
        "random_header_bytes_hex", "start", "stop", "max_candidates", "seconds", "max_hits")}
    request.update(candidate_index=index, carry_masks=masks)
    try:
        result = Sandbox(database).execute(run_id, SandboxRequest(
            target=artifact, mode="script", script=script, stdin=json.dumps(request).encode(),
            timeout=seconds), _reserved=_operation_id is not None, _profile=_profile,
            _operation_id=_operation_id)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"reason": "isolation_unavailable", "stage": "sandbox",
                "detail": f"{type(exc).__name__}: {str(exc)[:160]}"}
    failure = _sandbox_failure(result)
    if failure is not None:
        return failure
    try:
        lines = result["stdout"]["text"].splitlines()
        payload = json.loads(next(line for line in reversed(lines)
                                  if line and not line.startswith("METIS_PHASE:")))
        if payload.get("reason"):
            return {"reason": payload["reason"], "stage": "input-validation"}
        scan = payload["result"]
        candidate_hits = scan.pop("hits")
        if (not isinstance(candidate_hits, list) or len(candidate_hits) > options["max_hits"]
                or type(scan.get("next_index")) is not int
                or not options["start"] <= scan["next_index"] <= options["stop"]
                or any(not isinstance(hit, list) or len(hit) != 2
                       or type(hit[0]) is not int or not 0 <= hit[0] < 1 << 26
                       or type(hit[1]) is not int or not 0 <= hit[1] <= 0xFFFFFFFF
                       for hit in candidate_hits)):
            raise ValueError("invalid worker output")
    except (KeyError, TypeError, ValueError, StopIteration):
        return {"reason": "worker_failed", "stage": "worker-output"}
    shard_ref = None
    if candidate_hits:
        output = shard_root / f"s2-{uuid4().hex}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(output, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"stage1_shard": options["stage1_shard"], "hit_index": options["hit_index"],
                           "start": options["start"], "next_index": scan["next_index"],
                           "hits": candidate_hits}, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        shard_ref = str(output.relative_to(database.parent))
    return {**scan, "hits_count": len(candidate_hits), "candidate_shard": shard_ref}


def _sandbox_failure(result: dict[str, Any]) -> dict[str, Any] | None:
    """Map isolated execution failures to stable ZipCrypto reason codes."""
    stdout = result.get("stdout")
    text = stdout.get("text", "") if isinstance(stdout, dict) else ""
    # Spawned multiprocessing workers re-import the bootstrap and can print an
    # older phase after the parent has reached candidate search. Preserve the
    # furthest phase observed instead of letting a child import downgrade it.
    phase_order = ("worker-imports", "worker-startup", "archive-parsing",
                   "stay-first-stage-scan", "candidate-reduction", "candidate-key-search")
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
