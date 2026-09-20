using NteHost.Input;

namespace NteIntegrationVerifier;

internal sealed class CallbackRawInputBackend : IRawInputBackend
{
    private readonly object _gate = new();
    private readonly List<ulong> _extraInfo = new();
    private long _sendCalls;
    private long _accepted;

    public Action? BeforeAccept { get; set; }

    public long SendCallCount => Interlocked.Read(ref _sendCalls);

    public long InputsSentCount => Interlocked.Read(ref _accepted);

    public IReadOnlyList<ulong> SentExtraInfo
    {
        get { lock (_gate) return _extraInfo.ToArray(); }
    }

    public uint Send(InputRecord[] inputs)
    {
        ArgumentNullException.ThrowIfNull(inputs);
        Interlocked.Increment(ref _sendCalls);
        BeforeAccept?.Invoke();
        Interlocked.Add(ref _accepted, inputs.Length);
        lock (_gate)
        {
            foreach (var input in inputs)
            {
                _extraInfo.Add(input.ExtraInfo);
            }
        }

        return (uint)inputs.Length;
    }
}
