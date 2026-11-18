# AWS audit investigation

## Define the population

Record account, region, service, time interval, trail/log configuration and event category.
Management and data events have different collection settings. A complete management trail
does not establish S3 object-level visibility. Event time and collection time must stay separate.

Build an actor record from userIdentity type, ARN/principal, account, access key and session
issuer. An assumed role can obscure the originating person; follow role-assumption context.
A source IP or userAgent alone cannot uniquely identify an operator.

Use eventName and eventSource for operation meaning, requestParameters for requested changes,
and error/response context for outcome. An absent error field is not a universal guarantee
that every higher-level action completed; some services report important outcome details
elsewhere. Review the relevant event type.

## Investigation paths

| Question | Evidence to relate |
| --- | --- |
| New or changed access | User/key creation, policy attachment/version changes, group membership and role trust changes |
| Assumed identity | Role assumption, session issuer, session name, source identity and later key/session activity |
| Logging impairment | Changes to trails, event selectors, logging state, destinations and retention |
| Persistence | New principals, credentials, trust relationships, workload identity and scheduled service configuration |
| Object access | Bucket/object-level records, requested operation, key, outcome and transfer context |
| Credential misuse | Unusual services/regions, source changes, privilege changes and baseline activity for the same identity |

A denied call may be normal automation or a configuration error. Enumeration claims require
patterns and context. A security-control change is worth review but may have an authorized
change record. Separate observed configuration from downstream effects.

## Counting and reconstruction

Deduplicate by stable event identity and document duplicate ingestion across destinations.
Use half-open phases and retain events with unknown critical fields as a separate population.
Do not aggregate anonymous reads with authenticated access or List with Get.

For S3 distinguish listing, metadata checks, reads, writes, policy and ACL effects. Keep
observed bucket/key fields separate from any constructed ARN. Correlate with additional
transfer evidence before stating an exfiltrated volume.

Compressed files need byte and expansion limits. Account for unreadable records and missing
partitions rather than silently accepting a smaller denominator. For an exact result use
[population controls](exact-populations.md), including a fresh replay of the selected evidence.

## Locate records and retain their coordinates

| Evidence location | Read these fields | Correlation and measurement | What must still be checked |
| --- | --- | --- | --- |
| Trail objects in S3: optional prefix, then `AWSLogs/account/CloudTrail/region/YYYY/MM/DD/`; organization trails add the organization ID before account | Gzip JSON `Records[]`; preserve object version/hash and array position | A filename contains delivery time; use each record's `eventTime` for the API timeline | Delivery directories are not event-time filters; include late deliveries and account/region coverage. Lake records have a different export path. [Delivery format](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-examples.html) |
| One CloudTrail record | `eventSource`, `eventName`, `eventCategory`, `eventType`, `awsRegion`, `eventTime`, `readOnly` | Match service and operation together; categories `Management`, `Data`, `NetworkActivity` are distinct | `readOnly` describes the API class; it is not an authorization decision or result. [Event contract](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference-record-contents.html) |
| Record identity and cross-account copies | `eventID`, `requestID`, `recipientAccountId`, `sharedEventID`, `addendum.originalEventID` | Deduplicate identical delivery copies by event identity; cross-account records may share `sharedEventID` while retaining different `eventID` values | Keep conflicting copies and addenda for resolution. A shared action is not one identical audit record. [Event contract](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference-record-contents.html) |
| `userIdentity` object | `type`, `accountId`, `principalId`, `arn`, `userName`, `accessKeyId` | Keep principal, credential identifier and account as separate columns; join credential activity only within its recorded validity/context | An access-key ID is a pivot, not a secret key or proof of a particular human. Missing identity is unknown, not anonymous. [Identity schema](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference-user-identity.html) |
| `userIdentity.sessionContext` | `sessionIssuer.arn`, `sessionIssuer.principalId`, `sourceIdentity`, `attributes.creationDate`, `attributes.mfaAuthenticated` | Relate role sessions to an observed STS issuance event, including returned assumed-role identity and credential ID when recorded | `sessionIssuer` identifies the issuing role/principal context, not automatically the person assuming it. `sourceIdentity` availability and trust depend on configuration; string `"false"` must not be treated as truthy. [Identity schema](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference-user-identity.html) |
| API result and client context | `errorCode`, `errorMessage`, `responseElements`, `sourceIPAddress`, `userAgent` | Classify the operation using its response contract; retain observed address separately from inferred endpoint ownership | Some services place errors inside `responseElements`; missing top-level errors alone are insufficient. AWS-internal/service addresses and editable user agents limit attribution. [Event contract](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference-record-contents.html) |
| Console sign-in record | `eventName=ConsoleLogin`, `responseElements.ConsoleLogin`, `additionalEventData.MFAUsed` | `Success` and `Failure` classify that sign-in; correlate later actions through validated session/credential evidence | API success and console success need different selectors. A successful login is not evidence that a later object transfer completed. [Console audit fields](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference-aws-console-sign-in-events.html) |

