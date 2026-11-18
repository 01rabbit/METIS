---
name: ctf-blue-solve
description: Resolve scored defensive investigation questions using supplied forensic evidence, exact answer formatting, and a shared attempt budget.
---

# Defensive exercise answers

Use this entry when success is an evidence-backed answer in a specified field. Ordinary
incident conclusions belong in the SOC reporting workflow. Select the artifact specialist
before interpreting the answer; the exercise format does not change evidence quality.

Read the [exercise handbook](references/analyst-handbook.md) for ambiguous wording,
representations, rejected answers, visual evidence or instance-specific submissions.
The owner retains control of the question service and its finite attempts.

For each question return the requested value, the artifact coordinate that supports it,
the relevant source digest, any necessary transformation, and unresolved uncertainty.
An answer-shaped example is never an answer source. A worker's typed value must agree with
its cited evidence before the owner uses it. Missing evidence warrants an unresolved result.
Use only available approved parsers or native tools; do not imply this skill contains them.

Use [evidence locators](../soc-triage/references/evidence-locators.md) to bind the requested value to a record and exact field; keep original source paths separate from local acquisition names.
