namespace Clawdy.Windows.Core;

// UI contract shared by the native host and card. Routing is memory-only.
public sealed record AttentionChat(string Provider, string ThreadId);
public sealed record StatusSnapshot(
    string State, int WorkingCount, string[] Providers, bool Demo, string Phrase,
    string Confidence, string[] AttentionProviders, AttentionChat[] AttentionChats)
{
    public static StatusSnapshot Offline(string phrase = "Waiting for local status") =>
        new("disconnected", 0, [], false, phrase, "unknown", [], []);
}
