using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Clawdy.Windows.Core;

namespace Clawdy.Windows.Native;

public readonly record struct TrayPlacement(Rect Anchor, Rect WorkArea, Rect PhysicalAnchor);

/// <summary>Owns one GUID notification icon and a hidden top-level message window.</summary>
public sealed class TrayIcon : IDisposable
{
    private const int Callback = 0x8000 + 41;
    private readonly HwndSource _window;
    private readonly IntPtr _handle;
    private readonly uint _taskbarCreated = Api.RegisterWindowMessage("TaskbarCreated");
    private readonly Guid _identity = new("a62c83b0-4278-43e2-9a97-2896327a0b36");
    private IntPtr _icon;
    private bool _registered, _disposed;
    private bool _placing;
    private string _signature = "", _tip = "Virtual Clawdy";
    private double _nextRetry;
    private int _retry;
    public event Action? Hovered;
    public event Action<bool>? Selected;
    public event Action? ContextRequested;
    public event Action<bool>? SessionActiveChanged;
    public event Action? PlacementChanged;

    public TrayIcon()
    {
        _window = new HwndSource(new HwndSourceParameters("VirtualClawdy private tray host")
        { Width = 0, Height = 0, WindowStyle = unchecked((int)0x80000000) });
        _handle = _window.Handle;
        _window.AddHook(WindowMessage);
        Api.WTSRegisterSessionNotification(_window.Handle, 0);
    }

    public void Update(StatusSnapshot value, BlinkState finishBlink, bool reduceMotion, long second)
    {
        if (_disposed) return;
        var blink = value.State == "attention" && !reduceMotion && second % 2 != 0;
        var signature = $"{value.State}:{value.WorkingCount}:{blink}:{finishBlink.IsBlinking}:{finishBlink.GreenPhaseOn}:{finishBlink.KeepAmberOn}:{finishBlink.AllFinished}";
        var names = string.Join(", ", value.Providers.Select(Name));
        var tip = $"Clawdy {(value.Demo ? "DEMO" : "reported")}: {value.State}. {value.WorkingCount} WIP. {names}";
        if (!value.Demo) tip += ". Session liveness unconfirmed.";
        tip = tip[..Math.Min(127, tip.Length)];
        if (_signature != signature)
        {
            var icon = Draw(value, finishBlink, blink);
            var old = _icon; _icon = icon; _signature = signature;
            _tip = tip; ModifyOrAdd();
            if (old != IntPtr.Zero) Api.DestroyIcon(old);
        }
        else if (_tip != tip) { _tip = tip; ModifyOrAdd(); }
        else if (!_registered && MonotonicSeconds() >= _nextRetry) ModifyOrAdd();
    }
    private static string Name(string provider) => provider switch
    { "codex" => "Codex", "claude" => "Claude Code", "gemini" => "Gemini CLI", "cursor" => "Cursor", _ => "Other" };

    private Api.NotifyData Data() => new()
    {
        Size = (uint)Marshal.SizeOf<Api.NotifyData>(), Window = _handle, Id = 1,
        Flags = 1 | 2 | 4 | 0x20, CallbackMessage = Callback, Icon = _icon,
        Tip = _tip, Info = "", InfoTitle = "", Guid = _identity
    };
    private void ModifyOrAdd()
    {
        var data = Data();
        if (_registered)
        {
            if (Api.Shell_NotifyIcon(1, ref data)) return;
            _registered = false;
        }
        if (MonotonicSeconds() < _nextRetry) return;
        _registered = Api.Shell_NotifyIcon(0, ref data);
        if (_registered)
        {
            data.TimeoutOrVersion = 4; Api.Shell_NotifyIcon(4, ref data);
            _retry = 0; _nextRetry = 0;
        }
        else _nextRetry = MonotonicSeconds() + Math.Min(30, Math.Pow(2, Math.Min(++_retry, 5)));
    }
    private static double MonotonicSeconds() => Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
    private IntPtr WindowMessage(IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if ((uint)message == _taskbarCreated)
        { _registered = false; _nextRetry = 0; ModifyOrAdd(); PlacementChanged?.Invoke(); }
        else if (message == Callback)
        {
            var kind = (int)(lParam.ToInt64() & 0xffff);
            if (kind is 0x200 or 0x406) Hovered?.Invoke();
            else if (kind is 0x400 or 0x202) Selected?.Invoke(false);
            else if (kind == 0x401) Selected?.Invoke(true);
            else if (kind is 0x7b or 0x205) ContextRequested?.Invoke();
            handled = true;
        }
        else if (message is 0x7e or 0x2e0) { if (!_placing) PlacementChanged?.Invoke(); }
        else if (message == 0x218)
        {
            if (wParam.ToInt64() == 4) SessionActiveChanged?.Invoke(false);
            else if (wParam.ToInt64() is 7 or 18) SessionActiveChanged?.Invoke(true);
        }
        else if (message == 0x2b1)
        {
            if (wParam.ToInt64() == 7) SessionActiveChanged?.Invoke(false);
            else if (wParam.ToInt64() == 8) SessionActiveChanged?.Invoke(true);
        }
        return IntPtr.Zero;
    }

