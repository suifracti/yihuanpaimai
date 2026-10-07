using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace WgcLiveHarness;

// No BGRA ownership: bounded metadata computed while the owner has the frame.
internal sealed record DeliveryVisualSummary(string CaptureId, long Epoch, long ReadbackNs,
    string SceneRoiSha256, string WarehouseRoiSha256, bool ActionQualified, string ObservationRoiSha256 = "")
{
    public static DeliveryVisualSummary From(CapturedBgraFrame f)
    {
        string Hash(int x0, int y0, int x1, int y1)
        {
            using var h = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            for (var y = y0; y < y1; y++) h.AppendData(f.Pixels, y * f.Stride + x0 * 4, (x1 - x0) * 4);
            return Convert.ToHexString(h.GetHashAndReset()).ToLowerInvariant();
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
        return new(p.CaptureId, p.PoolEpoch, f.CaptureTimestampNs,
            Hash(X(60), Y(125), X(355), Y(220)),
            Hash(X(1280), Y(200), f.Width, f.Height), p.Qualified && p.SourceMarkerProgress, Hash(0, 0, X(1280), f.Height));
    }
}

// Explains the existing advice-only qualification without changing its result.
// SOURCE uses delivery proof and its own evidence gates; this value is diagnostic.
internal sealed record DeliveryAdviceQualification(
    bool SourceMarkerProgress,
    bool SupportSummaryPresent,
    bool SupportActionQualified,
    bool SamePoolEpoch,
    bool ReadbackNotAfterPublication,
    bool ReadbackWithinTwoSeconds,
    bool SceneRoiMatches,
    bool ObservationRoiMatches,
    bool WarehouseRoiMatches)
{
    public bool Qualified => SourceMarkerProgress && SupportSummaryPresent && SupportActionQualified
        && SamePoolEpoch && ReadbackNotAfterPublication && ReadbackWithinTwoSeconds
        && SceneRoiMatches && ObservationRoiMatches && WarehouseRoiMatches;

    public string[] FailureReasons
    {
        get
        {
            var failures = new List<string>();
            if (!SourceMarkerProgress) failures.Add("SOURCE_MARKER_NO_PROGRESS");
            if (!SupportSummaryPresent) failures.Add("SUPPORT_SUMMARY_MISSING");
            else
            {
                if (!SupportActionQualified) failures.Add("SUPPORT_ACTION_UNQUALIFIED");
                if (!SamePoolEpoch) failures.Add("SUPPORT_POOL_EPOCH_MISMATCH");
                if (!ReadbackNotAfterPublication) failures.Add("SUPPORT_READBACK_FROM_FUTURE");
                else if (!ReadbackWithinTwoSeconds) failures.Add("SUPPORT_READBACK_STALE");
                if (!SceneRoiMatches) failures.Add("SUPPORT_SCENE_ROI_MISMATCH");
                if (!ObservationRoiMatches) failures.Add("SUPPORT_OBSERVATION_ROI_MISMATCH");
                if (!WarehouseRoiMatches) failures.Add("SUPPORT_WAREHOUSE_ROI_MISMATCH");
            }
            return failures.ToArray();
        }
    }

    public JsonObject ToJson() => new()
    {
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
            present && latest!.WarehouseRoiSha256 == original.WarehouseRoiSha256);
    }
}
