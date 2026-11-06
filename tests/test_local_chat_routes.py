import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.local_chat_routes import LocalChatResolver
from scripts import status_core as core, virtual_clawdy as collector

ID = '11111111-2222-4333-8444-555555555555'


class LocalChatRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.resolver = LocalChatResolver(self.root)

    def metadata(self, **changes):
        path = self.root / '2026/10/21' / ('rollout-test-' + ID + '.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {'id': ID, 'source': 'vscode', 'originator': 'Codex Desktop', 'thread_source': 'user'}
        meta.update(changes)
        path.write_text(json.dumps({'type': 'session_meta', 'payload': meta}) + '\n' + 'PRIVATE_CHAT_BODY\n')
        return path

    def test_verified_local_desktop_metadata_enables_only_attention_uuid(self):
        self.metadata()
        status = {'active_sessions': {'codex:' + ID: 'B', 'claude:PRIVATE': 'Y'}}
        view = {'state': 'attention'}
        self.assertEqual(self.resolver.attention_chats(status, view), [{'provider': 'codex', 'thread_id': ID}])
        self.assertEqual(self.resolver.attention_chats(status, {'state': 'error'}), [])
        self.assertEqual(self.resolver.attention_chats(status, {'state': 'working'}), [])

    def test_missing_remote_cli_subagent_and_mismatched_ids_are_not_routes(self):
        self.assertFalse(self.resolver.verified(ID))
        for changes in ({'id': 'other'}, {'source': 'cli'}, {'thread_source': 'remote'}, {'originator': 'unknown'},
                        {'source': {'subagent': {'thread_spawn': {'parent_thread_id': ID}}}}):
            self.metadata(**changes)
            self.assertFalse(LocalChatResolver(self.root).verified(ID))

    def test_paths_urls_queries_and_noncanonical_ids_never_read_metadata(self):
        with patch.object(Path, 'glob', side_effect=AssertionError('Invalid IDs must not touch files')):
            for value in ('../secret', ID + '?hostId=remote', 'codex://threads/' + ID, '', None, 7):
                self.assertFalse(self.resolver.verified(value))

    def test_metadata_read_is_bounded_and_no_body_is_needed(self):
        path = self.metadata()
        path.write_text('x' * 262145 + '\n')
        self.assertFalse(self.resolver.verified(ID))
        path.write_text('{}\nPRIVATE_BODY')
        self.assertFalse(LocalChatResolver(self.root).verified(ID))

    def test_symlink_outside_session_root_is_not_followed(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'meta.jsonl'
            target.write_text(json.dumps({'type': 'session_meta', 'payload': {
                'id': ID, 'source': 'vscode', 'originator': 'Codex Desktop', 'thread_source': 'user'}}) + '\n')
            path = self.root / '2026/10/21' / ('rollout-test-' + ID + '.jsonl')
            path.parent.mkdir(parents=True)
            try:
                path.symlink_to(target)
            except PermissionError as error:
                if getattr(error, 'winerror', None) == 1314:
                    self.skipTest('Windows runner does not grant symbolic-link creation')
                raise
            self.assertFalse(self.resolver.verified(ID))

    def test_negative_cache_expires_for_new_local_session(self):
        now = [0.0]
        resolver = LocalChatResolver(self.root, clock=lambda: now[0])
        self.assertFalse(resolver.verified(ID))
        self.metadata()
        self.assertFalse(resolver.verified(ID))
        now[0] = 61
        self.assertTrue(resolver.verified(ID))
        for index in range(150):
            resolver.verified('%08x-2222-4333-8444-555555555555' % index)
        self.assertLessEqual(len(resolver.cache), 128)

    def test_collector_routes_are_metadata_derived_not_backend_injected(self):
        self.metadata()
        status = {'status': 'ok', 'aggregate': 'B', 'active_sessions': {'codex:' + ID: 'B'},
                  'attention_chats': [{'provider': 'codex', 'thread_id': 'PRIVATE'}]}
        with patch.object(collector, 'read_status', return_value=status):
            view = collector.observe_view(self.resolver)
        record = core.snapshot('fixture', 1, view, False)
        self.assertEqual(record['attention_chats'][0]['thread_id'], ID)
        self.assertNotIn('PRIVATE', json.dumps(record))
        with patch.object(collector, 'read_status', side_effect=OSError('lost')):
            offline = core.snapshot('fixture', 2, collector.observe_view(self.resolver), False)
        self.assertNotIn('attention_chats', offline)

    def test_snapshot_rejects_untrusted_or_ineligible_chat_route(self):
        view = dict(core.observed_view({'status': 'ok', 'aggregate': 'B', 'active_sessions': {'codex:' + ID: 'B'}}))
        route = {'provider': 'codex', 'thread_id': ID}
        for bad in (None, [dict(route, url='PRIVATE')], [dict(route, thread_id=ID + '#x')],
                    [dict(route, provider='claude')], [route, route], [route] * 4):
            with self.assertRaises(ValueError):
                core.snapshot('fixture', 1, dict(view, attention_chats=bad), False)
        with self.assertRaises(ValueError):
            core.snapshot('fixture', 1, dict(core.demo_view(17), attention_chats=[route]), True)