    public TrayPlacement Placement()
    {
        var id = new Api.NotifyIdentifier { Size = (uint)Marshal.SizeOf<Api.NotifyIdentifier>(), Window = _handle, Id = 1, Guid = _identity };
        Api.Rect anchor;
        if (Api.Shell_NotifyIconGetRect(ref id, out anchor) != 0)
        {
            Api.GetCursorPos(out var pointer);
            anchor = new() { Left = pointer.X, Top = pointer.Y, Right = pointer.X + 1, Bottom = pointer.Y + 1 };
        }
        var monitor = Api.MonitorFromRect(ref anchor, 2);
        var info = new Api.MonitorInfo { Size = (uint)Marshal.SizeOf<Api.MonitorInfo>() };
        if (!Api.GetMonitorInfo(monitor, ref info))
            return new(SystemParameters.WorkArea, SystemParameters.WorkArea, ToRect(anchor));
        // GetDpiForMonitor is not appropriate for a per-monitor-aware thread.
        // Move only our invisible HWND (NOACTIVATE/NOZORDER), then query its DPI.
        _placing = true;
        try { Api.SetWindowPos(_handle, IntPtr.Zero, anchor.Left, anchor.Top, 1, 1, 0x10 | 0x4 | 0x200); }
        finally { _placing = false; }
        var dpi = Api.GetDpiForWindow(_handle); if (dpi == 0) dpi = 96;
        Rect Dip(Api.Rect rectangle) => new(rectangle.Left * 96.0 / dpi, rectangle.Top * 96.0 / dpi,
            Math.Max(1, rectangle.Right - rectangle.Left) * 96.0 / dpi, Math.Max(1, rectangle.Bottom - rectangle.Top) * 96.0 / dpi);
        return new(Dip(anchor), Dip(info.Work), ToRect(anchor));
    }
    private static Rect ToRect(Api.Rect rect) => new(rect.Left, rect.Top, Math.Max(1, rect.Right - rect.Left), Math.Max(1, rect.Bottom - rect.Top));
    public bool IsPointerOver(Rect physicalAnchor)
    {
        if (!Api.GetCursorPos(out var pointer)) return false;
        physicalAnchor.Inflate(2, 2); return physicalAnchor.Contains(pointer.X, pointer.Y);
    }
    public static bool MayAutomaticallyNotify() => Api.SHQueryUserNotificationState(out var state) == 0 && state == 5;
    public void PrepareContextMenu() => Api.SetForegroundWindow(_handle);

