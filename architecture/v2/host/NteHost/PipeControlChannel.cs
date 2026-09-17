using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Threading;
using Microsoft.Win32.SafeHandles;
using NteHost.Protocol;

namespace NteHost;

public sealed record PipeSecurityFacts(
    string PipeName,
    string CurrentUserSid,
    string RequestedSddl,
    string ObservedSddl,
    bool AclReadBackSucceeded,
    int AllowAceCount,
    int DenyAceCount,
    bool AllowAceForCurrentUserWithFullAccess,
    int AllowAcesForOtherPrincipals,
    bool OwnerRightsSidPresent,
    IReadOnlyList<PipeAce> Aces,
    uint MaxInstances,
    bool RejectRemoteClientsRequested,
    bool ByteModeRequested,
    string CreationMode);

/// <summary>
/// The single V2-1 control-plane transport: a byte-mode Windows Named Pipe with
/// maxInstances=1, PIPE_REJECT_REMOTE_CLIENTS, and a DACL that grants GENERIC_ALL
/// exclusively to the dynamically resolved current-user SID (never the OWNER
/// RIGHTS placeholder S-1-3-4).
///
/// There is deliberately no stdio fallback: if the pipe cannot be created or the
/// engine cannot connect, the supervisor fails closed.
/// </summary>
public sealed class PipeControlChannel : IDisposable
{
    public string PipeName { get; }
    public PipeSecurityFacts SecurityFacts { get; private set; }

    private SafeFileHandle? _handle;
    private Stream? _stream;
    private readonly ManualResetEventSlim _connected = new(false);
    private Exception? _connectError;

    public bool IsConnected => _stream is not null;
    public bool StdioFallbackImplemented => false;

    private PipeControlChannel(string pipeName, PipeSecurityFacts facts)
    {
        PipeName = pipeName;
        SecurityFacts = facts;
    }

    public static PipeControlChannel Create(string sessionId, string nonce)
    {
        var pipeName = ProtocolConstants.PipeName(sessionId, nonce);
        var sid = WindowsIdentity.GetCurrent().User
                  ?? throw new InvalidOperationException("could not resolve the current user SID from the process token");

        // GENERIC_ALL to the current user SID only. OWNER_RIGHTS (S-1-3-4) is NOT used.
        var sddl = $"D:(A;;GA;;;{sid.Value})";

        if (!NativeMethods.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, NativeMethods.SDDL_REVISION_1, out var sd, out _))
        {
            throw new InvalidOperationException(
                $"ConvertStringSecurityDescriptorToSecurityDescriptorW failed: {Marshal.GetLastWin32Error()}");
        }

        var sa = new NativeMethods.SECURITY_ATTRIBUTES
        {
            nLength = Marshal.SizeOf<NativeMethods.SECURITY_ATTRIBUTES>(),
            lpSecurityDescriptor = sd,
            bInheritHandle = 0,
        };

        SafeFileHandle handle;
        try
        {
            handle = NativeMethods.CreateNamedPipeW(
                pipeName,
                NativeMethods.PIPE_ACCESS_DUPLEX | NativeMethods.FILE_FLAG_OVERLAPPED,
                NativeMethods.PIPE_TYPE_BYTE | NativeMethods.PIPE_READMODE_BYTE
                    | NativeMethods.PIPE_WAIT | NativeMethods.PIPE_REJECT_REMOTE_CLIENTS,
                1,
                ProtocolConstants.MaxMessageBytes,
                ProtocolConstants.MaxMessageBytes,
                0,
                ref sa);
        }
        finally
        {
            NativeMethods.LocalFree(sd);
        }

        if (handle.IsInvalid)
        {
            throw new ProtocolViolationException(ErrorCodes.PipeDisconnected,
                $"CreateNamedPipeW('{pipeName}') failed with Win32 error {Marshal.GetLastWin32Error()}");
        }

        var acl = PipeAclInspector.Inspect(handle, sid.Value);
        var facts = new PipeSecurityFacts(
            pipeName,
            sid.Value,
            sddl,
            acl.ObservedSddl,
            acl.ReadBackSucceeded,
            acl.AllowAceCount,
            acl.DenyAceCount,
            acl.AllowAceForCurrentUserWithFullAccess,
            acl.AllowAcesForOtherPrincipals,
            acl.OwnerRightsSidPresent,
            acl.Aces,
            1,
            true,
            true,
            "CreateNamedPipeW (PIPE_ACCESS_DUPLEX|FILE_FLAG_OVERLAPPED, PIPE_TYPE_BYTE|PIPE_READMODE_BYTE|PIPE_WAIT|PIPE_REJECT_REMOTE_CLIENTS, nMaxInstances=1)");

