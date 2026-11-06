using System.Text;
using System.Text.Json;
using Clawdy.Windows.Core;

static void Check(bool value, string message) { if (!value) throw new Exception(message); }
var fixture = """{"version":1,"instance_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","revision":1,"state":"working","working_count":2,"providers":["codex","claude"],"demo":false,"phrase":"Last reported working; freshness unconfirmed.","confidence":"reported","attention_providers":[]}""";
var bytes = Encoding.UTF8.GetBytes(fixture);
var decoded = WireProtocol.Decode(bytes, false);
Check(decoded.Snapshot.WorkingCount == 2 && decoded.Snapshot.Providers.Length == 2, "shared protocol count/apps");
Check(decoded.Snapshot.Confidence == "reported", "no invented freshness");
foreach (var bad in new[]
{
    fixture.Replace("\"revision\":1", "\"revision\":true"), fixture.Replace("\"version\":1", "\"version\":1,\"version\":1"),
    fixture.Replace("\"working_count\":2", "\"working_count\":257"), fixture.Replace("\"confidence\":\"reported\"", "\"confidence\":\"fresh\""),
    fixture.Replace("\"codex\",\"claude\"", "\"codex\",\"codex\""), fixture.Replace("\"providers\":", "\"private_prompt\":\"secret\",\"providers\":"),
    fixture.Replace("\"attention_providers\":[]", "\"attention_providers\":[\"codex\"]")
})
{
    var rejected = false;
    try { WireProtocol.Decode(Encoding.UTF8.GetBytes(bad), false); }
    catch (Exception error) when (error is FormatException or JsonException or InvalidOperationException) { rejected = true; }
    Check(rejected, "malformed snapshot must fail closed");
}
Check(SnapshotFreshness.Present(decoded.Snapshot, 2.99).State == "working", "fresh transport report retains colour");
var stale = SnapshotFreshness.Present(decoded.Snapshot, 3);
Check(stale.State == "uncertain" && stale.WorkingCount == 0 && stale.AttentionChats.Length == 0, "stale cannot expose actions");
var offline = SnapshotFreshness.Present(decoded.Snapshot with { State = "ready" }, 10);
Check(offline.State == "disconnected" && offline.Providers.Length == 0, "cached green cannot survive loss");
var framer = new NdjsonFramer();
Check(!framer.Append(bytes.AsMemory(0, 7)).Any(), "fragment retained");
Check(framer.Append(bytes.AsMemory(7)).Count() == 0, "newline required");
Check(framer.Append(new byte[] { 10, 10 }).Single().SequenceEqual(bytes), "tiny/multiple frames");
var oversize = false;
try { new NdjsonFramer().Append(new byte[WireProtocol.MaximumFrameBytes + 1]); } catch (FormatException) { oversize = true; }
Check(oversize, "framing has a hard byte bound");
var budget = new RestartBudget();
Check(budget.RecordFailure(0) == 1 && budget.RecordFailure(1) == 2 && budget.RecordFailure(2) == 4 && budget.RecordFailure(3) is null, "recovery stops after three automatic restarts");
budget.Reset(); Check(budget.RecordFailure(4) == 1, "explicit retry resets budget");
Console.WriteLine("Protocol checks passed: strict frames/schema/privacy, count/apps, confidence, stale/lost state and bounded recovery. Native Windows UI NOT tested.");
