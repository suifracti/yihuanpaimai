using System.Runtime.InteropServices.WindowsRuntime;
using System.Text.RegularExpressions;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;

namespace WgcLiveHarness;

/// <summary>Digit readback for the scene-anchor decoder. A missing or ambiguous line is null.</summary>
static class SceneAnchorOcr
{
    static readonly Lazy<OcrEngine?> Engine = new(OcrEngine.TryCreateFromUserProfileLanguages);

    // The lobby asset bar is left of the in-auction bar. Exclude its currency
    // icon: Windows OCR can read that icon as an additional zero.
    public static (int X, int Y, int W, int H)? AssetsRegion(string? scene, int width, int height)
    {
        if (width != 1920 || height != 1080) return null;
        return scene switch
        {
            "LOBBY" => (1340, 20, 170, 65),
            "AUCTION" or "AUCTION_READY" or "INSTRUMENT_LIST" or "INSTRUMENT_GOLD_SELECTED"
                => (1695, 25, 180, 65),
            _ => null
        };
    }

    public static long? ReadAssets(ReadOnlyMemory<byte> bgra, int width, int height, int stride, string? scene)
        => AssetsRegion(scene, width, height) is { } r
            ? Read(bgra, width, height, stride, r.X, r.Y, r.W, r.H) : null;

    public static long? ParseSingleAmount(string? text)
    {
        // RecognizeAsync may return "2 ， 588 ， 053". Join separator spacing,
        // never independent digit tokens (e.g. an icon's "0" plus the balance).
        var normalized = Regex.Replace(text ?? "", @"(?<=\d)\s*[,，]\s*(?=\d)", ",");
        var matches = Regex.Matches(normalized, @"-?\d[\d,，]*");
        if (matches.Count != 1) return null;
        var token = matches[0].Value.Replace('，', ',');
        if (!Regex.IsMatch(token, @"^(?:\d+|\d{1,3}(?:,\d{3})+)$")) return null;
        var digits = token.Replace(",", "");
        return long.TryParse(digits, out var amount) && amount is >= 0 and <= 9_999_999 ? amount : null;
    }

    public static long? Read(ReadOnlyMemory<byte> bgra, int width, int height, int stride, int x, int y, int w, int h)
    {
        if (w < 3 || h < 3 || x < 0 || y < 0 || x + w > width || y + h > height) return null;
        var cropped = new byte[w * h * 4];
        var source = bgra.Span;
        for (int row = 0; row < h; row++)
            source.Slice((y + row) * stride + x * 4, w * 4).CopyTo(cropped.AsSpan(row * w * 4));
        SoftwareBitmap bitmap;
        try
        {
            bitmap = SoftwareBitmap.CreateCopyFromBuffer(cropped.AsBuffer(), BitmapPixelFormat.Bgra8, w, h,
                BitmapAlphaMode.Premultiplied);
        }
        catch (Exception) { return null; }
        using (bitmap)
        {
            try
            {
                return Engine.Value is { } engine
                    ? ParseSingleAmount(engine.RecognizeAsync(bitmap).AsTask().GetAwaiter().GetResult().Text) : null;
            }
            catch (Exception) { return null; }
        }
    }
}