    private static IntPtr Draw(StatusSnapshot snapshot, BlinkState finishBlink, bool blinkOff)
    {
        const int size = 32;
        var visual = new DrawingVisual();
        using (var drawing = visual.RenderOpen())
        {
            Color redColor = Color.FromRgb(255, 75, 75);
            Color amberColor = Color.FromRgb(255, 185, 35);
            Color greenColor = Color.FromRgb(50, 220, 130);

            if (finishBlink.IsBlinking)
            {
                if (finishBlink.KeepAmberOn)
                {
                    // Others still working: 3-lamp pill with Amber solid ON and Green flashing!
                    var pillPen = new Pen(new SolidColorBrush(Color.FromArgb(90, 255, 255, 255)), 1.0);
                    drawing.DrawRoundedRectangle(new SolidColorBrush(Color.FromRgb(22, 25, 31)), pillPen, new Rect(0.5, 1.5, 31, 29), 8, 8);

                    // Red (inactive)
                    drawing.DrawEllipse(new SolidColorBrush(Color.FromRgb(62, 66, 75)), null, new Point(6.0, 16.0), 4.3, 4.3);

                    // Amber (solid ON)
                    var amberCenter = new Point(16.0, 16.0);
                    drawing.DrawEllipse(new SolidColorBrush(Color.FromArgb(85, amberColor.R, amberColor.G, amberColor.B)), null, amberCenter, 7.2, 7.2);
                    drawing.DrawEllipse(new SolidColorBrush(amberColor), null, amberCenter, 5.4, 5.4);
                    drawing.DrawEllipse(new SolidColorBrush(Color.FromArgb(160, 255, 255, 255)), null, new Point(amberCenter.X - 1.2, amberCenter.Y - 1.2), 1.6, 1.6);

                    // Green (blinking ON/OFF)
                    var greenCenter = new Point(26.0, 16.0);
                    if (finishBlink.GreenPhaseOn)
                    {
                        drawing.DrawEllipse(new SolidColorBrush(Color.FromArgb(85, greenColor.R, greenColor.G, greenColor.B)), null, greenCenter, 7.2, 7.2);
                        drawing.DrawEllipse(new SolidColorBrush(greenColor), null, greenCenter, 5.4, 5.4);
                        drawing.DrawEllipse(new SolidColorBrush(Color.FromArgb(160, 255, 255, 255)), null, new Point(greenCenter.X - 1.2, greenCenter.Y - 1.2), 1.6, 1.6);
                    }
                    else
                    {
                        drawing.DrawEllipse(new SolidColorBrush(Color.FromRgb(62, 66, 75)), null, greenCenter, 4.3, 4.3);
                    }
                }
                else
                {
                    // All finished: Giant Green Beacon flashes ON / OFF 3 times!
                    var center = new Point(16.0, 16.0);
                    var bezelPen = new Pen(new SolidColorBrush(Color.FromArgb(100, 255, 255, 255)), 1.2);
                    drawing.DrawEllipse(new SolidColorBrush(Color.FromRgb(18, 20, 26)), bezelPen, center, 14.8, 14.8);

                    if (finishBlink.GreenPhaseOn)
                    {
                        var haloColor = Color.FromArgb(80, greenColor.R, greenColor.G, greenColor.B);
                        drawing.DrawEllipse(new SolidColorBrush(haloColor), null, center, 13.0, 13.0);
                        drawing.DrawEllipse(new SolidColorBrush(greenColor), null, center, 10.5, 10.5);
                        drawing.DrawEllipse(new SolidColorBrush(Color.FromArgb(170, 255, 255, 255)), null, new Point(12.8, 12.8), 3.2, 3.2);
                    }
                    else
                    {
                        // Dim state during blink OFF phase
                        drawing.DrawEllipse(new SolidColorBrush(Color.FromRgb(40, 70, 50)), null, center, 8.0, 8.0);
                    }
                }
            }
            else
            {
                var active = snapshot.State switch { "attention" when !blinkOff => 0, "error" => 0, "working" => 1, "ready" => 2, _ => -1 };
                Color[] colors = [redColor, amberColor, greenColor];

                if (active >= 0)
                {
                    // SINGLE GIANT GLOWING LAMP BEACON (Fills the entire taskbar slot for maximum visibility)
                    var activeColor = colors[active];
                    var center = new Point(16.0, 16.0);

                    // Outer high-contrast dark bezel
                    var bezelPen = new Pen(new SolidColorBrush(Color.FromArgb(100, 255, 255, 255)), 1.2);
                    drawing.DrawEllipse(new SolidColorBrush(Color.FromRgb(18, 20, 26)), bezelPen, center, 14.8, 14.8);

                    // Outer radial glow halo
                    var haloColor = Color.FromArgb(80, activeColor.R, activeColor.G, activeColor.B);
                    drawing.DrawEllipse(new SolidColorBrush(haloColor), null, center, 13.0, 13.0);

                    // Main vivid traffic light lamp
                    drawing.DrawEllipse(new SolidColorBrush(activeColor), null, center, 10.5, 10.5);

                    // 3D lens specular highlight for rich hardware appearance
                    drawing.DrawEllipse(new SolidColorBrush(Color.FromArgb(170, 255, 255, 255)), null, new Point(12.8, 12.8), 3.2, 3.2);
                }
                else
                {
                    // Standby pill with 3 larger dots when idle / disconnected
                    var pillPen = new Pen(new SolidColorBrush(Color.FromArgb(70, 255, 255, 255)), 1.0);
                    drawing.DrawRoundedRectangle(new SolidColorBrush(Color.FromRgb(22, 25, 31)), pillPen, new Rect(0.5, 1.5, 31, 29), 8, 8);
                    for (var index = 0; index < 3; index++)
                    {
                        var center = new Point(6.0 + index * 10.0, 16.0);
                        drawing.DrawEllipse(new SolidColorBrush(Color.FromRgb(62, 66, 75)), null, center, 4.3, 4.3);
                    }
                }
            }
        }
        var bitmap = new RenderTargetBitmap(size, size, 96, 96, PixelFormats.Pbgra32); bitmap.Render(visual);
        var pixels = new byte[size * size * 4]; bitmap.CopyPixels(pixels, size * 4, 0);
        var header = new Api.BitmapInfo { Size = 40, Width = size, Height = -size, Planes = 1, Bits = 32 };
        var colorBitmap = Api.CreateDIBSection(IntPtr.Zero, ref header, 0, out var bits, IntPtr.Zero, 0);
        if (colorBitmap == IntPtr.Zero) throw new Win32Exception();
        IntPtr mask = IntPtr.Zero;
        try
        {
            Marshal.Copy(pixels, 0, bits, pixels.Length);
            mask = Api.CreateBitmap(size, size, 1, 1, IntPtr.Zero);
            if (mask == IntPtr.Zero) throw new Win32Exception();
            var info = new Api.IconInfo { IsIcon = true, Color = colorBitmap, Mask = mask };
            var icon = Api.CreateIconIndirect(ref info);
            if (icon == IntPtr.Zero) throw new Win32Exception();
            return icon;
        }
        finally { Api.DeleteObject(colorBitmap); if (mask != IntPtr.Zero) Api.DeleteObject(mask); }
    }

