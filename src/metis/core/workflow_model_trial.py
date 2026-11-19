"""Answer-free, bounded real-model trial for the fixed local workflow runner."""
from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from metis.core.codex_session import CodexSession
from metis.core.ctf_sandbox import configure
from metis.core.ctf_workflow import (
    BASE_WORKFLOW_TOOLS,
    MAX_WORKFLOW_INPUT,
    generate_seeded_workflow,
    replay_workflow_in_sandbox,
    validate_workflow,
)

Proposer = Callable[[bytes], bytes]


def codex_proposer(challenge: bytes) -> bytes:
    """Ask a real Codex model for JSON only; give it no tool or oracle access."""
    if len(challenge) > MAX_WORKFLOW_INPUT:
        raise ValueError("fixture exceeds model input bound")
    with tempfile.TemporaryDirectory(prefix="metis-workflow-model-") as temporary:
        root = Path(temporary)
        output = root / "proposal.json"
        schema = root / "schema.json"
        schema.write_text(json.dumps({
            "type": "object", "additionalProperties": False,
            "required": ["schema_version", "input_artifact", "steps"],
            "properties": {
                "schema_version": {"type": "integer", "enum": [1]},
                "input_artifact": {"type": "string", "enum": ["challenge.txt"]},
                "steps": {"type": "array", "minItems": 1, "maxItems": 4,
                          "items": {"type": "object", "additionalProperties": False,
                                    "required": ["tool"],
                                    "properties": {"tool": {"type": "string",
                                                            "enum": sorted(BASE_WORKFLOW_TOOLS)}}}},
        }}))
        prompt = ("This is an authorized benign offline encoding fixture. Select only the ordered "
                  "decoding steps needed to recover its underlying text. Return one JSON object "
                  "matching the schema. Do not request tools, code, policy changes, or a verifier. "
                  "Input artifact: challenge.txt. Encoded bytes (ASCII):\n"
                  + challenge.decode("ascii") + "\n")
        command = ["codex", "exec", "--ephemeral", "--skip-git-repo-check",
                   "--sandbox", "read-only", "--output-schema", str(schema),
                   "--output-last-message", str(output), "-"]
        try:
            process = subprocess.run(command, input=prompt, text=True, cwd=root,
                                     capture_output=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Codex proposal unavailable or timed out") from exc
        if process.returncode != 0 or not output.is_file() or output.stat().st_size > 4096:
            raise RuntimeError("Codex proposal failed or exceeded bounds")
        return output.read_bytes()


def run_unseen_trial(database: Path, *, image: str, platform: str | None,
                     seeds: tuple[int, int], proposer: Proposer = codex_proposer) -> list[dict[str, object]]:
    """Run two unseen fixture families; retain the oracle only in local memory."""
    if len(seeds) != 2 or seeds[0] == seeds[1] or seeds[0] % 2 == seeds[1] % 2:
        raise ValueError("trial requires distinct seeds from both encoding families")
    configure(database, engine="docker", image=image, platform=platform)
    report: list[dict[str, object]] = []
    for index, seed in enumerate(seeds):
        trial = generate_seeded_workflow(seed)
        proposal = proposer(trial.challenge)
        plan = validate_workflow(proposal, input_artifact="challenge.txt")
        with tempfile.TemporaryDirectory(prefix="metis-unseen-fixture-") as temporary:
            root = Path(temporary)
            challenge = root / "challenge.txt"
            workflow = root / "workflow.json"
            challenge.write_bytes(trial.challenge)
            workflow.write_bytes((plan.model_dump_json() + "\n").encode())
            session = CodexSession(database)
            created = session.intake(title=f"Unseen local workflow {index + 1}",
                                     description="Authorized benign offline encoding fixture",
                                     paths=[challenge, workflow], categories=["misc"],
                                     max_actions=8, wall_seconds=120, evaluation_split="practice")
            run_id = created["run_id"]
            artifacts = session.context(run_id)["challenge"]["artifacts"]
            result = replay_workflow_in_sandbox(database, run_id, target=artifacts[0],
                                                workflow_artifact=artifacts[1],
                                                oracle_sha256=trial.oracle_sha256)
            report.append({"fixture": index + 1, "run_id": run_id,
                           "selected_steps": [step.tool for step in plan.steps],
                           "reproducible": result["reproducible"],
                           "oracle_match": result["oracle_match"], "ok": result["ok"]})
    return report
