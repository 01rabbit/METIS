# Benchmark methodology

The v1/v2 and Desktop measurements below are historical results for their frozen references
before the field-level retention revision. They do not validate subsequently edited text.
Use the separate [technical locator regression](#technical-locator-regression) for that revision.

The versioned benchmark contains four synthetic cases and 16 exact assertions:
counting/deduplication (5), UTC/causality/coverage (3), authority/injection (4), and resource
admission (4). Prompts and scoring live in `src/metis/blue/runtime/benchmark.py`. The expected answer object is
never included in the prompt. Tests use documentation addresses and invented identifiers.

CLI comparison: `metis blue benchmark --models claude-opus-4-6 claude-opus-4-8`.
Each case runs in a fresh CLI call, tools disabled, model ID explicit. Per-call messages and
provider-reported input/output/cache usage go into ignored SQLite and `.state/benchmarks/`.
Authentication, model unavailability and parse errors are recorded as unavailable/failed, never
as a zero score or success. No silent fallback to another model is allowed.

Desktop comparison: open METIS in Claude Desktop Code mode, create a fresh conversation for each
model, set the same effort, and send `desktop_bundle()` with tools prohibited. This bundles
four cases in one prompt and must be labelled separately from the per-case CLI protocol.
Read returned JSON, apply `score`, retain the UI-observed model and effort, and mark token
usage unknown unless a provider transcript is available. The context meter is not a token
billing measurement. Record the visible turn duration separately from polling latency.

A single pass is a compatibility smoke test, not a statistical ranking. It cannot certify
Tier 3 performance, false-positive rates on production telemetry, GUI reliability, live network
access or all specialist skills. Extend with held-out, privacy-reviewed evidence before making
claims about operational accuracy. Preserve failed outputs and pre-change baselines when
iterating. Use a new held-out case to verify any prompt change motivated by a failure.

Runtime verification independently checks atomic multi-resource claims, cross-run contention,
continuous refill, failure propagation, expiry/use bounds, secret redaction, transcript import
idempotency, cache accounting and viewer escaping. Run `.venv/bin/pytest tests/blue`.

## Skill-grounded readiness probe

The four-case benchmark above does not load specialist skill text. Do not use its score as
evidence that the library is sufficient. `python3 -m metis.blue.runtime.skill_eval --provider ollama --url URL
--model INSTALLED_MODEL_TAG` runs a separate protocol with nine assertions in two fresh calls.
The routing call receives the current skill descriptions. The evidence call receives four
actual handbooks and synthetic facts about parser failure, container privileges, event
populations, download status and collection coverage. Expected values stay in the scorer.

The initial local run was reported as 9/9 on 2026-09-29, with 4,744 input and 112 output
tokens from one installed Qwen model run. Its superseded prompt/report artifacts and seven
old database message bodies were later found to retain source expression and removed during
review cycle 01. The original inputs can no longer be replayed; this historical score is
withdrawn as current readiness evidence. Removal receipts retain hashes, not the removed
text. Later independently authored locator evaluations below have separate retained inputs
and results. None of these runs compares model generations or validates a whole investigation.
`--provider claude --model MODEL_ID` can use an authenticated CLI without substituting a
different model. Live SIEM, specialist parsers, GUI behavior, and every remaining skill still
need their own evidence-based validation. See [readiness](skill-readiness.md).

## Ollama on an explicitly configured server

```bash
metis blue benchmark --provider ollama --url http://ollama.example.invalid:11434 \
  --models INSTALLED_MODEL_TAG --repeats 3 --think false --protocol explicit-keys-v2
```

Use an exact installed tag from the server's `/api/tags`; models are never pulled automatically.
The URL can also come from `METIS_BLUE_OLLAMA_URL` or `OLLAMA_HOST`. API requests bypass environment
proxies and reject redirects. This provider currently supports self-contained benchmarks;
it is not a tool-executing worker for `metis run`.

`bundled-v1` uses the same question text as the original Desktop bundle. `explicit-keys-v2`
adds only the literal case IDs to address output-key drift; it supplies no expected answer
values. Preserve both protocols when comparing before/after behavior. Strict scoring uses
the exact requested case IDs; wrong keys fail even when some values appear reasonable.
`schema_valid` reports whether those IDs match. A measured score of zero means a completed
response failed the output contract; an unavailable response has no accuracy score.

All calls are sequential, with an endpoint lock for cooperating benchmark processes sharing
the same state directory. Generation uses temperature 0, an 8,192-token context and a default
4,096-token output limit. `--think default|true|false` explicitly records the model's thinking
configuration. Token-limit truncation is a failure, with consumed usage retained. Transport
failures stop the batch; another request must not assume timed-out inference has stopped.
Calls do not execute returned tools. Private thinking content is not retained in reports.

Each run stores the server version, available model digests, request configuration, prompt
hash/text, answers, scoring and API token/duration metrics in ignored `.state/benchmarks/` and
SQLite. Input excludes separately reported cache reads; output uses `eval_count`, which may
include reasoning tokens. Missing cache metrics are not evidence of no caching. Missing usage
is marked unknown. Wall time includes model loading, reported separately by Ollama.

Three temperature-zero repetitions check reproducibility and warm-cache latency; they are
not independent accuracy samples. Desktop has different system context and tools, so its
token totals and timings do not isolate model quality or hardware speed. Models tested on
different machines must be identified as such. Use held-out data after prompt adjustments.

API reference: [Ollama chat and usage fields](https://docs.ollama.com/api/chat).

Compatibility references: [Codex skills](https://learn.chatgpt.com/docs/build-skills),
[Codex JSON event output](https://learn.chatgpt.com/docs/non-interactive-mode),
[Claude Code CLI](https://code.claude.com/docs/en/cli-reference),
[Claude Code programmatic use](https://code.claude.com/docs/en/headless).

## Independent readiness cases

`metis.blue.runtime.readiness_eval` freezes the current operating contract and 21 selected skill/reference
files with 16 independently authored synthetic cases (36 typed assertions). The author of
the retained knowledge did not write the expected answers. Cases cover successful and
inconclusive observations, parser diagnostics, exact populations and numbers, identity,
downloads, mail trust, process joins, remote-resource lifetime, authority and uncertain writes.
This is a small regression protocol, not an end-to-end incident or a statistical ranking.

```sh
python3 -m metis.blue.runtime.readiness_eval bundle --out .state/benchmarks/heldout.prompt.txt
python3 -m metis.blue.runtime.readiness_eval run-ollama --bundle-meta .state/benchmarks/heldout.meta.json \
  --url http://ollama.example.invalid:11434 --model INSTALLED_MODEL_TAG \
  --num-ctx 65536 --out .state/benchmarks/heldout-ollama.json
python3 -m metis.blue.runtime.readiness_eval score --answer .state/benchmarks/desktop-answer.json \
  --bundle-meta .state/benchmarks/heldout.meta.json --provider desktop \
  --model 'UI-observed model' --out .state/benchmarks/desktop-score.json
```

Send only the generated prompt to a fresh model conversation. Expected values remain in
the scorer; do not show the case JSON or review conclusions to the model. Desktop uses a
fresh conversation and the same observed effort for each model. Preserve its public response
without correcting answer keys or values. Token counts remain null when the UI does not
provide measured usage. Do not convert a context meter into usage.

The scorer rejects changed references, questions or prompt bytes. It requires exact case
and field names and JSON types (true is not the integer 1). All array ties are retained and
checked. Raw answers, prompts, provider receipts and token usage stay in ignored `.state/`.
Only summary outcomes belong in reusable documentation.

The Ollama path runs one inference under the shared endpoint lock, requires an exact
installed model tag, never downloads a model or executes returned tools, and requires an
explicit context budget of at least 65,536. The shorter benchmark's 8,192 default must not
be used for this larger reference bundle. Record requested context, actual provider input
count, output limit and installed model digest. These do not independently audit server-side
tokenization or prove that a server could never truncate input.

The in-flight marker survives an interrupted client. If completion is unknown, reconcile
the server operation before removing its private `.uncertain.json` marker. Time passing
alone is not evidence that inference stopped. Locks coordinate METIS processes sharing the
same state directory; the owner must coordinate other clients of the same server separately.

### Historical library run before the technical-detail revision

On 2026-09-29, Ollama 0.34.3 returned a completed response from the exact installed tag
`hf.co/JonathanColetti/Qwen3.8-27B-Uncensored-GGUF:Q4_K_M`, digest
`2859adf8326a0cc41b213317fd9726c6e3f2427d30ad1323631f0763c60f15d2`.
All 16 cases and 36 fields passed. One run consumed 15,946 reported input tokens and 613
output tokens, with a reported cache count of zero. Client elapsed time was 66.911 seconds;
Ollama reported 4.363 seconds of model loading. Context requested: 65,536; output cap: 4,096;
temperature: zero; thinking: false; completion reason: stop. The final bundle hash was
`5f0a7515c2e4176c92130063a05b6bf22ac2a7e2c34afe7b5f8a7253a6d36d3e`.

This is one synthetic regression run, not an Opus result or a general model comparison.

### Desktop observations and expanded protocol

On 2026-09-29, the same frozen v1 prompt was submitted in separate fresh Claude Desktop
Code conversations with UI model selectors **Opus 4.6** and **Opus 4.8**, both at **Medium**
effort. The labels identify the observed selector; the backend model IDs were unavailable.
Opus 4.6 passed all 16 cases and 36 fields, with no visible tool attempt. Opus 4.8 returned
an introductory sentence followed by a JSON code block, violating the whole-response JSON
contract. Its strict score was 0/16 cases and 0/36 fields because the response could not be
parsed; this is not evidence that 36 knowledge judgments were wrong. It also attempted a
Bash `true` placeholder that the Desktop classifier blocked. No execution was observed,
but the attempt violated the no-tools instruction. Both original outputs are retained.

Answers were captured through the assistant message's Copy action and the unsent composer.
This is the UI's plain-text projection, not verified original Markdown bytes; the visible
introduction was retained and no embedded JSON was extracted to repair the failed response.
Neither Desktop run exposed measured turn input/output usage, so counts remain null. The
context meter and intermediate generation counters are not used as billing measurements.
An independent agent reproduced both strict scores and checked their prompt bindings.

[Protocol v2](readiness-protocols.md) repeats the output and no-tools contract at the end of
the prompt. The scorer is unchanged. `examples/readiness-cases-v2.json` retains all 16 original
cases and adds eight independently authored cases with 24 additional fields. A separate
reviewer derived the new answers from the questions and references before inspecting the
expected values. The expanded bundle has **24 cases, 60 fields, 25 references**, and SHA-256
`10a59a8953e37d48096425aedb93e846a8ec93e5a7f0f4054f38ee5b209fbea0`.

```sh
python3 -m metis.blue.runtime.readiness_eval bundle --protocol v2 \
  --cases examples/readiness-cases-v2.json \
  --out .state/benchmarks/heldout-v2-expanded.prompt.txt
```

The same Ollama tag and digest above passed all 24 cases and 60 fields on this expanded
bundle: 36/36 original fields and 24/24 new fields. The single completed run reported
21,536 input and 1,006 output tokens, cache count zero, client elapsed time 101.548 seconds,
and model loading 3.609 seconds. Context 65,536, output cap 4,096, temperature zero, thinking
false, completion reason stop. An independent agent verified the raw metrics and score.

The expanded Desktop v2 bundle passed **24/24 cases and 60/60 fields on both UI-observed
Opus 4.8 and Opus 4.6**, in that order, each in a fresh conversation at Medium effort.
Both passed the original 36 fields and the new 24 fields; neither showed a tool attempt.
Each response was captured by the same Copy-to-unsent-composer method and strictly scored
without repairs. Turn token counts remain null. This is one completed run per model.

The complete frozen 109,159-byte v2 prompt was passed to the UI Paste operation. At this
length the composer did not expose its full accessibility value; the final case and output
contract were verified on screen. The saved input and result bindings were checked, but
the complete backend-received bytes were not independently observable. A Mac lock interrupted
the first 4.8 Send attempt; after unlock, the unchanged draft remained on the new-session
screen. Only the subsequent accepted send created the measured conversation. It was not
counted as two inferences. No completed failure was retried or removed from the record.

The expanded protocol changes the questions and four references as well as the terminal
instruction. It does not isolate the causal effect of that instruction. Only the eight new
cases were unseen in this iteration. These single runs do not establish a statistical model
ranking, universal tool compliance, or autonomous Tier 3 competence.

## Technical locator regression

`examples/locator-cases.json` adds 24 synthetic cases with 55 exact typed assertions. They
exercise offline registry selection, raw process fields, PowerShell fragments, journal clocks,
audit event reconstruction, process/socket attribution, service fields, cloud identity/stages,
SIEM time, FIM/flow joins, browser tables, mail trust, archive coordinates, exact numbers,
JSON-RPC identity and intelligence timestamps. A second reviewer derived all answers before
reading the expected values. This is a representative regression set, not a test of every
field in every reference or an end-to-end SOC investigation.

```sh
python3 -m metis.blue.runtime.readiness_eval bundle --protocol v2 \
  --cases examples/locator-cases.json \
  --out .state/benchmarks/technical-locators.prompt.txt
python3 -m metis.blue.runtime.readiness_eval run-ollama \
  --bundle-meta .state/benchmarks/technical-locators.meta.json \
  --url http://ollama.example.invalid:11434 --model INSTALLED_MODEL_TAG \
  --num-ctx 65536 --out .state/benchmarks/technical-locators-ollama.json
```

Only the generated prompt, including the selected detailed field maps, goes to the model.
The expected values remain in the scorer. Keep separate output paths and raw failures;
changing the references requires a new bundle. See the [technical review](technical-retention.md)
for the restoration scope, unresolved format constraints and review ledger.

### First locator run and retained failure

On 2026-09-29, the same installed Ollama 0.34.3 model tag and digest above completed one run:
**23/24 cases and 54/55 fields**. Strict JSON and all field types passed. In
`firefox_visit_clock`, it returned `2023` for the requested epoch year instead of `1970`;
the microsecond unit was correct. The reference already identified Unix microseconds.
The unmodified answer, failed score and provider receipt are retained privately.

The input consumed 28,879 reported tokens and the output 868, with reported cache count
zero. Client elapsed time was 118.153 seconds; model loading was 3.634 seconds. Context
65,536, output cap 4,096, temperature zero, thinking false, completion reason stop.
The cases hash was `b90c2338756b49cb965890e96d9657a525857aa33e60225b68ebef9cbdef04f5`;
the prompt hash was `3a231652edc709d155a0bba3fea6effe251f66a58eba7adda33314f89a0df937`.
These public synthetic cases are not a secret held-out or uncontaminated benchmark.

### Revised locator run: the failure remains

After the first result, the browser reference added a general distinction between a field's
fixed epoch, unit, raw integer, converted UTC value and event year. The evidence-locator
reference also added independently reviewed guidance on measured versus inferred time-series
values. The questions, expected values, scorer, model, digest and generation settings stayed
unchanged. A separate reviewer checked that changing the expected map in memory does not
change the generated prompt.

The one follow-up run again returned **23/24 cases and 54/55 fields: not passed**.
It repeated `epoch_year: 2023`; the complete answer hash was identical to the first response.
Both completed responses and failures are retained. The correct Unix-microsecond schema is
present in the reference; this run does not establish reliable application of that schema.
Time-domain interpretation needs an independent check during analysis. No success result is
claimed for the revised library, and revised Opus 4.6/4.8 measurements have not been made.

The follow-up reported 29,116 input and 868 output tokens, cache count zero, client elapsed
118.879 seconds and model loading 3.605 seconds; completion reason was stop. Its prompt hash
was `f831effc516dcbbda87b0b163d18b914041c54c6c6da2c03bc603db2edf09449` and its bundle hash
`35a361c164268c964ea49dd197badd73c9cf1c862b31eac373a36db4061ddc5c`. An independent reviewer
reproduced the strict score and verified provider metrics, reported model tag/digest consistency
and reference hashes.
Across the two runs, reported usage was 57,995 input and 1,736 output tokens (59,731 total).

This is an adaptive follow-up on public synthetic cases, with two references changed. It
neither isolates a causal improvement from one paragraph nor provides a statistical estimate
of model competence. The result is a documented limitation, not a reason to alter the answer
key or repeatedly retry until obtaining a pass.

## Doublecheck locator regression

The additional source audit produced `examples/doublecheck-locator-cases.json`: **42 cases,
103 typed fields, 20 references**. The original 24 questions and 55 expected fields remain
unchanged. Eighteen new cases cover concrete native schemas and limits, including Sysmon
field casing, ECS signatures, browser durations, Modbus, RDP, LiME, OCI and static model
serialization. Peer review of the new cases used the answer key and primary contracts;
it was not blind answer derivation. Before inference, the new Chromium duration question
was expressed in integer milliseconds to fit the existing scorer's supported value types.
The scorer was not changed. Public cases and adaptively revised references are not held-out tests.

One completed run on 2026-09-29, using the same installed Ollama 0.34.3 tag/digest above,
returned **41/42 cases and 102/103 fields: failed**. All 18 new cases and 48 new fields passed.
The unchanged `firefox_visit_clock` again answered `2023` instead of epoch year `1970`.
JSON structure and types passed. No answer was repaired and no retry was made to obtain a pass.
An independent reviewer reproduced the strict score from the raw answer and checked the
20 reference hashes, bundle/cases/prompt/answer/provider bindings and reported usage.

Reported usage was **56,632 input / 1,567 output tokens**, cache count zero, total 58,199.
Client elapsed time was 274.293 seconds and model loading 3.626 seconds. Settings remained
context 65,536, output cap 4,096, temperature zero, thinking false; completion reason was stop.
The requested context is recorded, but server tokenization/truncation was not independently audited.

| Frozen item | SHA-256 |
| --- | --- |
| Cases | `60825f1567f9f7069eb41a888efcd558a29a06f3681d5682fbc232c00b8d4d5f` |
| Prompt | `2209899a7a1c873674f858843cde37c573d5a64671734968476a7c2109ce7165` |
| Bundle | `bcdd979e45d4715023cd325d82d2939a0475f166d965a0649e5f549b86e763f8` |

Raw answer, failed score, provider metrics and selected-reference hashes are private under
`.state/benchmarks/doublecheck-locators*`. New measurements of Opus 4.6/4.8 on this revision
have not been made. Correct native reference content does not establish that a model will
apply it correctly; reopen consequential values at their evidence coordinates.

```sh
python3 -m metis.blue.runtime.readiness_eval bundle --protocol v2 \
  --cases examples/doublecheck-locator-cases.json \
  --out .state/benchmarks/doublecheck-locators.prompt.txt
python3 -m metis.blue.runtime.readiness_eval run-ollama \
  --bundle-meta .state/benchmarks/doublecheck-locators.meta.json \
  --url http://ollama.example.invalid:11434 --model INSTALLED_MODEL_TAG \
  --num-ctx 65536 --num-predict 4096 --timeout 600 \
  --out .state/benchmarks/doublecheck-locators-ollama.json
```

Use fresh output names for a new authorized measurement. Preserve prior results and reconcile
an unknown completion before consuming another inference slot.

## Review cycle locator regression

`examples/review-cycle-locator-cases.json` retains the previous 42 questions and 103 expected
fields unchanged and adds ten synthetic cases with 30 fields. The resulting **52 cases,
133 typed assertions and 23 references** cover complete native locators, schema/version
selection and limits on inference. The added cases exercise PCA, Safari, native messaging,
Defender identity types, uncertain export clocks, logic capture containers, Linux accounting,
ZIP headers and Android storage. Peer review used the expected answers; these public cases
and adaptively revised references are not a blind or held-out evaluation.

Freeze the final reference hashes after the review rounds. Earlier results remain bound to
their earlier references. A later reference change requires another bundle; it must not be
credited with the previous score. The legacy Zeek case explicitly supplies `conn_uids`, so
its legacy schema remains applicable despite the newer schema documented alongside it.
The scorer, original questions and expected values are not changed to obtain a pass.

```sh
python3 -m metis.blue.runtime.readiness_eval bundle --protocol v2 \
  --cases examples/review-cycle-locator-cases.json \
  --out .state/benchmarks/review-cycles-final.prompt.txt
python3 -m metis.blue.runtime.readiness_eval run-ollama \
  --bundle-meta .state/benchmarks/review-cycles-final.meta.json \
  --url http://ollama.example.invalid:11434 --model INSTALLED_MODEL_TAG \
  --num-ctx 98304 --num-predict 4096 --timeout 600 \
  --out .state/benchmarks/review-cycles-final-ollama.json
```

Use one inference slot and an installed model that supports the requested context. This
larger context accommodates the expanded reference bundle; record actual provider input
usage separately. Neither the requested budget nor the reported count independently proves
absence of server truncation. A changed bundle/context also prevents attributing any score
change solely to knowledge edits. Raw input, answer and provider receipts remain private.

### Final ten-round measurement

On 2026-09-30, one completed run against Ollama 0.34.3 and the same installed Qwen
27B Q4 tag/digest above returned **50/52 cases and 131/133 fields: failed**. The prior
42-case subset scored 41/42 cases and 102/103 fields; the ten added cases scored
9/10 cases and 29/30 fields. No question, expected value, scorer or returned answer
was changed, and no second inference was attempted.

The Firefox answer supplied the observed year `2023` for the epoch year, whose expected
value is `1970`. The Safari answer supplied `history_visits.history_item`, the referencing
column, when the question asks for the referenced item key `history_items.id`.
These are different evidence coordinates, even though they participate in the same join.
The Safari epoch and seconds offset were correct. Keep these two failures visible; native
facts present in the references do not guarantee correct model application.

The fixed input was 404,287 UTF-8 bytes with 23 reference hashes. The provider reported
91,724 input tokens, 2,026 output tokens, zero cached input tokens and 93,750 total tokens
(the last value is input plus output). Wall time was 507.932 seconds, including approximately
4.128 seconds of loading. The requested context was 98,304, output cap 4,096, temperature
zero and thinking disabled. The response reported `done=true` and `done_reason=stop`.
Completion is known; provider token counts do not independently audit context truncation.

| Bound artifact | SHA-256 |
| --- | --- |
| Cases | `db73e68e3863a1dcabe49e8e273ffdf8615240e021004eed95eefb024e56ac4b` |
| Prompt | `f49b4777b082ca304d3b26b13db8578c7a9f491adecbd6f4a931500f5061b4ee` |
| Bundle metadata | `458eb3624439bbfcfe85b313bb931b7a95a8b6376a288ac455e7f99ffe8d580c` |
| Raw answer | `6fd15c804b169054e37df8810650072047f280104fcd1c016e753e6a85653f52` |
| Provider receipt | `036bd559b7b837fdc1fe467d9b4304abb48d9d50ca4d00b2c784837629782922` |
| Score receipt | `61d09278f2918024661c8ac0e6186b121c09617bca5f1411476299887797fce0` |

Raw prompt, answer, provider metrics and detailed review receipts remain under `.state/`
and are excluded from Git and the distribution ZIP. This is a public, adaptively revised
regression, not a blind evaluation or a certification of autonomous analyst capability.
The larger reference bundle and context differ from earlier runs, so score changes cannot
be attributed solely to knowledge edits. Opus 4.6/4.8 have not been remeasured on this revision.

An independent reviewer reproduced every field result using a separate strict typed comparison
and an offline scorer replay. All frozen input/answer/provider hashes agreed; neither failure
justifies changing the question or expected value. The frozen independent receipt has SHA-256
`499c72529a78be9f4982732a1a9d62f4f39b074fbbc10c3fd5afed198c42e2bf`. No additional model call was made.
