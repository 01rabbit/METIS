# Cloud workload and cluster audit

## Google Cloud

Establish project, organization, service, log category and collection scope. Admin Activity,
Data Access, System Event and Policy Denied records answer different questions; do not
assume every data operation is enabled or retained.

Inspect the principal, delegated/service-account context, method, resource, permission decision
and status. A method name without outcome does not prove a successful change. A service
account can be used by several workloads; relate workload identity and credential issuance
where available.

Prioritize IAM/binding changes, service-account credentials, logging changes, unexpected
resource creation and access to sensitive storage. Preserve resource hierarchy and old/new
policy context. Compare against authorized deployments and administrative automation.

## Kubernetes API audit

Document cluster identity, audit policy, stage coverage and retention. Match auditID across
stages before counting requests. RequestReceived and ResponseComplete for one operation
are not two independent actions; not every policy captures a request or response body.

Use verb, requestURI, objectRef, user/groups, impersonation, source addresses, user agent and
responseStatus together. Distinguish pod creation, exec/attach, secret access, role binding,
service-account-token actions and admission/controller follow-up. Authentication as a
service account does not identify the human who initiated it.

Review pod specifications for privileged mode, host namespaces, sensitive mounts, capabilities
and image provenance. Those settings describe exposure, not proof of escape. An API response
needs pod/runtime or node evidence before claiming a container actually executed.

## Beyond the control plane

API audit misses direct activity inside a container or on a node. Combine runtime/eBPF/EDR
events, container stdout, scheduler events, image digests, writable-layer evidence and cloud
control-plane logs as appropriate. Include network-policy and admission decisions when
assessing whether an attempted action was blocked.

State which cluster/workload versions and schemas were used. Keep credentials from manifests,
Secrets and environment exports private. Recommend access revocation or workload changes
separately from performing them.

## GCP audit fields and collection scope

| Where to look | Concrete fields | Correlation / units | Validation and limit |
| --- | --- | --- | --- |
| Cloud Logging `LogEntry` export | `logName`, `insertId`, `timestamp`, `receiveTimestamp`, `resource.type`, `resource.labels`, `protoPayload` | Keep project/resource labels with event identity; compare event and receipt times in UTC | A saved sink may exclude records. A collector's receive time does not replace an absent source timestamp. [LogEntry schema](https://cloud.google.com/logging/docs/reference/v2/rest/v2/LogEntry) |
| Audit payload, type `type.googleapis.com/google.cloud.audit.AuditLog` | `serviceName`, `methodName`, `resourceName`, `authenticationInfo.principalEmail`, `authenticationInfo.principalSubject`, `serviceAccountDelegationInfo` within `authenticationInfo` | Track asserted principal and delegation chain separately; correlate service, resource and request context | An impersonated service account does not by itself identify the initiating human. [AuditLog schema](https://cloud.google.com/logging/docs/reference/audit/auditlog/rest/Shared.Types/AuditLog) |
| Audit request and result | `requestMetadata.callerIp`, `requestMetadata.callerSuppliedUserAgent`, `authorizationInfo[].resource`, `.permission`, `.granted`, `status.code`, `status.message` | Each authorization entry concerns a resource/permission pair; `status.code=0` is the API OK code | Authorization and completed operation differ. Missing `status` needs the service's success/omission contract; keyword occurrences do not classify a complete event. [AuditLog schema](https://cloud.google.com/logging/docs/reference/audit/auditlog/rest/Shared.Types/AuditLog) |
| Audit stream selection | Log IDs `cloudaudit.googleapis.com/activity`, `/data_access`, `/system_event`, `/policy`; `/` is encoded as `%2F` inside `logName` | Compare collection and retention separately for each category | Data Access commonly requires enabling; BigQuery has distinct defaults. Admin Activity coverage does not establish object-read coverage. [Collection defaults](https://cloud.google.com/logging/docs/audit) |

## Kubernetes API audit and workload joins

| Location / object | Concrete fields | How to correlate | Validation / result limit |
| --- | --- | --- | --- |
| API-server audit backend, file selected by `--audit-log-path` or configured webhook | `apiVersion=audit.k8s.io/v1`, `kind=Event`, `auditID`, `stage`, `level`, `requestReceivedTimestamp`, `stageTimestamp` | Stages `RequestReceived`, `ResponseStarted`, `ResponseComplete`, `Panic` can share `auditID`; count requests separately from stage records | `None`, `Metadata`, `Request`, `RequestResponse` levels and policy omissions control what is retained. A path such as `/var/log/kubernetes/audit.log` is not universal. [Audit Event schema](https://kubernetes.io/docs/reference/config-api/apiserver-audit.v1/) |
| Same API audit event | `verb`, `requestURI`, `user.username`, `user.uid`, `user.groups`, `impersonatedUser`, `sourceIPs`, `userAgent` | Record authenticated and impersonated identities separately; relate to the same `auditID` | `sourceIPs` can include proxy-asserted addresses. A service-account string identifies an account in a namespace, not a person. [Auditing contract](https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/) |
| Audit target and response | `objectRef.resource`, `.subresource`, `.namespace`, `.name`, `.uid`; `responseStatus.code`; optional `requestObject`, `responseObject` | A request for `pods/exec`, `pods/portforward`, a Secret or a RoleBinding requires its specific target and response context | A successful API response does not prove a shell command ran, a secret was read by a human, or a pod became reachable. Metadata may contain object names without bodies. [Audit Event schema](https://kubernetes.io/docs/reference/config-api/apiserver-audit.v1/) |
| Workload manifest | `metadata.namespace`, `metadata.name`, `metadata.uid`, `metadata.ownerReferences[]`, `spec.template.metadata.labels`, pod `metadata.labels` | Follow owner UID and namespace; compare a Service's `spec.selector` against pod labels | A manifest is desired configuration. Omitted namespace needs the export/apply context; do not silently assume `default` for arbitrary offline files. [Service selectors](https://kubernetes.io/docs/concepts/services-networking/service/) |
| Service and EndpointSlice snapshots | Service `spec.type`, `spec.ports[].port`, `.targetPort`, `.nodePort`; EndpointSlice `metadata.labels["kubernetes.io/service-name"]`, `endpoints[].addresses`, `.conditions.ready`, `.targetRef` | Service selector matches within a namespace; inspect resolved endpoint addresses and named-port mapping at the observation time | Counting matching workload templates is not counting ready serving pods. NodePort/LoadBalancer configuration alone does not prove external reachability. [Service semantics](https://kubernetes.io/docs/concepts/services-networking/service/) |
| Node container output | Typical Linux `/var/log/pods/` and links under `/var/log/containers/`; stream and container/runtime identity | Associate namespace, pod UID, container name, restart and timestamps; retain symlink target and rotation coverage | Container stdout/stderr is separate from API audit. Paths, rotation and collection can be customized. [Logging architecture](https://kubernetes.io/docs/concepts/cluster-administration/logging/) |

ConfigMap `data`/`binaryData` and Secret `data`/`stringData` are different fields.
Counting keys identifies configuration size, not secret values or successful use. Preserve only
needed metadata in shared notes and keep authorized sensitive evidence in the private case store.
