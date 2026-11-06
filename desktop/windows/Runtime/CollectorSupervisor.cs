using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using Clawdy.Windows.Core;

namespace Clawdy.Windows.Runtime;

public sealed record ReceivedStatus(StatusSnapshot Snapshot, long ReceivedTicks, int Generation, long Revision = 0);

// Only linked portable process tests change these values; the app uses defaults.
internal sealed record SupervisorTiming(TimeSpan SnapshotDeadline, double RetryDelayScale = 1)
{
    public static SupervisorTiming Default { get; } = new(TimeSpan.FromSeconds(16));
}

/// <summary>One owned collector, one latest snapshot slot, capped automatic recovery.</summary>
public sealed class CollectorSupervisor : IAsyncDisposable
{
    private readonly string _python;
    private readonly string _script;
    private readonly SupervisorTiming _timing;
    private readonly CancellationTokenSource _lifetime = new();
    private readonly SemaphoreSlim _retry = new(0, 1);
    private readonly object _gate = new();
    private CancellationTokenSource? _childCancellation;
    private Task? _worker;
    private Task? _shutdown;
    private string? _resolvedPython;
    private ReceivedStatus? _latest;
    private long _lastValidTicks;
    private int _requestedGeneration;
    private volatile bool _demo;
    private volatile bool _paused;
    private volatile bool _disposed;
    public bool RecoveryPaused => _paused;
    public bool Demo => _demo;
    public int Generation => Volatile.Read(ref _requestedGeneration);
    public long LastValidTicks => Interlocked.Read(ref _lastValidTicks);
    public CollectorSupervisor(string python, string script, bool demo) : this(python, script, demo, SupervisorTiming.Default) { }
    internal CollectorSupervisor(string python, string script, bool demo, SupervisorTiming timing)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(python); ArgumentException.ThrowIfNullOrWhiteSpace(script);
        if (timing.SnapshotDeadline <= TimeSpan.Zero || timing.SnapshotDeadline > TimeSpan.FromMinutes(1)
            || !double.IsFinite(timing.RetryDelayScale) || timing.RetryDelayScale is <= 0 or > 1)
            throw new ArgumentOutOfRangeException(nameof(timing));
        _python = python; _script = script; _demo = demo; _timing = timing;
    }
    public void Start()
    {
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            _worker ??= Task.Run(RunAsync);
        }
    }
    public ReceivedStatus? TakeLatest() => Interlocked.Exchange(ref _latest, null);
    private void Publish(StatusSnapshot value, int generation, long revision = 0) => Interlocked.Exchange(ref _latest, new(value, Stopwatch.GetTimestamp(), generation, revision));
    public void Retry(bool? demo = null)
    {
        lock (_gate)
        {
            if (_disposed) return;
            if (demo.HasValue) _demo = demo.Value;
            _resolvedPython = null;
            _requestedGeneration++;
            _childCancellation?.Cancel();
            try { _retry.Release(); } catch (SemaphoreFullException) { }
        }
    }
    public void RestartStalledChild()
    {
        lock (_gate) { if (!_disposed) _childCancellation?.Cancel(); }
    }

    private async Task RunAsync()
    {
        var budget = new RestartBudget();
        var handledGeneration = -1;
        while (!_lifetime.IsCancellationRequested)
        {
            int generation;
            lock (_gate) generation = _requestedGeneration;
            if (generation != handledGeneration)
            {
                budget.Reset(); _paused = false; handledGeneration = generation;
                while (_retry.Wait(0)) { }
            }
            if (_paused)
            {
                try { await _retry.WaitAsync(_lifetime.Token).ConfigureAwait(false); } catch (OperationCanceledException) { break; }
                continue;
            }
            var demo = _demo;
            Publish(StatusSnapshot.Offline() with { Demo = demo }, handledGeneration);
            Interlocked.Exchange(ref _lastValidTicks, Stopwatch.GetTimestamp());
            var began = Stopwatch.GetTimestamp();
            using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token);
            lock (_gate)
            {
                _childCancellation = cancellation;
                // Retry/mode change may race the gap before this child existed.
                if (_requestedGeneration != handledGeneration || _disposed) cancellation.Cancel();
            }
            try { await ReadChildAsync(demo, handledGeneration, cancellation.Token).ConfigureAwait(false); }
            catch (Exception error) when (error is IOException or JsonException or FormatException or InvalidOperationException
                or System.ComponentModel.Win32Exception or OperationCanceledException or KeyNotFoundException or DecoderFallbackException)
            { /* Sanitized state only: never persist stderr, raw IDs or paths. */ }
            finally { lock (_gate) _childCancellation = null; }
            if (_lifetime.IsCancellationRequested) break;
            lock (_gate) generation = _requestedGeneration;
            if (generation != handledGeneration) continue;
            if (Stopwatch.GetElapsedTime(began).TotalSeconds >= 600) budget.Reset();
            var delay = budget.RecordFailure(Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency);
            if (delay is null)
            {
                _paused = true;
                Publish(StatusSnapshot.Offline("Status collector recovery paused. Use Retry in the tray menu.") with { Demo = demo }, handledGeneration);
                continue;
            }
            Publish(StatusSnapshot.Offline("Status collector is reconnecting") with { Demo = demo }, handledGeneration);
            using var backoff = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token);
            var explicitRetry = _retry.WaitAsync(backoff.Token);
            try
            {
                await Task.WhenAny(Task.Delay(TimeSpan.FromSeconds(delay.Value * _timing.RetryDelayScale), backoff.Token), explicitRetry).ConfigureAwait(false);
            }
            finally
            {
                backoff.Cancel();
                try { await explicitRetry.ConfigureAwait(false); } catch (OperationCanceledException) { }
            }
        }
    }

    private async Task ReadChildAsync(bool demo, int generation, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        var python = await ResolvePythonAsync(token).ConfigureAwait(false);
        token.ThrowIfCancellationRequested();
        using var process = new Process();
        process.StartInfo = new ProcessStartInfo(python)
        {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        foreach (var argument in new[] { "-S", "-u", _script, demo ? "--demo" : "--observe" })
            process.StartInfo.ArgumentList.Add(argument);
        process.StartInfo.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        using var reads = CancellationTokenSource.CreateLinkedTokenSource(token);
        var started = false;
        Task errors = Task.CompletedTask, watchdog = Task.CompletedTask;
        try
        {
            process.Start(); started = true;
            process.StandardInput.Close();
            // Drain/discard stderr without retaining text or waiting for stdout.
            errors = DiscardAsync(process.StandardError.BaseStream, reads.Token);
            Interlocked.Exchange(ref _lastValidTicks, Stopwatch.GetTimestamp());
            watchdog = WatchdogAsync(reads);
            var framer = new NdjsonFramer(); var buffer = new byte[4096];
            string? instance = null; long revision = 0; int badFrames = 0;
            while (true)
            {
                var amount = await process.StandardOutput.BaseStream.ReadAsync(buffer, reads.Token).ConfigureAwait(false);
                if (amount == 0) break;
                foreach (var frame in framer.Append(buffer.AsMemory(0, amount)))
                {
                    WireSnapshot value;
                    try { value = WireProtocol.Decode(frame, demo); }
                    catch (Exception error) when (error is JsonException or FormatException or InvalidOperationException or KeyNotFoundException)
                    { if (++badFrames >= 5) throw new FormatException("invalid-collector"); else continue; }
                    if (instance is not null && value.InstanceId != instance) throw new FormatException("changed-instance");
                    if (value.Revision <= revision) continue;
                    instance = value.InstanceId; revision = value.Revision; badFrames = 0;
                    Interlocked.Exchange(ref _lastValidTicks, Stopwatch.GetTimestamp());
                    Publish(value.Snapshot, generation, revision);
                }
            }
        }
        finally
        {
            reads.Cancel();
            // Kill only the owned process tree; never find/kill a bridge or app by name/PID.
            try { if (started && !process.HasExited) process.Kill(entireProcessTree: true); }
            catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception or AggregateException) { }
            try { if (started) await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); }
            catch (TimeoutException) { }
            try { await Task.WhenAll(errors, watchdog).WaitAsync(TimeSpan.FromSeconds(1)).ConfigureAwait(false); }
            catch (Exception error) when (error is OperationCanceledException or IOException or TimeoutException) { }
        }
    }
    private async Task<string> ResolvePythonAsync(CancellationToken token)
    {
        if (!string.Equals(Path.GetFileNameWithoutExtension(_python), "py", StringComparison.OrdinalIgnoreCase)) return _python;
        lock (_gate) { if (_resolvedPython is not null) return _resolvedPython; }
        // The Windows launcher may own a Python child. Resolve the actual leaf
        // executable first rather than treating the launcher's lifetime as Python's.
        using var resolution = CancellationTokenSource.CreateLinkedTokenSource(token);
        resolution.CancelAfter(TimeSpan.FromSeconds(3));
        using var process = new Process { StartInfo = new ProcessStartInfo(_python)
        {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        } };
        foreach (var argument in new[] { "-3", "-I", "-S", "-X", "utf8", "-c", "import sys; print(sys.executable)" })
            process.StartInfo.ArgumentList.Add(argument);
        var started = false; Task errors = Task.CompletedTask;
        try
        {
            process.Start(); started = true; process.StandardInput.Close();
            errors = DiscardAsync(process.StandardError.BaseStream, resolution.Token);
            using var output = new MemoryStream(); var bytes = new byte[512];
            while (true)
            {
                var amount = await process.StandardOutput.BaseStream.ReadAsync(bytes, resolution.Token).ConfigureAwait(false);
                if (amount == 0) break;
                if (output.Length + amount > 4096) throw new FormatException("interpreter-output-limit");
                output.Write(bytes, 0, amount);
            }
            await process.WaitForExitAsync(resolution.Token).ConfigureAwait(false);
            var executable = new UTF8Encoding(false, true).GetString(output.ToArray()).TrimEnd('\r', '\n');
            if (process.ExitCode != 0 || executable.Contains('\n') || executable.Contains('\r')
                || !Path.IsPathFullyQualified(executable) || !File.Exists(executable))
                throw new FormatException("interpreter-unavailable");
            token.ThrowIfCancellationRequested();
            lock (_gate) _resolvedPython = executable;
            return executable;
        }
        finally
        {
            resolution.Cancel();
            try { if (started && !process.HasExited) process.Kill(entireProcessTree: true); }
            catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception or AggregateException) { }
            try { if (started) await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); }
            catch (TimeoutException) { }
            try { await errors.WaitAsync(TimeSpan.FromSeconds(1)).ConfigureAwait(false); }
            catch (Exception error) when (error is OperationCanceledException or IOException or TimeoutException) { }
        }
    }
    private async Task WatchdogAsync(CancellationTokenSource reads)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(Math.Min(250, _timing.SnapshotDeadline.TotalMilliseconds / 4)));
        try
        {
            while (await timer.WaitForNextTickAsync(reads.Token).ConfigureAwait(false))
                if (Stopwatch.GetElapsedTime(LastValidTicks) >= _timing.SnapshotDeadline) { reads.Cancel(); return; }
        }
        catch (OperationCanceledException) { }
    }
    private static async Task DiscardAsync(Stream stream, CancellationToken token)
    {
        var bytes = new byte[1024];
        try { while (await stream.ReadAsync(bytes, token).ConfigureAwait(false) != 0) { } }
        catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException) { }
    }
    public ValueTask DisposeAsync()
    {
        lock (_gate)
        {
            if (_shutdown is not null) return new(_shutdown);
            _disposed = true; _lifetime.Cancel(); _childCancellation?.Cancel();
            _shutdown = FinishShutdownAsync();
            return new(_shutdown);
        }
    }
    private async Task FinishShutdownAsync()
    {
        try { if (_worker is not null) await _worker.ConfigureAwait(false); }
        finally { _lifetime.Dispose(); _retry.Dispose(); }
    }
}
