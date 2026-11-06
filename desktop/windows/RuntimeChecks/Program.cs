using System.Diagnostics;
using System.Text.Json;
using Clawdy.Windows.Core;
using Clawdy.Windows.Runtime;

var pythonIndex = Array.IndexOf(args, "--python");
var python = pythonIndex >= 0 && pythonIndex + 1 < args.Length ? args[pythonIndex + 1]
    : OperatingSystem.IsWindows() ? "python" : "/usr/bin/python3";
var fixture = Path.Combine(AppContext.BaseDirectory, "collector_fixture.py");
var shared = Path.Combine(AppContext.BaseDirectory, "shared", "virtual_clawdy.py");
var fast = new SupervisorTiming(TimeSpan.FromSeconds(1.5), .02);
static void Check(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
static async Task Until(Func<bool> condition, string message, int milliseconds = 8000)
{
    var deadline = Stopwatch.GetTimestamp();
    while (!condition())
    {
        if (Stopwatch.GetElapsedTime(deadline).TotalMilliseconds >= milliseconds) throw new TimeoutException(message);
        await Task.Delay(20);
    }
}
static List<int> Pids(string marker)
{
    if (!File.Exists(marker)) return [];
    var result = new List<int>();
    foreach (var line in File.ReadAllLines(marker))
        try { using var doc = JsonDocument.Parse(line); result.Add(doc.RootElement.GetProperty("pid").GetInt32()); }
        catch (JsonException) { /* Last append may still be in flight. */ }
    return result;
}
static bool Alive(int pid)
{
    try { using var process = Process.GetProcessById(pid); return !process.HasExited; }
    catch (ArgumentException) { return false; }
}
async Task Scenario(string name, string scenario, Func<CollectorSupervisor, string, Task> exercise, bool demo = false, string? script = null)
{
    var directory = Path.Combine(Path.GetTempPath(), "clawdy-fixture-" + Guid.NewGuid().ToString("N"));
    Directory.CreateDirectory(directory); var marker = Path.Combine(directory, "starts.jsonl");
    var previousScenario = Environment.GetEnvironmentVariable("CLAWDY_TEST_SCENARIO");
    var previousMarker = Environment.GetEnvironmentVariable("CLAWDY_TEST_MARKER");
    Environment.SetEnvironmentVariable("CLAWDY_TEST_SCENARIO", scenario);
    Environment.SetEnvironmentVariable("CLAWDY_TEST_MARKER", marker);
    var source = new CollectorSupervisor(python, script ?? fixture, demo, fast);
    try
    {
        source.Start(); await exercise(source, marker);
    }
    finally
    {
        try
        {
            await Task.WhenAll(source.DisposeAsync().AsTask(), source.DisposeAsync().AsTask()).WaitAsync(TimeSpan.FromSeconds(5));
            await Until(() => Pids(marker).All(pid => !Alive(pid)), "owned fixture survived shutdown", 2000);
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLAWDY_TEST_SCENARIO", previousScenario);
            Environment.SetEnvironmentVariable("CLAWDY_TEST_MARKER", previousMarker);
            Directory.Delete(directory, recursive: true);
        }
    }
    Console.WriteLine("PASS: " + name);
}

// Pure dispatch tests do not inspect a real registry or launch an application.
var id = "11111111-2222-4333-8444-555555555555";
Check(LaunchPolicy.Destination(new("chat", "codex", new("codex://threads/" + id)), _ => true, "fixture-terminal") == "codex://threads/" + id, "valid fixed Codex route");
foreach (var invalid in new[] { "https://example.invalid/" + id, "codex://threads//" + id,
    "codex://threads/" + id + "?prompt=PRIVATE", "codex://threads/" + id + "#x", "codex://other/" + id,
    "codex://user@threads/" + id, "codex://threads:42/" + id })
    Check(LaunchPolicy.Destination(new("chat", "codex", new(invalid)), _ => true, "terminal") is null, "malformed URL must not dispatch");
Check(LaunchPolicy.Destination(new("chat", "codex", new("relative", UriKind.Relative)), _ => true, "terminal") is null, "relative URL rejected");
Check(LaunchPolicy.Destination(new("chat", "codex", new("codex://threads/" + id)), _ => false, "terminal") is null, "protocol registration required");
Check(LaunchPolicy.Destination(new("app", "claude", null), _ => false, "fixture-terminal") == "fixture-terminal", "CLI fallback stays terminal-only");
Check(LaunchPolicy.Destination(new("app", "gemini", new("https://example.invalid")), _ => true, "terminal") is null, "app action cannot inject URL");
Console.WriteLine("PASS: pure launch allowlist; no provider or OS app launched");

await Scenario("shared Python collector -S -u --demo emits real idle and working snapshots", "unused", async (source, _) =>
{
    ReceivedStatus? item = null;
    await Until(() => (item = source.TakeLatest()) is { Snapshot.Demo: true, Snapshot.State: "idle" }, "real demo idle missing");
    Check(item!.Snapshot.Confidence == "demo", "real collector demo qualification");
    await Until(() => (item = source.TakeLatest()) is { Snapshot.State: "working", Snapshot.WorkingCount: 1 }, "real demo working missing", 10000);
    Check(item!.Snapshot.Providers.SequenceEqual(new[] { "codex" }), "real collector provider summary");
}, true, shared);

await Scenario("single startup, rapid source changes and concurrent idempotent shutdown", "healthy", async (source, marker) =>
{
    await Task.WhenAll(Enumerable.Range(0, 12).Select(_ => Task.Run(source.Start)));
    await Until(() => source.TakeLatest() is { Snapshot.State: "working" }, "healthy child missing");
    Check(Pids(marker).Count == 1, "concurrent Start launched extra collectors");
    for (var index = 0; index < 30; index++) source.Retry(index % 2 == 0);
    source.Retry(true); var generation = source.Generation;
    ReceivedStatus? item = null;
    await Until(() => (item = source.TakeLatest()) is { Snapshot.Demo: true, Snapshot.State: "working" } && item.Generation == generation,
                "final source generation never became active");
    Check(source.Demo, "final mode changed unexpectedly");
});

await Scenario("crash circuit breaker, no automatic respawn and explicit retry", "crash", async (source, marker) =>
{
    await Until(() => source.RecoveryPaused, "crash budget never paused");
    Check(Pids(marker).Count == 4, "wrong automatic launch budget");
    await Task.Delay(200); Check(Pids(marker).Count == 4, "paused collector respawned");
    source.Retry(); await Until(() => Pids(marker).Count >= 5, "explicit retry did not wake recovery");
});

foreach (var fault in new[] { "hang", "replay", "malformed", "oversized", "changed-instance" })
    await Scenario("bounded owned-process recovery: " + fault, fault, async (source, marker) =>
    {
        if (fault == "replay")
        {
            await Until(() => source.TakeLatest() is { Snapshot.State: "ready" }, "replay initial frame missing");
            var last = source.LastValidTicks; await Task.Delay(150);
            Check(source.LastValidTicks == last, "equal revisions refreshed liveness");
        }
        await Until(() => Pids(marker).Count >= 2, "fault did not restart its collector");
        var pids = Pids(marker); Check(!Alive(pids[0]), "old child survived restart");
    });

await Scenario("stderr pipe flood cannot deadlock stdout/status", "stderr-flood", async (source, _) =>
    await Until(() => source.TakeLatest() is { Snapshot.State: "working" }, "stderr flood blocked reader"));

await Scenario("10,000-frame burst coalesces to latest with no queued history", "burst", async (source, _) =>
{
    // Revision 10000 has arrived when the last frame is returned; subsequent
    // TakeLatest must not replay an earlier queued item. Only one slot exists.
    await Until(() => source.TakeLatest() is { Revision: 10000 }, "burst did not deliver final revision");
    Check(source.TakeLatest() is null, "retained snapshot history instead of latest-only slot");
});

await Scenario("owned launcher descendants stop with their supervisor", "descendant", async (source, marker) =>
{
    await Until(() => Pids(marker).Count >= 2 && source.TakeLatest() is { Snapshot.State: "working" }, "descendant fixture did not start");
});

var missing = new CollectorSupervisor(Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"), "missing-python"), fixture, true, fast);
missing.Start();
await Until(() => missing.RecoveryPaused, "launch failure was not bounded");
await missing.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5));
var closed = false; try { missing.Start(); } catch (ObjectDisposedException) { closed = true; }
Check(closed, "Start after disposal recreated a worker");
Console.WriteLine("PASS: unavailable interpreter fails bounded; disposed supervisor cannot restart");
Console.WriteLine("All portable process checks passed. Recovery delays shortened for fixture tests. Native Windows WPF/tray/registry/actions NOT exercised.");
