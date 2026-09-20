using NteHost.Input;

namespace NteHost.Integration;

/// <summary>
/// Integration's last raw boundary. C permission is checked while this fence is
/// held immediately before the underlying backend is entered. A concurrent C
/// freeze therefore orders either before the real/fake raw call (zero underlying
/// calls) or after it (the submitted input is not retractable).
/// </summary>
public sealed class CArbitratedRawInputBackend : IRawInputBackend
{
    private readonly object _sendFence = new();
    private readonly IRawInputBackend _inner;
    private readonly Func<bool> _cPermission;
    private string _lastBlockReason = string.Empty;

    public CArbitratedRawInputBackend(IRawInputBackend inner, Func<bool> cPermission)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _cPermission = cPermission ?? throw new ArgumentNullException(nameof(cPermission));
    }

    public long SendCallCount => _inner.SendCallCount;

    public long InputsSentCount => _inner.InputsSentCount;

    public IReadOnlyList<ulong> SentExtraInfo => _inner.SentExtraInfo;

    public string LastBlockReason
    {
        get { lock (_sendFence) return _lastBlockReason; }
    }

    public bool IsSendFenceHeld => Monitor.IsEntered(_sendFence);

    public uint Send(InputRecord[] inputs)
    {
        lock (_sendFence)
        {
            if (!_cPermission())
            {
                _lastBlockReason = "C_PERMISSION_REVOKED_BEFORE_RAW";
                return 0;
            }

            _lastBlockReason = string.Empty;
            return _inner.Send(inputs);
        }
    }

    public void RunAtSendFence(Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        lock (_sendFence) action();
    }
}
