# Local status integration

In Observe mode, Virtual Clawdy reads status from a separate local service.
The desktop app connects to TCP port 8765 on IPv4 loopback and writes one
UTF-8 line:

```json
{"action":"status"}
```

Reply on the same connection with one newline-terminated JSON object, at most
8192 bytes including its newline. The observer allows 500 ms for the entire
request. It treats these values as last reported and displays an unknown or
disconnected state when it cannot validate or reach the service.

```json
{"status":"ok","aggregate":"Y","active_sessions":{"codex:example-turn":"Y"}}
```

Session IDs use a provider prefix and an opaque identifier. Recognized prefixes
are `codex`, `claude`, `gemini` and `cursor`. Other prefixes display as Other.
Provide at most 256 sessions. Use `B` for input needed, `R` for error, `Y` for
working, `G` for ready and `O` for inactive. The aggregate follows that
priority order. With zero active sessions, send an empty object for
`active_sessions` and use `O` as the aggregate.

Use an existing status service or implement this small contract for your own
integration. Bind the service to loopback and send only status and opaque
identifiers. The local TCP protocol itself has no authentication. Demo mode
does not connect to the socket.
