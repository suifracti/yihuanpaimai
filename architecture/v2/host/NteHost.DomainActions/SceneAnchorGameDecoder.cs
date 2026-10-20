using System.IO.Compression;
using System.Numerics;
using System.Text.Json;

namespace NteHost.DomainActions;

/// <summary>
/// Locates domain controls by the published scene-anchor templates. A missing
/// directory or a frame without a unique match returns null, which keeps the
/// host on NOT_CONNECTED. Search rectangles are not click coordinates.
/// </summary>
public sealed class SceneAnchorGameDecoder : IGameDomainFrameDecoder
{
    public const string VerifiedGameProfile = "NTE_VERIFIED_GAME_V1";
    public const string OwnCommittedBidIdentity = "own-committed-bid";
    public const int OwnCommittedBidSlot = 0;
    public delegate long? AmountSample(ReadOnlyMemory<byte> bgra, int width, int height, int stride,
        int x, int y, int w, int h);

    public readonly record struct GrayImage(byte[] Pixels, int Width, int Height)
    {
        // Preprocess each reference once. Integer lanes preserve the exact NCC
        // dot product; this is not a reduced-resolution or looser matcher.
        internal int[] Samples { get; } = Array.ConvertAll(Pixels, value => (int)value);
    }
    readonly record struct Box(int X, int Y, int Right, int Bottom);
    sealed record TemplateControl(DomainPrimitive Primitive, string File, Box Search, GrayImage Image, bool Optional = false);
    sealed record Witness(string File, Box Search, GrayImage Image);
    sealed record SceneSpec(string Scene, Witness[] Witnesses, TemplateControl[] Controls, Box? AmountAbove);
    sealed record Catalog(int ReferenceWidth, int ReferenceHeight, double Threshold, SceneSpec[] Scenes, Box? Committed,
        Witness? GoldAverage);

    readonly Catalog? catalog;
    readonly Dictionary<string, GrayImage> templates;
    public bool Ready { get; }
    public AmountSample? ReadAmount { get; set; }
    public AmountSample? ReadCommittedAmount { get; set; }
    public Func<NativeDomainFrame, string, InstrumentStock?>? ReadInstruments { get; set; }

    SceneAnchorGameDecoder(Catalog? catalog, Dictionary<string, GrayImage> templates)
    {
        this.catalog = catalog;
        this.templates = templates;
        Ready = catalog is not null;
    }

    public static bool OperatorAllowsGameInput(string? value) =>
        string.Equals(value, "1", StringComparison.Ordinal);

