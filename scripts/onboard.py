#!/usr/bin/env python3
"""Guided setup for a powered, factory-flashed Clawdy. USB data is unnecessary."""
import argparse
import asyncio
import contextlib
import importlib.util
import hashlib
import math
import re
import shlex
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
sys.dont_write_bytecode = True
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import provider_setup, device_identity
from scripts.platform_support import require_platform, venv_python

RUNTIME = Path.home() / '.local/share/trafficlights'
DEPENDENCY_TIMEOUT = 300
INSTALL_TIMEOUT = 600



class WizardUI:
    """Small accessible terminal presentation; no cursor control or dependencies."""
    def __init__(self, no_color=False, json_output=False):
        self.stream = sys.stderr if json_output else sys.stdout
        stream = self.stream
        windows_ansi = (os.name != 'nt' or os.environ.get('WT_SESSION')
                        or os.environ.get('ANSICON') or os.environ.get('TERM_PROGRAM') == 'vscode'
                        or os.environ.get('TERM', '').startswith('xterm'))
        self.color = (not no_color and 'NO_COLOR' not in os.environ
                      and os.environ.get('TERM') != 'dumb'
                      and bool(getattr(stream, 'isatty', lambda: False)())
                      and bool(windows_ansi))

    @staticmethod
    def text(value):
        # Nearby advertisements are not trusted terminal control sequences.
        return ''.join(c if c.isprintable() else '\\x%02x' % ord(c) for c in str(value))

    def paint(self, value, code):
        text = self.text(value)
        return '\033[' + code + 'm' + text + '\033[0m' if self.color else text

    def banner(self, laptop, preview=False):
        print(file=self.stream)
        print(self.paint('  C L A W D Y', '1;36'), file=self.stream)
        print('  A little companion for your AI work.', file=self.stream)
        print(self.paint('  ' + ('Offline preview' if preview else 'Bluetooth setup')
                         + ' | ' + self.text(laptop), '2'), file=self.stream)
        print(self.paint('  ' + '-' * 54, '2'), file=self.stream)
        self.status('info', 'Physical Clawdy setup. For the virtual desktop source preview, read docs/TRY_VIRTUAL_CLAWDY.md.')
        if preview:
            self.status('info', 'Preview only: no Bluetooth scan, downloads or changes.')
        else:
            self.detail('After approval', 'Prepare a private Python runtime, install the login companion and configure only your chosen app hooks.')
            command = 'py -3' if platform.system() == 'Windows' else 'python3'
            self.detail('Remove integration', command + ' manage_hooks.py disable (keeps firmware and backups)')

    def phase(self, number, title):
        print(file=self.stream)
        print(self.paint('  %d/5  %s' % (number, title), '1;36'), file=self.stream)

    def detail(self, label, value):
        print('       ' + self.paint(label + ':', '2') + ' ' + self.text(value), file=self.stream)

    def status(self, state, message):
        labels = {'ok':('OK', '32'), 'pending':('PENDING', '33'),
                  'info':('INFO', '36'), 'working':('...', '36')}
        label, color = labels[state]
        print('  ' + self.paint('[' + label + ']', color) + ' ' + self.text(message), flush=True, file=self.stream)