    public void Dispose()
    {
        if (_disposed) return; _disposed = true;
        var data = Data(); Api.Shell_NotifyIcon(2, ref data);
        Api.WTSUnRegisterSessionNotification(_handle);
        if (!_window.IsDisposed) { _window.RemoveHook(WindowMessage); _window.Dispose(); }
        if (_icon != IntPtr.Zero) { Api.DestroyIcon(_icon); _icon = IntPtr.Zero; }
    }

    private static class Api
    {
        [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
        [StructLayout(LayoutKind.Sequential)] public struct Point { public int X, Y; }
        [StructLayout(LayoutKind.Sequential)] public struct MonitorInfo { public uint Size; public Rect Monitor, Work; public uint Flags; }
        [StructLayout(LayoutKind.Sequential)] public struct NotifyIdentifier { public uint Size; public IntPtr Window; public uint Id; public Guid Guid; }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] public struct NotifyData
        {
            public uint Size; public IntPtr Window; public uint Id, Flags; public int CallbackMessage; public IntPtr Icon;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Tip;
            public uint State, StateMask;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string Info;
            public uint TimeoutOrVersion;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string InfoTitle;
            public uint InfoFlags; public Guid Guid; public IntPtr BalloonIcon;
        }
        [StructLayout(LayoutKind.Sequential)] public struct BitmapInfo
        { public uint Size; public int Width, Height; public ushort Planes, Bits; public uint Compression, ImageSize; public int XPels, YPels; public uint Used, Important; }
        [StructLayout(LayoutKind.Sequential)] public struct IconInfo
        { [MarshalAs(UnmanagedType.Bool)] public bool IsIcon; public uint X, Y; public IntPtr Mask, Color; }
        [DllImport("shell32.dll", CharSet = CharSet.Unicode)] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool Shell_NotifyIcon(uint command, ref NotifyData data);
        [DllImport("shell32.dll")] public static extern int Shell_NotifyIconGetRect(ref NotifyIdentifier id, out Rect rect);
        [DllImport("shell32.dll")] public static extern int SHQueryUserNotificationState(out int state);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern uint RegisterWindowMessage(string value);
        [DllImport("user32.dll")] public static extern IntPtr MonitorFromRect(ref Rect rect, uint flags);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool GetCursorPos(out Point point);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool SetForegroundWindow(IntPtr window);
        [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr window);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, uint flags);
        [DllImport("wtsapi32.dll")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool WTSRegisterSessionNotification(IntPtr window, uint flags);
        [DllImport("wtsapi32.dll")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool WTSUnRegisterSessionNotification(IntPtr window);
        [DllImport("gdi32.dll")] public static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapInfo info, uint usage, out IntPtr bits, IntPtr section, uint offset);
        [DllImport("gdi32.dll")] public static extern IntPtr CreateBitmap(int width, int height, uint planes, uint bits, IntPtr data);
        [DllImport("gdi32.dll")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool DeleteObject(IntPtr value);
        [DllImport("user32.dll")] public static extern IntPtr CreateIconIndirect(ref IconInfo info);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool DestroyIcon(IntPtr value);
    }
}