## S3 operation and resource worksheet

| Location / event family | Precise selectors | Join or count unit | Validation / result limit |
| --- | --- | --- | --- |
| S3 CloudTrail event | `eventSource=s3.amazonaws.com`; `requestParameters.bucketName`, `requestParameters.key`; `resources[].ARN`, `resources[].type` | Preserve bucket and full object key, and label an ARN computed from them as derived | Alias fields from an export require a documented mapping; an ARN prefix is not an observed exact object. Different S3 resource types require their own ARN grammar. [S3 event reference](https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging-s3-info.html) |
| Object reads and metadata | `GetObject`, `SelectObjectContent`, `HeadObject`; optional `additionalEventData.bytesTransferredOut` | Count requests separately from distinct object versions and transferred bytes | Head requests obtain metadata; byte fields may be absent. A successful request does not establish the recipient's complete local file. [S3 event reference](https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging-s3-info.html) |
| Listings, writes and controls | `ListObjects`, `ListObjectsV2`, `PutObject`, `CopyObject`, `DeleteObject`, bucket policy/ACL operations | Report each API family separately; multipart operations can describe parts of one object | A listing does not prove retrieval; a policy change does not prove later data access. Read the specific operation and audit selector coverage. [S3 logging coverage](https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging-s3-info.html) |
| Bucket versioning request | `eventName=PutBucketVersioning`; inspect the actual `requestParameters` object for `VersioningConfiguration.Status`, preserving its exported casing | API status values `Enabled` and `Suspended` describe the requested versioning state; correlate bucket/account and event time with result evidence and a later authorized configuration snapshot | The API parameter contract does not guarantee every audit exporter keeps the same JSON nesting. Request content alone proves neither acceptance nor the later state; an empty successful response is valid for this API. [Versioning API](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutBucketVersioning.html) |

Construct a credential timeline before clustering on source address or user agent. Define the time-gap
rule, show original event coordinates, and label continuity across different credentials as an inference.
Do not normalize away object-key case, slash distinctions, percent encodings or version identifiers.

## KMS signing audit coordinates

For `eventSource="kms.amazonaws.com"` with `eventName="Sign"` or `"Verify"`, the
published CloudTrail examples use string-valued `requestParameters.keyId`,
`requestParameters.messageType` and `requestParameters.signingAlgorithm`. Preserve
that lower-camel casing: the API's `KeyId`, `MessageType` and `SigningAlgorithm`
parameter names are a different schema. Keep region/account, `resources[].ARN`,
identity/session, event ID, request ID, event time and error fields together.

The examples have `responseElements=null` and do not carry the signed message or
signature. Do not infer a message-level Sign/Verify pair from the same key and nearby
times; use separately authorized application evidence for that relationship. One key can serve many requests. The examples also set
`readOnly=true`, so that flag alone does not mean reconnaissance. Local signature
verification outside KMS does not generate a KMS Verify API event.
See the primary [Sign audit example](https://docs.aws.amazon.com/kms/latest/developerguide/ct-sign.html),
[Verify audit example](https://docs.aws.amazon.com/kms/latest/developerguide/ct-verify.html)
and [Sign API contract](https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html).

## S3 response errors and request identifiers

When an acquired HTTP exchange contains an S3 XML error body, preserve
`Error/Code`, `Error/Message`, `Error/RequestId` and `Error/HostId` with the HTTP
status and request method. `Code` is a string identifier; keep diagnostic text
and opaque request IDs as strings. The corresponding HTTP response headers are
`x-amz-request-id` and `x-amz-id-2`. A Boto3 response exposes its request identifiers
under `ResponseMetadata.RequestId` and `ResponseMetadata.HostId`; its
`ResponseMetadata.HTTPStatusCode` is the status coordinate. These response
schemas differ from CloudTrail's `requestID` and `errorCode`. Preserve the original
casing and observation location when correlating them, together with bucket,
key/version, account/region and time. Request IDs identify a request, not a human.
[Request ID forms](https://docs.aws.amazon.com/AmazonS3/latest/developerguide/get-request-ids.html).

The S3 error contract assigns `NoSuchKey` to a specified key that the service
reports as nonexistent, with HTTP 404 and `SignatureDoesNotMatch` to a request-signature mismatch with HTTP
403. Keep the service error code separate from the status: many failures share a
status. For a general purpose bucket's `GetObject`, a nonexistent object can
produce 404 when the caller has `s3:ListBucket`, or 403 without that permission.
A 403 therefore does not by itself establish that an object exists. Do not infer
successful authentication or a particular principal merely from the absence of
`SignatureDoesNotMatch` or from a `NoSuchKey` string; validate response provenance
and use the operation's recorded identity/result context. Inspect retained
responses without issuing trial requests to infer access.
[S3 error definitions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_Error.html)
and [GetObject permissions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html).
