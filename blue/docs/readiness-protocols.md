# Versioned readiness comparison

`python3 -m metis.blue.runtime.readiness_eval` supports two prompt protocols. Both use the same
case format and strict JSON scorer. Expected values remain in the case file on
the scoring side and are never included in the generated prompt.

The concrete field/location revision uses `examples/locator-cases.json` with protocol v2
as a separate 24-case, 55-field regression set. Earlier Desktop and Ollama results remain
bound to their original reference hashes; changing skill text does not renew those results.
See [technical locator evaluation](benchmark.md#technical-locator-regression).

| Selection | Stored protocol | Prompt behavior |
| --- | --- | --- |
| Omitted or `--protocol v1` | `blue-readiness-v1` | Original prompt bytes for identical cases and references. |
| `--protocol v2` | `blue-readiness-v2` | The entire v1 prompt followed by a final output and tool-use contract. |

The canonical stored names are also accepted by `--protocol`. Version selection
applies to `bundle`; `score` and `run-ollama` read the version from the frozen
metadata. They do not reinterpret an old bundle using the newest protocol.
Changing only the metadata version invalidates the bundle.

The final v2 line is:

> FINAL OUTPUT CONTRACT: Return only the requested JSON object in the final channel, starting with { and ending with }. No explanations, Markdown, or code fences. Do not call any tool, including no-op, preflight, or placeholder actions. Make the requested judgments only.

This line changes the response instruction, not the evidence, questions, field
types, expected values or score thresholds. The default remains v1 so existing
scripts continue generating the original prompt format.

## Compare the prompt versions

Create separate output paths. Do not overwrite a bundle used for a measurement.

```sh
python3 -m metis.blue.runtime.readiness_eval bundle --protocol v1 \
  --cases examples/readiness-cases.json \
  --out .state/benchmarks/compare-v1.prompt.txt
python3 -m metis.blue.runtime.readiness_eval bundle --protocol v2 \
  --cases examples/readiness-cases.json \
  --out .state/benchmarks/compare-v2.prompt.txt
```

Hold the case-file hash and reference hashes constant when comparing v1 and v2.
Use a fresh model conversation for each prompt, preserve the same visible model
and effort settings, and record the order and any retries. The protocol and
prompt hash belong with each result. A different case file or changed guidance
creates another comparison condition and should be reported separately.

Use `--cases examples/<separate-case-file>.json` for independently drafted new
cases, retaining the original case file. Pass only the generated `.prompt.txt`
to the model. Do not include the case JSON, expected answers or scoring review.
A repeat of a previously used case set is a regression measurement, not evidence
that those cases are still unseen.

```sh
python3 -m metis.blue.runtime.readiness_eval score \
  --answer .state/benchmarks/compare-v2.answer.json \
  --bundle-meta .state/benchmarks/compare-v2.meta.json \
  --provider desktop --model 'UI-observed model' \
  --out .state/benchmarks/compare-v2.score.json
```

Preserve the public response exactly as observed. The scorer parses the whole
answer as JSON; it does not extract an embedded object, strip an explanation,
remove code fences, correct keys or coerce values. Standard JSON whitespace is
accepted by both versions. JSON syntax, exact keys, scalar types and ordered
array values use identical criteria in v1 and v2.

An answer file cannot establish which channel or tool actions occurred before
the answer. Record visible tool calls, blocked attempts and channel/format
behavior separately from typed-answer accuracy. A blocked tool attempt is still
an instruction-following failure even if the final JSON is correct. Prompt
instructions are not an execution sandbox. Never execute a suggested command
or replay a tool call while scoring.

When Desktop does not provide measured token usage, retain null counts. A model
name in the text response is not identity verification; record the model shown
in the UI. For Ollama, the existing runner records installed-tag identity,
provider metrics and requested context and uses the frozen protocol automatically.

## Compatibility and limits

Existing v1 metadata is supported without migration. Its case, reference and
prompt integrity checks remain active: a changed reference still requires a
new bundle and cannot be silently attached to an earlier measurement. The
runner also verifies that the bundle scored after inference is the one sent
before inference. Raw prompts, answers and receipts stay under ignored `.state/`.

Offline tests preserve a pre-version-selection v1 fixture hash, verify that v2
adds only the terminal contract, exercise alternate case files, and reject
version relabelling and explanation/code-fence wrappers. Those tests verify
the measurement implementation. They do not demonstrate that any model obeys
v2 or establish general analyst-tier competence. Live outcomes belong in the
separate measurement record, including failures.
