using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Clawdy.Windows.Core;
using Clawdy.Windows.UI;

namespace Clawdy.Windows.UiChecks;

// Isolated Windows-only smoke fixtures. Never creates a host, collector, tray,
// registry reader or real action launcher. This is not human UX acceptance.
internal static class Program
{
    private const string FirstId = "11111111-2222-4333-8444-555555555555";
    private const string SecondId = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
    private static readonly List<CardWindow> Owned = [];
    private static readonly List<TaskCompletionSource<bool>> Pending = [];
    private static Rect _area, _anchor;

    [STAThread]
    private static int Main()
    {
        if (!OperatingSystem.IsWindows()) return 2;
        // A stalled dispatcher must not hang CI. This exits only this fixture.
        using var watchdog = new System.Threading.Timer(_ =>
        {
            Console.Error.WriteLine("FAIL: Windows card fixture exceeded its 30-second deadline.");
            Environment.Exit(1);
        }, null, TimeSpan.FromSeconds(30), System.Threading.Timeout.InfiniteTimeSpan);
        var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        app.Startup += async (_, _) =>
        {
            var result = 0;
            try
            {
                _area = SystemParameters.WorkArea;
                if (_area.Width < 400 || _area.Height < 250) _area = new Rect(0, 0, 1024, 768);
                _anchor = new Rect(_area.Right - 140, _area.Bottom - 12, 100, 12);
                await CheckDeniedAutomaticOpen();
                await CheckHoverAndRender();
                await CheckAllowedGateRetentionAndDemo();
                await CheckActionAdmissionAndStaleCompletion();
                Console.WriteLine("PASS: isolated Windows WPF card fixtures. No provider, collector, registry or hardware action ran.");
            }
            catch (Exception error)
            {
                result = 1;
                Console.Error.WriteLine($"FAIL: {error.GetType().Name}: {error.Message}");
            }
            finally
            {
                foreach (var card in Owned) { card.Shutdown(); card.Shutdown(); }
                foreach (var pending in Pending) pending.TrySetCanceled();
                app.Shutdown(result);
            }
        };
        return app.Run();
    }

