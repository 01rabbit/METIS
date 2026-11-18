---
name: soc-host-forensics
description: Interpret supplied host evidence such as event files, registry, filesystem records, execution artifacts, Unix logs and memory images into a bounded forensic timeline.
---

# Offline host investigation

Begin with artifact identity and the question being answered. Preserve originals, hash inputs,
and inspect acquisition scope before opening a parser. This skill guides interpretation;
external binary-format and memory tools must be available and validated for the artifact.
Live collection belongs with [remote triage](../soc-remote-triage/SKILL.md).
The [artifact reader](../../docs/artifact-tools.md) reads UTF-8 Windows Event XML exports
with original timestamp text. It does not decode binary EVTX or memory images.

Load only the relevant reference:

- [Cross-artifact reasoning](references/analyst-handbook.md): evidence selection, timelines,
  identity joins, configuration review and competing explanations.
- [Windows](references/windows-artifacts.md): event, registry and execution traces.
- [Linux](references/linux-artifacts.md): authentication, persistence and filesystem context.
- [Memory](references/memory-analysis.md): image/symbol validation and supported plugin work.
- [Parser integrity](references/parser-integrity.md): partial reads, exact timestamps,
  replay, API traces and extraction limits.

Return a sequence of supported events with artifact coordinates, host/session identity,
original and normalized time, precision, interpretation and uncertainty. Preserve conflicts
between sources. A record showing presence or configuration does not necessarily show use;
a successful parser process does not necessarily establish complete coverage.
