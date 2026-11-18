# Application, database and identity observables

Separate a product's documented field from instrumentation the application must provide.
The examples of application fields below define a proposed local contract; they are not
automatic IIS, WAF, SIEM or METIS columns. Verify their existence and semantics with the
service owner before writing a query. Redact credentials, bearer tokens, session secrets
and sensitive response bodies at the source when possible.

## HTTP and application decisions

IIS W3C files commonly reside under
`%SystemDrive%\inetpub\logs\LogFiles\W3SVC{site-id}\`; the configured log directory can
change. Read each file's `#Fields` header rather than assuming column positions. Useful
selected fields include `c-ip`, `cs-method`, `cs-uri-stem`, `cs-uri-query`, `sc-status`,
`sc-substatus`, `sc-win32-status` and `time-taken`. Host and user-agent field spelling must
follow the actual header. W3C `date` and `time` form a UTC timestamp; `time-taken`
is milliseconds. File rollover/naming may use a different configured clock, so never
derive event time from the filename alone. Verify the format and selected fields.
The query field is not the POST body, and byte counts do not
show which protected data was delivered. Standard access logs do not include a generic
response-body column. A trusted proxy's forwarding policy is needed before attributing a
supplied client-address header to a user.

Define server-side `request_id`/`trace_id`, authenticated `actor_id`, `tenant_id`,
`object_type`, `object_id`, `action`, `policy_version`, `decision` and `outcome` when object
authorization is the question. These are local instrumentation names. Preserve the
normalization from a route to an object and the identity's state at decision time. HTTP
success, database permission and business-action completion are separate observations.

For outgoing HTTP instrumentation, the OpenTelemetry convention uses `server.address`
for the intended server, while `network.peer.address` can identify the proxy or actual
peer. `url.full` can describe the original request before redirects; it does not establish
the final contacted address. Bind spans to the incoming request and record redirect/DNS/
proxy evidence separately. Version and instrumentation options determine which attributes
are collected. Never expose embedded URL credentials or signed query parameters in a
generic detection report.

## Database correlation

SQL Server audit rows can include `event_time`, `action_id`, `session_id`,
`session_server_principal_name`, `server_principal_name`, `database_name`, `schema_name`,
`object_name` and `statement`. `client_ip`, `application_name` and `connection_id` depend
on version and action. `event_time` is the UTC datetime2 value for the audited action;
it is not a duration or an ingestion clock. Crucially, for non-login audit events `succeeded` reports the
permission check; it does not assert that the requested operation completed. Obtain
application outcomes, statement completion or data-state evidence for that stronger claim.

PostgreSQL CSV/JSON logging needs the selected format and settings. CSV is positional:
confirm the release layout and import-column mapping. The documented import example
names its timestamp `log_time`, process `process_id`, line counter `session_line_num`
and SQLSTATE `sql_state_code`. With `session_id`, the line counter locates a session
record more reliably than PID alone. JSON logs instead use native keys `timestamp`,
`pid`, `line_num` and `state_code`; the client query is `statement`, not the CSV import
example's `query`. Preserve `application_name` when available.

Both formats' log timestamp timezone follows `log_timezone`; do not assume the session
TimeZone setting or a UTC default. Retain raw milliseconds/offset and normalize explicitly.
Columns and collection change by release. A syntax error is an unsuccessful parse, not
proof that another request returned data. Connection pools require application trace
binding: database identity is often a service principal shared by many web users.

## Cloud identity and mail

Entra `SigninLogs` uses `Id`, `UserId`, `AppId`, `IPAddress`, `ResultType`,
`ConditionalAccessStatus`, `DeviceDetail` and `AuthenticationDetails`. The latter is a
serialized structure to parse against the current schema. A result code of string `0`
denotes a successful sign-in; do not convert missing results to success. `UserPrincipalName`
is display/context, not an immutable user key. Use tenant context with `UserId`.
`CorrelationId` assists troubleshooting and is not by itself a trusted session binding.
`AADNonInteractiveUserSignInLogs` is a separate population; requests and MFA challenges are
not one-to-one, so failure row counts alone do not count denied prompts.

Defender `EmailEvents` can provide `NetworkMessageId`, `RecipientEmailAddress`,
`SenderFromDomain`, `SenderMailFromDomain`, `DeliveryAction`, `DeliveryLocation` and
`AuthenticationDetails`. Use the provider's trace and collection boundary to assess
authentication claims, not a copied header label. `UrlClickEvents` adds URL interaction
evidence with `NetworkMessageId`, `AccountUpn`, `Url`, `ActionType` and `IsClickedThrough`.
Recipients and repeated delivery/click rows make these relationships one-to-many; joining
only a message ID can inflate counts or associate another recipient's activity.

