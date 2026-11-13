"""Per-user Windows login launcher; no administrator privileges required."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time


def startup_path():
    return Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup/TrafficLightBridge.vbs'


def stop():
    try:
        with socket.create_connection(('127.0.0.1', 8765), timeout=2) as client:
            client.sendall(b'{"action":"shutdown"}\n')
            reply = json.loads(client.recv(1024))
            if reply.get('status') != 'stopping':
                raise RuntimeError('Running bridge is too old to stop safely; close its process before updating.')
    except ConnectionRefusedError:
        return
    except TimeoutError as error:
        raise RuntimeError("Bridge shutdown timed out. Close the running bridge before retrying.") from error
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', 8765), timeout=.2):
                pass
        except ConnectionRefusedError:
            return
        except TimeoutError:
            pass
        time.sleep(.1)
    raise RuntimeError('Bridge did not stop; installation left unchanged.')


def install(root, runtime, python, config):
    stop()
    for name in ('bridge.py', 'ble_transport.py', 'dashboard.py'):
        shutil.copy2(root / 'scripts' / name, runtime / name)
    shutil.copytree(root / 'web', runtime / 'web', dirs_exist_ok=True)
    (runtime / 'connection.json').write_text(json.dumps(config, indent=2) + '\n')
    pythonw = python.with_name('pythonw.exe')
    if not pythonw.exists():
        raise RuntimeError('Native Windows Python with pythonw.exe is required.')
    # Redirect output inside Python, since pythonw has no console streams.
    launcher = runtime / 'start_bridge.py'
    launcher.write_text("import os, runpy, sys\nfrom pathlib import Path\n"
        "root = Path(__file__).resolve().parent\n"
        "sys.path.insert(0, str(root))\n"
        "sys.stdout = sys.stderr = open(root / 'bridge.log', 'a', encoding='utf-8', buffering=1)\n"
        "runpy.run_path(str(root / 'bridge.py'), run_name='__main__')\n")
    command = subprocess.list2cmdline([str(pythonw), str(launcher)])
    entry = startup_path()
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text('Set shell = CreateObject("WScript.Shell")\n'
                     'shell.Run "' + command.replace('"', '""') + '", 0, False\n')
    subprocess.Popen([str(pythonw), str(launcher)], cwd=runtime,
                     creationflags=subprocess.CREATE_NO_WINDOW)


def remove():
    # Remove startup first so a failed stop cannot cause reconnection on next login.
    startup_path().unlink(missing_ok=True)
    stop()
