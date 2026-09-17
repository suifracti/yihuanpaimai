using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ArchitectureV2.Contracts
{
    public static class ContractConstants
    {
        public const string ProtocolVersion = "1.0.0";
        public const uint FrameHeaderMagic = 0x4246544E; // 'NTFB' in LE
        public const int FrameHeaderVersion = 1;
        public const int FrameHeaderSize = 64;
        public const int MaxMessageBytes = 1048576; // 1 MB
        public const int DefaultPixelFormatBgra8 = 1;

        // Ring Buffer Geometry
        public const int SlotCount = 4;
        public const int SlotPayloadCapacityBytes = 8294400; // 1920 * 1080 * 4
        public const int SlotSizeBytes = 8294464;            // 64 + 8294400
        public const int SlotAlignmentBytes = 64;
        public const int MapTotalSizeBytes = 33177856;       // 4 * 8294464
    }

    [StructLayout(LayoutKind.Explicit, Size = ContractConstants.FrameHeaderSize)]
    public struct FrameHeaderV1
    {
        [FieldOffset(0)]  public uint Magic;
        [FieldOffset(4)]  public int HeaderVersion;
        [FieldOffset(8)]  public long Sequence;
        [FieldOffset(16)] public int Width;
        [FieldOffset(20)] public int Height;
        [FieldOffset(24)] public int Stride;
        [FieldOffset(28)] public int PixelFormat;
        [FieldOffset(32)] public int BufferLength;
        [FieldOffset(36)] public int Flags;
        [FieldOffset(40)] public long CaptureTimestampNs;
        [FieldOffset(48)] public long ProducerTimestampNs;
        [FieldOffset(56)] public uint CornerChecksum;
        [FieldOffset(60)] public int Reserved;

        public static FrameHeaderV1 CreateDefault(long sequence = 0, int width = 1920, int height = 1080)
        {
            return new FrameHeaderV1
            {
                Magic = ContractConstants.FrameHeaderMagic,
                HeaderVersion = ContractConstants.FrameHeaderVersion,
                Sequence = sequence,
                Width = width,
                Height = height,
                Stride = width * 4,
                PixelFormat = ContractConstants.DefaultPixelFormatBgra8,
                BufferLength = width * height * 4,
                Flags = 0,
                CaptureTimestampNs = 0,
                ProducerTimestampNs = 0,
                CornerChecksum = 0,
                Reserved = 0
            };
        }
    }

    public enum MessageType
    {
        HELLO,
        HELLO_ACK,
        HEARTBEAT,
        FRAME_READY,
        FRAME_ACK,
        PERCEPTION_RESULT,
        ABORT_SCAN,
        COMMAND,
        COMMAND_RESULT,
        STATE_SNAPSHOT_REQUEST,
        STATE_SNAPSHOT,
        ENGINE_SHUTDOWN,
        ENGINE_RESTARTING,
        ERROR
    }

    public enum CapabilityStatus
    {
        AVAILABLE,
        UNAVAILABLE,
        EXPERIMENTAL,
        NOT_MEASURED
    }

    public enum LifecycleState
    {
        ENGINE_DOWN,
        STARTING,
        HANDSHAKING,
        SYNCING,
        READY,
        DEGRADED
    }

    public enum ErrorCategory
    {
        PROTOCOL,
        TRANSPORT,
        PAYLOAD,
        TIMEOUT,
        AUTHORITY,
        CAPABILITY
    }

    public enum HelloAckStatus
    {
        ACCEPTED,
        REJECTED_VERSION,
        REJECTED_CAPABILITY
    }

    public enum EngineReadiness
    {
        STARTING,
        LOADING,
        READY,
        DEGRADED,
        FAILED
    }

    public enum FrameAckStatus
    {
        RELEASED,
        CONSUMED,
        SKIPPED,
        CORRUPTED
    }

    public enum CommandResultStatus
    {
        ACK,
        REJECT,
        EXPIRED,
        STALE_SESSION,
        DUPLICATE,
        NOT_FOREGROUND,
        FROZEN,
        CAPABILITY_UNAVAILABLE,
        FAILED
    }

    public enum AbortReason
    {
        USER_TAKEOVER,
        FOCUS_LOST,
        ESCAPE_KEY,
        TARGET_CLOSED
    }

    public enum SlotState
    {
        FREE,
        WRITING,
        COMMITTED,
        CONSUMER_LOCKED
    }

    public class Envelope
    {
        [JsonPropertyName("protocolVersion")]
        public string ProtocolVersion { get; set; } = ContractConstants.ProtocolVersion;

        [JsonPropertyName("sessionId")]
        public string SessionId { get; set; } = string.Empty;

        [JsonPropertyName("messageType")]
        public string MessageType { get; set; } = string.Empty;

        [JsonPropertyName("requestId")]
        public string RequestId { get; set; } = string.Empty;

        [JsonPropertyName("correlationId")]
        public string? CorrelationId { get; set; }

        [JsonPropertyName("sequence")]
        public long Sequence { get; set; }

        [JsonPropertyName("monotonicTimestampNs")]
        public long MonotonicTimestampNs { get; set; }

        [JsonPropertyName("payload")]
        public JsonElement Payload { get; set; }
    }

    public class DropCounters
    {
        public int ProducerOverwrite { get; set; }
        public int ConsumerTimeout { get; set; }
        public int CaptureFailure { get; set; }
        public int ContentInvalid { get; set; }
        public int FrameSuperseded { get; set; }
        public int BufferUnavailable { get; set; }
    }
}
