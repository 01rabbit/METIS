import base64
import json
import os
import time

import pytest

from metis.core.budgets import BudgetExhausted, BudgetTracker, Cancelled
from metis.core.contracts import ChallengeManifest, RunBudget, RunStatus
from metis.core.fixtures import generate_fixtures
from metis.core.models import Decision, FixtureProvider
from metis.core.runner import Runner
from metis.core.runtime import FixtureRuntime, ToolResult
from metis.core.store import RunStore
from metis.core.verification import FixtureOracle


class FailedRuntime:
    def execute(self, request, *, timeout_seconds):
        return ToolResult(ok=False, output="failed local transform")


class ConstantProvider:
    reservation_tokens = 0
    reservation_cost = 0.0

    def __init__(self, decision):
        self.decision = decision

    def decide(self, context, *, timeout_seconds):
        return self.decision


@pytest.fixture
def local_fixture(tmp_path):
    oracle_path = tmp_path / "private/answers.json"
    paths = generate_fixtures(tmp_path / "solver", oracle_path)
    manifest = ChallengeManifest.model_validate_json(paths[0].read_bytes())
    oracle = FixtureOracle(oracle_path, solver_roots=(tmp_path / "solver",))
    store = RunStore(tmp_path / "runs.sqlite")
    return manifest, oracle, store


def test_limits_are_charged_before_work():
    now = [0.0]
    tracker = BudgetTracker(RunBudget(max_actions=1, max_model_tokens=3,
                                      max_cost_usd=0.25, wall_time_seconds=2),
                            clock=lambda: now[0])
    tracker.reserve_action()
    with pytest.raises(BudgetExhausted, match="actions"):
        tracker.reserve_action()
    tracker.reserve_model(3, 0.25)
    with pytest.raises(BudgetExhausted, match="tokens"):
        tracker.reserve_model(1, 0)
    with pytest.raises(BudgetExhausted, match="cost"):
        tracker.reserve_model(0, 0.01)
    with pytest.raises(Cancelled):
        tracker.check(cancelled=True)
    now[0] = 2
    with pytest.raises(BudgetExhausted, match="wall time"):
        tracker.check()


def test_unverified_candidate_is_not_a_solve_or_leaked_to_events(local_fixture):
    manifest, oracle, store = local_fixture
    private_candidate = "METIS{wrong-private-candidate}"
    provider = ConstantProvider(Decision(kind="candidate", candidate=private_candidate))
    run_id = Runner(store, provider, FailedRuntime(), oracle, RunBudget(max_actions=2)).run(manifest)
    events = store.read(run_id)
    assert events[-1].status == RunStatus.EXHAUSTED
    assert RunStatus.SOLVED not in [event.status for event in events]
    assert private_candidate not in store.export_jsonl(run_id)


def test_repeated_action_is_stopped(local_fixture):
    manifest, oracle, store = local_fixture
    from metis.core.runtime import ToolRequest

    provider = ConstantProvider(Decision(kind="tool", tool=ToolRequest(tool="hex_decode", data="!")))
    run_id = Runner(store, provider, FailedRuntime(), oracle, RunBudget()).run(manifest)
    assert store.read(run_id)[-1].detail["reason"] == "repeated_action"


def test_cancelled_run_never_calls_provider(local_fixture):
    manifest, oracle, store = local_fixture
    runner = Runner(store, FixtureProvider(), FailedRuntime(), oracle, RunBudget(),
                    cancelled=lambda: True)
    run_id = runner.run(manifest)
    assert store.read(run_id)[-1].status == RunStatus.CANCELLED


def test_model_reservation_stops_before_call(local_fixture):
    manifest, oracle, store = local_fixture

    class ExpensiveProvider(FixtureProvider):
        reservation_tokens = 2

        def decide(self, context, *, timeout_seconds):
            raise AssertionError("must not call an unaffordable provider")

    run_id = Runner(store, ExpensiveProvider(), FailedRuntime(), oracle,
                    RunBudget(max_model_tokens=1)).run(manifest)
    assert store.read(run_id)[-1].status == RunStatus.EXHAUSTED


def test_provider_failure_is_audited_without_exception_text(local_fixture):
    manifest, oracle, store = local_fixture

    class BrokenProvider(FixtureProvider):
        def decide(self, context, *, timeout_seconds):
            raise RuntimeError("secret-in-error")

    run_id = Runner(store, BrokenProvider(), FailedRuntime(), oracle, RunBudget()).run(manifest)
    assert store.read(run_id)[-1].status == RunStatus.ERROR
    assert "secret-in-error" not in store.export_jsonl(run_id)


def test_tool_exception_becomes_audited_error(local_fixture):
    manifest, oracle, store = local_fixture

    class BrokenRuntime:
        def execute(self, request, *, timeout_seconds):
            raise RuntimeError("sensitive-tool-error")

    run_id = Runner(store, FixtureProvider(), BrokenRuntime(), oracle, RunBudget()).run(manifest)
    assert store.read(run_id)[-1].status == RunStatus.ERROR
    assert "sensitive-tool-error" not in store.export_jsonl(run_id)


