using System.ComponentModel;
using System.Diagnostics;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Clawdy.Windows.Core;
using Button = System.Windows.Controls.Button;
using Brush = System.Windows.Media.Brush;
using Color = System.Windows.Media.Color;

namespace Clawdy.Windows.UI;

public sealed partial class CardWindow : Window
{
    private readonly AttentionPolicy _policy = new();
    private readonly Func<CardAction, Task<bool>> _launchAction;
    private readonly Stopwatch _clock = Stopwatch.StartNew();
    private readonly Dictionary<string, Button> _buttons = new();
    private readonly CardActionAdmission _admission = new();
    private static readonly ImageSource? CachedProduct = LoadProduct();
    private DispatcherTimer? _enterTimer, _exitTimer, _retentionTimer;
    private DateTimeOffset? _scheduledDeadline;
    private Rect _anchor;
    private bool _hasAnchor, _anchorHovered, _cardHovered, _keyboard, _manualReducedMotion, _closed;
    private long _presentationVersion;
    private long _hoverVersion, _deadlineVersion;
    private string? _actionFailure;
    private long _failureVersion;
    private DateTimeOffset Now => DateTimeOffset.UnixEpoch + _clock.Elapsed;
    private bool ReduceMotion => _manualReducedMotion || !SystemParameters.ClientAreaAnimation;

    public bool HasDeferredAttention => _policy.HasDeferredAttention;
    public bool HasPendingAttention => _policy.HasPendingAttention;
    public event EventHandler? AutoOpenRequested;
    public event EventHandler? Dismissed;
    public event Action? RightClicked;
    // Coordinates are screen DIPs. The host supplies the tray monitor work area
    // after converting physical NotifyIcon pixels with that monitor's DPI.
    public Rect WorkArea { get; set; } = SystemParameters.WorkArea;

    public CardWindow(Func<CardAction, Task<bool>>? launchAction = null)
    {
        InitializeComponent();
        _launchAction = launchAction ?? (_ => Task.FromResult(false));
        ProductImage.Source = CachedProduct;
        ProductFallback.Visibility = CachedProduct is null ? Visibility.Visible : Visibility.Collapsed;
        CloseButton.Click += (_, _) => Dismiss();
        MouseEnter += (_, _) => { _hoverVersion++; _cardHovered = true; Stop(ref _exitTimer); SetInteraction(); };
        MouseLeave += (_, _) => { _hoverVersion++; _cardHovered = false; SetInteraction(); ScheduleExit(); };
        MouseRightButtonUp += (_, e) => { e.Handled = true; Dismiss(); RightClicked?.Invoke(); };
        PreviewKeyDown += (_, args) => { if (args.Key == Key.Escape) { Dismiss(); args.Handled = true; } };
        Deactivated += (_, _) => { _keyboard = false; SetInteraction(); ScheduleExit(); };
        Activated += (_, _) => { _keyboard = true; SetInteraction(); };
        SystemParameters.StaticPropertyChanged += SystemPreferenceChanged;
        Closed += (_, _) => ReleaseResources();
        Render();
    }

