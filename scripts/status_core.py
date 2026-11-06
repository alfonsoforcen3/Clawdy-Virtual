"""Pure, privacy-preserving presentation semantics for the private virtual prototype.

Legacy bridge status has no per-session timestamps or producer health. Its active
states are therefore last-reported, never fresh merely because a poll succeeded.
This module neither imports nor starts a bridge, provider, serial or BLE worker.
"""

import re

PROVIDERS = ('codex', 'claude', 'gemini', 'cursor', 'other')
STATES = ('idle', 'working', 'ready', 'attention', 'error', 'disconnected', 'uncertain')
# Optional v1 extension for native consumers: legacy status supplies logical
# colour plus 'reported' confidence; this never means provider-fresh. Old Swift
# decoders ignore the extra field. Missing confidence must mean unknown/demo.
CONFIDENCES = ('demo', 'reported', 'unknown')
MAX_SESSIONS = 256
PHRASES = {
    'idle': 'Taking a tiny breather.',
    'working': 'Tiny paws. Big plans.',
    'ready': 'All reported work is done.',
    'attention': 'A little help, please.',
    'error': 'A bump in the road.',
    'disconnected': 'Waiting for the local companion.',
    'uncertain': 'Signals are unclear; status unconfirmed.',
}
LAST_REPORTED = {
    'idle': 'Last report: no active work; freshness unconfirmed.',
    'working': 'Last reported working; freshness unconfirmed.',
    'ready': 'Last reported ready; freshness unconfirmed.',
    'attention': 'Last reported needing input; freshness unconfirmed.',
    'error': 'Last reported error; freshness unconfirmed.',
}
PRIORITY = (('B', 'attention'), ('R', 'error'), ('Y', 'working'), ('G', 'ready'))


def resolve_sessions(sessions):
    """Return logical aggregate/count/provider enums, keeping raw identifiers local.

    Providers summarize working Y records only, matching the physical screen's
    working-provider mask; ready/input/error records add no working icon. No
    provider liveness or freshness is implied by either summary.
    """
    if not isinstance(sessions, dict) or len(sessions) > MAX_SESSIONS:
        raise ValueError('Invalid session registry')
    active = []
    providers = set()
    for key, value in sessions.items():
        if not isinstance(key, str) or not isinstance(value, str) or value not in ('B', 'R', 'Y', 'G', 'O'):
            raise ValueError('Invalid session record')
        if value == 'O':
            continue
        active.append(value)
        # Older bridge versions stored bare Codex IDs. Unknown namespaces remain
        # neutral instead of guessing a provider/model from arbitrary text.
        namespace = key.partition(':')[0] if ':' in key else 'other'
        if value == 'Y':
            providers.add(namespace if namespace in PROVIDERS else 'other')
    state = next((state for flag, state in PRIORITY if flag in active), 'idle')
    return state, active.count('Y'), [provider for provider in PROVIDERS if provider in providers]


def attention_providers(sessions, state):
    """Provider enums needing action, never unrelated working sessions or IDs."""
    flag = {'attention': 'B', 'error': 'R'}.get(state)
    if flag is None:
        return []
    names = {key.partition(':')[0] if ':' in key else 'other'
             for key, value in sessions.items() if value == flag}
    names = {name if name in PROVIDERS else 'other' for name in names}
    return [name for name in PROVIDERS if name in names]


def observed_view(status):
    """Keep consistent reported colours, separately marking confidence 'reported'.

    A fresh loopback reply is never evidence of provider freshness. Malformed
    replies use unknown confidence; hardware state and arbitrary text are ignored.
    """
    try:
        if not isinstance(status, dict) or status.get('status') != 'ok':
            raise ValueError('Invalid bridge status')
        sessions = status.get('active_sessions')
        # Validate before filtering. Legacy Codex process fallbacks identify a
        # long-lived app, not a turn, and cannot support an agent count.
        resolve_sessions(sessions)
        identified = {key: value for key, value in sessions.items()
                      if not (key.startswith('codex:proc_') and key[11:].isdigit())}
        ignored_fallback = len(identified) != len(sessions)
        logical, count, providers = resolve_sessions(identified)
        if status.get('aggregate') not in ('B', 'R', 'Y', 'G', 'O'):
            raise ValueError('Invalid aggregate')
        expected = {'attention':'B', 'error':'R', 'working':'Y', 'ready':'G'}
        if not ignored_fallback and logical != 'idle' and status['aggregate'] != expected[logical]:
            return {'state':'uncertain', 'working_count':count, 'providers':providers,
                    'phrase':PHRASES['uncertain'], 'confidence':'unknown'}
        if logical == 'idle':
            if not ignored_fallback and status['aggregate'] not in ('G', 'O'):
                raise ValueError('Inconsistent empty registry')
        return {'state':logical, 'working_count':count, 'providers':providers,
                'phrase':LAST_REPORTED[logical], 'confidence':'reported',
                **({'attention_providers': attention_providers(identified, logical)}
                   if logical in ('attention', 'error') else {})}
    except (TypeError, ValueError):
        return {'state':'uncertain', 'working_count':0, 'providers':[],
                'phrase':PHRASES['uncertain'], 'confidence':'unknown'}


