namespace NteHost.WindowMonitor;

/// <summary>
/// A captured window identity. Identity is what makes a handle trustworthy: an
/// HWND alone is a recyclable integer, so every consumer decision is gated on
/// handle liveness AND a fresh identity read.
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
}
