# Collector envelopes and container observability

This is a map for inspecting available logs and UI exports. It does not add live product APIs.
Pinned schema links below identify the reviewed revision; compare the deployed exporter version.
Use a bounded known event to confirm the collector's wrapper, field types, clock and retention
before a broad search. Preserve the original event coordinate alongside the normalized field.

| Product / evidence location | Concrete fields or navigation | Correlation and units | Validation / limit |
| --- | --- | --- | --- |
| Datadog Log Explorer, selected log's JSON/attributes panel | Reserved `message`, `host`, `service`, `status`; custom attribute searches use `@field` | Inspect whether a Windows payload is at `winlog.event_id`, nested under `event.winlog.event_id`, or held as serialized text | Those Windows paths are collector possibilities, not guaranteed Datadog fields. Record the observed JSON pointer and type; creating/remapping facets is a write. [Attributes](https://docs.datadoghq.com/logs/log_configuration/attributes_naming_convention/), [search syntax](https://docs.datadoghq.com/logs/explorer/search_syntax/) |
| Graylog search result, expanded message and selected stream/index set | `timestamp`, `source`, `message`, optional `full_message`; extractor/pipeline-defined fields | GELF transport uses `host`, `short_message`, optional `full_message`, fractional Unix `timestamp`; verify how these become indexed message fields | A stream filter, pipeline rename or flattened JSON envelope can hide the expected source key. Do not reuse another installation's field path without a sample. [GELF](https://go2docs.graylog.org/current/getting_in_log_data/gelf_format.html), [search fields](https://go2docs.graylog.org/current/making_sense_of_your_log_data/search_syntax_reference.htm) |
| Tetragon JSON export or exporter container stdout | Envelope `time`, `node_name`, `cluster_name`; event objects `process_exec`, `process_exit`, `process_kprobe`; optional `aggregation_info` | Preserve event type and node; `aggregation_info.count` counts grouped events and `time` marks the first observation in that group | Export container names and paths come from the deployed DaemonSet/configuration; `export-stdout` is a deployment convention, not a universal path. [Export envelope](https://raw.githubusercontent.com/cilium/tetragon/666efe6f91e3605ad58683ad226d759d9cf970ca/api/v1/tetragon/events.proto) |
| Tetragon process object | `exec_id`, `parent_exec_id`, `pid`, `start_time`, `binary`, `arguments`, `cwd`, `uid`, `auid`, `pod.namespace`, `pod.name`, `pod.uid`, `pod.container.id` | Prefer exec IDs for parent/child continuity; retain host PID and container identity separately | PID reuse, missing parent metadata, truncated arguments and startup snapshots constrain execution claims. Optional credential/namespace fields require collection support. [Process schema](https://raw.githubusercontent.com/cilium/tetragon/666efe6f91e3605ad58683ad226d759d9cf970ca/api/v1/tetragon/tetragon.proto) |
| Hubble flow export | Protobuf fields `time`, `uuid`, `node_name`, `verdict`, `IP`, `l4`, `source`, `destination`, `traffic_direction`, `is_reply`, `l7` | Endpoint `source.namespace`, `.pod_name` and destination equivalents identify context; `l7.latency_ns` is nanoseconds; correlate tuple + time + node/pod identity | Proto JSON may use camelCase names; inspect actual serialization. Missing `is_reply` is unknown. Flow metrics are aggregates, not equivalent to full flow records or packets. [Flow schema](https://raw.githubusercontent.com/cilium/cilium/d66929b1dfc702fc6dafda7dec0afee0f5c57def/api/v1/flow/flow.proto) |
| Arkime session search and session detail | Search expressions `ip.src`, `ip.dst`, `port.src`, `port.dst`, `packets.src`, `packets.dst`, `databytes.src`, `databytes.dst`, `communityId` | Keep session identity and node before requesting an authorized packet export; compare tuple/time with Zeek and EVE | Search expressions can differ from stored database field names; packet retention may expire before session metadata. [Expression definitions](https://raw.githubusercontent.com/arkime/arkime/229ef55fc703c483675aa75e05026988ba55f8ed/capture/field.c) |
| Arkime stored session/export metadata | `firstPacket`, `lastPacket`, `length`, `node`, `packetPos`, `fileId` when available in that version/export | Stored first/last times and length are milliseconds; node/file/position bind packets to capture storage | An aggregate session may be split across files. Never translate a session count directly into packet or HTTP-request count. [Session serialization](https://raw.githubusercontent.com/arkime/arkime/229ef55fc703c483675aa75e05026988ba55f8ed/capture/db.c) |

Match Kubernetes context through cluster, namespace, pod UID, container identity and node at the
relevant time. Similar pod names alone are insufficient after rescheduling. Compare collection status
and event loss before calling a process or network population complete; see [Kubernetes evidence](../../soc-cloud-identity-forensics/references/gcp-kubernetes.md).

## Saved Ray job observations

For an acquired Ray export, record the Ray version, producing model, cluster identity,
collection time and JSON/line coordinates. The following describes Ray 2.58.0
`JobDetails`, whose API stability is beta; a collector may add a separate envelope.

| Native member | Type and interpretation |
| --- | --- |
| `type`, `job_id`, `submission_id` | `type` is the string enum `SUBMISSION` or `DRIVER`; both IDs are optional strings in separate namespaces. Scope joins to the same cluster and documented model; equal-looking IDs do not establish equivalence |
| `status`, `entrypoint` | `status` is a string enum: `PENDING`, `RUNNING`, `STOPPED`, `SUCCEEDED` or `FAILED`. `entrypoint` is a string describing the job's configured entry point, not proof of every operation it performed |
| `start_time`, `end_time` | Optional integers in Unix epoch milliseconds. End time concerns reaching a terminal state; absence is not zero and collection time remains separate |
| `driver_info` | Optional last-driver object; its `id`, `node_ip_address` and `pid` are strings. Preserve the driver/job relationship instead of treating the rendered PID as a globally unique process |

The separate `JobLogsResponse` exposes `logs` as a string; the default driver-log
basename is `job-driver-{submission_id}.log`. Resolve its acquired session/log directory
from provenance rather than assuming a universal absolute path. The older submission
response's deprecated `job_id` alias must not be confused with `JobDetails.job_id`.
Logs can contain sensitive job output and do not authenticate a human operator.
METIS has no dedicated Ray reader; these are selectors for preserved responses and logs,
not instructions to submit jobs or contact a service.
[Job model](https://raw.githubusercontent.com/ray-project/ray/ray-2.58.0/python/ray/dashboard/modules/job/pydantic_models.py)
and [status, response and log definitions](https://raw.githubusercontent.com/ray-project/ray/ray-2.58.0/python/ray/dashboard/modules/job/common.py).

## marimo's internal log and separately captured console output

In marimo 0.18.0, the internal file handler uses `marimo.log` beneath the directory
resolved by `marimo_log_dir()`. A nonblank `XDG_CACHE_HOME` selects the cache root;
otherwise the normal home-based candidate is `~/.cache/marimo/logs/marimo.log`.
Resolve the actual process user and environment; the helper can fall back to `/tmp`
when a home directory is unavailable. Preserve acquired paths, hashes and rotations.
[Versioned directory resolver](https://github.com/marimo-team/marimo/blob/0.18.0/marimo/_utils/xdg.py),
[file-handler selection](https://github.com/marimo-team/marimo/blob/0.18.0/marimo/_loggers.py).

The file formatter renders `asctime` as `%Y-%m-%d %H:%M:%S`, with level, logger name,
source line and message. Its unmodified Python formatter uses local time; retain the
runtime version, effective zone and any formatter override before normalizing it.
The rendered clock has no explicit offset. This is application logging, not a complete
notebook execution or authentication audit.
[marimo formatter](https://github.com/marimo-team/marimo/blob/0.18.0/marimo/_utils/log_formatter.py),
[Python 3.12 formatter clock](https://github.com/python/cpython/blob/v3.12.0/Lib/logging/__init__.py).

An acquired `~/marimo.log` is a separate search lead. Check launcher/service output
redirection and content provenance before attributing it to the internal handler;
that home-root filename is not the default established above. Matching basenames do
not establish equal record formats, clocks or collection coverage.
