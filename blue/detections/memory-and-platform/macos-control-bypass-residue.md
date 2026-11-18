# Assess macOS security decisions and unexpected execution

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did the system enforce the expected control for an acquired application, and what actually ran?

## Evidence to request

Acquisition metadata and quarantine state where retained, code-signing/notarization assessment, policy decisions, unified/endpoint logs, process ancestry and privacy-permission changes.

## Reasoning procedure

- Evaluate the specific control separately: download assessment, code identity, runtime protection, or privacy consent. Success in one control is not proof that all controls were satisfied.
- Relate quarantine or policy state changes to the same artifact and actor. An absent attribute on a copied file does not establish deliberate removal.
- Use actual process identity and observed access to determine execution and impact. A signature or notarization status is not a benign verdict.
- Review configuration/profile changes and granted permissions against authorized deployment activity.
- Record OS/build, retention and privacy redaction limits. A generic endpoint schema may not expose the security decision being investigated.

## Alternatives and limits

Enterprise deployment, developer tools, archive extraction and migration can produce unusual acquisition metadata. Logging differences across releases make fixed event assumptions unreliable.

## Discriminating checks

Test approved managed deployment, a copied file with unknown provenance, a blocked launch and an observed launch with a policy discrepancy. Do not bypass controls to validate a detection. Permission or profile changes require the relevant owner.

## Concrete observation contract

Request the acquired `com.apple.quarantine` attribute, LaunchServices quarantine database,
relevant `tccd`/`syspolicyd` log interval and, when already authorized and available, the
TCC database with its schema version. These artifacts answer different questions about
origin, assessment and privacy permission. Absence of an attribute is not a removal event.

With Endpoint Security records, relate the event's `audit_token` to the parent and
responsible audit tokens; retain `signing_id`, `team_id`, `cdhash` and `codesigning_flags`
at that observation. A later signature inspection cannot reconstruct the earlier state.
Use [specialist telemetry](../../skills/soc-detection-engineering/references/telemetry-specialist.md)
for exact candidate locations and private-schema limits. Confirm an actual protected
operation or execution after the policy transition before concluding that a control was
ineffective; an authorized permission change is a necessary benign counterpart.
