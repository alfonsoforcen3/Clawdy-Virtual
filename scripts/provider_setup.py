#!/usr/bin/env python3
"""Detect supported local AI apps and merge their owned traffic-light hooks."""
import argparse
import json
import os
import plistlib
from pathlib import Path
import shlex
import shutil
import sys
import time
from xml.parsers.expat import ExpatError

try:
    from scripts.platform_support import venv_python, hook_command
except ModuleNotFoundError:
    from platform_support import venv_python, hook_command

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path.home() / '.local/share/trafficlights'
SUPPORTED = ('codex','claude','gemini','cursor')
ADAPTER_LABELS = {'codex': 'Codex local CLI/desktop hooks', 'claude': 'Claude Code hooks',
                  'gemini': 'Gemini CLI hooks', 'cursor': 'Cursor hooks'}
APP_BUNDLES = {'codex': (('Codex.app', 'com.openai.codex'), ('ChatGPT.app', 'com.openai.codex')),
               'cursor': (('Cursor.app', 'com.todesktop.230313mzl4w4u92'),)}
EVENTS = {
    'gemini': {'SessionStart':'G','BeforeAgent':'Y',
               'BeforeTool':'Y','AfterTool':'Y','AfterAgent':'G','Notification':'','SessionEnd':'O'},
    # Avoid Cursor permission/tool-gating hooks: this integration observes lifecycle only.
    'cursor': {'sessionStart':'G','beforeSubmitPrompt':'Y','afterAgentThought':'Y',
               'afterAgentResponse':'Y','stop':'G','sessionEnd':'O'},
}

def adapter_inventory():
    """Scope of shipped adapters, separate from installation evidence or acceptance."""
    return {'supported': dict(ADAPTER_LABELS),
            'unsupported': ['Ordinary ChatGPT chats', 'Claude Desktop chats', 'Gemini web chats',
                            'Other AI apps or models without a repository adapter'],
            'detection_is_acceptance': False}

def settings_path(provider):
    return Path.home() / ('.cursor/hooks.json' if provider == 'cursor' else '.' + provider + '/settings.json')

def windows_provider_evidence(provider):
    home = Path.home()
    local = os.environ.get('LOCALAPPDATA')
    roaming = os.environ.get('APPDATA')
    program_files = os.environ.get('ProgramFiles')
    candidates = []
    if provider == 'codex':
        if local:
            root = Path(local)
            candidates.extend((root / 'Packages').glob('OpenAI.Codex_*'))
            candidates.extend(root / path for path in
                              ('Microsoft/WindowsApps/chatgpt-desktop.exe', 'Programs/Codex/Codex.exe'))
        if program_files:
            candidates.append(Path(program_files) / 'Codex/Codex.exe')
    if provider == 'claude':
        candidates.append(home / '.local/bin/claude.exe')
    if provider in ('claude', 'gemini') and roaming:
        candidates.append(Path(roaming) / 'npm' / (provider + '.cmd'))
    if provider == 'cursor':
        if local:
            candidates.extend(Path(local) / path for path in
                              ('Programs/cursor/Cursor.exe', 'cursor/Cursor.exe'))
        if program_files:
            candidates.append(Path(program_files) / 'Cursor/Cursor.exe')
    evidence = [str(path) for path in candidates if path.exists()]
    config_dir = home / ('.' + provider)
    if provider in ('codex', 'gemini') and config_dir.is_dir():
        try:
            if next(config_dir.iterdir(), None) is not None:
                evidence.append(str(config_dir))
        except OSError:
            pass
    return evidence


def detect(application_directories=None):
    """Evidence of installation: executable, app bundle, or actual settings file; never execute an AI request."""
    evidence = {}
    application_directories = (Path('/Applications'), Path.home()/'Applications') if application_directories is None else application_directories
    for provider in SUPPORTED:
        hits = windows_provider_evidence(provider) if sys.platform == 'win32' else []
        executables = {'cursor':('cursor','cursor-agent','agent')}.get(provider,(provider,))
        for executable in executables:
            found = shutil.which(executable)
            # A generic 'agent' executable alone is not sufficient evidence of Cursor.
            if found and (executable != 'agent' or 'cursor' in found.lower()):
                hits.append(found)
        # Claude Desktop is not Claude Code. Likewise ordinary ChatGPT is not
        # Codex merely because its app folder happens to have the same name.
        for app, expected_id in APP_BUNDLES.get(provider, ()):
            for directory in application_directories:
                path = Path(directory)/app
                try:
                    with (path/'Contents/Info.plist').open('rb') as source:
                        identity = plistlib.load(source)
                    if isinstance(identity, dict) and identity.get('CFBundleIdentifier') == expected_id:
                        hits.append(str(path))
                except (OSError, ValueError, plistlib.InvalidFileException, ExpatError):
                    pass
        config = Path.home()/'.codex/hooks.json' if provider == 'codex' else settings_path(provider)
        if config.exists(): hits.append(str(config))
        if hits: evidence[provider] = list(dict.fromkeys(hits))
    return evidence

