using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Threading;
using Clawdy.Windows.Core;
using Clawdy.Windows.Native;
using Clawdy.Windows.Runtime;
using Clawdy.Windows.UI;

namespace Clawdy.Windows;

internal static class Program
{
    private const string InstanceMutex = @"Local\ClawdyVirtual.PrivatePrototype.0";
    private static string HandoffEvent(string nonce) => @"Local\ClawdyVirtual.UpdateReady." + nonce;

    [STAThread]
    private static int Main(string[] args)
    {
        if (!OperatingSystem.IsWindows()) return 2;
        bool demo = false, skipUpdateHandoff = false;
        string python = "py";
        string? handoffNonce = null, handoffRevision = null;
        for (var index = 0; index < args.Length; index++)
        {
            if (args[index] == "--demo") demo = true;
            else if (args[index] == "--observe") demo = false;
            else if (args[index] == "--python" && index + 1 < args.Length) python = args[++index];
            else if (args[index] == "--skip-update-handoff") skipUpdateHandoff = true;
            else if (args[index] == "--update-handoff" && index + 2 < args.Length && handoffNonce is null)
            {
                handoffNonce = args[++index]; handoffRevision = args[++index];
                skipUpdateHandoff = true;
            }
            else return 2;
        }
        // One explicit user-session instance. This never controls a physical bridge.
        int exitCode;
        string? restart;
        using (var unique = new Mutex(true, InstanceMutex, out var owns))
        {
            if (!owns && handoffNonce is null) return 0;
            try
            {
                if (handoffNonce is not null)
                {
                    if (!AcknowledgeHandoff(handoffNonce, handoffRevision)) return 2;
                    if (!owns)
                    {
                        try { owns = unique.WaitOne(TimeSpan.FromSeconds(10)); }
                        catch (AbandonedMutexException) { owns = true; }
                    }
                    if (!owns) return 0;
                }
                if (!skipUpdateHandoff && VirtualUpdateClient.PendingOnLaunch() is { } pending
                    && TryStartupHandoff(pending, demo, python)) return 0;

                var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
                var host = new TrayHost(app, python, demo);
                app.Exit += (_, _) => host.CloseUi();
                try { host.Start(); exitCode = app.Run(); }
                finally { host.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
                restart = host.RestartExecutable;
                demo = host.Demo;
            }
            finally { if (owns) unique.ReleaseMutex(); }
        }
        // Dispose the mutex handle before launching. The new app tests whether
        // the named mutex was created, even when the old one is unlocked.
        if (restart is not null)
        {
            try
            {
                using var launched = Process.Start(UpdateStartInfo(restart, demo, python))
                    ?? throw new InvalidOperationException("restart-failed");
            }
            catch (Exception error) when (error is IOException or InvalidOperationException or UnauthorizedAccessException
                or System.ComponentModel.Win32Exception or System.Security.SecurityException)
            {
                MessageBox.Show("Clawdy could not start the prepared update. Open your previous Clawdy preview to keep using it.",
                    "Virtual Clawdy", MessageBoxButton.OK, MessageBoxImage.Warning);
                return 1;
            }
        }
        return exitCode;
    }

    private static ProcessStartInfo UpdateStartInfo(string path, bool demo, string python)
    {
        var start = new ProcessStartInfo(path) { UseShellExecute = false };
        foreach (var argument in new[] { demo ? "--demo" : "--observe", "--python", python, "--skip-update-handoff" })
            start.ArgumentList.Add(argument);
        return start;
    }

    private static bool AcknowledgeHandoff(string nonce, string? expectedRevision)
    {
        if (!Guid.TryParseExact(nonce, "N", out var id) || id.ToString("N") != nonce
            || expectedRevision != VirtualUpdateClient.SourceRevision) return false;
        try
        {
            using var ready = EventWaitHandle.OpenExisting(HandoffEvent(nonce));
            return ready.Set();
        }
        catch (Exception error) when (error is WaitHandleCannotBeOpenedException or IOException
            or UnauthorizedAccessException or System.Security.SecurityException) { return false; }
    }

    private static bool TryStartupHandoff(PreparedUpdate pending, bool demo, string python)
    {
        try
        {
            var nonce = Guid.NewGuid().ToString("N");
            using var ready = new EventWaitHandle(false, EventResetMode.ManualReset, HandoffEvent(nonce));
            var start = UpdateStartInfo(pending.Path, demo, python);
            start.ArgumentList.Add("--update-handoff");
            start.ArgumentList.Add(nonce);
            start.ArgumentList.Add(pending.Revision);
            using var launched = Process.Start(start);
            if (launched is null) return false;
            // The candidate must reach managed Main and confirm its embedded
            // revision while this process still owns the single-instance lock.
            if (ready.WaitOne(TimeSpan.FromSeconds(5))) return true;
            try { if (!launched.HasExited) launched.Kill(); }
            catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception) { }
            return false;
        }
        catch (Exception error) when (error is IOException or InvalidOperationException or UnauthorizedAccessException
            or System.ComponentModel.Win32Exception or System.Security.SecurityException or WaitHandleCannotBeOpenedException)
        { return false; }
    }
}

