import base64
import json
import os
import random
import time

import pytest

from metis.core.budgets import BudgetExhausted, BudgetTracker, Cancelled
from metis.core.contracts import ChallengeManifest, RunBudget, RunStatus
from metis.core.fixtures import generate_fixtures
from metis.core.models import Decision, FixtureProvider, SolverContext
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


def test_model_rationale_is_not_persisted_in_event_chain(local_fixture):
    from metis.core.runtime import ToolRequest

    manifest, oracle, store = local_fixture
    private_rationale = "METIS{private-model-rationale}"
    provider = ConstantProvider(Decision(
        kind="tool", tool=ToolRequest(tool="hex_decode", data="!"),
        rationale=private_rationale))
    run_id = Runner(store, provider, FailedRuntime(), oracle, RunBudget(max_actions=2)).run(manifest)
    assert private_rationale not in store.export_jsonl(run_id)
    assert all("rationale" not in event.detail for event in store.read(run_id))


def test_repeated_action_is_stopped(local_fixture):
    manifest, oracle, store = local_fixture
    from metis.core.runtime import ToolRequest

    provider = ConstantProvider(Decision(kind="tool", tool=ToolRequest(tool="hex_decode", data="!")))
    run_id = Runner(store, provider, FailedRuntime(), oracle, RunBudget()).run(manifest)
    assert store.read(run_id)[-1].detail["reason"] == "repeated_action"


def test_fixture_provider_does_not_replan_on_unclassified_runtime_failure(local_fixture):
    from metis.core.models import SolverContext
    from metis.core.runtime import ToolRequest

    manifest, _, _ = local_fixture
    manifest = manifest.model_copy(update={"description": json.dumps({"attempts": [
        {"tool": "base64_decode", "data": "/w=="},
        {"tool": "hex_decode", "data": "/w=="},
    ], "fallbacks": [{"after": 0, "on": "invalid_input", "try": 1,
                      "rationale": "Parser rejection tests the alternate representation."}]})})
    context = SolverContext(
        challenge=manifest,
        observations=(ToolResult(ok=False, output="decoded data is not UTF-8 text",
                                 failure_kind="invalid_text"),),
        last_tool=ToolRequest(tool="base64_decode", data="/w=="),
    )
    decision = FixtureProvider().decide(context, timeout_seconds=1)
    assert decision.kind == "halt"
    assert "not parser-rejection evidence" in (decision.rationale or "")


@pytest.mark.parametrize(("first", "alternate", "shared_data"), [
    ("base64_decode", "hex_decode", "48"),
    ("hex_decode", "base64_decode", "SGVsbG8="),
])
def test_fixture_provider_uses_declared_parser_evidence_routes(
        local_fixture, first, alternate, shared_data):
    from metis.core.models import SolverContext
    from metis.core.runtime import ToolRequest

    manifest, _, _ = local_fixture
    primary = ToolRequest(tool=first, data=shared_data)
    alternate_request = ToolRequest(tool=alternate, data=shared_data)
    manifest = manifest.model_copy(update={"description": json.dumps({
        "attempts": [primary.model_dump(), alternate_request.model_dump()],
        "fallbacks": [{"after": 0, "on": "invalid_input", "try": 1,
                       "rationale": "Parser rejection supports the declared alternate strategy."}],
    })})
    context = SolverContext(
        challenge=manifest,
        observations=(ToolResult(ok=False, output="invalid transform input", failure_kind="invalid_input"),),
        last_tool=primary,
        attempted_tools=(primary,),
    )
    decision = FixtureProvider().decide(context, timeout_seconds=1)
    assert decision.kind == "tool" and decision.tool == alternate_request
    assert decision.rationale == "Parser rejection supports the declared alternate strategy."


@pytest.mark.parametrize("failure_kind", ["invalid_text", "execution_error", "timeout", "policy", None])
def test_fixture_provider_halts_configured_fallback_on_non_parser_failure(local_fixture, failure_kind):
    from metis.core.models import SolverContext
    from metis.core.runtime import ToolRequest

    manifest, _, _ = local_fixture
    primary = ToolRequest(tool="base64_decode", data="%%%")
    alternate = ToolRequest(tool="hex_decode", data="%%%")
    manifest = manifest.model_copy(update={"description": json.dumps({
        "attempts": [primary.model_dump(), alternate.model_dump()],
        "fallbacks": [{"after": 0, "on": "invalid_input", "try": 1,
                       "rationale": "Parser rejection supports testing hex."}],
    })})
    context = SolverContext(challenge=manifest,
                            observations=(ToolResult(ok=False, output="controlled failure",
                                                    failure_kind=failure_kind),),
                            last_tool=primary, attempted_tools=(primary,))
    assert FixtureProvider().decide(context, timeout_seconds=1).kind == "halt"


