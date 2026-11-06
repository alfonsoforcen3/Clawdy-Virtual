"""Private synthetic child for supervisor checks. No sockets/provider/device imports."""
import json
import os
import sys
import time

scenario = os.environ['CLAWDY_TEST_SCENARIO']
marker = os.environ['CLAWDY_TEST_MARKER']
demo = '--demo' in sys.argv
with open(marker, 'a', encoding='utf-8') as output:
    output.write(json.dumps({'pid': os.getpid(), 'demo': demo}) + '\n')

def emit(revision, instance='a' * 32, state='working'):
    print(json.dumps({'version': 1, 'instance_id': instance, 'revision': revision,
                      'state': state, 'working_count': 1 if state == 'working' else 0,
                      'providers': ['codex'] if state == 'working' else [], 'demo': demo,
                      'phrase': 'Fixture status', 'confidence': 'demo' if demo else 'reported',
                      'attention_providers': []}), flush=True)

if scenario == 'crash':
    raise SystemExit(23)
if scenario == 'hang':
    time.sleep(60)
elif scenario == 'malformed':
    print(('PRIVATE_INVALID\n' * 5), end='', flush=True)
    time.sleep(60)
elif scenario == 'oversized':
    sys.stdout.write('X' * 65537 + '\n')
    sys.stdout.flush()
    time.sleep(60)
elif scenario == 'changed-instance':
    emit(1)
    emit(2, instance='b' * 32)
    time.sleep(60)
elif scenario == 'replay':
    while True:
        emit(1, state='ready')
        time.sleep(.03)
elif scenario == 'burst':
    for revision in range(1, 10001):
        emit(revision)
    time.sleep(60)
elif scenario == 'descendant':
    import subprocess
    environment = dict(os.environ, CLAWDY_TEST_SCENARIO='healthy')
    child = subprocess.Popen([sys.executable, '-S', '-u', __file__, *sys.argv[1:]], env=environment)
    child.wait()
else:
    if scenario == 'stderr-flood':
        for _ in range(32):
            os.write(2, b'PRIVATE_DISCARDED_STDERR' * 2048)
    revision = 0
    while True:
        revision += 1
        emit(revision)
        time.sleep(.03)
