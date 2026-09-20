namespace NteHost.WindowMonitor;

/// <summary>
/// The semantic definition of the target game window.
///
/// The authoritative target is the real game process image name plus its window
/// class. A window matches only when BOTH hold. Nothing about a controlled test
/// window can satisfy the default spec, which is exactly the point: a test window
/// proves the mechanism, never the real product positive case.
/// </summary>
public sealed record TargetWindowSpec(string ProcessImageName, string WindowClass)
{
    /// <summary>The real product target: htgame.exe hosting an UnrealWindow.</summary>
    public static TargetWindowSpec Default { get; } = new("htgame.exe", "UnrealWindow");

    /// <summary>
    /// Pure match predicate. Case-insensitive on both fields because Windows
    /// process image names and window class names are case-insensitive.
    /// </summary>
    public bool Matches(string? processImageName, string? windowClass)
    {
        if (string.IsNullOrEmpty(processImageName) || string.IsNullOrEmpty(windowClass))
        {
            return false;
        }
        return string.Equals(processImageName, ProcessImageName, StringComparison.OrdinalIgnoreCase)
               && string.Equals(windowClass, WindowClass, StringComparison.OrdinalIgnoreCase);
    }

    public string Describe() => $"processImageName='{ProcessImageName}' windowClass='{WindowClass}'";

    public override string ToString() => Describe();
}
