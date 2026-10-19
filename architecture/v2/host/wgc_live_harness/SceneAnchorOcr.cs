using System.Runtime.InteropServices.WindowsRuntime;
using System.Text.RegularExpressions;
using NteHost.DomainActions;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;

namespace WgcLiveHarness;

/// <summary>Digit readback for the scene-anchor decoder. A missing or ambiguous line is null.</summary>
static class SceneAnchorOcr
{
    static readonly OcrEngine? Engine = OcrEngine.TryCreateFromUserProfileLanguages();

    public static long? Read(ReadOnlyMemory<byte> bgra, int width, int height, int stride, int x, int y, int w, int h)
    {
        if (Engine is null || w < 3 || h < 3 || x < 0 || y < 0 || x + w > width || y + h > height) return null;
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
        OcrResult result;
        try { result = Engine.RecognizeAsync(bitmap).AsTask().GetAwaiter().GetResult(); }
        catch (Exception) { return null; }
        var matches = Regex.Matches(result.Text ?? "", @"\d[\d,，]*");
        if (matches.Count != 1) return null;
        var digits = Regex.Replace(matches[0].Value, "[,，]", "");
        return long.TryParse(digits, out var amount) && amount is >= 0 and <= 9_999_999 ? amount : null;
    }
}
