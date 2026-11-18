"""Real protocol tests against only the servers provisioned by this lab."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "/repo")
from PIL import ImageGrab

from metis.blue.connections import ConnectionSession, execute
from metis.blue.ledger import ConnectionLedger
from metis.core.resources import init_owner_key, read_owner_key

LAB = Path("/lab")
os.umask(0o077)
deadline = time.monotonic() + 45
while time.monotonic() < deadline:
    if all((LAB / (role + ".ready")).exists() for role in ("desktop", "vpn")):
        break
    time.sleep(0.2)
else:
    raise RuntimeError("Disposable servers did not become ready")
store = ConnectionLedger(LAB / "state.sqlite3")
run = "disposable-protocol-lab"
init_owner_key(LAB / "state.sqlite3")
OWNER_KEY = read_owner_key(LAB / "state.sqlite3")
store.broker.configure("lab-session", 1, owner_key=OWNER_KEY)
rows = []


def profile(protocol, **kwargs):
    return dict(protocol=protocol, resource="lab-session", **kwargs)


ssh = profile(
    "ssh",
    host="desktop",
    user="analyst",
    identity_file="/lab/client_key",
    known_hosts_file="/lab/known_hosts",
)
rdp = profile(
    "rdp",
    host="desktop",
    user="analyst",
    password_env="METIS_LAB_PASSWORD",
    certificate_sha256=(LAB / "rdp-fingerprint.txt").read_text(),
)
vnc = profile("vnc", host="desktop", password_file="/lab/vnc.pass", ca_file="/lab/ca.crt")
vpn = profile("vpn", config_file="/lab/client.conf")
os.environ["METIS_LAB_PASSWORD"] = (LAB / "desktop.password").read_text()
os.environ["DISPLAY"] = ":99"
display = subprocess.Popen(
    ["Xvfb", ":99", "-screen", "0", "1280x900x24", "-ac"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)


def task(name):
    assert store.lease_task(run, name, {"lab-session": 1})


def grant(name, action):
    return store.permits.issue(
        run, name, "lab-session", action, "User requested self-hosted connection tests", owner_key=OWNER_KEY
    )["permit_id"]


def http(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=3) as response:
        return response.read().decode()


def capture(session, name, color):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        if session.process.poll() is not None:
            raise AssertionError("Desktop client exited: " + json.dumps(session.output()))
        frame = ImageGrab.grab(xdisplay=":99").convert("RGB")
        matching = sum(
            count
            for count, rgb in frame.getcolors(frame.width * frame.height)
            if max(abs(a - b) for a, b in zip(rgb, color)) < 6
        )
        if matching > 15000:
            frame.save(LAB / (name + ".png"))
            return {"frame_pixels": matching, "screenshot": name + ".png"}
        time.sleep(0.3)
    frame.save(LAB / (name + "-failed.png"))
    raise AssertionError("Expected server desktop pixels were not received: " + json.dumps(session.output()))


def check(name, fn):
    task(name)
    started = time.monotonic()
    try:
        detail = fn(name)
        row = {"name": name, "passed": True, "detail": detail}
    except Exception as exc:  # noqa: BLE001 -- every lab check is reported, never aborts the run
        row = {"name": name, "passed": False, "error": str(exc)}
    row["seconds"] = round(time.monotonic() - started, 3)
    try:
        store.finish_task(run, name)
    except ValueError as exc:
        row.update(passed=False, error=str(exc))
    rows.append(row)
    print(json.dumps(row), flush=True)


def ssh_login(name):
    result = execute(store, run, name, ssh, "identity")
    assert result["returncode"] == 0 and "analyst" in result["stdout"], result
    return {"identity": result["stdout"].strip()}


def ssh_bad_key(name):
    (LAB / "bad_known_hosts").write_text("desktop " + (LAB / "client_key.pub").read_text())
    result = execute(store, run, name, dict(ssh, known_hosts_file="/lab/bad_known_hosts"), "identity")
    assert result["returncode"] != 0 and "analyst" not in result["stdout"], result
    return {"rejected": True}


def no_grant(name):
    try:
        execute(store, run, name, rdp, "open")
    except PermissionError:
        return {"rejected_before_launch": True}
    raise AssertionError("Missing grant was accepted")


def rdp_bad_cert(name):
    result = execute(
        store, run, name, dict(rdp, certificate_sha256="00" * 32), "open", grant(name, "open"), timeout=15
    )
    assert result["returncode"] != 0 and not result["timed_out"], result
    return {"rejected": True}


def rdp_frame(name):
    with ConnectionSession(store, run, name, rdp, "open", grant(name, "open")) as session:
        result = capture(session, name, (32, 60, 96))
        try:
            store.finish_task(run, name)
        except ValueError:
            result["early_release_blocked"] = True
        else:
            raise AssertionError("Active desktop lease was released")
    result["client_stopped"] = session.process.poll() is not None
    return result


def vnc_frame(name):
    with ConnectionSession(store, run, name, vnc, "view") as session:
        return capture(session, name, (24, 92, 54))


def socks_http(name):
    config = dict(ssh, protocol="socks", local_port=11080)
    with ConnectionSession(store, run, name, config, "start", grant(name, "start")):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", 11080), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        result = subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--max-time",
                "5",
                "--noproxy",
                "",
                "--socks5-hostname",
                "127.0.0.1:11080",
                "http://desktop:8080",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0 and "METIS_DISPOSABLE_LAB_OK" in result.stdout, result.stderr
    try:
        socket.create_connection(("127.0.0.1", 11080), timeout=0.2)
    except OSError:
        return {"http_through_socks": True, "listener_closed": True}
    raise AssertionError("SOCKS listener survived cleanup")


def vpn_http(name):
    before = {link["ifname"] for link in json.loads(subprocess.check_output(["ip", "-j", "link", "show"]))}
    try:
        http("http://10.203.0.1:8080")
    except OSError:
        pass
    else:
        raise AssertionError("VPN fixture reachable before connection")
    with ConnectionSession(store, run, name, vpn, "start", grant(name, "start")) as session:
        session.wait_for("Initialization Sequence Completed", timeout=30)
        active = {
            link["ifname"] for link in json.loads(subprocess.check_output(["ip", "-j", "link", "show"]))
        }
        assert active - before == {"tun0"}, active - before
        assert "METIS_DISPOSABLE_LAB_OK" in http("http://10.203.0.1:8080")
    links = json.loads(subprocess.check_output(["ip", "-j", "link", "show"]))
    assert {link["ifname"] for link in links} == before, links
    return {"tls_tunnel_established": True, "http_over_tun": True, "tun_removed": True}


def vpn_bad_identity(name):
    path = LAB / "wrong-vpn.conf"
    path.write_text(
        (LAB / "client.conf")
        .read_text()
        .replace("verify-x509-name vpn name", "verify-x509-name wrong-server name")
        + "connect-retry-max 1\n"
    )
    result = execute(
        store, run, name, dict(vpn, config_file=str(path)), "start", grant(name, "start"), timeout=6
    )
    assert "Initialization Sequence Completed" not in result["stdout"] + result["stderr"]
    assert "VERIFY X509NAME ERROR" in result["stdout"] + result["stderr"], result
    return {"wrong_server_identity_rejected": True}


try:
    time.sleep(0.5)
    for name, fn in [
        ("ssh-login", ssh_login),
        ("ssh-host-key-rejection", ssh_bad_key),
        ("missing-grant", no_grant),
        ("rdp-cert-rejection", rdp_bad_cert),
        ("rdp-desktop", rdp_frame),
        ("vnc-desktop", vnc_frame),
        ("socks-traffic", socks_http),
        ("vpn-server-identity", vpn_bad_identity),
        ("vpn-traffic", vpn_http),
    ]:
        check(name, fn)
finally:
    display.terminate()
    display.wait(timeout=5)
    (LAB / "ledger.json").write_text(json.dumps(store.report(run), indent=2, default=str) + "\n")
    versions = subprocess.check_output(
        [
            "dpkg-query",
            "-W",
            "-f=${Package} ${Version}\n",
            "xrdp",
            "freerdp2-x11",
            "openvpn",
            "openssh-client",
            "tigervnc-viewer",
        ],
        text=True,
    )
    (LAB / "results.json").write_text(
        json.dumps(
            {"at": datetime.now(UTC).isoformat(), "run": run, "versions": versions, "tests": rows}, indent=2
        )
        + "\n"
    )
raise SystemExit(0 if len(rows) == 9 and all(r["passed"] for r in rows) else 1)
