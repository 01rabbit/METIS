"""Connection profiles and foreground client sessions under a ledger lease."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metis.blue.connections import ConnectionSession, build, execute, validate_vpn
from metis.blue.ledger import ConnectionLedger


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.store = ConnectionLedger(self.path / "db")
        self.run = "connection-test"
        self.store.broker.configure("vm", 1)
        self.store.lease_task(self.run, "a", {"vm": 1})
        self.config = {"protocol": "ssh", "host": "example.invalid", "resource": "vm"}

    def tearDown(self):
        self.tmp.cleanup()

    def spec(self, code):
        spec = build(self.config, "identity")
        spec["argv"] = [sys.executable, "-c", code]
        return spec

    def test_live_consumer_prevents_lease_release_and_extra_session(self):
        spec = self.spec('import time; print("ready",flush=True); time.sleep(30)')
        with patch("metis.blue.connections.build", return_value=spec):
            with ConnectionSession(self.store, self.run, "a", self.config, "identity") as session:
                session.wait_for("ready", 2)
                with self.assertRaises(ValueError):
                    self.store.finish_task(self.run, "a")
                with self.assertRaises(PermissionError):
                    ConnectionSession(self.store, self.run, "a", self.config, "identity").start()
            self.assertIsNotNone(session.process.poll())
        self.store.finish_task(self.run, "a")
        self.assertEqual(self.store.report(self.run)["connections"][0]["state"], "stopped")

    def test_timeout_stops_child_group_and_redacts_output(self):
        code = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); print("private-example",flush=True); time.sleep(30)'
        spec = self.spec(code)
        spec["env"] = {"CUSTOM": "private-example"}
        with patch("metis.blue.connections.build", return_value=spec):
            result = execute(self.store, self.run, "a", self.config, "identity", timeout=0.1)
        self.assertTrue(result["timed_out"])
        self.assertNotIn("private-example", str(result))
        self.assertEqual(self.store.report(self.run)["connections"][0]["state"], "stopped")

    def test_failed_launch_does_not_strand_connection(self):
        spec = self.spec("")
        spec["argv"] = ["/missing/metis-client"]
        with patch("metis.blue.connections.build", return_value=spec), self.assertRaises(FileNotFoundError):
            execute(self.store, self.run, "a", self.config, "identity")
        self.store.finish_task(self.run, "a")

    def test_rdp_credentials_are_stdin_and_certificate_pinned(self):
        with patch.dict(os.environ, {"CUSTOM_LOGIN": "private-example"}):
            spec = build(
                {
                    "protocol": "rdp",
                    "host": "::1",
                    "password_env": "CUSTOM_LOGIN",
                    "certificate_sha256": "ab" * 32,
                },
                "open",
            )
        self.assertEqual(spec["stdin"], "private-example\n")
        self.assertNotIn("private-example", str(spec["argv"]))
        self.assertIn("-clipboard", spec["argv"])
        self.assertIn("/v:[::1]:3389", spec["argv"])
        self.assertIn("/cert:fingerprint:sha256:" + ":".join(["ab"] * 32), spec["argv"])

    def test_vpn_rejects_detach_and_external_execution(self):
        config = self.path / "vpn.conf"
        for directive in (
            "daemon",
            "--daemon",
            "config other.conf",
            "plugin x.so",
            "up script.sh",
            "management localhost 7505",
        ):
            config.write_text("client\n" + directive + "\n")
            with self.assertRaises(ValueError):
                validate_vpn(config)
        config.write_text("client\n<ca>\nsynthetic certificate data\n</ca>\n")
        validate_vpn(config)


class WritePermitTests(unittest.TestCase):
    def test_state_changing_session_needs_an_exact_permit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConnectionLedger(Path(tmp) / "db")
            run = "permit-test"
            store.lease_task(run, "a", {"vm": 1})
            config = {"protocol": "vnc", "host": "example.invalid", "resource": "vm"}
            spec = build(config, "control")
            spec["argv"] = [sys.executable, "-c", 'print("ok")']
            with patch("metis.blue.connections.build", return_value=spec):
                with self.assertRaises(PermissionError):
                    execute(store, run, "a", config, "control")
                wrong = store.permits.issue(run, "a", "vm", "view", "user asked to watch")["permit_id"]
                with self.assertRaises(PermissionError):
                    execute(store, run, "a", config, "control", wrong)
                permit = store.permits.issue(run, "a", "vm", "control", "user asked to operate the desktop")[
                    "permit_id"
                ]
                self.assertEqual(
                    execute(store, run, "a", config, "control", permit, timeout=5)["returncode"], 0
                )
                with self.assertRaises(PermissionError):
                    execute(store, run, "a", config, "control", permit)
            store.finish_task(run, "a")
            self.assertEqual(store.broker.status()["leases"], [])
