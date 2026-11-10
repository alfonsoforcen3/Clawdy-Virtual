namespace Clawdy.Windows.Core;

// Destinations are constructed locally. Backend input never supplies a URI.
public sealed record CardAction(string Kind, string Provider, Uri? Target)
{
    public string Label => Kind == "chat" ? "Open chat" : Provider switch
    {
        "codex" => "Open in ChatGPT", "cursor" => "Open Cursor", _ => "Open Terminal"
    };
    public string Identity => Kind == "chat" ? "chat:" + Target?.AbsolutePath :
        Provider is "claude" or "gemini" ? "app:terminal" : "app:" + Provider;
    public override string ToString() => $"CardAction({Kind}, {Provider}, target redacted)";

    public static bool IsThreadId(string? value) => value is not null && value.Length == 36 &&
        Guid.TryParseExact(value, "D", out var id) && id.ToString("D") == value;
}

// One user action may be handed to the host at a time. Tickets contain only
// versions, never routing IDs. A stale completion cannot release a newer slot.
public sealed class CardActionAdmission
{
    public readonly record struct Ticket(long Id, long ActionVersion, long PresentationVersion);
    private long _next;
    private Ticket? _active;
    public bool Busy => _active is not null;
    public bool TryBegin(long actionVersion, long presentationVersion, out Ticket ticket)
    {
        ticket = default;
        if (Busy) return false;
        ticket = new Ticket(++_next, actionVersion, presentationVersion); _active = ticket; return true;
    }
    public bool Complete(Ticket ticket)
    {
        if (_active != ticket) return false;
        _active = null; return true;
    }
}

// No WPF, filesystem, provider control, or hardware dependency. Time is supplied
// by the caller so retention and reconnect behaviour can be tested on any OS.
public sealed class AttentionPolicy
{
    private bool _redEpisode, _consumed, _dismissed, _autoPinned, _hovered, _keyboard;
    private bool _exactChatActions;
    private StatusSnapshot _latest = StatusSnapshot.Offline();
    private StatusSnapshot? _retained;
    private long _episode, _heldEpisode;

    public StatusSnapshot Displayed { get; private set; } = StatusSnapshot.Offline();
    public bool IsRecent { get; private set; }
    public bool Visible { get; private set; }
    public DateTimeOffset? RetainUntil { get; private set; }
    public long ActionVersion { get; private set; }
    public IReadOnlyList<CardAction> Actions { get; private set; } = Array.Empty<CardAction>();
    public bool HasDeferredAttention => _retained is null && IsRed(_latest.State) && !_consumed && !_dismissed;
    public bool HasPendingAttention => _retained is not null;
    public bool HasInteraction => _hovered || _keyboard;

    public AttentionPolicy(TimeSpan? minimumDuration = null, bool exactChatActions = false)
    {
        // Kept as a source-compatible argument; attention now requires acknowledgment.
        if (minimumDuration < TimeSpan.Zero || minimumDuration > TimeSpan.FromMinutes(1))
            throw new ArgumentOutOfRangeException(nameof(minimumDuration));
        _exactChatActions = exactChatActions;
    }

    public static bool IsRed(string state) => state is "attention" or "error";
    private static StatusSnapshot Copy(StatusSnapshot value) => value with
    {
        Providers = [.. value.Providers], AttentionProviders = [.. value.AttentionProviders],
        AttentionChats = [.. value.AttentionChats]
    };
    private static bool SameAttention(StatusSnapshot a, StatusSnapshot b) => a.State == b.State && a.Demo == b.Demo &&
        a.AttentionProviders.Order().SequenceEqual(b.AttentionProviders.Order()) &&
        a.AttentionChats.OrderBy(c => c.ThreadId).SequenceEqual(b.AttentionChats.OrderBy(c => c.ThreadId));

    public void EnableExactChatActions(bool enabled)
    {
        _exactChatActions = enabled; SetDisplay(Displayed, IsRecent);
    }

    // True requests one automatic expansion. Revision, count, phrase and
    // transport changes never create another red episode on their own.
    public bool Update(StatusSnapshot value, DateTimeOffset now)
    {
        // A mode switch must never carry a retained live action into Demo.
        if (_latest.Demo != value.Demo)
        {
            ClearRetention(); _autoPinned = false;
            _redEpisode = false; _consumed = false; _dismissed = false;
            if (!HasInteraction) Visible = false;
        }
        var red = IsRed(value.State);
        if (red && (!_redEpisode || (_retained is not null && IsRed(_latest.State) && !SameAttention(_latest, value))))
        {
            _episode++; _consumed = false; _dismissed = false;
        }
        if (red) _redEpisode = true;
        else if (value.State is "working" or "ready" or "idle")
            _redEpisode = false;
        _latest = Copy(value);
        if (_retained is not null)
        {
            // The first pending destination is immutable. Only the live WIP/app
            // summary follows the source; the latest snapshot is a bounded deferral.
            SetDisplay(_retained with { WorkingCount = value.WorkingCount, Providers = [.. value.Providers] },
                !red || !SameAttention(_retained, value));
            return false;
        }
        var open = red && !_consumed && !_dismissed;
        if (open)
        {
            _consumed = true; _heldEpisode = _episode;
            _retained = Copy(value); _autoPinned = true; Visible = true;
        }
        SetDisplay(value, false);
        return open;
    }