def preflight_report(args):
    """Read-only agent inventory: no Bluetooth, subprocess, downloads or writes."""
    detected = provider_setup.detect()
    selected = [] if args.no_hooks else list(args.providers or [])
    providers = {}
    for provider in dict.fromkeys([*detected, *selected]):
        try:
            provider_setup.preflight([provider])
            policy = 'review_required'
            reason = None
        except (RuntimeError, ValueError, OSError) as error:
            policy, reason = 'blocked', WizardUI.text(str(error))
        providers[provider] = {'detected': provider in detected, 'evidence': detected.get(provider, []),
                               'selected': provider in selected, 'hook_policy': policy, 'reason': reason}
    connection = RUNTIME / 'connection.json'
    saved = 'absent'
    saved_unit = None
    if connection.exists():
        try:
            value = existing_connection()
            saved_unit = {key: value[key] for key in ('transport', 'ble_name', 'device_id')}
            saved = 'present'
        except (OSError, ValueError, RuntimeError):
            saved = 'recovery_required'
    system = platform.system()
    python_supported = sys.version_info >= (3, 9)
    dependencies = {name: importlib.util.find_spec(name) is not None for name in ('venv', 'pip', 'bleak', 'serial')}
    command = 'py -3' if system == 'Windows' else 'python3'
    next_steps = ['Physical toy setup only. For the virtual desktop source preview, read docs/TRY_VIRTUAL_CLAWDY.md.']
    if system not in ('Darwin', 'Windows'):
        next_steps.append('Physical setup requires native macOS or Windows; Linux/WSL is unsupported. Do not run discovery or installation here.')
    elif not python_supported:
        next_steps.append('Use Python 3.9 or newer, then rerun this offline preflight before discovery or installation.')
    elif saved == 'recovery_required':
        next_steps.append('Review the invalid saved connection.json and recover the existing integration before discovery or replacement; do not delete it automatically.')
    else:
        if saved == 'present':
            next_steps.append('Review existing_unit with the owner and release the previous controlling integration before replacing it; never replace it silently.')
        blocked = [name for name, value in providers.items() if value['hook_policy'] == 'blocked']
        if blocked:
            next_steps.append('Review blocked app policies: ' + ', '.join(blocked) + '. Choose only approved usable adapters or --no-hooks; do not bypass disabled hooks or trust controls.')
        next_steps.append('Confirm which detected supported apps may receive hooks, or choose --no-hooks. Detection is not a real-provider acceptance test.')
        if not dependencies['bleak']:
            next_steps.append('Bluetooth dependencies are missing. Discovery with --yes may create a private Python environment and download packages; obtain approval first.')
        next_steps += [
            'After approving any downloads, discover powered toys with ' + command + ' install.py --onboard --list-devices --json --yes; explicitly select and physically identify yours.',
            'Run ' + command + ' install.py --onboard interactively with the owner to review and apply the plan.',
            'Approve normal Bluetooth access and provider hook/workspace trust.',
            'Require BLE GPIO acknowledgements and human visible LEDs; test a real turn in each approved provider separately.']
    return {'version': 1, 'mode': 'preflight', 'mutations': False, 'bluetooth_scanned': False,
            'platform': system, 'platform_supported': system in ('Darwin', 'Windows'),
            'python_version': platform.python_version(), 'python_supported': python_supported,
            'dependencies': dependencies,
            'saved_connection': saved, 'existing_unit': saved_unit, 'providers': providers,
            'supported_adapters': provider_setup.adapter_inventory(),
            'provider_selection_required': args.providers is None and not args.no_hooks,
            'runtime_transport': 'ble', 'customer_ready': False,
            'setup_target': 'physical_clawdy', 'virtual_preview_guide': 'docs/TRY_VIRTUAL_CLAWDY.md',
            'next_steps': next_steps}


class BootstrapResult:
    def __init__(self, returncode):
        self.returncode = returncode


def make_name(laptop, nickname):
    """Preview the shared naming policy; the suffix needs verified device identity."""
    return device_identity.make_device_name(laptop, nickname, '00000000')[:-8] + '<UID8>'


def existing_connection():
    """Read the current owned profile without contacting its device or service."""
    path = RUNTIME / 'connection.json'
    if not path.exists():
        return None
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get('transport') not in ('ble', 'serial', 'local')
                or (value.get('transport') == 'ble' and
                    (not isinstance(value.get('ble_name'), str) or not value['ble_name'].strip()))):
            raise ValueError('Invalid saved profile')
    except (ValueError, TypeError) as error:
        raise RuntimeError('Existing connection.json needs recovery; review it before replacing this laptop integration.') from error
    return {'transport': value['transport'], 'ble_name': value.get('ble_name'),
            'device_id': value.get('device_id'), 'fingerprint': hashlib.sha256(raw).hexdigest()}


def confirm_existing_connection(args, ui):
    saved = existing_connection()
    args.existing_connection = saved
    if saved is None:
        return
    ui.detail('Existing laptop integration', '%s | %s | UID %s' %
              (saved['transport'], saved['ble_name'] or 'no BLE name', saved['device_id'] or 'unavailable'))
    ui.status('info', 'Enrollment replaces the current connection profile. Release any previous toy first.')
    if args.yes and not args.replace_existing:
        raise RuntimeError('Existing laptop integration requires explicit --replace-existing after reviewing its name and identity in --preflight.')
    if not args.replace_existing and not confirm('Replace this existing laptop integration?'):
        raise RuntimeError('Existing integration kept; no dependency, device, companion or hook changes performed.')


