---
name: soc-email-forensics
description: Examine supplied email messages, mailbox exports and mail-security logs to assess phishing, delivery, sender authentication and attachment activity.
---

# Email evidence analysis

Use this skill for EML/MBOX, mail headers, or message-trace evidence. Live mailbox collection
uses the owner's existing scope and access tools; METIS does not provide a mail API connector.
An attached file goes to soc-malware-triage for static analysis after extraction.

Read [message analysis](references/message-analysis.md) for header trust, MIME and delivery.
For supplied EML/MBOX, the bounded [artifact reader](../../docs/artifact-tools.md) inventories
headers and MIME hashes. It does not verify sender authentication or extract runnable files.
Report the message identity privately, the trustworthy receiving boundary, observed delivery,
authentication results, URL/attachment evidence, and what user activity remains unproven.
Return the required finding fields from [the worker contract](../blue-owner/references/worker-contract.md).

Use the [mail evidence field map](references/message-analysis.md) to locate transport headers,
MIME-part coordinates, authentication properties and provider message/recipient join keys.
Choose a parser for the actual container and preserve separate message, delivery, part and click counts.
