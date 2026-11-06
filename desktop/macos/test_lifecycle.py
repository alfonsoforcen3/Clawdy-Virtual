#!/usr/bin/env python3
"""Native private-demo fault tests. Never enables hooks or starts a hardware bridge."""
import argparse
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time


class Demo:
    def __init__(self, executable, overlay=True):
        self.process = subprocess.Popen(
            [str(executable), '--demo', '--ephemeral', '--diagnostics', '--quit-after=100'] + (['--overlay'] if overlay else []),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.pending = b''
        self.lines = []
        self.launched = []

    def poll(self, seconds):
        ready, _, _ = select.select([self.process.stderr], [], [], seconds)
        if ready:
            chunk = os.read(self.process.stderr.fileno(), 8192)
            self.pending += chunk
            while b'\n' in self.pending:
                raw, self.pending = self.pending.split(b'\n', 1)
                line = raw.decode('utf-8', errors='replace')
                self.lines.append(line)
                match = re.search(r'(collector|renderer) launch pid=(\d+)', line)
                if match:
                    self.launched.append((match[1], int(match[2])))

    def wait(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while not predicate():
            if self.process.poll() is not None:
                raise AssertionError('Host exited unexpectedly')
            if time.monotonic() >= deadline:
                raise AssertionError('Lifecycle condition timed out')
            self.poll(min(.2, max(0, deadline-time.monotonic())))

    def observe(self, duration):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError('Host exited unexpectedly')
            self.poll(min(.2, max(0, deadline-time.monotonic())))

    def count(self, role):
        return sum(item[0] == role for item in self.launched)

    def latest(self, role):
        return next(pid for item_role, pid in reversed(self.launched) if item_role == role)

    def send_to_owned(self, role, action):
        pid = self.latest(role)
        parent = subprocess.check_output(['ps', '-p', str(pid), '-o', 'ppid='], text=True).strip()
        if parent != str(self.process.pid):
            raise AssertionError('Refusing to signal a process not owned by this test host')
        os.kill(pid, action)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Signal only still-owned children before terminating this host.
                for role in ('renderer', 'collector'):
                    try:
                        self.send_to_owned(role, signal.SIGKILL)
                    except (StopIteration, ProcessLookupError, subprocess.CalledProcessError, AssertionError):
                        pass
                self.process.kill()
                self.process.wait(timeout=3)
                raise AssertionError('Host failed to terminate cleanly')
        while select.select([self.process.stderr], [], [], 0)[0]:
            before = len(self.lines)
            self.poll(0)
            if len(self.lines) == before:
                break
        self.process.stderr.close()


def run(executable):
    demo = Demo(executable)
    try:
        demo.wait(lambda: demo.count('renderer') == 1 and demo.count('collector') == 1)
        demo.observe(12)
        assert not any('retry reason=' in line or 'safe-mode' in line for line in demo.lines), 'Healthy app restarted a child'
        print('PASS: healthy demo stayed responsive beyond watchdog interval', flush=True)

        before = demo.count('collector')
        renderer_count = demo.count('renderer')
        demo.send_to_owned('collector', signal.SIGKILL)
        demo.wait(lambda: demo.count('collector') > before)
        assert demo.count('renderer') == renderer_count, 'Collector crash restarted renderer'
        print('PASS: collector crash recovered without restarting renderer', flush=True)

        collector = demo.latest('collector')
        before = demo.count('renderer')
        demo.send_to_owned('renderer', signal.SIGSTOP)
        demo.wait(lambda: demo.count('renderer') > before, timeout=18)
        assert demo.latest('collector') == collector, 'Renderer freeze restarted status collector'
        assert any('main-loop-timeout' in line for line in demo.lines)
        print('PASS: frozen renderer recovered while host and collector survived', flush=True)

        # The freeze used one retry; two further retries are allowed, then safe mode.
        for attempt in range(3):
            before = demo.count('renderer')
            demo.send_to_owned('renderer', signal.SIGKILL)
            if attempt < 2:
                demo.wait(lambda: demo.count('renderer') > before)
            else:
                demo.wait(lambda: any('renderer safe-mode' in line for line in demo.lines))
        count = demo.count('renderer')
        demo.observe(3)
        assert demo.count('renderer') == count, 'Renderer restarted after circuit breaker'
        print('PASS: repeated renderer crashes entered bounded safe mode', flush=True)
    except BaseException:
        print('\n'.join(demo.lines), file=sys.stderr)
        raise
    finally:
        demo.stop()
    assert demo.process.returncode == 0, 'Host did not exit successfully on SIGTERM'
    for _, pid in demo.launched:
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
        assert not result.stdout.strip(), 'Owned child remained after host quit'
    print('PASS: quit stopped all owned children', flush=True)


def run_recovery(executable):
    """Only signal this fixture's own verified host/collector; never ChatGPT."""
    demo = Demo(executable, overlay=False)
    try:
        demo.wait(lambda: demo.count('collector') == 1)
        demo.observe(3)
        assert demo.count('renderer') == 0, 'Menu-only fixture launched renderer'
        # Simulate a long host scheduling gap while the collector remains alive.
        os.kill(demo.process.pid, signal.SIGSTOP)
        try:
            time.sleep(18)
        finally:
            os.kill(demo.process.pid, signal.SIGCONT)
        demo.observe(5)
        assert demo.count('collector') == 1, 'Scheduling gap falsely restarted healthy collector'
        assert not any('safe-mode' in line for line in demo.lines), 'Scheduling gap exhausted recovery'
        print('PASS: 18-second host pause recovered without false collector restart', flush=True)
        before = demo.count('collector')
        demo.send_to_owned('collector', signal.SIGSTOP)
        demo.wait(lambda: demo.count('collector') > before, timeout=24)
        demo.observe(3)
        assert demo.count('renderer') == 0, 'Collector recovery launched floating widget'
        assert demo.count('collector') == before + 1, 'Collector recovery duplicated launches'
        print('PASS: actually stalled collector recovered once in menu-only mode', flush=True)
    except BaseException:
        print('\n'.join(demo.lines), file=sys.stderr)
        raise
    finally:
        demo.stop()
    assert demo.process.returncode == 0
    for _, pid in demo.launched:
        command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
        assert not command.stdout.strip(), 'Recovery fixture left an owned child'
    print('PASS: menu-only recovery fixture cleaned up all owned children', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path,
                        default=Path.home()/'Library/Caches/ClawdyPrototype/Build/VirtualClawdy.app')
    parser.add_argument('--recovery-only', action='store_true', help='Menu-only host pause and collector stall fixture')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Native lifecycle acceptance requires macOS')
    (run_recovery if args.recovery_only else run)(args.app.resolve()/'Contents/MacOS/VirtualClawdy')
