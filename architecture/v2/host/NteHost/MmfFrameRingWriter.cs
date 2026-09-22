using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using NteHost.Protocol;

namespace NteHost;

public enum FrameRingSlotState
{
    Free,
    Writing,
    Committed,
    ConsumerLocked,
}

public sealed record FrameSlotDiagnostic(
    int BufferIndex,
    FrameRingSlotState State,
    long? Sequence,
    string? SessionId);

public sealed record FramePublishReceipt(
    int BufferIndex,
    FrameHeaderV1 Header,
    string SessionId);

public sealed record FrameRingStats(
    string MapName,
    int FrameHeadersWritten,
    long BufferUnavailableCount,
    long CaptureFailureCount,
    long ContentInvalidCount,
    long AckMismatchCount,
    long NoAckCount,
    IReadOnlyList<FrameSlotDiagnostic> Slots);

/// <summary>
/// Host-owned V2 frame producer. This is deliberately separate from
/// <see cref="MmfRingGuard"/>: V2-1 proves mapping lifecycle and must continue to
/// assert that it never writes frames, while this class owns the real frame data
/// plane for the opt-in V2 experiment.
///
/// The producer writes BGRA8 pixels and a 64-byte FrameHeaderV1 into a fixed-v1
/// named mapping. Slot ownership is local to the Host and is released only by an
/// exact (sessionId, bufferIndex, sequence) FRAME_ACK. A locked slot is never
/// overwritten and a full ring drops the new frame instead.
/// </summary>
public sealed class MmfFrameRingWriter : IDisposable
{
    private readonly Action<byte[], int, IntPtr, int> _copyBytes;
    private readonly object _gate = new();
    private readonly FrameRingSlotState[] _states = new FrameRingSlotState[ProtocolConstants.SlotCount];
    private readonly string?[] _lockSessions = new string?[ProtocolConstants.SlotCount];
    private readonly long?[] _lockSequences = new long?[ProtocolConstants.SlotCount];

    private SafeFileHandle? _mapping;
    private IntPtr _view = IntPtr.Zero;
    private string _mapName = string.Empty;
    private long _nextSequence;
    private int _frameHeadersWritten;
    private long _bufferUnavailableCount;
    private long _captureFailureCount;
    private long _contentInvalidCount;
    private long _ackMismatchCount;
    private long _noAckCount;

    public MmfFrameRingWriter() : this(null)
    {
    }

    // Internal only: the ownership probe can inject a native-copy failure after
    // pixels are written, without changing the production Marshal.Copy path.
    internal MmfFrameRingWriter(Action<byte[], int, IntPtr, int>? copyBytes)
    {
        _copyBytes = copyBytes ?? ((source, startIndex, destination, length) =>
            Marshal.Copy(source, startIndex, destination, length));
    }

    public string MapName => _mapName;

    public bool IsCreated => _mapping is { IsInvalid: false } && _view != IntPtr.Zero;

    public long BufferUnavailableCount
    {
        get { lock (_gate) return _bufferUnavailableCount; }
    }

    public long CaptureFailureCount
    {
        get { lock (_gate) return _captureFailureCount; }
    }

    public long ContentInvalidCount
    {
        get { lock (_gate) return _contentInvalidCount; }
    }

    public long AckMismatchCount
    {
        get { lock (_gate) return _ackMismatchCount; }
    }

    public long NoAckCount
    {
        get { lock (_gate) return _noAckCount; }
    }

    public int FrameHeadersWritten
    {
        get { lock (_gate) return _frameHeadersWritten; }
    }

