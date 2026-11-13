# Set up your Clawdy or Clawdy Pro Max

Power your Clawdy by USB. When it is looking for a host, paste this into an AI
coding agent that can run commands on the computer you want Clawdy to use:

> I bought a new Clawdy. Make it work. Clone https://github.com/alfonsoforcen3/Clawdy-Virtual and follow its setup instructions.

You can keep it powered from a wall adapter. Clawdy talks to your computer over
Bluetooth Low Energy.

## Run setup yourself

Use Git and native Python 3.9 or newer. On Windows, open PowerShell on the Windows
host. On macOS, open Terminal.

```powershell
git clone https://github.com/alfonsoforcen3/Clawdy-Virtual.git
cd Clawdy-Virtual
py -3 install.py --onboard --preflight --json
py -3 install.py --onboard
```

On macOS, use `python3` in place of `py -3`. From an existing checkout, start
at preflight. The wizard confirms any dependency downloads, the selected toy
and name, the per-user background service, and which local apps to configure.
Select your exact Bluetooth device. Keep its existing name if it already has
the one you want.

## For the agent helping the buyer

1. Run preflight first. It reads local app and policy information without
   scanning Bluetooth, installing packages or changing settings. If Python is
   missing or workplace policy blocks an action, explain what the buyer or IT
   needs to approve.
2. Show which supported local apps were detected and ask which the buyer wants
   configured. The available adapters are Codex, Claude Code, Gemini CLI and
   Cursor. Ordinary AI chats in a browser are unsupported.
3. Run the guided wizard in an interactive terminal. If your tool has no
   interactive terminal, hand the displayed command to the buyer. Let the buyer
   approve Bluetooth, confirm their exact unit and preferred name, and review
   hook trust in each selected app. On a shared desk or in a room with multiple
   units, use the exact advertised name and firmware identity. Never pick the
   first nearby device. Use the shipped firmware as-is.
4. Verify Bluetooth delivery using the wizard's device and LED checks. Ask
   which LEDs are visible, confirm the Pro Max screen when applicable, and run
   one real turn in each selected app. Report which checks passed. Native
   Windows testing with a physical unit is still pending for this release.

Use `py -3 manage_hooks.py status` on Windows to inspect the installed service,
or `py -3 manage_hooks.py disable` to remove the integration. Use `python3`
on macOS. Use the wizard again to review and change the device or hook selection.
