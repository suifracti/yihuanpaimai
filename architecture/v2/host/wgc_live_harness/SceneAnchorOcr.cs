using System.Runtime.InteropServices.WindowsRuntime;
using System.Text.RegularExpressions;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using NteHost.DomainActions;

namespace WgcLiveHarness;

/// <summary>Digit readback for the scene-anchor decoder. A missing or ambiguous line is null.</summary>
static class SceneAnchorOcr
{
    static readonly Lazy<OcrEngine?> Engine = new(OcrEngine.TryCreateFromUserProfileLanguages);
    static readonly Lazy<OcrEngine?> AmountEngine = new(() => OcrEngine.TryCreateFromLanguage(new Windows.Globalization.Language("en-US")));

    // The lobby asset bar is left of the in-auction bar. Exclude its currency
    // icon: Windows OCR can read that icon as an additional zero.
    public static (int X, int Y, int W, int H)? AssetsRegion(string? scene, int width, int height)
    {
        if (width != 1920 || height != 1080) return null;
        return scene switch
        {
            "LOBBY" => (1340, 20, 170, 65),
            "TOOL_SETUP" or "TOOL_GROUPS" => (335, 28, 170, 65),
            "AUCTION" or "AUCTION_READY" or "INSTRUMENT_LIST" or "INSTRUMENT_GOLD_SELECTED" or "INSTRUMENT_PURPLE_SELECTED"
                => (1695, 25, 180, 65),
            _ => null
        };
    }

    public static long? ReadAssets(ReadOnlyMemory<byte> bgra, int width, int height, int stride, string? scene)
        => ParseAssets(ReadAssetsText(bgra, width, height, stride, scene));

    public static long? ParseAssets(string? text)
    {
        // Windows OCR also represents the visible comma groups as spaces.
        // Accept complete groups of three only, within this single balance ROI.
        string value=Regex.Replace((text ?? "").Trim(),@"\s*[,，]\s*",",");
        if (Regex.IsMatch(value,@"^\d{1,3}(?:(?:,|\s+)\d{3})+$"))
            value=Regex.Replace(value,@"\s+",",");
        return ParseSingleAmount(value);
    }

    public static string? ReadAssetsText(ReadOnlyMemory<byte> bgra, int width, int height, int stride, string? scene)
    {
        if (AssetsRegion(scene, width, height) is not { } r) return null;
        // Small bold balance digits lost the 7 in the real 2,732,464 frame.
        // Enlarge the same crop; do not repair or guess missing OCR digits.
        return ReadEnlargedText(bgra,width,height,stride,r.X,r.Y,r.W,r.H);
    }

    public static string? ReadCommittedText(ReadOnlyMemory<byte> bgra, int width, int height, int stride,
        int x,int y,int cropWidth,int cropHeight)
        // This button contains Latin digits, decimal point and K/M only. Use
        // the matching OCR language, without guessing or repairing characters.
        => ReadEnlargedText(bgra,width,height,stride,x,y,cropWidth,cropHeight,latin:true);

    static string? ReadEnlargedText(ReadOnlyMemory<byte> bgra, int width, int height, int stride,
        int left,int top,int cropWidth,int cropHeight,bool latin=false)
    {
        if(left<0 || top<0 || cropWidth<3 || cropHeight<3 || left+cropWidth>width || top+cropHeight>height) return null;
        const int scale=3;
        int w=cropWidth*scale,h=cropHeight*scale;
        var enlarged=new byte[w*h*4];
        for(int y=0;y<h;y++) for(int x=0;x<w;x++)
            bgra.Span.Slice((top+y/scale)*stride+(left+x/scale)*4,4)
                .CopyTo(enlarged.AsSpan((y*w+x)*4,4));
        return ReadTextWithEngine(enlarged,w,h,w*4,0,0,w,h,latin ? AmountEngine.Value : Engine.Value);
    }

    public static InstrumentStock ReadInstruments(NativeDomainFrame f, string scene, int counterY = 235)
    {
        if (scene is "LOBBY" or "TOOL_GROUPS") return new(null, null, null,
            ReadAssets(f.Pixels, f.Geometry.Width, f.Geometry.Height, f.Stride, scene));
        long? Price(int x,int y,int w,int h) => ParseSingleAmount(Regex.Replace(
            ReadText(f.Pixels,f.Geometry.Width,f.Geometry.Height,f.Stride,x,y,w,h) ?? "", @"(?<=\d)\s+(?=\d{3}(?:\D|$))", ","));
        if (scene == "TOOL_REFILL_CONFIRM") return new(null, null, Price(715, 513, 485, 60), null);
        if (scene == "ENTRY_FEE") {
            var text = Regex.Replace(ReadText(f.Pixels,f.Geometry.Width,f.Geometry.Height,f.Stride,620,500,690,90) ?? "",@"\s","");
            var fee = Regex.Match(text,@"入场费(\d+(?:[,，]\d{3})*)");
            return new(null,null,fee.Success ? ParseSingleAmount(fee.Groups[1].Value) : null,null);
        }
        // Isolate the white stock label from its dark outline/background. This
        // small counter otherwise produces an empty Windows OCR result.
        const int cw=115,ch=55,scale=3;
        var counter=new byte[cw*ch*scale*scale*4];
        for(int y=0;y<ch*scale;y++) for(int x=0;x<cw*scale;x++) {
            int src=(counterY+y/scale)*f.Stride+(320+x/scale)*4, dst=(y*cw*scale+x)*4;
            var p=f.Pixels.Span;
            byte ink=p[src]>190 && p[src+1]>190 && p[src+2]>190?(byte)0:(byte)255;
            counter[dst]=counter[dst+1]=counter[dst+2]=ink; counter[dst+3]=255;
        }
        int? count=(int?)Read(counter,cw*scale,ch*scale,cw*scale*4,0,0,cw*scale,ch*scale);
        return new(count, count, Price(421, 927, 145, 66), ReadAssets(f.Pixels, f.Geometry.Width, f.Geometry.Height, f.Stride, scene));
    }

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
        => ParseSingleAmount(ReadText(bgra, width, height, stride, x, y, w, h));

    public static string? ReadText(ReadOnlyMemory<byte> bgra, int width, int height, int stride, int x, int y, int w, int h)
        => ReadTextWithEngine(bgra,width,height,stride,x,y,w,h,Engine.Value);

    static string? ReadTextWithEngine(ReadOnlyMemory<byte> bgra, int width, int height, int stride, int x, int y, int w, int h,
        OcrEngine? engine)
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
                return engine?.RecognizeAsync(bitmap).AsTask().GetAwaiter().GetResult().Text;
            }
            catch (Exception) { return null; }
        }
    }
}