    private static StatusSnapshot Red(string thread = FirstId, string state = "attention") =>
        new(state, 3, ["claude"], false, "Fixture request", "reported", ["codex"], [new AttentionChat("codex", thread)]);
    private static StatusSnapshot Ready => new("ready", 0, [], false, "Your next move", "reported", [], []);
    private static void Check(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
    private static async Task Pump(int milliseconds = 40) => await Task.Delay(milliseconds);
    private static T Control<T>(CardWindow card, string name) where T : class =>
        card.FindName(name) as T ?? throw new InvalidOperationException("Missing named card control: " + name);
    private static Button[] Buttons(CardWindow card) => Control<StackPanel>(card, "ActionRow").Children.OfType<Button>().ToArray();
    private static CardWindow Card(Func<CardAction, Task<bool>>? launch = null)
    {
        var card = new CardWindow(launch ?? (_ => throw new InvalidOperationException("Unexpected fake action"))) { WorkArea = _area };
        card.SetReducedMotion(true); card.EnableExactChatActions(true); Owned.Add(card); return card;
    }
    private static void Click(Button button) => button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

    private static async Task CheckDeniedAutomaticOpen()
    {
        var card = Card(); int requests = 0;
        card.AutoOpenRequested += (_, _) => requests++; // Simulated quiet-time denial.
        card.SetAnchorHover(_anchor, false); // Cache a valid tray anchor without entering it.
        card.Update(Red()); await Pump();
        Check(requests == 1 && !card.IsVisible, "Known anchor bypassed the host's denied automatic request");
        card.Update(Red() with { WorkingCount = 4, Phrase = "Another fixture" });
        card.Update(Red(SecondId)); card.Update(StatusSnapshot.Offline()); card.Update(Red());
        await Pump();
        Check(requests == 1 && !card.IsVisible, "Denied episode reopened after report/route/reconnect churn");
        card.ShowAt(_anchor, false); await Pump();
        Check(card.IsVisible, "Explicit user opening was blocked by notification suppression");
        card.Dismiss(); card.Shutdown(); card.Shutdown();
        Console.WriteLine("PASS: known-anchor quiet-time denial stays consumed; explicit user opening is allowed.");
    }

    private static async Task CheckHoverAndRender()
    {
        var card = Card(); card.Update(Ready);
        card.SetAnchorHover(_anchor, true); card.SetAnchorHover(_anchor, false); await Pump(200);
        Check(!card.IsVisible, "Superseded hover dwell opened the card");
        card.SetAnchorHover(_anchor, true); await Pump(240);
        Check(card.IsVisible, "Stable synthetic hover did not open the actual card");
        card.SetAnchorHover(_anchor, false);
        card.RaiseEvent(new MouseEventArgs(Mouse.PrimaryDevice, Environment.TickCount) { RoutedEvent = Mouse.MouseEnterEvent });
        await Pump(330);
        Check(card.IsVisible, "Moving from anchor into card collapsed across the hover gap");
        var root = Control<Border>(card, "CardRoot"); root.UpdateLayout();
        var bitmap = new RenderTargetBitmap(332, 184, 96, 96, PixelFormats.Pbgra32); bitmap.Render(root);
        var pixels = new byte[332 * 184 * 4]; bitmap.CopyPixels(pixels, 332 * 4, 0);
        Check(Enumerable.Range(0, pixels.Length / 4).Any(i => pixels[i * 4 + 3] != 0), "Actual card rendered an empty bitmap");
        Check(Control<Image>(card, "ProductImage").Source is not null, "Bundled product illustration did not load");
        Check(card.Opacity == 1 && !Control<ScaleTransform>(card, "RevealScale").HasAnimatedProperties,
            "Reduced-motion presentation left active reveal animations");
        card.RaiseEvent(new MouseEventArgs(Mouse.PrimaryDevice, Environment.TickCount) { RoutedEvent = Mouse.MouseLeaveEvent });
        await Pump(450);
        Check(!card.IsVisible, "Synthetic pointer exit did not collapse a non-alert card");
        card.Shutdown();
        Console.WriteLine("PASS: real WPF construction/render/resource, hover dwell/gap/exit, and reduced-motion reveal.");
    }

    private static async Task CheckAllowedGateRetentionAndDemo()
    {
        var card = Card(); int requests = 0;
        card.AutoOpenRequested += (_, _) => { requests++; card.ShowAt(_anchor, false); };
        card.Update(Red()); await Pump();
        Check(requests == 1 && card.IsVisible, "Allowed synchronous host gate did not show the card");
        var original = Buttons(card).Single();
        card.Update(Ready); await Pump();
        Check(card.IsVisible && ReferenceEquals(original, Buttons(card).Single()) && original.Content?.ToString() == "Open chat",
            "Immediate B-to-G removed the retained exact-chat control");
        Check(Control<TextBlock>(card, "FooterText").Text == "Recent request · status changed"
              && Control<TextBlock>(card, "SummaryText").Text == "0 WIP", "Recent card misrepresented latest status or WIP");
        card.Update(Ready with { Demo = true, Confidence = "demo" }); await Pump();
        Check(Buttons(card).Length == 0, "Demo carried a retained live action");
        card.ShowAt(_anchor, true); await Pump();
        var source = PresentationSource.FromVisual(card) ?? throw new InvalidOperationException("Keyboard fixture has no presentation source");
        var escape = new KeyEventArgs(Keyboard.PrimaryDevice, source, Environment.TickCount, Key.Escape)
            { RoutedEvent = Keyboard.PreviewKeyDownEvent };
        card.RaiseEvent(escape); await Pump();
        Check(escape.Handled && !card.IsVisible, "Card Escape handler did not dismiss a keyboard presentation");
        card.Shutdown();
        Console.WriteLine("PASS: synchronous host approval, retained B-to-G action, honest note/latest WIP, Demo guard and Escape handler.");
    }

    private static async Task CheckActionAdmissionAndStaleCompletion()
    {
        int launches = 0; var queue = new Queue<TaskCompletionSource<bool>>();
        var card = Card(_ =>
        {
            launches++;
            var pending = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            queue.Enqueue(pending); Pending.Add(pending); return pending.Task;
        });
        card.AutoOpenRequested += (_, _) => card.ShowAt(_anchor, false);
        card.Update(Red()); await Pump();
        var first = Buttons(card).Single(); Click(first); Click(first);
        Check(launches == 1 && Buttons(card).All(b => !b.IsEnabled), "Rapid synthetic clicks admitted duplicate host launches");
        queue.Dequeue().SetResult(false); await Pump();
        Check(Buttons(card).All(b => b.IsEnabled) && Control<TextBlock>(card, "HeadingText").Text == "Couldn’t open chat",
            "Failed fake launch did not re-enable controls and show failure");
        card.Update(Red() with { WorkingCount = 4, Phrase = "Changed fixture" });
        Check(Control<TextBlock>(card, "HeadingText").Text == "Couldn’t open chat", "Report churn erased failure feedback");
        Click(Buttons(card).Single());
        card.Update(Red(SecondId, "error"));
        Check(ReferenceEquals(first, Buttons(card).Single())
              && Control<TextBlock>(card, "FooterText").Text == "Recent request · status changed",
            "A later source replaced the original pending target");
        queue.Dequeue().SetResult(true); await Pump();
        Check(!card.IsVisible, "Successful launch did not acknowledge the held alert");
        card.Update(Red(SecondId, "error")); await Pump();
        Check(card.IsVisible && Control<TextBlock>(card, "HeadingText").Text == "Something needs a look",
            "Latest deferred alert was silently acknowledged with the first");
        card.SuspendPresentation(); await Pump();
        Check(!card.IsVisible, "Temporary suspension left the card visible");
        card.ShowAt(_anchor, false); await Pump();
        Check(Buttons(card).Single().Content?.ToString() == "Open chat", "Suspension lost the pending target");
        Click(Buttons(card).Single());
        queue.Dequeue().SetException(new InvalidOperationException("Synthetic launcher failure")); await Pump();
        Check(Buttons(card).All(b => b.IsEnabled), "Exceptional fake completion left controls disabled");
        Click(Buttons(card).Single()); card.Dismiss();
        card.Update(Ready); card.Update(Red());
        queue.Dequeue().SetResult(true); await Pump();
        Check(card.IsVisible && Buttons(card).All(b => b.IsEnabled), "Pre-dismiss completion changed a newly presented episode");
        card.Shutdown();
        Console.WriteLine("PASS: single-flight fake launcher, final re-enable, failure/exception paths and stale completion guards.");
    }
}
