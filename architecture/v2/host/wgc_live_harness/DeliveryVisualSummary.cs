using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace WgcLiveHarness;

// Own bounded ROI copies, never the capture owner's BGRA buffer.
internal sealed record DeliveryVisualSummary(string CaptureId, long Epoch, long ReadbackNs,
    string SceneRoiSha256, string WarehouseRoiSha256, bool ActionQualified, string ObservationRoiSha256 = "",
    string ScrollContentRoiSha256 = "", byte[]? ScrollContentBgr = null, byte[]? SceneBgr = null)
{
    // Only the scroll snapshot attaches the already read private payload.
    // It carries diagnostic evidence, never SOURCE or action authority.
    public CapturedBgraFrame? DiagnosticFrame { get; init; }
    public static bool AdjacentCodes(byte[]? a, byte[]? b)
    {
        if (a is null || b is null || a.Length == 0 || a.Length != b.Length) return false;
        for (var i = 0; i < a.Length; i++) if (Math.Abs(a[i] - b[i]) > 1) return false;
        return true;
    }

    public bool ContentSupportedBy(DeliveryVisualSummary other) =>
        !string.IsNullOrEmpty(ScrollContentRoiSha256) && (ScrollContentRoiSha256 == other.ScrollContentRoiSha256
            || AdjacentCodes(ScrollContentBgr, other.ScrollContentBgr));

    public bool SceneSupportedBy(DeliveryVisualSummary other)
    {
        if (!string.IsNullOrEmpty(SceneRoiSha256) && SceneRoiSha256 == other.SceneRoiSha256) return true;
        var a = SceneBgr; var b = other.SceneBgr;
        if (a is null || b is null || a.Length == 0 || a.Length != b.Length) return false;
        // Same normalized text-shape correlation contract as existing scene
        // anchors, with the stricter .99 stationary-support boundary. Background
        // brightness is not identity. The saved original's settlement title is
        // independently verified by Python; current context must remain eligible.
        double sa = 0, sb = 0, aa = 0, bb = 0, ab = 0;
        for (var i = 0; i < a.Length; i++) { sa += a[i]; sb += b[i]; aa += a[i] * a[i]; bb += b[i] * b[i]; ab += a[i] * b[i]; }
        var va = aa - sa * sa / a.Length; var vb = bb - sb * sb / a.Length;
        return va / a.Length >= 64 && vb / b.Length >= 64
            && (ab - sa * sb / a.Length) / Math.Sqrt(va * vb) >= .99;
    }
    // Same normalized board + right/bottom padding as warehouse_search_roi.
    // Includes unknown/dark cells, badges, clipping edges and scrollbar; no item masks.
    internal static (int Left, int Top, int Right, int Bottom) ScrollContentBox(int width, int height)
    {
        if (width <= 0 || height <= 0) throw new ArgumentOutOfRangeException(nameof(width));
        var vw = width; var vh = height; var vx = 0; var vy = 0;
        if (Math.Abs((double)width / height - 16.0 / 9) >= .02)
        {
            if ((double)width / height > 16.0 / 9) { vw = (int)(height * (16.0 / 9)); vx = (width - vw) / 2; }
            else { vh = (int)(width / (16.0 / 9)); vy = (height - vh) / 2; }
        }
        var left = Math.Clamp(vx + (int)(.685 * vw), 0, width - 1);
        var top = Math.Clamp(vy + (int)(.196 * vh), 0, height - 1);
        var right = Math.Max(left + 1, Math.Min(width, vx + (int)(.978 * vw)));
        var bottom = Math.Max(top + 1, Math.Min(height, vy + (int)(.755 * vh)));
        return (left, top, Math.Min(width, right + (int)(.020 * vw)),
            Math.Min(height, bottom + (int)(.030 * vh)));
    }

    public static DeliveryVisualSummary From(CapturedBgraFrame f)
    {
        string Hash(int x0, int y0, int x1, int y1)
        {
            using var h = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            for (var y = y0; y < y1; y++) h.AppendData(f.Pixels, y * f.Stride + x0 * 4, (x1 - x0) * 4);
            return Convert.ToHexString(h.GetHashAndReset()).ToLowerInvariant();
        }
        byte[] CopyBgr(int x0, int y0, int x1, int y1)
        {
            var bytes = new byte[checked((x1 - x0) * (y1 - y0) * 3)]; var k = 0;
            for (var y = y0; y < y1; y++) for (var x = x0; x < x1; x++)
            { var offset = y * f.Stride + x * 4; bytes[k++] = f.Pixels[offset]; bytes[k++] = f.Pixels[offset+1]; bytes[k++] = f.Pixels[offset+2]; }
            return bytes;
        }
        var vw = f.Width; var vh = f.Height; var vx = 0; var vy = 0;
        // Same 16:9 viewport compensation as the specified-window scroll entry.
        if (Math.Abs((double)f.Width / f.Height - 16.0 / 9) >= .02)
        {
            if ((double)f.Width / f.Height > 16.0 / 9) { vw = (int)(f.Height * 16.0 / 9); vx = (f.Width - vw) / 2; }
            else { vh = (int)(f.Width / (16.0 / 9)); vy = (f.Height - vh) / 2; }
        }
        int X(double n) => vx + (int)Math.Round(vw * n / 1920.0);
        int Y(double n) => vy + (int)Math.Round(vh * n / 1080.0);
        var p = f.DeliveryProof!;
        var scroll = ScrollContentBox(f.Width, f.Height);
        return new(p.CaptureId, p.PoolEpoch, f.CaptureTimestampNs,
            Hash(X(60), Y(125), X(355), Y(220)),
            Hash(X(1280), Y(200), f.Width, f.Height), p.Qualified && p.SourceMarkerProgress, Hash(0, 0, X(1280), f.Height),
            Hash(scroll.Left, scroll.Top, scroll.Right, scroll.Bottom),
            CopyBgr(scroll.Left, scroll.Top, scroll.Right, scroll.Bottom), CopyBgr(X(60), Y(125), X(355), Y(220)));
    }
}

