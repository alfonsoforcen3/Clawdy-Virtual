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
It asks for your first name or the name you want for your Clawdy. Enter a name to
personalize it, or type `/keep` to deliberately keep its current name. A blank
answer asks again. Select your exact
Bluetooth device and confirm its identifying light sequence before any rename.

For firmware that supports naming, setup saves a Bluetooth name made from your
laptop name, your chosen name and a short suffix from the toy's immutable
identity. Bluetooth limits the name to 29 UTF-8 bytes, so long names are
shortened. Setup reconnects to read the name and identity back, then checks
that the laptop saved the same connection. Your chosen Bluetooth name is
visible to nearby devices, so use a nickname if you prefer.

Firmware without rename support offers an explicit choice to keep the current
name. Setup reports the limitation if naming cannot be applied. Saved-name
readback checks a new Bluetooth connection. Confirm retention after a physical
power cycle separately before reporting that check as passed.

## For the agent helping the buyer

1. Run preflight first. It reads local app and policy information without
   scanning Bluetooth, installing packages or changing settings. If Python is
   missing or workplace policy blocks an action, explain what the buyer or IT
   needs to approve.
2. Show which supported local apps were detected and ask which the buyer wants
   configured. The available adapters are Codex, Claude Code, Gemini CLI and
   Cursor. Ordinary AI chats in a browser are unsupported.
3. Follow [the buyer agent guide](CUSTOMER_AGENT.md). Ask for the buyer's name
   or desired Clawdy name, or their explicit choice to keep the current name.
   Run the guided wizard interactively when available. An agent without a
   terminal can collect these answers in chat, show discovered candidates,
   obtain physical identification and use the documented machine-readable
   invocation. Let the buyer approve Bluetooth and review hook trust in each
   selected app. On a shared desk or in a room with multiple units, use the
   exact advertised name and firmware identity. Never pick the first nearby
   device. Use the shipped firmware as-is.
4. Verify Bluetooth delivery using the wizard's device and LED checks. Ask
   which LEDs are visible, confirm the Pro Max screen when applicable, and run
   one real turn in each selected app. Report which checks passed. Native
   Windows testing with a physical unit is still pending for this release.

Use `py -3 manage_hooks.py status` on Windows to inspect the installed service,
or `py -3 manage_hooks.py disable` to remove the integration. Use `python3`
on macOS. Use the wizard again to review and change the device or hook selection.
