using System.IO;
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
/// showcasing the official Clawdy brand mascot and full-sized traffic light lamps.
/// </summary>
public sealed class DesktopPillWindow : Window
{
    private readonly Action _openCard;
    private readonly Ellipse _redLamp;
    private readonly Ellipse _amberLamp;
    private readonly Ellipse _greenLamp;
    private readonly TextBlock _brandTitle;
    private readonly TextBlock _stateTitle;
    private readonly TextBlock _detailLabel;
    private bool _reducedMotion;

    private static readonly ImageSource? CachedProduct = LoadProductImage();

    public DesktopPillWindow(Action openCard)
    {
        _openCard = openCard;

        Title = "Virtual Clawdy Desktop Companion";
        Width = 280;
        Height = 72;
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

        // Root pill container with frosted glass aesthetic and soft drop shadow
        var root = new Border
        {
            CornerRadius = new CornerRadius(24),
            Background = new SolidColorBrush(Color.FromArgb(244, 23, 26, 33)),
            BorderBrush = new SolidColorBrush(Color.FromArgb(65, 255, 255, 255)),
            BorderThickness = new Thickness(1.5),
            Cursor = Cursors.SizeAll,
            Effect = new DropShadowEffect
            {
                BlurRadius = 24,
                ShadowDepth = 4,
                Opacity = 0.55,
                Color = Colors.Black
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

        var mainGrid = new Grid { Margin = new Thickness(10, 8, 14, 8) };
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); // Mascot avatar
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }); // Brand & Status text
        mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); // 3 Large Traffic Lights

        // 1. OFFICIAL CLAWDY BRAND AVATAR (52x52px with warm cream background)
        var avatarBorder = new Border
        {
            Width = 54,
            Height = 54,
            CornerRadius = new CornerRadius(14),
            Background = new SolidColorBrush(Color.FromRgb(245, 232, 212)),
            Cursor = Cursors.Hand,
            Margin = new Thickness(0, 0, 10, 0)
        };
        avatarBorder.MouseLeftButtonDown += (s, e) => { e.Handled = true; _openCard(); };

        var avatarGrid = new Grid { Margin = new Thickness(4) };
        if (CachedProduct != null)
        {
            avatarGrid.Children.Add(new Image
            {
                Source = CachedProduct,
                Stretch = Stretch.Uniform
            });
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

        // 2. BRAND & STATUS TEXT PANEL
        var textPanel = new StackPanel
        {
            VerticalAlignment = VerticalAlignment.Center,
            Cursor = Cursors.Hand,
            Margin = new Thickness(0, 0, 10, 0)
        };
        textPanel.MouseLeftButtonDown += (s, e) => { e.Handled = true; _openCard(); };

        var brandRow = new StackPanel { Orientation = Orientation.Horizontal };
        _brandTitle = new TextBlock
        {
            Text = "Clawdy",
            FontSize = 13.5,
            FontWeight = FontWeights.Bold,
            Foreground = new SolidColorBrush(Color.FromRgb(225, 148, 109)),
            Margin = new Thickness(0, 0, 6, 0)
        };
        _stateTitle = new TextBlock
        {
            Text = "Idle",
            FontSize = 13,
            FontWeight = FontWeights.SemiBold,
            Foreground = new SolidColorBrush(Color.FromRgb(255, 253, 252)),
            TextTrimming = TextTrimming.CharacterEllipsis
        };
        brandRow.Children.Add(_brandTitle);
        brandRow.Children.Add(_stateTitle);

        _detailLabel = new TextBlock
        {
            Text = "Waiting for status...",
            FontSize = 10.5,
            FontWeight = FontWeights.Medium,
            Foreground = new SolidColorBrush(Color.FromRgb(165, 170, 182)),
            Margin = new Thickness(0, 2, 0, 0),
            TextTrimming = TextTrimming.CharacterEllipsis
        };

        textPanel.Children.Add(brandRow);
        textPanel.Children.Add(_detailLabel);

        Grid.SetColumn(textPanel, 1);
        mainGrid.Children.Add(textPanel);

        // 3. FULL-SIZED TRAFFIC LIGHT HOUSING (17px diameter lamps)
        var trafficLightHousing = new Border
        {
            VerticalAlignment = VerticalAlignment.Center,
            Background = new SolidColorBrush(Color.FromArgb(140, 12, 14, 18)),
            BorderBrush = new SolidColorBrush(Color.FromArgb(60, 255, 255, 255)),
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
        Grid.SetColumn(trafficLightHousing, 2);
        mainGrid.Children.Add(trafficLightHousing);

        root.Child = mainGrid;
        Content = root;
    }

    private static Ellipse CreateLamp() => new()
    {
        Width = 17,
        Height = 17,
        Margin = new Thickness(3.5, 0, 3.5, 0),
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

        if (finishBlink.IsBlinking)
        {
            // Session finish blinking mode:
            SetLamp(_redLamp, false, redColor);
            SetLamp(_amberLamp, finishBlink.KeepAmberOn, amberColor);
            SetLamp(_greenLamp, finishBlink.GreenPhaseOn, greenColor);

            if (finishBlink.KeepAmberOn)
            {
                _stateTitle.Text = "Working";
                _stateTitle.Foreground = new SolidColorBrush(amberColor);
                _detailLabel.Text = finishBlink.GreenPhaseOn ? "🎉 Session finished!" : $"{snapshot.WorkingCount} active session(s)";
            }
            else
            {
                _stateTitle.Text = "All Done!";
                _stateTitle.Foreground = new SolidColorBrush(greenColor);
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

        var (stateName, stateColor) = snapshot.State switch
        {
            "working" => ("Working", amberColor),
            "ready" => ("Ready", greenColor),
            "attention" => ("Needs You", redColor),
            "error" => ("Error", redColor),
            _ => ("Idle", Color.FromRgb(165, 170, 182))
        };

        _stateTitle.Text = stateName;
        _stateTitle.Foreground = new SolidColorBrush(stateColor);

        var prefix = snapshot.Demo ? "Demo · " : "";
        _detailLabel.Text = snapshot.WorkingCount > 0
            ? $"{prefix}{snapshot.WorkingCount} active session(s)"
            : $"{prefix}{(snapshot.Phrase ?? "Ready for work")}";
    }
}
