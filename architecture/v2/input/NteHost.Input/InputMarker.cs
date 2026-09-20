using System.Globalization;
using System.Security.Cryptography;

namespace NteHost.Input;

/// <summary>
/// The marker transport contract shared by generation, SendInput construction,
/// low-level observation, and the self-injection ledger.
///
/// The Windows boundary is intentionally fixed at a full 32-bit value.  This is
/// not a low-32-bit comparison of a wider marker: every producer creates a
/// 32-bit marker, every native boundary conversion validates that width, and the
/// ledger compares the observed ULONG_PTR value exactly against the zero-extended
/// marker.  A non-zero high half therefore remains a mismatch.
/// </summary>
internal static class InputMarker
{
    internal const int TransportBits = 32;
    internal const ulong TransportMask = uint.MaxValue;

    internal static ulong NewRandom()
    {
        Span<byte> bytes = stackalloc byte[sizeof(uint)];
        uint value;
        do
        {
            RandomNumberGenerator.Fill(bytes);
            value = BitConverter.ToUInt32(bytes);
        }
        while (value == 0);

        return value;
    }

    internal static bool IsValid(ulong marker) => marker != 0 && marker <= TransportMask;

    internal static UIntPtr ToNative(ulong marker)
    {
        if (!IsValid(marker))
        {
            throw new ArgumentOutOfRangeException(
                nameof(marker),
                marker,
                "The marker must be a non-zero 32-bit transport value.");
        }

        return new UIntPtr((uint)marker);
    }

    internal static ulong FromNative(UIntPtr marker) => marker.ToUInt64();

    internal static bool ExactMatch(ulong expected, ulong observed) =>
        IsValid(expected) && observed == expected;

    internal static string ToHex(ulong marker) =>
        "0x" + marker.ToString("X8", CultureInfo.InvariantCulture);
}
