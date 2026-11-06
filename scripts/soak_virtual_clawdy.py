#!/usr/bin/env python3
"""Elapsed-time soak of an isolated demo collector; never native UI acceptance.

Example: python3 scripts/soak_virtual_clawdy.py --duration 86400 --report /tmp/clawdy-soak.json
The explicit report is replaced atomically every minute and on exit. It contains
counts, gaps and resource summaries, never captured snapshots or stderr. Ctrl-C
and SIGTERM cancel on macOS; a forced OS kill cannot guarantee cleanup/reporting.
Duration uses a monotonic clock; any observed long pause fails the output-gap
check. This is not a certification of overnight sleep/wake or GUI behavior.
Run the CLI in its own process: Unix child resource totals are runner-wide.
"""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time

if __package__:
    from . import status_core
else:
    import status_core

MAX_LINE = 1024
FIELDS = {'version','instance_id','revision','state','working_count','providers','demo','phrase','confidence','attention_providers'}


def _pairs(pairs):
    result = {}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate field')
        result[key] = value
    return result


def checked_record(raw, previous_instance=None, previous_revision=0):
    """Strict demo allowlist; backend text can never enter the report."""
    if len(raw)>MAX_LINE or not raw.endswith(b'\n'): raise ValueError('invalid frame')
    record=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs)
    if not isinstance(record,dict) or set(record)!=FIELDS: raise ValueError('invalid fields')
    instance=record['instance_id']
    if (type(record['version']) is not int or record['version']!=1 or record['demo'] is not True
            or not isinstance(instance,str) or len(instance)!=32
            or any(c not in '0123456789abcdef' for c in instance)
            or (previous_instance is not None and instance!=previous_instance)
            or type(record['revision']) is not int or record['revision']!=previous_revision+1):
        raise ValueError('invalid identity or revision')
    expected=status_core.snapshot(instance,record['revision'],{
        key:record[key] for key in ('state','working_count','providers','phrase','confidence','attention_providers')},True)
    if record!=expected or not record['phrase'].startswith('Demo: '): raise ValueError('invalid demo')
    return record


def write_report(path, report):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode('utf-8')
    if len(raw)>8192: raise ValueError('Report exceeded fixed limit')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='clawdy-soak-',delete=False) as output:
            temporary=Path(output.name)
            output.write(raw)
        os.replace(temporary,path)
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()


def run_soak(duration, interval, report_path, *, command=None):
    if not math.isfinite(duration) or not 1<=duration<=604800: raise ValueError('Invalid duration')
    if not math.isfinite(interval) or not .1<=interval<=60: raise ValueError('Invalid interval')
    command=command or [sys.executable,'-S','-u',str(Path(__file__).with_name('virtual_clawdy.py')),
                        '--demo','--interval',str(interval)]
    started=time.monotonic();last=started;last_report=started
    report={'version':1,'scope':'isolated demo collector only','status':'running',
            'requested_seconds':duration,'interval_seconds':interval,'elapsed_seconds':0,
            'records':0,'state_counts':{},'maximum_gap_seconds':0,'failures':[],
            'collector_peak_rss_bytes':None,'collector_cpu_seconds':None,'cleanup_complete':False}
    # Fail before spawning if the requested report cannot be created.
    write_report(report_path,report)
    process=None;reader=None;stop=threading.Event();inbox=queue.Queue(maxsize=8)
    counts=Counter();instance=None;revision=0
    def fail(code):
        if len(report['failures'])<16: report['failures'].append(code)
        report['status']='failed'
    def deliver(item):
        while not stop.is_set():
            try: inbox.put(item,timeout=.1);return
            except queue.Full: pass
    def read_output():
        try:
            while not stop.is_set():
                raw=process.stdout.readline(MAX_LINE+1)
                if not raw: deliver(('eof',None));return
                if len(raw)>MAX_LINE: deliver(('oversized',None));return
                deliver(('line',raw))
        except (OSError,ValueError): deliver(('read-error',None))
    try:
        environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL,env=environment)
        reader=threading.Thread(target=read_output,name='clawdy-soak-reader',daemon=True);reader.start()
        while time.monotonic()-started<duration:
            now=time.monotonic()
            try: kind,raw=inbox.get(timeout=min(.25,max(.001,duration-(now-started))))
            except queue.Empty:
                if time.monotonic()-last>max(3,interval*3): fail('collector-output-timeout');break
                continue
            if kind!='line': fail('collector-'+kind);break
            now=time.monotonic()
            try: record=checked_record(raw,instance,revision)
            except (ValueError,TypeError,KeyError,UnicodeError,RecursionError): fail('invalid-snapshot');break
            gap=now-last
            report['maximum_gap_seconds']=round(max(report['maximum_gap_seconds'],gap),4)
            if gap>max(3,interval*3): fail('collector-output-gap');break
            last=now;instance=record['instance_id'];revision=record['revision']
            counts[record['state']]+=1;report['records']+=1
            report['elapsed_seconds']=round(now-started,4);report['state_counts']=dict(counts)
            if now-last_report>=60: write_report(report_path,report);last_report=now
        if report['status']=='running':
            if report['records']: report['status']='passed'
            else: fail('no-snapshots')
    except KeyboardInterrupt: report['status']='interrupted'
    except OSError: fail('process-or-report-io-error')
    finally:
        stop.set()
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=2)
            if reader is not None: reader.join(timeout=1)
            if reader is None or not reader.is_alive(): process.stdout.close()
            report['cleanup_complete']=process.poll() is not None and (reader is None or not reader.is_alive())
            try:
                import resource
                usage=resource.getrusage(resource.RUSAGE_CHILDREN)
                # macOS reports bytes; other Unix implementations report KiB.
                report['collector_peak_rss_bytes']=int(usage.ru_maxrss*(1 if sys.platform=='darwin' else 1024))
                report['collector_cpu_seconds']=round(usage.ru_utime+usage.ru_stime,4)
            except ImportError: pass
        else:
            report['cleanup_complete']=True
        if not report['cleanup_complete']: fail('cleanup-incomplete')
        report['elapsed_seconds']=round(time.monotonic()-started,4)
        write_report(report_path,report)
    return report


def positive_arg(value):
    try: number=float(value)
    except ValueError: raise argparse.ArgumentTypeError('Expected finite seconds')
    if not math.isfinite(number): raise argparse.ArgumentTypeError('Expected finite seconds')
    return number


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration',type=positive_arg,default=60,help='Actual elapsed seconds, 1..604800; 86400 for 24h')
    parser.add_argument('--interval',type=positive_arg,default=1,help='Collector interval, 0.1..60 seconds')
    parser.add_argument('--report',type=Path,required=True,help='Explicit private summary path; replaced each minute/on exit')
    args=parser.parse_args(argv)
    if not 1<=args.duration<=604800 or not .1<=args.interval<=60: parser.error('Duration/interval outside allowed bounds')
    old=signal.getsignal(signal.SIGTERM)
    def cancel(_signum,_frame): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,cancel)
    try:
        result=run_soak(args.duration,args.interval,args.report)
        print(json.dumps(result,sort_keys=True))
        return 0 if result['status']=='passed' else 130 if result['status']=='interrupted' else 1
    except OSError:
        print('Soak report could not be written.',file=sys.stderr);return 1
    finally: signal.signal(signal.SIGTERM,old)


if __name__=='__main__': raise SystemExit(main())
