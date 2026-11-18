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


class VirtualLiveSetupTests(unittest.TestCase):
    def test_reuses_the_existing_bridge_and_configures_approved_hooks(self):
        from scripts import setup_virtual as setup

        live = {'status': 'ok', 'aggregate': 'G', 'active_sessions': {}}
        with patch.object(setup, 'require_platform', return_value='Windows'), \
                patch.object(setup.virtual_clawdy, 'read_status', return_value=live), \
                patch.object(setup, 'prepare_hooks', return_value=Path('python')), \
                patch.object(setup.subprocess, 'run') as run, \
                patch.object(setup.codex_setup, 'install_service') as install, \
                patch.object(setup.provider_setup, 'preflight') as preflight, \
                patch.object(setup.provider_setup, 'configure') as configure:
            self.assertEqual(setup.configure_live(['gemini']), 'reuse_existing')
        run.assert_not_called()
        install.assert_not_called()
        preflight.assert_called_once_with(['gemini'])
        configure.assert_called_once_with('gemini')

    def test_offline_saved_toy_and_unknown_listener_block_mutation(self):
        from scripts import setup_virtual as setup

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = base / 'connection.json'
            original = '{"transport":"ble","ble_name":"Fixture","device_id":"01234567"}'
            config.write_text(original, encoding='utf-8')
            with patch.object(setup, 'RUNTIME', base), \
                    patch.object(setup, 'require_platform', return_value='Darwin'), \
                    patch.object(setup.provider_setup, 'preflight'), \
                    patch.object(setup, 'prepare_hooks') as prepare:
                with patch.object(setup.virtual_clawdy, 'read_status', side_effect=ConnectionRefusedError):
                    with self.assertRaisesRegex(RuntimeError, 'saved bridge'):
                        setup.configure_live(['codex'])
                with patch.object(setup.virtual_clawdy, 'read_status', return_value={'status': 'other'}):
                    with self.assertRaisesRegex(RuntimeError, 'compatible'):
                        setup.configure_live(['codex'])
                prepare.assert_not_called()
            self.assertEqual(config.read_text(encoding='utf-8'), original)

    def test_fresh_virtual_setup_waits_for_local_bridge_before_configuring_hooks(self):
        from scripts import setup_virtual as setup

        events = []
        python = Path('sandbox python')
        with patch.object(setup, 'require_platform', return_value='Darwin'), \
                patch.object(setup, 'bridge_plan', side_effect=['start_local', 'start_local', 'reuse_existing']), \
                patch.object(setup, 'prepare_hooks', return_value=python), \
                patch.object(setup.subprocess, 'run'), \
                patch.object(setup.provider_setup, 'preflight'), \
                patch.object(setup.codex_setup, 'install_service',
                             side_effect=lambda transport, **kw: events.append((transport, kw['python']))), \
                patch.object(setup.provider_setup, 'configure', side_effect=events.append):
            self.assertEqual(setup.configure_live(['claude', 'cursor']), 'start_local')
        self.assertEqual(events, [('local', python), 'claude', 'cursor'])
