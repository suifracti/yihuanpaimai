using System.Reflection;
using NteHost.Input;

static class ObserverLatencyChecks
{
    public static void Run()
    {
        // No Start: only exercise the statistics buffer, never install hooks.
        var observer = new Win32LowLevelInputObserver("offline-latency");
        var record = typeof(Win32LowLevelInputObserver).GetMethod("RecordLatency", BindingFlags.NonPublic | BindingFlags.Instance)!;
        var capacity = (int)typeof(Win32LowLevelInputObserver).GetField("LatencySampleCapacity", BindingFlags.NonPublic | BindingFlags.Static)!.GetRawConstantValue()!;
        if (observer.Diagnostics().CallbackP95Us != 0) throw new Exception("EMPTY_LATENCY");
        for (int i=0; i<capacity; i++) record.Invoke(observer, new object[]{7.0});
        if (observer.Diagnostics().CallbackP95Us != 7.0) throw new Exception("FULL_LATENCY_BUFFER");
        record.Invoke(observer, new object[]{20.0});
        if (observer.Diagnostics().CallbackP95Us != 7.0) throw new Exception("OVERFLOW_LATENCY_BUFFER");
        for (int i=0; i<capacity; i++) record.Invoke(observer, new object[]{20.0});
        var final = observer.Diagnostics();
        if (final.CallbackP95Us != 7.0 || final.CallbackMaxUs != 20.0 || final.HooksInstalled)
            throw new Exception("SATURATED_LATENCY_STATS");
        Console.WriteLine("PASS empty/full/overflow/saturated statistics; hooks never started");
    }
}
