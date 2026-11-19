"""Independent integer-tick verifier for finite synthetic build fixtures."""

from dataclasses import dataclass

_HORIZON = 512
POOLS = ("build", "test")
NORMAL_WORKERS = 2


@dataclass(frozen=True)
class Job:
    name: str
    pool: str
    duration: int
    deps: tuple[str, ...] = ()


@dataclass(frozen=True)
class Cause:
    kind: str
    target: str
    amount: int
    start: int = 0


@dataclass(frozen=True)
class Observation:
    job: str
    event: str
    tick: int


@dataclass(frozen=True)
class BuildFixture:
    jobs: tuple[Job, ...]
    options: tuple[Cause, ...]
    observations: tuple[Observation, ...]


def _validate(fixture: BuildFixture) -> None:
    names = {job.name for job in fixture.jobs}
    if not names or len(names) != len(fixture.jobs) or len(names) > 24:
        raise ValueError("fixture requires 1 to 24 distinct jobs")
    for job in fixture.jobs:
        if job.pool not in POOLS or not 1 <= job.duration <= 8:
            raise ValueError("invalid job pool or duration")
        if not set(job.deps) <= names or job.name in job.deps:
            raise ValueError("invalid job dependencies")
    remaining = {job.name: set(job.deps) for job in fixture.jobs}
    visited: set[str] = set()
    while remaining:
        ready = {name for name, deps in remaining.items() if deps <= visited}
        if not ready:
            raise ValueError("dependency cycle")
        visited.update(ready)
        for name in ready:
            del remaining[name]
    if not fixture.options or len(fixture.options) > 128 or len(set(fixture.options)) != len(fixture.options):
        raise ValueError("fixture requires 1 to 128 distinct causes")
    for cause in fixture.options:
        if cause.kind in {"slow_job", "late_artifact"}:
            if cause.target not in names or not 1 <= cause.amount <= 8 or cause.start != 0:
                raise ValueError("invalid job cause")
        elif cause.kind == "worker_loss":
            if cause.target not in POOLS or not 0 <= cause.start <= 32 or not 1 <= cause.amount <= 16:
                raise ValueError("invalid worker loss")
        else:
            raise ValueError("unknown cause kind")
    observed_keys = {(row.job, row.event) for row in fixture.observations}
    if not observed_keys or len(observed_keys) != len(fixture.observations):
        raise ValueError("observations require distinct event keys")
    for row in fixture.observations:
        if row.job not in names or row.event not in {"start", "finish"} or not 0 <= row.tick <= _HORIZON:
            raise ValueError("invalid observation")


def _matches(fixture: BuildFixture, cause: Cause) -> bool:
    expected = {(row.job, row.event): row.tick for row in fixture.observations}
    pending = {job.name: job for job in fixture.jobs}
    running: dict[str, tuple[Job, int]] = {}
    available: dict[str, int] = {}
    left = len(expected)
    for tick in range(_HORIZON + 1):
        for name, (job, finish) in tuple(running.items()):
            if finish != tick:
                continue
            finish_key = (name, "finish")
            if finish_key in expected:
                if expected[finish_key] != tick:
                    return False
                left -= 1
            delay = cause.amount if cause.kind == "late_artifact" and cause.target == name else 0
            available[name] = tick + delay
            del running[name]

        for pool in POOLS:
            occupied = sum(job.pool == pool for job, _ in running.values())
            loss = (
                cause.kind == "worker_loss" and pool == cause.target
                and cause.start <= tick < cause.start + cause.amount
            )
            free = max(0, NORMAL_WORKERS - int(loss) - occupied)
            eligible = [
                name for name, job in pending.items()
                if job.pool == pool and all(available.get(dep, _HORIZON + 1) <= tick for dep in job.deps)
            ]
            for name in sorted(eligible)[:free]:
                job = pending.pop(name)
                start_key = (name, "start")
                if start_key in expected:
                    if expected[start_key] != tick:
                        return False
                    left -= 1
                extra = cause.amount if cause.kind == "slow_job" and cause.target == name else 0
                running[name] = (job, tick + job.duration + extra)
        if not pending and not running:
            return left == 0
    raise ValueError("fixture exceeded the oracle horizon")


def matching_causes(fixture: BuildFixture) -> tuple[Cause, ...]:
    """Enumerate matching causes using only the public fixture."""
    _validate(fixture)
    return tuple(cause for cause in fixture.options if _matches(fixture, cause))


def verify_proposal(fixture: BuildFixture, proposed: Cause) -> bool:
    return matching_causes(fixture) == (proposed,)
