using System;
using System.Collections.Generic;

namespace NteHost.Protocol;

/// <summary>Mirror of message_catalog_v1.json (14 message types, protocol 1.0.0).</summary>
public static class MessageTypes
{
    public const string Hello = "HELLO";
    public const string HelloAck = "HELLO_ACK";
    public const string Heartbeat = "HEARTBEAT";
    public const string FrameReady = "FRAME_READY";
    public const string FrameAck = "FRAME_ACK";
    public const string PerceptionResult = "PERCEPTION_RESULT";
    public const string AbortScan = "ABORT_SCAN";
    public const string Command = "COMMAND";
    public const string CommandResult = "COMMAND_RESULT";
    public const string StateSnapshotRequest = "STATE_SNAPSHOT_REQUEST";
    public const string StateSnapshot = "STATE_SNAPSHOT";
    public const string EngineShutdown = "ENGINE_SHUTDOWN";
    public const string EngineRestarting = "ENGINE_RESTARTING";
    public const string Error = "ERROR";

    public static readonly IReadOnlyList<string> All = new[]
    {
        Hello, HelloAck, Heartbeat, FrameReady, FrameAck, PerceptionResult, AbortScan,
        Command, CommandResult, StateSnapshotRequest, StateSnapshot, EngineShutdown,
        EngineRestarting, Error,
    };

    public static bool IsKnown(string messageType) => All.Contains(messageType);

    /// <summary>
    /// Messages that are legal before the handshake completes
    /// (models.py::verify_message_allowed_in_state).
    /// </summary>
    public static readonly IReadOnlySet<string> PreHandshakeAllowed = new HashSet<string>
    {
        Hello, HelloAck, Heartbeat, EngineShutdown, Error,
    };
}
