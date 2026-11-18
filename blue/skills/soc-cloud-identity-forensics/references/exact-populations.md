# Exact cloud populations and object access

Use bounded phase intervals [start, end), normalized UTC and an explicit inclusion rule.
State event source, category, identity type, authentication state and outcome before counting.
Separate anonymous access, authenticated access and access-key activity; separate management
and data events. CloudTrail eventID is the normal deduplication coordinate, not timestamp alone.
Different IDs at the same time can be distinct events.

Check coverage by region, account, trail configuration, time and service. Missing object-level
data events cannot support “no object access.” Unknown relevant fields, duplicate JSON keys,
malformed records, decompression or record caps make exact totals incomplete. Preserve gzip
input identity and bound both compressed and expanded bytes.

Reconstruct S3 activity by operation: List, Head, Get, Put, policy and ACL changes have different
effects. Cluster with principal/access key, bucket, IP and user agent plus an explicit bounded
idle gap. A user agent is spoofable and does not independently identify an actor. NAT and
shared credentials can merge people; credential changes can split one actor.

An ARN synthesized from bucket and object key is derived, not observed. Keep original fields
and the synthesis rule. Evidence of an object request is not automatically proof of successful
transfer or complete exfiltration; inspect outcome and response-size coverage.

For a consequential count, replay from the original bytes using the same field selectors,
phase boundaries, deduplication and success criteria. Report included, excluded, duplicate,
malformed and unknown populations separately. A query's displayed row count is not a complete
population unless pagination, truncation and retained source coverage are established.

## Concrete count contract

| Stage / source coordinate | Retain | Required decision | Failure boundary |
| --- | --- | --- | --- |
| Input file and `Records[]` entry | Source hash, entry ordinal, original `eventTime` | Validate a timezone-bearing timestamp and retain raw precision; apply `[start,end)` after UTC normalization | An invalid timestamp may belong in scope and cannot be silently excluded |
| Category and identity | `eventCategory`, `userIdentity.type`, `accessKeyId`, `principalId`, `accountId` | Freeze categories and allowed identity/credential population before counting | Missing identity is not equivalent to public/anonymous access; known exclusions and unresolved candidates stay separate |
| Outcome selector | `eventName`, `eventSource`, `errorCode`, `errorMessage`, operation-specific `responseElements` | Record the service-specific rule and classify success, failure and unknown separately | A generic parser's no-error fallback is not a universal provider guarantee |
| Event deduplication | `eventID`, recipient account, original record hash; `sharedEventID` for related account records | Report delivery copies, distinct records and related cross-account actions as separate totals | Equal IDs with conflicting content require review; missing IDs cannot become fabricated unique IDs |
| Grouped object activity | Bucket + full key + version when present, principal/credential, time bound | Distinguish request count, object count, session estimate and bytes | A keyword classifier can hit several families in one record; its feature count is not an exact API count |

The [CloudTrail event contract](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference-record-contents.html)
defines event identity and optional response fields. Attach the chosen selectors to the result;
provider semantics take priority over a convenient parser fallback. If a relevant candidate remains
unclassified, publish the confirmed subtotal plus unresolved candidates, not an exact grand total.
