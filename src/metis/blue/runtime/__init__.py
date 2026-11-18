"""METIS Blue investigation runtime (owner + bounded worker pool) ``metis/``.

``BLUE_ROOT`` is the knowledge root (``blue/`` in the METIS checkout: skills, detections,
playbooks, docs, examples). Private runtime state lives under ``BLUE_ROOT/.state`` (ignored by Git).
Run it as ``metis blue ...``.
"""
from __future__ import annotations

import os
from pathlib import Path

BLUE_ROOT = Path(os.environ.get("METIS_BLUE_ROOT") or Path(__file__).resolve().parents[4] / "blue")
