using System;
using System.Collections.Generic;

namespace NteHost.Protocol;

/// <summary>
/// Mirrors models.py::SequenceTracker. Scope is
/// PER_SENDER_PER_CONNECTION_GENERATION with generation key
/// (sessionId, sessionNonce, senderRole).
///
/// The critical property proven by V2-1 T10 is that a new generation starts from a
/// fresh high-water mark, so the replacement engine's first message (sequence 0) is
/// accepted even though sessionId is unchanged - while any packet carrying the old
/// nonce fails closed with ERR_STALE_GENERATION.
/// </summary>
public sealed class SequenceTracker
{
    private readonly Dictionary<(string SessionId, string Nonce, string SenderRole), long> _highWater = new();

    public string SessionId { get; private set; }
    public string CurrentNonce { get; private set; }
    public int GenerationId { get; private set; }

    public SequenceTracker(string sessionId, string sessionNonce, int generationId = 1)
    {
        SessionId = sessionId;
        CurrentNonce = sessionNonce;
        GenerationId = generationId;
    }

    /// <summary>Called when a new HELLO/HELLO_ACK handshake negotiates a fresh nonce.</summary>
    public void ResetGeneration(string sessionId, string newNonce)
    {
        SessionId = sessionId;
        CurrentNonce = newNonce;
        GenerationId += 1;
    }

    public void CheckAndUpdate(string senderRole, string sessionId, string sessionNonce, long sequence)
    {
        if (!string.Equals(sessionId, SessionId, StringComparison.Ordinal))
        {
            throw new ProtocolViolationException(ErrorCodes.StaleSession,
                $"session id '{sessionId}' does not match the active session '{SessionId}'");
        }
        if (!string.Equals(sessionNonce, CurrentNonce, StringComparison.Ordinal))
        {
            throw new ProtocolViolationException(ErrorCodes.StaleGeneration,
                $"session nonce '{Shorten(sessionNonce)}' belongs to an earlier or unknown connection generation");
        }
        if (sequence < 0)
        {
            throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope, $"negative sequence {sequence} is not allowed");
        }

        var key = (sessionId, sessionNonce, senderRole);
        var last = _highWater.TryGetValue(key, out var v) ? v : -1L;
        if (sequence <= last)
        {
            throw new ProtocolViolationException(ErrorCodes.StaleSequence,
                $"stale sequence {sequence} for generation ({Shorten(sessionId)}, {Shorten(sessionNonce)}, {senderRole}); high-water is {last}");
        }
        _highWater[key] = sequence;
    }

    public bool TryCheckAndUpdate(string senderRole, string sessionId, string sessionNonce, long sequence, out string errorCode)
    {
        try
        {
            CheckAndUpdate(senderRole, sessionId, sessionNonce, sequence);
            errorCode = string.Empty;
            return true;
        }
        catch (ProtocolViolationException ex)
        {
            errorCode = ex.ErrorCode;
            return false;
        }
    }

    public long HighWater(string senderRole, string sessionId, string sessionNonce) =>
        _highWater.TryGetValue((sessionId, sessionNonce, senderRole), out var v) ? v : -1L;

    private static string Shorten(string value) => value.Length <= 8 ? value : value[..8];
}
