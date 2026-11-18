# Determine what an application-control decision actually enforced

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did a policy merely audit an operation, block it, or permit a chain that subsequently performed an unauthorized action?

## Evidence to request

Application-control channel, provider, policy identifier, policy mode, target image/script, signer and hash; process and module events; policy deployment records.

## Reasoning procedure

- Separate audit decisions from enforcement. Preserve which artifact the decision concerned: an allowed launcher does not imply its child or loaded module was allowed.
- Associate a permitted executable with unexpected script, module or network activity using stable process identity. Signed status alone is neither an allow decision nor a benign verdict.
- Investigate execution from user-writable locations and unusual parentage in the context of the effective policy, not a global list of executable names.
- Distinguish an implementation gap, an intentional policy exception and missing telemetry. Report a bypass only when an applicable restriction and a prohibited action are both evidenced.

## Alternatives and limits

Installers, deployment agents, accessibility software and support scripts use trusted launchers. An unresolved signature or unavailable module event is not evidence of unsigned code. Policy upgrades can change event shape.

## Discriminating checks

Exercise inert event fixtures representing audit-only, successful block, allowed signed tool and a policy exception. The first two must not be labeled successful circumvention. Validate the provider/event mapping on the deployed OS before building a rule.

## Concrete observation contract

Distinguish the channel and policy mode. In Microsoft-Windows-AppLocker/EXE and DLL,
8002 is allowed, 8003 is an audit-mode would-block outcome and 8004 is blocked. For the
MSI and Script channel, the corresponding outcomes are 8005/8006/8007. A would-block
event is not enforcement failure because that policy was auditing.

For application-control policy enforcement, Microsoft-Windows-CodeIntegrity/Operational
3076 records an audit outcome and 3077 a block. Signature details in 3089 can be related
using the event's System Correlation `ActivityID`; preserve policy identity and all
relevant signature rows. Validate mappings against the deployed OS/policy version.
Only associate a later process/module with this file after checking digest, lifetime and
policy timing. A trusted signer or an allowed event does not itself demonstrate a bypass;
an approved policy exception is a legitimate explanation.
