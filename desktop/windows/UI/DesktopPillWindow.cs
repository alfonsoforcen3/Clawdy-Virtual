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
/// A prominent, beautiful, draggable always-on-top desktop companion widget
/// showcasing the official Clawdy brand mascot, cycling working AI logos, and full-sized traffic light lamps.
/// </summary>
public sealed class DesktopPillWindow : Window
{
    private readonly Action _openCard;
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
    private static readonly Geometry GeminiGeom = Geometry.Parse("M 16,2 C 16,9.5 9.5,16 2,16 C 9.5,16 16,22.5 16,30 C 16,22.5 22.5,16 30,16 C 22.5,16 16,9.5 16,2 Z");
    private static readonly Geometry CodexGeom = Geometry.Parse("M 16,5 C 19.5,5 22.5,7 23.8,10.2 C 24.8,10 25.8,10.2 26.6,10.8 C 27.8,11.8 28.3,13.4 28,15 C 29.2,16 29.8,17.6 29.5,19.2 C 29,21 27.6,22.2 26,22.5 C 26,23.5 25.5,24.5 24.8,25.2 C 23.6,26.4 21.8,26.8 20.2,26.2 C 19.2,27.5 17.6,28.2 16,28 C 14.4,28.2 12.8,27.5 11.8,26.2 C 10.2,26.8 8.4,26.4 7.2,25.2 C 6.5,24.5 6,23.5 6,22.5 C 4.4,22.2 3,21 2.5,19.2 C 2.2,17.6 2.8,16 4,15 C 3.7,13.4 4.2,11.8 5.4,10.8 C 6.2,10.2 7.2,10 8.2,10.2 C 9.5,7 12.5,5 16,5 Z");
    private static readonly Geometry ClaudeGeom = Geometry.Parse("M 16,3 L 18.2,11.5 L 26.5,8.5 L 21.5,15 L 29,18 L 21.5,21 L 26.5,27.5 L 18.2,24.5 L 16,33 L 13.8,24.5 L 5.5,27.5 L 10.5,21 L 3,18 L 10.5,15 L 5.5,8.5 L 13.8,11.5 Z");
    private static readonly Geometry CursorGeom = Geometry.Parse("M 16,4 L 27,10 L 27,22 L 16,28 L 5,22 L 5,10 Z M 16,4 L 16,28 M 5,10 L 27,22 M 27,10 L 5,22");
    private static readonly Geometry ReadyGeom = Geometry.Parse("M 8,16 L 14,22 L 25,9");