        var channel = new PipeControlChannel(pipeName, facts);
        channel._handle = handle;
        return channel;
    }

    /// <summary>
    /// Blocking ConnectNamedPipe on a background thread. A client that connected
    /// before the call still reports ERROR_PIPE_CONNECTED, which is success.
    /// </summary>
    public void BeginAccept(TimeSpan timeout, TraceLog trace, int generationId)
    {
        var worker = new Thread(() =>
        {
            try
            {
                var ok = OverlappedIo.Connect(_handle!, out var err);
                if (!ok && err != NativeMethods.ERROR_PIPE_CONNECTED)
                {
                    _connectError = new ProtocolViolationException(ErrorCodes.PipeDisconnected,
                        $"ConnectNamedPipe failed with Win32 error {err}");
                    _connected.Set();
                    return;
                }

                _stream = new RawPipeStream(_handle!);
                trace.Event("pipe.accepted", generationId, new { pipeName = PipeName, win32Error = err });
                _connected.Set();
            }
            catch (Exception ex)
            {
                _connectError = ex;
                _connected.Set();
            }
        })
        {
            IsBackground = true,
            Name = "nte-pipe-accept",
        };
        worker.Start();

        if (!_connected.Wait(timeout))
        {
            throw new ProtocolViolationException(ErrorCodes.HandshakeTimeout,
                $"no engine connected to '{PipeName}' within {timeout.TotalMilliseconds:F0}ms");
        }
        if (_connectError is not null)
        {
            throw _connectError;
        }
    }

    public Stream Stream => _stream ?? throw new ProtocolViolationException(ErrorCodes.PipeDisconnected, "pipe stream is not connected");

    public void Send(Envelope envelope, TraceLog trace, int generationId)
    {
        try
        {
            Framing.WriteFramed(Stream, envelope);
        }
        catch (IOException ex)
        {
            trace.Event("pipe.send.failed", generationId, new
            {
                messageType = envelope.MessageType,
                message = ex.Message,
                diagnostic = Diagnose(),
            });
            throw;
        }
        trace.Event("pipe.send", generationId,
            new { messageType = envelope.MessageType, requestId = envelope.RequestId, sequence = envelope.Sequence },
            envelope.RequestId, envelope.CorrelationId);
    }

    /// <summary>Diagnostic snapshot used only when a pipe write fails.</summary>
    public Dictionary<string, object?> Diagnose()
    {
        var info = new Dictionary<string, object?>();
        if (_handle is null || _handle.IsInvalid)
        {
            info["handle"] = "<invalid or null>";
            return info;
        }
        info["handleValue"] = _handle.DangerousGetHandle().ToInt64();
        info["fileType"] = NativeMethods.GetFileType(_handle);
        var ok = NativeMethods.GetNamedPipeInfo(_handle, out var flags, out var outSize, out var inSize, out var maxInstances);
        info["getNamedPipeInfoOk"] = ok;
        info["win32Error"] = Marshal.GetLastWin32Error();
        info["flags"] = flags;
        info["outBufferSize"] = outSize;
        info["inBufferSize"] = inSize;
        info["maxInstances"] = maxInstances;
        info["streamPresent"] = _stream is not null;
        return info;
    }

    public Envelope? Receive(TraceLog trace, int generationId)
    {
        var envelope = Framing.ReadEnvelope(Stream);
        if (envelope is not null)
        {
            trace.Event("pipe.receive", generationId,
                new { messageType = envelope.MessageType, requestId = envelope.RequestId, sequence = envelope.Sequence },
                envelope.RequestId, envelope.CorrelationId);
        }
        return envelope;
    }

    public void Dispose()
    {
        try
        {
            _stream?.Dispose();
        }
        catch (IOException)
        {
        }
        _stream = null;
        _handle?.Dispose();
        _handle = null;
        _connected.Dispose();
    }
}

/// <summary>
/// Overlapped I/O helpers. The pipe handle is created with FILE_FLAG_OVERLAPPED,
/// which is mandatory here: the supervisor keeps a blocking read in flight on the
/// pump thread while the session thread writes, and on a synchronous handle that
/// combination breaks the pipe instance (write -> ERROR_NO_DATA 232,
/// read -> ERROR_BROKEN_PIPE 109; reproduced in an isolated probe).
/// </summary>
internal static class OverlappedIo
{
    public static bool Connect(SafeFileHandle handle, out int win32Error)
    {
        var overlapped = Marshal.AllocHGlobal(Marshal.SizeOf<NativeMethods.OVERLAPPED>());
        var evt = NativeMethods.CreateEventW(IntPtr.Zero, true, false, null);
        try
        {
            var ov = new NativeMethods.OVERLAPPED { hEvent = evt };
            Marshal.StructureToPtr(ov, overlapped, false);

            var ok = NativeMethods.ConnectNamedPipe(handle, overlapped);
            if (ok)
            {
                win32Error = 0;
                return true;
            }
            win32Error = Marshal.GetLastWin32Error();
            if (win32Error != NativeMethods.ERROR_IO_PENDING)
            {
                return false;
            }
            NativeMethods.WaitForSingleObject(evt, NativeMethods.INFINITE);
            var completed = NativeMethods.GetOverlappedResult(handle, overlapped, out _, false);
            win32Error = completed ? 0 : Marshal.GetLastWin32Error();
            return completed;
        }
        finally
        {
            NativeMethods.CloseHandle(evt);
            Marshal.FreeHGlobal(overlapped);
        }
    }