    public void Create(string sessionId, string nonce)
    {
        ArgumentException.ThrowIfNullOrEmpty(sessionId);
        ArgumentException.ThrowIfNullOrEmpty(nonce);
        lock (_gate)
        {
            if (IsCreated)
            {
                throw new InvalidOperationException("frame ring is already created");
            }

            _mapName = ProtocolConstants.MapName(sessionId, nonce);
            _mapping = NativeMethods.CreateFileMappingW(
                NativeMethods.INVALID_HANDLE_VALUE,
                IntPtr.Zero,
                NativeMethods.PAGE_READWRITE,
                0,
                (uint)ProtocolConstants.MapTotalSizeBytes,
                _mapName);
            if (_mapping.IsInvalid)
            {
                var error = Marshal.GetLastWin32Error();
                _mapping.Dispose();
                _mapping = null;
                throw new ProtocolViolationException(ErrorCodes.BufferUnavailable,
                    $"CreateFileMappingW('{_mapName}') failed with Win32 error {error}");
            }

            _view = NativeMethods.MapViewOfFile(
                _mapping,
                NativeMethods.FILE_MAP_ALL_ACCESS,
                0,
                0,
                (UIntPtr)ProtocolConstants.MapTotalSizeBytes);
            if (_view == IntPtr.Zero)
            {
                var error = Marshal.GetLastWin32Error();
                _mapping.Dispose();
                _mapping = null;
                throw new ProtocolViolationException(ErrorCodes.BufferUnavailable,
                    $"MapViewOfFile('{_mapName}') failed with Win32 error {error}");
            }
        }
    }

    public FramePublishReceipt? Publish(
        string sessionId,
        ReadOnlySpan<byte> bgraPixels,
        int width,
        int height,
        int stride,
        long captureTimestampNs,
        bool keyframe = true)
    {
        lock (_gate)
        {
            if (!IsCreated)
            {
                throw new InvalidOperationException("frame ring is not created");
            }

            if (!ValidateGeometry(width, height, stride, bgraPixels.Length, out var geometryError))
            {
                _contentInvalidCount++;
                throw new ProtocolViolationException(ErrorCodes.FrameCapacityExceeded, geometryError);
            }

            var slot = FindFreeSlot();
            if (slot < 0)
            {
                _bufferUnavailableCount++;
                return null;
            }

            _states[slot] = FrameRingSlotState.Writing;
            var sequence = ++_nextSequence;
            var checksum = CornerChecksum(bgraPixels, width, height, stride);
            var header = new FrameHeaderV1
            {
                Sequence = sequence,
                Width = width,
                Height = height,
                Stride = stride,
                PixelFormat = ProtocolConstants.DefaultPixelFormatBgra8,
                BufferLength = bgraPixels.Length,
                Flags = keyframe ? 1 : 0,
                CaptureTimestampNs = captureTimestampNs,
                ProducerTimestampNs = ProtocolClock.NowNs(),
                CornerChecksum = checksum,
                Reserved = 0,
            };

            var slotBase = IntPtr.Add(_view, ProtocolConstants.SlotOffset(slot));
            var pixelBase = IntPtr.Add(slotBase, ProtocolConstants.FrameHeaderSize);
            var headerBytes = header.Pack();

            try
            {
                // Publish pixels before the header. FRAME_READY is sent only after this
                // method returns, so a reader can never observe an advertised header
                // before its complete payload is present.
                _copyBytes(bgraPixels.ToArray(), 0, pixelBase, bgraPixels.Length);
                _copyBytes(headerBytes, 0, slotBase, headerBytes.Length);
                Thread.MemoryBarrier();

                _states[slot] = FrameRingSlotState.Committed;
                _states[slot] = FrameRingSlotState.ConsumerLocked;
                _lockSessions[slot] = sessionId;
                _lockSequences[slot] = sequence;
                _frameHeadersWritten++;
                return new FramePublishReceipt(slot, header, sessionId);
            }
            catch (Exception ex)
            {
                // A partial native copy must never strand a slot in Writing or
                // advertise incomplete bytes.  The caller sees a fail-closed
                // transport error and the slot is immediately reusable.
                _captureFailureCount++;
                _states[slot] = FrameRingSlotState.Free;
                _lockSessions[slot] = null;
                _lockSequences[slot] = null;
                throw new ProtocolViolationException(
                    ErrorCodes.BufferUnavailable,
                    $"frame write failed before publication: {ex.Message}");
            }
        }
    }

