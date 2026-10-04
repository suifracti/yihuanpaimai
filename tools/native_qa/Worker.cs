using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using NteHost.Protocol;

namespace BoundedWgcQa;

internal static class Program
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
    };
    private static readonly object OutputGate = new();
    private static int _stop;

    public static int Main()
    {
        Console.InputEncoding = new UTF8Encoding(false);
        Console.OutputEncoding = new UTF8Encoding(false);
        Go? go = null;
        try
        {
            var readyClock = QpcSample.Read();
            Emit(new { kind = "ready", nowNs = readyClock.Nanoseconds, frequency = readyClock.FrequencyHz,
                clock = readyClock });
            var line = Console.ReadLine();
            go = line is null ? null : JsonSerializer.Deserialize<Go>(line, Json);
            if (go is null || !string.Equals(go.Command, "GO", StringComparison.Ordinal))
                throw new InvalidOperationException("first-command-must-be-GO");
            if (!Native.IsProcessInJob(Native.GetCurrentProcess(), IntPtr.Zero, out var inJob) || !inJob)
                throw new InvalidOperationException("child-not-owned-by-job-before-capture");
            ValidateGo(go);
            var reader = new Thread(ReadStop) { IsBackground = true, Name = "bounded-qa-stop-reader" };
            reader.Start();
            Directory.CreateDirectory(go.OutputDir);
            Emit(new { kind = "phase", phase = "go-accepted", mode = go.Mode,
                observationWindowMode = go.ObservationWindowMode,
                workDeadlineNs = go.DeadlineNs, totalDeadlineNs = go.TotalDeadlineNs, inJob });

            if (go.Mode is "fake-hang-constructor" or "fake-hang-readback")
            {
                if (ProtocolClock.NowNs() >= go.DeadlineNs || StopRequested())
                    throw new InvalidOperationException("work-deadline-before-fake-hang");
                if (go.Mode == "fake-hang-readback")
                    Emit(new { kind = "attempt", attempt = 1, requestTimestampNs = ProtocolClock.NowNs() });
                Emit(new { kind = "phase", phase = go.Mode == "fake-hang-constructor" ? "construct" : "readback",
                    fake = true });
                // Deliberately no WGC/window API and no polling: only the owning parent's Job can end this.
                Thread.Sleep(Timeout.Infinite);
                return 2;
            }

            QaResult result;
            if (go.Mode == "selftest") result = SelfTest(go);
            else if (go.Mode == "eligibility") result = EligibilityTest(go);
            else if (go.Mode == "live")
            {
                if (go.Hwnd == 0 || go.Pid <= 0 || go.Instance == 0)
                    throw new InvalidOperationException("explicit-hwnd-pid-instance-required");
                var clock = new LiveClock();
                var api = new CompiledHost(go.HostDir);
                var target = new LiveTarget(api, go);
                using var source = new LiveSource(api, go.Hwnd, go.DeadlineNs, StopRequested);
                result = Run(go.Mode, go.OutputDir, clock, target, source, go.DeadlineNs,
                    go.TotalDeadlineNs, StopRequested, "live", go.ObservationWindowMode);
                result.HostDll = api.HostPath;
                result.HostDllSha256 = api.HostHash;
                result.Target = new { go.Hwnd, go.Pid, go.Instance, image = "htgame.exe", @class = "UnrealWindow" };
            }
            else throw new InvalidOperationException("unsupported-mode");

            result.RequestedMode = go.ObservationWindowMode;
            SaveResult(go.OutputDir, result);
            Emit(new { kind = "result", result });
            return result.Passed ? 0 : 1;
        }
        catch (Exception ex)
        {
            var result = new QaResult
            {
                Mode = go?.Mode ?? "handshake", RequestedMode = go?.ObservationWindowMode ?? "foreground", RejectionReason = Error(ex),
                WorkDeadlineNs = go?.DeadlineNs ?? 0, TotalDeadlineNs = go?.TotalDeadlineNs ?? 0,
                CompletedAtNs = ProtocolClock.NowNs(),
            };
            result.TotalBudgetOk = result.TotalDeadlineNs > 0 && result.CompletedAtNs < result.TotalDeadlineNs;
            if (go is not null && SafeOutput(go.OutputDir)) SaveResult(go.OutputDir, result);
            Emit(new { kind = "result", result });
            return 1;
        }
    }

    private static void ValidateGo(Go go)
    {
        if (go.ObservationWindowMode is not "foreground" and not "background-readonly")
            throw new InvalidOperationException("unknown-observation-window-mode");
        if (!SafeOutput(go.OutputDir)) throw new InvalidOperationException("output-must-be-inside-project-build");
        go.OutputDir = Path.GetFullPath(go.OutputDir);
        go.HostDir = Path.GetFullPath(string.IsNullOrWhiteSpace(go.HostDir)
            ? Path.Combine(RepoRoot(), "build", "native-observation") : go.HostDir);
        if (go.DeadlineNs <= 0 || go.TotalDeadlineNs <= go.DeadlineNs
            || go.TotalDeadlineNs - go.DeadlineNs > 2_000_000_000L)
            throw new InvalidOperationException("invalid-shared-deadlines");
        var now = ProtocolClock.NowNs();
        if (go.DeadlineNs - now > 8_000_000_000L || go.TotalDeadlineNs - now > 10_000_000_000L)
            throw new InvalidOperationException("deadline-budget-exceeds-8s-10s");
        if (now >= go.DeadlineNs) throw new InvalidOperationException("work-deadline-before-GO");
    }

    private static bool SafeOutput(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;
        var root = Path.GetFullPath(Path.Combine(RepoRoot(), "build")) + Path.DirectorySeparatorChar;
        var full = Path.GetFullPath(path);
        return full.StartsWith(root, StringComparison.OrdinalIgnoreCase);
    }

    private static string RepoRoot()
    {
        foreach (var start in new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        {
            var directory = new DirectoryInfo(start);
            while (directory is not null)
            {
                if (File.Exists(Path.Combine(directory.FullName, "AGENTS.md"))
                    && Directory.Exists(Path.Combine(directory.FullName, "architecture"))) return directory.FullName;
                directory = directory.Parent;
            }
        }
        throw new DirectoryNotFoundException("project-root-not-found");
    }

    private static void ReadStop()
    {
        try
        {
            string? line;
            while ((line = Console.ReadLine()) is not null)
            {
                using var command = JsonDocument.Parse(line);
                if (command.RootElement.TryGetProperty("command", out var item)
                    && item.GetString() == "STOP") Interlocked.Exchange(ref _stop, 1);
            }
        }
        catch { }
        finally { Interlocked.Exchange(ref _stop, 1); }
    }

    private static bool StopRequested() => Volatile.Read(ref _stop) != 0;
    private static void Emit(object item)
    {
        lock (OutputGate) { Console.WriteLine(JsonSerializer.Serialize(item, Json)); Console.Out.Flush(); }
    }
    private static void SaveResult(string outputDir, QaResult result)
    {
        Directory.CreateDirectory(outputDir);
        File.WriteAllText(Path.Combine(outputDir, "result.json"), JsonSerializer.Serialize(result, Json), new UTF8Encoding(false));
    }
    private static string Error(Exception ex)
    {
        while (ex is TargetInvocationException && ex.InnerException is not null) ex = ex.InnerException;
        return $"{ex.GetType().Name}:{ex.Message}";
    }

    private static QaResult Run(string mode, string outputDir, IClock clock, ITarget target,
        ISource source, long workDeadlineNs, long totalDeadlineNs, Func<bool> stopped, string caseName,
        string observationWindowMode = "foreground")
    {
        var result = new QaResult { Mode = mode, WorkDeadlineNs = workDeadlineNs, TotalDeadlineNs = totalDeadlineNs };
        var hashes = new HashSet<string>(StringComparer.Ordinal);
        long lastSourceNs = 0;
        bool constructed = false;

        string? Gate(string stage, bool mapping)
        {
            var before = clock.NowNs();
            var reason = stopped() ? "stop-requested" : before >= workDeadlineNs ? "work-deadline" : null;
            TargetCheck? observation = null;
            bool? map = null;
            if (reason is null)
            {
                observation = target.Check(stage);
                reason = observation.Rejection;
                if (reason is null && mapping)
                {
                    map = source.MappingCurrent();
                    if (map != true) reason = "client-area-mapping-unproven-or-changed";
                }
            }
            var after = clock.NowNs();
            // The fresh queries themselves may cross cancellation/deadline boundaries.
            if (stopped()) reason = "stop-requested";
            else if (after >= workDeadlineNs) reason = "work-deadline";
            var check = new GateCheck(stage, before, after, map, observation?.Evidence, reason);
            result.GateChecks.Add(check);
            Emit(new { kind = "gate", caseName, check });
            // Diagnostic output is not an admission: it may consume the remaining budget.
            if (stopped()) return $"{stage}:stop-requested";
            if (clock.NowNs() >= workDeadlineNs) return $"{stage}:work-deadline";
            return reason is null ? null : $"{stage}:{reason}";
        }

        try
        {
            result.RejectionReason = Gate("before-construct", false);
            if (result.RejectionReason is null)
            {
                Emit(new { kind = "phase", caseName, phase = "construct" });
                // Nothing on another thread is permitted to dispose this capture object.
                if (stopped() || clock.NowNs() >= workDeadlineNs)
                    result.RejectionReason = stopped() ? "construct-admission:stop-requested" : "construct-admission:work-deadline";
                else
                {
                    source.Construct();
                    constructed = true;
                    result.RejectionReason = Gate("after-construct", true);
                }
            }
            while (result.RejectionReason is null && result.Attempts < 3)
            {
                result.RejectionReason = Gate("before-capture", true);
                if (result.RejectionReason is not null) break;
                result.Attempts++;
                var requestNs = clock.NowNs();
                Emit(new { kind = "attempt", caseName, attempt = result.Attempts, requestTimestampNs = requestNs,
                    requestClock = (clock as LiveClock)?.LastSample });
                // Logging does not create a fresh budget. Fail before calling Capture if it used the remainder.
                var remainingNs = workDeadlineNs - clock.NowNs();
                if (stopped() || remainingNs < 1_000_000L)
                {
                    result.RejectionReason = stopped() ? "before-capture-call:stop-requested" : "before-capture-call:work-deadline";
                    break;
                }
                Frame frame;
                try
                {
                    Emit(new { kind = "phase", caseName, phase = "readback", attempt = result.Attempts });
                    remainingNs = workDeadlineNs - clock.NowNs();
                    if (stopped() || remainingNs < 1_000_000L)
                    {
                        result.RejectionReason = stopped() ? "before-capture-call:stop-requested" : "before-capture-call:work-deadline";
                        break;
                    }
                    frame = source.Capture((int)Math.Min(2000L, remainingNs / 1_000_000L), requestNs);
                    result.Readbacks++;
                }
                catch (Exception ex)
                {
                    result.DiscardedQueuedFrames += source.LastDiscardedQueuedFrames;
                    result.RejectionReason = "capture:" + Error(ex); break;
                }
                result.DiscardedQueuedFrames += source.LastDiscardedQueuedFrames;
                var evidence = new FrameEvidence
                {
                    Attempt = result.Attempts, RequestTimestampNs = requestNs, SourceTimestampNs = frame.SourceNs,
                    ReadbackTimestampNs = frame.ReadbackNs, ObservedAfterReadbackNs = clock.NowNs(),
                    Width = frame.Width, Height = frame.Height, Stride = frame.Stride,
                    DiscardedQueuedFrames = source.LastDiscardedQueuedFrames,
                };
                evidence.ObservedAfterReadbackClock = (clock as LiveClock)?.LastSample;
                result.ReadbackFrames.Add(evidence);
                Emit(new { kind = "readback", caseName, frame = evidence });
                result.RejectionReason = Gate("after-capture", true);
                if (result.RejectionReason is not null) break;
                if (frame.Width <= 0 || frame.Height <= 0 || frame.Width > 1920 || frame.Height > 1080
                    || frame.Stride != checked(frame.Width * 4)
                    || frame.Pixels.Length != checked(frame.Stride * frame.Height))
                { result.RejectionReason = "readback:invalid-client-frame-geometry"; break; }
                if (frame.SourceNs <= requestNs)
                { result.RejectionReason = "readback:source-not-after-request"; break; }
                if (frame.SourceNs <= lastSourceNs)
                { result.RejectionReason = "readback:source-not-increasing"; break; }
                if (frame.SourceNs > frame.ReadbackNs || frame.ReadbackNs > evidence.ObservedAfterReadbackNs)
                { result.RejectionReason = "readback:inconsistent-source-readback-clock"; break; }
                if (observationWindowMode == "background-readonly" && frame.ReadbackNs - frame.SourceNs > 2_000_000_000L)
                { result.RejectionReason = "readback:source-older-than-two-seconds"; break; }
                lastSourceNs = frame.SourceNs;
                evidence.PixelSha256 = Convert.ToHexString(SHA256.HashData(frame.Pixels)).ToLowerInvariant();
                if (!hashes.Add(evidence.PixelSha256))
                { result.RejectionReason = "readback:duplicate-pixels-not-independent-support"; break; }
                result.RejectionReason = Gate("before-save", true);
                if (result.RejectionReason is not null) break;
                var path = Path.Combine(outputDir, $"candidate-{result.Attempts:D2}{source.Extension}");
                if (File.Exists(path)) { result.RejectionReason = "save:candidate-path-already-exists"; break; }
                var candidate = new CandidateFile { Attempt = result.Attempts, Path = path, PixelSha256 = evidence.PixelSha256 };
                result.CandidateFiles.Add(candidate);
                Emit(new { kind = "candidate", caseName, candidate });
                // Admission is checked again after candidate metadata emission and immediately before saving.
                result.RejectionReason = Gate("save-admission", true);
                if (result.RejectionReason is not null) break;
                try { source.Save(path, frame); candidate.Saved = true; }
                catch (Exception ex) { result.RejectionReason = "save:" + Error(ex); candidate.Saved = File.Exists(path); break; }
                result.RejectionReason = Gate("after-save", true);
                candidate.Exists = File.Exists(path);
                if (result.RejectionReason is not null) break;
                candidate.FileSha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
                result.RejectionReason = Gate("before-accept", true);
                if (result.RejectionReason is not null) break;
                candidate.Accepted = true;
                evidence.Path = path;
                evidence.FileSha256 = candidate.FileSha256;
                result.AcceptedFrames.Add(evidence);
                Emit(new { kind = "accepted", caseName, frame = evidence });
            }
        }
        catch (Exception ex) { result.RejectionReason ??= "worker:" + Error(ex); }
        finally
        {
            Emit(new { kind = "phase", caseName, phase = "dispose", constructed });
            try { source.Dispose(); }
            catch (Exception ex) { result.RejectionReason ??= "dispose:" + Error(ex); }
            foreach (var candidate in result.CandidateFiles) candidate.Exists = File.Exists(candidate.Path);
            result.CompletedAtNs = clock.NowNs();
            result.TotalBudgetOk = result.CompletedAtNs < totalDeadlineNs;
            if (!result.TotalBudgetOk) result.RejectionReason ??= "total-deadline-exceeded";
            result.Passed = result.RejectionReason is null && result.AcceptedFrames.Count > 0 && result.TotalBudgetOk;
        }
        return result;
    }

    private static string? TargetRejection(string observationWindowMode, bool identityAndVisibleProven,
        bool foreground, bool iconic, bool gotClient, long width, long height)
    {
        return !identityAndVisibleProven ? "target-identity-changed-or-unproven"
            : observationWindowMode == "foreground" && !foreground ? "target-not-foreground"
            : iconic ? "target-minimized"
            : !gotClient || width <= 0 || height <= 0 || width > 1920 || height > 1080
                ? "client-size-unavailable-or-over-1920x1080" : null;
    }

    private static QaResult EligibilityTest(Go go)
    {
        // Pure known inputs: no CompiledHost, window queries, WGC, frames or files.
        var front = TargetRejection("foreground", true, false, false, true, 1920, 1080);
        var back = TargetRejection("background-readonly", true, false, false, true, 1920, 1080);
        var invalid = TargetRejection("background-readonly", false, false, false, true, 1920, 1080);
        var minimized = TargetRejection("background-readonly", true, false, true, true, 1920, 1080);
        var oversize = TargetRejection("background-readonly", true, false, false, true, 1921, 1080);
        var passed = front == "target-not-foreground" && back is null
            && invalid == "target-identity-changed-or-unproven" && minimized == "target-minimized"
            && oversize == "client-size-unavailable-or-over-1920x1080";
        var now = ProtocolClock.NowNs();
        var withinBudget = now < go.DeadlineNs && now < go.TotalDeadlineNs && !StopRequested();
        return new QaResult
        {
            Mode = "eligibility", Passed = passed && withinBudget,
            Cases = new() { new("foreground-vs-background-readonly-eligibility", passed,
                new { foreground = front, background = back, invalidIdentityOrVisibility = invalid, minimized, oversize }) },
            WorkDeadlineNs = go.DeadlineNs, TotalDeadlineNs = go.TotalDeadlineNs,
            CompletedAtNs = now, TotalBudgetOk = now < go.TotalDeadlineNs,
            RejectionReason = !withinBudget ? "eligibility-parent-budget-or-stop" : !passed ? "eligibility-policy-failed" : null,
        };
    }

    private static QaResult SelfTest(Go go)
    {
        // This branch instantiates no CompiledHost/LiveTarget/LiveSource and loads no WGC or WindowMonitor.
        var cases = new List<CaseResult>();
        const long origin = 10_000_000_000L;
        const long work = origin + 8_000_000_000L;
        const long total = origin + 10_000_000_000L;
        void Case(string name, Action<FakeClock, FakeTarget, FakeSource> setup,
            Func<QaResult, FakeSource, bool> assertion)
        {
            var clock = new FakeClock(origin);
            var target = new FakeTarget();
            var source = new FakeSource(clock);
            setup(clock, target, source);
            var dir = Path.Combine(go.OutputDir, name);
            Directory.CreateDirectory(dir);
            var actual = Run("selftest", dir, clock, target, source, work, total,
                () => source.Stopped || StopRequested(), name);
            cases.Add(new CaseResult(name, assertion(actual, source), new { result = actual, captureCalls = source.Calls }));
        }
        static bool Counts(QaResult r, int attempts, int readbacks, int files, int accepted) =>
            r.Attempts == attempts && r.Readbacks == readbacks && r.CandidateFiles.Count == files
            && r.AcceptedFrames.Count == accepted;
        static bool Reason(QaResult r, string text) => r.RejectionReason?.Contains(text, StringComparison.Ordinal) == true;

        Case("normal-four-available", (_, _, _) => { }, (r, s) =>
            r.Passed && Counts(r, 3, 3, 3, 3) && s.Calls == 3 && r.CandidateFiles.All(f => f.Exists));
        Case("failed-capture-consumes-attempt", (_, _, s) => s.FailCapture = true,
            (r, s) => !r.Passed && Counts(r, 1, 0, 0, 0) && s.Calls == 1 && Reason(r, "known-fake-capture-failure"));
        Case("readback-crosses-work-deadline", (c, _, s) => s.AfterCapture = () => c.Time = work + 1,
            (r, s) => !r.Passed && Counts(r, 1, 1, 0, 0) && s.Calls == 1 && Reason(r, "work-deadline"));
        Case("save-crosses-work-deadline-retains-candidate", (c, _, s) => s.AfterSave = () => c.Time = work + 1,
            (r, s) => !r.Passed && Counts(r, 1, 1, 1, 0) && s.Calls == 1
                && r.CandidateFiles[0].Saved && r.CandidateFiles[0].Exists && Reason(r, "after-save:work-deadline"));
        Case("identity-change-after-readback", (_, t, s) => s.AfterCapture = () => t.Identity = false,
            (r, s) => !r.Passed && Counts(r, 1, 1, 0, 0) && s.Calls == 1 && Reason(r, "target-identity-changed"));
        Case("foreground-loss-after-readback", (_, t, s) => s.AfterCapture = () => t.Foreground = false,
            (r, s) => !r.Passed && Counts(r, 1, 1, 0, 0) && s.Calls == 1 && Reason(r, "target-not-foreground"));
        Case("mapping-loss-after-readback", (_, _, s) => s.AfterCapture = () => s.Mapping = false,
            (r, s) => !r.Passed && Counts(r, 1, 1, 0, 0) && s.Calls == 1 && Reason(r, "mapping-unproven-or-changed"));
        Case("source-at-request-is-old", (_, _, s) => s.OldSource = true,
            (r, s) => !r.Passed && Counts(r, 1, 1, 0, 0) && s.Calls == 1 && Reason(r, "source-not-after-request"));
        Case("duplicate-pixels-end-without-retry", (_, _, s) => s.Duplicate = true,
            (r, s) => !r.Passed && Counts(r, 2, 2, 1, 1) && s.Calls == 2 && Reason(r, "duplicate-pixels"));
        Case("construction-crosses-work-deadline", (c, _, s) => s.AfterConstruct = () => c.Time = work + 1,
            (r, s) => !r.Passed && Counts(r, 0, 0, 0, 0) && s.Calls == 0 && Reason(r, "after-construct:work-deadline"));
        Case("stop-after-readback", (_, _, s) => s.AfterCapture = () => s.Stopped = true,
            (r, s) => !r.Passed && Counts(r, 1, 1, 0, 0) && s.Calls == 1 && Reason(r, "stop-requested"));
        Case("late-dispose-fails-total-budget", (c, _, s) => s.AfterDispose = () => c.Time = total + 1,
            (r, s) => !r.Passed && !r.TotalBudgetOk && Counts(r, 3, 3, 3, 3)
                && s.Calls == 3 && Reason(r, "total-deadline-exceeded"));

        var now = ProtocolClock.NowNs();
        var withinBudget = now < go.DeadlineNs && now < go.TotalDeadlineNs && !StopRequested();
        return new QaResult
        {
            Mode = "selftest", Passed = cases.All(c => c.Passed) && withinBudget, Cases = cases,
            WorkDeadlineNs = go.DeadlineNs, TotalDeadlineNs = go.TotalDeadlineNs,
            CompletedAtNs = now, TotalBudgetOk = now < go.TotalDeadlineNs,
            RejectionReason = !withinBudget ? "selftest-parent-budget-or-stop" : cases.Any(c => !c.Passed) ? "selftest-case-failed" : null,
        };
    }

    private sealed class Go
    {
        public Go() { }
        public string Command { get; set; } = "";
        public string Mode { get; set; } = "";
        public string ObservationWindowMode { get; init; } = "foreground";
        public string HostDir { get; set; } = "";
        public string OutputDir { get; set; } = "";
        public long DeadlineNs { get; set; }
        public long TotalDeadlineNs { get; set; }
        public long Hwnd { get; set; }
        public int Pid { get; set; }
        public long Instance { get; set; }
    }
    private sealed class QaResult
    {
        public bool Passed { get; set; }
        public string Mode { get; set; } = "";
        public string RequestedMode { get; set; } = "foreground";
        public int Attempts { get; set; }
        public int Readbacks { get; set; }
        public int DiscardedQueuedFrames { get; set; }
        public List<CandidateFile> CandidateFiles { get; set; } = new();
        public List<FrameEvidence> AcceptedFrames { get; set; } = new();
        public List<FrameEvidence> ReadbackFrames { get; set; } = new();
        public List<GateCheck> GateChecks { get; set; } = new();
        public string? RejectionReason { get; set; }
        public long WorkDeadlineNs { get; set; }
        public long TotalDeadlineNs { get; set; }
        public long CompletedAtNs { get; set; }
        public bool TotalBudgetOk { get; set; }
        public string? HostDll { get; set; }
        public string? HostDllSha256 { get; set; }
        public object? Target { get; set; }
        public List<CaseResult>? Cases { get; set; }
        public string ExitProof { get; } = "parent-must-confirm-actual-process-exit";
    }
    private sealed class CandidateFile
    {
        public int Attempt { get; set; }
        public string Path { get; set; } = "";
        public string PixelSha256 { get; set; } = "";
        public string? FileSha256 { get; set; }
        public bool Saved { get; set; }
        public bool Exists { get; set; }
        public bool Accepted { get; set; }
    }
    private sealed class FrameEvidence
    {
        public int Attempt { get; set; }
        public long RequestTimestampNs { get; set; }
        public long SourceTimestampNs { get; set; }
        public long ReadbackTimestampNs { get; set; }
        public long ObservedAfterReadbackNs { get; set; }
        public QpcSample? ObservedAfterReadbackClock { get; set; }
        public int Width { get; set; }
        public int Height { get; set; }
        public int Stride { get; set; }
        public int DiscardedQueuedFrames { get; set; }
        public string? PixelSha256 { get; set; }
        public string? FileSha256 { get; set; }
        public string? Path { get; set; }
    }
    private sealed record GateCheck(string Stage, long BeforeNs, long AfterNs, bool? MappingCurrent, object? Target, string? Rejection);
    private sealed record CaseResult(string Name, bool Passed, object Actual);
    private sealed record Frame(int Width, int Height, int Stride, byte[] Pixels, long SourceNs, long ReadbackNs);
    private sealed record TargetCheck(string? Rejection, object Evidence);
    private interface IClock { long NowNs(); }
    private sealed record QpcSample(long RawTicks, long FrequencyHz, long WholeSeconds,
        long RemainderTicks, long Nanoseconds)
    {
        public static QpcSample Read()
        {
            var ticks = Stopwatch.GetTimestamp();
            var ns = ProtocolClock.TicksToNs(ticks);
            var frequency = ProtocolClock.Frequency;
            return new(ticks, frequency, ticks / frequency, ticks % frequency, ns);
        }
    }
    private sealed class LiveClock : IClock
    {
        public QpcSample? LastSample { get; private set; }
        public long NowNs() { LastSample = QpcSample.Read(); return LastSample.Nanoseconds; }
    }
    private sealed class FakeClock(long initial) : IClock
    {
        public long Time = initial;
        public long NowNs() => Time;
    }
    private interface ITarget { TargetCheck Check(string stage); }
    private interface ISource : IDisposable
    {
        string Extension { get; }
        int LastDiscardedQueuedFrames => 0;
        void Construct();
        bool MappingCurrent();
        Frame Capture(int timeoutMs, long requestNs);
        void Save(string path, Frame frame);
    }
    private sealed class FakeTarget : ITarget
    {
        public bool Identity = true, Foreground = true;
        public TargetCheck Check(string stage) => new(!Identity ? "target-identity-changed" : !Foreground ? "target-not-foreground" : null,
            new { fake = true, identity = Identity, foreground = Foreground });
    }
    private sealed class FakeSource(FakeClock clock) : ISource
    {
        public int Calls;
        public bool Mapping = true, FailCapture, OldSource, Duplicate, Stopped;
        public Action? AfterConstruct, AfterCapture, AfterSave, AfterDispose;
        private bool _disposed;
        public string Extension => ".fake";
        public void Construct() => AfterConstruct?.Invoke();
        public bool MappingCurrent() => Mapping;
        public Frame Capture(int timeoutMs, long requestNs)
        {
            Calls++;
            if (Calls >= 4) throw new InvalidOperationException("fourth-capture-call-forbidden-with-four-distinct-available");
            if (FailCapture) throw new InvalidOperationException("known-fake-capture-failure");
            clock.Time += 1_000_000L;
            var frame = new Frame(1, 1, 4, new byte[] { Duplicate ? (byte)1 : (byte)Calls, 2, 3, 255 },
                OldSource ? requestNs : clock.Time - 100_000L, clock.Time);
            AfterCapture?.Invoke();
            return frame;
        }
        public void Save(string path, Frame frame) { File.WriteAllBytes(path, frame.Pixels); AfterSave?.Invoke(); }
        public void Dispose() { if (_disposed) return; _disposed = true; AfterDispose?.Invoke(); }
    }

    private sealed class CompiledHost
    {
        private readonly string _directory;
        public Assembly CaptureAssembly { get; }
        public Assembly MonitorAssembly { get; }
        public string HostPath { get; }
        public string HostHash { get; }
        public CompiledHost(string directory)
        {
            _directory = directory;
            HostPath = Path.Combine(directory, "WgcLiveHarness.dll");
            HostHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(HostPath))).ToLowerInvariant();
            AssemblyLoadContext.Default.Resolving += Resolve;
            CaptureAssembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(HostPath);
            MonitorAssembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(directory, "NteHost.WindowMonitor.dll"));
        }
        private Assembly? Resolve(AssemblyLoadContext context, AssemblyName name)
        {
            var path = Path.Combine(_directory, name.Name + ".dll");
            return File.Exists(path) ? context.LoadFromAssemblyPath(path) : null;
        }
    }
    private sealed class LiveTarget : ITarget
    {
        private readonly Go _go;
        private readonly object _reader;
        private object? _identity;
        private readonly MethodInfo _read;
        private readonly MethodInfo _revalidate;
        private readonly MethodInfo _foreground;
        private readonly object _spec;
        private readonly MethodInfo _matches;
        public LiveTarget(CompiledHost api, Go go)
        {
            _go = go;
            var readerType = api.MonitorAssembly.GetType("NteHost.WindowMonitor.WindowIdentityReader", true)!;
            _reader = Activator.CreateInstance(readerType)!;
            _read = readerType.GetMethod("Read")!;
            _revalidate = readerType.GetMethod("Revalidate")!;
            var specType = api.MonitorAssembly.GetType("NteHost.WindowMonitor.TargetWindowSpec", true)!;
            _spec = specType.GetProperty("Default", BindingFlags.Public | BindingFlags.Static)!.GetValue(null)!;
            _matches = specType.GetMethod("Matches")!;
            var nativeType = api.MonitorAssembly.GetType("NteHost.WindowMonitor.Win32.NativeWindowApi", true)!;
            _foreground = nativeType.GetMethod("GetForegroundWindow", BindingFlags.Static | BindingFlags.NonPublic)!;
        }
        public TargetCheck Check(string stage)
        {
            // No discovery, no hooks: every authority read addresses exactly the parent's pinned HWND/PID/instance.
            if (_identity is null)
            {
                var found = _read.Invoke(_reader, new object[] { _go.Hwnd })!;
                var type = found.GetType();
                T Value<T>(string property) => (T)type.GetProperty(property)!.GetValue(found)!;
                var image = Value<string>("ProcessImageName");
                var windowClass = Value<string>("ClassName");
                var matches = (bool)_matches.Invoke(_spec, new object?[] { image, windowClass })!;
                if (!matches || Value<long>("Hwnd") != _go.Hwnd || Value<int>("Pid") != _go.Pid
                    || Value<long>("ProcessInstanceToken") != _go.Instance)
                    return new TargetCheck("explicit-target-identity-does-not-match-live-process-instance",
                        new { _go.Hwnd, _go.Pid, _go.Instance, actual = found.ToString() });
                _identity = found;
            }
            var verdict = _revalidate.Invoke(_reader, new object?[] { _identity, true, null })!;
            var same = (bool)verdict.GetType().GetProperty("IsSame")!.GetValue(verdict)!;
            var foreground = ((IntPtr)_foreground.Invoke(null, null)!).ToInt64();
            var iconic = Native.IsIconic(new IntPtr(_go.Hwnd));
            var gotClient = Native.GetClientRect(new IntPtr(_go.Hwnd), out var client);
            var width = (long)client.Right - client.Left;
            var height = (long)client.Bottom - client.Top;
            // Revalidate(..., true, ...) still proves identity and window visibility.
            var failure = TargetRejection(_go.ObservationWindowMode, same, foreground == _go.Hwnd,
                iconic, gotClient, width, height);
            return new TargetCheck(failure, new { _go.Hwnd, _go.Pid, _go.Instance, same, foregroundHwnd = foreground,
                iconic, gotClient, width, height, verdict = verdict.ToString() });
        }
    }
    private sealed class LiveSource(CompiledHost api, long hwnd, long workDeadlineNs, Func<bool> stopped) : ISource
    {
        private object? _capture;
        private MethodInfo? _captureMethod, _mappingMethod, _writeBmp;
        private PropertyInfo? _discardedProperty, _clockDiagnosticsProperty;
        private bool _disposed;
        public string Extension => ".bmp";
        public int LastDiscardedQueuedFrames => _capture is null ? 0 : (int)_discardedProperty!.GetValue(_capture)!;
        public void Construct()
        {
            var type = api.CaptureAssembly.GetType("WgcLiveHarness.WgcWindowCapture", true)!;
            _captureMethod = type.GetMethod("CaptureAfterRequest", BindingFlags.Public | BindingFlags.Instance,
                null, new[] { typeof(int), typeof(long), typeof(long), typeof(Func<bool>) }, null)
                ?? throw new InvalidOperationException("Host lacks explicit request-frame selection");
            _discardedProperty = type.GetProperty("LastRequestDiscardedQueuedFrames", BindingFlags.Public | BindingFlags.Instance)
                ?? throw new InvalidOperationException("Host lacks request selection diagnostics");
            var enableClockDiagnostics = type.GetProperty("EnableRequestClockDiagnostics", BindingFlags.Public | BindingFlags.Instance)
                ?? throw new InvalidOperationException("Host lacks raw request-clock diagnostics; do not capture using a stale Host");
            _clockDiagnosticsProperty = type.GetProperty("LastRequestClockDiagnosticsJson", BindingFlags.Public | BindingFlags.Instance)
                ?? throw new InvalidOperationException("Host lacks raw request-clock trace");
            _mappingMethod = type.GetMethod("IsClientAreaMappingCurrent", BindingFlags.Public | BindingFlags.Instance)!;
            _writeBmp = api.CaptureAssembly.GetType("WgcLiveHarness.Program", true)!.GetMethod("WriteBmp", BindingFlags.NonPublic | BindingFlags.Static)!;
            _capture = type.GetConstructor(new[] { typeof(IntPtr) })!.Invoke(new object[] { new IntPtr(hwnd) });
            enableClockDiagnostics.SetValue(_capture, true);
        }
        public bool MappingCurrent() => _capture is not null && (bool)_mappingMethod!.Invoke(_capture, null)!;
        public Frame Capture(int timeoutMs, long requestNs)
        {
            try
            {
                var raw = _captureMethod!.Invoke(_capture, new object[] { timeoutMs, requestNs, workDeadlineNs, stopped })!;
                var type = raw.GetType();
                T Value<T>(string property) => (T)type.GetProperty(property)!.GetValue(raw)!;
                return new Frame(Value<int>("Width"), Value<int>("Height"), Value<int>("Stride"), Value<byte[]>("Pixels"),
                    Value<long>("SourceTimestampNs"), Value<long>("CaptureTimestampNs"));
            }
            finally
            {
                if (_clockDiagnosticsProperty!.GetValue(_capture) is string trace)
                {
                    using var parsed = JsonDocument.Parse(trace);
                    Emit(new { kind = "clock-diagnostic", requestTimestampNs = requestNs,
                        diagnostic = parsed.RootElement });
                }
                Emit(new { kind = "frame-selection", requestTimestampNs = requestNs,
                    discardedQueuedFrames = LastDiscardedQueuedFrames });
            }
        }
        public void Save(string path, Frame frame) => _writeBmp!.Invoke(null, new object[] { path, frame.Width, frame.Height, frame.Pixels });
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            if (_capture is IDisposable disposable) disposable.Dispose();
        }
    }
    private static class Native
    {
        [DllImport("kernel32.dll")] internal static extern IntPtr GetCurrentProcess();
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool IsProcessInJob(IntPtr process, IntPtr job, [MarshalAs(UnmanagedType.Bool)] out bool result);
        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool IsIconic(IntPtr hwnd);
        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool GetClientRect(IntPtr hwnd, out Rect result);
        [StructLayout(LayoutKind.Sequential)] internal struct Rect { public int Left, Top, Right, Bottom; }
    }
}
