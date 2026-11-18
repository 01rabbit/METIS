"""Disposable protocol servers. All credentials are generated into the private lab mount."""

import os
import secrets
import shutil
import signal
import subprocess
import time
from pathlib import Path

LAB = Path("/lab")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def initialize():
    os.umask(0o077)
    run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(LAB / "ssh_host_key"))
    run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(LAB / "client_key"))
    (LAB / "known_hosts").write_text("desktop " + (LAB / "ssh_host_key.pub").read_text())
    (LAB / "desktop.password").write_text(secrets.token_urlsafe(24))
    password = secrets.token_urlsafe(8)[:8]
    (LAB / "vnc.pass").write_bytes(run("tigervncpasswd", "-f", input=(password + "\n").encode()).stdout)
    run(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-subj",
        "/CN=METIS Disposable Lab CA",
        "-keyout",
        str(LAB / "ca.key"),
        "-out",
        str(LAB / "ca.crt"),
    )
    for name, usage in (("desktop", "serverAuth"), ("vpn", "serverAuth"), ("client", "clientAuth")):
        run(
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=" + name,
            "-keyout",
            str(LAB / (name + ".key")),
            "-out",
            str(LAB / (name + ".csr")),
        )
        ext = LAB / (name + ".ext")
        ext.write_text(
            "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage="
            + usage
            + "\nsubjectAltName=DNS:"
            + name
            + "\n"
        )
        run(
            "openssl",
            "x509",
            "-req",
            "-in",
            str(LAB / (name + ".csr")),
            "-CA",
            str(LAB / "ca.crt"),
            "-CAkey",
            str(LAB / "ca.key"),
            "-CAcreateserial",
            "-days",
            "2",
            "-extfile",
            str(ext),
            "-out",
            str(LAB / (name + ".crt")),
        )
    fingerprint = (
        run("openssl", "x509", "-in", str(LAB / "desktop.crt"), "-noout", "-fingerprint", "-sha256")
        .stdout.decode()
        .strip()
        .split("=")[1]
    )
    (LAB / "rdp-fingerprint.txt").write_text(fingerprint)
    run("openvpn", "--genkey", "secret", str(LAB / "tls.key"))
    common = "proto udp\ndev tun\nca /lab/ca.crt\ntls-crypt /lab/tls.key\ndata-ciphers AES-256-GCM\ndisable-dco\nverb 3\n"
    (LAB / "server.conf").write_text(
        common
        + "port 1194\ntopology subnet\nserver 10.203.0.0 255.255.255.0\ncert /lab/vpn.crt\nkey /lab/vpn.key\ndh none\nremote-cert-tls client\n"
    )
    (LAB / "client.conf").write_text(
        common
        + "client\nremote vpn 1194\nnobind\ncert /lab/client.crt\nkey /lab/client.key\nremote-cert-tls server\nverify-x509-name vpn name\nroute-nopull\n"
    )
    fixture = LAB / "fixture"
    fixture.mkdir()
    (fixture / "index.html").write_text("METIS_DISPOSABLE_LAB_OK\n")
    print("Disposable keys and certificates generated; no credentials printed.", flush=True)


children = []
handles = []


def launch(name, args, **kwargs):
    log = (LAB / (name + ".log")).open("w")
    handles.append(log)
    child = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, **kwargs)
    children.append(child)
    return child


def desktop():
    password = (LAB / "desktop.password").read_text()
    run("chpasswd", input=("analyst:" + password + "\n").encode())
    sshdir = Path("/home/analyst/.ssh")
    sshdir.mkdir(mode=0o700, exist_ok=True)
    shutil.copy(LAB / "client_key.pub", sshdir / "authorized_keys")
    run("chown", "-R", "analyst:analyst", str(sshdir))
    (sshdir / "authorized_keys").chmod(0o600)
    Path("/etc/ssh/sshd_config").write_text(
        "HostKey /lab/ssh_host_key\nPasswordAuthentication no\nPermitRootLogin no\nAllowUsers analyst\nAllowTcpForwarding yes\nSubsystem sftp internal-sftp\n"
    )
    launch("sshd", ["/usr/sbin/sshd", "-D", "-e"])
    for source, target in (("desktop.crt", "cert.pem"), ("desktop.key", "key.pem")):
        target = Path("/etc/xrdp") / target
        if target.is_symlink():
            target.unlink()
        shutil.copy(LAB / source, target)
        target.chmod(0o640)
        run("chown", "root:xrdp", str(target))
    startwm = Path("/etc/xrdp/startwm.sh")
    startwm.write_text(
        '#!/bin/sh\nxsetroot -solid "#203c60"\nexec xterm -geometry 90x25+40+40 -bg "#203c60" -fg white -e sh -c "printf METIS_RDP_DESKTOP_READY; exec sleep 3600"\n'
    )
    startwm.chmod(0o755)
    launch("sesman", ["/usr/sbin/xrdp-sesman", "--nodaemon"])
    launch("xrdp", ["/usr/sbin/xrdp", "--nodaemon"])
    launch(
        "vnc-server",
        [
            "Xtigervnc",
            ":1",
            "-localhost",
            "no",
            "-rfbport",
            "5900",
            "-geometry",
            "1024x768",
            "-depth",
            "24",
            "-SecurityTypes",
            "X509Vnc",
            "-PasswordFile",
            "/lab/vnc.pass",
            "-X509Cert",
            "/lab/desktop.crt",
            "-X509Key",
            "/lab/desktop.key",
        ],
    )
    time.sleep(1)
    env = dict(os.environ, DISPLAY=":1")
    run("xsetroot", "-solid", "#185c36", env=env)
    launch(
        "vnc-desktop",
        [
            "xterm",
            "-geometry",
            "90x25+40+40",
            "-bg",
            "#185c36",
            "-fg",
            "white",
            "-e",
            "sh",
            "-c",
            "printf METIS_VNC_DESKTOP_READY; exec sleep 3600",
        ],
        env=env,
    )
    launch("http", ["python3", "-m", "http.server", "8080", "--directory", "/lab/fixture"])


def vpn():
    launch("vpn-server", ["openvpn", "--config", "/lab/server.conf"])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if "Initialization Sequence Completed" in (LAB / "vpn-server.log").read_text():
            break
        if children[0].poll() is not None:
            raise RuntimeError("VPN server stopped")
        time.sleep(0.2)
    else:
        raise RuntimeError("VPN server not ready")
    # Accessible only through the real tunnel, not the Docker interface.
    launch(
        "vpn-http",
        ["python3", "-m", "http.server", "8080", "--bind", "10.203.0.1", "--directory", "/lab/fixture"],
    )


def stop(*args):
    raise KeyboardInterrupt


if __name__ == "__main__":
    role = os.environ.get("METIS_LAB_ROLE", "init")
    if role == "init":
        initialize()
    else:
        signal.signal(signal.SIGTERM, stop)
        try:
            {"desktop": desktop, "vpn": vpn}[role]()
            (LAB / (role + ".ready")).touch()
            while all(child.poll() is None for child in children):
                time.sleep(0.2)
            raise RuntimeError("A test server stopped unexpectedly")
        except KeyboardInterrupt:
            pass
        finally:
            for child in children:
                child.terminate()
            for child in children:
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            for log in handles:
                log.close()
