---
name: evidence-question-answering
description: Answer individual or batched defensive investigation questions from supplied evidence with calibrated confidence and citations.
---

# Evidence question answering

Classify a single question, batch or regression evaluation. Route host, network, cloud,
identity, email, browser database, memory, archive, document and binary artifacts to the
corresponding SOC skill. Use `metis blue run` with a bounded plan for independent questions.

Retrieve from the supplied evidence and reviewed knowledge only. Exclude answer catalogs and
expected outputs from independent analysis. In regression mode keep expected answers in the
scorer, separate from model input; do not report a regression lookup as a fresh investigation.

Return the smallest answer that satisfies the question, confidence, artifact/line/event citations,
and limitations. If evidence is insufficient, identify the missing artifact rather than inventing
a flag. Restrict raw access to the user's provided scope. Use the same timestamp and count model
across a batch; deduplicate repeated records using documented identifiers.

The shared workflow applies in either supported agent runtime. Check that the current
provider can access the required evidence tools; the generic runner does not replace every
specialist parser. Output-format compliance and analytical correctness are evaluated separately.

For each answer use [evidence locators](../soc-triage/references/evidence-locators.md): exact input identity, record coordinate, field name, raw value and transformation. The cited field must answer the requested entity, not a nearby display label.
