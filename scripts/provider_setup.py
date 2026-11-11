#!/usr/bin/env python3
"""Detect supported local AI apps and merge their owned traffic-light hooks."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys
import time

try:
    from scripts.platform_support import venv_python, hook_command
except ModuleNotFoundError:
    from platform_support import venv_python, hook_command

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path.home() / '.local/share/trafficlights'
SUPPORTED = ('codex','claude','gemini','cursor')
EVENTS = {
    'gemini': {'SessionStart':'G','BeforeAgent':'Y',
               'BeforeTool':'Y','AfterTool':'Y','AfterAgent':'G','Notification':'','SessionEnd':'O'},
    # Avoid Cursor permission/tool-gating hooks: this integration observes lifecycle only.
    'cursor': {'sessionStart':'G','beforeSubmitPrompt':'Y','afterAgentThought':'Y',
               'afterAgentResponse':'Y','stop':'G','sessionEnd':'O'},
}

PROVIDER_DISPLAY_NAMES = {
    'codex': 'OpenAI Codex / ChatGPT Desktop',
    'claude': 'Claude Code / Desktop',
    'gemini': 'Gemini CLI',
    'cursor': 'Cursor Agent'
}

def settings_path(provider):
    return Path.home() / ('.cursor/hooks.json' if provider == 'cursor' else '.' + provider + '/settings.json')

def detect():
    """Evidence of installation: executable, app bundle, Windows package/dir, or actual settings file; never execute an AI request."""
    import glob
    import os

    evidence = {}
    home = Path.home()
    local_appdata = os.environ.get('LOCALAPPDATA', '')
    roaming_appdata = os.environ.get('APPDATA', '')
    prog_files = os.environ.get('ProgramFiles', '')

    for provider in SUPPORTED:
        hits = []

        # 1. Standard executable lookups across platforms
        executables = {
            'codex': ('codex', 'chatgpt-desktop', 'chatgpt'),
            'cursor': ('cursor', 'cursor-agent', 'agent'),
            'claude': ('claude',),
            'gemini': ('gemini',),
        }.get(provider, (provider,))

        for executable in executables:
            found = shutil.which(executable)
            if found and (executable != 'agent' or 'cursor' in found.lower()):
                if found not in hits:
                    hits.append(found)

        # 2. macOS Application bundles
        app_names = {'codex': ('Codex.app', 'ChatGPT.app'), 'claude': ('Claude.app',), 'cursor': ('Cursor.app',)}
        for app in app_names.get(provider, ()):
            for directory in (Path('/Applications'), home / 'Applications'):
                path = directory / app
                if path.exists():
                    hits.append(str(path))

        # 3. Windows-specific packages, execution aliases, and application paths
        if sys.platform == 'win32':
            if provider == 'codex':
                # OpenAI Codex / ChatGPT Desktop Windows package & app paths
                if local_appdata:
                    for pkg in glob.glob(os.path.join(local_appdata, 'Packages', 'OpenAI.Codex_*')):
                        hits.append(pkg)
                    alias = os.path.join(local_appdata, 'Microsoft', 'WindowsApps', 'chatgpt-desktop.exe')
                    if os.path.exists(alias):
                        hits.append(alias)
                    chatgpt_exe = os.path.join(local_appdata, 'Programs', 'ChatGPT', 'ChatGPT.exe')
                    if os.path.exists(chatgpt_exe):
                        hits.append(chatgpt_exe)
                codex_dir = home / '.codex'
                if codex_dir.exists() and any(codex_dir.iterdir()):
                    hits.append(str(codex_dir))

            elif provider == 'claude':
                # Claude Code local bin and npm cmd
                local_claude = home / '.local' / 'bin' / 'claude.exe'
                if local_claude.exists():
                    hits.append(str(local_claude))
                if roaming_appdata:
                    npm_claude = os.path.join(roaming_appdata, 'npm', 'claude.cmd')
                    if os.path.exists(npm_claude):
                        hits.append(npm_claude)
                if local_appdata:
                    claude_app = os.path.join(local_appdata, 'Programs', 'Claude', 'Claude.exe')
                    if os.path.exists(claude_app):
                        hits.append(claude_app)
                    claude_anthropic = os.path.join(local_appdata, 'AnthropicClaude', 'Claude.exe')
                    if os.path.exists(claude_anthropic):
                        hits.append(claude_anthropic)
                claude_dir = home / '.claude'
                if claude_dir.exists() or (home / '.claude.json').exists() or (home / '.claude.json.backup').exists():
                    hits.append(str(claude_dir if claude_dir.exists() else home / '.claude.json'))

            elif provider == 'cursor':
                # Cursor Windows executable and appdata
                if local_appdata:
                    cursor_exe = os.path.join(local_appdata, 'Programs', 'cursor', 'Cursor.exe')
                    if os.path.exists(cursor_exe):
                        hits.append(cursor_exe)
                    cursor_exe2 = os.path.join(local_appdata, 'cursor', 'Cursor.exe')
                    if os.path.exists(cursor_exe2):
                        hits.append(cursor_exe2)
                if prog_files:
                    cursor_pfiles = os.path.join(prog_files, 'Cursor', 'Cursor.exe')
                    if os.path.exists(cursor_pfiles):
                        hits.append(cursor_pfiles)
                cursor_dir = home / '.cursor'
                if cursor_dir.exists() or (roaming_appdata and os.path.exists(os.path.join(roaming_appdata, 'Cursor'))):
                    hits.append(str(cursor_dir if cursor_dir.exists() else os.path.join(roaming_appdata, 'Cursor')))

            elif provider == 'gemini':
                if roaming_appdata:
                    gemini_cmd = os.path.join(roaming_appdata, 'npm', 'gemini.cmd')
                    if os.path.exists(gemini_cmd):
                        hits.append(gemini_cmd)
                gemini_dir = home / '.gemini'
                if gemini_dir.exists():
                    hits.append(str(gemini_dir))

        # 4. Actual user configuration / hooks files across platforms
        config = home / '.codex/hooks.json' if provider == 'codex' else settings_path(provider)
        if config.exists():
            hits.append(str(config))

        if hits:
            evidence[provider] = hits

    return evidence

def prompt_optional_providers(detected, preselected=None):
    """Presents every detected AI on the machine and lists them as optional to install hooks."""
    if preselected:
        return [p for p in preselected if p in SUPPORTED]

    if not detected:
        print("No supported AI providers detected on this machine.")
        return []

    detected_list = [p for p in SUPPORTED if p in detected]

    # If not running in an interactive terminal, default to all detected providers
    if not sys.stdin.isatty():
        return detected_list

    print("\n" + "=" * 65)
    print("DISCOVERED AI PROVIDERS ON THIS MACHINE:")
    print("=" * 65)
    for idx, provider in enumerate(detected_list, 1):
        display_name = PROVIDER_DISPLAY_NAMES.get(provider, provider)
        evidence_sample = detected[provider][0] if detected[provider] else "installed"
        print(f"  [{idx}] {display_name:<32} (found: {evidence_sample})")

    print("\nHook installation is optional for each detected AI.")
    print("Enter the numbers of the AI tools you want to install hooks for (e.g. '1, 2'),")
    print("or 'all' to select all, or 'none' / '0' to skip hook installation.")

    try:
        choice = input("\nInstall hooks for [default: all]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nInstallation cancelled.")
        return []

    if not choice or choice in ('all', 'a', 'yes', 'y'):
        selected = detected_list
    elif choice in ('none', 'n', '0', 'no', 'skip'):
        selected = []
    else:
        selected = []
        for token in choice.replace(',', ' ').split():
            if token.isdigit():
                num = int(token)
                if 1 <= num <= len(detected_list):
                    p = detected_list[num - 1]
                    if p not in selected:
                        selected.append(p)
            elif token in detected_list and token not in selected:
                selected.append(token)

    print("Selected for hook installation:", ", ".join(PROVIDER_DISPLAY_NAMES.get(p, p) for p in selected) or "None")
    print("=" * 65 + "\n")
    return selected

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
            if provider == 'cursor':
                command = base + (' ' + state if state else '') + ' --provider ' + provider + ' --trafficlights-hook'
                if event == 'beforeSubmitPrompt': command += ' --cursor-prompt'
                data.setdefault('hooks',{}).setdefault(event,[]).append({'command':command,'timeout':3})
            elif provider == 'gemini' and sys.platform == 'win32':
                def make_fast_cmd(st):
                    return (
                        "& { try { $c=New-Object System.Net.Sockets.TcpClient; "
                        "$ar=$c.BeginConnect('127.0.0.1', 8765, $null, $null); "
                        "if ($ar.AsyncWaitHandle.WaitOne(300, $false)) { "
                        "$c.EndConnect($ar); $s=$c.GetStream(); $s.WriteTimeout=300; "
                        "$b=[System.Text.Encoding]::UTF8.GetBytes('{\"session_id\":\"gemini:$GEMINI_SESSION_ID\",\"state\":\"" + st + "\"}' + \"`n\"); "
                        "$s.Write($b, 0, $b.Length); $s.Flush(); $c.Close() } "
                        "else { $c.Close() } } catch {} ; Write-Output '{}' }"
                    )
                if event == 'BeforeTool':
                    data.setdefault('hooks',{}).setdefault(event,[]).append({
                        'matcher': 'ask.*user|request_user_input',
                        'hooks': [{'name': 'trafficlights-gemini-BeforeTool-ask_user', 'type': 'command',
                                   'command': make_fast_cmd('B'), 'timeout': 10000}]
                    })
                    data.setdefault('hooks',{}).setdefault(event,[]).append({
                        'matcher': '^(?!.*(ask.*user|request_user_input)).*',
                        'hooks': [{'name': 'trafficlights-gemini-BeforeTool', 'type': 'command',
                                   'command': make_fast_cmd('Y'), 'timeout': 10000}]
                    })
                elif event == 'Notification':
                    data.setdefault('hooks',{}).setdefault(event,[]).append({
                        'hooks': [{'name': 'trafficlights-gemini-Notification', 'type': 'command',
                                   'command': make_fast_cmd('B'), 'timeout': 10000}]
                    })
                else:
                    st = state if state else 'G'
                    group = {'hooks':[{'name':'trafficlights-gemini-'+event,'type':'command',
                                       'command':make_fast_cmd(st),'timeout':10000}]}
                    if event == 'AfterTool': group['matcher'] = '.*'
                    data.setdefault('hooks',{}).setdefault(event,[]).append(group)
            else:
                command = base + (' ' + state if state else '') + ' --provider ' + provider
                group = {'hooks':[{'name':'trafficlights-gemini-'+event,'type':'command',
                                   'command':command,'timeout':3000}]}
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
    parser.add_argument('--providers',nargs='+',choices=SUPPORTED)
    parser.add_argument('--disable',action='store_true',help='Remove selected adapters, leaving shared service running')
    args = parser.parse_args()
    found = detect()
    print('Detected providers: '+(', '.join(found) or 'none'))
    if args.detect: return
    if args.disable:
        selected = list(args.providers or found)
    else:
        selected = prompt_optional_providers(found, preselected=args.providers)
    if not selected:
        print('No providers selected for configuration.')
        return
    preflight(selected)
    for provider in selected:
        configure(provider,not args.disable)
    print('Review provider hook/workspace trust and policy; configured hooks still require live acceptance tests.')

if __name__ == '__main__': main()
