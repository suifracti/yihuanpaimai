using System.Runtime.InteropServices.WindowsRuntime;
using Windows.Graphics.Imaging;
using WgcLiveHarness;

var cases = new (string? Text, long? Expected)[] {
    ("2 ， 588 ， 053", 2588053), ("2,524,575", 2524575), ("251374", 251374),
    ("余额 9 , 999 , 999", 9999999), ("0", 0), (null, null), ("没有余额", null),
    ("0 2 ， 588 ， 053", null), ("123 45", null), ("1, 2", null), ("12,34,567", null),
    ("1,234,", null), ("10,000,000", null), ("-1", null), ("1,000 99", null), ("12.50", null)
};
foreach (var (text, expected) in cases)
    if (SceneAnchorOcr.ParseSingleAmount(text) != expected) throw new Exception($"AMOUNT_PARSE: {text}");
if (SceneAnchorOcr.AssetsRegion("LOBBY", 1920, 1080) != (1340, 20, 170, 65)
    || SceneAnchorOcr.AssetsRegion("AUCTION_READY", 1920, 1080) != (1695, 25, 180, 65)
    || SceneAnchorOcr.AssetsRegion("UNKNOWN", 1920, 1080) is not null
    || SceneAnchorOcr.AssetsRegion("LOBBY", 1280, 720) is not null)
    throw new Exception("SCENE_ASSETS_REGION");
Console.WriteLine($"PASS {cases.Length} amount cases and scene-specific regions (no OCR/capture/input)");
if (args.Contains("--parser-only")) return;

foreach (var (name, expected) in new[] { ("lobby", 2588053L), ("auction", 2524575L) })
{
    var path = Path.GetFullPath($"tests/fixtures/native-funds-{name}.png");
    using var stream = File.OpenRead(path).AsRandomAccessStream();
    var decoder = await BitmapDecoder.CreateAsync(stream);
    using var bitmap = await decoder.GetSoftwareBitmapAsync(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied);
    var buffer = new Windows.Storage.Streams.Buffer((uint)(bitmap.PixelWidth * bitmap.PixelHeight * 4));
    bitmap.CopyToBuffer(buffer);
    var raw = buffer.ToArray();
    var value = SceneAnchorOcr.Read(raw, bitmap.PixelWidth, bitmap.PixelHeight, bitmap.PixelWidth * 4,
        0, 0, bitmap.PixelWidth, bitmap.PixelHeight);
    Console.WriteLine($"real saved {name} numeric crop: expected={expected} actual={value?.ToString() ?? "null"}");
    if (value != expected) throw new Exception($"REAL_{name.ToUpperInvariant()}_BALANCE_UNREADABLE");
}
Console.WriteLine("PASS real saved Windows OCR numeric crop (not an input-qualified frame)");