    public static unsafe int Read(SafeFileHandle handle, byte* buffer, int count)
    {
        var overlapped = Marshal.AllocHGlobal(Marshal.SizeOf<NativeMethods.OVERLAPPED>());
        var evt = NativeMethods.CreateEventW(IntPtr.Zero, true, false, null);
        try
        {
            var ov = new NativeMethods.OVERLAPPED { hEvent = evt };
            Marshal.StructureToPtr(ov, overlapped, false);

            if (!NativeMethods.ReadFile(handle, (IntPtr)buffer, (uint)count, out var read, overlapped))
            {
                var err = Marshal.GetLastWin32Error();
                if (err == NativeMethods.ERROR_IO_PENDING)
                {
                    NativeMethods.WaitForSingleObject(evt, NativeMethods.INFINITE);
                    if (!NativeMethods.GetOverlappedResult(handle, overlapped, out read, false))
                    {
                        err = Marshal.GetLastWin32Error();
                        if (err is NativeMethods.ERROR_BROKEN_PIPE or NativeMethods.ERROR_NO_DATA)
                        {
                            return 0;
                        }
                        throw new IOException($"overlapped ReadFile failed with Win32 error {err}");
                    }
                }
                else if (err is NativeMethods.ERROR_BROKEN_PIPE or NativeMethods.ERROR_NO_DATA)
                {
                    return 0;
                }
                else
                {
                    throw new IOException($"overlapped ReadFile failed with Win32 error {err}");
                }
            }
            return (int)read;
        }
        finally
        {
            NativeMethods.CloseHandle(evt);
            Marshal.FreeHGlobal(overlapped);
        }
    }

    public static unsafe void Write(SafeFileHandle handle, byte* buffer, int count)
    {
        var overlapped = Marshal.AllocHGlobal(Marshal.SizeOf<NativeMethods.OVERLAPPED>());
        var evt = NativeMethods.CreateEventW(IntPtr.Zero, true, false, null);
        try
        {
            var ov = new NativeMethods.OVERLAPPED { hEvent = evt };
            Marshal.StructureToPtr(ov, overlapped, false);

            if (!NativeMethods.WriteFile(handle, (IntPtr)buffer, (uint)count, out var written, overlapped))
            {
                var err = Marshal.GetLastWin32Error();
                if (err != NativeMethods.ERROR_IO_PENDING)
                {
                    throw new IOException($"overlapped WriteFile failed with Win32 error {err}");
                }
                NativeMethods.WaitForSingleObject(evt, NativeMethods.INFINITE);
                if (!NativeMethods.GetOverlappedResult(handle, overlapped, out written, false))
                {
                    throw new IOException($"overlapped WriteFile failed with Win32 error {Marshal.GetLastWin32Error()}");
                }
            }
            if (written == 0)
            {
                throw new IOException("overlapped WriteFile wrote 0 bytes");
            }
        }
        finally
        {
            NativeMethods.CloseHandle(evt);
            Marshal.FreeHGlobal(overlapped);
        }
    }
}

/// <summary>
/// Minimal duplex Stream over a raw Named Pipe handle using overlapped
/// ReadFile / WriteFile.
///
/// FileStream is deliberately NOT used here: on a pipe handle it routes writes
/// through RandomAccess.WriteAtOffset, which is a seekable-file code path and
/// fails on pipes. Raw byte-mode overlapped ReadFile/WriteFile is exactly what the
/// frozen protocol expects and mirrors the Python engine's own implementation.
/// </summary>
internal sealed class RawPipeStream : Stream
{
    private readonly SafeFileHandle _handle;

    public RawPipeStream(SafeFileHandle handle)
    {
        _handle = handle;
    }

    public override bool CanRead => true;
    public override bool CanSeek => false;
    public override bool CanWrite => true;
    public override long Length => throw new NotSupportedException();

    public override long Position
    {
        get => throw new NotSupportedException();
        set => throw new NotSupportedException();
    }

    public override void Flush()
    {
    }

    public override int Read(byte[] buffer, int offset, int count) =>
        Read(buffer.AsSpan(offset, count));

    public override int Read(Span<byte> buffer)
    {
        unsafe
        {
            fixed (byte* ptr = buffer)
            {
                return OverlappedIo.Read(_handle, ptr, buffer.Length);
            }
        }
    }

    public override void Write(byte[] buffer, int offset, int count) =>
        Write(buffer.AsSpan(offset, count));

    public override void Write(ReadOnlySpan<byte> buffer)
    {
        var total = 0;
        while (total < buffer.Length)
        {
            unsafe
            {
                fixed (byte* ptr = buffer.Slice(total))
                {
                    OverlappedIo.Write(_handle, ptr, buffer.Length - total);
                }
            }
            // OverlappedIo.Write throws unless the full requested count was written.
            total = buffer.Length;
        }
    }

    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();

    public override void SetLength(long value) => throw new NotSupportedException();
}