    public void Show(bool keyboard)
    {
        Visible = true; _keyboard |= keyboard;
        if (_retained is null && IsRed(_latest.State))
        {
            _retained = Copy(_latest); _heldEpisode = _episode;
            _autoPinned = true; _consumed = true;
            SetDisplay(_latest, false);
        }
    }
    // The host owns quiet-time/session gating. A denied request is consumed,
    // not queued for later; an already user-visible card may remain visible.
    public void SuppressAutomaticOpen(bool preserveVisible = false)
    {
        ClearRetention(); _autoPinned = false;
        Visible = preserveVisible;
        SetDisplay(_latest, false);
    }
    public void SetInteraction(bool hovered, bool keyboard) { _hovered = hovered; _keyboard = keyboard; }

    public bool Expire(DateTimeOffset now)
    {
        // Pending alerts have no time-based acknowledgment.
        return false;
    }
    public bool Leave(DateTimeOffset now)
    {
        if (HasInteraction) return false;
        if (Expire(now)) return true;
        if (_autoPinned) return false;
        Visible = false; return true;
    }
    public void Dismiss()
    {
        if (_redEpisode && (_retained is null || _heldEpisode == _episode)) { _dismissed = true; _consumed = true; }
        ClearRetention(); _autoPinned = false; _keyboard = false; _hovered = false;
        Visible = false; ActionVersion++; SetDisplay(_latest, false);
    }
    public void Reset()
    {
        Dismiss(); _redEpisode = false; _consumed = false; _dismissed = false;
        _latest = StatusSnapshot.Offline(); SetDisplay(_latest, false);
    }
    private void ClearRetention() { _retained = null; RetainUntil = null; }

    private void SetDisplay(StatusSnapshot value, bool recent)
    {
        var actions = BuildActions(value, _exactChatActions);
        if (Displayed.State != value.State || Displayed.Demo != value.Demo || !Actions.SequenceEqual(actions)) ActionVersion++;
        Displayed = Copy(value); IsRecent = recent; Actions = actions;
    }

    public static IReadOnlyList<CardAction> BuildActions(StatusSnapshot value, bool exactChatActions)
    {
        if (value.Demo || !IsRed(value.State)) return Array.Empty<CardAction>();
        var actions = new List<CardAction>();
        if (exactChatActions && value.AttentionProviders.Contains("codex"))
        {
            foreach (var chat in value.AttentionChats.Where(c => c.Provider == "codex" && CardAction.IsThreadId(c.ThreadId))
                         .DistinctBy(c => c.ThreadId).Take(3))
                actions.Add(new CardAction("chat", "codex", new Uri("codex://threads/" + chat.ThreadId)));
        }
        foreach (var provider in value.AttentionProviders)
        {
            if (provider is not ("codex" or "claude" or "gemini" or "cursor")) continue;
            if (provider == "codex" && actions.Any(a => a.Kind == "chat")) continue;
            var action = new CardAction("app", provider, null);
            if (!actions.Any(a => a.Identity == action.Identity)) actions.Add(action);
        }
        return actions.Take(3).ToArray();
    }

