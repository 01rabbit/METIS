# Elastic and OpenSearch evidence queries

Establish the product, version, permissions and available APIs before choosing syntax.
Shared ancestry does not make the two products' query languages and plugins interchangeable.
This is a field/coverage guide, not a prevalidated connection to either product.

## Match the question to a query mode

| Need | Elastic option | Boundary to check |
| --- | --- | --- |
| Filter a Discover view | Kibana KQL or its Lucene mode | KQL filters; it is not Kusto and does not perform arbitrary aggregations |
| Pipeline transforms and grouped results | ES\|QL | Available functions, mappings, result ceilings and version |
| Sequence or event-oriented search | EQL where supported | Entity keys, ordering and temporal bounds |
| Explicit programmatic search/aggregation | Query DSL | Mapping, index selection, pagination and shard completion |
| OpenSearch investigation | Installed DQL, PPL, SQL or Query DSL facilities | Confirm the selected plugin and product's own syntax |

Avoid translating by renaming keywords alone. Inspect a known source event and the mapping.
A keyword field and an analyzed text field can match differently. Nested data, arrays,
case handling and missing values can also change a predicate's meaning.

## Select data deliberately

Identify the requested tenant, namespace and integration datasets before using a wildcard.
Raw telemetry, derived detections and alert documents are separate populations; searching
an alert index does not establish that all underlying events were available. Confirm any
hidden or rolled-over index needed for the period is in scope and accessible.

ECS provides common roles such as host/user identity, process entity, source/destination,
network direction, file path/hash, event action and outcome. The integration decides which
fields exist and how they were populated. related.* fields can aid discovery when available,
but an empty related field does not prove the value is absent elsewhere in the document.
Retain original values when checking a normalization discrepancy.

## Separate clocks and identities

Compare the source event time with agent creation and ingestion timestamps. These can differ
because of buffering, delayed collection or bad clocks. Confirm the time picker and query
field both cover the intended event interval. Ingestion-window searches answer a different
question from event-window searches unless the lag is accounted for.

Prefer process entity identity over a reused PID. Correlate network directions with sensor
placement instead of assuming an originator is internal. A log's asserted client header and
its socket peer have different trust. Repeated ingestion can create distinct documents for
one semantic event, so document _id is not always an event deduplication key.

## Do not confuse an output cap with a population

