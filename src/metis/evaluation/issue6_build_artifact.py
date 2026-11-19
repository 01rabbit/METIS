"""Canonical build fixture identity and opaque structured proposal handling."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from .issue6_build_generator import PUBLIC_RULES
from .issue6_build_oracle import BuildFixture, Cause


def _options(fixture: BuildFixture) -> dict[str, Cause]:
    ordered = sorted(fixture.options, key=lambda cause: (cause.kind, cause.target, cause.amount, cause.start))
    return {f"option-{index:03}": cause for index, cause in enumerate(ordered, 1)}


def canonical_artifact(fixture: BuildFixture, *, include_submission_rule: bool = True) -> bytes:
    options = [{"id": label, **asdict(cause)} for label, cause in _options(fixture).items()]
    jobs = [
        {**asdict(job), "deps": sorted(job.deps)}
        for job in sorted(fixture.jobs, key=lambda job: job.name)
    ]
    observations = [
        asdict(row) for row in sorted(fixture.observations, key=lambda row: (row.job, row.event))
    ]
    rules = PUBLIC_RULES
    if include_submission_rule:
        rules += " Return one JSON object containing only the matching option_id."
    payload = {
        "version": 1,
        "rules": rules,
        "jobs": jobs,
        "options": options,
        "observations": observations,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def fixture_digest(fixture: BuildFixture) -> str:
    return hashlib.sha256(canonical_artifact(fixture)).hexdigest()


def fixture_labels(fixtures: Iterable[BuildFixture]) -> tuple[str, ...]:
    """Return input-order labels, rejecting duplicates across all supplied cohorts."""
    labels = []
    seen: set[str] = set()
    for fixture in fixtures:
        digest = fixture_digest(fixture)
        if digest in seen:
            raise ValueError("duplicate canonical build fixture")
        seen.add(digest)
        labels.append(f"build-{digest}")
    return tuple(labels)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate proposal key")
        result[key] = value
    return result


def parse_proposal(raw: str, fixture: BuildFixture) -> Cause | None:
    if len(raw) > 128:
        return None
    try:
        proposal = json.loads(raw, object_pairs_hook=_strict_object)
    except (ValueError, RecursionError):
        return None
    if not isinstance(proposal, dict) or set(proposal) != {"option_id"}:
        return None
    label = proposal["option_id"]
    if not isinstance(label, str):
        return None
    return _options(fixture).get(label)