    public static SceneAnchorGameDecoder Load(string directory)
    {
        var templates = new Dictionary<string, GrayImage>(StringComparer.OrdinalIgnoreCase);
        try
        {
            var jsonPath = Path.Combine(directory, "domain_controls.json");
            if (!File.Exists(jsonPath)) return new(null, templates);
            using var doc = JsonDocument.Parse(File.ReadAllText(jsonPath));
            var root = doc.RootElement;
            int refW = root.GetProperty("referenceWidth").GetInt32();
            int refH = root.GetProperty("referenceHeight").GetInt32();
            double threshold = root.GetProperty("threshold").GetDouble();
            if (refW < 16 || refH < 16 || threshold is <= 0 or > 1) return new(null, templates);
            var scenes = new List<SceneSpec>();
            foreach (var scene in root.GetProperty("scenes").EnumerateArray())
            {
                var witnesses = new List<Witness>();
                if (scene.TryGetProperty("witnesses", out var witnessNode))
                {
                    foreach (var item in witnessNode.EnumerateArray())
                    {
                        var image = LoadTemplate(directory, item.GetProperty("template").GetString()!, templates);
                        if (image is null) return new(null, templates);
                        witnesses.Add(new(item.GetProperty("template").GetString()!, ReadBox(item.GetProperty("search")), image.Value));
                    }
                }
                var controls = new List<TemplateControl>();
                foreach (var item in scene.GetProperty("controls").EnumerateArray())
                {
                    if (!Enum.TryParse<DomainPrimitive>(item.GetProperty("primitive").GetString(), out var primitive))
                        return new(null, templates);
                    var image = LoadTemplate(directory, item.GetProperty("template").GetString()!, templates);
                    if (image is null) return new(null, templates);
                    controls.Add(new(primitive, item.GetProperty("template").GetString()!, ReadBox(item.GetProperty("search")), image.Value,
                        item.TryGetProperty("optional", out var optional) && optional.GetBoolean()));
                }
                Box? amount = null;
                if (scene.TryGetProperty("amountAboveSubmit", out var amountNode))
                    amount = new(amountNode.GetProperty("dx").GetInt32(), amountNode.GetProperty("dy").GetInt32(),
                        amountNode.GetProperty("width").GetInt32(), amountNode.GetProperty("height").GetInt32());
                scenes.Add(new(scene.GetProperty("scene").GetString()!, witnesses.ToArray(), controls.ToArray(), amount));
            }
            Box? committed = root.TryGetProperty("committedSearch", out var committedNode) ? ReadBox(committedNode) : null;
            Witness? goldAverage = null;
            if (root.TryGetProperty("goldAverageWitness", out var goldNode))
            {
                string file = goldNode.GetProperty("template").GetString()!;
                var image = LoadTemplate(directory, file, templates);
                if (image is null) return new(null, templates);
                goldAverage = new(file, ReadBox(goldNode.GetProperty("search")), image.Value);
            }
            if (scenes.Any(s => s.Scene == "TOOL_SETUP")
                && LoadTemplate(directory, "tool_used_badge.png", templates) is null) return new(null, templates);
            return new(new(refW, refH, threshold, scenes.ToArray(), committed, goldAverage), templates);
        }
        catch (Exception ex) when (ex is IOException or JsonException or KeyNotFoundException or InvalidOperationException
            or FormatException or ArgumentException)
        {
            return new(null, templates);
        }
    }

    public bool TryGetTemplate(string fileName, out GrayImage image) => templates.TryGetValue(fileName, out image);

    public static void PaintGray(byte[] bgra, int stride, int x, int y, GrayImage image)
    {
        for (int row = 0; row < image.Height; row++)
        {
            int destination = (y + row) * stride + x * 4;
            int source = row * image.Width;
            for (int col = 0; col < image.Width; col++)
            {
                byte gray = image.Pixels[source + col];
                bgra[destination] = gray;
                bgra[destination + 1] = gray;
                bgra[destination + 2] = gray;
                bgra[destination + 3] = 255;
                destination += 4;
            }
        }
    }

