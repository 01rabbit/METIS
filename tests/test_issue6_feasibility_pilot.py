"""Validate the six-cluster pilot against its frozen design without model calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis.evaluation.issue6_handoff_diagnostic import PILOT_SHAPE, analyze

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_pilot_ids_are_unused_and_output_is_new() -> None:
    ids = {f"pilot6-{index:02d}" for index in range(6)}
    for name in ("issue6-symmetric-replication-2026-11-18.json",
                 "issue6-handoff-diagnostic-2026-11-18.json"):
        data = json.loads((ROOT / "docs/reports/data" / name).read_text(encoding="utf-8"))
        assert ids.isdisjoint(data["encoding_pairs"])


def test_pilot_analysis_rejects_prior_study_shape() -> None:
    data = json.loads((ROOT / "docs/reports/data/issue6-handoff-diagnostic-2026-11-18.json")
                      .read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="preregistration"):
        analyze(data, expected_clusters=6, study_shape=PILOT_SHAPE)


def test_pilot_result_matches_frozen_identity_and_negative_outcome() -> None:
    path = ROOT / "docs/reports/data/issue6-feasibility-pilot-2026-11-18.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    result = analyze(data, expected_clusters=6, study_shape=PILOT_SHAPE)
    assert len(data["records"]) == 18
    assert result["primary_contrast_multi_combined_minus_single"] == -0.3333
    assert result["primary_gain_gate_met"] is False
    data["seed"] += 1
    with pytest.raises(ValueError, match="preregistration"):
        analyze(data, expected_clusters=6, study_shape=PILOT_SHAPE)


def test_pilot_shape_rejects_changed_task_family() -> None:
    path = ROOT / "docs/reports/data/issue6-feasibility-pilot-2026-11-18.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["encoding_pairs"][PILOT_SHAPE.task_ids[0]] = ["hex", "base85"]
    with pytest.raises(ValueError, match="preregistration"):
        analyze(data, expected_clusters=6, study_shape=PILOT_SHAPE)