def confirm(message, yes=False, input_fn=input):
    if yes:
        return True
    if not sys.stdin.isatty():
        raise RuntimeError('Noninteractive setup needs --yes plus explicit --ble-name and --nickname (or --keep-name).')
    return input_fn(message + ' [y/N] ').strip().lower() in ('y', 'yes')


def select_device(devices, exact_name=None, address=None, input_fn=input, allow_prompt=True):
    candidates = [d for d in devices if (not exact_name or d['name'] == exact_name)
                  and (not address or d['address'].casefold() == address.casefold())]
    if not candidates:
        raise RuntimeError('No matching advertising Clawdy. Check power, Bluetooth permission, range, and that another laptop is disconnected.')
    if (exact_name or address) and len(candidates) == 1:
        return candidates[0]
    if not allow_prompt or not sys.stdin.isatty():
        raise RuntimeError('Select one exact --ble-name and, for duplicate names, --device-address. No arbitrary device will be chosen.')
    print('       Nearby devices (Clawdy firmware is checked next):')
    for index, device in enumerate(candidates, 1):
        print('       [%d] %s  (%s)' % (index, WizardUI.text(device['name']), WizardUI.text(device['address'])))
    try:
        choice = int(input_fn('Which toy is yours? Enter its number: '))
    except ValueError:
        raise RuntimeError('Enter a listed device number.')
    if not 1 <= choice <= len(candidates):
        raise RuntimeError('Device selection is out of range.')
    return candidates[choice - 1]


def choose_providers(args, input_fn=input):
    if args.no_hooks:
        return []
    if args.providers is not None:
        return args.providers
    found = list(provider_setup.detect())
    ui = WizardUI(getattr(args, 'no_color', False), getattr(args, 'json', False))
    ui.detail('Detected supported adapters', ', '.join(found) or 'none')
    ui.detail('Adapter limits', 'Codex, Claude Code, Gemini CLI, Cursor only. Ordinary ChatGPT/Claude Desktop/Gemini web chats have no adapter.')
    if args.dry_run:
        return found
    if args.yes:
        raise RuntimeError('Choose --providers explicitly or --no-hooks; --yes does not approve automatically detected apps.')
    if not sys.stdin.isatty():
        raise RuntimeError('Use --providers or --no-hooks for noninteractive setup.')
    text = input_fn('Providers (codex claude gemini cursor), Enter for detected, or none: ').strip().lower()
    if text == 'none':
        return []
    selected = text.split() if text else found
    if any(p not in provider_setup.SUPPORTED for p in selected):
        raise ValueError('Choose only codex, claude, gemini, cursor, or none.')
    return list(dict.fromkeys(selected))


def installer_command(name, providers, device_id=None):
    command = [sys.executable, str(ROOT / 'install.py'), '--transport', 'ble', '--ble-name', name]
    if device_id:
        command += ['--device-id', device_id]
    return command + (['--providers', *providers] if providers else ['--no-hooks'])


def ensure_dependencies(args, argv):
    if importlib.util.find_spec('bleak') is not None:
        return False
    ui = WizardUI(getattr(args, 'no_color', False), getattr(args, 'json', False))
    ui.status('info', 'Bluetooth setup needs a private Python environment and packages from PyPI.')
    if not confirm('Create ~/.local/share/trafficlights/venv and download Bluetooth dependencies?', args.yes):
        raise RuntimeError('Setup cancelled before dependency installation.')
    python = venv_python(RUNTIME)
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(RUNTIME / 'venv')], check=True, timeout=120)
    ui.status('working', 'Preparing Bluetooth dependencies...')
    subprocess.run([str(python), '-m', 'pip', 'install', 'bleak==0.22.3', 'pyserial==3.5'], check=True,
                   timeout=DEPENDENCY_TIMEOUT, stdout=sys.stderr if getattr(args, 'json', False) else None)
    ui.status('ok', 'Dependencies ready. Continuing setup in the private environment.')
    result = subprocess.run([str(python), str(Path(__file__).resolve()), *argv], check=False)
    return BootstrapResult(result.returncode)


def human_confirmation(message, input_fn=input):
    """--yes accepts install changes; it cannot assert a physical observation."""
    if not sys.stdin.isatty():
        return False
    return input_fn(message + ' [y/N] ').strip().lower() in ('y', 'yes')


