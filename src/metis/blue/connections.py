"""Explicit connection profiles.

No target discovery or exploit transport. SSH reads, RDP/VNC desktops, SOCKS and VPN tunnels run as
foreground clients in their own process group under a ledger lease; interactive desktops, tunnels
and VNC control are state-changing and need an exact scoped permit.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from metis.blue.ledger import redact

READ_COMMANDS = {
    "system": "uname -a",
    "identity": "id",
    "processes": "ps -eo pid,ppid,user,comm",
    "sockets": "ss -tunap",
    "os-release": "cat /etc/os-release",
}


def hostname(value):
    if not isinstance(value, str):
        raise ValueError("Invalid host")  # noqa: TRY004 -- callers handle ValueError
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", value):
        raise ValueError("Invalid host")
    return value


def port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Invalid port")
    return value


def profile(path, name):
    profiles = json.loads(Path(path).read_text())
    p = profiles[name]
    if p.get("protocol") not in ("ssh", "rdp", "vnc", "socks", "vpn", "browser"):
        raise ValueError("Unsupported protocol")
    return p


def build(p, action="inspect"):
    protocol = p["protocol"]
    env = {}
    stdin = None
    write = False
    host = hostname(p["host"]) if protocol not in ("vpn", "browser") else None
    if protocol in ("ssh", "socks"):
        user = p.get("user", "analyst")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", user):
            raise ValueError("Invalid user")
        args = [
            "ssh",
            "-F",
            "/dev/null",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ExitOnForwardFailure=yes",
            "-p",
            str(port(p.get("port", 22))),
        ]
        if p.get("identity_file"):
            args += ["-i", str(Path(p["identity_file"]).expanduser().resolve())]
        if p.get("known_hosts_file"):
            args += ["-o", "UserKnownHostsFile=" + str(Path(p["known_hosts_file"]).expanduser().resolve())]
        args += ["-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2"]
        if p.get("password_env"):
            value = os.environ.get(p["password_env"])
            if not value:
                raise ValueError("Credential environment reference is unavailable")
            env["SSHPASS"] = value
            args = ["sshpass", "-e"] + args
        else:
            args += ["-o", "BatchMode=yes"]
        if protocol == "socks":
            if action != "start":
                raise ValueError("SOCKS supports start")
            args += ["-N", "-D", "127.0.0.1:" + str(port(p.get("local_port", 1080))), user + "@" + host]
            write = True
        else:
            args += ["-o", "ClearAllForwardings=yes", user + "@" + host]
            if action in READ_COMMANDS:
                args.append(READ_COMMANDS[action])
            elif action == "read-log":
                path = p.get("log_path", "")
                if path not in p.get("allowed_log_paths", []) or not path.startswith("/") or "\x00" in path:
                    raise ValueError("Log path must be explicitly allowlisted")
                args.append("tail -n 500 -- " + shlex.quote(path))
            else:
                raise ValueError("Unsupported SSH action")
    elif protocol == "rdp":
        target = ("[" + host + "]") if ":" in host else host
        args = [
            p.get("client", "xfreerdp"),
            "/v:" + target + ":" + str(port(p.get("port", 3389))),
            "/u:" + p.get("user", "analyst"),
            "/dynamic-resolution",
            "-clipboard",
            "/audio-mode:2",
            "/size:1024x768",
        ]
        fingerprint = p.get("certificate_sha256")
        if fingerprint:
            fingerprint = fingerprint.replace(":", "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise ValueError("Invalid RDP certificate SHA256")
            # FreeRDP 2 requires colon separators; FreeRDP 3 accepts either form.
            fingerprint = ":".join(fingerprint[i : i + 2] for i in range(0, 64, 2))
            args += ["/cert:fingerprint:sha256:" + fingerprint]
        else:
            args += ["/cert:deny"]
        if p.get("password_env"):
            password = os.environ.get(p["password_env"])
            if not password or "\n" in password or "\r" in password:
                raise ValueError("Credential environment reference is unavailable or not single-line")
            # Only the password is prompted when /u is supplied; never put it in argv.
            args += ["/from-stdin:force"]
            stdin = password + "\n"
        # Interactive remote input cannot be constrained portably across RDP clients.
        # Opening an interactive session is therefore a scoped write capability.
        if action != "open":
            raise ValueError("RDP supports open")
        write = True
    elif protocol == "vnc":
        if action not in ("view", "control"):
            raise ValueError("VNC supports view or control")
        args = [
            p.get("client", "vncviewer"),
            "-Shared=1",
            "-AcceptClipboard=0",
            "-SendClipboard=0",
            "-ViewOnly=" + ("1" if action == "view" else "0"),
            host + "::" + str(port(p.get("port", 5900))),
        ]
        if p.get("password_file"):
            args += ["-passwd", str(Path(p["password_file"]).expanduser().resolve())]
        if p.get("ca_file"):
            args += ["-SecurityTypes=X509Vnc", "-X509CA", str(Path(p["ca_file"]).expanduser().resolve())]
        write = action == "control"
    elif protocol == "vpn":
        if action != "start":
            raise ValueError("VPN supports start")
        config = Path(p["config_file"]).expanduser().resolve()
        if not config.is_file():
            raise ValueError("VPN profile is missing")
        validate_vpn(config)
        args = ["openvpn", "--config", str(config), "--script-security", "1", "--auth-nocache"]
        write = True
    else:
        url = urlsplit(p["url"])
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("Browser URL must be HTTP(S) without embedded credentials")
        if action != "view":
            raise ValueError("Browser supports view")
        return {
            "protocol": "browser",
            "url": p["url"],
            "resource": p.get("resource"),
            "write": False,
            "instruction": "Use the connected browser skill. Read and authenticate within scope; request a grant before changing application state.",
        }
    # Executable names are configuration, not artifact data. No shell is used.
    if Path(args[0]).name != args[0] and protocol in ("rdp", "vnc"):
        raise ValueError("Desktop client must be a binary name on PATH")
    return {
        "protocol": protocol,
        "argv": args,
        "env": env,
        "stdin": stdin,
        "write": write,
        "resource": p.get("resource"),
    }


def validate_vpn(path):
    """Keep the managed process in the foreground; profiles still require operator review."""
    inline = False
    forbidden = {
        "daemon",
        "config",
        "plugin",
        "up",
        "down",
        "route-up",
        "route-pre-down",
        "ipchange",
        "iproute",
        "tls-verify",
        "auth-user-pass-verify",
        "client-connect",
        "client-disconnect",
        "learn-address",
        "management",
        "management-client",
        "log",
        "log-append",
        "syslog",
        "script-security",
        "writepid",
        "cd",
        "chroot",
    }
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("</"):
            inline = False
            continue
        if inline:
            continue
        if line.startswith("<"):
            if line not in (
                "<ca>",
                "<cert>",
                "<key>",
                "<tls-auth>",
                "<tls-crypt>",
                "<tls-crypt-v2>",
                "<pkcs12>",
                "<auth-user-pass>",
                "<http-proxy-user-pass>",
                "<extra-certs>",
                "<dh>",
                "<secret>",
            ):
                raise ValueError("Unsupported VPN inline section")
            inline = True
            continue
        words = shlex.split(line, comments=True)
        if words and words[0].lstrip("-") in forbidden:
            raise ValueError("Unmanaged VPN directive: " + words[0])


class ConnectionSession:
    """A worker-owned foreground client with a process group and durable lease guard.

    Keep the context open while consuming a tunnel/desktop. A crashed supervisor leaves
    its lease reserved for owner reconciliation, never automatically reclaimable.
    """

    def __init__(self, store, run, task, p, action, grant=None):
        self.store, self.run, self.task = store, run, task
        self.spec = build(p, action)
        self.action = action
        self.grant = grant
        self.process = None
        self.cid = None
        self.files = []
        self.closed = False
        self.result = None

    def start(self):
        if self.cid:
            raise ValueError("Connection already started")
        spec = self.spec
        resource = spec.get("resource")
        if not resource:
            raise ValueError("Every connection needs a declared resource")
        if spec["protocol"] == "browser":
            raise ValueError("Use the native browser adapter")
        self.cid = self.store.begin_connection(
            self.run, self.task, resource, spec["protocol"], self.action, spec["write"], self.grant
        )
        try:
            # Output files outlive this block; close() owns them.
            self.files = [tempfile.TemporaryFile(), tempfile.TemporaryFile()]  # noqa: SIM115
            env = os.environ.copy()
            env.update(spec["env"])
            self.process = subprocess.Popen(
                spec["argv"],
                stdin=subprocess.PIPE if spec["stdin"] else subprocess.DEVNULL,
                stdout=self.files[0],
                stderr=self.files[1],
                env=env,
                start_new_session=True,
            )
            self.store.connection_state(self.cid, "running", self.process.pid)
            if spec["stdin"]:
                try:
                    self.process.stdin.write(spec["stdin"].encode())
                    self.process.stdin.flush()
                except BrokenPipeError:
                    pass
                finally:
                    self.process.stdin.close()
            self.store.message(
                self.run,
                self.task,
                self.task,
                "connection",
                "action",
                json.dumps(
                    {
                        "connection": self.cid,
                        "resource": resource,
                        "action": self.action,
                        "write": spec["write"],
                    }
                ),
            )
            return self
        except BaseException:
            self.close()
            raise

    def output(self):
        if self.closed:
            return self.result or {}
        data = {}
        for field, handle in zip(("stdout", "stderr"), self.files):
            size = os.fstat(handle.fileno()).st_size
            value = os.pread(handle.fileno(), min(size, 1024 * 1024), max(0, size - 1024 * 1024)).decode(
                errors="replace"
            )
            secrets = list(self.spec["env"].values()) + [
                self.spec.get("stdin", "").strip() if self.spec.get("stdin") else ""
            ]
            for secret in secrets:
                if secret:
                    value = value.replace(secret, "[REDACTED]")
            data[field] = redact(value)
        return data

    def wait_for(self, marker, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if marker in "\n".join(self.output().values()):
                return
            if self.process.poll() is not None:
                raise RuntimeError("Connection exited before readiness: " + json.dumps(self.output()))
            time.sleep(0.1)
        raise TimeoutError("Connection readiness deadline exceeded")

    def wait(self, timeout=60):
        timed_out = False
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            self.close()
        return dict(self.result, timed_out=timed_out)

    def close(self):
        if self.closed:
            return
        if self.process:
            # Stop descendants even when the original launcher has already exited.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
        self.result = dict(self.output(), returncode=self.process.returncode if self.process else None)
        for handle in self.files:
            handle.close()
        if self.cid:
            self.store.connection_state(self.cid, "stopped")
            self.store.message(
                self.run,
                self.task,
                "connection",
                self.task,
                "result",
                json.dumps(self.result, ensure_ascii=False),
            )
        self.closed = True

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()


def execute(store, run, task, p, action, grant=None, timeout=60):
    if p["protocol"] == "browser":
        spec = build(p, action)
        cid = store.begin_connection(run, task, spec.get("resource"), "browser", action, False, None)
        store.connection_state(cid, "stopped")
        return spec
    with ConnectionSession(store, run, task, p, action, grant) as session:
        return session.wait(timeout)