    public static void SelfTest()
    {
        static void Check(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
        var now = DateTimeOffset.UnixEpoch;
        var first = new AttentionChat("codex", "11111111-2222-4333-8444-555555555555");
        var red = new StatusSnapshot("attention", 3, ["claude"], false, "fixture", "reported", ["codex"], [first]);
        var ready = new StatusSnapshot("ready", 0, [], false, "fixture", "reported", [], []);
        var policy = new AttentionPolicy(exactChatActions: true);
        Check(policy.Update(red, now), "red requests automatic expansion");
        var version = policy.ActionVersion;
        Check(!policy.Update(red with { WorkingCount = 4, Phrase = "another" }, now.AddSeconds(1)) && policy.ActionVersion == version,
            "report/count/phrase churn retains episode and action identity");
        policy.Update(ready, now.AddSeconds(2));
        Check(policy.IsRecent && policy.Displayed.State == "attention" && policy.Displayed.WorkingCount == 0 && policy.Actions[0].Kind == "chat",
            "B-to-G retains exact chat with recent label and latest WIP");
        policy.Update(ready with { State = "working", WorkingCount = 2, Providers = ["gemini"] }, now.AddSeconds(3));
        Check(policy.Displayed.WorkingCount == 2 && policy.RetainUntil is null, "B-to-Y has no expiry");
        policy.SetInteraction(true, false);
        Check(!policy.Expire(now.AddSeconds(21)), "pointer protects recent action after deadline");
        policy.SetInteraction(false, false);
        Check(!policy.Leave(now.AddDays(1)) && policy.Visible, "pending alert survives time and pointer exit");
        policy.Dismiss();
        policy.Update(red, now.AddSeconds(22)); policy.Dismiss();
        policy.Update(StatusSnapshot.Offline(), now.AddSeconds(23));
        Check(!policy.Update(red, now.AddSeconds(24)) && !policy.Visible, "dismissed red cannot reopen through transport loss");
        policy.Update(ready, now.AddSeconds(25));
        Check(policy.Update(red, now.AddSeconds(26)), "confirmed non-red state allows next request");
        Check(BuildActions(red with { Demo = true }, true).Count == 0, "demo never launches");
        Check(BuildActions(red, false)[0].Kind == "app", "missing protocol registration has honest fallback");
        var mixed = red with { AttentionProviders = ["codex", "claude", "gemini"] };
        Check(BuildActions(mixed, true).Count == 2 && BuildActions(mixed, true)[1].Label == "Open Terminal", "CLI fallback deduplicates Terminal");
        Check(!CardAction.IsThreadId("../thread") && !CardAction.IsThreadId("https://example.invalid"), "malformed routes rejected");
        Check(!BuildActions(red, true)[0].ToString().Contains(first.ThreadId), "action diagnostics redact thread IDs");
        policy.Reset();
        Check(policy.Actions.Count == 0 && policy.Displayed.AttentionChats.Length == 0 && !policy.Visible,
            "mode reset and shutdown clear routing IDs and actions");
        var denied = new AttentionPolicy(exactChatActions: true);
        Check(denied.Update(red, now), "new request reaches the host notification gate");
        denied.SuppressAutomaticOpen();
        Check(!denied.Visible && denied.RetainUntil is null, "quiet-time denial leaves no visible or retained automatic card");
        var another = red with { AttentionChats = [new AttentionChat("codex", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")] };
        Check(!denied.Update(another, now.AddSeconds(1)) && !denied.Visible,
            "cached anchor or changed route cannot reopen a denied red episode");
        denied.Update(StatusSnapshot.Offline(), now.AddSeconds(2));
        Check(!denied.Update(red, now.AddSeconds(3)) && !denied.Visible, "quiet-time expiry or reconnect cannot deliver a deferred popup");
        denied.Show(false);
        Check(denied.Visible && denied.HasPendingAttention && !denied.Leave(now.AddDays(1)),
            "explicit opening remains permitted during quiet time and latches its red destination");
        denied.Dismiss(); denied.Update(ready, now.AddSeconds(4));
        Check(denied.Update(red, now.AddSeconds(5)), "a new confirmed episode is gated anew");
        denied.Show(true); denied.SuppressAutomaticOpen(preserveVisible: true);
        Check(denied.Visible, "host denial does not close an already explicit user presentation");
        var admission = new CardActionAdmission();
        Check(admission.TryBegin(1, 2, out var firstTicket) && !admission.TryBegin(1, 2, out _),
            "rapid repeated clicks admit one host launch only");
        Check(admission.Complete(firstTicket), "completion releases its own action");
        Check(admission.TryBegin(3, 4, out var newTicket), "completion re-enables a subsequent action");
        Check(!admission.Complete(firstTicket) && admission.Busy, "old completion cannot release a newer action");
        Check(admission.Complete(newTicket) && !admission.Busy, "current completion releases its own action slot");
        var modeSwitch = new AttentionPolicy(exactChatActions: true);
        modeSwitch.Update(red, now); modeSwitch.Show(false);
        modeSwitch.Update(ready with { Demo = true }, now.AddSeconds(1));
        Check(modeSwitch.Displayed.Demo && modeSwitch.Actions.Count == 0 && modeSwitch.RetainUntil is null,
            "live retained actions cannot survive an immediate switch to Demo");
        var recentOffline = new AttentionPolicy(exactChatActions: true);
        recentOffline.Update(red, now); recentOffline.Show(false);
        recentOffline.Update(StatusSnapshot.Offline(), now.AddSeconds(1));
        Check(recentOffline.IsRecent && recentOffline.Actions.Count == 1 && recentOffline.Displayed.WorkingCount == 0,
            "offline recent request remains honestly actionable within the click window");
        Check(!recentOffline.Expire(now.AddDays(1)) && recentOffline.Actions.Count == 1,
            "offline retained actions await acknowledgment");
        var deferred = new AttentionPolicy(exactChatActions: true);
        deferred.Update(red, now); deferred.Update(ready, now);
        deferred.Update(another, now); deferred.Update(another with { WorkingCount = 8 }, now);
        Check(deferred.Actions[0].Target == BuildActions(red, true)[0].Target && deferred.IsRecent
            && deferred.Displayed.WorkingCount == 8, "first destination retained with live WIP");
        deferred.Dismiss();
        Check(deferred.Update(another, now), "acknowledging A preserves latest deferred B eligibility");
        deferred.Dismiss();
        Check(!deferred.Update(another, now), "acknowledged B does not reopen");
    }
}