internal sealed class TrayHost : IAsyncDisposable
{
    private readonly Application _app;
    private readonly CollectorSupervisor _collector;
    private readonly TrayIcon _tray;
    private readonly CardWindow _card;
    private readonly DesktopPillWindow _desktopPill;
    private readonly SessionFinishTracker _finishTracker = new();
    private readonly DispatcherTimer _tick;
    private readonly VirtualUpdateClient _updates;
    private readonly CancellationTokenSource _updateLifetime = new();
    private CancellationTokenSource? _automaticUpdateCancellation;
    private Task<UpdateReply>? _updateWork;
    private UpdateReply? _updateReply;
    private string _updateMessage;
    private DateTimeOffset _nextAutomaticCheck;
    private bool _automaticUpdates;
    private MenuItem? _updateStatusItem, _checkUpdateItem, _stageUpdateItem, _restartUpdateItem, _automaticUpdateItem;
    private StatusSnapshot _snapshot = StatusSnapshot.Offline();
    private StatusSnapshot? _displayed;
    private long _received = Stopwatch.GetTimestamp();
    private bool _manualReducedMotion, _reducedMotion, _sessionActive = true, _hovered, _showDesktopPill = true, _closed, _disposed;
    private ContextMenu? _menu;
    public string? RestartExecutable { get; private set; }
    public bool Demo => _collector.Demo;
    public TrayHost(Application app, string python, bool demo)
    {
        _app = app;
        _collector = new(python, Path.Combine(AppContext.BaseDirectory, "collector", "virtual_clawdy.py"), demo);
        _updates = new(_collector.ResolvePythonAsync);
        _automaticUpdates = _updates.AutomaticEnabled;
        _updateMessage = _updates.CanUpdate ? "Updates have not been checked." : "Rebuild from the public Clawdy-Virtual checkout to enable updates.";
        _tray = new TrayIcon(); _card = new CardWindow(ActionLauncher.LaunchAsync);
        _desktopPill = new DesktopPillWindow(() => ShowCard(false));
        _reducedMotion = !SystemParameters.ClientAreaAnimation;
        _card.SetReducedMotion(_reducedMotion);
        _desktopPill.SetReducedMotion(_reducedMotion);
        SystemParameters.StaticPropertyChanged += SystemPreferenceChanged;
        _card.EnableExactChatActions(ActionLauncher.HasProtocol("codex"));
        _card.AutoOpenRequested += (_, _) =>
        {
            if (!_sessionActive || !TrayIcon.MayAutomaticallyNotify()) return;
            if (_menu?.IsOpen == true) _card.SuspendPresentation();
            else ShowCard(false);
        };
        _tray.Hovered += () => SetHover(true);
        _tray.Selected += ShowCard;
        _tray.ContextRequested += OpenMenu;
        _card.RightClicked += () => OpenMenu();
        _tray.SessionActiveChanged += active =>
        {
            _sessionActive = active;
            _snapshot = StatusSnapshot.Offline() with { Demo = _collector.Demo };
            _received = Stopwatch.GetTimestamp(); _collector.TakeLatest();
            _card.SuspendPresentation(); _hovered = false;
            if (active) { _collector.Retry(); RestorePendingCard(); }
        };
        _tray.PlacementChanged += () => { if (_card.IsVisible && _sessionActive) ShowCard(false); };
        _tick = new DispatcherTimer(DispatcherPriority.Background) { Interval = TimeSpan.FromMilliseconds(60) };
        _tick.Tick += (_, _) => Tick();
        _desktopPill.Show();
    }
    public void Start() { _collector.Start(); _tick.Start(); Tick(); }
    private void Tick()
    {
        if (_closed) return;
        var latest = _collector.TakeLatest();
        if (latest is not null && latest.Generation == _collector.Generation
            && latest.Snapshot.Demo == _collector.Demo && _sessionActive)
        { _snapshot = latest.Snapshot; _received = latest.ReceivedTicks; }
        var now = Stopwatch.GetTimestamp();
        var presented = SnapshotFreshness.Present(_snapshot, Stopwatch.GetElapsedTime(_received, now).TotalSeconds);
        if (!_sessionActive) presented = StatusSnapshot.Offline() with { Demo = _collector.Demo };
        // Never dispatch historical snapshots or terminal action requests to an app.
        if (_displayed is null || !SamePresentation(_displayed, presented) || _card.HasDeferredAttention)
        { _displayed = presented; _card.Update(presented); }
        var nowTicks = Stopwatch.GetTimestamp();
        _finishTracker.Update(presented, nowTicks);
        var blinkState = _finishTracker.GetBlinkState(nowTicks);
        var second = (long)(now / (double)Stopwatch.Frequency);
        _tray.Update(presented, blinkState, _reducedMotion, second);
        if (_showDesktopPill) _desktopPill.Update(presented, blinkState, second);
        var placement = _tray.Placement();
        var hover = _sessionActive && _menu?.IsOpen != true && _tray.IsPointerOver(placement.PhysicalAnchor);
        if (hover != _hovered) SetHover(hover);
        if (_sessionActive && _automaticUpdates && _updates.CanUpdate && _updateWork is null
            && _updateReply?.State != UpdateState.Ready && DateTimeOffset.UtcNow >= _nextAutomaticCheck)
            _ = UpdateAsync(stage: false, automatic: true);
        // Collector liveness is supervised off-dispatcher, even if UI stalls.
    }
    private static bool SamePresentation(StatusSnapshot a, StatusSnapshot b) =>
        a.State == b.State && a.WorkingCount == b.WorkingCount && a.Demo == b.Demo && a.Phrase == b.Phrase
        && a.QuestionPending == b.QuestionPending && a.Confidence == b.Confidence && a.Providers.SequenceEqual(b.Providers)
        && a.AttentionProviders.SequenceEqual(b.AttentionProviders) && a.AttentionChats.SequenceEqual(b.AttentionChats);
    private void SystemPreferenceChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs args)
    {
        if (_closed) return;
        _reducedMotion = _manualReducedMotion || !SystemParameters.ClientAreaAnimation;
        _card.SetReducedMotion(_reducedMotion);
        _desktopPill.SetReducedMotion(_reducedMotion);
    }
    private void SetHover(bool hovered)
    {
        if (_closed || !_sessionActive || (hovered && _menu?.IsOpen == true)) return;
        _hovered = hovered;
        var placement = _tray.Placement();
        _card.WorkArea = placement.WorkArea;
        _card.SetAnchorHover(placement.Anchor, hovered);
    }
    private void ShowCard(bool keyboard)
    {
        if (_closed || !_sessionActive) return;
        var placement = _tray.Placement();
        _card.WorkArea = placement.WorkArea;
        _card.ShowAt(placement.Anchor, keyboard);
    }
    private void SetMode(bool demo)
    {
        _card.ResetEpisode(); _snapshot = StatusSnapshot.Offline() with { Demo = demo };
        _received = Stopwatch.GetTimestamp(); _collector.TakeLatest(); _collector.Retry(demo); Tick();
    }
    private void OpenMenu()
    {
        if (_closed) return;
        _card.SuspendPresentation();
        _menu?.SetCurrentValue(ContextMenu.IsOpenProperty, false);
        var menu = new ContextMenu();
        MenuItem Add(string title, Action callback, bool? check = null)
        {
            var item = new MenuItem { Header = title, IsCheckable = check.HasValue, IsChecked = check ?? false };
            item.Click += (_, _) => callback(); menu.Items.Add(item);
            return item;
        }
        menu.Items.Add(new MenuItem { Header = "Virtual Clawdy · private Windows prototype", IsEnabled = false });
        Add("Show status", () => ShowCard(true));
        Add("Floating desktop widget", () =>
        {
            _showDesktopPill = !_showDesktopPill;
            if (_showDesktopPill) _desktopPill.Show();
            else _desktopPill.Hide();
        }, _showDesktopPill);
        Add("Observe existing local bridge", () => SetMode(false), !_collector.Demo);
        Add("Demo · simulated activity", () => SetMode(true), _collector.Demo);
        menu.Items.Add(new Separator());
        Add("Reduce motion", () => { _manualReducedMotion = !_manualReducedMotion; SystemPreferenceChanged(null, new(null)); Tick(); }, _reducedMotion);
        Add("Retry status collector", () => _collector.Retry());
        menu.Items.Add(new MenuItem { Header = "No hook, device or startup installation", IsEnabled = false });
        menu.Items.Add(new Separator());
        _checkUpdateItem = Add("Check for Updates", () => _ = UpdateAsync(stage: false));
        _automaticUpdateItem = Add("Automatic Updates", ToggleAutomaticUpdates, _automaticUpdates);
        _stageUpdateItem = Add("Prepare Update", () => _ = UpdateAsync(stage: true));
        _restartUpdateItem = Add("Restart to Update", RestartForUpdate);
        _updateStatusItem = new MenuItem { IsEnabled = false };
        menu.Items.Add(_updateStatusItem);
        RefreshUpdateMenu();
        menu.Items.Add(new Separator()); Add("Quit Virtual Clawdy", () => _app.Shutdown());
        var placement = _tray.Placement();
        menu.Placement = PlacementMode.AbsolutePoint;
        menu.HorizontalOffset = placement.Anchor.Left;
        menu.VerticalOffset = placement.Anchor.Top;
        menu.Closed += (_, _) =>
        {
            if (ReferenceEquals(_menu, menu)) { _menu = null; RestorePendingCard(); }
        };
        _menu = menu; _tray.PrepareContextMenu(); menu.IsOpen = true;
    }
    private void RefreshUpdateMenu()
    {
        if (_updateStatusItem is null) return;
        var ready = _updateReply?.State == UpdateState.Ready;
        _updateStatusItem.Header = new TextBlock { Text = _updateMessage, TextWrapping = TextWrapping.Wrap, MaxWidth = 320 };
        _checkUpdateItem!.IsEnabled = _updates.CanUpdate && _updateWork is null && !ready;
        _automaticUpdateItem!.IsChecked = _automaticUpdates;
        _automaticUpdateItem.IsEnabled = _updates.CanUpdate || _automaticUpdates;
        _stageUpdateItem!.Visibility = _updateReply?.State == UpdateState.Available ? Visibility.Visible : Visibility.Collapsed;
        _stageUpdateItem.IsEnabled = _updateWork is null;
        _restartUpdateItem!.Visibility = ready ? Visibility.Visible : Visibility.Collapsed;
    }
    private void ToggleAutomaticUpdates()
    {
        var enabled = !_automaticUpdates;
        if (_updates.SetAutomatic(enabled))
        {
            _automaticUpdates = enabled;
            _nextAutomaticCheck = DateTimeOffset.MinValue;
            if (!enabled) _automaticUpdateCancellation?.Cancel();
            if (_updateWork is null && _updateReply?.State != UpdateState.Ready)
                _updateMessage = enabled ? "Automatic updates on. Prepared updates open on the next launch." : "Automatic updates off.";
        }
        else _updateMessage = "Clawdy could not save the automatic update setting.";
        RefreshUpdateMenu();
    }
    private async Task UpdateAsync(bool stage, bool automatic = false)
    {
        if (_closed || _updateWork is not null || !_updates.CanUpdate || _updateReply?.State == UpdateState.Ready) return;
        _nextAutomaticCheck = DateTimeOffset.UtcNow.AddHours(6);
        using var automaticCancellation = automatic ? CancellationTokenSource.CreateLinkedTokenSource(_updateLifetime.Token) : null;
        _automaticUpdateCancellation = automaticCancellation;
        var token = automaticCancellation?.Token ?? _updateLifetime.Token;
        try
        {
            var result = await StartUpdateWork(stage, token);
            if (_closed) return;
            if (automatic && !token.IsCancellationRequested && result.State == UpdateState.Available)
                result = await StartUpdateWork(stage: true, token);
            if (_closed) return;
            if (token.IsCancellationRequested) _updateMessage = "Automatic update cancelled.";
            else { _updateReply = result; _updateMessage = result.Message; }
        }
        finally
        {
            _automaticUpdateCancellation = null;
            _updateWork = null;
            if (!_closed) RefreshUpdateMenu();
        }
    }
    private Task<UpdateReply> StartUpdateWork(bool stage, CancellationToken token)
    {
        _updateMessage = stage ? "Preparing an update in the background…" : "Checking for updates…";
        _updateWork = Task.Run(() => _updates.RunAsync(stage, token));
        RefreshUpdateMenu();
        return _updateWork;
    }
    private void RestartForUpdate()
    {
        if (_closed || _updateWork is not null || _updateReply?.State != UpdateState.Ready) return;
        var path = _updateReply.Path;
        if (path is null || !File.Exists(path))
        {
            _updateReply = null;
            _updateMessage = "The prepared update is missing. Check for updates again.";
            RefreshUpdateMenu();
            return;
        }
        RestartExecutable = path;
        _app.Shutdown();
    }
    private void RestorePendingCard()
    {
        if (!_closed && _sessionActive && _menu?.IsOpen != true && _card.HasPendingAttention) ShowCard(false);
    }
    public void CloseUi()
    {
        if (_closed) return; _closed = true;
        _updateLifetime.Cancel();
        SystemParameters.StaticPropertyChanged -= SystemPreferenceChanged;
        _tick.Stop(); if (_menu is not null) _menu.IsOpen = false;
        _desktopPill.Close();
        _card.Shutdown(); _tray.Dispose();
    }
    public async ValueTask DisposeAsync()
    {
        if (_disposed) return; _disposed = true;
        try { CloseUi(); }
        finally
        {
            try { await Task.WhenAll(_collector.DisposeAsync().AsTask(), _updateWork ?? Task.CompletedTask).ConfigureAwait(false); }
            finally { _automaticUpdateCancellation?.Dispose(); _updateLifetime.Dispose(); }
        }
    }
}
