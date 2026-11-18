# Splunk investigation decisions

Use a read-capable authenticated search interface and a resource lease. Record deployment
version, app context, role and accessible indexes. This document describes query reasoning;
example field names are schema hints, not a validated query for the user's deployment.

## Establish scope and fields

Choose the specific index and sourcetype, explicit earliest/latest interval and entity scope.
Preview known records before aggregating. Verify whether relevant fields are indexed,
extracted at search time or introduced by an app. CIM fields describe a normalization contract;
inspect the add-on mapping and raw event before treating missing normalized values as absent.

Useful model families include Endpoint process/file/registry/service data, Authentication,
Network_Traffic and Web. Node names and available fields depend on the installed models.
Do not transfer a field from one source or acceleration pipeline without checking it.

## Acceleration is a coverage choice

The tstats command reads indexed structures and, when requested, accelerated data-model
summaries. It cannot arbitrarily substitute for search-time extraction on an unaccelerated
raw index. Confirm model/node, summary coverage and the fields used for grouping. Restricting
to summaries can omit the interval that has not been accelerated. Compare the relevant raw
population or a non-summary-only search before reporting a consequential total.
See the [tstats contract](https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/10.0/search-commands/tstats).

An index-wide coverage query is useful only within the permitted workload budget. Existing
onboarding/health metadata and a bounded known-host search may establish coverage more cheaply.
A pipe does not identify a search-head execution boundary; inspect the actual job cost.

## Choose an aggregation that preserves meaning

- Use count for the chosen row population and an explicit stable key when deduplicating events.
- Use distinct counting only for the entity being claimed; blank, aliased or recycled values
  need separate accounting. Preserve raw identifiers when presenting display labels.
- Compute first and last observations within the declared retention/window. Those extrema
  do not establish the lifetime of the behavior outside retained data.
- Bin times only after retaining required precision. Interval calculations need ordering
  within each entity pair and a stated treatment of duplicates and missing intervals.
- A set of values is not a chronological sequence. A bounded list may omit later values;
  inspect the actual function limits before relying on it for reconstruction.

Rarity, Office descendants, sensitive-process access, encoded commands, periodic flows and
new account/source combinations are investigation patterns. Each needs context and benign
comparators. A particular access mask alone does not prove credential dumping, and periodicity
alone does not identify malicious traffic. Keep original records behind every aggregation.

## Correlation and query limits

Join keys need identity and time semantics, not just matching text. A host/PID combination
can be reused; a session display name may not be unique. Where appropriate, aggregate a
bounded union of sources by a validated correlation key, while keeping source provenance.
That also avoids some subsearch limits, but it does not repair an invalid key.

Inspect job messages, completion state, event/result count and export pagination. General
subsearches, join subsearches, value lists and memory-heavy commands have distinct limits.
Do not apply one remembered default to every deployment. An explicitly unlimited sort can
still exceed memory or workload budgets. Check effective configuration with an authorized
operator rather than changing limits to make a query pass.

## Time, case and extraction

Retain _time as the event-time interpretation and _indextime as ingestion time. Large or
negative differences warrant source/clock/parser review. Time rendering follows user/query
context; do not append a UTC marker to local text. Misconfigured event-time extraction can
misplace a whole dataset and is not established merely by a cluster of identical timestamps.

Field-name case and value-comparison case have different rules. The search command, CASE()
terms and where/eval comparisons need their own verified semantics. Multivalue expansion can
multiply rows; count after expansion only when that expanded population is intended. A failed
regular-expression extraction yields missing evidence for that field, not a verified empty
value. Preserve unmatched records and validate patterns against representative raw samples.

## Reportable search receipt

Keep query text, absolute window, selected indexes, version/context, job identity, warnings,
pagination state, aggregation definitions, source hashes or private export references and
known-positive replay. Distinguish exact totals from partial retrieval. A negative finding
must name the covered entities, sensors and interval rather than declaring the whole estate
clean. Production rule edits remain outside search authority.

## Locate normalized and original evidence

