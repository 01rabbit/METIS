# Report a hunt with explicit evidence and sharing boundaries

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Can a recipient act on the findings while understanding their confidence, coverage and permitted redistribution?

## Evidence to request

Hypothesis versions, query/result references, coverage measurements, event-level findings, alternative explanations, owners and sharing instructions.

## Reasoning procedure

- Lead with the decision the evidence supports, then separate observed facts from interpretation and outstanding questions.
- Describe searched assets, time ranges, event categories and collection gaps. A report cannot generalize beyond its measured population.
- For each proposed detection, name its required data, expected benign cases and unvalidated branches. Recommendations need an owner and an acceptance test.
- Apply the applicable TLP label and originator restrictions to the specific information being shared. TLP concerns dissemination; it is not a substitute for legal authority, data classification or redaction.
- Keep secrets and raw session identifiers out of the report; provide controlled evidence references for authorized reviewers.

## Sharing decision aid

Apply the originator's restrictions in addition to this [TLP 2.0 reference](https://www.first.org/tlp/):

| Marking | Recipient boundary to check |
| --- | --- |
| TLP:RED | Only the individual recipients; no onward disclosure. |
| TLP:AMBER | Need-to-know recipients in the organization and its clients. |
| TLP:AMBER+STRICT | Need-to-know recipients inside the organization. |
| TLP:GREEN | The defined community; exclude public channels. |
| TLP:CLEAR | TLP itself adds no dissemination limit; other rights and obligations still apply. |

Ask the originator before exceeding a stated boundary. A TLP label never supplies the authorization for METIS to send a message.

## Alternatives and limits

A short executive summary may omit detail for readability but must not erase material uncertainty. Several supporting indicators can still arise from one underlying source and are not independent corroboration.

## Discriminating checks

Have a reviewer trace every consequential statement to evidence and identify who may receive the report. Test a report with a collection gap and an unvalidated rule. Sending or publishing the report requires the user-authorized communication scope.

## Concrete observation contract

The report's result table should name the evidence locator, event-time interval/timezone,
query or method version, entity, observed fact, alternative and confidence. Add eligible
assets, reporting assets, searched sources, excluded sources and any approximate or
truncated counts. A numerator without its coverage denominator is not a prevalence or
quality measure.

Tie each recommendation to the finding it changes and a responsible owner. Record the
distribution audience and chosen TLP marking separately from incident severity; neither
creates permission to share credentials or personal data. Refer to private case evidence
using stable locators rather than reproducing raw artifacts in the generic report. An
unresolved collection gap remains a result to communicate, even when the hunt task itself
has completed.
