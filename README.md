# Virtual Clawdy

A tiny traffic light for local AI coding sessions. Virtual Clawdy lives in the
macOS menu bar or Windows notification area. Amber means work is in progress,
green means ready, and red flags a question or error.

**Try the sample activity first.** Demo mode runs locally without an AI account,
a model key, or a device. [Try the browser demo](https://alfonsoforcen3.github.io/clawd-mascot-3d/#experience).

| Platform | Build from source |
| --- | --- |
| macOS 13+ | [Mac setup guide](docs/TRY_VIRTUAL_CLAWDY.md) |
| Windows 11 x64 or ARM64 | [Windows setup guide](desktop/windows/README.md) |

These are source previews. Automated Windows builds and isolated card checks
complement the remaining hands-on Windows tray testing.

Live observation reads an existing compatible local status service. This
repository contains the desktop observer and demo. See
[local status integration](docs/LOCAL_STATUS.md) for the request and response
format. Regular browser AI chats do not produce that local status.

Clawdy also comes as an optional physical desk companion. [See Clawdy and Pro Max](https://alfonsoforcen3.github.io/clawd-mascot-3d/#get-clawdy).

Original Virtual Clawdy software is available under the [MIT License](LICENSE).
[Asset and branding terms](NOTICE.md).
