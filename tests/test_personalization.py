"""Buyer naming, BLE reconnect and saved-profile checks using isolated fixtures."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import install
from scripts import device_identity, onboard


class PersonalizationTests(unittest.TestCase):
    uid = '0123456789ABCDEF'

    def report(self, name='Factory Clawdy', **updates):
        report = dict(firmware='traffic-esp32c3-v1', transport='ble',
                      ble_name=name, device_id=self.uid, identity_protocol=1,
                      rename_supported=True)
        report.update(updates)
        return report

    def test_plain_install_prompts_and_saves_personalization_on_mac_and_windows(self):
        cases = [('Darwin', 'Ada', True), ('Windows', 'Ada', True),
                 ('Darwin', '/keep', True), ('Windows', 'Ada', False)]
        for system, choice, rename_supported in cases:
            with self.subTest(system=system, choice=choice, rename_supported=rename_supported), \
                    tempfile.TemporaryDirectory(prefix='Buyer profile ') as folder:
                runtime = Path(folder) / 'runtime'
                renaming = choice != '/keep' and rename_supported
                target = (device_identity.make_device_name('Buyer Laptop', choice, self.uid)
                          if renaming else 'Factory Clawdy')
                selected = {'name': 'Factory Clawdy', 'address': 'FIXTURE-ONLY'}

                def save_profile(command, **kwargs):
                    runtime.mkdir(parents=True, exist_ok=True)
                    self.assertEqual(command[-2:], ['--providers', 'codex'])
                    self.assertEqual(command[command.index('--ble-name') + 1], target)
                    self.assertEqual(command[command.index('--device-id') + 1], self.uid)
                    (runtime / 'connection.json').write_text(json.dumps({
                        'transport': 'ble', 'ble_name': target, 'device_id': self.uid}), encoding='utf-8')

                responses = ['codex', '', choice, '1', 'y']
                if not rename_supported:
                    responses.append('y')  # Explicitly accept the firmware's current name.
                answers = Mock(side_effect=responses)
                prompt = patch('builtins.input', answers)
                choose, select, confirm = onboard.choose_providers, onboard.select_device, onboard.confirm
                rename = AsyncMock(return_value={'ok': True, 'persistent': True, 'ble_name': target})
                contexts = [
                    patch.object(onboard, 'RUNTIME', runtime),
                    patch.object(install, 'RUNTIME', runtime),
                    patch('sys.argv', ['install.py']),
                    patch('sys.stdin.isatty', return_value=True),
                    patch.object(onboard.socket, 'gethostname', return_value='Buyer Laptop'),
                    patch.object(onboard, 'require_platform', return_value=system),
                    patch.object(onboard, 'ensure_dependencies', return_value=False),
                    patch.object(onboard, 'choose_providers', side_effect=lambda args: choose(args, input_fn=answers)),
                    patch.object(onboard, 'select_device', side_effect=lambda *args, **kw: select(*args, **kw, input_fn=answers)),
                    patch.object(onboard, 'confirm', side_effect=lambda *args: confirm(*args, input_fn=answers)),
                    patch.object(onboard.provider_setup, 'detect', return_value={'codex': ['fixture'], 'claude': ['fixture']}),
                    patch.object(onboard.provider_setup, 'preflight'),
                    patch.object(device_identity, 'discover_candidates', new=AsyncMock(return_value=[selected])),
                    patch.object(device_identity, 'inspect_device', new=AsyncMock(return_value=self.report(rename_supported=rename_supported))),
                    patch.object(device_identity, 'identify_device', new=AsyncMock()),
                    patch.object(device_identity, 'rename_device', new=rename),
                    patch.object(onboard, 'human_confirmation', return_value=True),
                    patch.object(onboard.subprocess, 'run', side_effect=save_profile),
                    patch.object(onboard, 'verify_install', return_value=True),
                    contextlib.redirect_stdout(io.StringIO()),
                ]
                with contextlib.ExitStack() as stack:
                    for context in contexts:
                        stack.enter_context(context)
                    prompt_mock = stack.enter_context(prompt)
                    self.assertEqual(install.main(), 0)
                self.assertEqual(sum('Your first name or chosen Clawdy name' in call.args[0]
                                     for call in prompt_mock.call_args_list), 2)
                if renaming:
                    rename.assert_awaited_once_with('FIXTURE-ONLY', target, self.uid)
                else:
                    rename.assert_not_awaited()
                record = json.loads(next((runtime / 'onboarding').glob('*.json')).read_text())
                self.assertEqual(record['device_id'], self.uid)
                self.assertEqual(record['verification']['saved_name_reconnect'], 'passed' if renaming else 'not_requested')
                self.assertEqual(record['verification']['host_profile'], 'passed')
                self.assertEqual(record['providers'], ['codex'])
                self.assertFalse(record['customer_ready'])

    def test_rename_reconnect_rechecks_identity_and_name_after_ack(self):
        target = 'Ada-Clawdy-89ABCDEF'
        ack = dict(identity_ack='rename', device_id=self.uid, ok=True,
                   persistent=True, ble_name=target)
        for reports, error in (([self.report(), self.report(target)], None),
                               ([self.report(), self.report(), self.report(target)], None),
                               ([self.report(), OSError('restarting'), self.report(target)], None),
                               ([self.report(), self.report(target, device_id='FEDCBA9876543210')], ValueError)):
            with self.subTest(error=error, reports=len(reports)), \
                    patch.object(device_identity, 'inspect_device', new=AsyncMock(side_effect=reports)) as inspect, \
                    patch.object(device_identity, '_transaction', new=AsyncMock(return_value=ack)), \
                    patch.object(device_identity.asyncio, 'sleep', new=AsyncMock()):
                if error:
                    with self.assertRaisesRegex(error, 'identity changed'):
                        asyncio.run(device_identity.rename_device('FIXTURE', target, self.uid))
                else:
                    self.assertEqual(asyncio.run(device_identity.rename_device('FIXTURE', target, self.uid)), ack)
                self.assertGreaterEqual(inspect.await_count, 2)
                self.assertTrue(all(call.args[0] == 'FIXTURE' for call in inspect.await_args_list))

    def test_unconfirmed_rename_never_claims_reconnect_and_readback_is_bounded(self):
        ack = dict(ok=True, persistent=True, ble_name='Ada', device_id=self.uid)
        with patch.object(device_identity, 'inspect_device', new=AsyncMock(return_value=self.report())), \
                patch.object(device_identity, '_transaction', new=AsyncMock(return_value=ack)), \
                patch.object(device_identity, 'time', SimpleNamespace(monotonic=Mock(side_effect=[0, 13]))):
            with self.assertRaisesRegex(TimeoutError, 'read back on reconnect'):
                asyncio.run(device_identity.rename_device('FIXTURE', 'Ada', self.uid))

    def test_profile_readback_rejects_missing_wrong_name_transport_or_identity(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(onboard, 'RUNTIME', Path(folder)):
            path = Path(folder) / 'connection.json'
            with self.assertRaisesRegex(RuntimeError, 'profile does not match'):
                onboard.verify_saved_connection('Ada', self.uid)
            for changes in ({'ble_name': 'old'}, {'device_id': 'FEDCBA98'}, {'transport': 'local'}, {}):
                value = dict(transport='ble', ble_name='Ada', device_id=self.uid)
                value.update(changes)
                path.write_text(json.dumps(value), encoding='utf-8')
                if changes:
                    with self.assertRaisesRegex(RuntimeError, 'profile does not match'):
                        onboard.verify_saved_connection('Ada', self.uid)
                else:
                    onboard.verify_saved_connection('Ada', self.uid)
