"""Explicit-origin HTTP for CTF intake/submission. No ambient browser credentials."""
from __future__ import annotations

import hashlib
import http.client
import http.cookiejar
import http.cookies
import ipaddress
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, BinaryIO

from metis import __version__

HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}")
FORBIDDEN_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection", "upgrade", "te",
                               "trailer", "keep-alive", "expect"})


def clean_url(value: str) -> str:
    if len(value) > 8192 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("invalid URL characters or size")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("HTTP(S) URL without embedded credentials required")
    host = parsed.hostname.encode("idna").decode().lower()
    if "%" in host:
        raise ValueError("scoped IP addresses are unsupported")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    netloc = "[" + host + "]" if ":" in host else host
    if port != (443 if parsed.scheme == "https" else 80):
        netloc += ":" + str(port)
    path = urllib.parse.quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    return urllib.parse.urlunsplit((parsed.scheme, netloc, path, parsed.query, ""))


def origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(clean_url(value))
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class HTTPResult:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    size: int
    sha256: str


class SafeHTTP:
    """Pin direct DNS and preserve platform proxies. Credentials bind to one origin.

    Proxy routing/DNS is delegated to the inherited trusted platform proxy;
    local pinning cannot verify a proxy's destination. Never bypass that proxy.
    """

    def __init__(self, allowed_origins: list[str], *, auth_origin: str,
                 token_env: str | None = None, cookie_env: str | None = None,
                 state: dict | None = None, credentials: dict | None = None, timeout: float = 15):
        self.allowed = {origin(value) for value in allowed_origins}
        self.auth_origin = origin(auth_origin)
        if self.auth_origin not in self.allowed or len(self.allowed) > 16 or not 0 < timeout <= 60:
            raise ValueError("invalid HTTP scope/timeout")
        self.token_env, self.cookie_env = token_env, cookie_env
        for name in (token_env, cookie_env):
            if name is not None and (not name or len(name) > 80 or not all(char.isupper() or char.isdigit() or char == "_" for char in name)):
                raise ValueError("credential environment variable name required")
        self.timeout = timeout
        self.credentials = credentials or {}
        state = state or {}
        self.pins: dict[str, list[str]] = state.get("pins", {})
        self.jars: dict[str, http.cookiejar.CookieJar] = {}
        for key, values in state.get("cookies", {}).items():
            if key not in self.allowed or len(values) > 64:
                raise ValueError("invalid cookie state")
            jar = http.cookiejar.CookieJar()
            for fields in values:
                jar.set_cookie(http.cookiejar.Cookie(**fields))
            self.jars[key] = jar
        self.requests = 0
        self.auth_generation = 0
        self.auth_generation_check: Callable[[int], bool] | None = None
        self.proxy_used = bool(state.get("proxy_used", False))
        self.cookie_fingerprint = state.get("cookie_fingerprint")
        cookie = os.environ.get(cookie_env, "") if cookie_env else self.credentials.get("cookie", "")
        if cookie_env and not cookie:
            raise ValueError("configured CTF cookie binding is missing")
        if cookie:
            if len(cookie) > 16384:
                raise ValueError("cookie exceeds limit")
            fingerprint = hashlib.sha256(cookie.encode()).hexdigest()
            if fingerprint != self.cookie_fingerprint:
                parsed = http.cookies.SimpleCookie()
                parsed.load(cookie)
                if not parsed or len(parsed) > 64:
                    raise ValueError("invalid bounded Cookie header")
                jar = http.cookiejar.CookieJar()
                host = urllib.parse.urlsplit(self.auth_origin).hostname or ""
                for morsel in parsed.values():
                    if len(morsel.value) > 4096:
                        raise ValueError("cookie value exceeds limit")
                    jar.set_cookie(http.cookiejar.Cookie(0, morsel.key, morsel.value, None, False,
                                                        host, False, False, "/", True,
                                                        self.auth_origin.startswith("https:"), None,
                                                        True, None, None, {}))
                self.jars[self.auth_origin] = jar
                self.cookie_fingerprint = fingerprint

    def export_state(self) -> dict:
        cookies: dict[str, list[dict[str, Any]]] = {}
        for key, jar in self.jars.items():
            cookies[key] = [{"version": cookie.version, "name": cookie.name, "value": cookie.value,
                             "port": cookie.port, "port_specified": cookie.port_specified,
                             "domain": cookie.domain, "domain_specified": cookie.domain_specified,
                             "domain_initial_dot": cookie.domain_initial_dot, "path": cookie.path,
                             "path_specified": cookie.path_specified, "secure": cookie.secure,
                             "expires": cookie.expires, "discard": cookie.discard,
                             "comment": cookie.comment, "comment_url": cookie.comment_url,
                             "rest": {}, "rfc2109": cookie.rfc2109} for cookie in jar]
        return {"pins": self.pins, "cookies": cookies, "proxy_used": self.proxy_used,
                "cookie_fingerprint": self.cookie_fingerprint}

    def secret_values(self) -> list[str]:
        values = [os.environ.get(name, "") for name in (self.token_env, self.cookie_env) if name]
        values.extend(str(value) for value in self.credentials.values())
        values.extend(cookie.value or "" for jar in self.jars.values() for cookie in jar)
        return [value for value in values if len(value) >= 4]

    def _headers(self, url: str, supplied: dict[str, str], extended: bool = False) -> dict[str, str]:
        target = origin(url)
        headers = {"User-Agent": f"METIS/{__version__} authorized-CTF-client", "Accept-Encoding": "identity"}
        for key, value in supplied.items():
            lowered = key.lower()
            if extended:
                # Challenge interaction may craft arbitrary headers, but never hop-by-hop
                # framing headers, and never the platform's own credentials.
                if (not HEADER_NAME.fullmatch(key) or lowered in FORBIDDEN_HEADERS
                        or lowered.startswith("proxy-") or len(value) > 8192
                        or any(char in value for char in "\r\n\x00")
                        or (lowered in {"authorization", "cookie"} and target == self.auth_origin)):
                    raise ValueError("unsupported request header: " + key[:40])
            elif lowered not in {"content-type", "accept", "csrf-token"}:
                raise ValueError("unsupported request header")
            headers[key] = value
        if target == self.auth_origin:
            token = os.environ.get(self.token_env, "") if self.token_env else self.credentials.get("token", "")
            if self.token_env and not token:
                raise ValueError("configured CTF token binding is missing")
            if token:
                scheme = self.credentials.get("scheme", "Token")
                if scheme not in {"Token", "Bearer"}:
                    raise ValueError("unsupported token scheme")
                headers["Authorization"] = scheme + " " + token
        return headers

    def _addresses(self, url: str) -> list[str]:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        literal = False
        try:
            values = [str(ipaddress.ip_address(host))]
            literal = True
        except ValueError:
            values = sorted({str(ipaddress.ip_address(item[4][0])) for item in
                             socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        if not values or (not literal and any(not ipaddress.ip_address(value).is_global for value in values)):
            raise ValueError("hostname resolved to an ungranted private address")
        key = origin(url)
        if key in self.pins and set(values) != set(self.pins[key]):
            raise ValueError("DNS changed; a trusted operator must re-establish scope")
        self.pins[key] = values
        return values

    def _open(self, url: str, method: str, body: bytes | None, headers: dict[str, str]):
        parsed = urllib.parse.urlsplit(url)
        jar = self.jars.setdefault(origin(url), http.cookiejar.CookieJar())
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        jar.add_cookie_header(request)
        proxy = urllib.request.getproxies().get(parsed.scheme)
        if proxy and not urllib.request.proxy_bypass(parsed.hostname or ""):
            self.proxy_used = True
            opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(jar))
            try:
                response = opener.open(request, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                response = exc
            return response, None
        addresses = self._addresses(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection = http.client.HTTPConnection(parsed.hostname or "", port, timeout=self.timeout)
        connection.sock = socket.create_connection((addresses[0], port), timeout=self.timeout)
        if parsed.scheme == "https":
            try:
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock,
                                                                           server_hostname=parsed.hostname)
            except BaseException:
                connection.close()
                raise
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        try:
            connection.request(method, path, body=body, headers=dict(request.header_items()))
            response = connection.getresponse()
            jar.extract_cookies(response, request)
            return response, connection
        except BaseException:
            connection.close()
            raise

    def request(self, url: str, *, method: str = "GET", body: bytes | None = None,
                headers: dict[str, str] | None = None, max_bytes: int = 2_097_152,
                sink: BinaryIO | None = None, sensitive: bool = False,
                follow_redirects: bool = True, extended: bool = False,
                deadline: float | None = None) -> HTTPResult:
        methods = {"GET", "POST", "HEAD"} | ({"PUT", "DELETE", "PATCH", "OPTIONS"} if extended else set())
        if method not in methods or not 1 <= max_bytes <= 256 * 1024 * 1024:
            raise ValueError("invalid bounded HTTP request")
        if body is not None and len(body) > 131072:
            raise ValueError("HTTP request body exceeds limit")
        url = clean_url(url)
        initial_origin = origin(url)
        if deadline is not None and not self.timeout <= deadline <= 600:
            raise ValueError("invalid HTTP operation deadline")
        # Socket operations keep the short timeout; large bodies may take longer overall.
        deadline = time.monotonic() + (deadline or self.timeout)
        for _ in range(6):
            if origin(url) not in self.allowed or (sensitive and origin(url) != initial_origin):
                raise ValueError("URL or redirect is outside the authorized origin scope")
            if (origin(url) == self.auth_origin and self.auth_generation_check is not None
                    and not self.auth_generation_check(self.auth_generation)):
                raise ValueError("authentication has been forgotten for this origin")
            if self.requests >= 128 or time.monotonic() >= deadline:
                raise TimeoutError("bounded HTTP operation exhausted")
            self.requests += 1
            response, connection = self._open(url, method, body, self._headers(url, headers or {}, extended))
            try:
                status = response.status if hasattr(response, "status") else response.code
                response_headers: dict[str, str] = {}
                for key, value in response.headers.items():
                    lowered = key.lower()
                    response_headers[lowered] = (response_headers[lowered] + "\n" + value
                                                 if lowered in response_headers else value)
                if (follow_redirects and status in (301, 302, 303, 307, 308)
                        and response_headers.get("location")):
                    destination = clean_url(urllib.parse.urljoin(url, response_headers["location"]))
                    if origin(destination) not in self.allowed or (sensitive and origin(destination) != initial_origin):
                        raise ValueError("redirect destination is outside scope")
                    if method == "POST" and status in (301, 302, 303):
                        method, body, headers = "GET", None, {}
                    url = destination
                    continue
                length = response_headers.get("content-length")
                if method != "HEAD" and length is not None and (not length.isdigit() or int(length) > max_bytes):
                    raise ValueError("response exceeds declared download limit")
                size, chunks = 0, []
                digest = hashlib.sha256()
                reader = getattr(response, "read1", response.read)
                while method != "HEAD":
                    if time.monotonic() >= deadline:
                        raise TimeoutError("HTTP operation deadline exceeded")
                    chunk = reader(min(65_536, max_bytes + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("response exceeds download limit")
                    digest.update(chunk)
                    if sink is None:
                        chunks.append(chunk)
                    else:
                        sink.write(chunk)
                if method != "HEAD" and length is not None and size < int(length):
                    raise http.client.IncompleteRead(b"", int(length) - size)
                jar = self.jars[origin(url)]
                if len(jar) > 64 or any(len(cookie.value or "") > 4096 for cookie in jar):
                    raise ValueError("cookie state exceeds limits")
                # Do not return the platform's Set-Cookie or credential headers to solver
                # context. Challenge origins in extended mode return every header.
                if extended and origin(url) != self.auth_origin:
                    safe_headers = {key: value[:4096] for key, value in list(response_headers.items())[:64]}
                else:
                    safe_headers = {key: value for key, value in response_headers.items() if key in {
                        "content-type", "content-length", "retry-after", "location", "content-disposition",
                    }}
                return HTTPResult(url, status, safe_headers, b"".join(chunks), size, digest.hexdigest())
            finally:
                response.close()
                if connection is not None:
                    connection.close()
        raise ValueError("too many redirects")
