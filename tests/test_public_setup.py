"""Verify the two customer entry points without touching the host profile."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PublicSetupTests(unittest.TestCase):
    def test_fresh_checkout_preflight_does_not_write_or_scan(self):
        with tempfile.TemporaryDirectory(prefix="Clawdy test profile ") as directory:
            profile = Path(directory)
            env = {**os.environ, "HOME": directory, "USERPROFILE": directory}
            if sys.platform == "win32":
                env.update(APPDATA=directory, LOCALAPPDATA=directory)
            command = [sys.executable, "-B", str(ROOT / "install.py"), "--onboard",
                       "--preflight", "--json"]
            result = subprocess.run(command, env=env, cwd=ROOT, capture_output=True,
                                    check=True, text=True, timeout=15)
            report = json.loads(result.stdout)
            self.assertFalse(report["mutations"])
            self.assertFalse(report["bluetooth_scanned"])
            self.assertEqual(report["runtime_transport"], "ble")
            self.assertEqual(report["saved_connection"], "absent")
            self.assertEqual(list(profile.iterdir()), [])

    def test_local_bridge_observes_status_without_touching_hardware(self):
        try:
            import serial
        except ModuleNotFoundError:
            self.skipTest("pyserial is required to exercise the bridge")
        from scripts import bridge

        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]

            ready = threading.Event()
            failures = []

            def run_bridge():
                try:
                    bridge.run_bridge()
                except Exception as error:
                    failures.append(error)
                    ready.set()

            def send(payload):
                with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
                    client.sendall(json.dumps(payload).encode() + b"\n")
                    with client.makefile("rb") as response:
                        return json.loads(response.readline())

            with patch.multiple(bridge, TRANSPORT="local", TCP_PORT=port,
                                STATE_FILE=str(Path(directory) / "sessions.json"),
                                active_sessions={}, current_hardware_state="G",
                                bluetooth_link=None, ser_conn=None, pending_transition=None), \
                    patch.object(bridge, "restore_sessions", side_effect=ready.set), \
                    patch.object(bridge.Dashboard, "start") as dashboard_start, \
                    patch.object(bridge, "hardware_watchdog") as watchdog:
                runner = threading.Thread(target=run_bridge, daemon=True)
                runner.start()
                try:
                    self.assertTrue(ready.wait(3))
                    self.assertFalse(failures)
                    idle = send({"action": "status"})
                    self.assertEqual(idle["aggregate"], "O")
                    self.assertFalse(idle["hardware_connected"])
                    send({"session_id": "codex:fixture", "state": "Y"})
                    working = send({"action": "status"})
                    self.assertEqual(working["active_sessions"], {"codex:fixture": "Y"})
                    self.assertEqual(working["aggregate"], "Y")
                    self.assertEqual(working["transport"], "local")
                    self.assertEqual(send({"action": "hardware_test", "state": "Y"})["status"],
                                     "no_hardware")
                    watchdog.assert_not_called()
                    dashboard_start.assert_not_called()
                finally:
                    if ready.is_set() and not failures:
                        send({"action": "shutdown"})
                    runner.join(4)
                self.assertFalse(runner.is_alive())
                self.assertFalse(failures)
