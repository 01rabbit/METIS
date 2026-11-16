"""Route raw TCP through the platform proxy when one is configured.

Agent sandboxes such as Claude Code's allow outbound traffic only through a
local proxy (``ALL_PROXY=socks5h://...`` and/or ``HTTPS_PROXY=http://...``) that
enforces a domain allowlist and resolves names itself. A raw socket that
resolves DNS locally fails there with ``gaierror`` even for an allowed host, so
METIS tunnels through the proxy instead: SOCKS5 with a remote hostname when
available, otherwise an HTTP ``CONNECT``. Destination policy (including DNS) is
then enforced by that trusted proxy; METIS never bypasses it.
"""
from __future__ import annotations

import base64
import ipaddress
import os
import socket
import struct
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Proxy:
    kind: str  # "socks5" or "http"
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    def describe(self) -> str:
        return f"{self.kind}://{self.host}:{self.port}"


def _parse(value: str) -> Proxy | None:
    if not value:
        return None
    if "://" not in value:
        value = "http://" + value
    parsed = urllib.parse.urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme in {"socks5", "socks5h", "socks"}:
        kind = "socks5"
    elif scheme in {"http", "https"}:
        kind = "http"
    else:
        return None
    if not parsed.hostname:
        return None
    default = 1080 if kind == "socks5" else 8080
    return Proxy(kind, parsed.hostname, parsed.port or default,
                 urllib.parse.unquote(parsed.username) if parsed.username else None,
                 urllib.parse.unquote(parsed.password) if parsed.password else None)


def _bypassed(host: str) -> bool:
    no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    if not no_proxy:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    for entry in (item.strip().lower() for item in no_proxy.split(",")):
        if not entry:
            continue
        if entry == "*":
            return True
        if address is not None and "/" in entry:
            try:
                if address in ipaddress.ip_network(entry, strict=False):
                    return True
            except ValueError:
                pass
            continue
        entry = entry.lstrip("*")
        name = host.lower()
        if name == entry.lstrip(".") or (entry.startswith(".") and name.endswith(entry)):
            return True
        if not entry.startswith(".") and name.endswith("." + entry):
            return True
    return False


def proxy_for(host: str) -> Proxy | None:
    """Return the proxy that raw TCP to ``host`` must use, or None for a direct connection."""
    if _bypassed(host):
        return None
    for name in ("ALL_PROXY", "all_proxy"):
        proxy = _parse(os.environ.get(name, ""))
        if proxy is not None:
            return proxy
    # Fall back to the HTTPS proxy, which supports CONNECT.
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        proxy = _parse(os.environ.get(name, ""))
        if proxy is not None:
            return proxy
    return None


def describe_environment() -> dict[str, str | None]:
    """Proxy summary for diagnostics without credentials."""
    probe = proxy_for("example.invalid")
    return {"raw_tcp_route": probe.describe() if probe else "direct",
            "http_proxy_detected": "yes" if urllib.request.getproxies() else "no"}


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise OSError("proxy closed the connection")
        data.extend(chunk)
    return bytes(data)


def _socks5(connection: socket.socket, proxy: Proxy, host: str, port: int) -> None:
    methods = b"\x00\x02" if proxy.username is not None else b"\x00"
    connection.sendall(b"\x05" + bytes([len(methods)]) + methods)
    version, method = _recv_exact(connection, 2)
    if version != 5 or method == 0xFF:
        raise OSError("SOCKS5 proxy refused all authentication methods")
    if method == 2:
        user = (proxy.username or "").encode()
        secret = (proxy.password or "").encode()
        connection.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(secret)]) + secret)
        if _recv_exact(connection, 2)[1] != 0:
            raise OSError("SOCKS5 proxy authentication failed")
    try:
        address = ipaddress.ip_address(host)
        target = (b"\x01" + address.packed) if address.version == 4 else (b"\x04" + address.packed)
    except ValueError:
        encoded = host.encode("idna")
        if len(encoded) > 255:
            raise OSError("hostname too long for SOCKS5") from None
        target = b"\x03" + bytes([len(encoded)]) + encoded  # remote DNS (socks5h semantics)
    connection.sendall(b"\x05\x01\x00" + target + struct.pack(">H", port))
    version, reply, _, kind = _recv_exact(connection, 4)
    if version != 5 or reply != 0:
        reasons = {1: "general failure", 2: "connection not allowed by ruleset", 3: "network unreachable",
                   4: "host unreachable", 5: "connection refused", 6: "TTL expired",
                   7: "command not supported", 8: "address type not supported"}
        raise OSError("SOCKS5 proxy: " + reasons.get(reply, f"error {reply}"))
    length = {1: 4, 4: 16}.get(kind)
    if length is None:
        length = _recv_exact(connection, 1)[0]
    _recv_exact(connection, length + 2)


def _http_connect(connection: socket.socket, proxy: Proxy, host: str, port: int) -> None:
    authority = (f"[{host}]" if ":" in host else host) + f":{port}"
    lines = [f"CONNECT {authority} HTTP/1.1", f"Host: {authority}", "User-Agent: METIS"]
    if proxy.username is not None:
        token = base64.b64encode(f"{proxy.username}:{proxy.password or ''}".encode()).decode()
        lines.append("Proxy-Authorization: Basic " + token)
    connection.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    response = bytearray()
    while b"\r\n\r\n" not in response:
        chunk = connection.recv(1)
        if not chunk:
            raise OSError("proxy closed the connection during CONNECT")
        response.extend(chunk)
        if len(response) > 16_384:
            raise OSError("oversized proxy CONNECT response")
    status = response.split(b"\r\n", 1)[0].decode("latin-1")
    parts = status.split(" ", 2)
    if len(parts) < 2 or parts[1] != "200":
        raise OSError("HTTP proxy refused CONNECT: " + status[:120])


def open_tunnel(host: str, port: int, timeout: float, proxy: Proxy) -> socket.socket:
    connection = socket.create_connection((proxy.host, proxy.port), timeout=timeout)
    try:
        if proxy.kind == "socks5":
            _socks5(connection, proxy, host, port)
        else:
            _http_connect(connection, proxy, host, port)
    except BaseException:
        connection.close()
        raise
    return connection
