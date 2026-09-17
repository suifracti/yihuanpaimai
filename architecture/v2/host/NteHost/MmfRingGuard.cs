using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using NteHost.Protocol;

namespace NteHost;

public sealed record MmfGenerationRecord(
    int GenerationId,
    string MapName,
    int DeclaredCapacityBytes,
    bool Created,
    bool ExactSizeViewSucceeded,
    bool OversizeViewDenied,
    int OversizeViewErrorCode,
    bool ZeroInitialized,
    long NonZeroBytesFound,
    bool ReadOnlyReopenSucceeded,
    bool ReadOnlyHandleWriteViewDenied,
    int ReadOnlyHandleWriteViewErrorCode,
    bool DisposeSucceeded,
    bool ReopenAfterDisposeFailed,
    int ReopenAfterDisposeErrorCode,
    int FrameHeadersWritten,
    int FrameReadyMessagesSent);

/// <summary>
/// V2-1 MMF responsibility is deliberately narrow: create the real fixed-v1
/// 4-slot mapping, prove its size / zero-init / access mode / generation
/// lifecycle, and NEVER write a frame header, pixel byte or FRAME_READY.
/// </summary>
public sealed class MmfRingGuard : IDisposable
{
    private SafeFileHandle? _mapping;
    private IntPtr _view = IntPtr.Zero;
    private readonly List<MmfGenerationRecord> _records = new();

    public int FrameHeadersWritten { get; private set; }
    public int FrameReadyMessagesSent { get; private set; }
    public IReadOnlyList<MmfGenerationRecord> Records => _records;

    public string? LastMapName { get; private set; }
    public bool LastCreated => _mapping is { IsInvalid: false };

    public MmfGenerationRecord Create(int generationId, string sessionId, string nonce)
    {
        var mapName = ProtocolConstants.MapName(sessionId, nonce);
        var capacity = ProtocolConstants.MapTotalSizeBytes;
        LastMapName = mapName;

        _mapping = NativeMethods.CreateFileMappingW(
            NativeMethods.INVALID_HANDLE_VALUE,
            IntPtr.Zero,
            NativeMethods.PAGE_READWRITE,
            0,
            (uint)capacity,
            mapName);

        var created = !_mapping.IsInvalid;
        if (!created)
        {
            var err = Marshal.GetLastWin32Error();
            var record = new MmfGenerationRecord(generationId, mapName, capacity, false, false, false, 0, false, -1,
                false, false, 0, false, false, 0, FrameHeadersWritten, FrameReadyMessagesSent);
            _records.Add(record with { });
            throw new ProtocolViolationException(ErrorCodes.BufferUnavailable,
                $"CreateFileMappingW('{mapName}', {capacity}) failed with Win32 error {err}");
        }

        // Map exactly the declared capacity.
        _view = NativeMethods.MapViewOfFile(_mapping, NativeMethods.FILE_MAP_ALL_ACCESS, 0, 0, (UIntPtr)capacity);
        var exactOk = _view != IntPtr.Zero;

        // Mapping past the end of the section must be denied, which is the machine
        // check that the real capacity is exactly `capacity` and not larger.
        var oversizeView = NativeMethods.MapViewOfFile(_mapping, NativeMethods.FILE_MAP_ALL_ACCESS, 0, 0, (UIntPtr)(capacity + 4096));
        var oversizeDenied = oversizeView == IntPtr.Zero;
        var oversizeErr = oversizeDenied ? Marshal.GetLastWin32Error() : 0;
        if (!oversizeDenied)
        {
            NativeMethods.UnmapViewOfFile(oversizeView);
        }

        // Zero-init proof: every byte of the fresh section must be 0.
        long nonZero = -1;
        if (exactOk)
        {
            nonZero = CountNonZero(_view, capacity);
        }

        // A second, read-only handle must not be able to obtain a writable view.
        var roHandle = NativeMethods.OpenFileMappingW(NativeMethods.FILE_MAP_READ, false, mapName);
        var roOpenOk = !roHandle.IsInvalid;
        var writeDenied = false;
        var writeErr = 0;
        if (roOpenOk)
        {
            var writeView = NativeMethods.MapViewOfFile(roHandle, NativeMethods.FILE_MAP_WRITE, 0, 0, UIntPtr.Zero);
            writeDenied = writeView == IntPtr.Zero;
            writeErr = writeDenied ? Marshal.GetLastWin32Error() : 0;
            if (!writeDenied)
            {
                NativeMethods.UnmapViewOfFile(writeView);
            }
            roHandle.Dispose();
        }

        var record2 = new MmfGenerationRecord(
            generationId, mapName, capacity, true,
            exactOk, oversizeDenied, oversizeErr,
            nonZero == 0, nonZero,
            roOpenOk, writeDenied, writeErr,
            false, false, 0,
            FrameHeadersWritten, FrameReadyMessagesSent);

        _records.Add(record2);
        return record2;
    }

    /// <summary>
    /// Releases this generation's mapping and proves the old generation name is no
    /// longer openable once every handle has been released.
    /// </summary>
    public MmfGenerationRecord DisposeGeneration(int generationId)
    {
        var index = _records.FindIndex(r => r.GenerationId == generationId);
        var previous = _records[index];

        if (_view != IntPtr.Zero)
        {
            NativeMethods.UnmapViewOfFile(_view);
            _view = IntPtr.Zero;
        }
        var disposed = false;
        if (_mapping is { IsInvalid: false })
        {
            _mapping.Dispose();
            disposed = true;
            _mapping = null;
        }

        // The engine has already closed its read-only handle by the time this runs,
        // so a fresh open of the old name must fail.
        var reopen = NativeMethods.OpenFileMappingW(NativeMethods.FILE_MAP_READ, false, previous.MapName);
        var reopenFailed = reopen.IsInvalid;
        var reopenErr = reopenFailed ? Marshal.GetLastWin32Error() : 0;
        if (!reopenFailed)
        {
            reopen.Dispose();
        }

        var updated = previous with
        {
            DisposeSucceeded = disposed,
            ReopenAfterDisposeFailed = reopenFailed,
            ReopenAfterDisposeErrorCode = reopenErr,
            FrameHeadersWritten = FrameHeadersWritten,
            FrameReadyMessagesSent = FrameReadyMessagesSent,
        };
        _records[index] = updated;
        return updated;
    }

    private static long CountNonZero(IntPtr view, int length)
    {
        long nonZero = 0;
        unsafe
        {
            var span = new Span<byte>((void*)view, length);
            for (var i = 0; i < span.Length; i++)
            {
                if (span[i] != 0)
                {
                    nonZero++;
                }
            }
        }
        return nonZero;
    }

    public void Dispose()
    {
        if (_view != IntPtr.Zero)
        {
            NativeMethods.UnmapViewOfFile(_view);
            _view = IntPtr.Zero;
        }
        _mapping?.Dispose();
        _mapping = null;
    }
}