    public DecodedDomainFrame? Decode(NativeDomainFrame frame)
    {
        var catalog = this.catalog;
        if (catalog is null || frame.Geometry.Width < 16 || frame.Geometry.Height < 16) return null;
        var gray = ToGray(frame.Pixels.Span, frame.Geometry.Width, frame.Geometry.Height, frame.Stride);
        SceneSpec? settlement = Scene(catalog, "SETTLEMENT");
        SceneSpec? auction = Scene(catalog, "AUCTION");
        SceneSpec? lobby = Scene(catalog, "LOBBY");
        var found = new List<(TemplateControl Control, int Left, int Top, int Width, int Height)>();
        string? scene = null;
        if (settlement is not null && AllWitnesses(gray, frame, catalog, settlement) && Collect(gray, frame, catalog, settlement, found))
            scene = "SETTLEMENT";
        else
        {
            foreach (string name in new[] { "TOOL_REFILL_CONFIRM", "TOOL_SETUP", "LOBBY", "INSTRUMENT_GOLD_SELECTED", "INSTRUMENT_LIST", "AUCTION", "AUCTION_READY" })
            {
                var spec = Scene(catalog, name);
                if (spec is null || !AllWitnesses(gray, frame, catalog, spec)) continue;
                if (spec.Controls.Length == 0 ? spec.Witnesses.Length > 0 : Collect(gray, frame, catalog, spec, found))
                { scene = name; break; }
            }
        }
        if (scene is null && SeatStripBright(gray, frame.Geometry.Width, frame.Geometry.Height))
            scene = frame.Scope.Round == 1 ? "AUCTION_R1" : "AUCTION";
        if (scene is null) return null;
        if (scene == "AUCTION" && auction is not null)
            AddAmountFocus(gray, frame, auction, found);
        var controls = found.Select(item => Anchor(item.Control.Primitive, item.Left, item.Top, item.Width, item.Height, frame)).ToArray();
        long? amount = null;
        long? committed = null;
        if (scene is "AUCTION" or "AUCTION_R1" or "AUCTION_READY")
        {
            var focus = found.FirstOrDefault(item => item.Control.Primitive == DomainPrimitive.FocusAmountField);
            if (focus.Control is not null && ReadAmount is not null)
                amount = ReadSample(ReadAmount, frame, focus.Left, focus.Top, focus.Width, focus.Height);
            bool panelOpen = found.Any(item => item.Control.Primitive == DomainPrimitive.SubmitBid);
            if (!panelOpen && catalog.Committed is Box committedBox && ReadCommittedAmount is not null)
            {
                var scaled = Scale(committedBox, frame.Geometry.Width, frame.Geometry.Height, catalog);
                committed = ReadSample(ReadCommittedAmount, frame, scaled.X, scaled.Y,
                    scaled.Right - scaled.X, scaled.Bottom - scaled.Y);
            }
        }
        CapturedOwnBid? own = committed is > 0 and <= 9_999_999
            ? new(OwnCommittedBidSlot, OwnCommittedBidIdentity, committed.Value, true, frame.EvidenceRef)
            : null;
        bool goldVisible = catalog.GoldAverage is { } gold && Match(gray, frame.Geometry.Width, frame.Geometry.Height,
            gold.Image, Scale(gold.Search, frame.Geometry.Width, frame.Geometry.Height, catalog), catalog.Threshold, out _, out _);
        var stock = scene is "LOBBY" or "TOOL_SETUP" or "TOOL_REFILL_CONFIRM" ? ReadInstruments?.Invoke(frame, scene) : null;
        if (scene == "TOOL_SETUP" && stock is not null && TryGetTemplate("tool_used_badge.png", out var used))
        {
            bool Used(Box box) => Match(gray, frame.Geometry.Width, frame.Geometry.Height, used,
                Scale(box, frame.Geometry.Width, frame.Geometry.Height, catalog), catalog.Threshold, out _, out _);
            stock = stock with {
                GoldAverage = stock.GoldAverage is { } g ? Math.Max(0, g - (Used(new(960, 806, 1070, 850)) ? 1 : 0)) : null,
                PurpleCount = stock.PurpleCount is { } p ? Math.Max(0, p - (Used(new(960, 675, 1070, 718)) ? 1 : 0)) : null };
        }
        return new(scene, frame.Scope.Round, frame.Scope.MatchId, frame.Scope.MatchGeneration,
            own, amount is >= 0 and <= 9_999_999 ? amount : null, controls) { GoldAverageVisible = goldVisible, Instruments = stock };
    }

    void AddAmountFocus(byte[] gray, NativeDomainFrame frame, SceneSpec auction,
        List<(TemplateControl Control, int Left, int Top, int Width, int Height)> found)
    {
        if (auction.AmountAbove is not Box offset) return;
        var submit = found.FirstOrDefault(item => item.Control.Primitive == DomainPrimitive.SubmitBid);
        if (submit.Control is null) return;
        int left = submit.Left + Scale(offset.X, frame.Geometry.Width, catalog!.ReferenceWidth);
        int top = submit.Top + Scale(offset.Y, frame.Geometry.Height, catalog.ReferenceHeight);
        int width = Math.Max(3, Scale(offset.Right, frame.Geometry.Width, catalog.ReferenceWidth));
        int height = Math.Max(3, Scale(offset.Bottom, frame.Geometry.Height, catalog.ReferenceHeight));
        if (!Inside(left, top, width, height, frame.Geometry.Width, frame.Geometry.Height)) return;
        var bright = BrightUnion(gray, frame.Geometry.Width, left, top, width, height);
        if (bright is (int x, int y, int w, int h))
            found.Add((new(DomainPrimitive.FocusAmountField, "", default, default), x, y, w, h));
        else
            found.Add((new(DomainPrimitive.FocusAmountField, "", default, default), left, top, width, height));
    }

    static long? ReadSample(AmountSample sample, NativeDomainFrame frame, int x, int y, int w, int h)
    {
        if (!Inside(x, y, w, h, frame.Geometry.Width, frame.Geometry.Height)) return null;
        try { return sample(frame.Pixels, frame.Geometry.Width, frame.Geometry.Height, frame.Stride, x, y, w, h); }
        catch { return null; }
    }

