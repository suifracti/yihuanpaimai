using System;
using System.Buffers.Binary;
using System.IO;

namespace NteHost.Protocol;

/// <summary>
/// The single frozen framing for protocol 1.0.0: a 4-byte little-endian uint32
/// payload length followed by UTF-8 JSON. There is no newline delimiter and no
/// second wire format; V2-1 implements exactly one transport (Windows Named
/// Pipe) and fails closed rather than falling back to stdio.
/// </summary>
public static class Framing
{
    public const int LengthPrefixBytes = 4;

    public static byte[] Frame(ReadOnlySpan<byte> utf8Json)
    {
        if (utf8Json.Length > ProtocolConstants.MaxMessageBytes)
        {
            throw new ProtocolViolationException(ErrorCodes.MessageTooLarge,
                $"message of {utf8Json.Length} bytes exceeds maxMessageBytes {ProtocolConstants.MaxMessageBytes}");
        }

        var buffer = new byte[LengthPrefixBytes + utf8Json.Length];
        BinaryPrimitives.WriteUInt32LittleEndian(buffer.AsSpan(0, LengthPrefixBytes), (uint)utf8Json.Length);
        utf8Json.CopyTo(buffer.AsSpan(LengthPrefixBytes));
        return buffer;
    }

    public static byte[] FrameEnvelope(Envelope envelope) => Frame(System.Text.Encoding.UTF8.GetBytes(envelope.ToCompactJson()));

    public static void WriteFramed(Stream stream, ReadOnlySpan<byte> utf8Json)
    {
        var framed = Frame(utf8Json);
        stream.Write(framed, 0, framed.Length);
        stream.Flush();
    }

    public static void WriteFramed(Stream stream, Envelope envelope)
    {
        var framed = FrameEnvelope(envelope);
        stream.Write(framed, 0, framed.Length);
        stream.Flush();
    }

    /// <summary>
    /// Reads one length-prefixed message. Returns null on a clean stream end.
    /// A truncated prefix or truncated body is ERR_INCOMPLETE_FRAME.
    /// </summary>
    public static byte[]? ReadFramed(Stream stream)
    {
        var prefix = new byte[LengthPrefixBytes];
        var read = ReadAtMost(stream, prefix, 0, LengthPrefixBytes);
        if (read == 0)
        {
            return null;
        }
        if (read < LengthPrefixBytes)
        {
            throw new ProtocolViolationException(ErrorCodes.IncompleteFrame,
                $"stream ended after {read} of {LengthPrefixBytes} length-prefix bytes");
        }

        var length = (long)BinaryPrimitives.ReadUInt32LittleEndian(prefix);
        if (length > ProtocolConstants.MaxMessageBytes)
        {
            throw new ProtocolViolationException(ErrorCodes.MessageTooLarge,
                $"declared payload length {length} exceeds maxMessageBytes {ProtocolConstants.MaxMessageBytes}");
        }

        var body = new byte[length];
        var got = ReadAtMost(stream, body, 0, (int)length);
        if (got < length)
        {
            throw new ProtocolViolationException(ErrorCodes.IncompleteFrame,
                $"stream ended after {got} of {length} declared payload bytes");
        }
        return body;
    }

    public static Envelope? ReadEnvelope(Stream stream)
    {
        var body = ReadFramed(stream);
        return body is null ? null : Envelope.Parse(body);
    }

    private static int ReadAtMost(Stream stream, byte[] buffer, int offset, int count)
    {
        var total = 0;
        while (total < count)
        {
            int n;
            try
            {
                n = stream.Read(buffer, offset + total, count - total);
            }
            catch (IOException ex)
            {
                throw new ProtocolViolationException(ErrorCodes.PipeBroken, $"pipe read failed: {ex.Message}");
            }
            if (n <= 0)
            {
                break;
            }
            total += n;
        }
        return total;
    }
}
