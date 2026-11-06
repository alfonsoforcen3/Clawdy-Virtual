using System.Diagnostics;
using System.IO;
using Microsoft.Win32;
using Clawdy.Windows.Core;

namespace Clawdy.Windows.Runtime;

/// <summary>User-click-only launch. Fixed schemes/programs, never backend commands.</summary>
public static class ActionLauncher
{
    public static bool HasProtocol(string scheme)
    {
        try
        {
            using var key = Registry.ClassesRoot.OpenSubKey(scheme);
            using var command = key?.OpenSubKey(@"shell\open\command");
            return key?.GetValueNames().Contains("URL Protocol", StringComparer.OrdinalIgnoreCase) == true
                && command?.GetValue(null) is string value && !string.IsNullOrWhiteSpace(value);
        }
        catch (Exception error) when (error is UnauthorizedAccessException or System.Security.SecurityException or IOException) { return false; }
    }
    public static Task<bool> LaunchAsync(CardAction action)
    {
        // Keep OS shell work off WPF's dispatcher. At most one action is admitted by the card.
        return Task.Run(() =>
        {
            try
            {
                // Opens a terminal, never a command, resume action or guessed chat.
                var terminal = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Microsoft", "WindowsApps", "wt.exe");
                terminal = File.Exists(terminal) ? terminal : Path.Combine(Environment.SystemDirectory, "cmd.exe");
                var destination = LaunchPolicy.Destination(action, HasProtocol, terminal);
                if (destination is null) return false;
                using var process = Process.Start(new ProcessStartInfo(destination) { UseShellExecute = true });
                return true;
            }
            catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception
                or IOException or UnauthorizedAccessException or System.Security.SecurityException) { return false; }
        });
    }
}
