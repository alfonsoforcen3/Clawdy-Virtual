#!/usr/bin/env python3
"""Install the native macOS/Windows traffic-light bridge and selected local provider adapters without system-wide pip changes."""
import sys
# Read-only agent previews must not leave import caches in a fresh checkout.
sys.dont_write_bytecode = True
import argparse
import json
from pathlib import Path
import platform
import subprocess
import venv

ROOT = Path(__file__).resolve().parent
RUNTIME = Path.home() / '.local' / 'share' / 'trafficlights'


def onboarding_requested(argv):
    """A new buyer needs BLE selection, never implicit USB provisioning.

    Explicit maintainer flags retain their existing path. A saved but malformed
    connection is a recovery problem, not permission to pick another toy.
    """
    if '--onboard' in argv or any(flag in argv for flag in ('--preflight', '--list-devices', '--list-usb', '--dry-run')):
        return True
    if argv:
        return False
    connection = RUNTIME / 'connection.json'
    if not connection.exists():
        return True
    try:
        saved = json.loads(connection.read_text())
        if (not isinstance(saved, dict) or saved.get('transport') not in ('ble', 'serial', 'local')
                or (saved.get('transport') == 'ble' and not isinstance(saved.get('ble_name'), str))
                or (saved.get('transport') == 'ble' and not saved['ble_name'].strip())):
            raise ValueError('Invalid saved connection')
    except (OSError, ValueError, TypeError) as error:
        raise RuntimeError('Saved Clawdy connection needs recovery. Review connection.json; '
                           'use --onboard to explicitly select and identify your toy. No device was scanned.') from error
    return True

def main():
    if onboarding_requested(sys.argv[1:]):
        from scripts.onboard import run_cli as onboard
        return onboard([arg for arg in sys.argv[1:] if arg != '--onboard'])
    parser = argparse.ArgumentParser(description=__doc__, epilog='New Clawdy: run without arguments or use --onboard. '
        'Agent preview: --onboard --preflight --json. BLE selection does not need a USB data cable.')
    parser.add_argument('--transport', choices=['ble', 'local', 'serial'],
                        help='Use local for desktop-only live status, BLE for a toy, or serial for legacy diagnostics')
    parser.add_argument('--ble-name', help='Exact verified advertisement; use --onboard for buyer device selection')
    parser.add_argument('--device-id', help='Verified immutable board identity from customer enrollment')
    parser.add_argument('--providers', nargs='+', choices=['codex', 'claude', 'gemini', 'cursor'],
                        help='Install only these explicitly selected local provider hooks')
    parser.add_argument('--no-hooks', action='store_true', help='Update connection/service only, preserving hook definitions')
    args = parser.parse_args()
    config_path = RUNTIME / 'connection.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    if not isinstance(config, dict):
        raise RuntimeError('Saved Clawdy connection is invalid; review connection.json before updating.')
    if args.transport is None and config.get('transport') == 'serial' and not args.ble_name:
        raise RuntimeError('Saved serial runtime is a legacy maintainer configuration. Use --onboard for BLE, '
                           'or explicitly request --transport serial for a maintainer diagnostic.')
    args.transport = args.transport or config.get('transport', 'ble')
    if args.transport == 'local' and (args.ble_name or args.device_id):
        parser.error('Local mode cannot select a physical device. Use --onboard for a toy.')
    if args.transport == 'local' and config.get('transport') not in (None, 'local'):
        parser.error('An existing hardware profile is configured. Use its live status service with Virtual Clawdy.')
    name = (args.ble_name or config.get('ble_name')) if args.transport == 'ble' else None
    if args.transport == 'ble' and not name:
        raise RuntimeError('No verified BLE name. Use --onboard to select and identify your toy; USB is never a runtime fallback.')
    if not args.no_hooks and args.providers is None:
        raise RuntimeError('Select --providers explicitly or --no-hooks. Use --onboard for guided buyer setup.')
    from scripts.platform_support import require_platform, venv_python
    try:
        system = require_platform()
    except RuntimeError as error:
        raise SystemExit(str(error))
    print('Detected operating system:', system)
    python = venv_python(RUNTIME)
    if Path(sys.prefix) != RUNTIME / 'venv':
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(RUNTIME / 'venv')
        subprocess.run([str(python), '-m', 'pip', 'install', 'pyserial==3.5'], check=True)
        subprocess.run([str(python), str(ROOT / 'install.py'), *sys.argv[1:]], check=True)
        return
    from scripts import codex_setup
    from scripts import provider_setup
    providers = args.providers or []
    if not args.no_hooks:
        provider_setup.preflight(providers)
    codex_setup.install_service(args.transport, name, device_id=args.device_id)
    if not args.no_hooks:
        print('Installing selected hooks:', ', '.join(providers) or 'none')
        for provider in providers:
            provider_setup.configure(provider)
    print('Installed transport:', args.transport)
    if name:
        print('Bluetooth name:', name)
        print('Allow normal Bluetooth access if prompted.')
    if not args.no_hooks:
        print('Review installed hooks in each selected provider.')
    command = 'py -3' if system == 'Windows' else 'python3'
    print(f'Run {command} manage_hooks.py status, then verify a real turn in each selected app.')

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, TimeoutError, subprocess.CalledProcessError) as error:
        print('Clawdy installation stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
