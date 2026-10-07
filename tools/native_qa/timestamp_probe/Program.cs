using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;
using Windows.Graphics.Capture;
using WinRT;

internal static class Program
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private static long WorkDeadline;
    private static bool Stop => Clock().Ns >= WorkDeadline;
    private static void Emit(object item) { Console.WriteLine(JsonSerializer.Serialize(item, Json)); Console.Out.Flush(); }
    private sealed record Sample(long Ticks, long Frequency, long Ns, int Thread);
    private static Sample Clock()
    {
        var ticks = Stopwatch.GetTimestamp(); var f = Stopwatch.Frequency;
        return new(ticks, f, (ticks / f) * 1_000_000_000L + (ticks % f) * 1_000_000_000L / f, Environment.CurrentManagedThreadId);
    }

    [STAThread]
    public static int Main(string[] args)
    {
        Emit(new { kind = "ready", clock = Clock() });
        using var go = JsonDocument.Parse(Console.ReadLine() ?? throw new Exception("missing-GO"));
        if (go.RootElement.GetProperty("command").GetString() != "GO") return 2;
        WorkDeadline = go.RootElement.GetProperty("workDeadlineNs").GetInt64();
        var hostDir = Path.GetFullPath(args[0]);
        AssemblyLoadContext.Default.Resolving += (_, name) => {
            var path = Path.Combine(hostDir, name.Name + ".dll");
            return File.Exists(path) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(path) : null;
        };
        object? capture = null;
        string? failure = null;
        int attempts = 0, arrivals = 0;
        var observations = new List<object>();
        using var window = new SyntheticWindow();
        try
        {
            if (Stop) throw new TimeoutException("work-deadline-before-window");
            window.Show(); window.Update();
            var hwnd = window.Handle;
            var monitor = Assembly.LoadFrom(Path.Combine(hostDir, "NteHost.WindowMonitor.dll"));
            var reader = Activator.CreateInstance(monitor.GetType("NteHost.WindowMonitor.WindowIdentityReader", true)!)!;
            var identity = reader.GetType().GetMethod("Read")!.Invoke(reader, new object[] { hwnd.ToInt64() })!;
            bool Same() => !window.IsDisposed && window.Handle == hwnd &&
                (bool)reader.GetType().GetMethod("IsStillSameWindow")!.Invoke(reader, new object[] { identity, true })!;
            var assembly = Assembly.LoadFrom(Path.Combine(hostDir, "WgcLiveHarness.dll"));
            var type = assembly.GetType("WgcLiveHarness.WgcWindowCapture", true)!;
            if (Stop || !Same()) throw new Exception("own-window-invalid-before-construct");
            Emit(new { kind = "construct", ownHwnd = hwnd.ToInt64(), pid = Environment.ProcessId, identity });
            capture = type.GetConstructor(new[] { typeof(IntPtr) })!.Invoke(new object[] { hwnd });
            var pool = (Direct3D11CaptureFramePool)type.GetField("_framePool", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(capture)!;
            var session = (GraphicsCaptureSession)type.GetField("_session", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(capture)!;
            if (Windows.Foundation.Metadata.ApiInformation.IsPropertyPresent("Windows.Graphics.Capture.GraphicsCaptureSession", "IsCursorCaptureEnabled"))
                session.IsCursorCaptureEnabled = false;
            pool.FrameArrived += (_, _) => Interlocked.Increment(ref arrivals);
            var mapping = type.GetMethod("IsClientAreaMappingCurrent")!;
            bool Map() => (bool)mapping.Invoke(capture, null)!;
            if (Stop || !Same() || !Map()) throw new Exception("own-window-or-mapping-invalid");
            // The unique marker is painted after ONE unchanged request gate.
            // New content, not arrival order, proves causality for this fixture.
            var request = Clock();
            window.Counter = 1; window.Invalidate(); window.Update();
            var readback = type.GetMethod("ReadBack", BindingFlags.Instance | BindingFlags.NonPublic)!;
            bool futureFound = false;
            while (attempts < 3 && !Stop)
            {
                attempts++;
                var attemptDeadline = Math.Min(WorkDeadline, Clock().Ns + 2_000_000_000L);
                Direct3D11CaptureFrame? frame = null;
                Sample beforeDequeue = Clock(), afterDequeue = beforeDequeue;
                while (frame is null && Clock().Ns < attemptDeadline)
                {
                    Application.DoEvents();
                    if (!Same() || !Map()) throw new Exception("own-window-or-mapping-invalid-before-dequeue");
                    beforeDequeue = Clock(); frame = pool.TryGetNextFrame(); afterDequeue = Clock();
                    if (frame is null) Thread.Sleep(5);
                }
                if (frame is null) throw new TimeoutException("bounded-frame-request-timeout");
                using (frame)
                {
                    if (Stop) throw new TimeoutException("work-deadline-before-getters");
                    var projectedBefore = Clock(); var projectedTicks = frame.SystemRelativeTime.Ticks; var projectedAfter = Clock();
                    var nativeBefore = Clock(); var raw = RawDuration(frame); var nativeAfter = Clock();
                    var repeatedBefore = Clock(); var projectedAgain = frame.SystemRelativeTime.Ticks; var rawAgain = RawDuration(frame); var repeatedAfter = Clock();
                    var sourceNs = checked(raw.Duration * 100L);
                    var aheadNs = sourceNs - projectedAfter.Ns;
                    futureFound = aheadNs > 0;
                    var getterEvidence = new { kind = "same-frame-getters", attempt = attempts, request, beforeDequeue, afterDequeue,
                        projectedBefore, projectedTicks, projectedAfter, nativeBefore, nativeAfter, raw,
                        repeatedBefore, projectedAgain, rawAgain, repeatedAfter, sourceNs, aheadNs,
                        sameFrameIdentity = raw.SameIdentity && rawAgain.SameIdentity && raw.FrameUnknown == rawAgain.FrameUnknown,
                        sameValue = projectedTicks == raw.Duration && projectedAgain == projectedTicks && rawAgain.Duration == raw.Duration };
                    Emit(getterEvidence);
                    if (!raw.SameIdentity || !rawAgain.SameIdentity || raw.FrameUnknown != rawAgain.FrameUnknown
                        || projectedTicks != raw.Duration || projectedAgain != projectedTicks || rawAgain.Duration != raw.Duration)
                        throw new Exception("same-frame-projection-or-value-mismatch");
                    if (Stop || !Same() || !Map()) throw new Exception("own-window-or-mapping-invalid-before-diagnostic-readback");
                    // Diagnostic readback ONLY of this synthetic window. A future
                    // value is never admitted through production FRAME/SOURCE.
                    var pixelsFrame = readback.Invoke(capture, new object?[] { frame, null })!;
                    T Value<T>(string name) => (T)pixelsFrame.GetType().GetProperty(name)!.GetValue(pixelsFrame)!;
                    var pixels = Value<byte[]>("Pixels");
                    var marker = window.Decode(pixels, Value<int>("Stride"));
                    var causal = marker.Nonce == window.Nonce && marker.Counter == 1 && window.PaintBegin.Ns > request.Ns;
                    if (Stop || !Same() || !Map()) throw new Exception("own-window-or-mapping-invalid-after-diagnostic-readback");
                    var observation = new { kind = "observation", attempt = attempts, getterEvidence,
                        ownHwnd = hwnd.ToInt64(), marker = new { marker.Nonce, marker.Counter }, expectedNonce = window.Nonce,
                        paintBegin = window.PaintBegin, paintEnd = window.PaintEnd,
                        requestAfterRenderCausalityProved = causal, diagnosticReadbackClock = Clock(),
                        readbackSourceTimestampNs = Value<long>("SourceTimestampNs"),
                        pixelSha256 = Convert.ToHexString(SHA256.HashData(pixels)).ToLowerInvariant(),
                        acceptedBusinessFrame = false, mappingCurrent = true };
                    observations.Add(observation); Emit(observation);
                    if (futureFound) break;
                }
            }
            if (observations.Count == 0) failure = "no-diagnostic-frame";
        }
        catch (Exception ex)
        {
            while (ex is TargetInvocationException && ex.InnerException is not null) ex = ex.InnerException;
            failure = ex.GetType().Name + ": " + ex.Message;
        }
        finally
        {
            Emit(new { kind = "disposing", attempts, failure });
            try { (capture as IDisposable)?.Dispose(); }
            catch (Exception ex) { failure ??= "dispose:" + ex.Message; }
            window.Close();
        }
        Emit(new { kind = "result", attempts, frameArrivals = arrivals, observations, failure,
            completedClock = Clock(), ownWindowClosed = window.IsDisposed,
            productionAdmissionChanged = false, gameCapture = false, desktopCapture = false, gameInput = false,
            sdk = typeof(Direct3D11CaptureFrame).Assembly.FullName,
            sdkSha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(Direct3D11CaptureFrame).Assembly.Location))).ToLowerInvariant(),
            projectionRuntime = typeof(IWinRTObject).Assembly.FullName });
        return failure is null ? 0 : 1;
    }

    private sealed record AbiResult(long Duration, long FrameUnknown, long InterfaceUnknown, bool SameIdentity);
    private static unsafe AbiResult RawDuration(Direct3D11CaptureFrame frame)
    {
        var original = ((IWinRTObject)frame).NativeObject.ThisPtr;
        var iid = new Guid("FA50C623-38DA-4B32-ACF3-FA9734AD800E");
        var unknown = new Guid("00000000-0000-0000-C000-000000000046");
        nint face = 0, first = 0, second = 0;
        try
        {
            Marshal.ThrowExceptionForHR(Marshal.QueryInterface(original, ref iid, out face));
            Marshal.ThrowExceptionForHR(Marshal.QueryInterface(original, ref unknown, out first));
            Marshal.ThrowExceptionForHR(Marshal.QueryInterface(face, ref unknown, out second));
            var vtable = *(nint**)face;
            var getter = (delegate* unmanaged[Stdcall]<nint, long*, int>)vtable[7];
            long duration;
            Marshal.ThrowExceptionForHR(getter(face, &duration));
            GC.KeepAlive(frame);
            return new(duration, first.ToInt64(), second.ToInt64(), first == second);
        }
        finally { if (second != 0) Marshal.Release(second); if (first != 0) Marshal.Release(first); if (face != 0) Marshal.Release(face); }
    }

    private sealed class SyntheticWindow : Form
    {
        public uint Nonce { get; } = BitConverter.ToUInt32(RandomNumberGenerator.GetBytes(4));
        public int Counter { get; set; }
        public Sample PaintBegin { get; private set; } = Clock();
        public Sample PaintEnd { get; private set; } = Clock();
        protected override bool ShowWithoutActivation => true;
        public SyntheticWindow()
        {
            Text = "NTE synthetic timestamp probe"; ClientSize = new Size(640, 360);
            StartPosition = FormStartPosition.Manual; Location = new Point(24, 24);
            ShowInTaskbar = false; FormBorderStyle = FormBorderStyle.FixedToolWindow;
            BackColor = Color.White; DoubleBuffered = true;
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            PaintBegin = Clock(); base.OnPaint(e);
            ulong code = ((ulong)Nonce << 16) | (uint)Counter;
            for (int i = 0; i < 48; i++) e.Graphics.FillRectangle(((code >> i) & 1) == 1 ? Brushes.Red : Brushes.Blue, 8 + i * 6, 8, 6, 16);
            PaintEnd = Clock();
        }
        public (uint Nonce, int Counter) Decode(byte[] bgra, int stride)
        {
            ulong code = 0;
            for (int i = 0; i < 48; i++)
            {
                var index = 16 * stride + (11 + i * 6) * 4;
                if (bgra[index + 2] > 240 && bgra[index] < 10) code |= 1UL << i;
                else if (!(bgra[index] > 240 && bgra[index + 2] < 10)) throw new Exception("synthetic-marker-not-decodable");
            }
            return ((uint)(code >> 16), (int)(code & 65535));
        }
    }
}