def test_fixture_provider_does_not_repeat_an_already_tried_alternate(local_fixture):
    from metis.core.models import SolverContext
    from metis.core.runtime import ToolRequest

    manifest, _, _ = local_fixture
    primary = ToolRequest(tool="base64_decode", data="%%%")
    alternate = ToolRequest(tool="hex_decode", data="%%%")
    manifest = manifest.model_copy(update={"description": json.dumps({
        "attempts": [primary.model_dump(), alternate.model_dump()],
        "fallbacks": [{"after": 0, "on": "invalid_input", "try": 1,
                       "rationale": "Parser rejection supports testing hex."}],
    })})
    context = SolverContext(challenge=manifest,
                            observations=(ToolResult(ok=False, output="invalid", failure_kind="invalid_input"),),
                            last_tool=primary, attempted_tools=(primary, alternate))
    decision = FixtureProvider().decide(context, timeout_seconds=1)
    assert decision.kind == "halt"
    assert "already attempted" in (decision.rationale or "")


def test_fixture_plan_rejects_fallbacks_on_infrastructure_failures(local_fixture):
    manifest, _, _ = local_fixture
    manifest = manifest.model_copy(update={"description": json.dumps({
        "attempts": [
            {"tool": "base64_decode", "data": "%%%"},
            {"tool": "hex_decode", "data": "%%%"},
        ],
        "fallbacks": [{"after": 0, "on": "execution_error", "try": 1,
                       "rationale": "Runtime failure tries a second tool."}],
    })})
    with pytest.raises(ValueError, match="only use invalid_input"):
        FixtureProvider().decide(SolverContext(challenge=manifest), timeout_seconds=1)


def test_fixture_plan_rejects_fallback_evidence_from_a_different_input(local_fixture):
    manifest, _, _ = local_fixture
    manifest = manifest.model_copy(update={"description": json.dumps({
        "attempts": [
            {"tool": "hex_decode", "data": "unrelated-probe"},
            {"tool": "base64_decode", "data": "SGVsbG8="},
        ],
        "fallbacks": [{"after": 0, "on": "invalid_input", "try": 1,
                       "rationale": "Probe rejection is incorrectly used to infer challenge encoding."}],
    })})
    with pytest.raises(ValueError, match="must preserve the challenge input"):
        FixtureProvider().decide(SolverContext(challenge=manifest), timeout_seconds=1)


def test_fixture_fallback_respects_action_budget(local_fixture):
    from metis.core.runtime import ToolRequest

    manifest, oracle, store = local_fixture
    primary = ToolRequest(tool="base64_decode", data="%%%")
    alternate = ToolRequest(tool="hex_decode", data="%%%")
    manifest = manifest.model_copy(update={"description": json.dumps({
        "attempts": [primary.model_dump(), alternate.model_dump()],
        "fallbacks": [{"after": 0, "on": "invalid_input", "try": 1,
                       "rationale": "Parser rejection supports testing hex."}],
    })})

    class CountingRuntime:
        calls = 0

        def execute(self, request, *, timeout_seconds):
            self.calls += 1
            return ToolResult(ok=False, output="invalid transform input", failure_kind="invalid_input")

    runtime = CountingRuntime()
    run_id = Runner(store, FixtureProvider(), runtime, oracle, RunBudget(max_actions=1)).run(manifest)
    assert runtime.calls == 1
    assert store.read(run_id)[-1].status == RunStatus.EXHAUSTED


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
            except UnicodeDecodeError:
                return ToolResult(ok=False, output="decoded data is not UTF-8 text", failure_kind="invalid_text")
            except ValueError:
                return ToolResult(ok=False, output="invalid encoded input", failure_kind="invalid_input")

    store = RunStore(tmp_path / f"{category}.sqlite")
    run_id = Runner(store, FixtureProvider(), DecoderRuntime(), oracle, RunBudget()).run(manifest)
    events = store.read(run_id)
    assert events[-1].status == RunStatus.SOLVED
    assert events[-1].detail["verification"] == "local_fixture_oracle"
    assert all(answer not in store.export_jsonl(run_id)
               for answer in json.loads(oracle_path.read_text()).values())


