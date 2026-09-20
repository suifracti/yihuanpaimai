using System.Runtime.InteropServices;

namespace NteHost.Input;

/// <summary>
/// The single raw SendInput entry point in the whole module. Everything above it
/// is policy; nothing above it may call the OS directly.
/// </summary>
public interface IRawInputBackend
{
    /// <summary>Number of times the raw SendInput API was invoked.</summary>
    long SendCallCount { get; }

    /// <summary>Number of INPUT records actually handed to the OS.</summary>
    long InputsSentCount { get; }

    /// <summary>Extra-info values handed to the OS, in order (bounded, for evidence only).</summary>
    IReadOnlyList<ulong> SentExtraInfo { get; }

    /// <summary>Returns the number of records the OS accepted.</summary>
    uint Send(InputRecord[] inputs);
}

public interface ICursorBackend
{
    long SetCallCount { get; }

    (int X, int Y) GetPosition();

    bool SetPosition(int x, int y);
}

public sealed class Win32RawInputBackend : IRawInputBackend
{
    private readonly object _gate = new();
    private readonly List<ulong> _sentExtraInfo = new();
    private readonly List<ulong> _nativeExtraInfo = new();
    private long _sendCallCount;
    private long _inputsSentCount;

    public long SendCallCount => Interlocked.Read(ref _sendCallCount);

    public long InputsSentCount => Interlocked.Read(ref _inputsSentCount);

    public IReadOnlyList<ulong> SentExtraInfo
    {
        get { lock (_gate) { return _sentExtraInfo.ToArray(); } }
    }

    /// <summary>Values present in the native INPUT records immediately before SendInput.</summary>
    public IReadOnlyList<ulong> NativeExtraInfo
    {
        get { lock (_gate) { return _nativeExtraInfo.ToArray(); } }
    }

    public uint Send(InputRecord[] inputs)
    {
        ArgumentNullException.ThrowIfNull(inputs);
        if (inputs.Length == 0)
        {
            return 0;
        }

        var native = new NativeInputMethods.INPUT[inputs.Length];
        for (int i = 0; i < inputs.Length; i++)
        {
            var record = inputs[i];
            native[i] = new NativeInputMethods.INPUT
            {
                type = record.Type,
                u = new NativeInputMethods.INPUTUNION
                {
                    mi = new NativeInputMethods.MOUSEINPUT
                    {
                        dx = record.Dx,
                        dy = record.Dy,
                        mouseData = record.MouseData,
                        dwFlags = record.Flags,
                        time = 0,
                        dwExtraInfo = InputMarker.ToNative(record.ExtraInfo),
                    },
                },
            };
        }

        lock (_gate)
        {
            foreach (var record in inputs)
            {
                _sentExtraInfo.Add(record.ExtraInfo);
            }

            foreach (NativeInputMethods.INPUT record in native)
            {
                _nativeExtraInfo.Add(InputMarker.FromNative(record.u.mi.dwExtraInfo));
            }
        }

        Interlocked.Increment(ref _sendCallCount);

        uint sent = NativeInputMethods.SendInput(
            (uint)native.Length,
            native,
            Marshal.SizeOf<NativeInputMethods.INPUT>());

        Interlocked.Add(ref _inputsSentCount, sent);

        return sent;
    }
}

public sealed class Win32CursorBackend : ICursorBackend
{
    private long _setCallCount;

    public long SetCallCount => Interlocked.Read(ref _setCallCount);

    public (int X, int Y) GetPosition()
    {
        return NativeInputMethods.GetCursorPos(out var point) ? (point.X, point.Y) : (0, 0);
    }

    public bool SetPosition(int x, int y)
    {
        Interlocked.Increment(ref _setCallCount);
        return NativeInputMethods.SetCursorPos(x, y);
    }
}

/// <summary>
/// Deterministic raw backend for the targeted matrix. Counts exactly like the real
/// one but never touches the OS, so "SendInput count == 0" is asserted on the same
/// counter that the live path uses.
/// </summary>
public sealed class CountingRawInputBackend : IRawInputBackend
{
    private readonly object _gate = new();
    private readonly List<ulong> _sentExtraInfo = new();
    private long _sendCallCount;
    private long _inputsSentCount;

    /// <summary>When true, the backend throws instead of delivering (adapter-failure case).</summary>
    public bool ThrowOnSend { get; set; }

    /// <summary>When set, the backend reports this many accepted records instead of all of them.</summary>
    public uint? PartialSendResult { get; set; }

    public long SendCallCount => Interlocked.Read(ref _sendCallCount);

    public long InputsSentCount => Interlocked.Read(ref _inputsSentCount);

    public IReadOnlyList<ulong> SentExtraInfo
    {
        get { lock (_gate) { return _sentExtraInfo.ToArray(); } }
    }

    public uint Send(InputRecord[] inputs)
    {
        ArgumentNullException.ThrowIfNull(inputs);

        // The attempt is counted BEFORE any failure, so the counter always tells the
        // truth about how often the raw API was reached. "Nothing was delivered" is
        // reported separately by InputsSentCount.
        Interlocked.Increment(ref _sendCallCount);

        if (ThrowOnSend)
        {
            throw new InvalidOperationException("Injected raw backend failure.");
        }

        uint accepted = PartialSendResult ?? (uint)inputs.Length;
        Interlocked.Add(ref _inputsSentCount, accepted);
        lock (_gate)
        {
            for (int i = 0; i < Math.Min(accepted, (uint)inputs.Length); i++)
            {
                _sentExtraInfo.Add(inputs[i].ExtraInfo);
            }
        }

        return accepted;
    }
}

/// <summary>
/// Deterministic cursor backend. <see cref="OnSetPosition"/> is the seam that lets
/// a test place a user action exactly between <c>SetCursorPos</c> and the final
/// precheck, reproducing the TOCTOU window deterministically.
/// </summary>
public sealed class FakeCursorBackend : ICursorBackend
{
    private readonly object _gate = new();
    private int _x;
    private int _y;
    private long _setCallCount;

    public FakeCursorBackend(int x = 0, int y = 0)
    {
        _x = x;
        _y = y;
    }

    public Action<int, int, long>? OnSetPosition { get; set; }

    public bool ThrowOnSet { get; set; }

    /// <summary>When true, SetPosition silently does not move the cursor (models a clamped move).</summary>
    public bool IgnoreSet { get; set; }

    /// <summary>When set, that call reports false and leaves the cursor unchanged.</summary>
    public long? ReturnFalseOnSetCall { get; set; }

    public long SetCallCount => Interlocked.Read(ref _setCallCount);

    public (int X, int Y) GetPosition()
    {
        lock (_gate) { return (_x, _y); }
    }

    public void ForcePosition(int x, int y)
    {
        lock (_gate)
        {
            _x = x;
            _y = y;
        }
    }

    public bool SetPosition(int x, int y)
    {
        long call = Interlocked.Increment(ref _setCallCount);

        if (ThrowOnSet)
        {
            throw new InvalidOperationException("Injected cursor backend failure.");
        }

        bool succeeded = ReturnFalseOnSetCall != call;
        if (succeeded && !IgnoreSet)
        {
            lock (_gate)
            {
                _x = x;
                _y = y;
            }
        }

        OnSetPosition?.Invoke(x, y, call);
        return succeeded;
    }
}
