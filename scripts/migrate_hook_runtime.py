#!/usr/bin/env python3
"""Move existing owned hook commands to durable runtime; never enable hooks/services.

Default is a read-only preview. Applying does not grant provider trust: review
changed hook commands normally. No Bluetooth/USB modules or services are used.
"""
import argparse
import ast
import copy
import json
import os
import stat
from pathlib import Path
import shutil
import time

try:
    from scripts.platform_support import hook_command, venv_python
except ModuleNotFoundError:
    from platform_support import hook_command, venv_python

ROOT = Path(__file__).resolve().parents[1]


def owned(hook, provider):
    command = hook.get('command')
    if not isinstance(command, str) or 'traffic.py' not in command:
        return False
    marker = hook.get('statusMessage') or ''
    name = hook.get('name') or ''
    if provider == 'codex':
        return isinstance(marker, str) and marker.startswith('Traffic light:') and not marker.startswith('Traffic light: Claude ')
    if provider == 'claude':
        return isinstance(marker, str) and marker.startswith('Traffic light: Claude ')
    if provider == 'gemini':
        return isinstance(name, str) and (name.startswith('trafficlights-gemini-') or (
            name.startswith('traffic-light-') and '--provider gemini' in command))
    return '--provider cursor' in command and '--trafficlights-hook' in command


def rewrite(data, provider, python, script):
    """Change only commands; all policy, disabled flags, matchers and other hooks survive."""
    updated = copy.deepcopy(data)
    hooks = updated.get('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('Invalid hooks object for ' + provider)
    changed = 0
    for groups in hooks.values():
        if not isinstance(groups, list):
            raise ValueError('Invalid hook groups for ' + provider)
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError('Invalid hook group for ' + provider)
            handlers = [group] if provider == 'cursor' else group.get('hooks', [])
            if not isinstance(handlers, list) or any(not isinstance(h, dict) for h in handlers):
                raise ValueError('Invalid hook handlers for ' + provider)
            for hook in handlers:
                if not owned(hook, provider):
                    continue
                # Retain the configured event/provider flags verbatim. Refuse
                # compound shell commands: only the generated observer invocation
                # can be migrated without altering user-defined behavior.
                command = hook['command']
                suffix = command[command.rfind('traffic.py') + len('traffic.py'):]
                if suffix.startswith(('"', "'")):
                    suffix = suffix[1:]
                if suffix and not suffix[0].isspace():
                    raise ValueError('Unrecognized owned hook command; review ' + provider)
                if any(character in suffix for character in '\n\r;&|<>`$'):
                    raise ValueError('Compound owned hook command; review ' + provider)
                new = hook_command(python, script, powershell=provider == 'gemini') + suffix
                if new != command:
                    hook['command'] = new
                    changed += 1
    return updated, changed


def migrate(home, runtime, source, apply=False, providers=None):
    home, runtime, source = Path(home), Path(runtime), Path(source)
    python = venv_python(runtime)
    if not python.is_file():
        raise RuntimeError('Existing runtime interpreter is missing; migration cannot install dependencies.')
    content = source.read_bytes()
    ast.parse(content, filename='traffic.py')
    script = runtime / 'traffic.py'
    paths = {'codex':home/'.codex/hooks.json', 'claude':home/'.claude/settings.json',
             'gemini':home/'.gemini/settings.json', 'cursor':home/'.cursor/hooks.json'}
    plans = []
    for provider, path in paths.items():
        if providers is not None and provider not in providers:
            continue
        if not path.exists():
            continue
        if path.is_symlink():
            raise RuntimeError('Symlinked provider configuration needs manual review: ' + provider)
        original = path.read_bytes()
        data = json.loads(original)
        if not isinstance(data, dict):
            raise ValueError('Invalid provider config: ' + provider)
        updated, count = rewrite(data, provider, python, script)
        if count:
            plans.append((provider, path, original, updated, count))
    result = {'apply':apply, 'script':str(script), 'changes':{p[0]:p[4] for p in plans},
              'service_started':False, 'hooks_enabled':False}
    if not apply:
        return result
    backup = runtime / 'backups' / ('hook-migration-' + str(time.time_ns()))
    backup.mkdir(parents=True, exist_ok=False, mode=0o700)
    if script.exists():
        shutil.copyfile(script, backup/'traffic.py')
    for provider, _path, original, _updated, _count in plans:
        saved = backup/(provider+'.json')
        saved.write_bytes(original)
        os.chmod(saved, 0o600)
    temporary = script.with_suffix('.tmp')
    temporary.write_bytes(content)
    temporary.replace(script)
    for _provider, path, original, updated, _count in plans:
        # Refuse to overwrite changes made since preview/preflight. Migration is
        # intentionally not an all-config atomic transaction; backups enable rollback.
        if path.read_bytes() != original:
            raise RuntimeError('Provider configuration changed during migration; backup: ' + str(backup))
        temporary = path.with_suffix('.trafficlights.tmp')
        temporary.write_text(json.dumps(updated, indent=2) + '\n', encoding='utf-8')
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        temporary.replace(path)
    result['backup'] = str(backup)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--providers', nargs='+', choices=['codex','claude','gemini','cursor'])
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--runtime', type=Path, default=Path.home()/'.local/share/trafficlights')
    parser.add_argument('--source', type=Path, default=ROOT/'scripts/traffic.py')
    args = parser.parse_args()
    print(json.dumps(migrate(args.home, args.runtime, args.source, args.apply, args.providers), indent=2))
    print('Review changed commands in normal provider trust controls; no service or hooks were enabled.')


if __name__ == '__main__':
    main()
