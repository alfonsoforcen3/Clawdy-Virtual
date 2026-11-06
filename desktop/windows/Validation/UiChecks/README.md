# Isolated WPF card smoke checks

Run on a Windows desktop with the .NET 10 SDK:

```powershell
dotnet run --project desktop/windows/Validation/UiChecks/Clawdy.UiChecks.csproj -c Release
```

The STA fixture uses the real `CardWindow`, a WPF application dispatcher, synthetic
hover/key/button events, an in-memory bitmap render and fake action launchers.
It briefly shows only its own windows, closes them on completion and exits with
code 1 on assertion failure or a 30-second timeout. It does not create a tray,
collector, bridge, provider, registry reader or device connection. No screenshot,
chat ID or report file is written.

Passing demonstrates these isolated WPF paths on the tested Windows runner. It
does not establish physical pointer travel, foreground-focus restrictions,
Narrator speech, mixed-DPI placement, quiet-time OS detection, real provider
delivery, protocol-handler navigation, clean installation or a long-duration soak.
The pure policy checks remain runnable on macOS; this WPF fixture cannot execute
there because it requires the Windows Desktop runtime.
