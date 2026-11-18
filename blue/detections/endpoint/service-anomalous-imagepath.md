# Review service configuration and executable provenance

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does a service registration or change introduce an unexpected executable, identity or privilege boundary?

## Evidence to request

Service installation/configuration events, direct registry changes, service account/start mode, executable path/hash/signature and ACLs, initiating process and change ticket.

## Reasoning procedure

- Inspect both newly installed services and modifications to existing ones. An installation-only feed misses direct configuration edits.
- Resolve environment variables and quoting according to service execution semantics. Preserve the original value while recording the interpreted executable separately.
- Prioritize unexpected user-writable locations, identities or changed artifacts using local service baselines. A temporary path is suspicious context, not proof.
- Correlate configuration with actual service start and resulting process. Registration does not establish execution or persistence success.
- Inspect binary and directory write permissions when assessing who could alter future execution.

## Alternatives and limits

Updates, management agents, device software and emergency support create or modify services. A valid signature does not establish an approved change, and absent signature data is not an invalid signature.

## Discriminating checks

Test an approved installer, direct configuration edit, changed executable at the same path and a registration never started. Keep service control-manager events separate from unrelated provider events sharing an event number. Reconfiguration requires service-owner authorization.

## Concrete observation contract

Security 4697 names installation fields such as `ServiceName`, `ServiceFileName`,
`ServiceStartType` and `ServiceAccount`; System's Service Control Manager 7045 uses a
separate schema. Check installed-service state under
`HKLM\SYSTEM\CurrentControlSet\Services\{service}` on a live system: `ImagePath`, start/account settings
and, when applicable, `Parameters\ServiceDll` describe different launch mechanisms.
Later edits do not imply a fresh installation event. In an offline SYSTEM hive, resolve
`Select\Current` to `ControlSetNNN`; do not presume the live `CurrentControlSet` alias
exists. The [Windows artifact reference](../../skills/soc-host-forensics/references/windows-artifacts.md)
describes that offline distinction.

Sysmon 13 `TargetObject`/`Details` can identify a selected registry change. Bind the
configured executable or DLL to a later process or module event using file identity,
service instance and time. Record ACLs for the file and directory independently; a
configuration string alone does not establish writable contents. Use actual signature
evidence for the loaded file, not version-information text or its parent's signer.
Approved upgrades and a changed path that was never used are negative controls.
