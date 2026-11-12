using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using Clawdy.Windows.Core;

namespace Clawdy.Windows.UI;

/// <summary>
/// A sleek, seamless circular bubble desktop companion widget with no sharp corners,
/// dynamic background that reacts to traffic light status, and accurate AI logos.
/// </summary>
public sealed class DesktopPillWindow : Window
{
    private readonly Action _openCard;
    private readonly Border _rootBorder;
    private readonly Ellipse _redLamp;
    private readonly Ellipse _amberLamp;
    private readonly Ellipse _greenLamp;
    private readonly Border _providerBox;
    private readonly Path _providerPath;
    private readonly TextBlock _brandTitle;
    private readonly TextBlock _detailLabel;
    private bool _reducedMotion;

    private static readonly ImageSource? CachedProduct = LoadProductImage();

    // Provider Vector Geometries
    private static readonly Geometry GeminiGeom = Geometry.Parse(
        "M 16,2 C 16,9.5 9.5,16 2,16 C 9.5,16 16,22.5 16,30 C 16,22.5 22.5,16 30,16 C 22.5,16 16,9.5 16,2 Z");

    // Official OpenAI / ChatGPT / Codex knot blossom geometry
    private static readonly Geometry CodexGeom = Geometry.Parse(
        "M 13.2,20 C 12.67,20 12.16,19.9 11.68,19.7 C 11.2,19.49 10.78,19.21 10.4,18.85 C 10,18.99 9.58,19.06 9.14,19.06 C 8.43,19.06 7.76,18.88 7.16,18.53 C 6.55,18.18 6.06,17.7 5.68,17.09 C 5.32,16.48 5.14,15.8 5.14,15.06 C 5.14,14.75 5.18,14.41 5.27,14.05 C 4.84,13.65 4.51,13.2 4.28,12.69 C 4.04,12.17 3.92,11.62 3.92,11.06 C 3.92,10.48 4.05,9.93 4.29,9.39 C 4.54,8.86 4.88,8.4 5.32,8.02 C 5.76,7.62 6.28,7.35 6.87,7.2 C 6.99,6.59 7.23,6.05 7.6,5.57 C 7.99,5.08 8.46,4.69 9.01,4.42 C 9.57,4.14 10.16,4 10.79,4 C 11.32,4 11.83,4.1 12.31,4.3 C 12.79,4.51 13.21,4.79 13.59,5.15 C 13.99,5.01 14.41,4.94 14.85,4.94 C 15.57,4.94 16.23,5.12 16.84,5.47 C 17.44,5.82 17.93,6.3 18.29,6.91 C 18.67,7.52 18.85,8.2 18.85,8.94 C 18.85,9.25 18.81,9.59 18.72,9.95 C 19.15,10.35 19.48,10.81 19.72,11.33 C 19.95,11.84 20.07,12.38 20.07,12.94 C 20.07,13.52 19.95,14.07 19.7,14.61 C 19.45,15.14 19.11,15.61 18.66,16 C 18.22,16.38 17.71,16.65 17.12,16.8 C 17.01,17.41 16.76,17.95 16.37,18.43 C 16,18.92 15.53,19.31 14.98,19.58 C 14.43,19.86 13.83,20 13.2,20 Z " +
        "M 9.28,17.82 C 9.79,17.82 10.23,17.71 10.61,17.49 L 13.51,15.82 C 13.63,15.75 13.68,15.65 13.68,15.52 V 14.4 L 10.12,16.45 C 9.79,16.64 9.45,16.64 9.12,16.45 L 6.37,14.86 C 6.37,14.93 6.37,14.99 6.37,15.06 C 6.37,15.51 6.49,15.99 6.74,16.43 C 7,16.86 7.35,17.19 7.8,17.44 C 8.24,17.7 8.74,17.82 9.28,17.82 Z " +
        "M 9.43,15.22 C 9.55,15.27 9.66,15.27 9.78,15.22 L 10.76,14.67 L 7.2,12.59 C 6.87,12.41 6.71,12.12 6.71,11.73 V 8.58 C 6.24,8.82 5.87,9.17 5.59,9.62 C 5.32,10.05 5.19,10.54 5.19,11.07 C 5.19,11.57 5.31,12.05 5.56,12.51 C 5.81,12.96 6.14,13.3 6.55,13.54 L 9.43,15.22 Z " +
        "M 13.19,18.75 C 13.73,18.75 14.22,18.63 14.66,18.38 C 15.1,18.14 15.44,17.8 15.68,17.38 C 15.94,16.95 16.07,16.47 16.07,15.95 V 12.62 C 16.07,12.49 16.01,12.38 15.89,12.32 L 14.92,11.73 V 15.86 C 14.92,16.25 14.75,16.54 14.42,16.72 L 11.68,18.3 C 12.15,18.6 12.65,18.75 13.19,18.75 Z " +
        "M 13.68,13.01 V 10.99 L 12,10.03 L 10.31,10.99 V 13.01 L 12,13.97 L 13.68,13.01 Z " +
        "M 9.08,8.14 C 9.08,7.75 9.24,7.46 9.57,7.28 L 12.31,5.7 C 11.84,5.4 11.34,5.25 10.8,5.25 C 10.27,5.25 9.79,5.37 9.35,5.62 C 8.91,5.86 8.56,6.2 8.31,6.62 C 8.06,7.05 7.94,7.53 7.94,8.05 V 11.36 C 7.94,11.49 8,11.59 8.12,11.68 L 9.08,12.27 V 8.14 Z " +
        "M 17.3,15.42 C 17.76,15.19 18.12,14.85 18.39,14.4 C 18.67,13.95 18.8,13.46 18.8,12.93 C 18.8,12.43 18.68,11.95 18.42,11.5 C 18.17,11.05 17.85,10.7 17.44,10.46 L 14.56,8.8 C 14.44,8.74 14.33,8.74 14.21,8.8 L 13.24,9.33 L 16.8,11.42 C 16.97,11.52 17.1,11.64 17.17,11.78 C 17.26,11.9 17.3,12.07 17.3,12.27 V 15.42 Z " +
        "M 13.88,7.52 C 14.21,7.32 14.54,7.32 14.87,7.52 L 17.62,9.14 C 17.62,9.1 17.62,9.07 17.62,9.04 C 17.62,8.55 17.5,8.09 17.25,7.65 C 17.02,7.2 16.68,6.84 16.23,6.58 C 15.79,6.31 15.28,6.18 14.71,6.18 C 14.21,6.18 13.76,6.29 13.38,6.51 L 10.48,8.18 C 10.37,8.25 10.31,8.35 10.31,8.48 V 9.6 L 13.88,7.52 Z");

