import contextlib
import ctypes
import importlib.util
import io
import json
import os
import queue
import threading
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts import migrate_hook_runtime as migration

spec = importlib.util.spec_from_file_location('traffic_observer_test', Path(__file__).resolve().parents[1]/'scripts/traffic.py')
traffic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(traffic)


class HookRuntimeTests(unittest.TestCase):
    def test_codex_session_start_sets_amber(self):
        args=SimpleNamespace(event='G',provider='codex',session_id=None)
        payload={'hook_event_name':'SessionStart','session_id':'new-session'}
        with patch.object(traffic,'read_payload',return_value=payload):
            self.assertEqual(traffic.parse_input(args),('codex:new-session','Y'))
    def test_missing_or_invalid_chat_identity_never_creates_process_scoped_state(self):
        args=SimpleNamespace(event='Y',provider='codex',session_id=None)
        invalid=(None,'','   ',False,7,[],{},['chat'],{'id':'chat'},'chat\ncontrol','chat\x00control')
        for identity in invalid:
            payload={'hook_event_name':'PreToolUse','session_id':identity}
            with self.subTest(identity_type=type(identity).__name__), \
                    patch.object(traffic,'read_payload',return_value=payload), \
                    patch.object(traffic.os,'getppid',side_effect=AssertionError('PID is not a chat identity')):
                self.assertEqual(traffic.parse_input(args),(None,None))
        with patch.object(traffic,'read_payload',return_value={}):
            self.assertEqual(traffic.parse_input(args),(None,None))

    def test_valid_identity_aliases_and_explicit_custom_ids_are_preserved(self):
        for provider in ('codex','claude','gemini','cursor','custom'):
            args=SimpleNamespace(event='Y',provider=provider,session_id=None)
            for key in ('conversationId','sessionId','conversation_id','session_id'):
                with self.subTest(provider=provider,key=key), \
                        patch.object(traffic,'read_payload',return_value={key:'stable-雪-chat'}):
                    self.assertEqual(traffic.parse_input(args),(provider+':stable-雪-chat','Y'))
            args.session_id='explicit-chat'
            with patch.object(traffic,'read_payload',return_value={'session_id':'payload-chat'}):
                self.assertEqual(traffic.parse_input(args),(provider+':explicit-chat','Y'))
            args.session_id=''
            with patch.object(traffic,'read_payload',return_value={'session_id':'payload-chat'}):
                self.assertEqual(traffic.parse_input(args),(None,None))

    def test_missing_identity_skips_delivery_and_keeps_required_provider_outputs(self):
        for provider,silent,cursor_prompt,expected in (
                ('codex',False,False,'{}\n'),('gemini',False,False,'{}\n'),
                ('claude',True,False,''),('cursor',False,True,'{"continue": true}\n')):
            args=SimpleNamespace(event='Y',provider=provider,session_id=None,
                                 silent=silent,cursor_prompt=cursor_prompt)
            with self.subTest(provider=provider),patch.object(traffic,'options',return_value=args), \
                    patch.object(traffic,'read_payload',return_value={}), \
                    patch.object(traffic,'send_via_tcp',side_effect=AssertionError('No unidentified delivery')), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as ended:traffic.main()
                self.assertEqual(ended.exception.code,0)
            self.assertEqual(output.getvalue(),expected)

    def test_partial_start_then_real_stop_cannot_leave_a_phantom_working_record(self):
        delivered=[]
        args=SimpleNamespace(event='',provider='codex',session_id=None,silent=False,cursor_prompt=False)
        for payload in ({'hook_event_name':'PreToolUse'},
                        {'hook_event_name':'Stop','conversation_id':'real-chat'}):
            with patch.object(traffic,'options',return_value=args), \
                    patch.object(traffic,'read_payload',return_value=payload), \
                    patch.object(traffic,'send_via_tcp',side_effect=lambda sid,state,*a,**k:delivered.append((sid,state))), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as ended:traffic.main()
                self.assertEqual(ended.exception.code,0)
        self.assertEqual(delivered,[('codex:real-chat','G')])

    def test_explicit_global_maintenance_remains_available_without_chat_identity(self):
        for provider in ('codex','claude','gemini','cursor','custom'):
            for event in ('RESET','CLEAR'):
                args=SimpleNamespace(event=event,provider=provider,session_id=None)
                with self.subTest(provider=provider,event=event), \
                        patch.object(traffic,'read_payload',return_value={}):
                    self.assertEqual(traffic.parse_input(args),(provider+':manual-control','RESET'))
                args.session_id='explicit-chat'
                with patch.object(traffic,'read_payload',return_value={}):
                    self.assertEqual(traffic.parse_input(args),(provider+':explicit-chat','RESET'))

    def test_bad_payload_is_empty_and_size_is_bounded(self):
        for value in ('[]', 'null', '1', 'oops', '{"error":true}'*10):
            self.assertEqual(traffic.read_payload(io.StringIO(value), max_bytes=20), {})
        self.assertEqual(traffic.read_payload(io.StringIO('{"session_id":"test"}')), {'session_id':'test'})

    def test_open_stdin_pipe_cannot_hold_up_hook(self):
        reader, writer = os.pipe()
        try:
            with os.fdopen(reader, 'r') as stream:
                started = time.monotonic()
                self.assertEqual(traffic.read_payload(stream, timeout=.05), {})
                self.assertLess(time.monotonic()-started, .5)
        finally:
            os.close(writer)

    def test_partial_pipe_input_times_out_without_a_background_reader(self):
        reader, writer = os.pipe()
        try:
            os.write(writer,b'{"session_id":')
            with os.fdopen(reader,'r') as stream, \
                    patch.object(threading.Thread,'start',side_effect=AssertionError('No background stdin reader')):
                self.assertEqual(traffic.read_payload(stream,timeout=.01),{})
            # Stream close above occurs while the writer is still open. On
            # Windows this used to deadlock against a daemon CRT os.read lock.
        finally:
            os.close(writer)

    def test_pipe_eof_and_payload_size_limit(self):
        reader, writer = os.pipe()
        os.close(writer)
        with os.fdopen(reader,'r') as stream:
            self.assertEqual(traffic.read_payload(stream),{})
        reader, writer = os.pipe()
        try:
            os.write(writer,b'{"session_id":"too long"}')
            with os.fdopen(reader,'r') as stream:
                self.assertEqual(traffic.read_payload(stream,max_bytes=8),{})
        finally:
            os.close(writer)

    def test_complete_pipe_json_with_trailing_cr_does_not_wait_for_more_text(self):
        reader, writer = os.pipe()
        try:
            # A CRT text-mode read can perform CRLF lookahead after this final
            # CR. The Windows implementation deliberately uses raw ReadFile.
            os.write(writer,b'{"session_id":"raw"}\r')
            with os.fdopen(reader,'r') as stream:
                self.assertEqual(traffic.read_payload(stream),{'session_id':'raw'})
        finally:
            os.close(writer)

    def test_windows_api_reads_only_available_bytes_and_bypasses_crt(self):
        events=[]
        data=bytearray(b'{"session_id":"windows"}\r')
        state={'first':True}
        class Function:
            def __init__(self,call): self.call=call
            def __call__(self,*args): return self.call(*args)
        def peek(handle,_buffer,_size,_received,available,_left):
            self.assertEqual(handle.value,12345)
            if state['first']:
                state['first']=False
                available._obj.value=0
                events.append(('peek',0))
            else:
                available._obj.value=len(data)
                events.append(('peek',len(data)))
            return 1
        def read(_handle,buffer,size,received,_overlapped):
            self.assertLessEqual(size,len(data))
            events.append(('read',size))
            chunk=bytes(data[:size]);del data[:size]
            ctypes.memmove(buffer,chunk,len(chunk))
            received._obj.value=len(chunk)
            return 1
        kernel=SimpleNamespace(PeekNamedPipe=Function(peek),ReadFile=Function(read))
        reader, writer=os.pipe()
        try:
            with os.fdopen(reader,'r') as stream, \
                    patch.object(traffic.sys,'platform','win32'), \
                    patch.dict(sys.modules,{'msvcrt':SimpleNamespace(get_osfhandle=lambda fd:12345)}), \
                    patch.object(ctypes,'WinDLL',return_value=kernel,create=True), \
                    patch.object(traffic.time,'sleep'), \
                    patch.object(traffic.os,'read',side_effect=AssertionError('CRT read must not be used')):
                self.assertEqual(traffic.read_payload(stream),{'session_id':'windows'})
        finally:
            os.close(writer)
        self.assertEqual(events[0],('peek',0))
        self.assertEqual([e[0] for e in events],['peek','peek','read'])

    def test_windows_broken_pipe_is_eof_and_bad_handles_fail_open(self):
        class Function:
            def __call__(self,*args): return 0
        kernel=SimpleNamespace(PeekNamedPipe=Function(),ReadFile=Function())
        for error in (109,232,6):
            with self.subTest(error=error):
                reader, writer=os.pipe()
                try:
                    with os.fdopen(reader,'r') as stream, \
                            patch.object(traffic.sys,'platform','win32'), \
                            patch.dict(sys.modules,{'msvcrt':SimpleNamespace(get_osfhandle=lambda fd:12345)}), \
                            patch.object(ctypes,'WinDLL',return_value=kernel,create=True), \
                            patch.object(ctypes,'get_last_error',return_value=error,create=True):
                        self.assertEqual(traffic.read_payload(stream),{})
                finally:
                    os.close(writer)

    def test_complete_json_does_not_wait_for_eof(self):
        reader, writer = os.pipe()
        try:
            os.write(writer, b'{"session_id":"complete"}')
            with os.fdopen(reader, 'r') as stream:
                self.assertEqual(traffic.read_payload(stream), {'session_id':'complete'})
        finally:
            os.close(writer)

    def test_missing_bridge_is_fail_open_and_never_uses_serial(self):
        with patch.object(traffic, 'options', return_value=type('Args', (), {'silent':False, 'cursor_prompt':False})()), \
             patch.object(traffic, 'parse_input', return_value=('codex:test', 'G')), \
             patch.object(traffic, 'send_via_tcp', side_effect=OSError('helper down')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as ended:
                traffic.main()
            self.assertEqual(ended.exception.code, 0)
        self.assertEqual(json.loads(output.getvalue()), {})
        self.assertNotIn('serial', traffic.__dict__)

    def test_stop_output_never_requests_agent_continuation(self):
        with patch.object(traffic, 'options', return_value=type('Args', (), {'silent':False, 'cursor_prompt':False})()), \
             patch.object(traffic, 'parse_input', return_value=('codex:test','G')), \
             patch.object(traffic, 'send_via_tcp', return_value=(True,None)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as ended:
                traffic.main()
            self.assertEqual(ended.exception.code, 0)
        self.assertEqual(output.getvalue(),'{}\n')

    def test_closed_provider_stdout_still_exits_zero(self):
        class ClosedOutput:
            def write(self, _text): raise BrokenPipeError('provider closed output')
            def flush(self): raise BrokenPipeError('provider closed output')
        with patch.object(traffic, 'options', return_value=type('Args', (), {'silent':False,'cursor_prompt':False})()), \
             patch.object(traffic, 'parse_input', return_value=('codex:test','G')), \
             patch.object(traffic, 'send_via_tcp', return_value=(False,None)), \
             patch.object(sys,'stdout',ClosedOutput()):
            with self.assertRaises(SystemExit) as ended:
                traffic.main()
            self.assertEqual(ended.exception.code,0)

    def test_tcp_failure_closes_socket(self):
        with patch.object(traffic.socket, 'socket') as socket_class:
            socket_class.return_value.__enter__.return_value.connect.side_effect=OSError('down')
            self.assertEqual(traffic.send_via_tcp('test', 'Y'), (False,None))
            socket_class.return_value.__exit__.assert_called_once()

    def test_standalone_process_exits_with_input_pipe_left_open(self):
        # Interpreter/import startup has its own budget. The handler deadline
        # begins only after READY and a one-byte barrier, with stdin still open.
        # A private temp copy and stubbed delivery avoid the live integration.
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder)/'traffic.py'
            script.write_bytes(Path(traffic.__file__).read_bytes())
            code = ("import os,runpy,sys;sys.argv=['traffic.py','G'];"
                    "ns=runpy.run_path(" + repr(str(script)) + ");"
                    "ns['main'].__globals__['send_via_tcp']=lambda *a:(False,None);"
                    "print('READY',flush=True);"
                    "assert os.read(0,1)==b'!';"
                    "ns['main']()")
            process = subprocess.Popen([sys.executable,'-I','-S','-c',code],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            ready = queue.Queue(maxsize=1)
            reader = threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True)
            reader.start()
            try:
                try:
                    message = ready.get(timeout=10)
                except queue.Empty:
                    self.fail('Child did not complete interpreter/import startup within 10 seconds')
                self.assertEqual(message.rstrip(b'\r\n'),b'READY')
                reader.join(timeout=1)
                self.assertFalse(reader.is_alive())
                process.stdin.write(b'!')
                process.stdin.flush()
                # Do not close stdin: this specifically tests bounded reads and
                # stdin close/shutdown with the provider pipe left open.
                process.wait(timeout=2)
                self.assertFalse(process.stdin.closed)
                self.assertEqual(process.returncode,0)
                self.assertEqual(process.stdout.read().splitlines(),[b'{}'])
                self.assertEqual(process.stderr.read(),b'')
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                process.stdin.close()
                reader.join(timeout=5)
                process.stdout.close()
                process.stderr.close()
                self.assertFalse(reader.is_alive(), 'Startup reader must terminate during cleanup')

    def test_tcp_payload_stays_inside_bridge_receive_budget(self):
        with patch.object(traffic.socket,'socket') as socket_class:
            self.assertEqual(traffic.send_via_tcp('🐱'*1000,'Y'),(True,None))
            raw=socket_class.return_value.__enter__.return_value.sendall.call_args.args[0]
            self.assertLessEqual(len(raw),1024)
            self.assertEqual(json.loads(raw)['state'],'Y')

    def test_migration_other_providers_preserves_disabled_fields(self):
        cases={
            'claude':{'hooks':{'Stop':[{'hooks':[{'statusMessage':'Traffic light: Claude Stop',
                'command':'python traffic.py G --provider claude --silent','enabled':False}]}]},'disableAllHooks':True},
            'gemini':{'hooks':{'AfterAgent':[{'hooks':[{'name':'trafficlights-gemini-AfterAgent',
                'command':'python traffic.py G --provider gemini','enabled':False}]}]},'hooksConfig':{'enabled':False}},
            'cursor':{'hooks':{'stop':[{'command':'python traffic.py G --provider cursor --trafficlights-hook',
                'enabled':False}]},'version':1}}
        for provider,data in cases.items():
            with self.subTest(provider=provider):
                updated,count=migration.rewrite(data,provider,Path('/runtime/python'),Path('/runtime/traffic.py'))
                self.assertEqual(count,1)
                event=next(iter(updated['hooks']))
                hook=updated['hooks'][event][0] if provider=='cursor' else updated['hooks'][event][0]['hooks'][0]
                self.assertFalse(hook['enabled'])
                self.assertIn(str(Path('/runtime/traffic.py')),hook['command'])
                self.assertEqual({k:v for k,v in updated.items() if k!='hooks'},
                                 {k:v for k,v in data.items() if k!='hooks'})

    def test_migration_preserves_policy_and_unrelated_commands_without_service(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);runtime=home/'runtime';runtime.mkdir()
            python=migration.venv_python(runtime);python.parent.mkdir(parents=True);python.touch()
            source=home/'source.py';source.write_text('print("{}")\n')
            path=home/'.codex/hooks.json';path.parent.mkdir()
            data={'enabled':False,'hooks':{'Stop':[{'enabled':False,'hooks':[
                {'statusMessage':'Traffic light: Stop','command':'"/old Desktop/python" "/old Desktop/traffic.py" G','timeout':3,'enabled':False},
                {'command':'unrelated command','enabled':True}]}]}}
            original=json.dumps(data);path.write_text(original)
            preview=migration.migrate(home,runtime,source)
            self.assertEqual(preview['changes'],{'codex':1})
            self.assertEqual(path.read_text(),original)
            self.assertFalse((runtime/'traffic.py').exists())
            result=migration.migrate(home,runtime,source,apply=True)
            updated=json.loads(path.read_text());hook=updated['hooks']['Stop'][0]['hooks'][0]
            self.assertIn(str(runtime/'traffic.py'),hook['command'])
            self.assertFalse(updated['enabled']);self.assertFalse(hook['enabled'])
            self.assertEqual(updated['hooks']['Stop'][0]['hooks'][1],data['hooks']['Stop'][0]['hooks'][1])
            self.assertEqual((Path(result['backup'])/'codex.json').read_text(),original)
            self.assertEqual(migration.migrate(home,runtime,source)['changes'],{})
            self.assertFalse(result['service_started']);self.assertFalse(result['hooks_enabled'])

    def test_migration_ignores_unowned_traffic_command_and_refuses_compound_owned(self):
        unrelated={'hooks':{'Stop':[{'hooks':[{'command':'python traffic.py G'}]}]}}
        self.assertEqual(migration.rewrite(unrelated,'codex',Path('python'),Path('runtime/traffic.py'))[1],0)
        compound={'hooks':{'Stop':[{'hooks':[{'statusMessage':'Traffic light: Stop','command':'python traffic.py G && other'}]}]}}
        with self.assertRaises(ValueError):migration.rewrite(compound,'codex',Path('python'),Path('runtime/traffic.py'))
