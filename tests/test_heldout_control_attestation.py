"""Offline attestation verification with synthetic protocol and test-only key material."""

import hashlib
import json
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from metis.evaluation import heldout_control_attestation as review
from metis.evaluation.heldout_protocol import Protocol, digest

_TEST_SIGNER = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


@pytest.fixture
def protocol() -> Protocol:
    budget = {"model_calls": 1, "tokens": 20, "actions": 1, "seconds": 5.0, "cost_usd": 0.0}
    full = {
        "memory_enabled": True,
        "planner_enabled": True,
        "max_specialists": 2,
        "prompt_sha256": "1" * 64,
    }
    tasks = [
        {
            "task_id": f"test-{i}",
            "source_id": f"source-{i}",
            "distribution_sha256": str(i) * 64,
            "split": "held_out",
            "difficulty": "easy",
            "category": "misc",
            "exposure": "unseen" if i == 1 else "unknown",
            "solvability_control_verified": i == 1,
        }
        for i in (1, 2)
    ]
    return Protocol.model_validate(
        {
            "schema_version": 1,
            "study_id": "synthetic",
            "measurement": "synthetic_fixture",
            "model_pin": "synthetic",
            "runtime_pin": "test-runtime",
            "seed": 0,
            "repetitions": 2,
            "arms": ["full", "single_agent"],
            "baseline": "full",
            "budgets": {"full": budget, "single_agent": budget},
            "tasks": tasks,
            "arm_config": {"full": full, "single_agent": dict(full, max_specialists=1)},
        }
    )


@pytest.fixture
def document(protocol):
    return {
        "schema_version": 1,
        "role": "independent_control_reviewer",
        "protocol_sha256": digest(protocol),
        "tasks": [
            {
                "task_id_sha256": hashlib.sha256(task.task_id.encode()).hexdigest(),
                "source_id_sha256": hashlib.sha256(task.source_id.encode()).hexdigest(),
                "distribution_sha256": task.distribution_sha256,
                "evidence_sha256": "b" * 64,
                "control": "verified" if task.solvability_control_verified else "unverified",
                "exposure": task.exposure,
            }
            for task in protocol.tasks
        ],
    }


def _sign(document):
    return _TEST_SIGNER.sign(
        review.signing_bytes(review.ControlAttestation.model_validate(document))
    )


def _verify(protocol, document, signature):
    return review.verify(
        protocol,
        json.dumps(document).encode(),
        signature,
        trusted_reviewer_key=_TEST_SIGNER.public_key(),
    )


def test_signature_binds_canonical_rows_but_ignores_json_format_and_order(protocol, document):
    signature = _sign(document)
    document["tasks"].reverse()
    checked = _verify(protocol, document, signature)
    assert checked.protocol_sha256 == digest(protocol)
    assert len(checked.tasks) == 2


@pytest.mark.parametrize(
    ("field", "new_value"),
    [
        ("task_id_sha256", "a" * 64),
        ("source_id_sha256", "a" * 64),
        ("distribution_sha256", "a" * 64),
        ("exposure", "prior_answer"),
        ("control", "unverified"),
    ],
)
def test_valid_signature_cannot_override_protocol_assertion(protocol, document, field, new_value):
    document["tasks"][0][field] = new_value
    with pytest.raises(ValueError, match="task assertions mismatch"):
        _verify(protocol, document, _sign(document))


def test_unrelated_protocol_and_mutated_evidence_fail(protocol, document):
    signature = _sign(document)
    other = protocol.model_copy(update={"seed": 7})
    with pytest.raises(ValueError, match="protocol mismatch"):
        _verify(other, document, signature)
    document["tasks"][0]["evidence_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="invalid control attestation signature"):
        _verify(protocol, document, signature)


def test_wrong_key_and_signature_domain_fail(protocol, document):
    payload = json.dumps(document).encode()
    other = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32)))).public_key()
    with pytest.raises(ValueError, match="invalid control attestation signature"):
        review.verify(protocol, payload, _sign(document), trusted_reviewer_key=other)
    message = review.signing_bytes(review.ControlAttestation.model_validate(document))
    with pytest.raises(ValueError, match="invalid control attestation signature"):
        _verify(protocol, document, _TEST_SIGNER.sign(b"unrelated-domain\x00" + message))


