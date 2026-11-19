# Issue #8 run-scoped memory treatment evidence

The prospective held-out protocol can now bind a scheduled run before its
first work event. `heldout_protocol bind` accepts the committed protocol hash,
run ID, task, repetition, arm and common prompt file. It verifies the file's
SHA-256 against the protocol and stores the prompt with the validated arm
configuration, model/runtime pins and equal per-run budget under the run lock. A duplicate
binding, unscheduled slot, wrong commitment, non-held-out run, prior work, or
session budget above the protocol is rejected.

Bind each fresh run with `python -m metis.evaluation.heldout_protocol bind
PROTOCOL.json --database STATE.sqlite --expected-sha256 DIGEST --run-id ID
--task-id TASK --repetition N --arm ARM --prompt-file PROMPT.txt` before
planning a wave or freezing its selected cards.

For bound runs, the specialist scheduler uses the arm's memory switch instead
of its global setting, limits the wave's specialists, fixes the per-run model
turn budget, and refuses a host launch if the selected model or runtime differs
from the binding. The Codex specialist driver prepends the committed common
prompt to every turn and records its prefix and rendered prompt digests. After
a host launch the scheduler records the arm, model, runtime and number of cards
in the specialist brief. Real-model finalization requires those records for
every bound specialist and compares them with the protocol,
as well as the existing exact frozen-card and ledger checks.

This attests the scheduler and Codex driver path used by this study. It does
not prove that a provider applied the prompt, expose the actual model's prior
training data, or measure an AlpacaHack solve. The `prompt_sha256` binds the
common prefix; each generated specialist brief has its own recorded digest.
Runs outside this binding
path are not acceptable to real-model protocol finalization.

Focused tests cover run binding and duplicate refusal, full/without-memory
brief behavior, host dispatch and prompt logging, missing/changed dispatch evidence,
and observed aggregate caps. The candidate AlpacaHack study has not begun.
Issue #8 remains open.

Validation on Python 3.12: 149 focused tests passed across held-out export,
analysis, MUNIN, scheduler and Codex specialist modules. Ruff and mypy on the
changed Python modules passed; `scripts/check_repo.py` reported zero findings.
