import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import codex_setup, claude_setup, provider_setup


class HookConfigSafetyTests(unittest.TestCase):
    def test_null_and_nonstring_ownership_fields_are_preserved(self):
        for provider in provider_setup.SUPPORTED:
            for value in (None, 12, False, [], {}):
                hook = {'statusMessage': value, 'name': value, 'command': value, 'custom': value}
                data = {'hooks': {'Other': [hook] if provider == 'cursor' else [
                    {'hooks': [hook], 'matcher': None}, {'hooks': [], 'custom': value}, {'custom': value}]}}
                original = copy.deepcopy(data)
                provider_setup.validate_config(data, provider)
                provider_setup.remove_ours(data, provider)
                self.assertEqual(data, original, (provider, value))

    def test_owned_hooks_removed_without_mutating_unrelated_hook_fields(self):
        markers = {'codex': {'statusMessage': 'Traffic light: Stop'},
                   'claude': {'statusMessage': 'Traffic light: Claude Stop'},
                   'gemini': {'name': 'trafficlights-gemini-AfterAgent'},
                   'cursor': {'command': 'python traffic.py G --provider cursor --trafficlights-hook'}}
        other = {'name': None, 'statusMessage': None, 'command': None}
        for provider, owned in markers.items():
            data = {'hooks': {'Stop': [owned, copy.deepcopy(other)] if provider == 'cursor'
                             else [{'hooks': [owned, copy.deepcopy(other)], 'extra': None}]}}
            provider_setup.remove_ours(data, provider)
            retained = data['hooks']['Stop'][0] if provider == 'cursor' else data['hooks']['Stop'][0]['hooks'][0]
            self.assertEqual(retained, other)

    def test_all_consumed_container_schemas_rejected_before_mutation(self):
        malformed = [None, [], {'hooks': None}, {'hooks': []}, {'hooks': {'Stop': None}},
                     {'hooks': {'Stop': [None]}}, {'hooks': {'Stop': [{'hooks': None}]}},
                     {'hooks': {'Stop': [{'hooks': [None]}]}}]
        for provider in provider_setup.SUPPORTED:
            for data in malformed:
                if provider == 'cursor' and isinstance(data, dict) and data.get('hooks') == {'Stop': [{'hooks': None}]}:
                    continue  # Cursor handlers are flat; nested hooks are an unrelated field.
                if provider == 'cursor' and isinstance(data, dict) and data.get('hooks') == {'Stop': [{'hooks': [None]}]}:
                    continue
                original = copy.deepcopy(data)
                with self.assertRaises(RuntimeError, msg=(provider, data)):
                    provider_setup.validate_config(data, provider)
                self.assertEqual(data, original)

    def test_disabled_global_owned_and_gemini_named_policies_not_bypassed(self):
        cases = [('claude', {'disableAllHooks': True}), ('codex', {'enabled': False}),
                 ('cursor', {'enabled': False}), ('gemini', {'hooksConfig': {'enabled': False}}),
                 ('gemini', {'hooksConfig': {'disabledHookNames': ['trafficlights-gemini-BeforeAgent']}}),
                 ('codex', {'hooks': {'Stop': [{'hooks': [{'statusMessage': 'Traffic light: Stop', 'enabled': False}]}]}})]
        for provider, data in cases:
            original = copy.deepcopy(data)
            with self.assertRaises(RuntimeError):
                provider_setup.validate_config(data, provider)
            provider_setup.validate_config(data, provider, enable=False)
            self.assertEqual(data, original)
        provider_setup.validate_config({'hooksConfig': {'disabledHookNames': ['unrelated']}}, 'gemini')

    def test_malformed_policy_types_are_rejected(self):
        cases = [('claude', {'disableAllHooks': 'false'}), ('codex', {'enabled': None}),
                 ('gemini', {'hooksConfig': None}), ('gemini', {'hooksConfig': {'enabled': 'false'}}),
                 ('gemini', {'hooksConfig': {'disabledHookNames': None}}),
                 ('gemini', {'hooksConfig': {'disabledHookNames': [None]}}),
                 ('cursor', {'version': True})]
        for provider, data in cases:
            with self.assertRaises(RuntimeError):
                provider_setup.validate_config(data, provider)

    def test_direct_codex_enable_rejects_before_service_or_save(self):
        with patch.object(codex_setup, 'read_hooks', return_value={'hooks': None}), \
             patch.object(codex_setup, 'install_service') as service, patch.object(codex_setup, 'save') as save:
            with self.assertRaises(RuntimeError):
                codex_setup.enable()
        service.assert_not_called()
        save.assert_not_called()

    def test_preflight_checks_entire_selection_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first = home/'.codex/hooks.json'; first.parent.mkdir(); first.write_text('{"hooks":{}}')
            last = home/'.claude/settings.json'; last.parent.mkdir(); last.write_text('{"hooks":null}')
            with patch.object(provider_setup.Path, 'home', return_value=home), \
                 patch.object(provider_setup, 'configure') as configure:
                with self.assertRaises(RuntimeError):
                    provider_setup.preflight(['codex', 'claude'])
                configure.assert_not_called()
            self.assertEqual(first.read_text(), '{"hooks":{}}')
            self.assertEqual(last.read_text(), '{"hooks":null}')

    def test_configure_builds_all_hooks_with_durable_runtime_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = root/'runtime'; runtime.mkdir()
            python = provider_setup.venv_python(runtime); python.parent.mkdir(parents=True); python.touch()
            settings = {p: root/(p+'.json') for p in provider_setup.SUPPORTED}
            unrelated = {'command': None, 'name': 17, 'statusMessage': None, 'custom': None}
            for provider, path in settings.items():
                group = unrelated if provider == 'cursor' else {'hooks': [unrelated], 'matcher': None}
                path.write_text(json.dumps({'hooks': {'Other': [group]}}))
            patches = [patch.object(provider_setup, 'ROOT', root), patch.object(provider_setup, 'RUNTIME', runtime),
                       patch.object(provider_setup, 'preflight'), patch.object(provider_setup, 'settings_path', side_effect=settings.get),
                       patch.object(codex_setup, 'ROOT', root), patch.object(codex_setup, 'RUNTIME', runtime),
                       patch.object(codex_setup, 'HOOKS', settings['codex']),
                       patch.object(claude_setup, 'ROOT', root), patch.object(claude_setup, 'RUNTIME', runtime),
                       patch.object(claude_setup, 'SETTINGS', settings['claude'])]
            from contextlib import ExitStack
            with ExitStack() as stack:
                for item in patches: stack.enter_context(item)
                for provider in provider_setup.SUPPORTED:
                    provider_setup.configure(provider)
            for path in settings.values():
                content = json.loads(path.read_text())
                for groups in content['hooks'].values():
                    for group in groups:
                        for hook in group.get('hooks', [group]):
                            if hook.get('command') is None:
                                self.assertEqual(hook, unrelated)
                                continue
                            if sys.platform == 'win32' and 'TcpClient' in hook['command']:
                                continue
                            self.assertIn(str(runtime/'traffic.py'), hook['command'])
                            self.assertNotIn(str(root/'scripts/traffic.py'), hook['command'])

    def test_codex_hooks_use_powershell_command_windows_on_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / 'runtime'
            python = runtime / 'venv' / 'Scripts' / 'python.exe'
            python.parent.mkdir(parents=True)
            python.touch()
            with patch.object(codex_setup, 'RUNTIME', runtime), \
                 patch.object(codex_setup, 'read_hooks', return_value={'hooks': {}}), \
                 patch.object(codex_setup, 'save') as save, \
                 patch.object(codex_setup.sys, 'platform', 'win32'), \
                 patch('scripts.platform_support.platform.system', return_value='Windows'):
                codex_setup.enable(install_login_service=False)
            installed = save.call_args.args[0]['hooks']
            for event, state in {'SessionStart':'Y', 'UserPromptSubmit':'Y', 'PreToolUse':'Y',
                                 'PostToolUse':'Y', 'Stop':'G',
                                 'Interrupt':'G', 'SessionEnd':'O'}.items():
                hook = installed[event][0]['hooks'][0]
                self.assertEqual(hook['commandWindows'],
                                 f"& '{python}' '{runtime / 'traffic.py'}' {state}")
                self.assertEqual(hook['timeout'], 3 if event in ('Interrupt', 'SessionEnd') else 20)
    def test_runtime_hook_copy_precedes_native_windows_service_and_preserves_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = root/'runtime'; runtime.mkdir()
            source = root/'scripts/traffic.py'; source.parent.mkdir(); source.write_text('# fixture')
            config = runtime/'connection.json'; config.write_text(json.dumps({'transport':'serial', 'ble_name':'old', 'device_id':'ABCDEF12', 'other':None}))
            def install(*args):
                self.assertEqual((runtime/'traffic.py').read_text(), '# fixture')
            with patch.object(codex_setup, 'ROOT', root), patch.object(codex_setup, 'RUNTIME', runtime), \
                 patch.object(codex_setup.sys, 'platform', 'win32'), \
                 patch('scripts.windows_service.install', side_effect=install) as service:
                codex_setup.install_service()
            service.assert_called_once()
            self.assertEqual(json.loads(config.read_text())['device_id'], 'ABCDEF12')
            self.assertIsNone(json.loads(config.read_text())['other'])

    def test_invalid_runtime_config_fails_before_copy_or_start(self):
        for content in ('null', '{"transport": "serial", "ble_name": 12}',
                        '{"transport": "ble", "ble_name":"x", "device_id":12}'):
            with tempfile.TemporaryDirectory() as directory:
                runtime = Path(directory); (runtime/'connection.json').write_text(content)
                with patch.object(codex_setup, 'RUNTIME', runtime), patch.object(codex_setup.sys, 'platform', 'win32'), \
                     patch.object(codex_setup.shutil, 'copy2') as copy_file, patch('scripts.windows_service.install') as service:
                    with self.assertRaises((RuntimeError, ValueError)):
                        codex_setup.install_service()
                copy_file.assert_not_called(); service.assert_not_called()

    def test_direct_claude_rejects_schema_before_backup_or_save(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory)/'settings.json'
            settings.write_text('{"hooks": {"Stop": [{"hooks": null}]}}')
            original = settings.read_bytes()
            with patch.object(claude_setup, 'SETTINGS', settings), \
                 patch.object(claude_setup.shutil, 'copy2') as copy_file:
                with self.assertRaises(RuntimeError):
                    claude_setup.configure(True)
                copy_file.assert_not_called()
            self.assertEqual(settings.read_bytes(), original)

    def test_owned_nonboolean_disable_flag_is_not_silently_replaced(self):
        data = {'hooks': {'Stop': [{'hooks': [
            {'statusMessage': 'Traffic light: Stop', 'enabled': 'false'}]}]}}
        with self.assertRaisesRegex(RuntimeError, 'policy'):
            provider_setup.validate_config(data, 'codex')