@pytest.mark.parametrize(
    "mutation", ["role", "schema_bool", "extra", "answer", "short", "duplicate", "artifact_alias"]
)
def test_manifest_is_strict_and_requires_distinct_rows(protocol, document, mutation):
    signature = _sign(document)
    if mutation == "role":
        document["role"] = "scheduler"
    elif mutation == "schema_bool":
        document["schema_version"] = True
    elif mutation == "extra":
        document["note"] = "unexpected"
    elif mutation == "answer":
        document["tasks"][0]["answer"] = "synthetic sentinel"
    elif mutation == "short":
        document["tasks"].pop()
    elif mutation == "duplicate":
        document["tasks"].append(document["tasks"][0])
    else:
        for field in ("source_id_sha256", "distribution_sha256"):
            document["tasks"][1][field] = document["tasks"][0][field]
    with pytest.raises(ValueError):
        _verify(protocol, document, signature)


def test_rejects_duplicate_json_fields_and_input_outside_size_bounds(protocol, document):
    options = {"trusted_reviewer_key": _TEST_SIGNER.public_key()}
    signature = _sign(document)
    duplicate = (
        json.dumps(document)
        .replace('"role":', '"role": "independent_control_reviewer", "role":')
        .encode()
    )
    with pytest.raises(ValueError, match="duplicate JSON field"):
        review.verify(protocol, duplicate, signature, **options)
    with pytest.raises(ValueError, match="input outside bounds"):
        review.verify(protocol, b" " * (review.MAX_ATTESTATION_BYTES + 1), signature, **options)
    with pytest.raises(ValueError, match="input outside bounds"):
        review.verify(protocol, b"{}", b"x" * 63, **options)


def test_api_parse_errors_discard_untrusted_values_and_field_names(protocol, document):
    signature = _sign(document)
    with pytest.raises(ValueError, match="^invalid control attestation document$"):
        _verify(protocol, document | {"synthetic-secret-key": "synthetic-secret-value"}, signature)
    with pytest.raises(ValueError, match="^invalid control attestation document$"):
        review.verify(protocol, b"[" * 10_000, signature, trusted_reviewer_key=_TEST_SIGNER.public_key())


def test_cli_prints_only_review_metadata_and_suppresses_candidate_input(
    tmp_path, monkeypatch, capsys, protocol, document
):
    protocol_path, attestation_path = tmp_path / "protocol", tmp_path / "attestation"
    signature_path, key_path = tmp_path / "signature", tmp_path / "public"
    protocol_path.write_text(protocol.model_dump_json())
    attestation_path.write_text(json.dumps(document))
    signature_path.write_bytes(_sign(document))
    key_path.write_bytes(_TEST_SIGNER.public_key().public_bytes_raw())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "attestation",
            str(protocol_path),
            str(attestation_path),
            str(signature_path),
            "--reviewer-key",
            str(key_path),
        ],
    )
    assert review.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "protocol_sha256": digest(protocol),
        "authenticated_task_rows": 2,
    }
    attestation_path.write_text(json.dumps(document | {"candidate": "synthetic sentinel"}))
    assert review.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "held-out control attestation rejected\n"


def test_symlink_loop_in_protocol_database_path_rejects_without_disclosure(
    tmp_path, monkeypatch, capsys, protocol, document
):
    database = tmp_path.resolve() / "private-path-marker"
    data = protocol.model_dump()
    data["measurement"] = "real_model"
    data["llama_backend"] = {
        "binary_sha256": "c" * 64,
        "model_sha256": "d" * 64,
        "database_path": str(database),
        "budget_key": "synthetic",
        "token_limit": 20,
        "max_output_tokens": 1,
        "context_reservation": True,
    }
    real_protocol = Protocol.model_validate(data)
    document["protocol_sha256"] = digest(real_protocol)
    signature = _sign(document)
    paths = [tmp_path / name for name in ("protocol", "manifest", "signature", "public")]
    paths[0].write_text(real_protocol.model_dump_json())
    paths[1].write_text(json.dumps(document))
    paths[2].write_bytes(signature)
    paths[3].write_bytes(_TEST_SIGNER.public_key().public_bytes_raw())
    database.symlink_to(database.name)

    monkeypatch.setattr(sys, "argv", ["attestation", *map(str, paths[:3]), "--reviewer-key", str(paths[3])])
    assert review.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "held-out control attestation rejected\n"

    with pytest.raises(ValueError, match="^invalid control attestation protocol$"):
        _verify(real_protocol, document, signature)
