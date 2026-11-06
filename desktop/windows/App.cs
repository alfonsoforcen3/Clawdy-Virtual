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
    [STAThread]
    private static int Main(string[] args)
    {
        if (!OperatingSystem.IsWindows()) return 2;
        bool demo = false; string python = "py";
        for (var index = 0; index < args.Length; index++)
        {
            if (args[index] == "--demo") demo = true;
            else if (args[index] == "--observe") demo = false;
            else if (args[index] == "--python" && index + 1 < args.Length) python = args[++index];
            else return 2;
        }
        // One explicit user-session instance. This never controls a physical bridge.
        using var unique = new Mutex(true, @"Local\ClawdyVirtual.PrivatePrototype.0", out var owns);
        if (!owns) return 0;
        try
        {
            var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
            var host = new TrayHost(app, python, demo);
            app.Exit += (_, _) => host.CloseUi();
            try { host.Start(); return app.Run(); }
            finally { host.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
        }
        finally { unique.ReleaseMutex(); }
    }
}

internal sealed class TrayHost : IAsyncDisposable
{
    private readonly Application _app;
    private readonly CollectorSupervisor _collector;
    private readonly TrayIcon _tray;
    private readonly CardWindow _card;
    private readonly DispatcherTimer _tick;
    private StatusSnapshot _snapshot = StatusSnapshot.Offline();
    private StatusSnapshot? _displayed;
    private long _received = Stopwatch.GetTimestamp();
    private bool _manualReducedMotion, _reducedMotion, _sessionActive = true, _hovered, _closed, _disposed;
    private ContextMenu? _menu;
    public TrayHost(Application app, string python, bool demo)
    {
        _app = app;
        _collector = new(python, Path.Combine(AppContext.BaseDirectory, "collector", "virtual_clawdy.py"), demo);
        _tray = new TrayIcon(); _card = new CardWindow(ActionLauncher.LaunchAsync);
        _reducedMotion = !SystemParameters.ClientAreaAnimation; _card.SetReducedMotion(_reducedMotion);
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
        _tray.SessionActiveChanged += active =>
        {
            _sessionActive = active;
            _snapshot = StatusSnapshot.Offline() with { Demo = _collector.Demo };
            _received = Stopwatch.GetTimestamp(); _collector.TakeLatest();
            _card.SuspendPresentation(); _hovered = false;
            if (active) { _collector.Retry(); RestorePendingCard(); }
        };
        _tray.PlacementChanged += () => { if (_card.IsVisible && _sessionActive) ShowCard(false); };
        _tick = new DispatcherTimer(DispatcherPriority.Background) { Interval = TimeSpan.FromMilliseconds(250) };
        _tick.Tick += (_, _) => Tick();
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
        _tray.Update(presented, _reducedMotion, (long)(now / (double)Stopwatch.Frequency));
        var placement = _tray.Placement();
        var hover = _sessionActive && _menu?.IsOpen != true && _tray.IsPointerOver(placement.PhysicalAnchor);
        if (hover != _hovered) SetHover(hover);
        // Collector liveness is supervised off-dispatcher, even if UI stalls.
    }
    private static bool SamePresentation(StatusSnapshot a, StatusSnapshot b) =>
        a.State == b.State && a.WorkingCount == b.WorkingCount && a.Demo == b.Demo && a.Phrase == b.Phrase
        && a.Confidence == b.Confidence && a.Providers.SequenceEqual(b.Providers)
        && a.AttentionProviders.SequenceEqual(b.AttentionProviders) && a.AttentionChats.SequenceEqual(b.AttentionChats);
    private void SystemPreferenceChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs args)
    {
        if (_closed) return;
        _reducedMotion = _manualReducedMotion || !SystemParameters.ClientAreaAnimation;
        _card.SetReducedMotion(_reducedMotion);
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
        void Add(string title, Action callback, bool check = false)
        {
            var item = new MenuItem { Header = title, IsCheckable = check, IsChecked = check };
            item.Click += (_, _) => callback(); menu.Items.Add(item);
        }
        menu.Items.Add(new MenuItem { Header = "Virtual Clawdy · private Windows prototype", IsEnabled = false });
        Add("Show status", () => ShowCard(true));
        Add("Observe existing local bridge", () => SetMode(false), !_collector.Demo);
        Add("Demo · simulated activity", () => SetMode(true), _collector.Demo);
        menu.Items.Add(new Separator());
        Add("Reduce motion", () => { _manualReducedMotion = !_manualReducedMotion; SystemPreferenceChanged(null, new(null)); Tick(); }, _reducedMotion);
        Add("Retry status collector", () => _collector.Retry());
        menu.Items.Add(new MenuItem { Header = "No hook, device or startup installation", IsEnabled = false });
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
    private void RestorePendingCard()
    {
        if (!_closed && _sessionActive && _menu?.IsOpen != true && _card.HasPendingAttention) ShowCard(false);
    }
    public void CloseUi()
    {
        if (_closed) return; _closed = true;
        SystemParameters.StaticPropertyChanged -= SystemPreferenceChanged;
        _tick.Stop(); if (_menu is not null) _menu.IsOpen = false;
        _card.Shutdown(); _tray.Dispose();
    }
    public async ValueTask DisposeAsync()
    {
        if (_disposed) return; _disposed = true;
        try { CloseUi(); }
        finally { await _collector.DisposeAsync().ConfigureAwait(false); }
    }
}
