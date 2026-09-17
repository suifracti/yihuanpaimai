using System;
using System.Buffers.Binary;

namespace NteHost.Protocol;

/// <summary>
/// The frozen 64-byte FrameHeaderV1 (struct format "&lt;IiqiiiiiiqqIi", little-endian).
/// V2-1 never writes this header into the ring - it only needs the layout so that
/// the declared geometry and the header contract stay machine-checkable.
/// </summary>
public sealed class FrameHeaderV1
{
    public uint Magic { get; set; } = ProtocolConstants.FrameHeaderMagic;
    public int HeaderVersion { get; set; } = ProtocolConstants.FrameHeaderVersion;
    public long Sequence { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
    public int Stride { get; set; }
    public int PixelFormat { get; set; } = ProtocolConstants.DefaultPixelFormatBgra8;
    public int BufferLength { get; set; }
    public int Flags { get; set; }
    public long CaptureTimestampNs { get; set; }
    public long ProducerTimestampNs { get; set; }
    public uint CornerChecksum { get; set; }
    public int Reserved { get; set; }

    public const int OffsetMagic = 0;
    public const int OffsetHeaderVersion = 4;
    public const int OffsetSequence = 8;
    public const int OffsetWidth = 16;
    public const int OffsetHeight = 20;
    public const int OffsetStride = 24;
    public const int OffsetPixelFormat = 28;
    public const int OffsetBufferLength = 32;
    public const int OffsetFlags = 36;
    public const int OffsetCaptureTimestampNs = 40;
    public const int OffsetProducerTimestampNs = 48;
    public const int OffsetCornerChecksum = 56;
    public const int OffsetReserved = 60;

    public byte[] Pack()
    {
        var buffer = new byte[ProtocolConstants.FrameHeaderSize];
        BinaryPrimitives.WriteUInt32LittleEndian(buffer.AsSpan(OffsetMagic, 4), Magic);
        BinaryPrimitives.WriteInt32LittleEndian(buffer.AsSpan(OffsetHeaderVersion, 4), HeaderVersion);
        BinaryPrimitives.WriteInt64LittleEndian(buffer.AsSpan(OffsetSequence, 8), Sequence);
        BinaryPrimitives.WriteInt32LittleEndian(buffer.AsSpan(OffsetWidth, 4), Width);
        BinaryPrimitives.WriteInt32LittleEndian(buffer.AsSpan(OffsetHeight, 4), Height);
        BinaryPrimitives.WriteInt32LittleEndian(buffer.AsSpan(OffsetStride, 4), Stride);
        BinaryPrimitives.WriteInt32LittleEndian(buffer.AsSpan(OffsetPixelFormat, 4), PixelFormat);
        BinaryPrimitives.WriteInt32LittleEndian(buffer.AsSpan(OffsetBufferLength, 4), BufferLength);
        BinaryPrimitives.WriteInt32LittleEndian(buffer.AsSpan(OffsetFlags, 4), Flags);
        BinaryPrimitives.WriteInt64LittleEndian(buffer.AsSpan(OffsetCaptureTimestampNs, 8), CaptureTimestampNs);
        BinaryPrimitives.WriteInt64LittleEndian(buffer.AsSpan(OffsetProducerTimestampNs, 8), ProducerTimestampNs);
        BinaryPrimitives.WriteUInt32LittleEndian(buffer.AsSpan(OffsetCornerChecksum, 4), CornerChecksum);
        BinaryPrimitives.WriteInt32LittleEndian(buffer.AsSpan(OffsetReserved, 4), Reserved);
        return buffer;
    }

    public static FrameHeaderV1 Unpack(ReadOnlySpan<byte> buffer)
    {
        if (buffer.Length < ProtocolConstants.FrameHeaderSize)
        {
            throw new ProtocolViolationException(ErrorCodes.FramePayloadTooShort,
                $"frame header needs {ProtocolConstants.FrameHeaderSize} bytes, got {buffer.Length}");
        }
        return new FrameHeaderV1
        {
            Magic = BinaryPrimitives.ReadUInt32LittleEndian(buffer.Slice(OffsetMagic, 4)),
            HeaderVersion = BinaryPrimitives.ReadInt32LittleEndian(buffer.Slice(OffsetHeaderVersion, 4)),
            Sequence = BinaryPrimitives.ReadInt64LittleEndian(buffer.Slice(OffsetSequence, 8)),
            Width = BinaryPrimitives.ReadInt32LittleEndian(buffer.Slice(OffsetWidth, 4)),
            Height = BinaryPrimitives.ReadInt32LittleEndian(buffer.Slice(OffsetHeight, 4)),
            Stride = BinaryPrimitives.ReadInt32LittleEndian(buffer.Slice(OffsetStride, 4)),
            PixelFormat = BinaryPrimitives.ReadInt32LittleEndian(buffer.Slice(OffsetPixelFormat, 4)),
            BufferLength = BinaryPrimitives.ReadInt32LittleEndian(buffer.Slice(OffsetBufferLength, 4)),
            Flags = BinaryPrimitives.ReadInt32LittleEndian(buffer.Slice(OffsetFlags, 4)),
            CaptureTimestampNs = BinaryPrimitives.ReadInt64LittleEndian(buffer.Slice(OffsetCaptureTimestampNs, 8)),
            ProducerTimestampNs = BinaryPrimitives.ReadInt64LittleEndian(buffer.Slice(OffsetProducerTimestampNs, 8)),
            CornerChecksum = BinaryPrimitives.ReadUInt32LittleEndian(buffer.Slice(OffsetCornerChecksum, 4)),
            Reserved = BinaryPrimitives.ReadInt32LittleEndian(buffer.Slice(OffsetReserved, 4)),
        };
    }

    public static byte[] AllZeroHeaderBytes() => new byte[ProtocolConstants.FrameHeaderSize];
}
