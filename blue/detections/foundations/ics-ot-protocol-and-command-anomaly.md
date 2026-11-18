# Assess control-system commands against operational intent

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Was a control command expected for the controller, operator station, process state and maintenance authorization?

## Evidence to request

Passive protocol metadata, asset roles, approved master/controller relationships, function and response codes, engineering change records and operator process observations.

## Reasoning procedure

- Distinguish reads, control/write requests, responses and acknowledged effects. A command being transmitted does not establish a physical state change.
- Compare peers and command types against a maintained operational baseline. Preserve baseline history across sensor restarts; first-seen-after-restart is not necessarily new.
- Review unusual masters, device/unit breadth and exception responses. Discovery or failed transactions may be visible where successful-command-only logs are blind.
- Interpret protocol fields with the deployed parser and device model. Similar numeric functions can have different operational significance across protocols.
- Ask the operations owner whether the observed state is safe before proposing any network or device action.

## Alternatives and limits

Commissioning, vendor support, failover and maintenance can change masters and command patterns. A network tap may cover only one direction or one cell; sensor loss must not become a claim that the plant is unaffected.

## Discriminating checks

Tabletop synthetic read, authorized write, rejected command, unexpected master and sensor-restart scenarios. Do not generate traffic to controllers. Any isolation or control change belongs to the operational safety authority and the scoped response plan.

## Concrete observation contract

For a deployed Zeek Modbus parser, inspect its actual `modbus.log` schema. Current base
fields include `ts`, `uid`, endpoint `id` and optional `func`/`exception`, with optional
`tid`, `unit` and `pdu_type` (request versus response). Do not assume register addresses,
quantity or write values are
present; these may require a different passive parser. Bind a response by connection,
transaction and unit, not merely by host and nearest timestamp.

Compare function and target asset with the authorized controller/master inventory and
maintenance window. Request acknowledgement establishes a protocol result, while actual
plant effect needs historian/controller state and operator confirmation. Record capture
coverage and parser errors. DNP3 or S7 field names are separate schema contracts, not
aliases of Modbus columns. See [specialist telemetry](../../skills/soc-detection-engineering/references/telemetry-specialist.md);
no active query or trial write is required for these checks.