// Eligibility to compute the delivered fact snapshot, never permission to bid.
// Cross-frame ROI equality remains diagnostic: dynamic pixels are not facts.
internal sealed record DeliveryAdviceQualification(
    bool SourceMarkerProgress,
    bool SupportSummaryPresent,
    bool SupportActionQualified,
    bool SamePoolEpoch,
    bool ReadbackNotAfterPublication,
    bool ReadbackWithinTwoSeconds,
    bool SceneRoiMatches,
    bool ObservationRoiMatches,
    bool WarehouseRoiMatches,
    bool OriginalFrameBound,
    bool OriginalDeliveryCurrent,
    bool SameSession,
    long EvaluationNs,
    string OriginalCaptureId,
    long OriginalReadbackNs,
    string? SupportCaptureId,
    long? SupportReadbackNs)
{
    public bool Qualified => SourceMarkerProgress && SupportSummaryPresent && SupportActionQualified
        && SamePoolEpoch && ReadbackNotAfterPublication && ReadbackWithinTwoSeconds
        && OriginalFrameBound && OriginalDeliveryCurrent && SameSession;

    public string[] FailureReasons
    {
        get
        {
            var failures = new List<string>();
            if (!OriginalFrameBound) failures.Add("ORIGINAL_FRAME_BINDING_MISMATCH");
            if (!OriginalDeliveryCurrent) failures.Add("ORIGINAL_DELIVERY_INVALID_OR_EXPIRED");
            if (!SourceMarkerProgress) failures.Add("SOURCE_MARKER_NO_PROGRESS");
            if (!SupportSummaryPresent) failures.Add("SUPPORT_SUMMARY_MISSING");
            else
            {
                if (!SupportActionQualified) failures.Add("SUPPORT_ACTION_UNQUALIFIED");
                if (!SamePoolEpoch) failures.Add("SUPPORT_POOL_EPOCH_MISMATCH");
                if (!SameSession) failures.Add("SUPPORT_SESSION_MISMATCH");
                if (!ReadbackNotAfterPublication) failures.Add("SUPPORT_READBACK_FROM_FUTURE");
                else if (!ReadbackWithinTwoSeconds) failures.Add("SUPPORT_READBACK_STALE");
            }
            return failures.ToArray();
        }
    }

    public JsonObject ToJson() => new()
    {
        ["schemaVersion"] = "delivery-facts-computation.v1",
        ["purpose"] = "compute-and-display-versioned-facts",
        ["automaticBidExecutionQualified"] = false,
        ["sourceAbsoluteAgeMs"] = null,
        ["evaluationNs"] = EvaluationNs,
        ["originalCaptureId"] = OriginalCaptureId,
        ["originalReadbackNs"] = OriginalReadbackNs,
        ["supportCaptureId"] = SupportCaptureId,
        ["supportReadbackNs"] = SupportReadbackNs,
        ["originalFrameBound"] = OriginalFrameBound,
        ["originalDeliveryCurrent"] = OriginalDeliveryCurrent,
        ["sameSession"] = SameSession,
        ["qualified"] = Qualified,
        ["sourceMarkerProgress"] = SourceMarkerProgress,
        ["supportSummaryPresent"] = SupportSummaryPresent,
        ["supportActionQualified"] = SupportActionQualified,
        ["samePoolEpoch"] = SamePoolEpoch,
        ["readbackNotAfterPublication"] = ReadbackNotAfterPublication,
        ["readbackWithinTwoSeconds"] = ReadbackWithinTwoSeconds,
        ["sceneRoiMatches"] = SceneRoiMatches,
        ["observationRoiMatches"] = ObservationRoiMatches,
        ["warehouseRoiMatches"] = WarehouseRoiMatches,
        ["failureReasons"] = new JsonArray(FailureReasons.Select(reason => JsonValue.Create(reason)).ToArray()),
    };

    public static DeliveryAdviceQualification EvaluateCurrent(CaptureDeliveryProof delivered,
        DeliveryVisualSummary original, Func<DeliveryVisualSummary?> readLatest, Func<long> now)
    {
        // Freeze the immutable summary first, then sample its comparison time.
        // A newer concurrent readback can no longer be compared with an older clock.
        var latest = readLatest();
        return Evaluate(delivered, latest, original, now());
    }

    public static DeliveryAdviceQualification Evaluate(CaptureDeliveryProof delivered,
        DeliveryVisualSummary? latest, DeliveryVisualSummary original, long publicationAtNs)
    {
        var present = latest is not null;
        var notAfter = present && latest!.ReadbackNs <= publicationAtNs;
        return new(
            delivered.SourceMarkerProgress,
            present,
            present && latest!.ActionQualified,
            present && latest!.Epoch == delivered.PoolEpoch,
            notAfter,
            notAfter && publicationAtNs - latest!.ReadbackNs <= 2_000_000_000,
            present && latest!.SceneRoiSha256 == original.SceneRoiSha256,
            present && latest!.ObservationRoiSha256 == original.ObservationRoiSha256,
            present && latest!.WarehouseRoiSha256 == original.WarehouseRoiSha256,
            original.CaptureId == delivered.CaptureId && original.Epoch == delivered.PoolEpoch
                && original.ReadbackNs == delivered.ReadbackCompletedNs && original.ActionQualified,
            delivered.Rejection(publicationAtNs, 31_000_000_000) is null,
            present && latest!.CaptureId.StartsWith(delivered.ObservationSessionId + "/", StringComparison.Ordinal),
            publicationAtNs, original.CaptureId, original.ReadbackNs, latest?.CaptureId, latest?.ReadbackNs);
    }
}