### Locating the SQL audit record

For file-target audits read with `sys.fn_get_audit_file`, retain output `file_name` and
`audit_file_offset` with the acquired file hash and server instance. `sequence_number`
orders fragments when a large audit record spans multiple records; it is not a universal
session event count. The function's `audit_record_offset` argument is a resume coordinate
with documented buffer behavior, not permission to carve an arbitrary byte as a whole row.
Keep raw rows and the reader version when assembling a long statement. See the
[function's result schema](https://learn.microsoft.com/en-us/sql/relational-databases/system-functions/sys-fn-get-audit-file-transact-sql).

SQL Server message 15457 identifies a configuration value change. Preserve the option
name and both values, instance, timestamp and configured destination; a change need not
be an enabling change, and neither direction proves the feature was used. A configuration
change message alone also does not prove that the running value has taken effect; verify
applicable configuration state and activation requirements separately. SQL message 33205 is the audit-event envelope: inspect its action and payload rather than treating
every 33205 as impersonation. File, Windows Application and Windows Security audit targets
are alternatives; confirm the configured target and provider instead of assuming all are
present. SQL authentication also needs SQL-side evidence and need not produce the same
Windows logon population as integrated authentication. Microsoft's
[configuration-message catalog](https://learn.microsoft.com/en-us/sql/relational-databases/errors-events/database-engine-events-and-errors-15000-to-15999),
[audit-message catalog](https://learn.microsoft.com/en-us/sql/relational-databases/errors-events/database-engine-events-and-errors-31000-to-41399)
and [audit destinations](https://learn.microsoft.com/en-us/sql/relational-databases/security/auditing/sql-server-audit-database-engine)
provide the product contracts; actual log transport remains a deployment prerequisite.

## Tomcat deployment and existing access-log evidence

Resolve the acquired instance's `CATALINA_BASE` first; it can differ from the installation's
`CATALINA_HOME`. Inspect `conf/server.xml` and the selected Host configuration. Host
`appBase` defaults to `webapps`, whereas `xmlBase` defaults to
`conf/{engine_name}/{host_name}` beneath that base when no override applies. A Context's
`docBase` can point to a different directory or WAR. Preserve configured paths, archive
members, unpacked files and their digests separately; the presence of a JSP or WAR does
not establish that a request executed it. Deployment and application response evidence
are needed for that conclusion.
[Host paths](https://tomcat.apache.org/tomcat-10.1-doc/config/host.html) and
[Context locations](https://tomcat.apache.org/tomcat-10.1-doc/config/context.html).

`conf/tomcat-users.xml` is a candidate local user/role store, not every deployment's
identity authority. Inspect the selected Realm and its resource or `pathname` configuration
before assigning meaning to its user/role entries; a different Realm can use another
backend. Keep credential-bearing values private and do not interpret a historical user
entry as a successful authentication.
[Realm configuration](https://tomcat.apache.org/tomcat-10.1-doc/config/realm.html).

For an existing AccessLogValve, retain its `directory`, `prefix`, `suffix` and `pattern`
so that each log column has an actual definition. The pattern `%{JSESSIONID}c`, if already
configured, records a request cookie of that name. It is not a default universal access-log
column; a custom parser's session field can instead come from URL rewriting or application
instrumentation. The token and its source must not be conflated. Session tokens are
sensitive, can rotate or be reused, and do not by themselves identify a human. Preserve
private raw evidence and use bounded correlations rather than publishing tokens. Record
existing logging settings without enabling new secret-bearing logging as part of analysis.
[Access-log pattern definitions](https://tomcat.apache.org/tomcat-10.1-doc/config/valve.html).

## PHP input selectors in acquired application evidence

When reviewing preserved PHP source, configuration and request telemetry, record the
PHP version, SAPI, request method, content type and the actual input selector. These
interfaces describe different input layers; they are not automatic access-log columns.

| Native selector | Input representation and boundary |
|---|---|
| `$_GET` | Associative array populated from the URL query string even when the HTTP method is not GET; values are URL-decoded |
| `$_POST` | Associative array populated for HTTP POST form input with `application/x-www-form-urlencoded` or `multipart/form-data`; it is not the raw JSON/XML body |
| `php://input` | Read-only stream exposing the raw request body; unavailable for POST `multipart/form-data` when `enable_post_data_reading` is enabled |
| `getallheaders()` | Associative array of current HTTP request headers; header presence is not a body observation or proof of sender identity |
| `php://stdin` | Read-only access to process standard input; do not assume it has the same content or lifecycle as the HTTP request-body stream |
| `$HTTP_RAW_POST_DATA` | Historical variable removed in PHP 7.0; its mention in older source does not establish availability in the acquired runtime |

The contracts are documented for [query input](https://www.php.net/manual/en/reserved.variables.get.php),
[form input](https://www.php.net/manual/en/reserved.variables.post.php),
[PHP streams](https://www.php.net/manual/en/wrappers.php.php),
[request headers](https://www.php.net/manual/en/function.getallheaders.php) and
[PHP 7.0 removals](https://www.php.net/manual/en/migration70.incompatible.php).
A framework property such as `request.body` requires its own producer/version contract;
it is not a native PHP superglobal. Join available observations through the application's
validated request identity and preserve whether a value was raw or parsed. Empty form
parameters alone cannot establish that the request had no body. Keep body and credential
values in private evidence; do not enable new secret-bearing logging merely to fill a gap.

## Apollo HTTP batches and operation counts

Apollo Server's `allowBatchedHttpRequests` is a Boolean configuration option.
The documented default is `true` in version 3 and `false` from version 4 onward;
identify the deployed version and effective configuration before interpreting
a retained request. With batching accepted, one HTTP request can carry a JSON
array of operation request objects and receive a corresponding response array.
Ordinary textual POST operation objects use `query` and can include `variables`,
`operationName` and `extensions`; persisted-query requests can omit the query text. The selected operation in a document is not a count of all
operation definitions in that document.

Count transport requests and parsed operation requests separately. Preserve
array position, request/trace identity and each operation's errors or result
when correlating existing evidence. A batch setting, HTTP status or response
array alone does not prove that every requested business action succeeded.
An access log that omitted the body cannot establish the batch population.
No active request or change to batching is needed to classify retained evidence.
[Version 3 configuration](https://www.apollographql.com/docs/apollo-server/v3/api/apollo-server),
[version 4 migration](https://www.apollographql.com/docs/apollo-server/migration-from-v3),
[request format](https://www.apollographql.com/docs/apollo-server/workflow/requests)
and [persisted-query contract](https://www.apollographql.com/docs/apollo-server/performance/apq).

## Varnish object hit counts

In the Varnish 7.6.0 VCL contract, `obj.hits` has type `INT` and is readable in
`vcl_hit` and `vcl_deliver`. It counts hits on that cache object; zero in
`vcl_deliver` denotes a cache miss. It does not count distinct clients, people
or executions of application content. Cache-object identity and replacement
matter when comparing observations across time.

A response header such as `X-Cache-Hits` is evidence of this variable only when
the acquired VCL and proxy chain establish that mapping. Do not assume a
universal header name or trust a client-supplied lookalike. Requests made to
observe a cached object can themselves contribute hits, so preserve existing
request provenance and avoid interpreting polling-induced changes as another
actor's activity. Retained cache and application records are needed to support
a stronger conclusion about who requested an object or what the application did.
[Versioned VCL variable reference](https://github.com/varnishcache/varnish-cache/blob/varnish-7.6.0/doc/sphinx/reference/vcl_var.rst).

## pgAudit settings are separate from PostgreSQL log filenames

In pgAudit 1.7.0, intended for PostgreSQL 15, `pgaudit.log` selects session-audit
statement classes; it is not a fixed output filename. Its class list supports
`READ`, `WRITE`, `FUNCTION`, `ROLE`, `DDL`, `MISC` and `MISC_SET`, with `ALL` and
class exclusions; the default is `none`. Inspect the acquired effective settings
and extension availability. The configured selection alone does not prove that
a particular statement was logged or completed.
[pgAudit 1.7.0 settings](https://github.com/pgaudit/pgaudit/blob/1.7.0/README.md#settings).

pgAudit sends records through PostgreSQL's logging facility. For PostgreSQL 15,
resolve `log_destination` and Boolean `logging_collector`. When the collector is
enabled, string `log_directory` is absolute or relative to the cluster data
directory, while string `log_filename` is a filename pattern. An acquired
`current_logfiles` records current collector destinations and paths when present;
it does not inventory every historical rotation. Retain the selected format,
rotation coverage and `log_timezone`; a setting named `pgaudit.log` supplies none
of those coordinates.
[PostgreSQL 15 logging destinations](https://www.postgresql.org/docs/15/runtime-config-logging.html#RUNTIME-CONFIG-LOGGING-WHERE).

The pgAudit payload exposes `AUDIT_TYPE`, `STATEMENT_ID`, `SUBSTATEMENT_ID`,
`CLASS`, `COMMAND`, `OBJECT_TYPE`, `OBJECT_NAME`, `STATEMENT` and `PARAMETER`.
Remove only the confirmed outer logging envelope before parsing its quoted CSV
fields. Statement and substatement identifiers are session-scoped; several
relation records can share the same pair. Bind them to the acquired server and
backend/session context, and use the outer log's clock. Do not equate payload
row count with statement count or committed changes. Optional row counts and
statement/parameter visibility depend on the acquired pgAudit settings. Retain
sensitive SQL and parameter values privately.
[Versioned payload contract](https://github.com/pgaudit/pgaudit/blob/1.7.0/README.md#format).

## Laravel application-log destination

In the Laravel application skeleton v12.0.0, `config/logging.php` selects the default
channel through `LOG_CHANNEL`, with `stack` as its fallback. The stack's `channels`
come from `LOG_STACK`, falling back to `single`. The `single` channel has `driver`,
`path` and `level` settings; its supplied path resolves to `storage/logs/laravel.log`
beneath the application base when the default storage directory applies. `LOG_LEVEL`
sets a severity threshold. Inspect the acquired effective configuration: a custom
channel, stderr/syslog destination or changed storage root can make that path inapplicable.
Laravel v12.0.0 also supports `LARAVEL_STORAGE_PATH` and `useStoragePath()` overrides.
[Application logging configuration](https://github.com/laravel/laravel/blob/v12.0.0/config/logging.php)
and [storage-root resolution](https://github.com/laravel/framework/blob/v12.0.0/src/Illuminate/Foundation/Application.php).

Retain channel, handler/formatter, application instance, file/rotation and line coordinates
with each observation. The configured `daily` channel and a `single` file have different
rotation behavior. This is application diagnostic output, not a guaranteed request ledger;
missing error text proves neither request success nor absence. Timestamp format/timezone,
request IDs and recorded payload depend on the actual logger and application. Correlate
available request/trace identity with independent access or outcome evidence, and keep
sensitive message content private.

## Debian Apache other-virtual-host access log

Debian's Apache package `2.4.62-1~deb11u1` supplies
`conf-available/other-vhosts-access-log.conf`, whose `CustomLog` selects
`${APACHE_LOG_DIR}/other_vhosts_access.log` with the `vhost_combined` format nickname.
It covers virtual hosts that do not define their own logfile when this configuration
is enabled. The supplied `envvars` sets the normal single-instance log directory to
`/var/log/apache2`; multiple-instance suffixes and local configuration can change it.
Preserve the active includes, virtual-host configuration and environment rather than
assuming every site's traffic reaches `/var/log/apache2/other_vhosts_access.log`.
[Distribution log selection](https://sources.debian.org/src/apache2/2.4.62-1~deb11u1/debian/config-dir/conf-available/other-vhosts-access-log.conf/)
and [directory environment](https://sources.debian.org/src/apache2/2.4.62-1~deb11u1/debian/config-dir/envvars/).

Resolve the actual `LogFormat` before assigning columns. This package's
`vhost_combined` starts with `%v:%p` for the serving canonical virtual-host name/port;
`%t` carries request receipt time with a numeric timezone offset, `%>s` the final HTTP
status, and `%O` sent bytes including headers when `mod_logio` is enabled. These are
rendered text fields, not a JSON schema or proof of completed business activity. Keep the virtual-host context,
request representation and private record coordinate; header claims and nearby times
alone do not authenticate a client or establish a cross-log join.
[Distribution format](https://sources.debian.org/src/apache2/2.4.62-1~deb11u1/debian/config-dir/apache2.conf.in/)
and [Apache 2.4 field meanings](https://httpd.apache.org/docs/2.4/mod/mod_log_config.html).

## PAN-OS SSL VPN diagnostic-log candidate

`sslvpn_ngx_error.log` is a PAN-OS SSL VPN nginx diagnostic log, located through the
`mp-log` log category in the vendor's PAN-OS 10.2.0 article. The article identifies
increased debug-level logging in 10.2.0 compared with info level in 10.1.x. Treat that
as a version-specific diagnostic fact, not a universal severity default or a count of
VPN authentications. The article's diagnostic path display is not a stable filesystem
schema to extrapolate to every release.

Preserve appliance/build, acquired member path/hash, logging level, rotations and the
original clock representation. Establish timezone from the acquired system rather than
assuming an unzoned diagnostic timestamp is UTC. Relate a diagnostic to independent
authentication or connection evidence before claiming user access, completed sessions
or impact; presence and absence of this error log alone establish none of those.
[Vendor diagnostic-log and version boundary](https://knowledgebase.paloaltonetworks.com/KCSArticleDetail?id=kA14u000000oNalCAE).