def test_stop_requested_after_tool_prevents_verification(local_fixture):
    manifest, oracle, store = local_fixture
    cancelled = [False]

    class StoppingRuntime:
        def execute(self, request, *, timeout_seconds):
            cancelled[0] = True
            return ToolResult(ok=True, output="candidate-that-must-not-be-submitted")

    run_id = Runner(store, FixtureProvider(), StoppingRuntime(), oracle, RunBudget(),
                    cancelled=lambda: cancelled[0]).run(manifest)
    events = store.read(run_id)
    assert events[-1].status == RunStatus.CANCELLED
    assert RunStatus.VERIFYING not in [event.status for event in events]


def test_fixture_scope_does_not_enable_endpoints(local_fixture):
    manifest, oracle, store = local_fixture
    data = manifest.model_dump()
    data["scope"]["allowed_endpoints"] = [{"hostname": "localhost", "port": 8080}]
    manifest = ChallengeManifest.model_validate(data)
    run_id = Runner(store, FixtureProvider(), FailedRuntime(), oracle, RunBudget()).run(manifest)
    assert store.read(run_id)[-1].status == RunStatus.POLICY_DENIED


def test_oracle_is_private_external_and_independent(tmp_path):
    solver = tmp_path / "solver"
    paths = generate_fixtures(solver, tmp_path / "answers.json")
    with pytest.raises(ValueError, match="outside"):
        FixtureOracle(paths[0], solver_roots=(solver,))
    oracle = FixtureOracle(tmp_path / "answers.json", solver_roots=(solver,))
    answers = json.loads((tmp_path / "answers.json").read_text())
    challenge_id, answer = next(iter(answers.items()))
    assert oracle.verify(challenge_id, answer)
    assert not oracle.verify(challenge_id, "METIS{pattern-only}")
    assert not oracle.verify("unregistered", answer)
    assert answer not in paths[0].read_text()
    (tmp_path / "answers.json").chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        FixtureOracle(tmp_path / "answers.json", solver_roots=(solver,))


def test_oracle_is_never_overwritten(tmp_path):
    oracle = tmp_path / "answers.json"
    generate_fixtures(tmp_path / "solver", oracle)
    before = oracle.read_bytes()
    with pytest.raises(FileExistsError):
        generate_fixtures(tmp_path / "solver", oracle)
    assert oracle.read_bytes() == before


@pytest.mark.parametrize("category", ["crypto", "misc"])
def test_deterministic_provider_solves_two_fixture_categories_without_docker(tmp_path, category):
    oracle_path = tmp_path / "private/answers.json"
    paths = generate_fixtures(tmp_path / "solver", oracle_path)
    manifest = next(ChallengeManifest.model_validate_json(path.read_bytes()) for path in paths
                    if f"generated-{category}-" in path.name)
    oracle = FixtureOracle(oracle_path, solver_roots=(tmp_path / "solver",))

    class DecoderRuntime:
        def execute(self, request, *, timeout_seconds):
            try:
                output = (base64.b64decode(request.data, validate=True).decode()
                          if request.tool == "base64_decode"
                          else bytes.fromhex(request.data).decode()
                          if request.tool == "hex_decode" else "")
                return ToolResult(ok=True, output=output)
            except (ValueError, UnicodeDecodeError):
                return ToolResult(ok=False, output="invalid encoded input")

    store = RunStore(tmp_path / f"{category}.sqlite")
    run_id = Runner(store, FixtureProvider(), DecoderRuntime(), oracle, RunBudget()).run(manifest)
    events = store.read(run_id)
    assert events[-1].status == RunStatus.SOLVED
    assert events[-1].detail["verification"] == "local_fixture_oracle"
    assert all(answer not in store.export_jsonl(run_id)
               for answer in json.loads(oracle_path.read_text()).values())


@pytest.mark.parametrize("category", ["crypto", "misc"])
def test_real_isolated_fixture_loop(tmp_path, category):
    image = os.environ.get("METIS_TEST_DOCKER_IMAGE")
    if not image:
        if os.environ.get("METIS_REQUIRE_DOCKER_TESTS") == "1":
            pytest.fail("required Docker image configuration missing")
        pytest.skip("set METIS_TEST_DOCKER_IMAGE for actual Docker integration")
    if not FixtureRuntime.isolation_available():
        if os.environ.get("METIS_REQUIRE_DOCKER_TESTS") == "1":
            pytest.fail("required Docker cgroup v2 resource enforcement unavailable")
        pytest.skip("environment lacks enforced cgroup v2 quotas; runtime fails closed")
    oracle_path = tmp_path / "private/answers.json"
    paths = generate_fixtures(tmp_path / "solver", oracle_path)
    manifest = next(ChallengeManifest.model_validate_json(path.read_bytes()) for path in paths
                    if f"generated-{category}-" in path.name)
    oracle = FixtureOracle(oracle_path, solver_roots=(tmp_path / "solver",))
    store = RunStore(tmp_path / "runs.sqlite")
    started = time.monotonic()
    run_id = Runner(store, FixtureProvider(), FixtureRuntime(image, timeout_seconds=30),
                    oracle, RunBudget()).run(manifest)
    events = store.read(run_id)
    assert events[-1].status == RunStatus.SOLVED, [event.model_dump() for event in events]
    assert time.monotonic() - started < 120
    assert events[-1].detail["verification"] == "local_fixture_oracle"
    if category == "crypto":
        assert any(event.detail.get("tool_ok") == "false" for event in events)
    for answer in json.loads(oracle_path.read_text()).values():
        assert answer not in store.export_jsonl(run_id)
