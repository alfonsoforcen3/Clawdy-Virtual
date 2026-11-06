using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Clawdy.Windows.Core;

public sealed record WireSnapshot(string InstanceId, long Revision, StatusSnapshot Snapshot);

/// <summary>Bounded v1 collector decoder. No URL or process command is accepted.</summary>
public static partial class WireProtocol
{
    public const int MaximumFrameBytes = 65_536;
    private static readonly HashSet<string> States = ["idle", "working", "ready", "attention", "error", "disconnected", "uncertain"];
    private static readonly HashSet<string> Providers = ["codex", "claude", "gemini", "cursor", "other"];
    private static readonly HashSet<string> Fields = ["version", "instance_id", "revision", "state", "working_count", "providers", "demo", "phrase", "confidence", "attention_providers", "attention_chats"];
    [GeneratedRegex("^[0-9a-f]{32}$", RegexOptions.CultureInvariant)]
    private static partial Regex InstancePattern();
    [GeneratedRegex("^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$", RegexOptions.CultureInvariant)]
    private static partial Regex ThreadPattern();

    public static WireSnapshot Decode(ReadOnlyMemory<byte> frame, bool expectedDemo)
    {
        if (frame.Length is 0 or > MaximumFrameBytes) throw new FormatException("frame-size");
        // JsonDocument rejects invalid UTF-8, comments, NaN and excessive nesting.
        using var document = JsonDocument.Parse(frame, new JsonDocumentOptions { MaxDepth = 16 });
        var root = document.RootElement;
        RequireObject(root, Fields);
        if (root.GetProperty("version").GetInt32() != 1) throw new FormatException("version");
        var instance = Text(root.GetProperty("instance_id"), 128);
        var revision = root.GetProperty("revision").GetInt64();
        if (!InstancePattern().IsMatch(instance) || revision < 1) throw new FormatException("identity");
        var state = Text(root.GetProperty("state"), 32);
        var count = root.GetProperty("working_count").GetInt32();
        var demo = root.GetProperty("demo").GetBoolean();
        var phrase = Text(root.GetProperty("phrase"), 256);
        var providers = ProviderList(root.GetProperty("providers"));
        var confidence = root.TryGetProperty("confidence", out var c) ? Text(c, 16) : demo ? "demo" : "unknown";
        if (!States.Contains(state) || count is < 0 or > 256 || demo != expectedDemo
            || confidence is not ("demo" or "reported" or "unknown") || (confidence == "demo") != demo)
            throw new FormatException("snapshot-values");
        var actions = root.TryGetProperty("attention_providers", out var a) ? ProviderList(a) : [];
        var chats = new List<AttentionChat>();
        if (root.TryGetProperty("attention_chats", out var routes))
        {
            if (routes.ValueKind != JsonValueKind.Array || routes.GetArrayLength() > 3) throw new FormatException("routes");
            foreach (var route in routes.EnumerateArray())
            {
                RequireObject(route, ["provider", "thread_id"]);
                var provider = Text(route.GetProperty("provider"), 16);
                var id = Text(route.GetProperty("thread_id"), 36);
                if (provider != "codex" || !ThreadPattern().IsMatch(id) || chats.Any(chat => chat.ThreadId == id))
                    throw new FormatException("route-values");
                chats.Add(new AttentionChat(provider, id));
            }
        }
        if ((actions.Length > 0 && state is not ("attention" or "error"))
            || (chats.Count > 0 && (demo || state is not ("attention" or "error") || !actions.Contains("codex"))))
            throw new FormatException("action-state");
        return new(instance, revision, new(state, count, providers, demo, phrase, confidence, actions, chats.ToArray()));
    }

    private static void RequireObject(JsonElement value, HashSet<string> allowed)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new FormatException("object");
        var found = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject())
            if (!allowed.Contains(property.Name) || !found.Add(property.Name)) throw new FormatException("fields");
    }

    private static string Text(JsonElement value, int maximumBytes)
    {
        if (value.ValueKind != JsonValueKind.String) throw new FormatException("string");
        var result = value.GetString()!;
        if (Encoding.UTF8.GetByteCount(result) > maximumBytes || result.Any(ch => ch < 32 || ch == 127))
            throw new FormatException("text-bounds");
        return result;
    }

    private static string[] ProviderList(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() > 5) throw new FormatException("providers");
        var result = value.EnumerateArray().Select(item => Text(item, 16)).ToArray();
        if (result.Any(item => !Providers.Contains(item)) || result.Distinct(StringComparer.Ordinal).Count() != result.Length)
            throw new FormatException("provider-values");
        return result;
    }
}

/// <summary>One partial frame retained; byte limits apply before JSON allocation.</summary>
public sealed class NdjsonFramer
{
    private readonly byte[] _partial = new byte[WireProtocol.MaximumFrameBytes];
    private int _count;
    public IEnumerable<byte[]> Append(ReadOnlyMemory<byte> data)
    {
        // Fixed caller reads bound this returned list. No event history is kept.
        var frames = new List<byte[]>();
        foreach (var item in data.Span)
        {
            if (item == 10)
            {
                if (_count > 0) frames.Add(_partial.AsSpan(0, _count).ToArray());
                _count = 0;
            }
            else
            {
                if (_count == _partial.Length) throw new FormatException("frame-size");
                _partial[_count++] = item;
            }
        }
        return frames;
    }
}

public sealed class RestartBudget
{
    private readonly Queue<double> _failures = new();
    public double? RecordFailure(double now)
    {
        while (_failures.TryPeek(out var oldest) && now - oldest > 300) _failures.Dequeue();
        if (_failures.Count >= 4) return null;
        _failures.Enqueue(now);
        return _failures.Count <= 3 ? Math.Pow(2, _failures.Count - 1) : null;
    }
    public void Reset() => _failures.Clear();
}

public static class SnapshotFreshness
{
    public static StatusSnapshot Present(StatusSnapshot value, double age) => age >= 10
        ? StatusSnapshot.Offline() with { Demo = value.Demo }
        : age >= 3 ? new("uncertain", 0, [], value.Demo, "Status is getting stale", "unknown", [], []) : value;
}