    bool Collect(byte[] gray, NativeDomainFrame frame, Catalog catalog, SceneSpec spec,
        List<(TemplateControl Control, int Left, int Top, int Width, int Height)> found)
    {
        if (spec.Controls.Length == 0) return false;
        var matches = new List<(TemplateControl Control, int Left, int Top, int Width, int Height)>();
        foreach (var control in spec.Controls)
        {
            if (!Match(gray, frame.Geometry.Width, frame.Geometry.Height, control.Image,
                Scale(control.Search, frame.Geometry.Width, frame.Geometry.Height, catalog), catalog.Threshold,
                out int left, out int top))
            { if (control.Optional) continue; return false; }
            int width = Math.Max(3, Scale(control.Image.Width, frame.Geometry.Width, catalog.ReferenceWidth));
            int height = Math.Max(3, Scale(control.Image.Height, frame.Geometry.Height, catalog.ReferenceHeight));
            if (!Inside(left, top, width, height, frame.Geometry.Width, frame.Geometry.Height)) return false;
            matches.Add((control, left, top, width, height));
        }
        found.AddRange(matches);
        // A witnessed panel remains open even when an optional item is absent.
        // Only actually matched controls become clickable anchors.
        return matches.Count > 0 || spec.Witnesses.Length > 0;
    }

    bool AllWitnesses(byte[] gray, NativeDomainFrame frame, Catalog catalog, SceneSpec spec)
    {
        foreach (var witness in spec.Witnesses)
        {
            if (!Match(gray, frame.Geometry.Width, frame.Geometry.Height, witness.Image,
                Scale(witness.Search, frame.Geometry.Width, frame.Geometry.Height, catalog), catalog.Threshold,
                out _, out _)) return false;
        }
        return true;
    }

    static bool Match(byte[] gray, int width, int height, GrayImage template, Box search, double threshold,
        out int left, out int top)
    {
        left = 0; top = 0;
        int cropW = search.Right - search.X;
        int cropH = search.Bottom - search.Y;
        if (cropW < template.Width || cropH < template.Height || search.X < 0 || search.Y < 0
            || search.Right > width || search.Bottom > height) return false;
        var crop = new int[cropW * cropH];
        int prefixWidth = cropW + 1;
        var sums = new long[prefixWidth * (cropH + 1)];
        var squares = new long[sums.Length];
        for (int row = 0; row < cropH; row++)
        {
            long sum = 0, square = 0;
            for (int col = 0; col < cropW; col++)
            {
                int value = gray[(search.Y + row) * width + search.X + col];
                crop[row * cropW + col] = value;
                sum += value; square += value * value;
                int p = (row + 1) * prefixWidth + col + 1;
                sums[p] = sums[p - prefixWidth] + sum;
                squares[p] = squares[p - prefixWidth] + square;
            }
        }
        double best = threshold - 1e-6;
        int bestX = 0, bestY = 0;
        int limitX = cropW - template.Width;
        int limitY = cropH - template.Height;
        long templateSum = 0, templateSumSq = 0;
        for (int i = 0; i < template.Pixels.Length; i++)
        {
            int value = template.Pixels[i];
            templateSum += value;
            templateSumSq += (long)value * value;
        }
        int count = template.Width * template.Height;
        double templateMean = templateSum / (double)count;
        double templateVar = templateSumSq - templateSum * templateMean;
        if (templateVar < 1) return false;
        int lanes = Vector<int>.Count;
        var samples = template.Samples;
        for (int oy = 0; oy <= limitY; oy++)
        {
            for (int ox = 0; ox <= limitX; ox++)
            {
                int tl = oy * prefixWidth + ox;
                int tr = tl + template.Width;
                int bl = (oy + template.Height) * prefixWidth + ox;
                int br = bl + template.Width;
                long imageSum = sums[br] - sums[bl] - sums[tr] + sums[tl];
                long imageSumSq = squares[br] - squares[bl] - squares[tr] + squares[tl];
                long cross = 0;
                int source = 0;
                for (int row = 0; row < template.Height; row++)
                {
                    int origin = (oy + row) * cropW + ox;
                    int col = 0;
                    if (Vector.IsHardwareAccelerated)
                        for (; col <= template.Width - lanes; col += lanes)
                            cross += Vector.Dot(new Vector<int>(crop, origin + col), new Vector<int>(samples, source + col));
                    for (; col < template.Width; col++)
                    {
                        int image = crop[origin + col];
                        int pixel = samples[source + col];
                        cross += (long)image * pixel;
                    }
                    source += template.Width;
                }
                double imageVar = imageSumSq - imageSum * (imageSum / (double)count);
                if (imageVar < 1) continue;
                double score = (cross - imageSum * templateMean) / Math.Sqrt(templateVar * imageVar);
                if (score > best) { best = score; bestX = ox; bestY = oy; }
            }
        }
        if (best < threshold) return false;
        left = search.X + bestX;
        top = search.Y + bestY;
        return true;
    }