    public bool TryRelease(string sessionId, int bufferIndex, long sequence, out string errorCode)
    {
        lock (_gate)
        {
            if (bufferIndex < 0 || bufferIndex >= ProtocolConstants.SlotCount)
            {
                _ackMismatchCount++;
                errorCode = ErrorCodes.SlotIndexOutOfBounds;
                return false;
            }
            if (_states[bufferIndex] != FrameRingSlotState.ConsumerLocked
                || !string.Equals(_lockSessions[bufferIndex], sessionId, StringComparison.Ordinal)
                || _lockSequences[bufferIndex] != sequence)
            {
                _ackMismatchCount++;
                errorCode = ErrorCodes.UnknownFrameAck;
                return false;
            }

            _states[bufferIndex] = FrameRingSlotState.Free;
            _lockSessions[bufferIndex] = null;
            _lockSequences[bufferIndex] = null;
            errorCode = string.Empty;
            return true;
        }
    }

    public void RecordNoAck()
    {
        lock (_gate) _noAckCount++;
    }

    public FrameRingStats SnapshotStats()
    {
        lock (_gate)
        {
            var slots = new List<FrameSlotDiagnostic>(ProtocolConstants.SlotCount);
            for (var i = 0; i < ProtocolConstants.SlotCount; i++)
            {
                slots.Add(new FrameSlotDiagnostic(i, _states[i], _lockSequences[i], _lockSessions[i]));
            }
            return new FrameRingStats(
                _mapName,
                _frameHeadersWritten,
                _bufferUnavailableCount,
                _captureFailureCount,
                _contentInvalidCount,
                _ackMismatchCount,
                _noAckCount,
                slots);
        }
    }

    public void RecordCaptureFailure()
    {
        lock (_gate) _captureFailureCount++;
    }

    private int FindFreeSlot()
    {
        for (var i = 0; i < _states.Length; i++)
        {
            if (_states[i] == FrameRingSlotState.Free)
            {
                return i;
            }
        }
        return -1;
    }

    private static bool ValidateGeometry(int width, int height, int stride, int length, out string error)
    {
        if (width <= 0 || width > ProtocolConstants.MaxFrameWidth
            || height <= 0 || height > ProtocolConstants.MaxFrameHeight)
        {
            error = $"frame geometry {width}x{height} exceeds fixed v1 capacity "
                    + $"{ProtocolConstants.MaxFrameWidth}x{ProtocolConstants.MaxFrameHeight}";
            return false;
        }
        if (stride != width * 4 || length != stride * height)
        {
            error = $"frame geometry mismatch width={width} height={height} stride={stride} length={length}";
            return false;
        }
        if (length > ProtocolConstants.SlotPayloadCapacityBytes)
        {
            error = $"frame payload {length} exceeds fixed v1 slot capacity {ProtocolConstants.SlotPayloadCapacityBytes}";
            return false;
        }
        error = string.Empty;
        return true;
    }

    public static uint CornerChecksum(ReadOnlySpan<byte> bgraPixels, int width, int height, int stride)
    {
        uint sum = 0;
        var lastX = (width - 1) * 4;
        var lastY = (height - 1) * stride;
        foreach (var offset in new[] { 0, lastX, lastY, lastY + lastX })
        {
            for (var channel = 0; channel < 4; channel++)
            {
                sum = unchecked(sum + bgraPixels[offset + channel]);
            }
        }
        return sum;
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (_view != IntPtr.Zero)
            {
                NativeMethods.UnmapViewOfFile(_view);
                _view = IntPtr.Zero;
            }
            _mapping?.Dispose();
            _mapping = null;
            for (var i = 0; i < _states.Length; i++)
            {
                _states[i] = FrameRingSlotState.Free;
                _lockSessions[i] = null;
                _lockSequences[i] = null;
            }
        }
    }
}
