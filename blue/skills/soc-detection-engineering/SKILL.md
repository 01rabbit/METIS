---
name: soc-detection-engineering
description: Design, review and validate defensive detections against recorded or inert synthetic telemetry, including field contracts, false positives, coverage and deployment readiness.
---

# Detection design and review

Start with a security decision and an observable behavior. Specify the required sensor,
entity key, temporal relation and legitimate activity that can look similar. Choose a
file signature, network rule, Sigma rule or native SIEM query to fit the evidence and the
available backend; portability is useful only when conversion preserves that meaning.

Read [validation integrity](references/validation-integrity.md) before claiming a test passed.
Use the [coverage map](references/coverage.md) to identify less common telemetry needs and
[the catalog](../../detections/README.md) for defensive investigation candidates.

## Make the detection reviewable

A rule needs an owner, version/digest, source schema, required audit settings, reason for
firing, documented exclusions, expected volume and an analyst follow-up. IOC matches can
support scoping while behavioral correlation can survive superficial changes; neither is
universally superior. Hash type, indicator age, process ancestry and endpoint attribution
must be explicit. Never include case secrets or real incident answers in a generic rule.

For Sigma, check the converter, pipeline and backend against the actual normalized fields.
For YARA, state disk versus memory scope, supported file layouts, size bounds and structural
assumptions. A string hit does not establish execution. For a network detector, state
reassembly, stream direction, encryption visibility and protocol normalization assumptions.
For Wazuh or similar decoders, validate the decoded fields before testing the rule predicate.
Installed engine versions and usable sensors are prerequisites, not capabilities supplied
by this Markdown file.

## Validate the claim being made

Use retained telemetry and inert synthetic examples. Separate predicate correctness,
backend execution and sensor collection into independently evidenced results. Exercise
positive records, realistic benign counterparts, missing fields, duplicated input, alternate
entities, reversed order and interval boundaries. Cover each branch without reproducing
an intrusion or running a malicious sample.

Report precision and recall only for labeled datasets with stated denominators and sampling.
Measure daily alert volume on the intended estate; an unrepresentative clean corpus cannot
prove acceptable noise. Distinct-count approximation, query caps and missing sources belong
in test results. Suppressions require narrow evidence, an owner and a review date; broad host
exclusions can conceal relevant activity.

Deliver a candidate rule, field/coverage contract, test receipts, known false positives and
triage instructions. Promote it to deployment-ready only when its backend and telemetry path
are verified. A production change requires a scoped grant, rollback state and monitoring for
volume or coverage regressions. Configuration acceptance alone does not show useful detection.

## Concrete observation contract

Select the raw contract before choosing a query language:

- [Windows telemetry](references/telemetry-windows.md) covers provider/channel/event
  identities, process and logon joins, task/service state and directory mutation.
- [Linux and network telemetry](references/telemetry-linux-network.md) covers multipart
  audit reconstruction, effective identities, path/capability fields and Zeek joins.
- [Application and identity telemetry](references/telemetry-application-identity.md) maps
  HTTP, database, Entra and mail observations without inventing product columns.
- [Specialist telemetry](references/telemetry-specialist.md) covers macOS, crashes,
  passive industrial records and wireless evidence with explicit platform limits.

For each required value, record raw field name, type/encoding, producer/version, source
path/channel, enabled collection, normalized destination and null behavior. Separate
event number from unique record ID, actor from event-emitting host, configuration from
use and accepted permission from completed operation. Reject a correlation whose key is
missing rather than broadening it silently to account name, PID or timestamp alone.

The card's observation contract is a starting specification. Verify each requested field
against retained records from the actual environment before claiming coverage. Application
decision fields labeled custom require explicit instrumentation; these documents do not
make them appear in a SIEM. Changed knowledge or field mappings require new validation;
historical benchmark results are evidence only for their recorded content hashes.