    public DesktopPillWindow(Action openCard)
    {
        _openCard = openCard;

        Title = "Virtual Clawdy Desktop Companion";
        Width = 340;
        Height = 74;
        WindowStyle = WindowStyle.None;
        AllowsTransparency = true;
        Background = Brushes.Transparent;
        ResizeMode = ResizeMode.NoResize;
        Topmost = true;
        ShowInTaskbar = false;
        ShowActivated = false;
        UseLayoutRounding = true;
        SnapsToDevicePixels = true;

        // Position at top-right corner of screen by default
        var workArea = SystemParameters.WorkArea;
        Left = Math.Max(24, workArea.Right - Width - 36);
        Top = Math.Max(24, workArea.Top + 36);

        // Subtle Claude-like terracotta gradient background with warm glass border
        var backgroundGradient = new LinearGradientBrush
        {
            StartPoint = new Point(0, 0),
            EndPoint = new Point(1, 1),
            GradientStops =
            {
                new GradientStop(Color.FromArgb(244, 52, 28, 22), 0.0),   // Warm terracotta tint
                new GradientStop(Color.FromArgb(246, 36, 20, 18), 0.45),  // Deep rich terracotta
                new GradientStop(Color.FromArgb(248, 22, 14, 15), 1.0)    // Dark warm espresso base
            }
        };

        var borderGradient = new LinearGradientBrush
        {
            StartPoint = new Point(0, 0),
            EndPoint = new Point(1, 1),
            GradientStops =
            {
                new GradientStop(Color.FromArgb(120, 225, 148, 109), 0.0), // Warm terracotta glass rim
                new GradientStop(Color.FromArgb(45, 225, 148, 109), 1.0)   // Subtle bottom rim
            }
        };

        // Root pill container with frosted glass aesthetic and soft drop shadow
        var root = new Border
        {
            CornerRadius = new CornerRadius(24),
            Background = backgroundGradient,
            BorderBrush = borderGradient,
            BorderThickness = new Thickness(1.4),
            Cursor = Cursors.SizeAll,
            Effect = new DropShadowEffect
            {
                BlurRadius = 24,
                ShadowDepth = 4,
                Opacity = 0.55,
                Color = Color.FromRgb(15, 8, 8)
            }
        };

        // Smooth dragging on left click; double-click opens full status card
        root.MouseLeftButtonDown += (_, e) =>
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

        var mainGrid = new Grid { Margin = new Thickness(10, 8, 12, 8) };
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); // 0: Mascot avatar (48px)
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); // 1: Active AI provider badge (32px)
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }); // 2: Text (spacious, no overlap)
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); // 3: Traffic Lights

        // 1. OFFICIAL CLAWDY BRAND AVATAR (Background-less, floats natively on dark glass)
        var avatarBorder = new Border
        {
            Width = 52,
            Height = 52,
            Background = Brushes.Transparent,
            Cursor = Cursors.Hand,
            Margin = new Thickness(0, 0, 6, 0)
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
                FontSize = 26,
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
            Width = 32,
            Height = 32,
            Background = Brushes.Transparent,
            BorderBrush = Brushes.Transparent,
            BorderThickness = new Thickness(0),
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, 8, 0),
            Cursor = Cursors.Hand
        };
        _providerBox.MouseLeftButtonDown += (s, e) => { e.Handled = true; _openCard(); };

        var viewbox = new Viewbox
        {
            Width = 24,
            Height = 24,
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
            FontSize = 13.5,
            FontWeight = FontWeights.Bold,
            Foreground = new SolidColorBrush(Color.FromRgb(255, 253, 252)),
            TextTrimming = TextTrimming.CharacterEllipsis
        };

        _detailLabel = new TextBlock
        {
            Text = "Waiting for status...",
            FontSize = 10,
            FontWeight = FontWeights.Medium,
            Foreground = new SolidColorBrush(Color.FromRgb(160, 165, 178)),
            Margin = new Thickness(0, 2, 0, 0),
            TextTrimming = TextTrimming.CharacterEllipsis
        };

        textPanel.Children.Add(_brandTitle);
        textPanel.Children.Add(_detailLabel);

        Grid.SetColumn(textPanel, 2);
        mainGrid.Children.Add(textPanel);

        // 4. FULL-SIZED TRAFFIC LIGHT HOUSING (16px lamps, fixed width, never overlaps text)
        var trafficLightHousing = new Border
        {
            VerticalAlignment = VerticalAlignment.Center,
            Background = new SolidColorBrush(Color.FromArgb(175, 20, 12, 12)),
            BorderBrush = new SolidColorBrush(Color.FromArgb(50, 225, 148, 109)),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(14),
            Padding = new Thickness(6, 4, 6, 4)
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

        root.Child = mainGrid;
        Content = root;
    }

    private static Ellipse CreateLamp() => new()
    {
        Width = 16,
        Height = 16,
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

        // Active Working AI Provider Iteration (Rotates every 3 seconds like Clawdy Pro Max OLED)
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

        if (finishBlink.IsBlinking)
        {
            SetLamp(_redLamp, false, redColor);
            SetLamp(_amberLamp, finishBlink.KeepAmberOn, amberColor);
            SetLamp(_greenLamp, finishBlink.GreenPhaseOn, greenColor);

            if (finishBlink.KeepAmberOn)
            {
                _brandTitle.Text = $"{providerDisplayName} · Working";
                _detailLabel.Text = finishBlink.GreenPhaseOn ? "🎉 Session finished!" : $"{snapshot.WorkingCount} active session(s)";
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