def disconnected_view():
    return {'state':'disconnected', 'working_count':0, 'providers':[],
            'phrase':PHRASES['disconnected'], 'confidence':'unknown'}


# Seconds since collector start, fixture registry. No real provider/event source.
DEMO_TIMELINE = (
    (0, {}),
    (4, {'codex:fixture':'Y'}),
    (10, {'codex:fixture':'Y', 'claude:fixture':'Y'}),
    (17, {'codex:fixture':'Y', 'claude:fixture':'B'}),
    (23, {'gemini:fixture':'R', 'cursor:fixture':'Y'}),
    (29, {'codex:fixture':'G', 'claude:fixture':'Y'}),
    (35, {'codex:fixture':'G', 'claude:fixture':'G'}),
    (42, {}),
)
DEMO_DURATION = 46


def demo_view(elapsed):
    moment = max(0, elapsed) % DEMO_DURATION
    registry = DEMO_TIMELINE[0][1]
    for start, fixture in DEMO_TIMELINE:
        if moment < start:
            break
        registry = fixture
    state, count, providers = resolve_sessions(registry)
    return {'state':state, 'working_count':count, 'providers':providers,
            'phrase':'Demo: ' + PHRASES[state], 'confidence':'demo',
            **({'attention_providers': attention_providers(registry, state)}
               if state in ('attention', 'error') else {})}


def snapshot(instance_id, revision, view, demo):
    """Emit only the fixed host contract. Never forward a backend-supplied phrase."""
    if not isinstance(instance_id, str) or not instance_id or len(instance_id) > 64:
        raise ValueError('Invalid collector instance')
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError('Invalid revision')
    state = view['state']
    phrase = view['phrase']
    allowed = set(PHRASES.values()) | set(LAST_REPORTED.values()) | {'Demo: ' + p for p in PHRASES.values()}
    if state not in STATES or phrase not in allowed:
        raise ValueError('Invalid presentation state')
    if type(demo) is not bool or type(view['working_count']) is not int or not 0 <= view['working_count'] <= MAX_SESSIONS:
        raise ValueError('Invalid presentation count/mode')
    providers = view['providers']
    if not isinstance(providers, list) or any(p not in PROVIDERS for p in providers) or len(set(providers)) != len(providers):
        raise ValueError('Invalid provider summary')
    actions = view.get('attention_providers', [])
    if (not isinstance(actions, list) or any(p not in PROVIDERS for p in actions)
            or len(set(actions)) != len(actions)
            or (actions and state not in ('attention', 'error'))):
        raise ValueError('Invalid attention providers')
    chats = view.get('attention_chats', [])
    if (not isinstance(chats, list) or len(chats) > 3
            or (chats and (demo or state not in ('attention', 'error') or 'codex' not in actions))):
        raise ValueError('Invalid chat routes')
    seen_chats = set()
    for chat in chats:
        if (not isinstance(chat, dict) or set(chat) != {'provider', 'thread_id'}
                or chat['provider'] != 'codex' or not isinstance(chat['thread_id'], str)
                or not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', chat['thread_id'])
                or chat['thread_id'] in seen_chats):
            raise ValueError('Invalid chat route')
        seen_chats.add(chat['thread_id'])
    confidence = view.get('confidence', 'demo' if demo else 'unknown')
    if confidence not in CONFIDENCES or (confidence == 'demo') != demo:
        raise ValueError('Invalid confidence')
    return {'version':1, 'instance_id':instance_id, 'revision':revision, 'state':state,
            'working_count':view['working_count'], 'providers':list(providers), 'demo':demo,
            'phrase':phrase, 'confidence':confidence, 'attention_providers':list(actions),
            **({'attention_chats': [dict(chat) for chat in chats]} if chats else {})}
