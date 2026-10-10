namespace WgcLiveHarness;

internal static class CaptureFailure
{
    public static string Reason(Exception failure, string fallback)
    {
        for (Exception? current = failure; current is not null; current = current.InnerException)
        {
            if (current is MappingRejectedException mapping) return mapping.Message;
            if (current is MappingProbeException probe) return probe.Probe.Reason;
            if (current.Message.StartsWith("Queued frame source timestamp is in the future.", StringComparison.Ordinal))
                return "source-clock-future-at-selection";
        }
        return fallback;
    }
}
