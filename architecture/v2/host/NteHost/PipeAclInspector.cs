using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace NteHost;

public sealed record PipeAce(string AceType, string Sid, uint Mask, bool IsAllow, bool IsDeny);

public sealed record PipeAclFacts(
    bool ReadBackSucceeded,
    uint ReadBackStatus,
    string ObservedSddl,
    IReadOnlyList<PipeAce> Aces,
    int AllowAceCount,
    int DenyAceCount,
    bool AllowAceForCurrentUserWithFullAccess,
    int AllowAcesForOtherPrincipals,
    bool OwnerRightsSidPresent);

/// <summary>
/// Reads the DACL of the live Named Pipe object and enumerates its ACEs, comparing
/// each ACE SID against the current process TokenUser SID.
///
/// This is deliberately a structural check on the real object rather than a
/// string comparison against the requested SDDL: the SDDL writer canonicalises
/// GENERIC_ALL to FILE_ALL_ACCESS and abbreviates the machine-local RID 500 to
/// "LA", so string matching would be both weaker and wrong.
/// </summary>
internal static class PipeAclInspector
{
    private const int AclHeaderSize = 8;   // AclRevision, Sbz1, AclSize, AceCount, Sbz2
    private const int AceHeaderSize = 4;   // AceType, AceFlags, AceSize
    private const int AccessMaskSize = 4;  // ACCESS_MASK before SidStart
    private const string OwnerRightsSid = "S-1-3-4";

    public static PipeAclFacts Inspect(SafeFileHandle handle, string currentUserSid)
    {
        var status = NativeMethods.GetSecurityInfo(
            handle,
            NativeMethods.SE_KERNEL_OBJECT,
            NativeMethods.DACL_SECURITY_INFORMATION | NativeMethods.OWNER_SECURITY_INFORMATION,
            out _, out _, out var dacl, out _, out var sd);

        if (status != 0 || sd == IntPtr.Zero)
        {
            return new PipeAclFacts(false, status, $"<GetSecurityInfo status={status}>", Array.Empty<PipeAce>(),
                0, 0, false, 0, false);
        }

        try
        {
            var observedSddl = ToSddl(sd);
            var aces = dacl == IntPtr.Zero ? new List<PipeAce>() : EnumerateAces(dacl);

            var allowCount = 0;
            var denyCount = 0;
            var otherPrincipals = 0;
            var currentUserFull = false;
            var ownerRights = false;

            foreach (var ace in aces)
            {
                if (ace.IsAllow)
                {
                    allowCount++;
                    if (string.Equals(ace.Sid, currentUserSid, StringComparison.OrdinalIgnoreCase))
                    {
                        if ((ace.Mask & (NativeMethods.GENERIC_ALL | NativeMethods.FILE_ALL_ACCESS)) != 0)
                        {
                            currentUserFull = true;
                        }
                    }
                    else
                    {
                        otherPrincipals++;
                    }
                }
                else if (ace.IsDeny)
                {
                    denyCount++;
                }

                if (string.Equals(ace.Sid, OwnerRightsSid, StringComparison.OrdinalIgnoreCase))
                {
                    ownerRights = true;
                }
            }

            return new PipeAclFacts(true, 0, observedSddl, aces, allowCount, denyCount, currentUserFull, otherPrincipals, ownerRights);
        }
        finally
        {
            NativeMethods.LocalFree(sd);
        }
    }

    private static string ToSddl(IntPtr sd)
    {
        if (!NativeMethods.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                sd, NativeMethods.SDDL_REVISION_1,
                NativeMethods.DACL_SECURITY_INFORMATION | NativeMethods.OWNER_SECURITY_INFORMATION,
                out var ptr, out _))
        {
            return $"<ConvertSecurityDescriptorToString failed err={Marshal.GetLastWin32Error()}>";
        }
        try
        {
            return Marshal.PtrToStringUni(ptr) ?? string.Empty;
        }
        finally
        {
            NativeMethods.LocalFree(ptr);
        }
    }

    private static List<PipeAce> EnumerateAces(IntPtr dacl)
    {
        var aces = new List<PipeAce>();
        var aceCount = (ushort)Marshal.ReadInt16(dacl, 4);
        for (uint i = 0; i < aceCount; i++)
        {
            if (!NativeMethods.GetAce(dacl, i, out var ace))
            {
                break;
            }

            var aceType = Marshal.ReadByte(ace, 0);
            var mask = (uint)Marshal.ReadInt32(ace, AceHeaderSize);
            var sidPtr = ace + AceHeaderSize + AccessMaskSize;
            var sid = SidToString(sidPtr);

            var isAllow = aceType == NativeMethods.ACCESS_ALLOWED_ACE_TYPE;
            var isDeny = aceType == NativeMethods.ACCESS_DENIED_ACE_TYPE;
            aces.Add(new PipeAce($"0x{aceType:x2}", sid, mask, isAllow, isDeny));
        }
        return aces;
    }

    private static string SidToString(IntPtr sid)
    {
        if (!NativeMethods.ConvertSidToStringSidW(sid, out var ptr))
        {
            return $"<sid conversion failed err={Marshal.GetLastWin32Error()}>";
        }
        try
        {
            return Marshal.PtrToStringUni(ptr) ?? string.Empty;
        }
        finally
        {
            NativeMethods.LocalFree(ptr);
        }
    }
}
