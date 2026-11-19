"""Deterministic, answer-free public fixtures for benign build-log triage."""

from dataclasses import dataclass
from random import Random
from typing import Literal

from .issue6_build_oracle import POOLS, BuildFixture, Cause, Job, Observation, matching_causes

Difficulty = Literal["small", "medium", "large"]
Family = Literal["slow_job", "late_artifact", "worker_loss"]
FAMILIES: tuple[Family, ...] = ("slow_job", "late_artifact", "worker_loss")
TIER = {"small": (7, 70), "medium": (11, 52), "large": (16, 38)}
MAX_ATTEMPTS = 256
PUBLIC_RULES = (
    "Each pool starts with two workers and jobs run without preemption. A job is ready when all its "
    "dependencies' artifacts are available. Finish events and due artifacts are processed before "
    "dispatch at the same tick. Each pool fills free slots with ready jobs in ascending job-name "
    "order. A slow_job adds amount to its running time. A late_artifact adds amount to the time "
    "between its finish and artifact availability. A worker_loss reduces capacity by one during "
    "the half-open interval [start, start + amount), without stopping any running job. Exactly one "
    "listed cause occurred. The log contains an unordered subset of start and finish records. Find "
    "the cause consistent with every listed timestamp. Missing records supply no constraints."
)


@dataclass(frozen=True)
class Admission:
    fixture: BuildFixture
    attempts: int
    ambiguous: int
    incompatible: int


def _events(jobs: tuple[Job, ...], cause: Cause) -> dict[tuple[str, str], int]:
    """Generate a log by advancing only to scheduled event boundaries."""
    unstarted = {job.name: job for job in jobs}
    in_progress: dict[str, int] = {}
    pools = {job.name: job.pool for job in jobs}
    artifact_times: dict[str, int] = {}
    log: dict[tuple[str, str], int] = {}
    time = 0
    while unstarted or in_progress:
        for name, finish in list(in_progress.items()):
            if finish == time:
                log[(name, "finish")] = time
                del in_progress[name]
                extra = cause.amount if (cause.kind, cause.target) == ("late_artifact", name) else 0
                artifact_times[name] = time + extra
        for name, job in sorted(unstarted.items()):
            capacity = 2
            if ((cause.kind, cause.target) == ("worker_loss", job.pool)
                    and cause.start <= time < cause.start + cause.amount):
                capacity -= 1
            if sum(pools[active] == job.pool for active in in_progress) >= capacity:
                continue
            if any(dep not in artifact_times or artifact_times[dep] > time for dep in job.deps):
                continue
            log[(name, "start")] = time
            extra = cause.amount if (cause.kind, cause.target) == ("slow_job", name) else 0
            in_progress[name] = time + job.duration + extra
            del unstarted[name]
        if not unstarted and not in_progress:
            break
        future = [*in_progress.values(), *artifact_times.values()]
        if cause.kind == "worker_loss":
            future.extend((cause.start, cause.start + cause.amount))
        upcoming = [event for event in future if event > time]
        if not upcoming:
            raise ValueError("generator could not advance")
        time = min(upcoming)
    return log


def make_fixture(seed: int, difficulty: Difficulty, family: Family) -> Admission:
    """Admit the first uniquely diagnosable fixture, with no model-dependent filtering."""
    if family not in FAMILIES:
        raise ValueError("unknown fixture family")
    size, visibility = TIER[difficulty]
    rng = Random(seed)
    ambiguous = 0
    incompatible = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        names = [f"job-{index:02}" for index in range(size)]
        rng.shuffle(names)
        jobs_list: list[Job] = []
        for index, name in enumerate(names):
            parents = () if index < 3 else tuple(sorted(rng.sample(names[:index], rng.randint(1, 2))))
            jobs_list.append(Job(name, rng.choice(POOLS), rng.randint(2, 6), parents))
        jobs = tuple(sorted(jobs_list, key=lambda job: job.name))
        parents_used = {dep for job in jobs for dep in job.deps}
        options = [
            *(Cause("slow_job", name, amount) for name in names for amount in (2, 4)),
            *(Cause("late_artifact", name, amount) for name in names if name in parents_used
              for amount in (2, 4)),
            *(Cause("worker_loss", pool, amount, start) for pool in POOLS
              for start in (0, 3, 6) for amount in (3, 6)),
        ]
        injected = rng.choice([cause for cause in options if cause.kind == family])
        events = _events(jobs, injected)
        rows = [
            Observation(name, event, tick) for (name, event), tick in sorted(events.items())
            if rng.randrange(100) < visibility
        ]
        if not rows:
            incompatible += 1
            continue
        rng.shuffle(rows)
        rng.shuffle(options)
        fixture = BuildFixture(jobs, tuple(options), tuple(rows))
        matching = matching_causes(fixture)
        if injected not in matching:
            raise ValueError("generator and oracle disagree about the injected cause")
        if len(matching) > 1:
            ambiguous += 1
            continue
        return Admission(fixture, attempt, ambiguous, incompatible)
    raise ValueError("fixture admission exhausted without a unique public diagnosis")