    public void EnableExactChatActions(bool enabled)
    {
        Dispatcher.VerifyAccess(); _policy.EnableExactChatActions(enabled); Render();
    }
    public void SetReducedMotion(bool enabled)
    {
        Dispatcher.VerifyAccess(); _manualReducedMotion = enabled;
        if (ReduceMotion) FinishAnimation();
    }
    public void Update(StatusSnapshot snapshot)
    {
        Dispatcher.VerifyAccess(); if (_closed) return;
        var open = _policy.Update(snapshot, Now); Render();
        if (open)
        {
            // Every automatic expansion must pass the host's current session
            // and quiet-time gate, even after a tray anchor was cached.
            var approvalVersion = _presentationVersion;
            AutoOpenRequested?.Invoke(this, EventArgs.Empty);
            if (_presentationVersion == approvalVersion)
            {
                _policy.SuppressAutomaticOpen(preserveVisible: IsVisible);
                Render();
            }
        }
        ScheduleRetention();
        if (!_policy.Visible && IsVisible) HideCard();
    }
    public void ShowAt(Rect anchor, bool keyboard = false)
    {
        Dispatcher.VerifyAccess(); if (_closed || !Valid(anchor)) return;
        _anchor = anchor; _hasAnchor = true; _policy.Show(keyboard); Present(keyboard);
    }
    public void SetAnchorHover(Rect anchor, bool hovered)
    {
        Dispatcher.VerifyAccess(); if (_closed || !Valid(anchor)) return;
        _anchor = anchor; _hasAnchor = true;
        if (_anchorHovered == hovered) return;
        var generation = ++_hoverVersion;
        _anchorHovered = hovered; SetInteraction();
        if (hovered)
        {
            Stop(ref _exitTimer); Stop(ref _enterTimer);
            _enterTimer = Once(TimeSpan.FromMilliseconds(200), () =>
            {
                _enterTimer = null;
                if (generation == _hoverVersion && _anchorHovered) { _policy.Show(false); Present(false); }
            });
        }
        else { Stop(ref _enterTimer); ScheduleExit(); }
    }
    public void Dismiss()
    {
        Dispatcher.VerifyAccess(); if (_closed) return;
        _policy.Dismiss(); _keyboard = false; _anchorHovered = false; _cardHovered = false;
        CancelTimers(); Render(); HideCard(); Dismissed?.Invoke(this, EventArgs.Empty);
    }
    // Menus and session lock temporarily hide the presentation without acknowledging it.
    public void SuspendPresentation()
    {
        Dispatcher.VerifyAccess(); if (_closed) return;
        _keyboard = false; _anchorHovered = false; _cardHovered = false;
        SetInteraction(); CancelTimers(); HideCard();
    }
    public void ResetEpisode() { _policy.Reset(); Dismiss(); }
    public void Shutdown()
    {
        Dispatcher.VerifyAccess(); if (_closed) return;
        _policy.Reset(); ReleaseResources(); Close();
    }

