using System.Diagnostics;

namespace Clawdy.Windows.Core;

public struct BlinkState
{
    public bool IsBlinking;
    public bool GreenPhaseOn;
    public bool KeepAmberOn;
    public bool AllFinished;
}

public sealed class SessionFinishTracker
{
    private int _prevWorkingCount;
    private string _prevState = "disconnected";
    private long _blinkStartTick;
    private bool _allFinished;

    public void Update(StatusSnapshot snapshot, long nowTicks)
    {
        // Detect session finish:
        // 1. Working count dropped while previously > 0
        // 2. Or state changed from "working" to "ready"
        bool sessionFinished = (snapshot.WorkingCount < _prevWorkingCount && _prevWorkingCount > 0)
                            || (_prevState == "working" && snapshot.State == "ready");

        if (sessionFinished)
        {
            _blinkStartTick = nowTicks;
            _allFinished = snapshot.WorkingCount == 0 || snapshot.State == "ready";
        }

        _prevWorkingCount = snapshot.WorkingCount;
        _prevState = snapshot.State;
    }

    public BlinkState GetBlinkState(long nowTicks)
    {
        if (_blinkStartTick == 0)
        {
            return new BlinkState { IsBlinking = false };
        }

        double elapsedMs = Stopwatch.GetElapsedTime(_blinkStartTick, nowTicks).TotalMilliseconds;
        // 3 blinks: 3 cycles of 500ms (250ms ON, 250ms OFF) = 1500ms total
        if (elapsedMs >= 1500.0)
        {
            _blinkStartTick = 0;
            return new BlinkState { IsBlinking = false, AllFinished = _allFinished };
        }

        double cyclePos = elapsedMs % 500.0;
        bool greenOn = cyclePos < 250.0;
        bool keepAmber = !_allFinished;

        return new BlinkState
        {
            IsBlinking = true,
            GreenPhaseOn = greenOn,
            KeepAmberOn = keepAmber,
            AllFinished = _allFinished
        };
    }
}
