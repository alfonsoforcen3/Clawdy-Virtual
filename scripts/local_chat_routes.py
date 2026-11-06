"""Bounded local metadata checks for explicit Codex attention-chat actions.

No chat bodies, titles, arbitrary URLs, or provider controls are consumed.
"""
import json
import os
from pathlib import Path
import re
import time

UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


class LocalChatResolver:
    def __init__(self, root=None, clock=time.monotonic):
        home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
        self.root = Path(root) if root is not None else home / 'sessions'
        self.clock = clock
        self.cache = {}

    def verified(self, thread_id):
        if not isinstance(thread_id, str) or not UUID.fullmatch(thread_id):
            return False
        now = self.clock()
        cached = self.cache.get(thread_id)
        if cached is not None and now - cached[0] < 60:
            return cached[1]
        valid = False
        try:
            root = self.root.resolve()
            for index, path in enumerate(self.root.glob('*/*/*/*-' + thread_id + '.jsonl')):
                if index >= 4:
                    break
                if root not in path.resolve().parents:
                    continue
                with path.open('rb') as stream:
                    line = stream.readline(262145)
                if len(line) > 262144 or not line.endswith(b'\n'):
                    continue
                header = json.loads(line)
                meta = header.get('payload', {})
                if (header.get('type') == 'session_meta' and isinstance(meta, dict)
                        and meta.get('id') == thread_id and meta.get('source') == 'vscode'
                        and meta.get('originator') == 'Codex Desktop' and meta.get('thread_source') == 'user'):
                    valid = True
                    break
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            valid = False
        if len(self.cache) >= 128:
            self.cache.pop(next(iter(self.cache)))
        self.cache[thread_id] = (now, valid)
        return valid

    def attention_chats(self, status, view):
        flag = {'attention': 'B', 'error': 'R'}.get(view['state'])
        if flag is None:
            return []
        sessions = status.get('active_sessions', {})
        routes = []
        for key, state in sessions.items():
            if state != flag or not key.startswith('codex:'):
                continue
            thread_id = key[6:].lower()
            if self.verified(thread_id):
                route = {'provider': 'codex', 'thread_id': thread_id}
                if route not in routes:
                    routes.append(route)
            if len(routes) == 3:
                break
        return routes
