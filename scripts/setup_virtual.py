"""Prepare Virtual Clawdy's live status source and explicitly approved hooks."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import venv

from scripts import codex_setup, provider_setup, status_core, virtual_clawdy
from scripts.platform_support import require_platform, venv_python, hook_command

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path.home() / '.local' / 'share' / 'trafficlights'


def bridge_plan():
    """Reuse a compatible bridge and distinguish a free port from a bad reply."""
    try:
        status = virtual_clawdy.read_status()
    except ConnectionRefusedError:
        profile = RUNTIME / 'connection.json'
        try:
            saved = json.loads(profile.read_text(encoding='utf-8'))
        except FileNotFoundError:
            if sys.platform == 'darwin' and codex_setup.PLIST.exists():
                return 'review_saved_profile'
            if sys.platform == 'win32':
                from scripts.windows_service import startup_path
                if startup_path().exists():
                    return 'review_saved_profile'
        except (OSError, ValueError):
            return 'review_saved_profile'
        else:
            if not isinstance(saved, dict) or saved.get('transport') != 'local':
                return 'review_saved_profile'
        return 'start_local'
    except (OSError, ValueError, RecursionError):
        return 'review_listener'
    if status_core.observed_view(status)['confidence'] != 'reported':
        return 'review_listener'
    return 'reuse_existing'


def prepare_hooks():
    """Keep hook commands stable across checkouts and bridge restarts."""
    python = venv_python(RUNTIME)
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(RUNTIME / 'venv')
    script = RUNTIME / 'traffic.py'
    if not script.is_file():
        shutil.copy2(ROOT / 'scripts' / 'traffic.py', script)
    return python


def require_bridge_plan():
    plan = bridge_plan()
    if plan == 'review_saved_profile':
        raise RuntimeError('The saved bridge is offline or its profile needs review. '
                           'Start or recover that bridge before completing live setup.')
    if plan == 'review_listener':
        raise RuntimeError('The existing listener on 127.0.0.1:8765 did not return compatible '
                           'Clawdy status. Restore the intended bridge before completing live setup.')
    return plan


def configure_live(providers):
    require_platform()
    provider_setup.preflight(providers)
    plan = require_bridge_plan()
    # Validate paths before writing, including the Windows Codex shell override.
    if 'codex' in providers:
        hook_command(venv_python(RUNTIME), RUNTIME / 'traffic.py', powershell=True)
    python = prepare_hooks()
    if plan == 'start_local':
        subprocess.run([str(python), '-m', 'pip', 'install', 'pyserial==3.5'],
                       check=True, timeout=120)
        # A bridge may have come online while the runtime was being prepared.
        plan = require_bridge_plan()
        if plan == 'start_local':
            codex_setup.install_service('local', python=python, replace_running=False)
            deadline = time.monotonic() + 5
            while bridge_plan() != 'reuse_existing':
                if time.monotonic() >= deadline:
                    raise RuntimeError('The local bridge was installed but did not report status. '
                                       'Check the bridge log before installing hooks.')
                time.sleep(0.15)
    elif require_bridge_plan() != 'reuse_existing':
        raise RuntimeError('The existing bridge stopped responding. Run live preflight again.')
    for provider in providers:
        provider_setup.configure(provider)
    return plan


def run_cli(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', action='store_true', help='Read bridge status and app availability')
    parser.add_argument('--json', action='store_true', help='Print machine-readable preflight')
    parser.add_argument('--providers', nargs='+', choices=provider_setup.SUPPORTED,
                        help='The apps whose hook installation the user has approved')
    args = parser.parse_args(argv)
    system = require_platform()
    if args.preflight:
        if args.providers:
            parser.error('Preflight detects apps. Pass --providers separately after approval.')
        report = {'platform': system, 'bridge': bridge_plan(),
                  'detected': sorted(provider_setup.detect()), 'mutations': False}
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print('Bridge:', report['bridge'])
            print('Detected AI apps:', ', '.join(report['detected']) or 'none')
        return 0
    if args.json or not args.providers:
        parser.error('Run --virtual --preflight --json, then pass --virtual --providers with user-approved apps.')
    plan = configure_live(list(dict.fromkeys(args.providers)))
    print('Reused existing status bridge.' if plan == 'reuse_existing'
          else 'Started the per-user local status bridge.')
    print('Open Virtual Clawdy in Observe mode. Review hook trust and test a real turn in each selected app.')
    return 0
