#!/usr/bin/env python3
"""Check native renderer small messages and blocked-output containment without hardware."""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time


def run(executable):
    child = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        child.stdin.write(b'{"type":"ping","nonce":1}\n')
        child.stdin.flush()
        ready, _, _ = select.select([child.stdout], [], [], 5)
        assert ready, 'A small ping did not produce a reply before EOF'
        reply = os.read(child.stdout.fileno(), 4096)
        value = json.loads(reply.split(b'\n', 1)[0])
        assert value == {'type':'pong', 'nonce':1}, value
        print('PASS: small ping acknowledged while input remains open', flush=True)
        child.stdin.close()
        code = child.wait(timeout=5)
        assert code == 0, 'Renderer failed to exit cleanly after input EOF'
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream and not stream.closed:
                stream.close()

    # Fill a pipe before launch, then give its write end to the renderer. One
    # tiny pong is enough to exercise actual backpressure; a fast input flood
    # alone cannot prove stdout filled because the inbox coalesces pings.
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    filled = 0
    try:
        while True:
            filled += os.write(write_fd, b'x' * 4096)
    except BlockingIOError:
        pass
    os.set_blocking(write_fd, True)
    child = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                             stdout=write_fd, stderr=subprocess.PIPE)
    os.close(write_fd)
    try:
        child.stdin.write(b'{"type":"ping","nonce":2}\n')
        child.stdin.flush()
        time.sleep(.5)
        assert child.poll() is None, 'Renderer exited on a full output pipe'
        child.stdin.close()
        assert child.wait(timeout=5) == 0, 'Renderer could not quit with stdout blocked'
        print('PASS: prefilled stdout (%d bytes) cannot prevent EOF cleanup' % filled, flush=True)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        child.stderr.close()
        if not child.stdin.closed:
            child.stdin.close()
        os.close(read_fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path,
                        default=Path.home()/'Library/Caches/ClawdyPrototype/Build/VirtualClawdy.app')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Native protocol acceptance requires macOS')
    run(args.app.resolve()/'Contents/MacOS/ClawdyRenderer')