def test_evidence_conditioned_fallback_paired_seeded_ablation(tmp_path):
    """Thirty synthetic pairs: same first action/budget, oracle-scored outcomes."""
    from metis.core.runtime import ToolRequest

    class DecoderRuntime:
        def execute(self, request, *, timeout_seconds):
            try:
                output = (base64.b64decode(request.data, validate=True).decode()
                          if request.tool == "base64_decode"
                          else bytes.fromhex(request.data).decode()
                          if request.tool == "hex_decode" else "")
                return ToolResult(ok=True, output=output)
            except UnicodeDecodeError:
                return ToolResult(ok=False, output="decoded data is not UTF-8 text", failure_kind="invalid_text")
            except ValueError:
                return ToolResult(ok=False, output="invalid encoded input", failure_kind="invalid_input")

    class FirstActionBaseline:
        reservation_tokens = 0
        reservation_cost = 0.0

        def decide(self, context, *, timeout_seconds):
            # Pinned baseline is one-shot: it never uses failure evidence to replan.
            if context.observations:
                if context.observations[-1].ok:
                    return Decision(kind="candidate", candidate=context.observations[-1].output)
                return Decision(kind="halt")
            planned = json.loads(context.challenge.description)["attempts"]
            return Decision(kind="tool", tool=ToolRequest.model_validate(planned[0]))

    rng = random.Random(20261117)
    samples = [("base64", "METIS{" + f"{rng.getrandbits(128):032x}" + "}")
               for _ in range(15)]
    while sum(encoding == "hex" for encoding, _ in samples) < 15:
        value = "METIS{" + f"{rng.getrandbits(128):032x}" + "}"
        # Ensure Base64 rejects the hex-encoded bytes, so the observed failure
        # genuinely distinguishes the representation.
        encoded_hex = value.encode().hex()
        try:
            base64.b64decode(encoded_hex, validate=True)
        except ValueError:
            samples.append(("hex", value))
    del rng
    initial_tools = ["base64_decode"] * 15 + ["hex_decode"] * 15
    random.Random(20261120).shuffle(initial_tools)
    oracle_path = tmp_path / "private" / "answers.json"
    oracle_path.parent.mkdir()
    answers = {f"adaptive-{i}": value for i, (_, value) in enumerate(samples)}
    # Both systems receive only an opaque challenge id; this private file is used by verifier.
    oracle_path.write_text(json.dumps(answers))
    oracle_path.chmod(0o600)
    oracle = FixtureOracle(oracle_path, solver_roots=(tmp_path / "solver",))
    runtime = DecoderRuntime()
    deltas: list[int] = []
    adaptive_actions: list[int] = []
    baseline_actions: list[int] = []
    for i, (encoding, answer) in enumerate(samples):
        encoded = (base64.b64encode(answer.encode()).decode()
                   if encoding == "base64" else answer.encode().hex())
        first_tool = initial_tools[i]
        alternate_tool = "hex_decode" if first_tool == "base64_decode" else "base64_decode"
        manifest = ChallengeManifest.model_validate({
            "challenge_id": f"adaptive-{i}", "title": "Paired decoder fixture",
            "description": json.dumps({"attempts": [
                {"tool": first_tool, "data": encoded},
                {"tool": alternate_tool, "data": encoded},
            ], "fallbacks": [{"after": 0, "on": "invalid_input", "try": 1,
                              "rationale": f"{first_tool} parser rejection supports testing {alternate_tool}."}]}),
            "categories": ["crypto"],
            "scope": {"authorized": True, "granted_by": "offline-paired-ablation",
                      "challenge_id": f"adaptive-{i}"},
        })
        arm_success = []
        arm_actions = []
        for arm in ("adaptive", "baseline"):
            provider = FixtureProvider() if arm == "adaptive" else FirstActionBaseline()
            store = RunStore(tmp_path / f"{arm}-{i}.sqlite")
            budget = RunBudget(max_actions=3, wall_time_seconds=10, per_tool_seconds=2,
                               max_model_tokens=100, max_cost_usd=1)
            run_id = Runner(store, provider, runtime, oracle, budget).run(manifest)
            events = store.read(run_id)
            arm_success.append(events[-1].status == RunStatus.SOLVED)
            arm_actions.append(sum(event.status == RunStatus.EXECUTING
                                   and event.detail.get("operation") == "isolated_fixture_tool"
                                   for event in events))
            action_requests = [event.detail["tool"] for event in events
                               if event.status == RunStatus.EXECUTING
                               and event.detail.get("operation") == "isolated_fixture_tool"]
            assert len(action_requests) == len(set(action_requests))
            if arm == "adaptive" and first_tool != f"{encoding}_decode":
                failed_observation = next(i for i, event in enumerate(events)
                                          if event.status == RunStatus.OBSERVING
                                          and event.detail.get("tool_ok") == "false"
                                          and event.detail.get("tool") == first_tool
                                          and event.detail.get("failure_kind") == "invalid_input")
                alternate_action = next(i for i, event in enumerate(events)
                                        if event.status == RunStatus.EXECUTING
                                        and event.detail.get("tool") == alternate_tool)
                assert failed_observation < alternate_action
                assert "rationale" not in events[alternate_action].detail
        assert arm_actions[0] == (2 if first_tool != f"{encoding}_decode" else 1)
        assert arm_actions[1] == 1
        deltas.append(int(arm_success[0]) - int(arm_success[1]))
        adaptive_actions.append(arm_actions[0])
        baseline_actions.append(arm_actions[1])

    # Paired bootstrap percentile interval over fixed-seed paired outcomes.
    bootstrap = random.Random(20261118)
    estimates = [sum(bootstrap.choices(deltas, k=len(deltas))) / len(deltas)
                 for _ in range(10_000)]
    estimates.sort()
    interval = (estimates[249], estimates[9749])
    assert sum(deltas) == 14
    assert interval == (0.3, 0.6333333333333333)
    assert sum(adaptive_actions) == 44
    assert sum(baseline_actions) / 30 == 1


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
