"""Evidence-oriented specialist checklists for the current Codex agent."""
from __future__ import annotations

import re

from metis.core.contracts import ChallengeManifest

PLAYBOOKS = {
    "crypto": {"tools": ["frequency", "xor_single", "xor", "gcd", "mod_inverse", "crt", "integer_root", "rsa_decrypt",
                          "x509", "tls_certificates", "tls_decrypt", "tls_http_body", "zipcrypto_info",
                          "infozip_seed", "zipcrypto_attack", "zipcrypto_stay_scan",
                          "zipcrypto_stay_stage2", "zipcrypto_decrypt"],
               "steps": ["Identify encoding, cipher and supplied parameters before choosing a method.",
                         "Test one hypothesis and inspect actual decoded bytes.",
                         "Check mathematical assumptions; submit only an independently verified candidate."],
               "limit": "No unrestricted factorization, password cracking or model API is started."},
    "web": {"tools": ["text", "http_parse", "url_decode", "html_decode", "jwt_decode"],
            "steps": ["Read supplied source, HTTP messages and session/token format.",
                      "JWT decoding is not signature verification; inspect authorization logic separately.",
                      "Use only explicitly authorized targets for live requests; native tools remain offline.",
                      "JavaScript-built problem pages: reopen with `metis web open --render` (scoped Chromium)."],
            "limit": "Live requests only to granted origins; raw TCP services via `metis remote` grants."},
    "forensics": {"tools": ["overview", "strings", "hex", "zip_list", "zip_read", "gzip", "image", "image_lsb", "pcap",
                            "tls_certificates", "x509"],
                  "steps": ["Identify real magic and size; do not trust the extension.",
                            "Inspect metadata and structure before trying extraction or bit planes.",
                            "Preserve original bytes and digest; derive bounded artifacts without executing them."],
                  "limit": "Eight MiB per source; bounded images and archive members; no arbitrary extraction."},
    "rev": {"tools": ["overview", "strings", "elf", "disassemble", "xor", "rot13"],
            "steps": ["Identify architecture and file format.",
                      "Inspect strings, symbols and section offsets; map virtual addresses correctly.",
                      "Decode relevant data and reconstruct the check; never execute the challenge on the host.",
                      "Confirm behavior dynamically with `metis sandbox run --mode run|strace|ltrace|gdb`."],
            "limit": "Static tools plus isolated container execution; not a general decompiler."},
    "pwn": {"tools": ["elf", "disassemble", "cyclic", "cyclic_find", "pack", "unpack"],
            "steps": ["Identify architecture, imports and mitigation indicators.",
                      "Inspect the vulnerable source/frame and distinguish known offsets from guesses.",
                      "Develop the exploit locally with `metis sandbox run --mode gdb|script` (pwntools inside).",
                      "Send the final payload only to a granted service via `metis remote exchange|pipe`."],
            "limit": "Challenge binaries run only in the no-network sandbox; never on the host."},
    "misc": {"tools": ["overview", "strings", "base64_decode", "base32_decode", "hex_decode", "rot13", "reverse", "flag_candidates"],
             "steps": ["Classify the data and preserve the original.",
                       "Try justified bounded transforms, reconsider failures and avoid blind repetition.",
                       "Flag-shaped output is a candidate until independently accepted."],
             "limit": "No uploaded code execution or automatic external tool installation."},
}


def triage(manifest: ChallengeManifest) -> dict:
    categories = [category.value for category in manifest.categories]
    text = (manifest.title + " " + manifest.description + " " + " ".join(manifest.artifacts)).lower()
    hints = {
        "crypto": ("rsa", "cipher", "xor", "encrypt", "暗号"),
        "web": ("http", "jwt", ".html", ".js", ".php", "cookie", "web"),
        "forensics": (".png", ".jpg", ".pcap", ".zip", ".gz", "forensic", "steg"),
        "rev": ("reverse", "crackme", "elf", ".exe", ".wasm"),
        "pwn": ("pwn", "stack", "heap", "overflow", "canary"),
    }
    if not categories:
        categories = [category for category, keywords in hints.items() if any(word in text for word in keywords)]
    categories = categories or ["misc"]
    remote = bool(re.search(r"\b(?:nc|ncat|netcat)\s+\S+\s+[0-9]{1,5}\b", manifest.description))
    return {"suggested_categories": categories,
            "remote_service_hint": ("statement mentions a TCP service; run `metis remote suggest RUN_ID`, "
                                    "then grant only the user-authorized endpoint") if remote else None,
            "basis": "declared" if manifest.categories else "keyword hints; verify from evidence",
            "playbooks": {category: PLAYBOOKS[category] for category in categories},
            "artifact_first_step": "overview" if manifest.artifacts else None}
