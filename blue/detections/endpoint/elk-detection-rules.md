# Design file-to-execution correlation in Elastic

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Can retained file and process events show that a newly introduced artifact was executed, and which execution model applies?

## Evidence to request

ECS field mappings, event provider/version, host and process entity IDs, file hash/path, creation/write semantics, process command arguments and event timing.

## Reasoning procedure

- For a native executable, relate the created artifact to the subsequently executed image using hash or a normalized path with an explicit host/time bound.
- For a script, the process executable is the interpreter. Parse the script argument according to the actual command format; do not join the script path to process.executable.
- Preserve event order, bounded delay and duplicate behavior when choosing an EQL sequence or another backend operation. A single-event query is not a sequence detector.
- Validate file rename, replacement, case sensitivity and path normalization. A filename match alone cannot prove the executed bytes were the created bytes.
- Keep a documented list of unimplemented branches, such as execution without a file, unsupported interpreters and absent write events.

## Alternatives and limits

Installers, package managers, updates and development builds naturally create then execute files. Mapping differences across integrations can silently remove one leg of the correlation.

## Discriminating checks

Use synthetic native-file, interpreted-script, renamed-file, preexisting-file and missing-event sequences. Test the installed backend syntax and compare exact event IDs, including out-of-order arrival. No production detection is implied by this design card.

## Concrete observation contract

Write the backend mapping before translating a behavioral idea into a query. In ECS,
`process.entity_id` and `process.parent.entity_id` express process identity/ancestry;
`process.executable` and `process.args` are observations with different parsing semantics.
Retain `host.id`, `event.dataset`, `event.category`, `event.type`, `@timestamp` and
`event.ingested`. File predicates need actual `file.path` and the correct hash algorithm.
These fields are populated only if the integration supplies them.

Test a bounded sequence with the intended entity join and event-time order, not collector
arrival order. A same-name process on another host, a reused PID, reversed events and an
absent parent entity must have explicit outcomes. Pin the integration, ECS version,
converter/backend and field types. A rule that parses or returns an empty result is not
evidence that the required events existed or that the detection meaning survived conversion.
