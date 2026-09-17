using System;
using System.Collections.Generic;

namespace NteHost.Protocol;

/// <summary>Mirror of error_catalog_v1.json (37 codes, protocol 1.0.0).</summary>
public static class ErrorCodes
{
    public const string ProtocolVersionMismatch = "ERR_PROTOCOL_VERSION_MISMATCH";
    public const string RingGeometryMismatch = "ERR_RING_GEOMETRY_MISMATCH";
    public const string UnknownMessageType = "ERR_UNKNOWN_MESSAGE_TYPE";
    public const string MessageBeforeHandshake = "ERR_MESSAGE_BEFORE_HANDSHAKE";
    public const string MalformedEnvelope = "ERR_MALFORMED_ENVELOPE";
    public const string StaleSequence = "ERR_STALE_SEQUENCE";
    public const string StaleSession = "ERR_STALE_SESSION";
    public const string StaleGeneration = "ERR_STALE_GENERATION";
    public const string InvalidStateTransition = "ERR_INVALID_STATE_TRANSITION";
    public const string DuplicateCommand = "ERR_DUPLICATE_COMMAND";
    public const string CommandIdReuseMismatch = "ERR_COMMAND_ID_REUSE_MISMATCH";
    public const string PipeDisconnected = "ERR_PIPE_DISCONNECTED";
    public const string PipeBroken = "ERR_PIPE_BROKEN";
    public const string MessageTooLarge = "ERR_MESSAGE_TOO_LARGE";
    public const string StreamEof = "ERR_STREAM_EOF";
    public const string IncompleteFrame = "ERR_INCOMPLETE_FRAME";
    public const string SchemaValidationFailed = "ERR_SCHEMA_VALIDATION_FAILED";
    public const string MissingRequiredField = "ERR_MISSING_REQUIRED_FIELD";
    public const string CorruptFrameMagic = "ERR_CORRUPT_FRAME_MAGIC";
    public const string FramePayloadTooShort = "ERR_FRAME_PAYLOAD_TOO_SHORT";
    public const string FrameChecksumFailed = "ERR_FRAME_CHECKSUM_FAILED";
    public const string FrameMetadataMismatch = "ERR_FRAME_METADATA_MISMATCH";
    public const string FrameCapacityExceeded = "ERR_FRAME_CAPACITY_EXCEEDED";
    public const string SlotIndexOutOfBounds = "ERR_SLOT_INDEX_OUT_OF_BOUNDS";
    public const string BufferUnavailable = "ERR_BUFFER_UNAVAILABLE";
    public const string SlotNotLocked = "ERR_SLOT_NOT_LOCKED";
    public const string UnknownFrameAck = "ERR_UNKNOWN_FRAME_ACK";
    public const string UnsupportedPixelFormat = "ERR_UNSUPPORTED_PIXEL_FORMAT";
    public const string HandshakeTimeout = "ERR_HANDSHAKE_TIMEOUT";
    public const string HeartbeatTimeout = "ERR_HEARTBEAT_TIMEOUT";
    public const string FrameAckTimeout = "ERR_FRAME_ACK_TIMEOUT";
    public const string CommandTimeout = "ERR_COMMAND_TIMEOUT";
    public const string AuthorityViolation = "ERR_AUTHORITY_VIOLATION";
    public const string UnauthorizedStateMutation = "ERR_UNAUTHORIZED_STATE_MUTATION";
    public const string CapabilityUnsupported = "ERR_CAPABILITY_UNSUPPORTED";
    public const string WgcNotMeasured = "ERR_WGC_NOT_MEASURED";
    public const string WebView2Unavailable = "ERR_WEBVIEW2_UNAVAILABLE";

    public static readonly IReadOnlyList<string> All = new[]
    {
        ProtocolVersionMismatch, RingGeometryMismatch, UnknownMessageType, MessageBeforeHandshake,
        MalformedEnvelope, StaleSequence, StaleSession, StaleGeneration, InvalidStateTransition,
        DuplicateCommand, CommandIdReuseMismatch, PipeDisconnected, PipeBroken, MessageTooLarge,
        StreamEof, IncompleteFrame, SchemaValidationFailed, MissingRequiredField, CorruptFrameMagic,
        FramePayloadTooShort, FrameChecksumFailed, FrameMetadataMismatch, FrameCapacityExceeded,
        SlotIndexOutOfBounds, BufferUnavailable, SlotNotLocked, UnknownFrameAck,
        UnsupportedPixelFormat, HandshakeTimeout, HeartbeatTimeout, FrameAckTimeout,
        CommandTimeout, AuthorityViolation, UnauthorizedStateMutation, CapabilityUnsupported,
        WgcNotMeasured, WebView2Unavailable,
    };
}

/// <summary>Fail-closed protocol violation carrying a catalog error code.</summary>
public sealed class ProtocolViolationException : Exception
{
    public string ErrorCode { get; }

    public ProtocolViolationException(string errorCode, string message)
        : base($"[{errorCode}] {message}")
    {
        ErrorCode = errorCode;
    }
}