def verify_install(device_id=None, timeout=30, ui=None, checks=None, expected_name=None):
    from scripts import verify_hardware
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
        raise ValueError('Verification timeout must be finite and nonnegative.')
    ui = ui or WizardUI()
    ui.status('info', 'Allow the normal Bluetooth request for Traffic Light Bridge.')
    ui.detail('Hook permissions', 'Review hooks and workspace trust in each selected AI app.')
    if sys.stdin.isatty():
        input('Press Enter after granting Bluetooth permission to test the lights: ')
    ui.status('working', 'Waiting for your Clawdy to acknowledge the Bluetooth connection...')
    deadline = time.monotonic() + timeout
    while True:
        try:
            status = verify_hardware.request({'action': 'status'})
            if not isinstance(status, dict) or not isinstance(status.get('hardware_connected'), bool):
                raise RuntimeError('Installed, but bridge status is malformed; Bluetooth delivery is not verified.')
            report = status.get('firmware_report')
            if report is not None and not isinstance(report, dict):
                raise RuntimeError('Installed, but the firmware report is malformed; Bluetooth delivery is not verified.')
            report = report or {}
            if status['hardware_connected'] and expected_name is not None and report.get('ble_name') != expected_name:
                raise RuntimeError('Installed, but Bluetooth delivery is not verified: connected toy name differs from selection.')
            if (status['hardware_connected'] and device_id is not None
                    and report.get('device_id') != device_id):
                raise RuntimeError('Installed, but Bluetooth delivery is not verified: connected toy identity differs from selection.')
            port = status.get('port')
            if (status['hardware_connected'] and status.get('transport') == 'ble'
                    and isinstance(port, str) and port.startswith('ble://') and port[6:]
                    and report.get('transport') == 'ble'):
                break
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('Installed, but Bluetooth delivery is not verified. Grant Bluetooth permission, check power/range and other laptops, then run python3 manage_hooks.py status and python3 scripts/verify_hardware.py.')
        time.sleep(.5)
    ui.status('ok', 'Bluetooth identity and board connection verified.')
    if checks is not None:
        checks['bluetooth_delivery'] = 'passed'
    ui.status('working', 'Checking red, amber, green, blinking red and off...')
    try:
        verify_hardware.verify('ble', expected_device_id=device_id)
    except (AssertionError, OSError, ValueError) as error:
        raise RuntimeError('Installed, but LED acknowledgement test failed: ' + str(error)) from error
    if checks is not None:
        checks['gpio_acknowledgements'] = 'passed'
    if not human_confirmation('Did YOUR toy visibly show red, amber, green and blinking red during the test?'):
        ui.status('pending', 'Hardware acknowledgements passed; physical LED confirmation remains pending.')
        return False
    ui.status('ok', 'Clawdy is linked. Bluetooth and visible LEDs verified.')
    if checks is not None:
        checks['visible_leds'] = 'passed'
    ui.detail('Next', 'Review hooks, then try a real prompt, completion and input request in each AI app.')
    ui.status('pending', 'Real-provider acceptance, power-cycle, and laptop restart tests remain pending until actually performed.')
    return True