| Source location | Fields worth projecting | Join / measure | Validation / limit |
| --- | --- | --- | --- |
| A selected raw `index` and `sourcetype` | `_raw`, `_time`, `_indextime`, `host`, `source`, `sourcetype`, `index` | `_time` is event epoch seconds, potentially fractional; `_indextime` is indexing epoch seconds | A displayed timezone and extraction configuration affect rendering. `host` can identify the log producer, not the affected destination. [Default fields](https://help.splunk.com/en/splunk-enterprise/manage-knowledge-objects/knowledge-management-manual/9.4/fields-and-field-extractions/use-default-fields) |
| CIM `Endpoint.Processes` | `Processes.dest`, `.user`, `.process_id`, `.process_guid`, `.parent_process_id`, `.parent_process_guid`, `.process_name`, `.process`, `.process_path` | Use process GUID and destination for lineage when populated; retain original provider ID/time | Search-time normalization is add-on dependent. A parent PID without creation context can join a different lifetime. [Endpoint CIM](https://help.splunk.com/en/data-management/common-information-model/6.0/data-models/endpoint) |
| CIM `Endpoint.Filesystem`, `.Registry`, `.Services` | `file_path`, `file_name`, `action`; `registry_path`, `registry_value_name`, `registry_value_data`; `service_name`, `service_path`, `start_mode` | Qualify these fields with the selected dataset name and keep `dest` plus event time | File/registry/service changes are distinct evidence classes; a stored service path alone is not an execution observation. [Endpoint CIM](https://help.splunk.com/en/data-management/common-information-model/6.0/data-models/endpoint) |
| CIM `Authentication` | `user`, `src`, `dest`, `action`, `app`, `signature_id`, `authentication_method` where available | Group authentication attempts by provider, user, endpoint and bounded interval | One transaction can produce multiple events; `success` reflects mapped provider semantics. [Authentication CIM](https://help.splunk.com/en/data-management/common-information-model/6.0/data-models/authentication) |
| CIM `Network_Traffic.All_Traffic` | `src_ip`, `dest_ip`, `src_port`, `dest_port`, `transport`, `action`, `bytes_in`, `bytes_out`, `packets` | Preserve sensor direction before deriving ingress/egress totals | Byte orientation follows the data model's mapping, not the field's colloquial meaning. Alert events and flows must not be added as sessions. [Network CIM](https://help.splunk.com/en/data-management/common-information-model/6.0/data-models/network-traffic) |
| CIM `Web` | `url`, `src`, `dest`, `http_method`, `status`, `http_user_agent`, `bytes` | Connect web transactions to flow/process evidence through identity, time and tuple where available | An HTTP status is not an application-effect guarantee; proxy mapping may replace the socket peer. [Web CIM](https://help.splunk.com/en/data-management/common-information-model/6.0/data-models/web) |
| Search job and final results | Job `sid`, `dispatchState`, `isDone`, `isFailed` when provided, `isFinalized`, `resultCount`, messages; result-page `offset` and `count` | Keep job identity across polling, final result retrieval and cancellation | Nonterminal states may omit final counts. A finalized job can be partial; inspect final diagnostics and all pages. See [verified adapter boundaries](../../../docs/siem-support.md) and [REST search endpoints](https://help.splunk.com/en/splunk-enterprise/rest-api-reference/10.0/search-endpoints/search-endpoint-descriptions) |

Treat `list()` and `values()` as distinct aggregations. A list can preserve input order subject to its
limit; a value set is deduplicated and not a timeline. Check the deployed aggregation and subsearch
settings rather than assigning a remembered common limit to all commands. [Multivalue statistics](https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/10.0/statistical-and-charting-functions/multivalue-stats-and-chart-functions)

Parent labels in the `Endpoint.Processes` dataset also include `Processes.parent_process_name`
and `Processes.parent_process`. Their availability depends on normalization. Retain parent
identity/lifetime and raw evidence before treating those labels as process lineage.
[Endpoint field definitions](https://help.splunk.com/en/data-management/common-information-model/6.0/data-models/endpoint).
