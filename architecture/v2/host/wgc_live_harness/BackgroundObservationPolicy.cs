using System.Text.Json.Nodes;
using NteHost.WindowMonitor;

namespace WgcLiveHarness;

/// <summary>Pure eligibility rules for a fixed read-only observation session. No capture or input API.</summary>
internal static class BackgroundObservationPolicy
{
    public const string Foreground = "foreground";
    public const string BackgroundReadOnly = "background-readonly";
    public const long MaximumReadbackSourceAgeNs = 2_000_000_000L;
    public const long MaximumPublishedSourceAgeNs = 31_000_000_000L;

    public static string ParseMode(string value) => value is Foreground or BackgroundReadOnly
        ? value : throw new ArgumentException("unsupported-observation-window-mode", nameof(value));

    public static bool IsObservationTargetUsable(string mode, WindowMonitorSnapshot snapshot,
        bool minimized, bool clientAreaAvailable, int width, int height)
        => IsObservationIdentityUsable(mode, snapshot, minimized)
            && (mode == Foreground || (clientAreaAvailable && width > 0 && height > 0 && width <= 1920 && height <= 1080));

    public static bool IsObservationIdentityUsable(string mode, WindowMonitorSnapshot snapshot, bool minimized)
    {
        if (mode is not (Foreground or BackgroundReadOnly)) return false;
        if (mode == Foreground)
            return snapshot.TargetHwnd != 0 && snapshot.IsTargetAlive && snapshot.IsTargetForeground
                && snapshot.TargetIdentity is { IsPresent: true };
        return snapshot.TargetHwnd != 0 && snapshot.TargetPid > 0 && snapshot.Generation > 0
            && snapshot.IsTargetAlive
            && snapshot.TargetIdentity is { IsPresent: true, IsVisible: true, ProcessInstanceToken: not 0 } identity
            && identity.Hwnd == snapshot.TargetHwnd && identity.Pid == snapshot.TargetPid
            && TargetWindowSpec.Default.Matches(identity.ProcessImageName, identity.ClassName)
            && (mode == BackgroundReadOnly || snapshot.IsTargetForeground)
            && !minimized;
    }

    public static bool IsSameObservationTarget(WindowMonitorSnapshot active, WindowMonitorSnapshot sessionTarget)
    {
        var processToken = sessionTarget.TargetIdentity?.ProcessInstanceToken;
        return processToken is not null and not 0
            && active.TargetHwnd == sessionTarget.TargetHwnd && active.TargetPid == sessionTarget.TargetPid
            && active.Generation == sessionTarget.Generation
            && active.TargetIdentity?.ProcessInstanceToken == processToken;
    }

    public static bool MatchesObservationTargetIdentity(string mode, JsonObject? expected,
        WindowMonitorSnapshot active, WindowMonitorSnapshot sessionTarget,
        bool minimized, bool clientAreaAvailable, int width, int height)
    {
        if (expected is null || !IsObservationTargetUsable(mode, active, minimized, clientAreaAvailable, width, height)
            || !IsSameObservationTarget(active, sessionTarget)) return false;
        return (long?)expected["targetHwnd"] == sessionTarget.TargetHwnd
            && (int?)expected["targetPid"] == sessionTarget.TargetPid
            && (long?)expected["generation"] == sessionTarget.Generation
            && (long?)expected["processInstanceToken"] == sessionTarget.TargetIdentity?.ProcessInstanceToken;
    }

    public static string? BackgroundReadbackRejection(string mode, long sourceNs, long readbackNs, long lastSourceNs)
    {
        if (mode == Foreground) return null;
        if (mode != BackgroundReadOnly) return "unsupported-observation-window-mode";
        if (sourceNs <= 0 || readbackNs <= 0) return "source-clock-unavailable";
        if (sourceNs <= lastSourceNs) return "source-clock-stalled";
        if (sourceNs > readbackNs) return "source-clock-after-readback";
        return readbackNs - sourceNs > MaximumReadbackSourceAgeNs ? "source-clock-stale-at-readback" : null;
    }

    public static string? BackgroundPublicationRejection(string mode, long sourceNs, long nowNs)
    {
        if (mode == Foreground) return null;
        if (mode != BackgroundReadOnly) return "unsupported-observation-window-mode";
        if (sourceNs <= 0 || nowNs <= 0) return "source-clock-unavailable";
        if (sourceNs > nowNs) return "source-clock-after-publication";
        return nowNs - sourceNs > MaximumPublishedSourceAgeNs ? "source-clock-stale-before-publication" : null;
    }
}
