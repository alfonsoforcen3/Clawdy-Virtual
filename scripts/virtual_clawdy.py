#!/usr/bin/env python3
"""Private NDJSON collector: explicit demo or read-only existing-bridge observation.

Never starts the legacy bridge or any hardware worker. --observe can read only
its unauthenticated loopback status; it is not a new authenticated backend and
cannot establish per-provider freshness from the legacy reply.
"""
import argparse
import io
import json
import math
import socket
import sys
import time
import uuid

if __package__:
    from . import status_core, local_chat_routes
else:
    import status_core
    import local_chat_routes

HOST = '127.0.0.1'
PORT = 8765
MAX_FRAME = 8192
READ_DEADLINE = 0.5
STATUS_REQUEST = b'{"action":"status"}\n'


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate response key')
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError('Nonfinite JSON constant')


def read_status(timeout=READ_DEADLINE):
    """Single bounded newline frame, one request in flight, no control operations."""
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Read deadline must be finite and positive')
    deadline = time.monotonic() + timeout
    def remaining():
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutError('Status deadline exceeded')
        return budget
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(remaining())
        connection.connect((HOST, PORT))
        connection.settimeout(remaining())
        connection.sendall(STATUS_REQUEST)
        frame = bytearray()
        while True:
            connection.settimeout(remaining())
            chunk = connection.recv(min(1024, MAX_FRAME + 1 - len(frame)))
            if not chunk:
                raise ValueError('Incomplete status frame')
            frame.extend(chunk)
            if len(frame) > MAX_FRAME:
                raise ValueError('Status frame too large')
            if b'\n' in frame:
                line, trailing = bytes(frame).split(b'\n', 1)
                if trailing.strip():
                    raise ValueError('Multiple status frames')
                return json.loads(line.decode('utf-8'), object_pairs_hook=_unique_object,
                                  parse_constant=_invalid_constant)


def observe_view(resolver=None):
    try:
        status = read_status()
        view = status_core.observed_view(status)
        if resolver is not None:
            view['attention_chats'] = resolver.attention_chats(status, view)
        return view
    except (OSError, ValueError, UnicodeError, RecursionError):
        return status_core.disconnected_view()


def interval_arg(value):
    try:
        interval = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError('Interval must be a number')
    if not math.isfinite(interval) or not .1 <= interval <= 60:
        raise argparse.ArgumentTypeError('Interval must be between 0.1 and 60 seconds')
    return interval


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo', action='store_true', help='Deterministic, explicitly labelled fixture timeline; no socket access')
    mode.add_argument('--observe', action='store_true', help='Read only status from an existing loopback bridge; never start it')
    result.add_argument('--once', action='store_true', help='Emit one snapshot and exit')
    result.add_argument('--interval', type=interval_arg, default=1.0, help='Seconds between polls (0.1-60, default 1)')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    instance = uuid.uuid4().hex
    revision = 0
    resolver = local_chat_routes.LocalChatResolver() if args.observe else None
    started = time.monotonic()
    try:
        while True:
            before = time.monotonic()
            view = status_core.demo_view(before - started) if args.demo else observe_view(resolver)
            revision += 1
            result = status_core.snapshot(instance, revision, view, args.demo)
            print(json.dumps(result, ensure_ascii=True, separators=(',', ':')), flush=True)
            if args.once:
                return 0
            # Missed intervals are dropped; there is never a backlog or parallel poll.
            time.sleep(max(0, args.interval - (time.monotonic() - before)))
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        # Prevent a second failed stdout flush from converting clean exit into 120.
        sys.stdout = io.StringIO()
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
