"""Shared native desktop platform paths and hook command quoting."""
import platform
import shlex
import subprocess

def require_platform():
    name = platform.system()
    if name not in ('Darwin', 'Windows'):
        raise RuntimeError('Use native macOS or Windows Python; Linux/WSL installation is unsupported.')
    return name

def venv_python(runtime):
    return runtime / 'venv' / ('Scripts/python.exe' if platform.system() == 'Windows' else 'bin/python')

def hook_command(python, script, powershell=False):
    parts = [str(python), str(script)]
    if platform.system() == 'Windows':
        if powershell:
            if any('\n' in part or '\r' in part for part in parts):
                raise ValueError('Hook paths cannot contain newlines.')
            return '& ' + ' '.join("'" + part.replace("'", "''") + "'" for part in parts)
        # cmd.exe treats percent signs as environment expansions, even inside quotes.
        if any('%' in part or '\n' in part or '"' in part for part in parts):
            raise ValueError('Move the checkout/runtime to a path without %, quotes or newlines.')
        return ' '.join('"' + part + '"' for part in parts)
    return ' '.join(shlex.quote(part) for part in parts)
