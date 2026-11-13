#!/usr/bin/env python3
"""Install/remove this project's Codex hooks and macOS login bridge service.

Hook trust is deliberately left to the app's normal hook review screen.
"""
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import time

try:
    from scripts.platform_support import venv_python, hook_command
except ModuleNotFoundError:
    from platform_support import venv_python, hook_command

ROOT = Path(__file__).resolve().parents[1]
HOOKS = Path.home() / '.codex' / 'hooks.json'
SERVICE = 'local.trafficlights.bridge'
PLIST = Path.home() / 'Library' / 'LaunchAgents' / (SERVICE + '.plist')
RUNTIME = Path.home() / '.local' / 'share' / 'trafficlights'
MARKER = 'Traffic light:'

def read_hooks():
    if HOOKS.exists():
        return json.loads(HOOKS.read_text())
    return {'hooks': {}}

def validate_hooks(data, enable=False):
    try:
        from scripts import provider_setup
    except ModuleNotFoundError:
        import provider_setup
    provider_setup.validate_config(data, 'codex', enable=enable)


def remove_ours(data):
    try:
        from scripts import provider_setup
    except ModuleNotFoundError:
        import provider_setup
    provider_setup.remove_ours(data, 'codex')


def save(data):
    HOOKS.parent.mkdir(parents=True, exist_ok=True)
    if HOOKS.exists():
        backup = ROOT / '.backups' / ('codex-hooks-' + str(time.time_ns()) + '.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HOOKS, backup)
    temporary = HOOKS.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(HOOKS)

def install_service(transport=None, ble_name=None, device_id=None):
    if sys.platform not in ('darwin', 'win32'):
        raise RuntimeError('Use native macOS or Windows Python.')
    config_path = RUNTIME / 'connection.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {
        'transport': 'serial', 'ble_name': None}
    if not isinstance(config, dict):
        raise RuntimeError('Invalid connection configuration; left unchanged.')
    if transport:
        config['transport'] = transport
    if ble_name:
        if ble_name != config.get('ble_name'):
            config.pop('device_id', None)
        config['ble_name'] = ble_name
    if device_id is not None:
        import re
        if not isinstance(device_id, str) or not re.fullmatch(r'[0-9a-fA-F]{8,64}', device_id):
            raise ValueError('Invalid verified device identity.')
        config['device_id'] = device_id
    if config.get('transport') not in ('ble', 'serial', 'local'):
        raise RuntimeError('Invalid connection transport; left unchanged.')
    if config.get('ble_name') is not None and not isinstance(config['ble_name'], str):
        raise RuntimeError('Invalid Bluetooth name; left unchanged.')
    if config.get('device_id') is not None:
        import re
        if not isinstance(config['device_id'], str) or not re.fullmatch(r'[0-9a-fA-F]{8,64}', config['device_id']):
            raise ValueError('Invalid saved device identity; configuration left unchanged.')
    if config['transport'] == 'ble' and not config.get('ble_name'):
        raise RuntimeError('Run python3 install.py to discover your board, or provide --ble-name.')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'scripts' / 'traffic.py', RUNTIME / 'traffic.py')
    python = Path(sys.executable)
    if config['transport'] == 'ble':
        python = venv_python(RUNTIME)
        if not python.exists():
            subprocess.run([sys.executable, '-m', 'venv', str(RUNTIME / 'venv')], check=True)
        dependencies = ['bleak==0.22.3', 'pyserial==3.5']
        if sys.platform == 'darwin':
            dependencies += ['py2app==0.28.8', 'setuptools<71']
        subprocess.run([str(python), '-m', 'pip', 'install', *dependencies], check=True)
    if sys.platform == 'win32':
        try:
            from scripts.windows_service import install
        except ModuleNotFoundError:
            from windows_service import install
        install(ROOT, RUNTIME, python, config)
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    if sys.platform == 'darwin':
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME.mkdir(parents=True, exist_ok=True)
        # Login services cannot rely on access to macOS-protected Desktop folders.
        shutil.copy2(ROOT / 'scripts' / 'bridge.py', RUNTIME / 'bridge.py')
        shutil.copy2(ROOT / 'scripts' / 'ble_transport.py', RUNTIME / 'ble_transport.py')
        shutil.copy2(ROOT / 'scripts' / 'dashboard.py', RUNTIME / 'dashboard.py')
        shutil.copytree(ROOT / 'web', RUNTIME / 'web', dirs_exist_ok=True)
        program = [str(python), '-u', str(RUNTIME / 'bridge.py')]
        if config['transport'] == 'ble':
            for filename in ('bluetooth_app.py', 'build_bluetooth_app.py'):
                shutil.copy2(ROOT / 'scripts' / filename, RUNTIME / filename)
            app = RUNTIME / 'dist' / 'Traffic Light Bridge.app'
            if not app.exists():
                subprocess.run([str(python), 'build_bluetooth_app.py', 'py2app', '-A'],
                               cwd=RUNTIME, check=True)
            program = [str(app / 'Contents' / 'MacOS' / 'Traffic Light Bridge')]
        service = {'Label': SERVICE, 'ProgramArguments': program, 'RunAtLoad': True,
                   'KeepAlive': True, 'WorkingDirectory': str(RUNTIME),
                   'EnvironmentVariables': {'TRAFFIC_TRANSPORT': config['transport'],
                                            'TRAFFIC_BLE_NAME': config.get('ble_name') or ''},
                   'StandardOutPath': str(RUNTIME / 'bridge.log'),
                   'StandardErrorPath': str(RUNTIME / 'bridge.log'), 'ThrottleInterval': 5}
        subprocess.run(['launchctl', 'bootout', 'gui/' + str(os.getuid()), str(PLIST)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        PLIST.write_bytes(plistlib.dumps(service))
        subprocess.run(['launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(PLIST)], check=True)

def enable(install_login_service=True):
    data = read_hooks()
    validate_hooks(data, enable=True)
    hook_command(venv_python(RUNTIME), RUNTIME / 'traffic.py')
    if install_login_service:
        install_service()
    remove_ours(data)
    events = {'SessionStart': 'Y', 'UserPromptSubmit': 'Y', 'PreToolUse': 'Y',
              'PostToolUse': 'Y', 'Stop': 'G',
              'Interrupt': 'G', 'SessionEnd': 'O'}
    hook_python = venv_python(RUNTIME)
    hook_python = hook_python if hook_python.exists() else Path(sys.executable)
    base = hook_command(hook_python, RUNTIME / 'traffic.py')
    windows_base = hook_command(hook_python, RUNTIME / 'traffic.py', powershell=True) if sys.platform == 'win32' else None
    for event, color in events.items():
        handler = {'type': 'command', 'command': base + ' ' + color,
                   'timeout': 3 if event in ('Interrupt', 'SessionEnd') else (20 if sys.platform == 'win32' else 3),
                   'statusMessage': MARKER + ' ' + event}
        if windows_base is not None:
            handler['commandWindows'] = windows_base + ' ' + color
        group = {'hooks': [handler]}
        if event in ('PreToolUse', 'PostToolUse'):
            group['matcher'] = '.*'
        data.setdefault('hooks', {}).setdefault(event, []).append(group)
    save(data)
    print('Installed Codex hooks: ' + str(HOOKS))
    print('Review and trust the Traffic light hooks in the app Hooks settings (or CLI /hooks).')

def disable():
    try:
        from scripts import claude_setup
    except ModuleNotFoundError:
        import claude_setup
    if claude_setup.SETTINGS.exists():
        claude_setup.configure(False)
    try:
        from scripts import provider_setup
    except ModuleNotFoundError:
        import provider_setup
    for provider in ('gemini', 'cursor'):
        provider_setup.configure(provider, False)
    if HOOKS.exists():
        data = read_hooks()
        original = json.dumps(data)
        remove_ours(data)
        if json.dumps(data) != original:
            save(data)
    if sys.platform == 'win32':
        try:
            from scripts.windows_service import remove
        except ModuleNotFoundError:
            from windows_service import remove
        remove()
    if sys.platform == 'darwin' and PLIST.exists():
        subprocess.run(['launchctl', 'bootout', 'gui/' + str(os.getuid()), str(PLIST)], check=False)
        PLIST.unlink()
    if sys.platform != 'win32':
        subprocess.run([sys.executable, str(RUNTIME / 'traffic.py'), 'O'],
                       stdin=subprocess.DEVNULL)
    print('Removed owned provider hooks and login service; unrelated hooks preserved.')

if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == 'enable':
        enable()
    elif len(sys.argv) == 2 and sys.argv[1] == 'disable':
        disable()
    elif len(sys.argv) == 2 and sys.argv[1] in ('bluetooth', 'usb'):
        install_service('ble' if sys.argv[1] == 'bluetooth' else 'serial')
        print('Bridge transport set to ' + sys.argv[1] + '; existing hook definitions preserved.')
    else:
        raise SystemExit('Usage: codex_setup.py enable|disable|bluetooth|usb')
