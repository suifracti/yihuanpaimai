using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;
using NteHost.Protocol;
using Windows.Graphics.Capture;
using WinRT;

// Isolated QA: invokes the EXISTING selector with a diagnostic clock callback.
// The decision clock is sampled BEFORE extra ABI reads and never replaced.
internal static class Program
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private static readonly object OutputGate = new();
    private static int StopFlag;
    private static long WorkDeadline;
    private static void Emit(object item) { lock (OutputGate) { Console.WriteLine(JsonSerializer.Serialize(item, Json)); Console.Out.Flush(); } }
    private sealed record Sample(long RawTicks, long FrequencyHz, long Nanoseconds, int ManagedThreadId);
    private static Sample Clock()
    {
        var ticks = Stopwatch.GetTimestamp();
        return new(ticks, ProtocolClock.Frequency, ProtocolClock.TicksToNs(ticks), Environment.CurrentManagedThreadId);
    }
    private static bool Stopped() => Volatile.Read(ref StopFlag) != 0;
    private static void Available()
    {
        if (Stopped()) throw new OperationCanceledException("qa-stopped");
        if (ProtocolClock.NowNs() >= WorkDeadline) throw new TimeoutException("qa-work-deadline");
    }
    private static string Error(Exception ex)
    {
        while (ex is TargetInvocationException && ex.InnerException is not null) ex = ex.InnerException;
        return ex.GetType().Name + ": " + ex.Message + $"; HRESULT=0x{ex.HResult:X8}";
    }

    private static Sample InspectAfterComparison(Func<Sample> clock, Action<Sample> inspect)
    {
        var comparison = clock();
        inspect(comparison);
        return comparison;
    }

    public static int Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--selector-check") return SelectorCheck(args[1]);
        Emit(new { kind = "ready", clock = Clock() });
        using var command = JsonDocument.Parse(Console.ReadLine() ?? throw new Exception("missing-GO"));
        var go = command.RootElement;
        if (go.GetProperty("command").GetString() != "GO") return 2;
        WorkDeadline = go.GetProperty("workDeadlineNs").GetInt64();
        var now = ProtocolClock.NowNs();
        if (WorkDeadline <= now || WorkDeadline - now > 8_000_000_000L) throw new Exception("invalid-work-budget");
        if (!IsProcessInJob(GetCurrentProcess(), 0, out var inJob) || !inJob) throw new Exception("not-owned-before-GO");
        var hwnd = go.GetProperty("hwnd").GetInt64();
        var pid = go.GetProperty("pid").GetInt32();
        var instance = go.GetProperty("instance").GetInt64();
        if (hwnd <= 0 || pid <= 0 || instance <= 0) throw new Exception("explicit-target-required");
        var hostDir = Path.GetFullPath(args[0]);
        AssemblyLoadContext.Default.Resolving += (_, name) => {
            var path = Path.Combine(hostDir, name.Name + ".dll");
            return File.Exists(path) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(path) : null;
        };
        new Thread(() => {
            try { while (Console.ReadLine() is { } line) {
                using var input = JsonDocument.Parse(line);
                if (input.RootElement.GetProperty("command").GetString() == "STOP") Interlocked.Exchange(ref StopFlag, 1);
            } } finally { Interlocked.Exchange(ref StopFlag, 1); }
        }) { IsBackground = true, Name = "qa-stop" }.Start();
        object? capture = null;
        string? failure = null;
        string? cleanupFailure = null;
        string? terminationFailure = null;
        object? firstGateFailure = null;
        int attempts = 0, accepted = 0, dequeued = 0, released = 0, comparisons = 0, frameArrivals = 0;
        long lastSourceNs = 0;
        try
        {
            var monitor = Assembly.LoadFrom(Path.Combine(hostDir, "NteHost.WindowMonitor.dll"));
            var readerType = monitor.GetType("NteHost.WindowMonitor.WindowIdentityReader", true)!;
            var reader = Activator.CreateInstance(readerType)!;
            var identity = readerType.GetMethod("Read")!.Invoke(reader, new object[] { hwnd })!;
            T Identity<T>(string name) => (T)identity.GetType().GetProperty(name)!.GetValue(identity)!;
            var specType = monitor.GetType("NteHost.WindowMonitor.TargetWindowSpec", true)!;
            var spec = specType.GetProperty("Default")!.GetValue(null)!;
            if (Identity<long>("Hwnd") != hwnd || Identity<int>("Pid") != pid || Identity<long>("ProcessInstanceToken") != instance
                || !(bool)specType.GetMethod("Matches")!.Invoke(spec, new object[] { Identity<string>("ProcessImageName"), Identity<string>("ClassName") })!)
                throw new Exception("pinned-target-identity-mismatch");
            object CheckTarget(string stage, bool log = false)
            {
                Available();
                var verdict = readerType.GetMethod("Revalidate")!.Invoke(reader, new object?[] { identity, true, null })!;
                var same = (bool)verdict.GetType().GetProperty("IsSame")!.GetValue(verdict)!;
                var rectOk = GetClientRect(new nint(hwnd), out var rect);
                var width = (long)rect.Right - rect.Left; var height = (long)rect.Bottom - rect.Top;
                var minimized = IsIconic(new nint(hwnd));
                var evidence = new { kind = "target", stage, identity, same, rectOk,
                    clientRect = new { rect.Left, rect.Top, rect.Right, rect.Bottom }, width, height, minimized, clock = Clock(), verdict };
                if (log) Emit(evidence);
                if (!same || minimized || !rectOk || width <= 0 || height <= 0 || width > 1920 || height > 1080)
                    throw new Exception("target-ineligible:" + stage);
                return evidence;
            }
            CheckTarget("before-construction", true);
            var host = Assembly.LoadFrom(Path.Combine(hostDir, "WgcLiveHarness.dll"));
            var type = host.GetType("WgcLiveHarness.WgcWindowCapture", true)!;
            var selector = host.GetType("WgcLiveHarness.RequestFrameSelector", true)!.GetMethod("Select")!.MakeGenericMethod(typeof(Direct3D11CaptureFrame));
            var policy = host.GetType("WgcLiveHarness.BackgroundObservationPolicy", true)!;
            capture = type.GetConstructor(new[] { typeof(IntPtr) })!.Invoke(new object[] { new nint(hwnd) });
            var pool = (Direct3D11CaptureFramePool)type.GetField("_framePool", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(capture)!;
            var arrived = (AutoResetEvent)type.GetField("_frameArrived", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(capture)!;
            pool.FrameArrived += (_, _) => Interlocked.Increment(ref frameArrivals);
            var mapping = type.GetMethod("IsClientAreaMappingCurrent")!;
            var readback = type.GetMethod("ReadBack", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var originalMap = type.GetField("_clientArea", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(capture);
            object Map(string stage)
            {
                var target = CheckTarget(stage);
                var before = Clock(); var current = (bool)mapping.Invoke(capture, null)!; var after = Clock();
                if (!current) throw new Exception("mapping-invalid:" + stage);
                return new { stage, target, originalMap, before, after, current };
            }
            var mapAtConstruction = Map("before-requests");
            Emit(new { kind = "construct", targetHwnd = hwnd, pid, instance, mapAtConstruction,
                sdk = typeof(Direct3D11CaptureFrame).Assembly.FullName, runtime = typeof(IWinRTObject).Assembly.FullName,
                osVersion = Environment.OSVersion.VersionString, dotnet = RuntimeInformation.FrameworkDescription,
                abiIid = "FA50C623-38DA-4B32-ACF3-FA9734AD800E", abiSlot = 7, durationUnitNs = 100,
                admission = "existing-selector; no FRAME/SOURCE", clock = Clock() });
            while (attempts < 3)
            {
                Available(); Map("before-request"); attempts++;
                var request = Clock();
                var deadline = Math.Min(WorkDeadline, request.Nanoseconds + 2_000_000_000L);
                Emit(new { kind = "attempt", attempt = attempts, request, deadline });
                Direct3D11CaptureFrame? pending = null;
                Sample? dequeueBefore = null, dequeueAfter = null, propertyBefore = null, propertyAfter = null;
                object? mapBeforeDequeue = null;
                long projectedTicks = 0;
                Direct3D11CaptureFrame? TakeNext()
                {
                    mapBeforeDequeue = Map("before-dequeue");
                    dequeueBefore = Clock(); var frame = pool.TryGetNextFrame(); dequeueAfter = Clock();
                    if (frame is not null) dequeued++;
                    return frame;
                }
                long Source(Direct3D11CaptureFrame frame)
                {
                    propertyBefore = Clock(); projectedTicks = frame.SystemRelativeTime.Ticks; propertyAfter = Clock();
                    pending = frame;
                    return checked(projectedTicks * 100L);
                }
                long DecisionClock() => InspectAfterComparison(Clock, comparison =>
                {
                    if (pending is null) return;
                    var frame = pending; pending = null; comparisons++;
                    var sourceNs = checked(projectedTicks * 100L);
                    var rejection = Stopped() ? "qa-stopped" : comparison.Nanoseconds >= deadline ? "request-deadline"
                        : sourceNs <= 0 ? "source-unavailable" : sourceNs > comparison.Nanoseconds ? "source-in-future" : null;
                    var savedDecision = new { kind = "original-decision", attempt = attempts, dequeued, request, deadline,
                        dequeueBefore, dequeueAfter, mapBeforeDequeue, propertyBefore, projectedTicks, propertyAfter, comparison, sourceNs,
                        aheadNs = sourceNs - comparison.Nanoseconds, rejection };
                    if (rejection is not null) firstGateFailure ??= savedDecision;
                    Emit(savedDecision); // Flush even if a later ABI getter hangs or throws.
                    object? abiEvidence = null;
                    object? mapAfterAbiEvidence = null;
                    string? secondaryError = null;
                    bool consistent = false;
                    try
                    {
                        Available();
                        var abiBefore = Clock(); var raw = ReadAbi(frame); var abiAfter = Clock();
                        Emit(new { kind = "native-property-read", attempt = attempts, dequeued, abiBefore, raw, abiAfter,
                            originalComparison = comparison, originalProjectedTicks = projectedTicks });
                        var repeatBefore = Clock(); var projectedAgain = frame.SystemRelativeTime.Ticks; var projectedAgainAfter = Clock();
                        var rawAgain = ReadAbi(frame); var repeatAfter = Clock();
                        var contentSize = frame.ContentSize;
                        consistent = raw.SameIdentity && rawAgain.SameIdentity && raw.FrameUnknown == rawAgain.FrameUnknown
                            && raw.Duration == projectedTicks && raw.OriginalPointerDuration == projectedTicks
                            && projectedAgain == projectedTicks && rawAgain.Duration == raw.Duration
                            && rawAgain.OriginalPointerDuration == raw.OriginalPointerDuration;
                        abiEvidence = new { abiBefore, raw, abiAfter, repeatBefore, projectedAgain, projectedAgainAfter, rawAgain, repeatAfter,
                            contentSize = new { contentSize.Width, contentSize.Height }, consistent,
                            nativeAheadOfOriginalComparisonNs = checked(raw.Duration * 100L) - comparison.Nanoseconds,
                            nativeAheadOfOwnGetterEndNs = checked(raw.Duration * 100L) - abiAfter.Nanoseconds,
                            projectedAgainAheadOfOwnGetterEndNs = checked(projectedAgain * 100L) - projectedAgainAfter.Nanoseconds };
                        mapAfterAbiEvidence = Map("after-same-frame-abi");
                    }
                    catch (Exception ex) { secondaryError = Error(ex); }
                    Emit(new { kind = "same-frame-abi", attempt = attempts, dequeued, originalDecision = savedDecision, abiEvidence, mapAfterAbiEvidence, secondaryError });
                    // Preserve the original source failure even if evidence collection fails.
                    if (rejection is null && (secondaryError is not null || !consistent))
                        throw new Exception(secondaryError ?? "same-frame-abi-or-projection-mismatch");
                }).Nanoseconds;
                void Release(Direct3D11CaptureFrame frame) { frame.Dispose(); released++; }
                object?[] selectorArgs = { (Func<Direct3D11CaptureFrame?>)TakeNext, (Func<Direct3D11CaptureFrame, long>)Source,
                    (Action<Direct3D11CaptureFrame>)Release, (Func<int, bool>)(ms => arrived.WaitOne(ms)), (Func<long>)DecisionClock,
                    (Func<bool>)Stopped, request.Nanoseconds, deadline, 0 };
                var selected = (Direct3D11CaptureFrame)selector.Invoke(null, selectorArgs)!;
                try
                {
                    Available(); Map("before-readback");
                    var pixelsFrame = readback.Invoke(capture, new object?[] { selected, null })!;
                    T Value<T>(string name) => (T)pixelsFrame.GetType().GetProperty(name)!.GetValue(pixelsFrame)!;
                    Available(); Map("after-readback");
                    var sourceNs = Value<long>("SourceTimestampNs"); var readbackNs = Value<long>("CaptureTimestampNs");
                    if (sourceNs != checked(projectedTicks * 100L)) throw new Exception("source-property-changed-at-readback");
                    var reason = (string?)policy.GetMethod("BackgroundReadbackRejection")!.Invoke(null, new object[] { "background-readonly", sourceNs, readbackNs, lastSourceNs });
                    if (reason is not null) throw new Exception(reason);
                    reason = (string?)policy.GetMethod("BackgroundPublicationRejection")!.Invoke(null, new object[] { "background-readonly", sourceNs, ProtocolClock.NowNs() });
                    if (reason is not null) throw new Exception(reason);
                    var pixelSha256 = Convert.ToHexString(SHA256.HashData(Value<byte[]>("Pixels"))).ToLowerInvariant();
                    Available(); Map("before-diagnostic-summary");
                    lastSourceNs = sourceNs; accepted++;
                    Emit(new { kind = "accepted-diagnostic-frame", attempt = attempts, accepted, sourceNs, readbackNs,
                        observed = Clock(), width = Value<int>("Width"), height = Value<int>("Height"), stride = Value<int>("Stride"),
                        pixelSha256,
                        diagnosticOnly = true, businessPublished = false, sourceLeaseGranted = false });
                }
                finally { Release(selected); }
            }
        }
        catch (Exception ex)
        {
            terminationFailure = Error(ex);
            // A later stop/ABI/cleanup failure must not erase the recorded first gate failure.
            failure = firstGateFailure is null ? terminationFailure : JsonSerializer.Serialize(firstGateFailure, Json);
        }
        finally
        {
            Emit(new { kind = "disposing", attempts, accepted, failure, firstGateFailure, clock = Clock() });
            try { (capture as IDisposable)?.Dispose(); } catch (Exception ex) { cleanupFailure = Error(ex); }
        }
        Emit(new { kind = "result", attempts, acceptedDiagnosticFrames = accepted, businessPublishedFrames = 0,
            dequeued, released, comparisons, frameArrivals, failure, firstGateFailure, terminationFailure, cleanupFailure, completed = Clock(),
            stopRequested = Stopped(), gameCapture = capture is not null, desktopCapture = false, gameInput = false,
            productionGateChanged = false, imagesSaved = 0 });
        return failure is null && cleanupFailure is null ? 0 : 1;
    }

    private sealed class TestFrame;
    private static int SelectorCheck(string hostDir)
    {
        // One new failure case, no WGC/window API: source 150 is future at 100.
        // Simulated ABI work advances the clock to 500 but cannot rescue the frame.
        var host = Assembly.LoadFrom(Path.Combine(hostDir, "WgcLiveHarness.dll"));
        var selector = host.GetType("WgcLiveHarness.RequestFrameSelector", true)!.GetMethod("Select")!.MakeGenericMethod(typeof(TestFrame));
        long time = 100; bool pending = false; int disposed = 0; bool rejected = false;
        long ReadClock() => pending ? InspectAfterComparison(() => new Sample(time, 1_000_000_000, time, 1), _ => {
            pending = false; time = 500;
        }).Nanoseconds : time;
        object?[] input = { (Func<TestFrame?>)(() => new TestFrame()), (Func<TestFrame, long>)(_ => { pending = true; return 150; }),
            (Action<TestFrame>)(_ => disposed++), (Func<int, bool>)(_ => false), (Func<long>)ReadClock,
            (Func<bool>)(() => false), 10L, 1_000L, 0 };
        try { selector.Invoke(null, input); }
        catch (TargetInvocationException ex) when (ex.InnerException is InvalidOperationException error && error.Message.Contains("in the future")) { rejected = true; }
        var passed = rejected && disposed == 1 && time == 500;
        Emit(new { kind = "offline-selector-check", passed, originalComparisonNs = 100, laterNs = time, sourceNs = 150,
            rejected, disposed, gameCapture = false, desktopCapture = false });
        return passed ? 0 : 1;
    }

    private sealed record AbiResult(long Duration, long FrameUnknown, long InterfaceUnknown, bool SameIdentity,
        int InterfaceQueryHresult, int FrameUnknownQueryHresult, int InterfaceUnknownQueryHresult, int GetterHresult,
        long OriginalInterfacePointer, long QueriedInterfacePointer, long OriginalPointerDuration, int OriginalPointerGetterHresult,
        Sample OriginalGetterBefore, Sample OriginalGetterAfter, Sample QueriedGetterBefore, Sample QueriedGetterAfter);
    private static unsafe AbiResult ReadAbi(Direct3D11CaptureFrame frame)
    {
        var original = ((IWinRTObject)frame).NativeObject.ThisPtr;
        var iid = new Guid("FA50C623-38DA-4B32-ACF3-FA9734AD800E");
        var unknown = new Guid("00000000-0000-0000-C000-000000000046");
        nint face = 0, first = 0, second = 0;
        try
        {
            var interfaceHr = Marshal.QueryInterface(original, ref iid, out face); Marshal.ThrowExceptionForHR(interfaceHr);
            var frameUnknownHr = Marshal.QueryInterface(original, ref unknown, out first); Marshal.ThrowExceptionForHR(frameUnknownHr);
            var interfaceUnknownHr = Marshal.QueryInterface(face, ref unknown, out second); Marshal.ThrowExceptionForHR(interfaceUnknownHr);
            // Exact audited SDK: NativeObject == _inner == property getter's interface.
            // Keep this probe pinned to that DLL. A new SDK requires another audit.
            var originalGetter = (delegate* unmanaged[Stdcall]<nint, long*, int>)(*(nint**)original)[7];
            var originalBefore = Clock(); long originalDuration;
            var originalGetterHr = originalGetter(original, &originalDuration); var originalAfter = Clock();
            Marshal.ThrowExceptionForHR(originalGetterHr);
            var getter = (delegate* unmanaged[Stdcall]<nint, long*, int>)(*(nint**)face)[7];
            var queriedBefore = Clock(); long duration; var getterHr = getter(face, &duration); var queriedAfter = Clock();
            Marshal.ThrowExceptionForHR(getterHr); GC.KeepAlive(frame);
            return new(duration, first.ToInt64(), second.ToInt64(), first == second, interfaceHr, frameUnknownHr, interfaceUnknownHr, getterHr,
                original.ToInt64(), face.ToInt64(), originalDuration, originalGetterHr, originalBefore, originalAfter, queriedBefore, queriedAfter);
        }
        finally { if (second != 0) Marshal.Release(second); if (first != 0) Marshal.Release(first); if (face != 0) Marshal.Release(face); }
    }
    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetClientRect(nint hwnd, out Rect rect);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsIconic(nint hwnd);
    [DllImport("kernel32.dll")] private static extern nint GetCurrentProcess();
    [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsProcessInJob(nint process, nint job, out bool inJob);
}
