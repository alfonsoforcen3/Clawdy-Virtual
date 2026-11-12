using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.Json;

namespace Clawdy.Windows.Runtime;

internal enum UpdateState { Current, Available, Ready, Unavailable }

internal sealed record UpdateReply(UpdateState State, string Message, string? Path = null);
internal sealed record PreparedUpdate(string Revision, string Path);

internal sealed class VirtualUpdateClient(Func<CancellationToken, Task<string>> resolvePython)
{
    private const string ExecutableName = "Clawdy.Windows.exe";
    private const int MaximumReplyBytes = 16 * 1024;
    private readonly string? _app = Environment.ProcessPath;
    internal static string? SourceRevision { get; } = typeof(VirtualUpdateClient).Assembly
        .GetCustomAttributes<AssemblyMetadataAttribute>().FirstOrDefault(value => value.Key == "ClawdySourceRevision")?.Value;
    private readonly string _script = Path.Combine(AppContext.BaseDirectory, "update_virtual_clawdy.py");
    private static string LocalRoot => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ClawdyPrototype");
    private static string OptInPath => Path.Combine(LocalRoot, "Settings", "automatic-updates");
    private static string OptOutPath => Path.Combine(LocalRoot, "Settings", "disable-automatic-updates");

    public bool CanUpdate => IsRevision(SourceRevision) && _app is not null && Path.IsPathFullyQualified(_app)
        && string.Equals(Path.GetFileName(_app), ExecutableName, StringComparison.OrdinalIgnoreCase) && File.Exists(_script);

    public bool AutomaticEnabled => !File.Exists(OptOutPath);

    internal static PreparedUpdate? PendingOnLaunch() => (!File.Exists(OptOutPath)) && SourceRevision is not null
        ? ReadPending(SourceRevision, LocalRoot) : null;

    internal static PreparedUpdate? ReadPending(string current, string localRoot)
    {
        if (!IsRevision(current) || !Path.IsPathFullyQualified(localRoot)) return null;
        var seen = new HashSet<string>(StringComparer.Ordinal) { current };
        PreparedUpdate? latest = null;
        for (var hops = 0; hops < 16; hops++)
        {
            var next = ReadPendingStep(current, localRoot);
            if (next is null) break;
            if (!seen.Add(next.Revision)) return null;
            latest = next;
            current = next.Revision;
        }
        return latest;
    }