    static (int X, int Y, int W, int H)? BrightUnion(byte[] gray, int width, int left, int top, int regionW, int regionH)
    {
        int minX = int.MaxValue, minY = int.MaxValue, maxX = -1, maxY = -1, area = 0;
        for (int row = 0; row < regionH; row++)
        {
            int origin = (top + row) * width + left;
            for (int col = 0; col < regionW; col++)
            {
                if (gray[origin + col] <= 200) continue;
                area++;
                if (col < minX) minX = col;
                if (row < minY) minY = row;
                if (col > maxX) maxX = col;
                if (row > maxY) maxY = row;
            }
        }
        if (area < 12 || maxX - minX < 2 || maxY - minY < 2) return null;
        return (left + minX, top + minY, maxX - minX + 1, maxY - minY + 1);
    }

    static bool SeatStripBright(byte[] gray, int width, int height)
    {
        int x0 = (int)(width * 0.02), x1 = (int)(width * 0.28);
        int y0 = (int)(height * 0.15), y1 = (int)(height * 0.75);
        if (x1 <= x0 || y1 <= y0) return false;
        int bright = 0, total = 0;
        for (int y = y0; y < y1; y += 2)
        {
            int origin = y * width;
            for (int x = x0; x < x1; x += 2)
            {
                total++;
                if (gray[origin + x] > 140) bright++;
            }
        }
        return total > 0 && bright >= total * 0.20;
    }

    static VisibleControlAnchor Anchor(DomainPrimitive primitive, int left, int top, int width, int height, NativeDomainFrame frame)
    {
        var scope = frame.Scope;
        return new(primitive, left, top, width, height, frame.Geometry, scope.MatchId, scope.MatchGeneration,
            scope.ObservationSessionId, scope.Round, scope.FactsRevision, scope.Window, scope.SourceSequence,
            scope.CapturedNs, scope.SourceQualified, frame.EvidenceRef, VerifiedGameProfile);
    }

    static byte[] ToGray(ReadOnlySpan<byte> bgra, int width, int height, int stride)
    {
        var gray = new byte[width * height];
        for (int y = 0; y < height; y++)
        {
            int source = y * stride;
            int destination = y * width;
            for (int x = 0; x < width; x++)
            {
                int pixel = source + x * 4;
                gray[destination + x] = (byte)Math.Clamp(Math.Round(
                    0.114 * bgra[pixel] + 0.587 * bgra[pixel + 1] + 0.299 * bgra[pixel + 2]), 0, 255);
            }
        }
        return gray;
    }

    static Box Scale(Box box, int width, int height, Catalog catalog) => new(
        Scale(box.X, width, catalog.ReferenceWidth), Scale(box.Y, height, catalog.ReferenceHeight),
        Scale(box.Right, width, catalog.ReferenceWidth), Scale(box.Bottom, height, catalog.ReferenceHeight));
    static int Scale(int value, int size, int reference) => (int)Math.Round(value * (size / (double)reference));
    static bool Inside(int x, int y, int w, int h, int width, int height) =>
        w >= 3 && h >= 3 && x >= 0 && y >= 0 && x + (long)w <= width && y + (long)h <= height;
    static SceneSpec? Scene(Catalog catalog, string name) => catalog.Scenes.FirstOrDefault(scene => scene.Scene == name);
    static Box ReadBox(JsonElement node) => new(node[0].GetInt32(), node[1].GetInt32(), node[2].GetInt32(), node[3].GetInt32());

