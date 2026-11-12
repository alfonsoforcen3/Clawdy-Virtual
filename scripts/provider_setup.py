#!/usr/bin/env python3
"""Inventory local coding tools for Virtual Clawdy without changing settings."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import sys
from xml.parsers.expat import ExpatError

SUPPORTED = ('codex', 'claude', 'gemini', 'cursor')
APP_BUNDLES = {'codex': (('Codex.app', 'com.openai.codex'), ('ChatGPT.app', 'com.openai.codex')),
               'cursor': (('Cursor.app', 'com.todesktop.230313mzl4w4u92'),)}


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

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--detect', action='store_true', help='List detected tools')
    parser.add_argument('--json', action='store_true', help='Print machine-readable inventory')
    args = parser.parse_args()
    found = detect()
    if args.json:
        print(json.dumps({'detected': sorted(found), 'mutations': False}))
    else:
        print('Detected local coding tools: ' + (', '.join(sorted(found)) or 'none'))
        print('Live status requires an existing local integration. Use --demo to try simulated activity.')


if __name__ == '__main__':
    main()
