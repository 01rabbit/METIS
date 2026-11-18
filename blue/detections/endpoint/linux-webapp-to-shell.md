# Trace unexpected child execution from a Linux web application

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Can an application request or service job explain an interpreter launched under the web workload?

## Evidence to request

Web workload identity and container/unit mapping, process start history, audit execution fragments, request/trace IDs, deployment jobs and resulting files/connections.

## Reasoning procedure

- Use the actual service account inventory; numeric UIDs and executable names vary across distributions and deployments.
- If only the effective UID is known, report service-account execution without claiming a particular parent. An ancestry claim requires parent-image resolution.
- Link request handling to the child through application trace or reliable process context. Shared workers and asynchronous queues weaken simple time joins.
- Check whether the child performs expected rendering, conversion or maintenance, then review unexpected persistence or outbound behavior.
- Investigate authentication failures followed by success as a separate lead using the same account/source/session context. A network sensor may not know the SSH authentication outcome.

## Alternatives and limits

Application helpers, build pipelines and background workers legitimately start interpreters. Process names alone do not distinguish an application runtime from an injected command.

## Discriminating checks

Test an expected renderer, an asynchronous approved job, missing parent history and an unexplained attributable child. Do not infer successful application compromise from a 200 response. Containment must account for the affected application and shared dependencies.

## Concrete observation contract

For nginx, `/var/log/nginx/access.log` and `error.log` are common configured locations;
Apache layouts often use `/var/log/apache2/` or `/var/log/httpd/`. Verify the actual
configuration and log format instead of assuming a fixed column layout. Relate its
request/trace reference to audit execution records and the web service's real UID and
process lifetime. The access log alone usually lacks that process binding.

Reassemble audit `SYSCALL`/`EXECVE`/`PATH` records using host, audit timestamp and serial,
preserving available log/boot context, then
resolve the parent with `ppid` plus process history. Separate a new shell from ordinary
CGI or conversion helpers. Authentication logs in `auth.log`, `secure` or the journal
can corroborate a later accepted SSH session; an outbound connection or handshake does
not establish login. Mark absent request-to-process linkage as a causal gap.

## Request coordinates across NGINX and PHP-FPM

If recorded by the configured `log_format`, NGINX `$request_uri` retains the original URI and arguments; `$uri` is the current normalized URI and may change during internal redirects. Preserve both meanings and the log escaping mode when comparing records. Logging uses the location where processing finishes, which need not be the initial location. [NGINX variables](https://nginx.org/en/docs/http/ngx_http_core_module.html#variables) and [request logging](https://nginx.org/en/docs/http/ngx_http_log_module.html).

Resolve PHP-FPM's global `error_log` and each pool's `access.log` / `access.format` from the acquired configuration; access logging is unset by default. Where the format includes them, retain these coordinates:

| Format selector | Observation |
| --- | --- |
| `%f` | Script filename, distinct from the request URI |
| `%r`, `%q` | URI without query; separate query string |
| `%n`, `%p` | Pool name; serving child PID |
| `%s` | Response status |
| `%t`, `%T` | Request arrival; log-write time at request completion; preserve format and zone |
| `%d` | Duration in seconds by default; `%{milliseconds}d` and `%{microseconds}d` select other units |

`catch_workers_output` controls whether worker stdout/stderr reaches the main error log and defaults to disabled. `security.limit_extensions` restricts main-script extensions; its documented default includes `.php` and `.phar`. A different suffix alone therefore cannot establish unauthorized execution. [PHP-FPM configuration](https://www.php.net/manual/en/install.fpm.configuration.php).

Correlate a recorded PID within the same host, pool and process lifetime, using request identifiers when available. A worker may handle many requests; temporal proximity alone leaves ambiguity. Treat a refusal message as an observed rejection, with cause and intent still to establish. Neither an HTTP status nor an absent error message establishes execution or complete collection. Keep this an investigation contract until the actual application configuration and sensor coverage validate an alert.
