namespace NteHost.WindowMonitor.Win32;

/// <summary>
/// The WinEvent range V2-2A subscribes to. Kept explicit and small so the
/// subscription is auditable: this module watches window lifetime and system
/// foreground changes, and nothing else.
/// </summary>
internal static class WinEvent
{
    internal const uint EVENT_SYSTEM_FOREGROUND = 0x0003;
    internal const uint EVENT_SYSTEM_MINIMIZESTART = 0x0016;
    internal const uint EVENT_SYSTEM_MINIMIZEEND = 0x0017;

    internal const uint EVENT_OBJECT_CREATE = 0x8000;
    internal const uint EVENT_OBJECT_DESTROY = 0x8001;
    internal const uint EVENT_OBJECT_SHOW = 0x8002;
    internal const uint EVENT_OBJECT_HIDE = 0x8003;

    /// <summary>Lowest subscribed event.</summary>
    internal const uint Min = EVENT_SYSTEM_FOREGROUND;

    /// <summary>Highest subscribed event.</summary>
    internal const uint Max = EVENT_OBJECT_HIDE;

    internal const uint WINEVENT_OUTOFCONTEXT = 0x0000;
    internal const uint WINEVENT_SKIPOWNPROCESS = 0x0002;

    /// <summary>
    /// OBJID_WINDOW. Only window-level events are interesting; child-object events
    /// (cursors, text, menus) are ignored by the callback.
    /// </summary>
    internal const int OBJID_WINDOW = 0;

    internal static string Name(uint eventType) => eventType switch
    {
        EVENT_SYSTEM_FOREGROUND => "EVENT_SYSTEM_FOREGROUND",
        EVENT_SYSTEM_MINIMIZESTART => "EVENT_SYSTEM_MINIMIZESTART",
        EVENT_SYSTEM_MINIMIZEEND => "EVENT_SYSTEM_MINIMIZEEND",
        EVENT_OBJECT_CREATE => "EVENT_OBJECT_CREATE",
        EVENT_OBJECT_DESTROY => "EVENT_OBJECT_DESTROY",
        EVENT_OBJECT_SHOW => "EVENT_OBJECT_SHOW",
        EVENT_OBJECT_HIDE => "EVENT_OBJECT_HIDE",
        _ => $"0x{eventType:x4}",
    };
}
