# Linux audit and network correlation contracts

Treat the path and format as collector configuration, not universal distribution defaults.
Common audit storage is `/var/log/audit/audit.log`. Authentication messages often go to
`/var/log/auth.log`, `/var/log/secure` or the journal. Ask which source actually covers the
interval. File rotation, forwarding loss, audit backlog and namespace boundaries affect
negative conclusions.

## Reconstruct an audit event before interpreting it

An audit record may be split into `SYSCALL`, `EXECVE`, `PATH`, `CWD` and `PROCTITLE`
records. Relate them by originating host plus the timestamp and serial in `msg=audit(...)`.
The serial alone is not a fleet identifier. Preserve every PATH item and its `item`
number: the first name is not necessarily the affected object. `CWD` helps resolve relative
names, while `inode` and `dev` help distinguish path reuse; neither substitutes for a
content hash when the claim concerns bytes.

`SYSCALL` has `pid`, `ppid`, `exe`, `comm`, `uid`, `euid`, `auid`, `ses`, `success` and
`exit` when supplied. Interpret syscall numbers against `arch`. `auid` refers to login
attribution; an unset value such as 4294967295 is common for daemons and is not root.
`uid` and `euid` answer different questions. `EXECVE` arguments can be encoded, segmented
or truncated. Decode for display without executing them; retain the original bytes and
decoding status. A successful syscall establishes that operation, not the whole incident.

For capability and mode review, PATH records can expose `mode`, `ouid`, `ogid`, `cap_fp`,
`cap_fi` and `cap_fe`. Their presence varies. The file's permitted/inheritable/effective
capability data is distinct from the running process's effective privileges. Preserve the
original representation and decode using the matching platform. Writable configuration,
set-user-ID mode or capabilities identify a control to review; evidence of subsequent use
requires execution context and an observed effect.

Sudo messages may name `TTY`, `PWD`, target `USER` and `COMMAND`; records can describe
both permitted and denied requests depending on logging settings. Pair the decision with
audit execution/session evidence where available instead of treating command text as
execution. Sudo policy lives in `/etc/sudoers` and included files such as `/etc/sudoers.d/`;
preserve include order and the applicable host/user context. For service ancestry, journal
fields `_SYSTEMD_UNIT`, `_PID`, `_UID` and `_BOOT_ID` assist correlation. Raw auditd does
not supply a universal `ParentImage` column; resolve the parent from process history.

## Network records

In Zeek `conn.log`, retain `uid`, `ts`, `id.orig_h`, `id.orig_p`, `id.resp_h`, `id.resp_p`,
`proto`, `duration`, `conn_state`, `orig_bytes` and `resp_bytes`. These describe the sensor's
connection observation. NAT, proxies and asymmetric routing can hide the originating user
or process. `missed_bytes` is useful loss evidence; zero is not a guarantee that all traffic
in the estate was observed. `local_orig` and `local_resp` depend on the configured local
network definition, not on an address being inherently trusted.

In `dns.log`, one connection `uid` can contain multiple transactions. Add `trans_id`,
`query`, query type, response code and event time when relating a response. Common decoded
columns are `qtype_name`, `rcode_name` and `answers`; confirm the installed schema. A
recursive resolver's source address does not identify its downstream client. Host DNS
events or resolver request attribution are needed for that extra relationship.

`ssl.log` can contribute `server_name` and the same `uid`. A HTTP authority comparison
requires a visible request on that connection, for example `http.log` with `host` and
`trans_depth`. Encryption can make the comparison unavailable. TLS 1.3 hides server
certificate details from ordinary passive capture, and ECH can hide the useful SNI.
Do not invent certificate/SNI columns or infer a mismatch when one side was not collected.