    static GrayImage? LoadTemplate(string directory, string file, Dictionary<string, GrayImage> cache)
    {
        if (cache.TryGetValue(file, out var cached)) return cached;
        var path = Path.Combine(directory, file);
        if (!File.Exists(path)) return null;
        var image = ReadPngGray(File.ReadAllBytes(path));
        cache[file] = image;
        return image;
    }

    static GrayImage ReadPngGray(byte[] png)
    {
        if (png.Length < 8 || png[0] != 137 || png[1] != 80) throw new InvalidOperationException("PNG_SIGNATURE");
        int cursor = 8;
        int width = 0, height = 0, bitDepth = 0, colorType = 0, interlace = 0;
        using var data = new MemoryStream();
        while (cursor + 8 <= png.Length)
        {
            int length = (png[cursor] << 24) | (png[cursor + 1] << 16) | (png[cursor + 2] << 8) | png[cursor + 3];
            var type = System.Text.Encoding.ASCII.GetString(png, cursor + 4, 4);
            cursor += 8;
            if (length < 0 || cursor + length + 4 > png.Length) throw new InvalidOperationException("PNG_CHUNK");
            if (type == "IHDR")
            {
                width = (png[cursor] << 24) | (png[cursor + 1] << 16) | (png[cursor + 2] << 8) | png[cursor + 3];
                height = (png[cursor + 4] << 24) | (png[cursor + 5] << 16) | (png[cursor + 6] << 8) | png[cursor + 7];
                bitDepth = png[cursor + 8]; colorType = png[cursor + 9]; interlace = png[cursor + 12];
            }
            else if (type == "IDAT") data.Write(png, cursor, length);
            else if (type == "IEND") break;
            cursor += length + 4;
        }
        int channels = colorType switch { 0 => 1, 2 => 3, 4 => 2, 6 => 4, _ => 0 };
        if (width < 1 || height < 1 || bitDepth != 8 || channels == 0 || interlace != 0)
            throw new InvalidOperationException("PNG_UNSUPPORTED");
        data.Position = 0;
        using var zlib = new ZLibStream(data, CompressionMode.Decompress);
        int rowBytes = width * channels;
        var raw = new byte[(rowBytes + 1) * height];
        zlib.ReadExactly(raw);
        var gray = new byte[width * height];
        var previous = new byte[rowBytes];
        var current = new byte[rowBytes];
        for (int row = 0; row < height; row++)
        {
            int filter = raw[row * (rowBytes + 1)];
            int origin = row * (rowBytes + 1) + 1;
            for (int i = 0; i < rowBytes; i++)
            {
                int left = i >= channels ? current[i - channels] : 0;
                int up = previous[i];
                int upperLeft = i >= channels ? previous[i - channels] : 0;
                int value = filter switch
                {
                    0 => raw[origin + i],
                    1 => raw[origin + i] + left,
                    2 => raw[origin + i] + up,
                    3 => raw[origin + i] + ((left + up) >> 1),
                    4 => raw[origin + i] + Paeth(left, up, upperLeft),
                    _ => throw new InvalidOperationException("PNG_FILTER"),
                };
                current[i] = (byte)value;
            }
            for (int x = 0; x < width; x++)
            {
                int pixel = x * channels;
                gray[row * width + x] = channels switch
                {
                    1 or 2 => current[pixel],
                    _ => (byte)Math.Clamp(Math.Round(0.114 * current[pixel + 2] + 0.587 * current[pixel + 1] + 0.299 * current[pixel]), 0, 255),
                };
            }
            (previous, current) = (current, previous);
        }
        return new(gray, width, height);
    }

    static int Paeth(int left, int up, int upperLeft)
    {
        int estimate = left + up - upperLeft;
        int leftDistance = Math.Abs(estimate - left);
        int upDistance = Math.Abs(estimate - up);
        int diagonal = Math.Abs(estimate - upperLeft);
        if (leftDistance <= upDistance && leftDistance <= diagonal) return left;
        return upDistance <= diagonal ? up : upperLeft;
    }
}
