namespace NteHost.WindowMonitor;

/// <summary>
/// A captured window identity. Identity is what makes a handle trustworthy: an
/// HWND alone is a recyclable integer, so every consumer decision is gated on
/// handle liveness AND a fresh identity read.
///
/// The identity is deliberately three-part rather than a pid+class pair:
///   * <see cref="Hwnd"/> is the handle, which Windows may recycle;
///   * <see cref="Pid"/> is the process, which Windows may also recycle;
///   * <see cref="ProcessImageName"/> is the executable backing that pid.
/// All three are captured at acquisition time, so "is this still my target?" can
/// be answered against the same three facts that established the target. A
/// pid+class check alone would accept a recycled handle whose pid happens to be
/// reused by a different executable.
/// </summary>
public sealed record WindowIdentity(
    long Hwnd,
    int Pid,
    string ProcessImageName,
    string ClassName,
    string Title,
    bool IsVisible)
{
    public static WindowIdentity None { get; } = new(0, 0, string.Empty, string.Empty, string.Empty, false);

    public bool IsPresent => Hwnd != 0;

    public string Describe() =>
        $"hwnd=0x{Hwnd:x} pid={Pid} image='{ProcessImageName}' class='{ClassName}' visible={IsVisible}";

    /// <summary>
    /// The identity-bearing fields, i.e. everything that must still hold for the
    /// handle to be considered the SAME window. <see cref="Title"/> is excluded on
    /// purpose: a game window legitimately retitles itself at runtime, so requiring
    /// a stable title would produce false losses.
    /// </summary>
    public (long Hwnd, int Pid, string Image, string Class) IdentityFields =>
        (Hwnd, Pid, ProcessImageName, ClassName);
}

/// <summary>
/// The outcome of a revalidation, reported field by field so a caller (and a test)
/// can see exactly which part of the identity stopped holding, instead of only
/// learning a boolean.
/// </summary>
public readonly record struct IdentityVerdict(
    bool IsSame,
    bool HandleAlive,
    bool PidMatches,
    bool ImageMatches,
    bool ClassMatches,
    bool VisibleEnough,
    string Failure)
{
    public static IdentityVerdict Fail(string failure) =>
        new(false, false, false, false, false, false, failure);

    public string Describe() =>
        IsSame
            ? "same-window"
            : $"different-window ({Failure}; alive={HandleAlive} pid={PidMatches} " +
              $"image={ImageMatches} class={ClassMatches} visible={VisibleEnough})";
}
