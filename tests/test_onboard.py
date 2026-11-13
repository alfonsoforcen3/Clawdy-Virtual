import contextlib
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
from scripts import onboard


class OnboardTests(unittest.TestCase):
    def test_launch_banner_explains_scope_changes_and_removal(self):
        with patch.object(onboard.platform, 'system', return_value='Windows'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            onboard.WizardUI(no_color=True).banner('fixture')
        text = output.getvalue()
        self.assertIn('Physical Clawdy setup', text)
        self.assertIn('docs/TRY_VIRTUAL_CLAWDY.md', text)
        self.assertIn('After approval', text)
        self.assertIn('only your chosen app hooks', text)
        self.assertIn('py -3 manage_hooks.py disable', text)

    def test_launch_preflight_json_keeps_stdout_machine_readable(self):
        with patch.object(onboard.platform, 'system', return_value='Darwin'), \
                patch.object(onboard.provider_setup, 'detect', return_value={}), \
                patch.object(onboard.importlib.util, 'find_spec', return_value=None), \
                patch.object(onboard.subprocess, 'run', side_effect=AssertionError('Offline only')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(onboard.main(['--preflight', '--json']), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['setup_target'], 'physical_clawdy')
        self.assertFalse(report['mutations'])
        self.assertFalse(report['customer_ready'])

    def launch_preflight(self, system='Darwin', saved=None, blocked=False, dependencies=True):
        if saved is not None:
            self.runtime.mkdir(parents=True, exist_ok=True)
            (self.runtime / 'connection.json').write_text(saved, encoding='utf-8')
        with patch.object(onboard.platform, 'system', return_value=system), \
                patch.object(onboard.provider_setup, 'detect', return_value={'codex': ['fixture']}), \
                patch.object(onboard.provider_setup, 'preflight', side_effect=RuntimeError('policy disabled') if blocked else None), \
                patch.object(onboard.importlib.util, 'find_spec', return_value=object() if dependencies else None), \
                patch.object(onboard.subprocess, 'run', side_effect=AssertionError('Preflight must stay offline')):
            return onboard.preflight_report(onboard.parser().parse_args([]))

    def test_launch_preflight_routes_physical_and_virtual_without_mutations(self):
        report = self.launch_preflight(system='Windows', dependencies=False)
        steps = ' '.join(report['next_steps'])
        self.assertEqual(report['setup_target'], 'physical_clawdy')
        self.assertEqual(report['virtual_preview_guide'], 'docs/TRY_VIRTUAL_CLAWDY.md')
        self.assertIn('py -3 install.py --onboard', steps)
        self.assertIn('obtain approval first', steps)
        self.assertIn('Detection is not a real-provider acceptance test', steps)
        self.assertFalse(report['mutations'])
        self.assertFalse(report['bluetooth_scanned'])
        self.assertFalse(report['customer_ready'])
        self.assertFalse(self.runtime.exists())

    def test_launch_preflight_does_not_recommend_discovery_on_unsupported_platform(self):
        report = self.launch_preflight(system='Linux')
        self.assertFalse(report['platform_supported'])
        self.assertNotIn('--list-devices', ' '.join(report['next_steps']))
        self.assertIn('Linux/WSL is unsupported', ' '.join(report['next_steps']))

    def test_launch_preflight_prioritizes_saved_profile_recovery(self):
        report = self.launch_preflight(saved='{invalid')
        self.assertEqual(report['saved_connection'], 'recovery_required')
        self.assertIn('do not delete it automatically', ' '.join(report['next_steps']))
        self.assertNotIn('--list-devices', ' '.join(report['next_steps']))
        self.assertEqual((self.runtime / 'connection.json').read_text(encoding='utf-8'), '{invalid')

    def test_launch_preflight_keeps_blocked_provider_policy_visible(self):
        report = self.launch_preflight(blocked=True)
        self.assertEqual(report['providers']['codex']['hook_policy'], 'blocked')
        self.assertIn('Review blocked app policies: codex', ' '.join(report['next_steps']))
        self.assertIn('do not bypass', ' '.join(report['next_steps']))

    def test_launch_preflight_old_python_stops_before_discovery_guidance(self):
        with patch.object(onboard.sys, 'version_info', (3, 8)):
            report = self.launch_preflight()
        self.assertFalse(report['python_supported'])
        self.assertIn('Python 3.9 or newer', ' '.join(report['next_steps']))
        self.assertNotIn('--list-devices', ' '.join(report['next_steps']))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.runtime = Path(temporary.name)/'runtime'
        runtime = patch.object(onboard, 'RUNTIME', self.runtime)
        runtime.start()
        self.addCleanup(runtime.stop)
        # A missed workflow mock must fail immediately, never touch Bluetooth.
        for operation in ('discover_candidates', 'inspect_device', 'identify_device', 'rename_device'):
            guard = patch.object(onboard.device_identity, operation,
                                 new=AsyncMock(side_effect=AssertionError('Unexpected real BLE operation: ' + operation)))
            guard.start()
            self.addCleanup(guard.stop)

    def test_color_requires_capable_tty_and_respects_plain_output(self):
        with patch.dict(onboard.os.environ, {'TERM':'xterm'}, clear=True), \
                patch.object(onboard.os, 'name', 'posix'), \
                patch('sys.stdout.isatty', return_value=True):
            self.assertIn('\x1b[', onboard.WizardUI().paint('Clawdy', '36'))
            self.assertNotIn('\x1b[', onboard.WizardUI(no_color=True).paint('Clawdy', '36'))
            with patch.dict(onboard.os.environ, {'NO_COLOR':''}):
                self.assertNotIn('\x1b[', onboard.WizardUI().paint('Clawdy', '36'))
            with patch.dict(onboard.os.environ, {'TERM':'dumb'}):
                self.assertFalse(onboard.WizardUI().color)
        with patch('sys.stdout.isatty', return_value=False):
            self.assertFalse(onboard.WizardUI().color)
        with patch.dict(onboard.os.environ, {}, clear=True), \
                patch.object(onboard.os, 'name', 'nt'), \
                patch('sys.stdout.isatty', return_value=True):
            self.assertFalse(onboard.WizardUI().color)
            with patch.dict(onboard.os.environ, {'WT_SESSION':'test'}):
                self.assertTrue(onboard.WizardUI().color)

    def test_untrusted_device_names_cannot_inject_terminal_controls(self):
        devices = [{'name':'Toy\x1b[31m\nother', 'address':'A\rB'}]
        with patch('sys.stdin.isatty', return_value=True), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(onboard.select_device(devices, input_fn=lambda _: '1'), devices[0])
        self.assertNotIn('\x1b', output.getvalue())
        self.assertNotIn('\r', output.getvalue())
        self.assertIn(r'\x1b[31m\x0aother', output.getvalue())

    def test_plain_preview_keeps_json_plan_and_explicit_pending_identity(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = onboard.main(['--dry-run','--no-color','--ble-name','Factory',
                                   '--nickname','Pip','--providers','codex'])
        text = output.getvalue()
        self.assertEqual(result,0)
        self.assertNotIn('\x1b',text)
        self.assertIn('C L A W D Y',text)
        self.assertIn('Preview only: no Bluetooth scan, downloads or changes.',text)
        self.assertIn('2/5',text)
        plan = json.loads(text[text.index('{'):])
        self.assertIsNone(plan['installer'])
        self.assertTrue(plan['requested_name'].endswith('<UID8>'))
        self.assertNotIn('Clawdy is linked',text)

    def test_numbered_mocked_setup_never_claims_verification_when_skipped(self):
        identity = self.workflow_identity()
        with patch.object(onboard,'device_identity',identity), \
                patch.object(onboard,'ensure_dependencies',return_value=False), \
                patch.object(onboard,'require_platform',return_value='Darwin'), \
                patch.object(onboard.subprocess,'run'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = onboard.main(['--yes','--no-color','--ble-name','Factory',
                '--nickname','Pip','--no-hooks','--identified-device','--skip-verification'])
        text = output.getvalue()
        self.assertEqual(result,0)
        offsets = [text.index(str(i)+'/5') for i in range(1,6)]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn('[PENDING]',text)
        self.assertIn('remain unverified',text)
        self.assertNotIn('Clawdy is linked',text)

    def setup_inputs(self):
        args = onboard.parser().parse_args(['--nickname','Pip','--laptop-name','TestMac','--skip-verification'])
        selected = {'name':'Factory','address':'MOCK-ONLY'}
        report = {'ble_name':'Factory','device_id':'0123456789ABCDEF'}
        return args, selected, report

    def recovery_state(self):
        files = list((self.runtime/'onboarding').glob('*.json'))
        self.assertEqual(len(files),1)
        return json.loads(files[0].read_text())

    def test_lost_rename_ack_keeps_recovery_record_and_never_installs(self):
        args,selected,report = self.setup_inputs()
        with patch.object(onboard.device_identity,'rename_device',new=AsyncMock(side_effect=TimeoutError('ack lost'))), \
                patch.object(onboard.subprocess,'run') as run, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(TimeoutError,'ack lost'):
                onboard.complete_setup(args,onboard.WizardUI(True),selected,report,['codex'],'Pip')
        run.assert_not_called()
        record = self.recovery_state()
        self.assertEqual(record['phase'],'rename_requested')
        self.assertEqual(record['previous_name'],'Factory')
        self.assertIn('Look for either:',output.getvalue())
        self.assertIn(record['target_name'],output.getvalue())
        self.assertIn('no rollback was attempted',output.getvalue())

    def test_rename_then_failed_installer_preserves_name_and_partial_status(self):
        args,selected,report = self.setup_inputs()
        target = onboard.device_identity.make_device_name('TestMac','Pip',report['device_id'])
        ack = {'ok':True,'persistent':True,'ble_name':target}
        for failure in (onboard.subprocess.CalledProcessError(7,['installer']),
                        onboard.subprocess.TimeoutExpired(['installer'],onboard.INSTALL_TIMEOUT), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(onboard.device_identity,'rename_device',new=AsyncMock(return_value=ack)), \
                    patch.object(onboard.subprocess,'run',side_effect=failure) as run, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises((RuntimeError,KeyboardInterrupt)):
                    onboard.complete_setup(args,onboard.WizardUI(True),selected,report,['codex'],'Pip')
                self.assertEqual(run.call_args.kwargs['timeout'],onboard.INSTALL_TIMEOUT)
                record = self.recovery_state()
                self.assertEqual(record['phase'],'installing')
                self.assertEqual(record['target_name'],target)
                self.assertIn('--keep-name',output.getvalue())
                self.assertIn('child processes or a service may remain',output.getvalue())
                self.assertNotIn('Clawdy is linked',output.getvalue())

    def test_checkpoint_failure_prevents_device_or_host_changes(self):
        args,selected,report = self.setup_inputs()
        with patch.object(onboard.RecoveryRecord,'save',side_effect=OSError('disk full')), \
                patch.object(onboard.device_identity,'rename_device',new=AsyncMock()) as rename, \
                patch.object(onboard.subprocess,'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(OSError,'disk full'):
                onboard.complete_setup(args,onboard.WizardUI(True),selected,report,[],'Pip')
        rename.assert_not_awaited()
        run.assert_not_called()

    def test_unverified_and_verified_install_checkpoints_are_distinct(self):
        args,selected,report = self.setup_inputs()
        args.nickname = None
        for verified, expected, phase in ((False,2,'installed_unverified'),(True,0,'hardware_verified')):
            args.skip_verification = False
            with self.subTest(verified=verified), patch.object(onboard.subprocess,'run'), \
                    patch.object(onboard,'verify_install',return_value=verified), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(onboard.complete_setup(args,onboard.WizardUI(True),selected,report,[],None),expected)
                self.assertEqual(self.recovery_state()['phase'],phase)

    def test_reported_persistence_requires_real_booleans(self):
        args,selected,report = self.setup_inputs()
        target = onboard.device_identity.make_device_name('TestMac','Pip',report['device_id'])
        with patch.object(onboard.device_identity,'rename_device',new=AsyncMock(return_value={
                'ok':'true','persistent':'true','ble_name':target})), \
                patch.object(onboard.subprocess,'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'persistent rename'):
                onboard.complete_setup(args,onboard.WizardUI(True),selected,report,[],'Pip')
        run.assert_not_called()

    def test_shared_cli_catches_eof_cancel_and_backend_errors(self):
        import install
        for error, expected in ((EOFError(),2),(KeyboardInterrupt(),130),(Exception('backend failed'),1)):
            with self.subTest(error=type(error).__name__), \
                    patch.object(onboard,'main',side_effect=error), \
                    patch('sys.argv',['install.py','--onboard']), \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(install.main(),expected)
                self.assertNotIn('Traceback',output.getvalue())

    def test_invalid_explicit_input_is_rejected_before_dependencies(self):
        for argv in (['--nickname',' '],['--laptop-name',' '],['--ble-name','bad\nname'],['--device-address',' ']):
            with self.subTest(argv=argv), patch.object(onboard,'ensure_dependencies') as deps:
                with self.assertRaises(ValueError):
                    onboard.main(argv)
                deps.assert_not_called()

    def test_malformed_bridge_status_is_controlled_and_cannot_pass(self):
        from scripts import verify_hardware
        for status in (None,[],{'hardware_connected':'yes'},
                       {'hardware_connected':True,'firmware_report':['invalid']}):
            with self.subTest(status=status), patch.object(verify_hardware,'request',return_value=status), \
                    patch.object(verify_hardware,'verify') as verify, \
                    patch('sys.stdin.isatty',return_value=False), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'not verified'):
                    onboard.verify_install(timeout=0)
                verify.assert_not_called()

    def test_dependency_and_environment_creation_have_deadlines(self):
        args = onboard.parser().parse_args(['--yes'])
        with patch.object(onboard.importlib.util,'find_spec',return_value=None), \
                patch.object(Path,'exists',return_value=False), \
                patch.object(onboard.subprocess,'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(onboard.ensure_dependencies(args,['--yes']))
        self.assertEqual(run.call_args_list[0].kwargs['timeout'],120)
        self.assertEqual(run.call_args_list[1].kwargs['timeout'],onboard.DEPENDENCY_TIMEOUT)

    def test_windows_recovery_command_uses_literal_powershell_arguments(self):
        selected = {'name':'Factory','address':'MOCK-ONLY'}
        report = {'ble_name':'Factory','device_id':'0123456789ABCDEF'}
        record = onboard.RecoveryRecord(selected,report,"$(echo PWNED)-O'Neil",[])
        record.data['phase'] = 'installed_unverified'
        with patch.object(onboard.sys,'platform','win32'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            record.explain(onboard.WizardUI(True))
        self.assertIn('PowerShell retry',output.getvalue())
        self.assertIn("'$(echo PWNED)-O''Neil'",output.getvalue())
        self.assertNotIn('"$(echo PWNED)',output.getvalue())
        self.assertIn('& ',output.getvalue())

    def test_legacy_keep_name_without_uid_does_not_rename_or_invent_identity(self):
        identity = self.workflow_identity(False)
        identity.inspect_device.return_value = {'ble_name':'Factory','mode':'O'}
        with patch.object(onboard,'device_identity',identity), \
                patch.object(onboard,'ensure_dependencies',return_value=False), \
                patch.object(onboard,'require_platform',return_value='Darwin'), \
                patch.object(onboard.subprocess,'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            result = onboard.main(['--yes','--ble-name','Factory','--keep-name','--no-hooks',
                                   '--identified-device','--skip-verification'])
        self.assertEqual(result,0)
        identity.rename_device.assert_not_awaited()
        identity.identify_device.assert_awaited_once_with('A',None)
        self.assertNotIn('--device-id',run.call_args.args[0])
        self.assertIsNone(self.recovery_state()['device_id'])

    def test_name_preview_includes_unknown_identity_suffix(self):
        self.assertEqual(onboard.make_name('My-Mac', 'Clody'), 'My-Mac-Clody-<UID8>')

    def test_preview_uses_final_normalization_and_shortening_policy(self):
        for laptop, nickname in [('é' * 40, 'Clody'), ('mac', 'x' * 22),
                                  ('My Laptop', '  ｃｌｏｄｙ\n toy  '), (' ', '\n')]:
            final = onboard.device_identity.make_device_name(laptop, nickname, '0123456789abcdef')
            preview = onboard.make_name(laptop, nickname)
            self.assertEqual(preview, final[:-8] + '<UID8>')
            self.assertLessEqual(len(final.encode()), 29)

    def test_duplicate_name_needs_address_noninteractive(self):
        devices = [{'name': 'Clody', 'address': 'A'}, {'name': 'Clody', 'address': 'B'}]
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaises(RuntimeError):
                onboard.select_device(devices, 'Clody')
            self.assertEqual(onboard.select_device(devices, 'Clody', 'B'), devices[1])
            with self.assertRaises(RuntimeError):
                onboard.select_device(devices)

    def test_interactive_selection_never_auto_chooses(self):
        devices = [{'name': 'Clody', 'address': 'A'}]
        with patch('sys.stdin.isatty', return_value=True):
            self.assertEqual(onboard.select_device(devices, input_fn=lambda _: '1'), devices[0])
            with self.assertRaises(RuntimeError):
                onboard.select_device(devices, input_fn=lambda _: '0')

    def test_dry_run_never_connects_installs_or_checks_dependency(self):
        with patch.object(onboard, 'ensure_dependencies') as deps, patch.object(onboard.subprocess, 'run') as run:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(onboard.main(['--dry-run', '--ble-name', 'TrafficLight-ABCD', '--nickname', 'Clody', '--providers', 'codex']), 0)
            deps.assert_not_called()
            run.assert_not_called()
            self.assertIn('rename_requires_firmware_support', output.getvalue())
            plan = json.loads(output.getvalue()[output.getvalue().index('{'):])
            self.assertTrue(plan['requested_name'].endswith('-<UID8>'))
            self.assertIsNone(plan['installer'])

    def test_live_bootstrap_precedes_interactive_choices(self):
        with patch.object(onboard, 'require_platform', return_value='Darwin'), \
                patch.object(onboard, 'ensure_dependencies', return_value=True) as deps, \
                patch.object(onboard, 'choose_providers') as choose, \
                patch('builtins.input') as prompt, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(onboard.main([]), 0)
        deps.assert_called_once()
        self.assertEqual(deps.call_args.args[1], [])
        choose.assert_not_called()
        prompt.assert_not_called()

    def test_explicit_provider_preflight_precedes_bootstrap(self):
        order = []
        argv = ['--yes', '--ble-name', 'Factory', '--nickname', 'Clody', '--providers', 'gemini']
        with patch.object(onboard, 'require_platform', return_value='Darwin'), \
                patch.object(onboard.provider_setup, 'preflight', side_effect=lambda p: order.append(('preflight', p))), \
                patch.object(onboard, 'ensure_dependencies', side_effect=lambda a, v: order.append(('bootstrap', v)) or True), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(onboard.main(argv), 0)
        self.assertEqual(order, [('preflight', ['gemini']), ('bootstrap', argv)])

    def test_keep_name_offline(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            onboard.main(['--dry-run', '--ble-name', 'Clawdy Demo1', '--keep-name', '--no-hooks'])
        self.assertIn('Clawdy Demo1', output.getvalue())
        self.assertIn('--no-hooks', output.getvalue())

    def test_noninteractive_explicit_requirements(self):
        for flags in (['--yes'], ['--dry-run', '--ble-name', 'abc'], ['--yes', '--nickname', 'x']):
            with self.assertRaises(ValueError):
                onboard.main(flags)

    def test_conflicting_options(self):
        with self.assertRaises(ValueError):
            onboard.main(['--keep-name', '--nickname', 'x'])
        with self.assertRaises(ValueError):
            onboard.main(['--providers', 'codex', '--no-hooks'])

    def test_bridge_only_does_not_autodetect_hooks(self):
        args = onboard.parser().parse_args(['--no-hooks'])
        with patch.object(onboard.provider_setup, 'detect') as detect:
            self.assertEqual(onboard.choose_providers(args), [])
            detect.assert_not_called()

    def test_installer_subprocess_uses_argument_list(self):
        cmd = onboard.installer_command('Mac-$(touch hacked)', ['codex', 'claude'])
        self.assertIn('Mac-$(touch hacked)', cmd)
        self.assertEqual(cmd[-3:], ['--providers', 'codex', 'claude'])

    def workflow_identity(self, rename_supported=True):
        return SimpleNamespace(
            discover_candidates=AsyncMock(return_value=[{'name': 'Factory', 'address': 'A'}]),
            identify_device=AsyncMock(return_value={}),
            inspect_device=AsyncMock(return_value={'ble_name': 'Factory', 'device_id': '0123456789abcdef',
                'identity_protocol': 1, 'rename_supported': rename_supported}),
            make_device_name=lambda *args: 'Mac-Clody-89abcdef',
            rename_device=AsyncMock(return_value={'ok': True, 'persistent': True, 'ble_name': 'Mac-Clody-89abcdef'}))

    def test_verified_rename_precedes_installer(self):
        identity = self.workflow_identity()
        with patch.object(onboard, 'device_identity', identity), \
                patch.object(onboard, 'ensure_dependencies', return_value=False), \
                patch.object(onboard, 'require_platform', return_value='Darwin'), \
                patch.object(onboard.subprocess, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            onboard.main(['--yes', '--ble-name', 'Factory', '--nickname', 'Clody', '--no-hooks', '--identified-device', '--skip-verification'])
        identity.inspect_device.assert_awaited_once_with('A')
        identity.rename_device.assert_awaited_once()
        self.assertIn('Mac-Clody-89abcdef', run.call_args.args[0])

    def test_old_firmware_does_not_install_with_unapplied_name(self):
        identity = self.workflow_identity(False)
        with patch.object(onboard, 'device_identity', identity), \
                patch.object(onboard, 'ensure_dependencies', return_value=False), \
                patch.object(onboard, 'require_platform', return_value='Darwin'), \
                patch.object(onboard.subprocess, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, '--keep-name'):
                onboard.main(['--yes', '--ble-name', 'Factory', '--nickname', 'Clody', '--no-hooks', '--identified-device', '--skip-verification'])
        run.assert_not_called()
        identity.rename_device.assert_not_awaited()

    def test_unacknowledged_rename_stops_install(self):
        identity = self.workflow_identity()
        identity.rename_device.return_value = {'ok': True, 'persistent': False, 'ble_name': 'Mac-Clody-89abcdef'}
        with patch.object(onboard, 'device_identity', identity), \
                patch.object(onboard, 'ensure_dependencies', return_value=False), \
                patch.object(onboard, 'require_platform', return_value='Darwin'), \
                patch.object(onboard.subprocess, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'persistent rename'):
                onboard.main(['--yes', '--ble-name', 'Factory', '--nickname', 'Clody', '--no-hooks', '--identified-device', '--skip-verification'])
        run.assert_not_called()

    def test_provider_preflight_failure_prevents_dependency_or_bluetooth(self):
        with patch.object(onboard.provider_setup, 'preflight', side_effect=RuntimeError('policy disabled')), \
                patch.object(onboard, 'require_platform', return_value='Darwin'), \
                patch.object(onboard, 'ensure_dependencies') as deps, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'policy disabled'):
                onboard.main(['--yes', '--ble-name', 'Factory', '--keep-name', '--providers', 'gemini'])
        deps.assert_not_called()

    def test_yes_does_not_assert_physical_observation(self):
        with patch('sys.stdin.isatty', return_value=False):
            self.assertFalse(onboard.human_confirmation('Did lights show?'))

    def test_missing_physical_identification_stops_before_rename(self):
        identity = self.workflow_identity()
        with patch.object(onboard, 'device_identity', identity), \
                patch.object(onboard, 'ensure_dependencies', return_value=False), \
                patch.object(onboard, 'require_platform', return_value='Darwin'), \
                patch('sys.stdin.isatty', return_value=False), \
                patch.object(onboard.subprocess, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'Physical selection'):
                onboard.main(['--yes', '--ble-name', 'Factory', '--nickname', 'Clody', '--no-hooks'])
        run.assert_not_called()
        identity.rename_device.assert_not_awaited()

    def test_verification_requires_ble_peer_report_and_visible_confirmation(self):
        from scripts import verify_hardware
        good = {'hardware_connected': True, 'transport': 'ble', 'port': 'ble://A',
                'firmware_report': {'transport': 'ble', 'device_id': 'abc'}}
        with patch.object(verify_hardware, 'request', return_value=good), \
                patch.object(verify_hardware, 'verify') as verify, \
                patch.object(onboard, 'human_confirmation', return_value=False), \
                patch('sys.stdin.isatty', return_value=False), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(onboard.verify_install('abc'))
        verify.assert_called_once_with('ble', expected_device_id='abc')

    def test_wrong_peer_identity_is_not_verified(self):
        from scripts import verify_hardware
        wrong = {'hardware_connected': True, 'transport': 'ble', 'port': 'ble://A',
                 'firmware_report': {'transport': 'ble', 'device_id': 'other'}}
        with patch.object(verify_hardware, 'request', return_value=wrong), \
                patch.object(verify_hardware, 'verify') as verify, \
                patch('sys.stdin.isatty', return_value=False), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'not verified'):
                onboard.verify_install('abc', timeout=0)
        verify.assert_not_called()

    def test_denied_visible_identification_never_renames_or_installs(self):
        identity = self.workflow_identity()
        with patch.object(onboard, 'device_identity', identity), \
                patch.object(onboard, 'ensure_dependencies', return_value=False), \
                patch.object(onboard, 'require_platform', return_value='Darwin'), \
                patch.object(onboard, 'human_confirmation', return_value=False), \
                patch('sys.stdin.isatty', return_value=True), \
                patch.object(onboard.subprocess, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'not physically confirmed'):
                onboard.main(['--yes', '--ble-name', 'Factory', '--nickname', 'Clody', '--no-hooks'])
        identity.identify_device.assert_awaited_once()
        identity.rename_device.assert_not_awaited()
        run.assert_not_called()

    def test_verified_and_visible_leds_finish_hardware_only(self):
        from scripts import verify_hardware
        good = {'hardware_connected': True, 'transport': 'ble', 'port': 'ble://A',
                'firmware_report': {'transport': 'ble', 'device_id': 'abc'}}
        with patch.object(verify_hardware, 'request', return_value=good), \
                patch.object(verify_hardware, 'verify'), \
                patch.object(onboard, 'human_confirmation', return_value=True), \
                patch('sys.stdin.isatty', return_value=False), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertTrue(onboard.verify_install('abc'))
        self.assertIn('Real-provider acceptance', output.getvalue())


if __name__ == '__main__':
    unittest.main()
