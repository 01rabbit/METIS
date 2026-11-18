"""Host execution adapters for specialist assignments (Issue #11, P2).

METIS cannot call the inference host's own subagent API (Codex/Claude subagents are
tools of the calling session). Adapters therefore isolate what the host can do:

* ``BridgeHost``     - the default. ``spawn`` hands the brief back to Daybreak, which runs
                       it with its own host tools and reports through `metis agent ...`.
* ``SequentialHost`` - for hosts without subagents: one assignment at a time, Daybreak
                       plays the role itself.
* ``FakeHost``       - deterministic executor for tests (scripted outputs, hangs, failures).

Every call is bounded; unsupported capabilities are reported, never assumed.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol
from uuid import uuid4

from pydantic import Field

from metis.core.agent_contracts import Contract, ModelSelection


class HostCapabilities(Contract):
    name: str
    can_spawn: bool
    max_parallel: int = Field(ge=1, le=16)
    can_send: bool
    cancel_confirmed: bool
    reports_models: bool
    reports_usage: bool
    note: str = ""


class AgentHost(Protocol):
    name: str

    def capabilities(self) -> HostCapabilities: ...
    def spawn(self, assignment: dict[str, Any], brief: dict[str, Any], model: ModelSelection,
              *, timeout: float = 30.0) -> str: ...
    def poll(self, job_id: str, *, timeout: float = 5.0) -> dict[str, Any]: ...
    def send(self, job_id: str, delta: dict[str, Any], *, timeout: float = 5.0) -> bool: ...
    def cancel(self, job_id: str, *, timeout: float = 10.0) -> bool: ...
    def collect(self, job_id: str, *, timeout: float = 5.0) -> dict[str, Any] | None: ...


class BridgeHost:
    """Daybreak is the host: spawned jobs are briefs it must run with its own tools."""

    name = "bridge"

    def __init__(self, max_parallel: int = 4):
        self.max_parallel = max(1, min(8, max_parallel))

    def capabilities(self) -> HostCapabilities:
        return HostCapabilities(name=self.name, can_spawn=True, max_parallel=self.max_parallel, can_send=False,
                                cancel_confirmed=True, reports_models=False, reports_usage=False,
                                note="Daybreak runs each brief with its host's subagent tool and reports via "
                                     "`metis agent complete|fail`. Cancel = Daybreak stops that subagent.")

    def spawn(self, assignment: dict[str, Any], brief: dict[str, Any], model: ModelSelection,
              *, timeout: float = 30.0) -> str:
        return "bridge-" + uuid4().hex[:12]

    def poll(self, job_id: str, *, timeout: float = 5.0) -> dict[str, Any]:
        return {"state": "running"}  # Completion arrives through `metis agent complete`.

    def send(self, job_id: str, delta: dict[str, Any], *, timeout: float = 5.0) -> bool:
        return False

    def cancel(self, job_id: str, *, timeout: float = 10.0) -> bool:
        return True  # The caller is Daybreak itself, which owns the host subagent.

    def collect(self, job_id: str, *, timeout: float = 5.0) -> dict[str, Any] | None:
        return None


class SequentialHost(BridgeHost):
    name = "sequential"

    def __init__(self) -> None:
        super().__init__(max_parallel=1)

    def capabilities(self) -> HostCapabilities:
        return HostCapabilities(name=self.name, can_spawn=False, max_parallel=1, can_send=False,
                                cancel_confirmed=True, reports_models=False, reports_usage=False,
                                note="No subagents: Daybreak takes the assignments one at a time itself.")


Behaviour = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


class FakeHost:
    """Test executor. ``script[role]`` returns {"after": polls, "state": ..., "output": ...}."""

    name = "fake"

    def __init__(self, script: dict[str, Behaviour] | None = None, *, max_parallel: int = 4,
                 cancel_confirmed: bool = True, spawn_error: set[str] | None = None):
        self.script = script or {}
        self.max_parallel = max_parallel
        self.cancel_confirmed = cancel_confirmed
        self.spawn_error = spawn_error or set()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.spawned: list[str] = []
        self.cancelled: list[str] = []

    def capabilities(self) -> HostCapabilities:
        return HostCapabilities(name=self.name, can_spawn=True, max_parallel=self.max_parallel, can_send=True,
                                cancel_confirmed=self.cancel_confirmed, reports_models=True, reports_usage=True)

    def spawn(self, assignment: dict[str, Any], brief: dict[str, Any], model: ModelSelection,
              *, timeout: float = 30.0) -> str:
        if assignment["role"] in self.spawn_error:
            raise RuntimeError("fake spawn failure")
        job_id = "fake-" + uuid4().hex[:8]
        behaviour = self.script.get(assignment["role"], lambda a, b: {"after": 1, "state": "finished",
                                                                       "output": None})
        self.jobs[job_id] = {"plan": behaviour(assignment, brief), "polls": 0, "assignment": assignment,
                             "brief": brief, "model": model, "started": time.time()}
        self.spawned.append(assignment["assignment_id"])
        return job_id

    def poll(self, job_id: str, *, timeout: float = 5.0) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            return {"state": "unknown"}
        job["polls"] += 1
        plan = job["plan"]
        if plan.get("state") == "hang" or job["polls"] < plan.get("after", 1):
            return {"state": "running"}
        return {"state": plan.get("state", "finished"), "usage": plan.get("usage")}

    def send(self, job_id: str, delta: dict[str, Any], *, timeout: float = 5.0) -> bool:
        return job_id in self.jobs

    def cancel(self, job_id: str, *, timeout: float = 10.0) -> bool:
        self.cancelled.append(job_id)
        return self.cancel_confirmed

    def collect(self, job_id: str, *, timeout: float = 5.0) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        return None if job is None else job["plan"].get("output")


HOSTS: dict[str, Callable[[], AgentHost]] = {"bridge": BridgeHost, "sequential": SequentialHost}


def host_by_name(name: str) -> AgentHost:
    if name not in HOSTS:
        raise ValueError("host must be bridge or sequential")
    return HOSTS[name]()