def owns_hook(hook, provider):
    """Ownership fields on unrelated hooks may be null or nonstring."""
    if not isinstance(hook, dict):
        return False
    marker = hook.get('statusMessage')
    name = hook.get('name')
    command = hook.get('command')
    if provider in ('codex', 'claude'):
        prefix = 'Traffic light:' if provider == 'codex' else 'Traffic light: Claude '
        return isinstance(marker, str) and marker.startswith(prefix)
    command = command if isinstance(command, str) else ''
    if provider == 'cursor':
        return ('traffic.py' in command and '--provider cursor' in command
                and '--trafficlights-hook' in command)
    return (isinstance(name, str) and (name.startswith('trafficlights-gemini-')
            or (name.startswith('traffic-light-') and 'traffic.py' in command
                and '--provider gemini' in command)))


def validate_config(data, provider, enable=True):
    """Validate every container consumed by setup before mutation or installation."""
    if provider not in SUPPORTED:
        raise ValueError('Unsupported provider: ' + str(provider))
    if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict):
        raise RuntimeError('Invalid hook configuration; settings left unchanged.')
    for key in ('enabled', 'disableAllHooks'):
        if key in data and not isinstance(data[key], bool):
            raise RuntimeError('Invalid hook policy ' + key + '; settings left unchanged.')
    if enable and (data.get('enabled') is False or data.get('disableAllHooks') is True):
        raise RuntimeError(provider + ' hooks are disabled; review your preference first.')
    if provider == 'cursor' and (type(data.get('version', 1)) is not int or data.get('version', 1) != 1):
        raise RuntimeError('Unsupported Cursor hook schema version; settings left unchanged.')
    disabled_names = []
    if provider == 'gemini':
        config = data.get('hooksConfig', {})
        if not isinstance(config, dict):
            raise RuntimeError('Invalid Gemini hooksConfig; settings left unchanged.')
        if 'enabled' in config and not isinstance(config['enabled'], bool):
            raise RuntimeError('Invalid Gemini hooks policy; settings left unchanged.')
        if enable and config.get('enabled') is False:
            raise RuntimeError('Gemini hooks are disabled; settings left unchanged.')
        disabled_names = config.get('disabledHookNames', [])
        if not isinstance(disabled_names, list) or any(not isinstance(name, str) for name in disabled_names):
            raise RuntimeError('Invalid Gemini disabledHookNames; settings left unchanged.')
    owned_names = set('trafficlights-gemini-' + event for event in EVENTS['gemini'])
    for event, groups in data.get('hooks', {}).items():
        if not isinstance(event, str) or not isinstance(groups, list):
            raise RuntimeError('Invalid hook event entries; settings left unchanged.')
        for group in groups:
            if not isinstance(group, dict):
                raise RuntimeError('Invalid hook group; settings left unchanged.')
            handlers = [group] if provider == 'cursor' else group.get('hooks', [])
            if not isinstance(handlers, list) or any(not isinstance(hook, dict) for hook in handlers):
                raise RuntimeError('Invalid hook handlers; settings left unchanged.')
            for hook in handlers:
                if owns_hook(hook, provider):
                    for container in (hook, group):
                        if 'enabled' in container and not isinstance(container['enabled'], bool):
                            raise RuntimeError('Invalid owned hook policy; settings left unchanged.')
                    if isinstance(hook.get('name'), str):
                        owned_names.add(hook['name'])
                    if enable and (hook.get('enabled') is False or group.get('enabled') is False):
                        raise RuntimeError('An owned hook is disabled; review that preference first.')
    if enable and provider == 'gemini' and owned_names.intersection(disabled_names):
        raise RuntimeError('A Gemini traffic-light hook is disabled; settings left unchanged.')


def remove_ours(data, provider):
    validate_config(data, provider, enable=False)
    for event, groups in list(data.get('hooks', {}).items()):
        retained = []
        changed = False
        for group in groups:
            if provider == 'cursor':
                if owns_hook(group, provider):
                    changed = True
                else:
                    retained.append(group)
                continue
            handlers = group.get('hooks', [])
            remaining = [hook for hook in handlers if not owns_hook(hook, provider)]
            if len(remaining) == len(handlers):
                retained.append(group)
            else:
                changed = True
                if remaining:
                    retained.append(dict(group, hooks=remaining))
        if changed:
            if retained:
                data['hooks'][event] = retained
            else:
                del data['hooks'][event]