class RecoveryRecord:
    """Private per-unit checkpoint; records partial work without attempting rollback."""
    def __init__(self, selected, report, target, providers):
        identity = report.get('device_id') or (selected['address'] + ':' + report['ble_name'])
        key = hashlib.sha256(str(identity).encode('utf-8')).hexdigest()[:24]
        self.path = RUNTIME / 'onboarding' / (key + '.json')
        self.data = {'version': 1, 'device_id': report.get('device_id'),
                     'previous_name': report['ble_name'], 'target_name': target,
                     'providers': list(providers), 'customer_ready': False,
                     'verification': {'bluetooth_delivery': 'pending', 'gpio_acknowledgements': 'pending',
                                      'visible_leds': 'pending', 'provider_trust': 'pending',
                                      'real_provider_turns': {provider: 'pending' for provider in providers},
                                      'power_cycle': 'pending', 'host_restart': 'pending'}}

    def save(self, phase):
        self.data['phase'] = phase
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(self.path.name + '.%d.tmp' % time.time_ns())
        try:
            with open(temporary, 'x', encoding='utf-8') as output:
                os.chmod(temporary, 0o600)
                output.write(json.dumps(self.data, indent=2) + '\n')
            temporary.replace(self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Cleanup must not replace the original checkpoint failure.

    def explain(self, ui):
        ui.status('pending', 'Setup did not finish. Device or host changes may already exist; no rollback was attempted.')
        ui.detail('Recovery record', self.path)
        if self.data['phase'] == 'rename_requested':
            ui.detail('Find your toy', 'Rename acknowledgement was not confirmed. Look for either: '
                      + self.data['previous_name'] + ' / ' + self.data['target_name'])
        else:
            ui.detail('Toy name', self.data['target_name'])
        ui.detail('Before retrying', 'Inspect companion status and running installers; child processes or a service may remain.')
        command = [sys.executable, str(ROOT / 'install.py'), '--onboard', '--ble-name',
                   self.data['target_name'], '--keep-name']
        command += ['--providers', *self.data['providers']] if self.data['providers'] else ['--no-hooks']
        if sys.platform == 'win32':
            # PowerShell uses the call operator and literal single-quoted args;
            # list2cmdline only quotes CreateProcess argv and permits $ expansion.
            formatted = '& ' + ' '.join("'" + arg.replace("'", "''") + "'" for arg in command)
            label = 'PowerShell retry if the target advertises'
        else:
            formatted = shlex.join(command)
            label = 'Shell retry if the target advertises'
        ui.detail(label, formatted)
        ui.detail('Safety', 'Identify the physical toy again. If it kept the old name, select that name instead.')


def complete_setup(args, ui, selected, report, providers, nickname):
    if existing_connection() != getattr(args, 'existing_connection', None):
        raise RuntimeError('Laptop connection/profile changed during setup. Review it and confirm a new enrollment before installing.')
    target = (device_identity.make_device_name(args.laptop_name, nickname, report['device_id'])
              if nickname else report['ble_name'])
    recovery = RecoveryRecord(selected, report, target, providers)
    recovery.data['usb_identity_match'] = getattr(args, 'usb_identity', None) is not None
    recovery.data['physical_selection'] = 'operator_asserted' if args.identified_device else 'visible_confirmed'
    changes_possible = False
    try:
        if nickname:
            ui.detail('Unique Bluetooth name', target)
            recovery.save('rename_requested')
            ui.detail('Recovery record', recovery.path)
            changes_possible = True
            ui.status('working', 'Saving the name on your toy...')
            ack = asyncio.run(device_identity.rename_device(selected['address'], target, report['device_id']))
            if (not isinstance(ack, dict) or ack.get('ok') is not True
                    or ack.get('persistent') is not True or ack.get('ble_name') != target):
                raise RuntimeError('Board did not acknowledge a persistent rename; host installation stopped.')
            recovery.save('renamed')
            ui.status('ok', 'Your toy confirmed the saved name.')
        else:
            ui.status('ok', 'Keeping your toy name: ' + target)
        recovery.save('installing')
        if existing_connection() != getattr(args, 'existing_connection', None):
            raise RuntimeError('Laptop connection/profile changed before host installation; review and confirm a new enrollment.')
        changes_possible = True
        ui.phase(5, 'Install & check')
        ui.status('working', 'Installing the local companion and your selected hooks...')
        try:
            subprocess.run(installer_command(target, providers, report.get('device_id')),
                           check=True, timeout=INSTALL_TIMEOUT,
                           stdout=sys.stderr if getattr(args, 'json', False) else None)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('Companion installation timed out. The direct installer was stopped; '
                               'child processes or installed components may remain.') from error
        except subprocess.CalledProcessError as error:
            raise RuntimeError('Companion installation failed (exit %s); some components may already be installed.'
                               % error.returncode) from error
        recovery.save('installed_unverified')
        if args.skip_verification:
            ui.status('pending', 'Installed; Bluetooth delivery, visible LEDs and real provider acceptance remain unverified.')
            ui.detail('Check next', 'python3 manage_hooks.py status; python3 scripts/verify_hardware.py')
            ui.detail('Recovery record', recovery.path)
            emit_result(args, recovery)
            return 0
        with contextlib.redirect_stdout(ui.stream):
            verified = verify_install(report.get('device_id'), ui=ui, expected_name=target,
                                      checks=recovery.data['verification'])
        if verified:
            # Keep mock/API callers consistent with the successful verifier.
            for key in ('bluetooth_delivery', 'gpio_acknowledgements', 'visible_leds'):
                recovery.data['verification'][key] = 'passed'
            recovery.save('hardware_verified')
        else:
            recovery.save('installed_unverified')
        emit_result(args, recovery)
        return 0 if verified else 2
    except (Exception, KeyboardInterrupt):
        if changes_possible:
            try:
                recovery.explain(ui)
            except (OSError, ValueError):
                pass  # A closed terminal must not mask the original failure.
        raise


def emit_result(args, recovery):
    if getattr(args, 'json', False):
        print(json.dumps({'version': 1, 'mode': 'onboarding', 'phase': recovery.data['phase'],
                          'software_installed': True, 'customer_ready': False,
                          'target_name': recovery.data['target_name'],
                          'physical_selection': recovery.data['physical_selection'],
                          'verification': recovery.data['verification'],
                          'recovery_record': str(recovery.path)}, indent=2))


def run_cli(argv=None):
    """Shared entrypoint for both install.py --onboard and direct wizard use."""
    try:
        return main(argv)
    except KeyboardInterrupt:
        print('Clawdy setup cancelled. No further setup actions will run; review any recovery details above.', file=sys.stderr)
        return 130
    except EOFError:
        print('Clawdy setup stopped: terminal input ended. Rerun interactively and review any recovery details above.', file=sys.stderr)
        return 2
    except Exception as error:
        message = WizardUI.text(str(error) or type(error).__name__)
        print('Clawdy setup stopped: ' + message, file=sys.stderr)
        return 1


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--ble-name', help='Exact current name printed on the device or seen in Bluetooth discovery')
    result.add_argument('--device-address', help='Disambiguate identical names using the address/UUID shown by discovery')
    result.add_argument('--usb-port', help='Optional identity Q on this exact allowlisted USB interface; never a runtime transport')
    result.add_argument('--usb-serial', help='Exact USB serial number from --list-usb, required with --usb-port')
    result.add_argument('--nickname', help='Your chosen device name; paired with this laptop name')
    result.add_argument('--laptop-name', default=socket.gethostname().split('.')[0])
    result.add_argument('--keep-name', action='store_true', help='Keep the firmware advertisement unchanged')
    result.add_argument('--providers', nargs='+', choices=provider_setup.SUPPORTED)
    result.add_argument('--no-hooks', action='store_true')
    result.add_argument('--yes', action='store_true', help='Accept the displayed plan; explicit device/name required')
    result.add_argument('--no-color', action='store_true', help='Use plain terminal output (also honors NO_COLOR)')
    mode = result.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Offline plan only: no scan, connection, downloads or changes')
    mode.add_argument('--preflight', action='store_true', help='Read-only OS/Python/provider/policy inventory; no scan, downloads or changes')
    mode.add_argument('--list-devices', action='store_true', help='List nearby UART candidates only; no identity exchange, rename, hooks or service installation')
    mode.add_argument('--list-usb', action='store_true', help='Read USB port metadata only; never open a serial port, scan BLE, download or install')
    result.add_argument('--json', action='store_true', help='Machine-readable result on stdout; progress goes to stderr')
    result.add_argument('--identified-device', action='store_true', help='Noninteractive assertion: you have already identified this exact physical device')
    result.add_argument('--skip-verification', action='store_true', help='Install only; leave LED/provider acceptance explicitly pending')
    result.add_argument('--replace-existing', action='store_true', help='Confirm replacing the existing laptop connection/profile after reviewing --preflight')
    result.add_argument('--scan-timeout', type=float, default=8.0)
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(argv)
    if args.nickname is not None and not args.nickname.strip():
        raise ValueError('Nickname cannot be empty or whitespace only.')
    if not args.laptop_name.strip():
        raise ValueError('Laptop name cannot be empty or whitespace only.')
    if args.ble_name is not None and (not 1 <= len(args.ble_name.encode('utf-8')) <= 29
            or any(ord(c) < 32 or ord(c) == 127 for c in args.ble_name)):
        raise ValueError('Current Bluetooth name must fit 1-29 UTF-8 bytes without controls.')
    if args.device_address is not None and not args.device_address.strip():
        raise ValueError('Device discovery address cannot be blank.')
    if bool(args.usb_port) != bool(args.usb_serial):
        raise ValueError('Optional USB identity needs both --usb-port and --usb-serial from --list-usb.')
    for value in (args.usb_port, args.usb_serial):
        if value is not None and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError('USB selection must be nonempty and contain no controls.')
    if args.usb_port and (args.preflight or args.list_devices or args.list_usb):
        raise ValueError('USB identity selection belongs on a separate enrollment command, after metadata review.')
    if args.list_usb and (args.ble_name or args.device_address):
        raise ValueError('--list-usb lists metadata only; BLE selection belongs on a separate enrollment command.')
    if args.providers is not None:
        args.providers = list(dict.fromkeys(args.providers))
    if args.keep_name and args.nickname:
        raise ValueError('Choose --nickname or --keep-name, not both.')
    if args.providers and args.no_hooks:
        raise ValueError('Choose --providers or --no-hooks, not both.')
    if not 1 <= args.scan_timeout <= 60:
        raise ValueError('Scan timeout must be between 1 and 60 seconds.')
    if not (args.preflight or args.list_devices or args.list_usb) and (args.yes or args.dry_run) and (
            not (args.ble_name or args.device_address) or not (args.nickname or args.keep_name)):
        raise ValueError('--yes/--dry-run require --ble-name or --device-address, and --nickname or --keep-name.')
    if args.yes and not (args.preflight or args.list_devices or args.list_usb or args.dry_run) and args.providers is None and not args.no_hooks:
        raise ValueError('--yes needs explicit --providers or --no-hooks before downloading or connecting.')
    if args.json and not (args.preflight or args.list_usb or args.dry_run or args.yes):
        raise ValueError('Machine-readable live setup/discovery needs --yes; use --preflight first.')
    if (args.list_devices or args.list_usb) and (args.nickname or args.keep_name or args.providers or args.no_hooks
                             or args.identified_device or args.skip_verification or args.replace_existing):
        raise ValueError('Discovery only lists candidates; supply setup choices on a separate enrollment command.')
    if args.preflight:
        print(json.dumps(preflight_report(args), indent=2))
        return 0
    if args.list_usb:
        print(json.dumps({'version': 1, 'mode': 'usb_inventory', **device_identity.usb_inventory(),
                          'ports_opened': False, 'bluetooth_scanned': False, 'mutations': False,
                          'runtime_transport': 'ble', 'customer_ready': False}, indent=2))
        return 0
    ui = WizardUI(args.no_color, args.json)
    ui.banner(args.laptop_name, preview=args.dry_run)
    if not args.dry_run:
        ui.phase(1, 'Prepare your laptop')
        ui.status('info', 'Run only one Clawdy setup on this laptop at a time; concurrent enrollment is unsupported.')
        require_platform()
        if sys.version_info < (3, 9):
            raise RuntimeError('Use Python 3.9 or newer before Clawdy setup.')
        if not args.list_devices:
            confirm_existing_connection(args, ui)
        # Fail explicit policy/configuration checks before downloading anything.
        # Bootstrap before interactive choices, since it relaunches with argv.
        if args.providers is not None or args.no_hooks:
            provider_setup.preflight(args.providers or [])
        bootstrap = ensure_dependencies(args, argv)
        if bootstrap:
            return bootstrap.returncode if isinstance(bootstrap, BootstrapResult) else 0
        ui.status('ok', 'Bluetooth tools ready. Your toy only needs power; no USB data cable.')
    if args.list_devices:
        ui.status('working', 'Listing nearby powered UART candidates; no toy will be connected or selected.')
        devices = asyncio.run(device_identity.discover_candidates(timeout=args.scan_timeout))
        candidates = [device for device in devices if (not args.ble_name or device['name'] == args.ble_name)
                      and (not args.device_address or device['address'].casefold() == args.device_address.casefold())]
        print(json.dumps({'version': 1, 'mode': 'discovery', 'devices': candidates,
                          'firmware_verified': False, 'explicit_selection_required': True,
                          'customer_ready': False, 'device_modified': False,
                          'companion_or_hooks_installed': False,
                          'dependency_bootstrap': 'may create a private venv/download packages with approval'}, indent=2))
        return 0
    ui.phase(2, 'Choose your setup')
    providers = choose_providers(args)
    if not args.dry_run:
        provider_setup.preflight(providers)
    nickname = args.nickname
    if not nickname and not args.keep_name:
        if not sys.stdin.isatty():
            raise RuntimeError('Supply --nickname or --keep-name.')
        nickname = input('What would you like to call your Clawdy? ').strip()
    desired = make_name(args.laptop_name, nickname) if nickname else args.ble_name
    ui.detail('Bluetooth name preview (UID pending)' if nickname else 'Bluetooth name',
              desired or 'Choose from nearby devices')
    if nickname:
        ui.detail('Naming', 'Laptop + nickname + unique device suffix; shortened to fit Bluetooth.')
    ui.detail('AI app hooks', ', '.join(providers) or 'none (companion only)')
    if args.usb_port:
        ui.detail('Optional USB identity Q', '%s | USB serial %s (BLE runtime remains required)' % (args.usb_port, args.usb_serial))
    ui.detail('Access', 'Normal Bluetooth permission and app hook/trust review are required.')
    if args.dry_run:
        print(json.dumps({'dry_run': True, 'current_name': args.ble_name, 'requested_name': desired,
                          'installer': None if nickname or not desired else installer_command(desired, providers),
                          'runtime_transport': 'ble', 'usb_identity_requested': bool(args.usb_port),
                          'providers': providers,
                          'provider_selection_confirmed': args.providers is not None or args.no_hooks,
                          'rename_requires_firmware_support': bool(nickname),
                          'compatibility': 'Requires a verified Clawdy BLE identity. Check delivery and visible lights on the buyer’s computer.',
                          'final_name_requires_device_identity': bool(nickname)}, indent=2))
        return 0
    ui.phase(3, 'Find your Clawdy')
    ui.status('info', 'Power on your toy nearby and disconnect its previous controlling laptop.')
    ui.status('working', 'Looking for nearby toys for up to %g seconds...' % args.scan_timeout)
    devices = asyncio.run(device_identity.discover_candidates(timeout=args.scan_timeout))
    selected = select_device(devices, args.ble_name, args.device_address, allow_prompt=not args.json)
    if not desired:
        desired = selected['name']
    ui.detail('Selected toy', selected['name'])
    ui.detail('Discovery ID', selected['address'])
    ui.status('info', 'Next: verify this toy, apply your naming choice, and install the companion and selected hooks.')
    if not confirm('Apply this setup?', args.yes):
        ui.status('info', 'Cancelled; device and host settings unchanged.')
        return 0
    ui.phase(4, 'Make it yours')
    args.usb_identity = None
    if args.usb_port:
        ui.status('working', 'Querying only the selected USB port; its immutable ID must match the selected BLE toy.')
        args.usb_identity = device_identity.inspect_usb_device(args.usb_port, args.usb_serial)
    ui.status('working', 'Checking the selected toy firmware and identity...')
    report = asyncio.run(device_identity.inspect_device(selected['address']))
    if not isinstance(report, dict):
        raise RuntimeError('Selected toy returned a malformed firmware report.')
    if args.usb_identity is not None and (report.get('device_id') != args.usb_identity.get('device_id')
            or report.get('hardware_family') != args.usb_identity.get('hardware_family')
            or report.get('ble_name') != args.usb_identity.get('ble_name')):
        raise RuntimeError('USB and BLE identities/names do not match; no LED identification, rename or host installation performed.')
    final_name = report.get('ble_name')
    if not isinstance(final_name, str) or not 1 <= len(final_name.encode('utf-8')) <= 29 or any(ord(c) < 32 or ord(c) == 127 for c in final_name):
        raise RuntimeError('Verified board did not report its Bluetooth name.')
    if selected['name'] and final_name != selected['name']:
        raise RuntimeError('Selected advertisement and firmware name differ; rediscover and confirm this toy before setup changes.')
    if (not sys.stdin.isatty() or args.json) and not args.identified_device:
        raise RuntimeError('Physical selection needs confirmation. Run interactively or provide --identified-device only after independently identifying this exact toy.')
    ui.status('info', 'Watch YOUR toy: red, amber, green, then its previous state.')
    asyncio.run(device_identity.identify_device(selected['address'], report.get('device_id')))
    if not args.identified_device and not human_confirmation('Did YOUR toy show that red/amber/green sequence?'):
        raise RuntimeError('Device was not physically confirmed; no rename or host installation performed.')
    if nickname and (report.get('rename_supported') is not True
                     or type(report.get('identity_protocol')) is not int or report['identity_protocol'] != 1):
        if not args.yes and sys.stdin.isatty() and confirm('This toy cannot save a new name. Keep its existing name instead?'):
            nickname = None
        else:
            raise RuntimeError('This firmware cannot persist a Bluetooth rename. Rerun with --keep-name; factory firmware update is required for naming.')
    identity = report.get('device_id')
    if identity is not None and (not isinstance(identity, str) or not re.fullmatch(r'[0-9a-fA-F]{8,64}', identity)):
        raise RuntimeError('Selected toy returned an invalid immutable identity; installation stopped.')
    if nickname and identity is None:
        raise RuntimeError('Selected toy did not report the immutable identity required for renaming.')
    return complete_setup(args, ui, selected, report, providers, nickname)


if __name__ == '__main__':
    raise SystemExit(run_cli())