    private static readonly Geometry ClaudeGeom = Geometry.Parse(
        "M 16,3 L 18.2,11.5 L 26.5,8.5 L 21.5,15 L 29,18 L 21.5,21 L 26.5,27.5 L 18.2,24.5 L 16,33 L 13.8,24.5 L 5.5,27.5 L 10.5,21 L 3,18 L 10.5,15 L 5.5,8.5 L 13.8,11.5 Z");
    private static readonly Geometry CursorGeom = Geometry.Parse(
        "M 16,4 L 27,10 L 27,22 L 16,28 L 5,22 L 5,10 Z M 16,4 L 16,28 M 5,10 L 27,22 M 27,10 L 5,22");
    private static readonly Geometry ReadyGeom = Geometry.Parse(
        "M 7,16 L 13,22 L 25,9");

    public DesktopPillWindow(Action openCard)
    {
        _openCard = openCard;

        Title = "Virtual Clawdy Bubble";
        // Slightly larger window so the drop shadow never clips at the edges
        Width = 362;
        Height = 84;
        WindowStyle = WindowStyle.None;
        AllowsTransparency = true;
        Background = Brushes.Transparent;
        ResizeMode = ResizeMode.NoResize;
        Topmost = true;
        ShowInTaskbar = false;
        ShowActivated = false;
        UseLayoutRounding = true;
        SnapsToDevicePixels = true;

        var workArea = SystemParameters.WorkArea;
        Left = Math.Max(24, workArea.Right - Width - 28);
        Top = Math.Max(24, workArea.Top + 28);

        // PURE CIRCULAR BUBBLE: Height=68, CornerRadius=34 (strictly circular ends, 0 sharp corners)
        _rootBorder = new Border
        {
            Width = 346,
            Height = 68,
            CornerRadius = new CornerRadius(34),
            Margin = new Thickness(8),
            BorderThickness = new Thickness(1.4),
            Cursor = Cursors.SizeAll,
            Effect = new DropShadowEffect
            {
                BlurRadius = 20,
                ShadowDepth = 3,
                Opacity = 0.55,
                Color = Colors.Black
            }
        };

        // Initialize with subtle idle theme
        UpdateBubbleTheme("idle", new BlinkState());

        _rootBorder.MouseLeftButtonDown += (_, e) =>
        {
            if (e.ClickCount == 2)
            {
                _openCard();
            }
            else if (e.ButtonState == MouseButtonState.Pressed)
            {
                DragMove();
            }
        };

        var mainGrid = new Grid { Margin = new Thickness(10, 6, 12, 6) };
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); // 0: Mascot avatar
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); // 1: Active AI provider logo
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }); // 2: Text channel
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); // 3: Traffic Lights

        // 1. OFFICIAL CLAWDY MASCOT (Background-less, floats natively on the glass)
        var avatarBorder = new Border
        {
            Width = 46,
            Height = 46,
            Background = Brushes.Transparent,
            Cursor = Cursors.Hand,
            Margin = new Thickness(2, 0, 6, 0)
        };
        avatarBorder.MouseLeftButtonDown += (s, e) => { e.Handled = true; _openCard(); };

        var avatarGrid = new Grid();
        if (CachedProduct != null)
        {
            var clawdyImg = new Image
            {
                Source = CachedProduct,
                Stretch = Stretch.Uniform
            };
            RenderOptions.SetBitmapScalingMode(clawdyImg, BitmapScalingMode.HighQuality);
            avatarGrid.Children.Add(clawdyImg);
        }
        else
        {
            avatarGrid.Children.Add(new TextBlock
            {
                Text = "C",
                FontSize = 24,
                FontWeight = FontWeights.Black,
                Foreground = new SolidColorBrush(Color.FromRgb(225, 148, 109)),
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center
            });
        }
        avatarBorder.Child = avatarGrid;
        Grid.SetColumn(avatarBorder, 0);
        mainGrid.Children.Add(avatarBorder);

        // 2. WORKING AI PROVIDER BADGE (Background-less glowing vector logo)
        _providerBox = new Border
        {
            Width = 28,
            Height = 28,
            Background = Brushes.Transparent,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, 8, 0),
            Cursor = Cursors.Hand
        };
        _providerBox.MouseLeftButtonDown += (s, e) => { e.Handled = true; _openCard(); };

        var viewbox = new Viewbox
        {
            Width = 22,
            Height = 22,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center
        };
        _providerPath = new Path
        {
            Data = GeminiGeom,
            Fill = new SolidColorBrush(Color.FromRgb(78, 136, 245)),
            Stretch = Stretch.Uniform
        };
        viewbox.Child = _providerPath;
        _providerBox.Child = viewbox;

        Grid.SetColumn(_providerBox, 1);
        mainGrid.Children.Add(_providerBox);

        // 3. BRAND & STATUS TEXT PANEL (Spacious, zero overlap with traffic lights)
        var textPanel = new StackPanel
        {
            VerticalAlignment = VerticalAlignment.Center,
            Cursor = Cursors.Hand,
            Margin = new Thickness(0, 0, 8, 0)
        };
        textPanel.MouseLeftButtonDown += (s, e) => { e.Handled = true; _openCard(); };

        _brandTitle = new TextBlock
        {
            Text = "Clawdy",
            FontSize = 13,
            FontWeight = FontWeights.Bold,
            Foreground = new SolidColorBrush(Color.FromRgb(255, 253, 252)),
            TextTrimming = TextTrimming.CharacterEllipsis
        };

        _detailLabel = new TextBlock
        {
            Text = "Waiting for status...",
            FontSize = 9.5,
            FontWeight = FontWeights.Medium,
            Foreground = new SolidColorBrush(Color.FromRgb(165, 170, 182)),
            Margin = new Thickness(0, 2, 0, 0),
            TextTrimming = TextTrimming.CharacterEllipsis
        };

        textPanel.Children.Add(_brandTitle);
        textPanel.Children.Add(_detailLabel);

        Grid.SetColumn(textPanel, 2);
        mainGrid.Children.Add(textPanel);

        // 4. FULL-SIZED TRAFFIC LIGHT HOUSING (15px lamps, fixed width, never overlaps text)
        var trafficLightHousing = new Border
        {
            VerticalAlignment = VerticalAlignment.Center,
            Background = new SolidColorBrush(Color.FromArgb(170, 16, 12, 12)),
            BorderBrush = new SolidColorBrush(Color.FromArgb(55, 225, 148, 109)),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(13),
            Padding = new Thickness(5, 3, 5, 3)
        };

        var lampsPanel = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            VerticalAlignment = VerticalAlignment.Center
        };

        _redLamp = CreateLamp();
        _amberLamp = CreateLamp();
        _greenLamp = CreateLamp();

        lampsPanel.Children.Add(_redLamp);
        lampsPanel.Children.Add(_amberLamp);
        lampsPanel.Children.Add(_greenLamp);

        trafficLightHousing.Child = lampsPanel;
        Grid.SetColumn(trafficLightHousing, 3);
        mainGrid.Children.Add(trafficLightHousing);

        _rootBorder.Child = mainGrid;
        Content = _rootBorder;
    }

    private static Ellipse CreateLamp() => new()
    {
        Width = 15,
        Height = 15,
        Margin = new Thickness(3, 0, 3, 0),
        Fill = new SolidColorBrush(Color.FromRgb(50, 54, 63)),
        Stroke = new SolidColorBrush(Color.FromArgb(90, 0, 0, 0)),
        StrokeThickness = 1
    };

    private static ImageSource? LoadProductImage()
    {
        try
        {
            var image = new BitmapImage();
            image.BeginInit();
            image.DecodePixelWidth = 216;
            image.UriSource = new Uri("pack://application:,,,/Assets/ClawdyProduct.png");
            image.CacheOption = BitmapCacheOption.OnLoad;
            image.EndInit();
            image.Freeze();
            return image;
        }
        catch
        {
            return null;
        }
    }

    public void SetReducedMotion(bool reduced) => _reducedMotion = reduced;

    public void Update(StatusSnapshot snapshot, BlinkState finishBlink, long second)
    {
        Color redColor = Color.FromRgb(255, 75, 75);
        Color amberColor = Color.FromRgb(255, 185, 35);
        Color greenColor = Color.FromRgb(50, 220, 130);
        SolidColorBrush offBrush = new(Color.FromRgb(50, 54, 63));

        void SetLamp(Ellipse lamp, bool on, Color color)
        {
            if (on)
            {
                lamp.Fill = new SolidColorBrush(color);
                lamp.Effect = new DropShadowEffect
                {
                    BlurRadius = 12,
                    ShadowDepth = 0,
                    Opacity = 0.95,
                    Color = color
                };
            }
            else
            {
                lamp.Fill = offBrush;
                lamp.Effect = null;
            }
        }

        // 1. Dynamic background adapting to traffic light state
        UpdateBubbleTheme(snapshot.State, finishBlink);

        // 2. Active Working AI Provider Iteration
        var activeProviders = snapshot.Providers != null && snapshot.Providers.Length > 0
            ? snapshot.Providers
            : (snapshot.AttentionProviders != null && snapshot.AttentionProviders.Length > 0 ? snapshot.AttentionProviders : Array.Empty<string>());

        string currentProvider = "gemini";
        if (activeProviders.Length > 0)
        {
            var index = (int)((second / 3) % activeProviders.Length);
            currentProvider = activeProviders[index].ToLowerInvariant();
        }

        UpdateProviderBadge(currentProvider, snapshot.State);
        var (providerDisplayName, _) = FormatProvider(currentProvider);

        // 3. Session completion green blinking logic
        if (finishBlink.IsBlinking)
        {
            // Red is OFF
            SetLamp(_redLamp, false, redColor);

            // Amber is kept solidly ON if other sessions are still working!
            SetLamp(_amberLamp, finishBlink.KeepAmberOn, amberColor);

            // Green blinks 3 times (ON during greenPhaseOn, OFF otherwise)
            SetLamp(_greenLamp, finishBlink.GreenPhaseOn, greenColor);

            if (finishBlink.KeepAmberOn)
            {
                _brandTitle.Text = $"{providerDisplayName} · Working";
                _detailLabel.Text = finishBlink.GreenPhaseOn ? "🎉 Session done (others working)" : $"{snapshot.WorkingCount} active session(s)";
            }
            else
            {
                _brandTitle.Text = "All Done!";
                _detailLabel.Text = finishBlink.GreenPhaseOn ? "🎉 All sessions completed!" : "Wrapping up...";
            }
            return;
        }

        // Standard snapshot presentation
        var attentionBlink = snapshot.State == "attention" && !_reducedMotion && second % 2 != 0;
        var active = snapshot.State switch
        {
            "attention" when !attentionBlink => 0,
            "error" => 0,
            "working" => 1,
            "ready" => 2,
            _ => -1
        };

        SetLamp(_redLamp, active == 0, redColor);
        SetLamp(_amberLamp, active == 1, amberColor);
        SetLamp(_greenLamp, active == 2, greenColor);

        var stateName = snapshot.State switch
        {
            "working" => "Working",
            "ready" => "Ready",
            "attention" => "Needs You",
            "error" => "Error",
            _ => "Idle"
        };

        if (activeProviders.Length > 0 && snapshot.State == "working")
        {
            _brandTitle.Text = $"{providerDisplayName} · Working";
            _detailLabel.Text = snapshot.WorkingCount > 0
                ? $"{snapshot.WorkingCount} active session(s)"
                : "Active session running";
        }
        else if (snapshot.State == "ready")
        {
            _brandTitle.Text = "Clawdy · Ready";
            _detailLabel.Text = "All work is completed";
        }
        else if (snapshot.State == "attention" || snapshot.State == "error")
        {
            _brandTitle.Text = $"{providerDisplayName} · {stateName}";
            _detailLabel.Text = snapshot.Phrase ?? "Input required in session";
        }
        else
        {
            _brandTitle.Text = $"Clawdy · {stateName}";
            _detailLabel.Text = snapshot.Phrase ?? "Waiting for local bridge";
        }
    }

    private void UpdateBubbleTheme(string state, BlinkState finishBlink)
    {
        Color topColor, midColor, botColor, rimTop, rimBot, shadowColor;

        if (finishBlink.IsBlinking)
        {
            if (finishBlink.KeepAmberOn)
            {
                topColor = finishBlink.GreenPhaseOn ? Color.FromArgb(246, 56, 36, 20) : Color.FromArgb(244, 52, 28, 18);
                midColor = Color.FromArgb(246, 38, 22, 16);
                botColor = Color.FromArgb(248, 22, 14, 14);
                rimTop = Color.FromArgb(140, 255, 185, 35);
                rimBot = Color.FromArgb(50, 225, 148, 109);
                shadowColor = Color.FromArgb(255, 30, 16, 12);
            }
            else
            {
                topColor = finishBlink.GreenPhaseOn ? Color.FromArgb(246, 20, 56, 34) : Color.FromArgb(244, 14, 38, 24);
                midColor = Color.FromArgb(246, 12, 28, 18);
                botColor = Color.FromArgb(248, 8, 18, 14);
                rimTop = Color.FromArgb(140, 50, 220, 130);
                rimBot = Color.FromArgb(50, 50, 220, 130);
                shadowColor = Color.FromArgb(255, 10, 30, 18);
            }
        }
        else
        {
            switch (state)
            {
                case "working":
                    // Warm Claude/Terracotta Amber glow
                    topColor = Color.FromArgb(244, 54, 30, 20);
                    midColor = Color.FromArgb(246, 38, 22, 16);
                    botColor = Color.FromArgb(248, 22, 14, 14);
                    rimTop = Color.FromArgb(130, 255, 185, 35);
                    rimBot = Color.FromArgb(45, 225, 148, 109);
                    shadowColor = Color.FromArgb(255, 25, 14, 10);
                    break;
                case "ready":
                    // Deep rich Emerald Green glow
                    topColor = Color.FromArgb(244, 16, 48, 30);
                    midColor = Color.FromArgb(246, 10, 32, 20);
                    botColor = Color.FromArgb(248, 8, 20, 14);
                    rimTop = Color.FromArgb(130, 50, 220, 130);
                    rimBot = Color.FromArgb(45, 50, 220, 130);
                    shadowColor = Color.FromArgb(255, 10, 28, 16);
                    break;
                case "attention":
                case "error":
                    // Deep rich Crimson Red glow
                    topColor = Color.FromArgb(244, 58, 18, 20);
                    midColor = Color.FromArgb(246, 40, 12, 14);
                    botColor = Color.FromArgb(248, 24, 8, 10);
                    rimTop = Color.FromArgb(140, 255, 75, 75);
                    rimBot = Color.FromArgb(50, 255, 75, 75);
                    shadowColor = Color.FromArgb(255, 32, 8, 10);
                    break;
                default:
                    // Subtle dark terracotta / charcoal idle
                    topColor = Color.FromArgb(244, 36, 24, 22);
                    midColor = Color.FromArgb(246, 26, 18, 18);
                    botColor = Color.FromArgb(248, 18, 14, 15);
                    rimTop = Color.FromArgb(90, 225, 148, 109);
                    rimBot = Color.FromArgb(35, 225, 148, 109);
                    shadowColor = Color.FromArgb(255, 12, 8, 8);
                    break;
            }
        }

        _rootBorder.Background = new LinearGradientBrush
        {
            StartPoint = new Point(0, 0),
            EndPoint = new Point(1, 1),
            GradientStops =
            {
                new GradientStop(topColor, 0.0),
                new GradientStop(midColor, 0.45),
                new GradientStop(botColor, 1.0)
            }
        };

        _rootBorder.BorderBrush = new LinearGradientBrush
        {
            StartPoint = new Point(0, 0),
            EndPoint = new Point(1, 1),
            GradientStops =
            {
                new GradientStop(rimTop, 0.0),
                new GradientStop(rimBot, 1.0)
            }
        };

        if (_rootBorder.Effect is DropShadowEffect shadow)
        {
            shadow.Color = shadowColor;
        }
    }

    private void UpdateProviderBadge(string provider, string state)
    {
        var (name, color) = FormatProvider(provider);
        _providerPath.Stroke = null;
        _providerPath.StrokeThickness = 0;

        switch (provider)
        {
            case "codex":
                _providerPath.Data = CodexGeom;
                _providerPath.Fill = new SolidColorBrush(Color.FromRgb(16, 163, 127)); // OpenAI green
                break;
            case "claude":
                _providerPath.Data = ClaudeGeom;
                _providerPath.Fill = new SolidColorBrush(Color.FromRgb(225, 148, 109)); // Anthropic terracotta
                break;
            case "cursor":
                _providerPath.Data = CursorGeom;
                _providerPath.Fill = Brushes.Transparent;
                _providerPath.Stroke = new SolidColorBrush(Color.FromRgb(56, 189, 248)); // Cursor cyan
                _providerPath.StrokeThickness = 2.2;
                break;
            case "gemini":
            default:
                if (state == "ready")
                {
                    _providerPath.Data = ReadyGeom;
                    _providerPath.Fill = Brushes.Transparent;
                    _providerPath.Stroke = new SolidColorBrush(Color.FromRgb(50, 220, 130));
                    _providerPath.StrokeThickness = 2.5;
                }
                else
                {
                    _providerPath.Data = GeminiGeom;
                    _providerPath.Fill = new SolidColorBrush(Color.FromRgb(78, 136, 245)); // Gemini blue
                }
                break;
        }

        _providerPath.Effect = new DropShadowEffect
        {
            BlurRadius = 10,
            ShadowDepth = 0,
            Opacity = 0.7,
            Color = color
        };
    }

    private static (string Name, Color Color) FormatProvider(string provider) => provider switch
    {
        "codex" => ("ChatGPT", Color.FromRgb(16, 163, 127)),
        "claude" => ("Claude", Color.FromRgb(225, 148, 109)),
        "cursor" => ("Cursor", Color.FromRgb(56, 189, 248)),
        "gemini" => ("Gemini", Color.FromRgb(78, 136, 245)),
        _ => ("Clawdy", Color.FromRgb(225, 148, 109))
    };
}
