# Try Virtual Clawdy on Mac

Virtual Clawdy puts three traffic lights and a compact status card in your
menu bar. The demo uses sample events so you can try it without configuring
an AI app. See the [Windows guide](../desktop/windows/README.md) for Windows.

## Build the Mac preview

You need macOS 13 or newer, Apple Command Line Tools and system Python 3.
Check the tools with `xcode-select -p` and `/usr/bin/python3 --version`. If the
Apple tools are missing, run `xcode-select --install` and finish the system
dialog before building.

From Terminal, clone the repo and build into an isolated local cache. If you
already cloned it, enter that checkout and start with the build command.

```sh
git clone https://github.com/alfonsoforcen3/Clawdy-Virtual.git
cd Clawdy-Virtual
CLAWDY_BUILD_DIR="$HOME/Library/Caches/ClawdyPrototype/SourcePreview" bash desktop/macos/build.sh
```

Quit any existing Clawdy instance from its menu before starting the new one.
Launch it with sample activity:

```sh
open "$HOME/Library/Caches/ClawdyPrototype/SourcePreview/VirtualClawdy.app" --args --demo
```

Look for the traffic lights in the menu bar. Hover or click to see the card.
For live observation, set up the [local status service and app hooks](LOCAL_STATUS.md).
The [native app guide](../desktop/macos/README.md) explains the optional overlay,
attention behavior and verification commands.

To remove the preview, quit Clawdy from its menu and delete the local
`SourcePreview/VirtualClawdy.app` bundle.
