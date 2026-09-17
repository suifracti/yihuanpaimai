using System;
using System.Collections.Generic;

namespace NteHost.Protocol;

/// <summary>
/// Frozen protocol-1.0.0 constants. Every value here is a mirror of
/// architecture/v2/contracts/*.json and is checked against the catalog by
/// HostSupervisorVerifier (D03/D04) so that a hand edit here cannot silently
/// drift away from the single schema truth.
/// </summary>
public static class ProtocolConstants
{
    public const string ProtocolVersion = "1.0.0";
    public const string VersionPolicy = "EXACT_MATCH_V1";
    public const int MaxMessageBytes = 1048576;

    public const uint FrameHeaderMagic = 0x4246544Eu;
    public const int FrameHeaderVersion = 1;
    public const int FrameHeaderSize = 64;
    public const int DefaultPixelFormatBgra8 = 1;

    // Ring geometry: FIXED_V1_CONSTANTS, never negotiated.
    public const string RingGeometryPolicy = "FIXED_V1_CONSTANTS";
    public const bool GeometryIsNegotiated = false;
    public const int SlotCount = 4;
    public const int MaxFrameWidth = 1920;
    public const int MaxFrameHeight = 1080;
    public const int SlotPayloadCapacityBytes = 8294400;
    public const int SlotSizeBytes = 8294464;
    public const int SlotAlignmentBytes = 64;
    public const int MapTotalSizeBytes = 33177856;

    // Timeouts (protocol_v1.json -> timeouts).
    public const int HelloNegotiationTimeoutMs = 5000;
    public const int HeartbeatIntervalMs = 1000;
    public const int HeartbeatTimeoutMs = 3000;
    public const int FrameAckTimeoutMs = 500;
    public const int CommandExecutionTimeoutMs = 500;
    public const int ShutdownTimeoutMs = 2000;

    public const string PipeNamePrefix = "\\\\.\\pipe\\nte_engine_ipc_";
    public const string MapNamePrefix = "Local\\NteFrameBuffer_v1_";

    public static string PipeName(string sessionId, string nonce) =>
        PipeNamePrefix + sessionId + "_" + nonce;

    public static string MapName(string sessionId, string nonce) =>
        MapNamePrefix + sessionId + "_" + nonce;

    public static int SlotOffset(int bufferIndex)
    {
        if (bufferIndex < 0 || bufferIndex >= SlotCount)
        {
            throw new ProtocolViolationException(ErrorCodes.SlotIndexOutOfBounds,
                $"slot index {bufferIndex} outside fixed v1 range 0 <= bufferIndex < {SlotCount}");
        }
        return bufferIndex * SlotSizeBytes;
    }

    public static IReadOnlyDictionary<string, int> FixedGeometry() => new Dictionary<string, int>
    {
        ["slotCount"] = SlotCount,
        ["slotSizeBytes"] = SlotSizeBytes,
        ["mapTotalSizeBytes"] = MapTotalSizeBytes,
        ["slotPayloadCapacityBytes"] = SlotPayloadCapacityBytes,
        ["headerSizeBytes"] = FrameHeaderSize,
        ["slotAlignmentBytes"] = SlotAlignmentBytes,
        ["maxWidth"] = MaxFrameWidth,
        ["maxHeight"] = MaxFrameHeight,
    };
}
