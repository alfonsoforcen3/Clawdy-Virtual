import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import platform_support as support, windows_service


class PlatformTests(unittest.TestCase):
    def test_paths_and_quoting(self):
        with patch.object(support.platform, 'system', return_value='Windows'):
            self.assertEqual(support.require_platform(), 'Windows')
            self.assertEqual(support.venv_python(Path('runtime')), Path('runtime/venv/Scripts/python.exe'))
            self.assertEqual(support.hook_command('C:/Program Files/python.exe', 'C:/Toy/traffic.py'),
                             '"C:/Program Files/python.exe" "C:/Toy/traffic.py"')
            with self.assertRaises(ValueError):
                support.hook_command('python', 'C:/%USERNAME%/traffic.py')
        with patch.object(support.platform, 'system', return_value='Darwin'):
            self.assertEqual(support.venv_python(Path('runtime')), Path('runtime/venv/bin/python'))
            self.assertIn("'", support.hook_command('/a space/python', '/toy/traffic.py'))

    def test_reject_unsupported(self):
        with patch.object(support.platform, 'system', return_value='Linux'):
            with self.assertRaises(RuntimeError):
                support.require_platform()

    def test_windows_install_and_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'checkout'; runtime = Path(directory) / 'runtime'
            (root / 'scripts').mkdir(parents=True); (root / 'web').mkdir()
            runtime.mkdir()
            for name in ('bridge.py', 'ble_transport.py', 'dashboard.py'):
                (root / 'scripts' / name).write_text('# test')
            python = runtime / 'python.exe'; python.with_name('pythonw.exe').touch()
            entry = Path(directory) / 'Startup' / 'TrafficLightBridge.vbs'
            with patch.object(windows_service, 'stop') as stop, \
                 patch.object(windows_service, 'startup_path', return_value=entry), \
                 patch.object(windows_service.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                 patch.object(windows_service.subprocess, 'Popen') as popen:
                windows_service.install(root, runtime, python, {'transport':'ble', 'ble_name':'Clawdy Demo1'})
                windows_service.install(root, runtime, python, {'transport':'ble', 'ble_name':'Clawdy Demo1'})
                self.assertEqual(popen.call_count, 2)
                self.assertEqual(len(list(entry.parent.iterdir())), 1)
                self.assertIn('WScript.Shell', entry.read_text())
                self.assertIn('Clawdy Demo1', (runtime / 'connection.json').read_text())
                windows_service.remove()
                self.assertFalse(entry.exists())
                self.assertEqual(stop.call_count, 3)
