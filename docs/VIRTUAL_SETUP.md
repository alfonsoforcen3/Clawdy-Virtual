# Install Virtual Clawdy for live AI activity

Tell an AI agent that can run commands on your computer:

> Install Virtual Clawdy from https://github.com/alfonsoforcen3/Clawdy-Virtual.

The agent should use this guide for every normal Virtual Clawdy installation.
Observe mode and hooks are part of live setup. Use the sample demo when the
user explicitly asks for a demo.

## 1. Check this computer

Clone or open the public repo on the computer that runs the user's coding apps.
Use native macOS Terminal or Windows PowerShell. Run the read-only preflight:

```sh
python3 install.py --virtual --preflight --json
```

On Windows use `py -3` in place of `python3` in every command here. A verified
native Python 3.9+ executable also works if the Windows launcher is unavailable.
Check the [Mac build requirements](TRY_VIRTUAL_CLAWDY.md) or
[Windows build requirements](../desktop/windows/README.md) for the desktop app.

## 2. Install the hooks for the user's apps

Explain that the hooks send local status signals such as working and done.
Recommend configuring every supported app the user actually wants to track,
and ask them to approve the detected selection in one question. Supported local
adapters are Codex, Claude Code, Gemini CLI, and Cursor. Browser-only AI chats
cannot provide these hooks. If no supported app is detected, help the user find
or choose one and explain that live activity is pending.

The preflight's `bridge` field tells you what to do:

- `reuse_existing` means the app will share the existing bridge, including
  a bridge serving a physical Clawdy. Keep that service running.
- `start_local` means the installer can start a per-user status service at login.
  Include that in the approval. This service works without a toy or Bluetooth.
- `review_saved_profile` means there is a saved bridge or startup entry that
  needs attention. Help the user recover their existing service.
- `review_listener` means the port did not return compatible Clawdy status.
  Identify the existing service before continuing.

Once the user approves, install or refresh the hooks for the selected apps.
For example, if the user approved Codex and Claude Code:

```sh
python3 install.py --virtual --providers codex claude
```

Use `codex`, `claude`, `gemini`, or `cursor` as applicable. The installer
checks policy before applying changes. Have the user review the hooks and
approve them in their app's normal hook or workspace trust interface. Restart
the provider or open a new session if it hasn't picked up the hooks. Keep
other hooks and existing Bluetooth settings in place.

If the user declines hooks or policy blocks them, report that live tracking
is incomplete and say what is still needed. Use the demo only on request.

## 3. Build, start, and confirm the result

Build the app for [macOS](TRY_VIRTUAL_CLAWDY.md) or
[Windows](../desktop/windows/README.md) and launch it in **Observe** mode
(`--observe`). If Clawdy is already open, select Observe in its menu.
Observe connects to the running bridge at `127.0.0.1:8765`.

Run a short real turn in each approved app. Watch Virtual Clawdy report working
and done. Check `python3 manage_hooks.py status` if the lights do not change.
A running service, an installed hook, and a test fixture each fall short of
that real-app test. Report which apps were verified and which are still pending.
Keep raw logs, paths, and session IDs on the user's computer.
