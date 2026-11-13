# Local status integration

## Set up live status without a toy

Try demo mode to see sample activity. To see real activity in Observe mode,
use the following commands from your Clawdy-Virtual checkout. On Windows:

```powershell
py -3 scripts/provider_setup.py --detect
py -3 install.py --transport local --providers codex
py -3 manage_hooks.py status
```

On macOS, replace `py -3` with `python3`. Replace `codex` with the local
apps you choose from `codex`, `claude`, `gemini` and `cursor`. You can
list multiple apps after `--providers`. Review and approve the selected hooks
in each app, then launch Virtual Clawdy in Observe mode and test a real turn.
Setup prepares a private Python runtime and starts a per-user service at login.
Use `manage_hooks.py disable` with the same Python command to remove it.

If you already set up a physical Clawdy on this computer, launch the desktop app
in Observe mode to reuse that status service.

## Connect your own status service

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