ES|QL's output row limits apply to returned rows; an aggregation can process more documents
than it returns groups. Verify effective limits and expected group cardinality. DISTINCT
operations may be approximate. A capped rare-values listing cannot support a claim that all
rare entities were considered. Review the deployed version's
[ES|QL limits](https://www.elastic.co/docs/reference/query-languages/esql/limitations)
when choosing a query form.

For search results, inspect total-hit relation: a lower-bound total is different from an
exact total. It does not by itself mean the documents in the current page were truncated.
Check timeouts, failed shards, partial responses and any warning attached to the operation.
Search pagination needs stable ordering and a supported consistency mechanism for a changing
index. Keep the point-in-time/context identity when the backend uses one.

Top-terms aggregations return selected buckets and can omit low-frequency entities. Inspect
bucket accuracy/other-count metadata where applicable. Use a supported complete bucket
pagination mechanism for an exhaustive group list. Exported rows, hit totals and group totals
are different counts; verify each against the actual question.

## Validate an investigative pattern

Confirm a known positive, a plausible benign comparator, a missing-field record and a
boundary-time case. Record source fields and the transformed result. A regular-expression or
base64 extraction does not validate the meaning or character encoding of the decoded value.
Decode privately without evaluating code. For beaconing or novelty, specify the observed
window, intervals, gaps and baseline; regular health checks and newly onboarded hosts are
common alternative explanations.

Return the product/dialect, exact index scope and interval, query, mapping assumptions,
completeness diagnostics and private evidence coordinates. Do not store credentials in URLs,
command arguments or exported reports. Configuration changes and deployed detection edits
require separate scoped authority.

## Field map for the first bounded sample

| Document location | Fields / exact coordinate | Correlation or units | Validation / limit |
| --- | --- | --- | --- |
| Event document in a selected data stream/index | `@timestamp`, `event.created`, `event.ingested`, `event.dataset`, `event.kind`, `event.action`, `event.code`, `event.outcome`, `event.original` | Separate source clock, first collector read and central arrival; event duration is `event.duration` in nanoseconds | `event.action` names the activity, `event.code` retains the provider code, and `event.outcome` uses the producer perspective. `event.original` may be retrievable but unindexed. [ECS event fields](https://www.elastic.co/docs/reference/ecs/ecs-event) |
| Process documents | `process.entity_id`, `process.pid`, `process.start`, `process.parent.entity_id`, `process.parent.name`, `process.parent.executable`, `process.executable`, `process.command_line`, `host.id`, `user.id` | Prefer host + entity identity for lineage; if absent, qualify PID with process start and host | An executable path does not prove successful completion. Integration population and entity semantics require sample validation. [ECS process fields](https://www.elastic.co/docs/reference/ecs/ecs-process) |
| Network documents | `source.ip`, `source.port`, `destination.ip`, `destination.port`, `network.transport`, `network.protocol`, `network.direction`, `network.community_id` | Tuple joins need sensor, time and NAT context; Community ID needs compatible algorithm/seed | `source`/`destination` are event roles, not a universal internal/external assignment. [ECS network fields](https://www.elastic.co/docs/reference/ecs/ecs-network) |
| File, DNS and HTTP evidence | `file.path`, `file.hash.sha256`; `dns.question.name`, `dns.question.type`, `dns.answers.data`; `url.full`, `http.request.method`, `http.response.status_code` | Keep each dataset's event ID and parent process/flow key before grouping by file, domain or URL | Missing fields may indicate disabled collection. Arrays and nested mappings require the proper query form. [ECS field reference](https://www.elastic.co/docs/reference/ecs/ecs-field-reference) |
| Winlogbeat / Windows integration payload | `winlog.event_id`, `winlog.record_id`, `winlog.provider_name`, `winlog.channel`, `winlog.computer_name`, `winlog.event_data.*`; optional `winlog.user_data` | Use provider + channel with event ID; qualify record ID by host/log lifetime. Event-specific names retain their provider casing | These are integration fields, not interchangeable with Wazuh `data.win.*`. A collector may wrap them under `event`; confirm a bounded raw sample before selecting a path. [Windows integration](https://www.elastic.co/docs/reference/integrations/windows) |
| Search response | `hits.total.value`, `hits.total.relation`, `hits.hits[]._index`, `._id`, `._source`, `.sort`, `_shards`, `timed_out` | `relation=eq` is exact under the response contract; `gte` is a lower bound; retain sort values for pagination | Exact hit count does not imply all rows were retrieved. Require successful shards and a stable search context for exhaustive retrieval. [Search API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-search) |
| Bucket response | `doc_count`, `sum_other_doc_count`, `doc_count_error_upper_bound`, composite `after_key` where applicable | Separate document counts, selected buckets and complete group enumeration | A terms top list can omit groups. Continue composite pagination using the returned key when exhaustive enumeration is needed. [Terms](https://www.elastic.co/docs/reference/aggregations/search-aggregations-bucket-terms-aggregation), [composite](https://www.elastic.co/docs/reference/aggregations/search-aggregations-bucket-composite-aggregation) |

A common data-stream pattern is `type-dataset-namespace`, such as logs for one integration and
namespace; inspect `data_stream.type`, `data_stream.dataset` and `data_stream.namespace` rather than
assuming a wildcard covers every tenant. Alert indexes and backing indexes remain different evidence
populations. [Data-stream naming](https://www.elastic.co/docs/reference/fleet/data-streams)

## Additional ECS selectors and collector aliases

Inspect the mapping and one source document before using these selectors. A schema field can
be defined correctly yet remain unpopulated by the installed integration.

| Evidence role | Exact ECS fields and types | Interpretation and correlation |
| --- | --- | --- |
| Host/account labels | `host.name`, `host.hostname`, `host.os.family`, `agent.id`; `user.name`, `user.domain`, `user.target.name` are keyword fields | Preserve host/user IDs for joins. Names, target accounts and collection agents describe different entities; an agent ID is not necessarily the affected host. [Host fields](https://www.elastic.co/docs/reference/ecs/ecs-host), [user fields](https://www.elastic.co/docs/reference/ecs/ecs-user) |
| Process context | `process.name` is keyword; `process.parent.command_line` inherits the command-line wildcard type; `process.hash.sha256` is keyword | The parent's command line concerns its own process lifetime. A name or binary digest is not a process-instance identifier; keep the existing entity/host/time keys. [Process fields](https://www.elastic.co/docs/reference/ecs/ecs-process) |
| File naming | `file.name`, `file.extension` are keyword fields | `file.name` omits the directory. The extension contains the final suffix without a leading dot; it does not verify the content format. [File fields](https://www.elastic.co/docs/reference/ecs/ecs-file) |
| Code signature | `process.code_signature.subject_name` is keyword; `process.code_signature.trusted` and `process.code_signature.valid` are booleans | Certificate-chain trust and verification against binary content are separate results. Missing checks remain unknown; a trusted signer does not establish benign behavior. The field set also appears under `file.code_signature`. [Signature schema](https://www.elastic.co/docs/reference/ecs/ecs-code_signature) |
| TLS negotiation | `tls.client.server_name`, `tls.client.ja3`, `tls.server.ja3s`, `tls.version`, `tls.version_protocol` are keyword fields | SNI is a client-supplied name; JA3 and JA3S fingerprint different handshake sides. The version contains its numeric portion as text, while the protocol field identifies TLS/SSL. None identifies a person. [TLS schema](https://www.elastic.co/docs/reference/ecs/ecs-tls) |
| Certificate subject | `tls.server.subject`; `tls.server.x509.subject.common_name` | Preserve full distinguished name separately from parsed common names. X.509 common names are keyword arrays; compare certificate identity and validity, not just display text. [TLS schema](https://www.elastic.co/docs/reference/ecs/ecs-tls), [X.509 schema](https://www.elastic.co/docs/reference/ecs/ecs-x509) |


Classification fields `event.category` and `event.type` are keyword arrays. `rule.name`,
`threat.technique.id` and `threat.tactic.name` describe detection/taxonomy metadata, not proof
that every stage of a technique occurred. Preserve source rule identity and raw observations.
[Event categories](https://www.elastic.co/docs/reference/ecs/ecs-event),
[rule fields](https://www.elastic.co/docs/reference/ecs/ecs-rule),
[threat fields](https://www.elastic.co/docs/reference/ecs/ecs-threat).
For web records, `url.domain` is a keyword host label, while `url.original` preserves the
original URL or URI representation. `user_agent.original` retains the observed agent string;
parsing it does not authenticate the client software.
[URL fields](https://www.elastic.co/docs/reference/ecs/ecs-url),
[user-agent fields](https://www.elastic.co/docs/reference/ecs/ecs-user_agent).

Collector names such as `tls.ja3`, `tls.sni`, `tls.cert_subject`, `dns.query`, `http.uri` and
`http.stat_code` are not interchangeable ECS selectors. Compare actual records with ECS
`tls.client.ja3`, `tls.client.server_name`, `tls.server.subject`, `dns.question.name`,
`url.original`/`url.path`, and `http.response.status_code` according to each value's role.
A URI may omit scheme/authority and must not be silently promoted to `url.full`.
Suricata EVE instead uses `tls.ja3.hash`, `tls.sni`, `tls.subject`, `http.url` and `http.status`;
Zeek uses its per-log fields. Keep a reviewed source-to-index mapping, including type and
transformation, rather than assuming a name substitution is lossless.

For discovery, ECS `related.ip`, `related.hosts`, `related.user` and `related.hash` collect
pivot values; they do not identify the role in which a value occurred. Reopen the concrete
source/destination, actor/target or file field before attribution.
[ECS related fields](https://www.elastic.co/docs/reference/ecs/ecs-related).
