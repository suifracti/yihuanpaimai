using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace NteHost;

/// <summary>
/// Owns the child process lifetime. JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE guarantees
/// that the child (and any grandchild, because BREAKAWAY is never granted) dies
/// when the Host process dies, even on a hard kill.
/// </summary>
public sealed class JobObjectGuard : IDisposable
{
    public SafeFileHandle Handle { get; }
    public bool KillOnJobCloseSet { get; }
    public string? CreateError { get; }

    public JobObjectGuard()
    {
        try
        {
            Handle = NativeMethods.CreateJobObjectW(IntPtr.Zero, null);
            if (Handle.IsInvalid)
            {
                CreateError = $"CreateJobObjectW failed: {Marshal.GetLastWin32Error()}";
                Handle = new SafeFileHandle(IntPtr.Zero, false);
                return;
            }

            var info = new NativeMethods.JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags = NativeMethods.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

            var size = Marshal.SizeOf<NativeMethods.JOBOBJECT_EXTENDED_LIMIT_INFORMATION>();
            var ptr = Marshal.AllocHGlobal(size);
            try
            {
                Marshal.StructureToPtr(info, ptr, false);
                KillOnJobCloseSet = NativeMethods.SetInformationJobObject(
                    Handle, NativeMethods.JobObjectExtendedLimitInformation, ptr, (uint)size);
                if (!KillOnJobCloseSet)
                {
                    CreateError = $"SetInformationJobObject failed: {Marshal.GetLastWin32Error()}";
                }
            }
            finally
            {
                Marshal.FreeHGlobal(ptr);
            }
        }
        catch (Exception ex)
        {
            CreateError = ex.Message;
            Handle = new SafeFileHandle(IntPtr.Zero, false);
        }
    }

    public bool Assign(Process process)
    {
        if (Handle.IsInvalid)
        {
            return false;
        }
        return NativeMethods.AssignProcessToJobObject(Handle, process.Handle);
    }

    /// <summary>Explicit fail-closed termination path used when a graceful shutdown times out.</summary>
    public bool Terminate(uint exitCode = 1)
    {
        if (Handle.IsInvalid)
        {
            return false;
        }
        return NativeMethods.TerminateJobObject(Handle, exitCode);
    }

    public void Dispose() => Handle.Dispose();
}
