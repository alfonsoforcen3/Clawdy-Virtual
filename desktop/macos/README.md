# Virtual Clawdy for macOS

Virtual Clawdy runs in the **menu bar** by default: horizontal red/amber/green
traffic lights in the system menu bar, with reported WIP and app indicators.
No floating island starts by default. Hover over the menu-bar lights for a
compact interactive status panel; questions/errors expand it once automatically
without activating another app. Dismissal is respected until the episode ends. Only Y records contribute app indicators,
matching the physical screen. These are provider applications, not inferred AI
models. The previous compact island remains an explicit optional menu/CLI feature.
Normal operation uses two owned processes: menu host and standard-library Python
status collector. An optional disposable renderer is started only when requested.
It does not install hooks,
register startup, change a physical device or launch the existing bridge.

## Build and run

Requires macOS, Apple's Swift Command Line Tools and `/usr/bin/python3`.
Builds for the local CPU with a macOS 13 deployment target; this target is not
proof of testing on every supported OS or Intel hardware. Full Xcode, a webview,
a model API key and a Bluetooth toy are unnecessary for the demo.

```bash
bash desktop/macos/build.sh
open "$HOME/Library/Caches/ClawdyPrototype/Build/VirtualClawdy.app" --args --demo
```

Artifacts stay in a local cache rather than the cloud-backed Desktop checkout;
file-provider Finder metadata can invalidate signing there. Set
`CLAWDY_BUILD_DIR` to a different local build directory if necessary.
The local bundle is ad-hoc signed only, not notarized. Keep it private. Do not
disable Gatekeeper or change OS privacy settings to run a shared copy.

Default mode observes the existing local companion read-only. **Demo data** is
an explicit menu choice or `--demo`. The optional island can be enabled from the
menu or with `--overlay`; its motion and positioning controls apply only then.
The optional overlay is click-through and must not steal keyboard focus.

The observer source queries only status from an **already-running**
local companion on `127.0.0.1:8765`. It does not start it or reconnect a released
laptop. If it is unavailable, the lights become unlit/disconnected and reported
WIP/providers clear. Valid reported colours are preserved; the expanded panel,
tooltip and accessibility text qualify them as reported, with session liveness
unconfirmed. The compact label has no cryptic question-mark suffix. Records do not become fresh merely because the bridge answers.
Optional v1 snapshot confidence is `demo`, `reported`, or `unknown`; no fresh
or confirmed claim exists. This prototype does not establish real-provider
acceptance. Ordinary browser AI chats remain unsupported.

## Update Clawdy

From the menu bar, choose **Update Clawdy…**. Clawdy checks the public
repository's `main` branch and builds the exact revision after GitHub checks
pass. **Automatic Updates** prepares builds in the background and opens the
prepared build on the next normal launch. Choose **Restart to Apply Update** to
switch sooner. Clawdy keeps the previous bundle; run its executable with
`--skip-update-handoff` to reopen that version for recovery. If Automatic Updates
is off, point your shortcut at the prepared bundle under
`~/Library/Caches/ClawdyPrototype/Updates/<revision>/VirtualClawdy.app`.

If your existing app has no update menu, build once from a clean checkout of
public `main`. Updates require Git, the same local build tools and access to
GitHub. The locally built app is still a source preview.

## Verification

```bash
"$HOME/Library/Caches/ClawdyPrototype/Build/VirtualClawdy.app/Contents/MacOS/VirtualClawdy" --self-test
"$HOME/Library/Caches/ClawdyPrototype/Build/VirtualClawdy.app/Contents/MacOS/ClawdyRenderer" --self-test
python3 -m unittest discover -s tests -p test_virtual_clawdy.py -v
python3 desktop/macos/test_lifecycle.py
python3 desktop/macos/test_lifecycle.py --recovery-only
"$HOME/Library/Caches/ClawdyPrototype/Build/VirtualClawdy.app/Contents/MacOS/VirtualClawdy" --attention-self-test
"$HOME/Library/Caches/ClawdyPrototype/Build/VirtualClawdy.app/Contents/MacOS/VirtualClawdy" --attention-ui-test
python3 desktop/macos/test_protocol.py
"$HOME/Library/Caches/ClawdyPrototype/Build/VirtualClawdy.app/Contents/MacOS/ClawdyRenderer" --acceptance-test
```

Automated checks must use fixtures, inherited pipes and temporary state. Do not
start a hardware bridge merely to test this prototype. Native focus, accessibility, monitor changes, sleep/wake and live-provider
behavior need separate hands-on validation.

The native lifecycle test opens its own demo instance, deliberately freezes and
kills only that host's verified child processes, checks capped recovery, and
quits it. Run it separately from manual menu/visual acceptance. It needs a logged-in
graphical macOS session; it is not a headless Linux CI test.
The protocol test checks tiny live-pipe messages and an actually full stdout
pipe; EOF must still close the renderer without blocking its main queue.
The isolated collector soak runner is
`python3 scripts/soak_virtual_clawdy.py --duration 86400 --report /PRIVATE/PATH/report.json`;
it does not establish native UI stability.

Quit from the menu before rebuilding. No login helper is installed; quitting
must stop the prototype's owned child processes. Removing the generated bundle
removes the prototype without altering existing physical Clawdy integrations.

The menu-only recovery fixture pauses its own host for 18 seconds and verifies
that a healthy collector survives, then stalls its own collector to verify real
recovery. Scheduling gaps and wake grant a bounded watchdog grace while cached
status is cleared; retry callbacks are generation/deadline checked and deferred
during sleep. These fixtures do not restart ChatGPT or prove every OS sleep path.

## Hover and attention details

A short hover opens the anchored glass status panel. Move into it to use its
controls; a brief exit delay prevents it closing across the gap. Questions or
errors expand it once per episode. The indicator prioritizes errors, work,
questions, ready, then idle. A question opens its own card and stays visible
until you use its action or close it. **Show status details** in the menu gives
keyboard access and Escape. Passive
hover/automatic expansion never steals keyboard focus. Reduce Motion and Pause
remove the expansion animation. There is no cursor polling loop.

Actions use `attention_providers`, distinct from working `providers`: Codex opens
the installed Codex app, Cursor opens Cursor if installed, and Claude/Gemini CLI
activity offers Terminal. Verified local Codex attention chats offer **Open chat**, which navigates to
that conversation; multiple eligible chats have numbered actions (up to three).
Other targets retain explicit app/Terminal fallback labels.
Only an explicit click launches an app; demo mode has no launch actions. The
collector forwards provider enums and, only for verified local Codex attention,
a bounded UUID routing field to the host. That field is stripped before optional
renderer forwarding and is never put in logs/reports/persistence. Prompts, chat
titles and arbitrary URLs are never forwarded.

Question/error cards are latched until an explicit close (or focused Escape)
or a successful action click. Time passing, pointer exit, outside clicks and a
later ready/working/offline report do not acknowledge the alert. If the source
changes, the card qualifies the original request as recent while menu lights and
WIP continue showing current status. Failed actions keep the card usable.
The pending alert remains in host memory only; changing mode or quitting clears
it. Native menu/sleep handling temporarily hides the card and restores it without
stealing focus. Ordinary non-alert hover details can still collapse on exit.

The expanded card uses a locally bundled Clawdy product image and terracotta
brand accents. The illustration depicts the Clawdy mascot. It loads locally, fits the full product
silhouette, and has a graceful missing-image fallback. It does not fetch images
or claim the illustration is a physical product photograph.