    private static PreparedUpdate? ReadPendingStep(string current, string localRoot)
    {
        try
        {
            var marker = Path.Combine(localRoot, "Updates", "pending", current);
            using var input = new FileStream(marker, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete);
            Span<byte> bytes = stackalloc byte[43];
            var count = input.ReadAtLeast(bytes, bytes.Length, false);
            // A full lower-case SHA and exactly one LF or CRLF. An extra byte
            // in the buffer detects oversized markers without reading them all.
            if (!(count == 41 && bytes[40] == '\n') && !(count == 42 && bytes[40] == '\r' && bytes[41] == '\n'))
                return null;
            var revision = Encoding.ASCII.GetString(bytes[..40]);
            if (!IsRevision(revision)) return null;
            var path = StagedExecutable(localRoot, revision);
            return File.Exists(path) ? new(revision, path) : null;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { return null; }
    }

    public bool SetAutomatic(bool enabled)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(OptOutPath)!);
            if (enabled)
            {
                if (File.Exists(OptOutPath)) File.Delete(OptOutPath);
                File.WriteAllText(OptInPath, "enabled\n");
            }
            else
            {
                File.WriteAllText(OptOutPath, "disabled\n");
                if (File.Exists(OptInPath)) File.Delete(OptInPath);
            }
            return true;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { return false; }
    }

    public async Task<UpdateReply> RunAsync(bool stage, CancellationToken token)
    {
        if (!CanUpdate) return Unavailable("Rebuild from the public Clawdy-Virtual checkout to enable updates.");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token);
        deadline.CancelAfter(stage ? TimeSpan.FromMinutes(20) : TimeSpan.FromSeconds(60));
        using var process = new Process();
        var started = false;
        Task stderr = Task.CompletedTask;
        try
        {
            var python = await resolvePython(deadline.Token).ConfigureAwait(false);
            deadline.Token.ThrowIfCancellationRequested();
            process.StartInfo = new ProcessStartInfo(python)
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            foreach (var argument in new[] { "-I", "-B", "-X", "utf8", _script, stage ? "install" : "check",
                         "--current", SourceRevision!, "--app", _app! })
                process.StartInfo.ArgumentList.Add(argument);
            process.Start(); started = true; process.StandardInput.Close();
            stderr = process.StandardError.BaseStream.CopyToAsync(Stream.Null, deadline.Token);
            using var output = new MemoryStream();
            var buffer = new byte[4096];
            while (true)
            {
                var count = await process.StandardOutput.BaseStream.ReadAsync(buffer, deadline.Token).ConfigureAwait(false);
                if (count == 0) break;
                if (output.Length + count > MaximumReplyBytes) throw new FormatException("update-output-limit");
                output.Write(buffer, 0, count);
            }
            await process.WaitForExitAsync(deadline.Token).ConfigureAwait(false);
            await stderr.ConfigureAwait(false);
            if (process.ExitCode != 0) return Unavailable("Clawdy could not finish the update. Check Python and try again.");
            return Decode(output.ToArray(), stage, SourceRevision!, LocalRoot);
        }
        catch (OperationCanceledException)
        {
            return Unavailable(token.IsCancellationRequested ? "Update cancelled." : "The update timed out. Try again later.");
        }
        catch (Exception error) when (error is IOException or FormatException or JsonException or InvalidOperationException
            or System.ComponentModel.Win32Exception or UnauthorizedAccessException or ArgumentException or System.Security.SecurityException)
        {
            return Unavailable("Clawdy could not finish the update. Check Python, Git and the build tools, then retry.");
        }
        finally
        {
            deadline.Cancel();
            try { if (started && !process.HasExited) process.Kill(entireProcessTree: true); }
            catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception or AggregateException) { }
            try { if (started) await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); }
            catch (TimeoutException) { }
            try { await stderr.WaitAsync(TimeSpan.FromSeconds(1)).ConfigureAwait(false); }
            catch (Exception error) when (error is IOException or OperationCanceledException or TimeoutException or ObjectDisposedException) { }
        }
    }

    internal static UpdateReply Decode(ReadOnlyMemory<byte> bytes, bool stage, string current, string localRoot)
    {
        using var document = JsonDocument.Parse(bytes);
        var root = document.RootElement;
        var status = ReadString(root, "status");
        var revision = ReadString(root, "revision");
        if (status == "current") return new(UpdateState.Current, "Clawdy is up to date.");
        if (status == "unavailable")
        {
            var message = ReadString(root, "message");
            return Unavailable(message is { Length: > 0 and <= 240 } && !message.Any(char.IsControl)
                ? message : "Updates are unavailable. Try again later.");
        }
        if (IsRevision(revision) && revision != current)
        {
            if (!stage && status == "available") return new(UpdateState.Available, "An update is available to prepare.");
            if (stage && status == "ready")
            {
                var path = ReadString(root, "path");
                var expected = StagedExecutable(localRoot, revision!);
                if (path is not null && Path.IsPathFullyQualified(path)
                    && string.Equals(Path.GetFullPath(path), expected, StringComparison.OrdinalIgnoreCase) && File.Exists(expected))
                    return new(UpdateState.Ready, "Update prepared. Restart Clawdy when you're ready.", expected);
            }
        }
        return Unavailable("Clawdy received an invalid update result. Try again later.");
    }

    private static string? ReadString(JsonElement root, string key) => root.ValueKind == JsonValueKind.Object
        && root.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
    private static bool IsRevision(string? value) => value is { Length: 40 }
        && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static string StagedExecutable(string localRoot, string revision) => Path.Combine(localRoot, "Updates", revision, ExecutableName);
    private static UpdateReply Unavailable(string message) => new(UpdateState.Unavailable, message);
}