def preflight(providers):
    """Validate all selected configs before installing the service or any hooks."""
    for provider in providers:
        if provider not in SUPPORTED:
            raise ValueError('Unsupported provider: ' + str(provider))
        path = Path.home()/'.codex/hooks.json' if provider == 'codex' else settings_path(provider)
        data = json.loads(path.read_text()) if path.exists() else {}
        validate_config(data, provider)
        hook_command(venv_python(RUNTIME), RUNTIME/'traffic.py', powershell=provider == 'gemini')


def configure(provider, enable=True):
    if provider not in SUPPORTED:
        raise ValueError('Unsupported provider: ' + str(provider))
    if enable:
        preflight([provider])
    if provider == 'codex':
        try: from scripts import codex_setup
        except ModuleNotFoundError: import codex_setup
        if not enable: raise RuntimeError('Use manage_hooks.py disable for Codex/shared service removal.')
        codex_setup.enable(install_login_service=False)
        return
    if provider == 'claude':
        try: from scripts import claude_setup
        except ModuleNotFoundError: import claude_setup
        claude_setup.configure(enable)
        return
    path = settings_path(provider)
    if not enable and not path.exists(): return
    data = json.loads(path.read_text()) if path.exists() else {}
    validate_config(data, provider, enable=enable)
    if provider == 'cursor' and data.get('version',1) != 1:
        raise RuntimeError('Unsupported Cursor hook schema version; settings left unchanged.')
    if enable and provider == 'gemini' and data.get('hooksConfig',{}).get('enabled') is False:
        raise RuntimeError('Gemini hooks are disabled; settings left unchanged.')
    python = venv_python(RUNTIME)
    if enable and not python.exists(): raise RuntimeError('Install the shared desktop bridge first.')
    remove_ours(data,provider)
    if enable:
        base = hook_command(python, RUNTIME/'traffic.py', powershell=provider == 'gemini')
        if provider == 'cursor': data.setdefault('version',1)
        for event,state in EVENTS[provider].items():
            command = base + (' ' + state if state else '') + ' --provider ' + provider
            if provider == 'cursor':
                command += ' --trafficlights-hook'
                if event == 'beforeSubmitPrompt': command += ' --cursor-prompt'
                data.setdefault('hooks',{}).setdefault(event,[]).append({'command':command,'timeout':3})
            else:
                group = {'hooks':[{'name':'trafficlights-gemini-'+event,'type':'command',
                                   'command':command,'timeout':10000 if sys.platform == 'win32' else 3000}]}
                if event in ('BeforeTool','AfterTool'): group['matcher'] = '.*'
                data.setdefault('hooks',{}).setdefault(event,[]).append(group)
    if path.exists():
        backup = ROOT/'.backups'/(provider+'-settings-'+str(time.time_ns())+'.json')
        backup.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,backup)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,indent=2)+'\n')
    temporary.replace(path)
    print(('Installed' if enable else 'Removed') + ' owned '+provider+' hooks: '+str(path))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--detect',action='store_true',help='Read-only inventory; no configuration changes')
    parser.add_argument('--json',action='store_true',help='Machine-readable inventory (requires --detect)')
    parser.add_argument('--providers',nargs='+',choices=SUPPORTED)
    parser.add_argument('--disable',action='store_true',help='Remove selected adapters, leaving shared service running')
    args = parser.parse_args()
    if args.json and not args.detect:
        parser.error('--json requires --detect')
    found = detect()
    if args.detect and args.json:
        print(json.dumps({'detected': sorted(found), 'mutations': False}, indent=2))
        return
    print('Detected providers: '+(', '.join(found) or 'none'))
    if args.detect:
        print('Unsupported: '+', '.join(adapter_inventory()['unsupported']))
        print('Detection is inventory only; choose adapters explicitly and test real turns after hook trust review.')
        return
    if args.providers is None:
        parser.error('Choose --providers explicitly after reviewing --detect; detection alone does not approve hook changes')
    selected = list(dict.fromkeys(args.providers))
    if not args.disable:
        preflight(selected)
    for provider in selected:
        configure(provider,not args.disable)
    print('Review provider hook/workspace trust and policy; configured hooks still require live acceptance tests.')

if __name__ == '__main__': main()
