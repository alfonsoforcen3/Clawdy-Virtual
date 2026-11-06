"""Private collector tests: sockets fail fast unless replaced by a fake transport."""
import contextlib
import io
import itertools
import json
from pathlib import Path
import random
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import status_core as core, virtual_clawdy as collector
from scripts import soak_virtual_clawdy as soak


def bridge(sessions, aggregate='G'):
    return {'status':'ok', 'active_sessions':sessions, 'aggregate':aggregate}


class FakeSocket:
    def __init__(self, chunks):
        self.chunks=list(chunks)
        self.timeouts=[]
        self.sent=[]
        self.address=None
        self.closed=False
        self.reads=0
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def settimeout(self,value):self.timeouts.append(value)
    def connect(self,address):self.address=address
    def sendall(self,data):self.sent.append(data)
    def recv(self,limit):
        self.reads+=1
        if not self.chunks:return b''
        data=self.chunks.pop(0)
        if isinstance(data,Exception):raise data
        if len(data)>limit:
            self.chunks.insert(0,data[limit:])
            return data[:limit]
        return data


class VirtualClawdyTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(collector.socket,'socket',side_effect=AssertionError('Real sockets forbidden'))
        self.socket=guard.start()
        self.addCleanup(guard.stop)

    def test_priority_and_working_count_are_session_scoped(self):
        sessions={'codex:one':'Y','claude:two':'Y','gemini:three':'G'}
        self.assertEqual(core.resolve_sessions(sessions),('working',2,['codex','claude']))
        sessions['codex:one']='G'
        self.assertEqual(core.resolve_sessions(sessions)[0:2],('working',1))
        sessions['cursor:four']='R'
        self.assertEqual(core.resolve_sessions(sessions)[0],'error')
        sessions['claude:five']='B'
        self.assertEqual(core.resolve_sessions(sessions)[0],'attention')

    def test_codex_process_fallback_is_not_an_identifiable_working_turn(self):
        view = core.observed_view(bridge({'codex:proc_17187':'Y'}, 'Y'))
        self.assertEqual((view['state'], view['working_count'], view['providers']), ('idle', 0, []))
        view = core.observed_view(bridge({'codex:proc_17187':'Y', 'codex:real-turn':'G'}, 'Y'))
        self.assertEqual((view['state'], view['working_count']), ('ready', 0))
        view = core.observed_view(bridge({'codex:proc_17187':'Y', 'claude:real-turn':'Y'}, 'Y'))
        self.assertEqual((view['state'], view['working_count'], view['providers']), ('working', 1, ['claude']))

    def test_attention_targets_are_separate_from_working_apps(self):
        view = core.observed_view(bridge({'codex:busy':'Y', 'claude:question':'B',
                                         'cursor:failed':'R'}, 'B'))
        self.assertEqual(view['providers'], ['codex'])
        self.assertEqual(view['attention_providers'], ['claude'])
        view = core.observed_view(bridge({'codex:busy':'Y', 'cursor:failed':'R'}, 'R'))
        self.assertEqual(view['attention_providers'], ['cursor'])
        record = core.snapshot('fixture', 1, view, False)
        self.assertEqual(record['attention_providers'], ['cursor'])
        self.assertNotIn('failed', json.dumps(record))
        for state in ('ready', 'working', 'disconnected', 'uncertain', 'idle'):
            self.assertEqual(core.attention_providers({'claude:q':'B'}, state), [])

    def test_attention_target_validation_and_legacy_default(self):
        view = core.demo_view(17)
        self.assertEqual(view['attention_providers'], ['claude'])
        legacy = core.demo_view(0)
        self.assertEqual(core.snapshot('fixture', 1, legacy, True)['attention_providers'], [])
        for bad in (None, 'codex', ['codex', 'codex'], ['file:///private'], ['SECRET']):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    core.snapshot('fixture', 1, dict(view, attention_providers=bad), True)
        with self.assertRaises(ValueError):
            core.snapshot('fixture', 1, dict(legacy, attention_providers=['codex']), True)

    def test_backend_cannot_inject_action_urls_or_override_attention_provider(self):
        data = bridge({'claude:PRIVATE_QUESTION':'B', 'codex:busy':'Y'}, 'B')
        data['attention_providers'] = ['codex', 'file:///private/SECRET']
        data['action_url'] = 'https://example.invalid/PRIVATE_QUESTION'
        record = core.snapshot('fixture', 1, core.observed_view(data), False)
        self.assertEqual(record['attention_providers'], ['claude'])
        self.assertNotIn('PRIVATE_QUESTION', json.dumps(record))
        self.assertNotIn('example.invalid', json.dumps(record))
        offline = core.snapshot('fixture', 2, core.disconnected_view(), False)
        self.assertEqual(offline['attention_providers'], [])
        self.assertEqual(offline['providers'], [])

    def test_empty_and_off_registry_are_idle(self):
        self.assertEqual(core.observed_view(bridge({}))['state'],'idle')
        self.assertEqual(core.observed_view(bridge({'codex:ended':'O'},'O'))['state'],'idle')
        self.assertEqual(core.resolve_sessions({})[0:2],('idle',0))

    def test_ready_is_not_provider_freshness_evidence(self):
        view=core.observed_view(bridge({'codex:old':'G'}))
        self.assertEqual(view['state'],'ready')
        self.assertEqual(view['confidence'],'reported')
        self.assertEqual(view['phrase'],'Last reported ready; freshness unconfirmed.')
        self.assertEqual(view['working_count'],0)

    def test_hardware_disconnect_does_not_invent_ai_disconnect(self):
        data=bridge({'claude:one':'Y'},'Y')
        data.update(hardware_connected=False,firmware_report=None,port=None)
        view=core.observed_view(data)
        self.assertEqual(view['state'],'working')
        self.assertEqual(view['confidence'],'reported')
        self.assertEqual(view['working_count'],1)

    def test_private_fields_and_unknown_providers_never_reach_snapshot(self):
        secret='SECRET_PATH_PROMPT_SESSION_HARDWARE'
        data=bridge({'codex:'+secret:'Y',secret+':x':'R'},'R')
        data.update(phrase=secret,port=secret,firmware_report={'device_id':secret},prompt=secret)
        output=core.snapshot('collector-instance',1,core.observed_view(data),False)
        self.assertEqual(set(output),{'version','instance_id','revision','state','working_count','providers','demo','phrase','confidence','attention_providers'})
        self.assertEqual(output['providers'],['codex'])
        self.assertNotIn(secret,json.dumps(output))
        self.assertLessEqual(len(output['phrase']),96)

    def test_bad_registry_and_inconsistent_aggregate_are_uncertain(self):
        for data in (None,[],{},bridge(None),bridge({'codex:x':'bad'}),
                     bridge({'codex:x':{'state':'Y'}},'Y'),bridge({'codex:x':'Y'},'G'),
                     bridge({},'Y'),bridge(dict.fromkeys(range(300),'Y'),'Y')):
            with self.subTest(data_type=type(data).__name__):
                self.assertEqual(core.observed_view(data)['state'],'uncertain')
                self.assertEqual(core.observed_view(data)['confidence'],'unknown')

    def test_observer_preserves_reported_colours_without_inventing_freshness(self):
        for flag,state,count in (('B','attention',0),('R','error',0),
                                 ('Y','working',1),('G','ready',0),('O','idle',0)):
            data=bridge({'codex:private':flag},flag)
            data.update(confidence='fresh',phrase='PRIVATE_BACKEND_PHRASE')
            record=core.snapshot('fixture',1,core.observed_view(data),False)
            self.assertEqual((record['state'],record['working_count']),(state,count))
            self.assertEqual(record['confidence'],'reported')
            self.assertEqual(record['phrase'],core.LAST_REPORTED[state])
            self.assertEqual(record['providers'],['codex'] if flag=='Y' else [])
            self.assertNotIn('PRIVATE',json.dumps(record))

    def test_green_then_backend_loss_clears_colour_count_and_confidence(self):
        with patch.object(collector,'read_status',side_effect=[
                bridge({'codex:ended':'G'}),OSError('lost'),bridge({'claude:new':'Y'},'Y')]):
            before=collector.observe_view();lost=collector.observe_view();after=collector.observe_view()
        self.assertEqual((before['state'],before['confidence']),('ready','reported'))
        self.assertEqual((lost['state'],lost['confidence'],lost['working_count'],lost['providers']),
                         ('disconnected','unknown',0,[]))
        self.assertEqual((after['state'],after['confidence'],after['working_count'],after['providers']),
                         ('working','reported',1,['claude']))

    def test_optional_confidence_defaults_conservatively_and_rejects_fresh_claims(self):
        old_view=core.observed_view(bridge({'codex:old':'G'}));old_view.pop('confidence')
        self.assertEqual(core.snapshot('fixture',1,old_view,False)['confidence'],'unknown')
        for confidence in ('fresh','demo',None,False):
            old_view['confidence']=confidence
            with self.assertRaises(ValueError):core.snapshot('fixture',1,old_view,False)
        demo_view=core.demo_view(0);demo_view.pop('confidence')
        self.assertEqual(core.snapshot('fixture',1,demo_view,True)['confidence'],'demo')

    def test_demo_timeline_is_deterministic_and_explicit(self):
        expected=[(0,'idle',0),(4,'working',1),(10,'working',2),(17,'attention',1),
                  (23,'error',1),(29,'working',1),(35,'ready',0),(42,'idle',0)]
        for moment,state,count in expected:
            with self.subTest(moment=moment):
                view=core.demo_view(moment)
                self.assertEqual((view['state'],view['working_count']),(state,count))
                self.assertTrue(view['phrase'].startswith('Demo: '))
                self.assertEqual(core.demo_view(moment),core.demo_view(moment+core.DEMO_DURATION))

    def test_only_one_read_only_status_request_and_fragmented_frame(self):
        raw=json.dumps(bridge({'codex:private':'Y'},'Y')).encode()+b'\n'
        fake=FakeSocket([raw[:5],raw[5:]])
        self.socket.side_effect=None;self.socket.return_value=fake
        result=collector.read_status()
        self.assertEqual(result['aggregate'],'Y')
        self.assertEqual(fake.address,('127.0.0.1',8765))
        self.assertEqual(fake.sent,[b'{"action":"status"}\n'])
        self.assertTrue(all(0<timeout<=collector.READ_DEADLINE for timeout in fake.timeouts))
        self.assertTrue(fake.closed)

    def test_deadline_applies_to_entire_frame_not_each_chunk(self):
        fake=FakeSocket([b'{',b'"'])
        self.socket.side_effect=None;self.socket.return_value=fake
        with patch.object(collector.time,'monotonic',side_effect=[0,.1,.2,.3,.6]):
            with self.assertRaises(TimeoutError):collector.read_status()
        self.assertEqual(fake.reads,1)
        self.assertTrue(fake.closed)

    def test_bad_frames_never_produce_ready_or_cached_work(self):
        for chunks in ([b'{}'],[b'x'*8193],[b'{"status":"ok","status":"ok"}\n'],
                       [b'{"x":NaN}\n'],[b'\xff\n'],[b'{}\n{}\n'],[socket.timeout()]):
            with self.subTest(kind=type(chunks[0]).__name__):
                fake=FakeSocket(chunks)
                self.socket.side_effect=None;self.socket.return_value=fake
                view=collector.observe_view()
                self.assertEqual(view['state'],'disconnected')
                self.assertEqual(view['working_count'],0)
                self.assertEqual(view['providers'],[])
                self.assertTrue(fake.closed)

    def test_repeated_backend_failure_cannot_replay_a_prior_reply(self):
        with patch.object(collector,'read_status',side_effect=[bridge({'codex:x':'Y'},'Y'),OSError('lost')]):
            self.assertEqual(collector.observe_view()['working_count'],1)
            self.assertEqual(collector.observe_view(),core.disconnected_view())

    def test_demo_once_never_opens_a_socket(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(collector.main(['--demo','--once']),0)
        record=json.loads(output.getvalue())
        self.assertTrue(record['demo'])
        self.assertEqual(record['revision'],1)
        self.assertEqual(len(record['instance_id']),32)
        self.socket.assert_not_called()

    def test_observe_once_sanitizes_failure(self):
        with patch.object(collector,'read_status',side_effect=OSError('private path')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(collector.main(['--observe','--once']),0)
        record=json.loads(output.getvalue())
        self.assertFalse(record['demo'])
        self.assertEqual(record['state'],'disconnected')
        self.assertNotIn('private path',output.getvalue())

    def test_loop_emits_monotonic_revision_and_stable_instance(self):
        with patch.object(collector.time,'monotonic',side_effect=[0,0,0,1,1,2,2]), \
                patch.object(collector.time,'sleep',side_effect=[None,None,KeyboardInterrupt()]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(collector.main(['--demo']),0)
        records=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([record['revision'] for record in records],[1,2,3])
        self.assertEqual(len({record['instance_id'] for record in records}),1)

    def test_broken_output_pipe_exits_cleanly(self):
        class Closed:
            def write(self,_):raise BrokenPipeError()
            def flush(self):raise BrokenPipeError()
        with patch.object(sys,'stdout',Closed()):
            self.assertEqual(collector.main(['--demo','--once']),0)

    def test_arguments_require_explicit_mode_and_finite_interval(self):
        for argv in ([],['--demo','--observe'],['--demo','--interval','nan'],
                     ['--demo','--interval','inf'],['--demo','--interval','0'],
                     ['--demo','--interval','-1'],['--demo','--interval','61']):
            with self.subTest(argv=argv),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:collector.main(argv)
                self.assertEqual(result.exception.code,2)

    def test_standalone_cli_needs_only_standard_library(self):
        script=Path(collector.__file__).resolve()
        process=subprocess.run([sys.executable,'-S',str(script),'--demo','--once'],
                               capture_output=True,text=True,timeout=10)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertTrue(json.loads(process.stdout)['demo'])
        self.assertEqual(process.stderr,'')

    def test_exhaustive_provider_combinations_preserve_legacy_priority(self):
        providers=core.PROVIDERS
        for flags in itertools.product('BRYGO',repeat=len(providers)):
            sessions={provider+':private':flag for provider,flag in zip(providers,flags)}
            expected=next((state for flag,state in (
                ('B','attention'),('R','error'),('Y','working'),('G','ready')) if flag in flags),'idle')
            state,count,summary=core.resolve_sessions(sessions)
            self.assertEqual((state,count),(expected,flags.count('Y')))
            self.assertEqual(summary,[provider for provider,flag in zip(providers,flags) if flag=='Y'])

    def test_only_working_provider_icons_remain_until_last_working_session_finishes(self):
        sessions={'codex:one':'Y','codex:two':'Y','claude:ready':'G','gemini:input':'B','cursor:error':'R'}
        self.assertEqual(core.resolve_sessions(sessions),('attention',2,['codex']))
        sessions['codex:one']='G'
        self.assertEqual(core.resolve_sessions(sessions),('attention',1,['codex']))
        sessions['codex:two']='G'
        self.assertEqual(core.resolve_sessions(sessions),('attention',0,[]))
        self.assertEqual(core.resolve_sessions({'unknown:working':'Y'}),('working',1,['other']))

    def test_registry_limit_and_overload_cannot_manufacture_ready(self):
        sessions={'codex:'+str(index):'Y' for index in range(core.MAX_SESSIONS)}
        view=core.observed_view(bridge(sessions,'Y'))
        self.assertEqual(view['working_count'],core.MAX_SESSIONS)
        self.assertEqual(view['state'],'working')
        self.assertEqual(view['confidence'],'reported')
        sessions['claude:overflow']='G'
        self.assertEqual(core.observed_view(bridge(sessions)),{
            'state':'uncertain','working_count':0,'providers':[],
            'phrase':core.PHRASES['uncertain'],'confidence':'unknown'})

    def test_fragmented_unicode_and_control_text_stays_private(self):
        secret='PRIVATE_雪_🔐_\n_\u0000'
        raw=(json.dumps(dict(bridge({'claude:'+secret:'Y'},'Y'),phrase=secret),
                        ensure_ascii=False)+'\n').encode('utf-8')
        fake=FakeSocket([bytes([byte]) for byte in raw])
        self.socket.side_effect=None;self.socket.return_value=fake
        record=core.snapshot('fixture',1,collector.observe_view(),False)
        self.assertEqual(record['working_count'],1)
        self.assertEqual(record['providers'],['claude'])
        self.assertNotIn('PRIVATE_',json.dumps(record))
        self.assertTrue(fake.closed)

    def test_exact_wire_limit_is_accepted_and_one_extra_byte_rejected(self):
        raw=json.dumps(bridge({})).encode('utf-8')
        for total,expected in ((collector.MAX_FRAME,'idle'),(collector.MAX_FRAME+1,'disconnected')):
            fake=FakeSocket([raw+b' '*(total-len(raw)-1)+b'\n'])
            self.socket.side_effect=None;self.socket.return_value=fake
            self.assertEqual(collector.observe_view()['state'],expected)
            self.assertTrue(fake.closed)
            self.assertLessEqual(fake.reads,collector.MAX_FRAME//1024+1)

    def test_connect_send_and_receive_failures_close_and_recover(self):
        good=json.dumps(bridge({'cursor:private':'Y'},'Y')).encode()+b'\n'
        for stage in ('connect','sendall','recv'):
            failed=FakeSocket([good]);recovered=FakeSocket([good])
            self.socket.side_effect=[failed,recovered]
            with patch.object(failed,stage,side_effect=OSError('PRIVATE_FAILURE')):
                self.assertEqual(collector.observe_view(),core.disconnected_view())
            self.assertTrue(failed.closed)
            view=collector.observe_view()
            self.assertEqual((view['state'],view['working_count'],view['providers']),
                             ('working',1,['cursor']))
            self.assertEqual(view['confidence'],'reported')
            self.assertTrue(recovered.closed)

    def test_nested_json_cannot_crash_the_observer(self):
        fake=FakeSocket([b'['*2000+b'0'+b']'*2000+b'\n'])
        self.socket.side_effect=None;self.socket.return_value=fake
        # Python 3.9 raises RecursionError for this frame; newer JSON parsers
        # may decode it and reject the non-object status at schema validation.
        # Both must clear activity and remain unknown, without crashing.
        view = collector.observe_view()
        self.assertIn(view['state'], ('disconnected', 'uncertain'))
        self.assertEqual(view['confidence'], 'unknown')
        self.assertEqual((view['working_count'], view['providers']), (0, []))
        self.assertTrue(fake.closed)

    def test_invalid_deadlines_do_not_create_connections(self):
        for timeout in (None,True,False,0,-1,float('nan'),float('inf'),'1'):
            with self.subTest(timeout=timeout),self.assertRaises(ValueError):
                collector.read_status(timeout)
        self.socket.assert_not_called()

    def test_seeded_malformed_reply_fuzz_stays_bounded_and_private(self):
        generator=random.Random(0xC10D)
        for index in range(500):
            # Invalid UTF-8 or invalid JSON followed by bounded random bytes.
            prefix=b'\xff' if index%2 else b'!PRIVATE'
            raw=prefix+bytes(generator.randrange(256) for _ in range(generator.randrange(512)))+b'\n'
            split=generator.randrange(1,len(raw))
            fake=FakeSocket([raw[:split],raw[split:]])
            self.socket.side_effect=None;self.socket.return_value=fake
            view=collector.observe_view()
            self.assertEqual(view,core.disconnected_view())
            self.assertTrue(fake.closed)
            self.assertLessEqual(fake.reads,2)
            self.assertNotIn('PRIVATE',json.dumps(core.snapshot('fixture',index+1,view,False)))

    def test_slow_poll_drops_missed_intervals_instead_of_replaying_catchup(self):
        sleeps=[]
        def sleep(delay):
            sleeps.append(delay)
            if len(sleeps)==2:raise KeyboardInterrupt()
        with patch.object(collector,'read_status',return_value=bridge({})) as poll, \
                patch.object(collector.time,'monotonic',side_effect=[0,0,2,2,5]), \
                patch.object(collector.time,'sleep',new=sleep), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(collector.main(['--observe','--interval','.1']),0)
        self.assertEqual(sleeps,[0,0])
        self.assertEqual(poll.call_count,2)
        self.assertEqual([json.loads(line)['revision'] for line in output.getvalue().splitlines()],[1,2])

    def test_lost_completion_stays_unconfirmed_without_an_expiry_success(self):
        # Repeated healthy backend polls cannot establish a silent provider's
        # freshness. This is an accelerated trace, not a timed overnight soak.
        for _ in range(1800):
            view=core.observed_view(bridge({'codex:silent-turn':'Y'},'Y'))
            self.assertEqual((view['state'],view['working_count']),('working',1))
            self.assertEqual(view['confidence'],'reported')
        finished=core.observed_view(bridge({'codex:silent-turn':'G'}))
        self.assertEqual(finished['state'],'ready')
        self.assertEqual(finished['confidence'],'reported')
        self.assertEqual(finished['phrase'],core.LAST_REPORTED['ready'])

    def test_ten_thousand_poll_trace_reconnects_without_replay_or_output_history(self):
        total=10000
        progress={'polls':0,'sleeps':0,'clock':0.0}
        class Sink:
            def __init__(self):self.pending='';self.count=0;self.instance=None
            def write(sink,text):
                sink.pending+=text
                self.assertLessEqual(len(sink.pending),512)
                if '\n' not in sink.pending:return len(text)
                line,sink.pending=sink.pending.split('\n',1)
                record=json.loads(line);sink.count+=1
                phase=(sink.count-1)%4
                expected=(('working',1),('disconnected',0),('idle',0),('ready',0))[phase]
                self.assertEqual((record['state'],record['working_count']),expected)
                self.assertEqual(record['confidence'],'unknown' if phase==1 else 'reported')
                self.assertEqual(record['revision'],sink.count)
                if sink.instance is None:sink.instance=record['instance_id']
                self.assertEqual(record['instance_id'],sink.instance)
                self.assertNotIn('PRIVATE',line)
                self.assertEqual(set(record),{'version','instance_id','revision','state',
                    'working_count','providers','demo','phrase','confidence','attention_providers'})
                return len(text)
            def flush(sink):pass
        sink=Sink()
        def status():
            phase=progress['polls']%4;progress['polls']+=1
            if phase==1:raise OSError('PRIVATE_CONNECTION_FAILURE')
            if phase==0:return bridge({'codex:PRIVATE':'Y'},'Y')
            if phase==2:return bridge({})
            return bridge({'claude:PRIVATE':'G'})
        def monotonic():
            progress['clock']+=.05
            return progress['clock']
        def sleep(delay):
            self.assertGreaterEqual(delay,0)
            self.assertLessEqual(delay,.1)
            progress['sleeps']+=1
            if progress['sleeps']==total:raise KeyboardInterrupt()
        with patch.object(collector,'read_status',new=status), \
                patch.object(collector.time,'monotonic',new=monotonic), \
                patch.object(collector.time,'sleep',new=sleep), \
                patch.object(sys,'stdout',new=sink):
            self.assertEqual(collector.main(['--observe','--interval','.1']),0)
        self.assertEqual((progress['polls'],sink.count),(total,total))
        self.assertEqual(sink.pending,'')
        self.socket.assert_not_called()


class CollectorSoakTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(collector.socket,'socket',side_effect=AssertionError('Real sockets forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def record(self):
        return core.snapshot('a'*32,1,core.demo_view(0),True)

    def test_strict_soak_contract_rejects_private_fields_and_replayed_revision(self):
        record=self.record();raw=json.dumps(record).encode()+b'\n'
        self.assertEqual(soak.checked_record(raw)['revision'],1)
        for bad in (dict(record,prompt='PRIVATE'),dict(record,phrase='PRIVATE'),
                    dict(record,instance_id='b'*32),dict(record,revision=True),
                    dict(record,demo=False),dict(record,version=True),
                    dict(record,confidence='fresh'),dict(record,confidence='reported')):
            with self.assertRaises((ValueError,TypeError)):
                soak.checked_record(json.dumps(bad).encode()+b'\n','a'*32,0)
        with self.assertRaises(ValueError):soak.checked_record(raw,'a'*32,1)
        with self.assertRaises(ValueError):soak.checked_record(b'x'*1025+b'\n')

    def test_actual_one_second_demo_soak_cleans_up_and_writes_bounded_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json'
            result=soak.run_soak(1,.1,path)
            self.assertEqual(result['status'],'passed')
            self.assertTrue(result['cleanup_complete'])
            self.assertGreaterEqual(result['elapsed_seconds'],1)
            self.assertGreater(result['records'],0)
            self.assertEqual(json.loads(path.read_text()),result)
            self.assertLess(path.stat().st_size,8192)
            self.assertNotIn('instance_id',path.read_text())

    def test_bad_fixture_output_fails_without_logging_raw_payload(self):
        command=[sys.executable,'-S','-u','-c',
                 'import sys,time; print("PRIVATE_INVALID"); sys.stdout.flush(); time.sleep(5)']
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json'
            result=soak.run_soak(1,.1,path,command=command)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['failures'],['invalid-snapshot'])
            self.assertTrue(result['cleanup_complete'])
            self.assertNotIn('PRIVATE_INVALID',path.read_text())

    def test_early_fixture_exit_is_failure_not_a_short_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result=soak.run_soak(1,.1,Path(directory)/'report.json',
                                 command=[sys.executable,'-S','-c','pass'])
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['failures'],['collector-eof'])
            self.assertTrue(result['cleanup_complete'])

    def test_unwritable_report_does_not_spawn_a_collector(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(soak.subprocess,'Popen') as spawn:
            path=Path(directory)/'parent-file';path.write_text('fixture')
            with self.assertRaises(OSError):soak.run_soak(1,.1,path/'report.json')
            spawn.assert_not_called()

    def test_cancellation_cleans_up_only_the_owned_fixture_process(self):
        command=[sys.executable,'-S','-c','import time; time.sleep(10)']
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(soak.queue.Queue,'get',side_effect=KeyboardInterrupt()):
            result=soak.run_soak(1,.1,Path(directory)/'report.json',command=command)
        self.assertEqual(result['status'],'interrupted')
        self.assertTrue(result['cleanup_complete'])

    def test_stalled_fixture_is_detected_and_terminated_even_if_term_is_ignored(self):
        raw=json.dumps(self.record())
        command=[sys.executable,'-S','-u','-c',
                 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                 'print('+repr(raw)+',flush=True); time.sleep(20)']
        with tempfile.TemporaryDirectory() as directory:
            result=soak.run_soak(10,.1,Path(directory)/'report.json',command=command)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['failures'],['collector-output-timeout'])
        self.assertEqual(result['records'],1)
        self.assertTrue(result['cleanup_complete'])
        self.assertLess(result['elapsed_seconds'],9)


if __name__=='__main__':unittest.main()
