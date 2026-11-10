using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using Clawdy.Windows.Core;

namespace Clawdy.Windows.Runtime;

/// <summary>User-click-only launch. Fixed schemes/programs, never backend commands.</summary>
public static class ActionLauncher
{
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern void SwitchToThisWindow(IntPtr hWnd, [MarshalAs(UnmanagedType.Bool)] bool fAltTab);

    private const int SW_RESTORE = 9;
    private const int SW_SHOW = 5;

    public static bool HasProtocol(string scheme)
    {
        try
        {
            using var key = Registry.ClassesRoot.OpenSubKey(scheme);
            if (key is null) return false;
            // Supports both packaged UWP/MSIX apps (like ChatGPT) and classic Win32 applications
            if (key.GetValueNames().Contains("URL Protocol", StringComparer.OrdinalIgnoreCase)) return true;
            using var command = key.OpenSubKey(@"shell\open\command");
            return command?.GetValue(null) is string value && !string.IsNullOrWhiteSpace(value);
        }
        catch (Exception error) when (error is UnauthorizedAccessException or System.Security.SecurityException or IOException) { return false; }
    }

    private static bool TryBringTerminalToFront()
    {
        string[] processNames = ["WindowsTerminal", "wt", "pwsh", "powershell", "cmd"];
        foreach (var name in processNames)
        {
            try
            {
                var processes = Process.GetProcessesByName(name);
                foreach (var p in processes)
                {
                    var handle = p.MainWindowHandle;
                    if (handle != IntPtr.Zero)
                    {
                        if (IsIconic(handle))
                            ShowWindow(handle, SW_RESTORE);
                        else
                            ShowWindow(handle, SW_SHOW);

                        SetForegroundWindow(handle);
                        SwitchToThisWindow(handle, true);
                        return true;
                    }
                }
            }
            catch { }
        }
        return false;
    }

    private static void EnsureAppForeground(string processName)
    {
        try
        {
            var processes = Process.GetProcessesByName(processName);
            foreach (var p in processes)
            {
                var handle = p.MainWindowHandle;
                if (handle != IntPtr.Zero)
                {
                    if (IsIconic(handle)) ShowWindow(handle, SW_RESTORE);
                    else ShowWindow(handle, SW_SHOW);
                    SetForegroundWindow(handle);
                    SwitchToThisWindow(handle, true);
                    return;
                }
            }
        }
        catch { }
    }

    public static Task<bool> LaunchAsync(CardAction action)
    {
        // Keep OS shell work off WPF's dispatcher. At most one action is admitted by the card.
        return Task.Run(() =>
        {
            try
            {
                var terminal = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Microsoft", "WindowsApps", "wt.exe");
                terminal = File.Exists(terminal) ? terminal : Path.Combine(Environment.SystemDirectory, "cmd.exe");
                var destination = LaunchPolicy.Destination(action, HasProtocol, terminal);
                if (destination is null) return false;

                // If targeting terminal, bring existing running terminal to front instead of opening a new one
                if (destination == terminal)
                {
                    if (TryBringTerminalToFront()) return true;
                }

                using var process = Process.Start(new ProcessStartInfo(destination) { UseShellExecute = true });
                if (destination.StartsWith("codex://", StringComparison.OrdinalIgnoreCase))
                {
                    EnsureAppForeground("ChatGPT");
                }
                return true;
            }
            catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception
                or IOException or UnauthorizedAccessException or System.Security.SecurityException) { return false; }
        });
    }
}
