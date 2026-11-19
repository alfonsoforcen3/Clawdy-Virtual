# Physical Clawdy buyer setup

Use this flow when the buyer asks a local AI agent to install a powered Clawdy
or Clawdy Pro Max. A simple request to clone this repo and set up their toy is
enough to begin. Use native macOS Python 3.9+ or native Windows Python 3.9+.
The Windows commands below use PowerShell. Substitute `python3` for `py -3`
on macOS.

1. Run `py -3 install.py --onboard --preflight --json`. Keep the raw inventory
   local. Summarize detected supported apps and any blocked policies for the buyer.
2. Ask for their first name or the name they want for their Clawdy. Offer an explicit
   choice to keep its current name. Explain that the Bluetooth name is visible
   nearby and will include the laptop name and a short unit suffix. Ask which
   detected supported app hooks they approve, including a subset or none.
3. Explain required dependency downloads, Bluetooth access, the per-user login
   service, and each selected app's normal hook/workspace trust review. Users
   authenticate in OS dialogs. Respect workplace policies and disabled hooks.
4. With an interactive terminal, run `py -3 install.py` with no special flags.
   The wizard asks for providers, a first name or chosen name, and the exact device.
   Blank names ask again. Typing `/keep` deliberately retains the current name.
   It verifies the
   firmware and runs a light sequence. Have the buyer confirm their own toy.
   Naming-capable firmware receives the chosen name over BLE. Setup requires a
   persistent acknowledgement and a fresh BLE readback with the same immutable
   identity before installing the host connection.
5. Check the saved connection, BLE/GPIO acknowledgements and visible lights.
   Guide hook approval and a real prompt, completion and input request in every
   chosen app. Verify name retention and reconnection after a physical power
   cycle separately. Record which checks passed and which remain pending.

## Agents without an interactive terminal

Collect the same answers in chat. After approval to prepare BLE dependencies,
list candidates with `py -3 install.py --onboard --list-devices --json --yes`.
Show the buyer the candidate names and have them explicitly choose their unit.
Use `--device-address` as well when names collide.

Inspect the chosen unit with the public `scripts.device_identity.inspect_device`
helper. Its `identify_device` helper sends the brief red/amber/green sequence
and restores the previous state. Ask the buyer to confirm the visible sequence
on their exact toy. Only then use `--identified-device` in the setup command.

```powershell
py -3 install.py --onboard --json --yes --ble-name "EXACT SELECTED NAME" --nickname "CHOSEN NAME" --providers codex --identified-device
```

Use the actual approved providers, or replace `--providers codex` with
`--no-hooks`. Use `--keep-name` instead of `--nickname` when the buyer asks to
retain the current name. Pass command arguments as a list when executing
through an agent tool. Review an existing enrollment through preflight before
using `--replace-existing` with the buyer's approval. Disconnect the previous
controlling laptop before enrolling its toy on another computer.

The wizard checks rename support before sending the rename command. If the
firmware cannot save a new name, explain that limitation and ask whether the
buyer wants to continue with the existing name. For an automated run, obtain
that answer and rerun with `--keep-name`.

## Verification and recovery

Setup saves private checkpoints under `~/.local/share/trafficlights/onboarding/`.
They include the old and target names, immutable identity and verification
results. A rename acknowledgement followed by a failed reconnect can leave
either name advertising. Review the recovery message, rediscover and identify
the same toy before retrying. A failed host install can leave a successfully
renamed toy. Use its confirmed name with `--keep-name` on retry.

`saved_name_reconnect` confirms the new name and identity were read over a new
BLE connection after the firmware acknowledged persistence. `host_profile`
confirms the laptop saved that name and identity. Neither field establishes a
physical power-cycle result. Provider trust, real-provider turns, power-cycle
and host-restart checks remain pending until performed. Hardware acknowledgements
and an installed service alone cannot establish customer readiness.

Keep personal names, paths, raw device addresses, identities, hook settings and
recovery records on the buyer's computer. Share only sanitized findings.