    private void SetInteraction() => _policy.SetInteraction(_anchorHovered || _cardHovered, _keyboard);
    private void ScheduleExit()
    {
        Stop(ref _exitTimer);
        var generation = _hoverVersion;
        _exitTimer = Once(TimeSpan.FromMilliseconds(280), () =>
        {
            if (generation != _hoverVersion) return;
            _exitTimer = null; SetInteraction();
            if (_policy.Leave(Now)) { Render(); HideCard(); }
        });
    }
    private void ScheduleRetention()
    {
        var deadline = _policy.RetainUntil;
        if (deadline == _scheduledDeadline) return;
        Stop(ref _retentionTimer); _scheduledDeadline = deadline;
        var generation = ++_deadlineVersion;
        if (deadline is null || deadline <= Now) return;
        _retentionTimer = Once(deadline.Value - Now + TimeSpan.FromMilliseconds(10), () =>
        {
            if (generation != _deadlineVersion) return;
            _retentionTimer = null; _scheduledDeadline = null;
            SetInteraction();
            if (_policy.Expire(Now)) { Render(); HideCard(); }
        });
    }
    private void Present(bool keyboard)
    {
        if (!_hasAnchor || _closed) return;
        _presentationVersion++; _keyboard |= keyboard; SetInteraction();
        Stop(ref _enterTimer); Stop(ref _exitTimer);
        var area = Valid(WorkArea) && WorkArea.Width > 0 && WorkArea.Height > 0 ? WorkArea : SystemParameters.WorkArea;
        var width = Math.Min(324, Math.Max(1, area.Width - 16));
        var height = Math.Min(176, Math.Max(1, area.Height - 16));
        Width = width; Height = height;
        Left = Math.Clamp(_anchor.Left + _anchor.Width / 2 - width / 2, area.Left + 8, Math.Max(area.Left + 8, area.Right - width - 8));
        var above = _anchor.Top > area.Top + area.Height / 2;
        Top = Math.Clamp(above ? _anchor.Top - height - 12 : _anchor.Bottom + 12,
            area.Top + 8, Math.Max(area.Top + 8, area.Bottom - height - 8));
        ShowActivated = keyboard;
        var reveal = !IsVisible;
        if (reveal) Show();
        if (keyboard)
        {
            Activate();
            (ActionRow.Children.OfType<Button>().FirstOrDefault() ?? CloseButton).Focus();
        }
        if (reveal && !ReduceMotion)
        {
            var duration = TimeSpan.FromMilliseconds(180);
            BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, duration) { FillBehavior = FillBehavior.Stop });
            RevealScale.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(.96, 1, duration) { FillBehavior = FillBehavior.Stop });
            RevealScale.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(.96, 1, duration) { FillBehavior = FillBehavior.Stop });
        }
        else FinishAnimation();
    }
    private void HideCard()
    {
        _presentationVersion++; _keyboard = false; FinishAnimation();
        if (IsVisible) Hide();
    }
    private void FinishAnimation()
    {
        BeginAnimation(OpacityProperty, null); Opacity = 1;
        RevealScale.BeginAnimation(ScaleTransform.ScaleXProperty, null); RevealScale.ScaleX = 1;
        RevealScale.BeginAnimation(ScaleTransform.ScaleYProperty, null); RevealScale.ScaleY = 1;
    }

    private void Render()
    {
        var value = _policy.Displayed;
        HeadingText.Text = value.State switch
        {
            "attention" => "A little help?", "error" => "Something needs a look", "working" => "Little lights. Big plans.",
            "ready" => "All yours.", "idle" => "Enjoying the quiet.", "uncertain" => "Waiting for a fresh signal.", _ => "Taking a signal break."
        };
        if (_actionFailure is not null && _failureVersion == _policy.ActionVersion) HeadingText.Text = _actionFailure;
        else _actionFailure = null;
        AutomationProperties.SetName(HeadingText, HeadingText.Text);
        var labels = value.Providers.Select(ProviderName).Distinct().ToArray();
        SummaryText.Text = $"{value.WorkingCount} WIP" + (labels.Length == 0 ? "" : "  ·  " + string.Join(", ", labels));
        SummaryText.Foreground = ColorBrush(value.State switch
        { "attention" or "error" => "#FF6159", "working" => "#F4C05C", "ready" => "#63D68B", _ => "#99A3B6" });
        FooterText.Text = _policy.IsRecent ? value.State == "error" ? "Recent error · status changed" : "Recent request · status changed"
            : value.Demo ? "Demo data · no app actions" : value.Confidence == "reported"
                ? "Reported status · session liveness unconfirmed" : "Status confidence unknown";
        HintText.Text = value.Demo ? "Just a rehearsal. No app will open." : AttentionPolicy.IsRed(value.State)
            ? "Open your AI app to respond." : value.Phrase;
        HintText.Visibility = _policy.Actions.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        var desired = _policy.Actions;
        var oldOrder = ActionRow.Children.OfType<Button>().Select(b => b.Tag as string ?? string.Empty).ToArray();
        if (!oldOrder.SequenceEqual(desired.Select(a => a.Identity)))
        {
            var focused = _buttons.FirstOrDefault(pair => pair.Value.IsKeyboardFocused).Key;
            ActionRow.Children.Clear();
            foreach (var key in _buttons.Keys.Except(desired.Select(a => a.Identity)).ToArray()) _buttons.Remove(key);
            var chatCount = desired.Count(a => a.Kind == "chat"); int number = 0;
            foreach (var action in desired)
            {
                if (!_buttons.TryGetValue(action.Identity, out var button))
                {
                    button = new Button { Width = 110, Height = 28, Margin = new Thickness(0, 0, 6, 0), Tag = action.Identity };
                    button.Click += async (_, _) =>
                    {
                        var current = _policy.Actions.FirstOrDefault(candidate => candidate.Identity == button.Tag as string);
                        if (current is not null) await InvokeAction(current);
                    };
                    _buttons[action.Identity] = button;
                }
                button.Content = action.Kind == "chat" && chatCount > 1 ? "Open chat " + (++number) : action.Label;
                button.ToolTip = action.Kind == "chat" ? "Open this specific chat in ChatGPT desktop app." : action.Provider is "claude" or "gemini"
                    ? "Bring active Terminal window to front." : "Open the app and select the relevant chat.";
                AutomationProperties.SetHelpText(button, button.ToolTip?.ToString() ?? string.Empty);
                ActionRow.Children.Add(button);
            }
            if (focused is not null && (_keyboard || IsKeyboardFocusWithin)) (_buttons.GetValueOrDefault(focused) ?? CloseButton).Focus();
        }
        SetActionButtonsEnabled();
    }
    private async Task InvokeAction(CardAction action)
    {
        if (!_policy.Actions.Contains(action)
            || !_admission.TryBegin(_policy.ActionVersion, _presentationVersion, out var ticket)) return;
        SetActionButtonsEnabled();
        _actionFailure = null; Render();
        bool success;
        try { success = await _launchAction(action); } catch { success = false; }
        finally { if (_admission.Complete(ticket) && !_closed) SetActionButtonsEnabled(); }
        if (_closed || ticket.ActionVersion != _policy.ActionVersion || ticket.PresentationVersion != _presentationVersion || !_policy.Actions.Contains(action)) return;
        if (success) Dismiss();
        else
        {
            _actionFailure = action.Kind == "chat" ? "Couldn’t open chat" : "Couldn’t open the app";
            _failureVersion = _policy.ActionVersion; HeadingText.Text = _actionFailure;
            AutomationProperties.SetName(HeadingText, HeadingText.Text);
            if (!_policy.IsRecent) FooterText.Text = "Try switching to the app directly.";
        }
    }
    private void SetActionButtonsEnabled()
    {
        foreach (var button in _buttons.Values) button.IsEnabled = !_admission.Busy;
    }
    private DispatcherTimer Once(TimeSpan interval, Action action)
    {
        var timer = new DispatcherTimer(DispatcherPriority.Normal, Dispatcher) { Interval = interval > TimeSpan.Zero ? interval : TimeSpan.FromMilliseconds(1) };
        timer.Tick += (_, _) => { timer.Stop(); if (!_closed) action(); };
        timer.Start(); return timer;
    }
    private static void Stop(ref DispatcherTimer? timer) { timer?.Stop(); timer = null; }
    private void CancelTimers()
    {
        _hoverVersion++; _deadlineVersion++;
        Stop(ref _enterTimer); Stop(ref _exitTimer); Stop(ref _retentionTimer); _scheduledDeadline = null;
    }
    private void SystemPreferenceChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(SystemParameters.ClientAreaAnimation)) Dispatcher.InvokeAsync(() => { if (!_closed && ReduceMotion) FinishAnimation(); });
    }
    private void ReleaseResources()
    {
        if (_closed) return;
        _closed = true; CancelTimers(); SystemParameters.StaticPropertyChanged -= SystemPreferenceChanged;
        _policy.Reset(); _buttons.Clear(); ActionRow.Children.Clear();
    }
    private static bool Valid(Rect value) => !value.IsEmpty && value.Width >= 0 && value.Height >= 0 &&
        double.IsFinite(value.X) && double.IsFinite(value.Y) && double.IsFinite(value.Width) && double.IsFinite(value.Height);
    private static string ProviderName(string name) => name switch
    { "codex" => "Codex", "claude" => "Claude", "gemini" => "Gemini", "cursor" => "Cursor", _ => "Other" };
    private static Brush ColorBrush(string value) => new SolidColorBrush((Color)ColorConverter.ConvertFromString(value)!);
    private static ImageSource? LoadProduct()
    {
        try
        {
            var image = new BitmapImage(); image.BeginInit(); image.CacheOption = BitmapCacheOption.OnLoad;
            image.DecodePixelWidth = 216; image.UriSource = new Uri("pack://application:,,,/Assets/ClawdyProduct.png");
            image.EndInit(); image.Freeze(); return image;
        }
        catch (Exception error) when (error is System.IO.IOException or NotSupportedException or UriFormatException) { return null; }
    }
}
