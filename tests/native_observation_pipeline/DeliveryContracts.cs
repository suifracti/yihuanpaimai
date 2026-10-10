using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using NteHost.Protocol;
using WgcLiveHarness;

internal static class DeliveryContracts
{
    public static void AdviceQualificationOnly()
    {
        void Check(bool value, string reason) { if (!value) throw new Exception(reason); }
        var sample = QpcClockSample.Read();
        var request = sample.Nanoseconds - 400;
        var publicationNs = sample.Nanoseconds + 1000;
        var sourceTicks = sample.Nanoseconds / 100 + 100_000;
        var delivered = new CaptureDeliveryProof("session", 1, 1, request, publicationNs + 100_000,
            request, request, request, sample, sample, sourceTicks, sourceTicks, 0,
            sample.Nanoseconds + 50, sample.Nanoseconds + 100)
            { ReleaseCompletedNs = request, DrainTakeCount = 1, BoundaryHeldCount = 0 };
        var original = new DeliveryVisualSummary(delivered.CaptureId, 1, delivered.ReadbackCompletedNs,
            "scene", "warehouse", true, "observation");
        var support = original with { CaptureId = "session/1/2" };
        var accepted = DeliveryAdviceQualification.Evaluate(delivered, support, original, publicationNs);
        Check(accepted.Qualified && accepted.FailureReasons.Length == 0, "all advice conditions did not qualify");

        var failures = new (string Case, DeliveryAdviceQualification Qualification, string Reason)[]
        {
            ("source-marker", DeliveryAdviceQualification.Evaluate(delivered with { PreviousMarkerNs = delivered.SourceNs }, support, original, publicationNs), "SOURCE_MARKER_NO_PROGRESS"),
            ("support-missing", DeliveryAdviceQualification.Evaluate(delivered, null, original, publicationNs), "SUPPORT_SUMMARY_MISSING"),
            ("action-unqualified", DeliveryAdviceQualification.Evaluate(delivered, support with { ActionQualified = false }, original, publicationNs), "SUPPORT_ACTION_UNQUALIFIED"),
            ("pool-epoch", DeliveryAdviceQualification.Evaluate(delivered, support with { Epoch = 2 }, original, publicationNs), "SUPPORT_POOL_EPOCH_MISMATCH"),
            ("readback-future", DeliveryAdviceQualification.Evaluate(delivered, support with { ReadbackNs = publicationNs + 1 }, original, publicationNs), "SUPPORT_READBACK_FROM_FUTURE"),
            ("readback-stale", DeliveryAdviceQualification.Evaluate(delivered, support with { ReadbackNs = publicationNs - 2_000_000_001 }, original, publicationNs), "SUPPORT_READBACK_STALE"),
            ("session", DeliveryAdviceQualification.Evaluate(delivered, support with { CaptureId = "old-session/1/2" }, original, publicationNs), "SUPPORT_SESSION_MISMATCH"),
            ("original-binding", DeliveryAdviceQualification.Evaluate(delivered, support, original with { CaptureId = "wrong" }, publicationNs), "ORIGINAL_FRAME_BINDING_MISMATCH"),
            ("original-expired", DeliveryAdviceQualification.Evaluate(delivered, support, original, publicationNs + 31_000_000_000), "ORIGINAL_DELIVERY_INVALID_OR_EXPIRED"),
        };
        foreach (var (name, qualification, reason) in failures)
            Check(!qualification.Qualified && qualification.FailureReasons.Contains(reason), name + " failure was not reported");
        var dynamic = DeliveryAdviceQualification.Evaluate(delivered, support with {
            SceneRoiSha256 = "new-scene-pixels", ObservationRoiSha256 = "new-timer-pixels",
            WarehouseRoiSha256 = "new-warehouse-pixels" }, original, publicationNs);
        Check(dynamic.Qualified && !dynamic.SceneRoiMatches && !dynamic.ObservationRoiMatches
            && !dynamic.WarehouseRoiMatches, "dynamic pixels vetoed computing the bound fact version");
        long clock = publicationNs;
        var concurrent = DeliveryAdviceQualification.EvaluateCurrent(delivered, original,
            () => { clock += 100; return support with { ReadbackNs = clock }; }, () => clock + 1);
        Check(concurrent.Qualified && concurrent.EvaluationNs > concurrent.SupportReadbackNs,
            "summary compared against a time preceding its read");
        Check(dynamic.ToJson()["sourceAbsoluteAgeMs"] is null
            && dynamic.ToJson()["automaticBidExecutionQualified"]!.GetValue<bool>() == false,
            "delivery calculation was upgraded to absolute freshness or bid permission");
        Console.WriteLine(JsonSerializer.Serialize(new { passed = true, test = "advice-qualification-breakdown",
            baseline = accepted.ToJson(), failedComponents = failures.Select(x => x.Case).ToArray() }));
    }

    public static void ReplayAdvice(string path)
    {
        // An offline retained original is the only available summary in this
        // replay timeline. Never claim it is the currently running game.
        var input = JsonNode.Parse(File.ReadAllText(path))!;
        var delivered = input["proof"]!.Deserialize<CaptureDeliveryProof>(
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
        var original = new DeliveryVisualSummary(delivered.CaptureId, delivered.PoolEpoch,
            delivered.ReadbackCompletedNs, (string)input["sceneHash"]!, (string)input["warehouseHash"]!,
            delivered.Qualified && delivered.SourceMarkerProgress, (string)input["observationHash"]!);
        var qualification = DeliveryAdviceQualification.EvaluateCurrent(delivered, original,
            () => original, () => (long)input["evaluationNs"]!);
        Console.WriteLine(qualification.ToJson().ToJsonString());
    }

    public static void ReplayVisibleContent(string path)
    {
        void Check(bool value, string reason) { if (!value) throw new Exception(reason); }
        var input = JsonNode.Parse(File.ReadAllText(path))!;
        CapturedBgraFrame Frame(JsonNode row)
        {
            var raw = File.ReadAllBytes((string)row["bmpPath"]!);
            var hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(raw)).ToLowerInvariant();
            Check(hash == (string)row["bmpSha256"]!, "retained BMP changed");
            var proof = row["deliveryProof"]!.Deserialize<CaptureDeliveryProof>(new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
            return new(1920, 1080, 7680, raw[54..], proof.ReadbackCompletedNs, "retained-offline", proof.SourceNs,
                proof.AcquisitionSequence, proof);
        }
        var frames = input["originals"]!.AsArray().Select(row => Frame(row!)).ToArray();
        var summaries = frames.Select(DeliveryVisualSummary.From).ToArray();
        var pairs = new[] { (4,5), (5,6), (6,7), (7,8), (8,9), (10,11), (11,12), (12,13) };
        foreach (var (a,b) in pairs) Check(summaries[a].ContentSupportedBy(summaries[b])
            && summaries[a].SceneSupportedBy(summaries[b]), $"real normal pair {a+1}:{b+1} refused");
        Check(!summaries[1].ContentSupportedBy(summaries[2]), "real blue reveal accepted");
        Check(!summaries[3].ContentSupportedBy(summaries[4]), "real mass reveal accepted");
        foreach (var index in new[] { 0, 3 * (560 * 600 + 20), 3 * (70 * 600 + 26), summaries[4].ScrollContentBgr!.Length-1 })
        {
            var bytes = summaries[4].ScrollContentBgr!.ToArray(); bytes[index] = (byte)(bytes[index] <= 253 ? bytes[index]+2 : bytes[index]-2);
            Check(!summaries[4].ContentSupportedBy(summaries[4] with { ScrollContentRoiSha256 = "changed", ScrollContentBgr = bytes }), "two-code protected edit accepted");
        }
        Check(!summaries[4].SceneSupportedBy(summaries[4] with { SceneRoiSha256 = "erased", SceneBgr = new byte[summaries[4].SceneBgr!.Length] }), "scene title loss accepted");
        var scope = input["scope"]!; var target = (JsonObject)scope["targetInstance"]!.DeepClone();
        long now = frames[4].DeliveryProof!.RequestNs - 100, deadline = (long)input["deadlineNs"]!;
        var events = new List<JsonObject>(); var diagnostics = new List<JsonObject>(); var sends = 0;
        DeliveryVisualSummary? latest = summaries[4];
        var root = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(path))!, "host-source-replay");
        using var lease = new WarehouseEvidenceLease(root, (string)scope["observationSessionId"]!, events.Add, () => now,
            (_, current) => { Check(current(), "lease revoked at inert send"); sends++; return true; },
            CapturePolicy.Delivery, () => latest, diagnostics.Add);
        lease.UpdateContext(new((string)scope["recordStableKey"]!, target, (string)input["originals"]![0]!["clientMap"]!,
            1920,1080,true,true,deadline,(long)scope["matchGeneration"]!));
        JsonObject Command(string operation, int ordinal=0) => new() {
            ["type"]=WarehouseEvidenceLease.ControlType,["schemaVersion"]=WarehouseEvidenceLease.SchemaV2,
            ["operation"]=operation,["commandId"]=Guid.NewGuid().ToString("N"),["nonce"]=Guid.NewGuid().ToString("N"),
            ["observationSessionId"]=scope["observationSessionId"]!.DeepClone(),["reviewSessionId"]="visible-replay",["reviewGeneration"]=1,
            ["recordStableKey"]=scope["recordStableKey"]!.DeepClone(),["matchGeneration"]=scope["matchGeneration"]!.DeepClone(),
            ["expectedTargetInstance"]=target.DeepClone(),["leaseToken"]=lease.LeaseToken,["requestOrdinal"]=ordinal,
            ["allowWindowScroll"]=true,["retainIndependentOriginals"]=true,["remainingPages"]=16,["remainingPngBytes"]=64*1024*1024,
            ["pngEncoding"]=WarehouseEvidenceLease.PngEncoding };
        lease.Handle(Command("OPEN")); Check(lease.IsOpen, "armed independent retention could not open");
        JsonObject? saved = null;
        foreach (var (index,ordinal) in new[] { (4,1), (6,2) })
        {
            var f = frames[index]; var p = f.DeliveryProof!; now = p.RequestNs;
            lease.Handle(Command("REQUEST_PAGE",ordinal));
            var snapshot = lease.RequestSnapshot() ?? throw new Exception(JsonSerializer.Serialize(events));
            now = p.ReadbackCompletedNs + 100; latest = summaries[index];
            Check(lease.TryPublish(new(1920,1080,7680,f.Pixels,p.SourceNs,p.ReadbackCompletedNs,f.CapturedAtUtc,
                p.AcquisitionSequence,"",0,p,latest,snapshot.Gate,(long)scope["matchGeneration"]!),()=>true), "SOURCE publication rejected");
            var sourceEvent = events.Last(e=>(string?)e["event"]=="SOURCE"); saved=(JsonObject)sourceEvent["source"]!;
            var ack = Command("ACK_SOURCE",ordinal); ack["nonce"]=sourceEvent["nonce"]?.DeepClone();
            ack["sourceLeaseId"]=saved["sourceLeaseId"]!.DeepClone(); ack["bmpSha256"]=saved["bmpSha256"]!.DeepClone();
            ack["pixelSha256"]=saved["pixelSha256"]!.DeepClone(); ack["result"]="SAVED"; lease.Handle(ack);
        }
        latest=summaries[8]; now=latest.ReadbackNs+100;
        var scroll=Command("SCROLL_DOWN",2); scroll["sourceLeaseId"]=saved!["sourceLeaseId"]!.DeepClone();
        scroll["pixelSha256"]=saved["pixelSha256"]!.DeepClone(); scroll["savedCaptureId"]=summaries[4].CaptureId;
        scroll["stableCaptureId"]=summaries[6].CaptureId; lease.Handle(scroll);
        Check(sends==1 && events.Any(e=>(string?)e["event"]=="SCROLLED"), "real supported page did not reach Host inert send");
        Console.WriteLine(JsonSerializer.Serialize(new { passed=true, normalPairs=pairs.Length, protectedEditsRejected=4,
            actualHostLeaseReachedInertSend=true, gameCapture=false, gameInput=false, diagnostics }));
    }

    public static void Run(string root)
    {
        void Check(bool value, string reason) { if (!value) throw new Exception(reason); }
        var results = new List<object>();
        int takes = 0, releases = 0; long now = 10;
        try
        {
            DeliveredFrameSelector.Select(() => { takes++; return new object(); }, _ => releases++, _ => { },
                _ => true, () => ++now, () => false, 1, 1000, out _, out _, out _, out _, out _, out _);
            throw new Exception("nonempty pool accepted");
        }
        catch (InvalidOperationException ex) { Check(ex.Message == "POOL_BOUNDARY_UNPROVEN", "wrong pool failure"); }
        Check(takes == 3 && releases == 3, "drain unbounded or ownership leaked");
        var candidates = new Queue<object?>(); var old = new object(); var delivered = new object();
        candidates.Enqueue(old); candidates.Enqueue(null); candidates.Enqueue(delivered);
        var chosen = DeliveredFrameSelector.Select(() => candidates.Dequeue(), _ => releases++, _ => { },
            _ => true, () => ++now, () => false, 1, 1000, out var barrier, out var before, out var after,
            out _, out _, out _);
        Check(ReferenceEquals(chosen, delivered) && barrier <= before && before <= after, "wrong delivered frame");
        results.Add(new { test = "pool-always-nonempty-and-post-empty-ownership", takes, releases, passed = true });

        long clock = ProtocolClock.NowNs();
        CaptureDeliveryProof Proof(long request, long seq, long previous = 0)
        {
            var getter = QpcClockSample.Read(); var compared = QpcClockSample.Read();
            // Deliberately future by 10ms at the original frozen comparison.
            var raw = compared.Nanoseconds / 100 + 100_000;
            var read = ProtocolClock.NowNs();
            return new("offline-delivery", 1, seq, request, request + 5_000_000_000,
                request, request, request, getter, compared, raw, raw, previous, read, ProtocolClock.NowNs())
                { ReleaseCompletedNs = request, DrainTakeCount = 1, BoundaryHeldCount = 0 };
        }
        var initial = Proof(clock, 1);
        Check(initial.Qualified && !initial.ToJson()["originStrictQualified"]!.GetValue<bool>()
            && initial.OriginStatus == "FUTURE_AT_READ", "future origin reclassified as strict");
        Check(initial.Rejection(initial.ReadbackCompletedNs + 2_000_000_001) is not null, "late local read accepted");
        Check(!(initial with { RepeatedSourceTicks = initial.SourceTicks + 1 }).Qualified, "changed same frame accepted");
        Check(!(initial with { PreviousMarkerNs = initial.SourceNs + 100 }).Qualified, "reordered marker accepted");
        results.Add(new { test = "future-preserved-late-repeat-reorder", proof = initial.ToJson(), passed = true });
        var strictDisposed = 0;
        try
        {
            RequestFrameSelector.Select(() => new object(), _ => initial.SourceNs, _ => strictDisposed++,
                _ => throw new Exception("strict waited for future"), () => initial.Comparison.Nanoseconds,
                () => false, clock, clock + 5_000_000_000, out _);
            throw new Exception("strict accepted future");
        }
        catch (InvalidOperationException) { Check(strictDisposed == 1, "strict future disposal changed"); }

        var output = Path.Combine(root, "source-worker"); Directory.CreateDirectory(output);
        var queue = new BlockingCollection<JsonObject>(8);
        var events = new ConcurrentQueue<JsonObject>();
        var target = new JsonObject { ["targetHwnd"] = 12, ["targetPid"] = 34 };
        var pixels = Enumerable.Range(0, 32 * 32 * 4).Select(x => (byte)(x % 255)).ToArray();
        DeliveryVisualSummary? latest = null;
        var wheels = 0;
        int produced = 0;
        var ownerIds = new ConcurrentDictionary<int, bool>();
        using var captureStop = new CancellationTokenSource();
        using var owner = new LatestCapturePump<Source, Packet>(() => new Source(() => { }), (_, cancelled) => {
            ownerIds[Environment.CurrentManagedThreadId] = true;
            if (cancelled()) throw new OperationCanceledException();
            var number = Interlocked.Increment(ref produced);
            return new(number, Enumerable.Repeat((byte)number, 4096).ToArray());
        }, () => captureStop.IsCancellationRequested, 5, reason => throw new Exception(reason));
        var business = owner.Take(1000); var businessCopy = business.Pixels.ToArray();
        Check(SpinWait.SpinUntil(() => produced >= business.Sequence + 8, 1000), "slow OCR blocked owner");
        var buffering = JsonSerializer.SerializeToElement(owner.Statistics());
        Check(buffering.GetProperty("pendingFrames").GetInt32() == 1
            && buffering.GetProperty("replacedFrames").GetInt64() >= 7, "latest memory bound/replacements wrong");
        using var lease = new WarehouseEvidenceLease(output, "offline-delivery", events.Enqueue,
            capturePolicy: CapturePolicy.Delivery, latestSummary: () => latest,
            scrollDown: (_, current) => { if (!current()) return false; wheels++; return true; });
        lease.UpdateContext(new("match-1", target, "map", 32, 32, true, true, ProtocolClock.NowNs() + 70_000_000_000, 1));
        int ordinal = 0; long sequence = 0;
        JsonObject Command(string op) => new() {
            ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.SchemaV2,
            ["operation"] = op, ["commandId"] = Guid.NewGuid().ToString("N"), ["nonce"] = "n",
            ["observationSessionId"] = "offline-delivery", ["reviewSessionId"] = "r", ["reviewGeneration"] = 1,
            ["matchGeneration"] = 1, ["recordStableKey"] = "match-1", ["expectedTargetInstance"] = target.DeepClone(),
            ["leaseToken"] = lease.LeaseToken, ["requestOrdinal"] = ordinal,
            ["remainingPages"] = 16, ["remainingPngBytes"] = 64L * 1024 * 1024,
            ["pngEncoding"] = WarehouseEvidenceLease.PngEncoding, ["allowWindowScroll"] = true };
        using var ocr = new ManualResetEventSlim();
        var blockedOcr = Task.Run(() => ocr.Wait(5000));
        var failures = new ConcurrentQueue<string>();
        using var worker = new DeliverySourcePump(lease, queue, () => { while (queue.TryTake(out var c)) lease.Handle(c); },
            (request, cancelled) => {
                return owner.Invoke((_, stopped) => {
                    ownerIds[Environment.CurrentManagedThreadId] = true;
                    if (cancelled() || stopped()) throw new OperationCanceledException();
                    var proof = Proof(request.Gate, ++sequence);
                    latest = new(proof.CaptureId, 1, proof.ReadbackCompletedNs, "scene", "warehouse", true, ScrollContentRoiSha256: "content");
                    return new WarehouseSourceFrame(32, 32, 128, pixels, proof.SourceNs, proof.ReadbackCompletedNs, "offline",
                        sequence, "", 0, proof, latest, request.Gate, request.Match);
                }, 1000, discardLatest: true);
            }, () => true, ex => failures.Enqueue(ex.Message), reason => failures.Enqueue(reason));
        queue.Add(Command("OPEN"));
        Check(SpinWait.SpinUntil(() => lease.IsOpen, 1000), "v2 did not open");
        ordinal++; var started = Stopwatch.StartNew(); queue.Add(Command("REQUEST_PAGE"));
        Check(SpinWait.SpinUntil(() => events.Any(e => (string?)e["event"] == "SOURCE"), 1500), "SOURCE waited for OCR");
        Check(!blockedOcr.IsCompleted && started.ElapsedMilliseconds < 1500, "SOURCE coupled to slow OCR");
        var saved = (JsonObject)events.Single(e => (string?)e["event"] == "SOURCE")["source"]!;
        var original = File.ReadAllBytes((string)saved["path"]!);
        Check(original.Skip(54).SequenceEqual(pixels) && saved["workerFrameSequence"] is null
            && saved["formalFactsQualified"]!.GetValue<bool>() == false, "v2 original/worker binding wrong");
        Check(ownerIds.Count == 1 && business.Pixels.SequenceEqual(businessCopy), "SOURCE owner or business ownership changed");
        var ack = Command("ACK_SOURCE"); ack["result"] = "SAVED";
        foreach (var k in new[] { "sourceLeaseId", "bmpSha256", "pixelSha256" }) ack[k] = saved[k]!.DeepClone();
        lease.Handle(ack);
        // Same saved delivery cannot authorize stability or scrolling.
        var wheel = Command("SCROLL_DOWN"); wheel["sourceLeaseId"] = saved["sourceLeaseId"]!.DeepClone();
        wheel["pixelSha256"] = saved["pixelSha256"]!.DeepClone();
        wheel["stableCaptureId"] = saved["deliveryProof"]!["captureId"]!.DeepClone();
        wheel["savedCaptureId"] = wheel["stableCaptureId"]!.DeepClone();
        lease.Handle(wheel); Check(wheels == 0, "one delivery counted as stable");
        ocr.Set(); blockedOcr.Wait();
        results.Add(new { test = "source-v2-save-before-slow-ocr-and-no-facts", elapsedMs = started.ElapsedMilliseconds,
            hash = saved["bmpSha256"]!.DeepClone(), wheels, buffering = owner.Statistics(), passed = true });

        // A captured original from match 1 cannot publish against match 2.
        lease.UpdateContext(new("match-1", target, "map", 32, 32, true, true, ProtocolClock.NowNs() + 70_000_000_000, 1));
        lease.Handle(Command("OPEN")); ordinal++; lease.Handle(Command("REQUEST_PAGE"));
        var pending = lease.RequestSnapshot();
        lease.UpdateContext(new("match-2", target, "map", 32, 32, true, true, ProtocolClock.NowNs() + 70_000_000_000, 2));
        Check(pending is not null && !lease.RequestCurrent(pending.Value.Gate, pending.Value.Match, pending.Value.Token), "old match still current");
        var staleProof = Proof(pending!.Value.Gate, ++sequence);
        Check(!lease.TryPublish(new(32, 32, 128, pixels, staleProof.SourceNs, staleProof.ReadbackCompletedNs,
            "offline", sequence, "", 0, staleProof, latest, pending.Value.Gate, 1), () => true), "late page crossed match");
        lease.SignalStop(); Check(!lease.IsOpen, "stop not immediate");
        Check(failures.IsEmpty, "SOURCE worker failed");
        results.Add(new { test = "stop-and-cross-match-late-source", passed = true });

        // An old worker exception must not close a newly opened match's lease.
        {
            using var entered = new ManualResetEventSlim(); using var resume = new ManualResetEventSlim();
            var exceptionObserved = 0; var newEvents = new ConcurrentQueue<JsonObject>();
            using var isolated = new WarehouseEvidenceLease(Path.Combine(root, "late-exception"),
                "offline-delivery", newEvents.Enqueue, capturePolicy: CapturePolicy.Delivery);
            isolated.UpdateContext(new("match-1", target, "map", 32, 32, true, true, ProtocolClock.NowNs() + 70_000_000_000, 1));
            var open = Command("OPEN"); open["leaseToken"] = null; isolated.Handle(open);
            var request = Command("REQUEST_PAGE"); request["leaseToken"] = isolated.LeaseToken; request["requestOrdinal"] = 1; isolated.Handle(request);
            using var lateWorker = new DeliverySourcePump(isolated, new BlockingCollection<JsonObject>(1), () => { }, (_, _) => {
                entered.Set(); if (!resume.Wait(1000)) throw new Exception("test-release-timeout");
                throw new InvalidOperationException("old-match-failed");
            }, () => true, _ => Interlocked.Increment(ref exceptionObserved), _ => { });
            Check(entered.Wait(1000), "old source did not enter");
            isolated.UpdateContext(new("match-2", target, "map", 32, 32, true, true, ProtocolClock.NowNs() + 70_000_000_000, 2));
            open = Command("OPEN"); open["leaseToken"] = null; open["recordStableKey"] = "match-2"; open["matchGeneration"] = 2;
            isolated.Handle(open); var successorToken = isolated.LeaseToken; Check(isolated.IsOpen, "successor did not open");
            resume.Set();
            Check(SpinWait.SpinUntil(() => exceptionObserved == 1, 1000), "old exception not observed");
            Check(isolated.IsOpen && isolated.LeaseToken == successorToken, "old failure closed successor");
            Check(!newEvents.Any(e => (string?)e["event"] == "SOURCE"), "old exception published source");
            results.Add(new { test = "late-worker-exception-preserves-successor", passed = true });
        }

        // Actual file admission failures and cancellation after an original has reached disk.
        foreach (var failureKind in new[] { "save-failure", "stop-during-save" })
        {
            var path = Path.Combine(root, failureKind); Directory.CreateDirectory(path);
            var captured = new List<JsonObject>();
            using var failed = new WarehouseEvidenceLease(path, "offline-delivery", captured.Add, capturePolicy: CapturePolicy.Delivery);
            failed.UpdateContext(new("match-1", target, "map", 32, 32, true, true, ProtocolClock.NowNs() + 70_000_000_000, 1));
            var open = Command("OPEN"); open["leaseToken"] = null; failed.Handle(open);
            var request = Command("REQUEST_PAGE"); request["leaseToken"] = failed.LeaseToken; request["requestOrdinal"] = 1; failed.Handle(request);
            var snapshot = failed.RequestSnapshot()!.Value;
            if (failureKind == "save-failure") File.WriteAllText(Path.Combine(path, "warehouse-sources"), "not a directory");
            var proof = Proof(snapshot.Gate, 1); var probes = 0;
            var published = failed.TryPublish(new(32, 32, 128, pixels, proof.SourceNs, proof.ReadbackCompletedNs,
                "offline", 1, "", 0, proof, null, snapshot.Gate, 1), () => {
                    if (++probes == 2 && failureKind == "stop-during-save") failed.SignalStop();
                    return true;
                });
            Check(!published && !captured.Any(e => (string?)e["event"] == "SOURCE"), "failed/stopped save published");
            Check(failed.WrittenSources == 1, "potential original not charged");
            if (failureKind == "stop-during-save") Check(Directory.GetFiles(Path.Combine(path, "warehouse-sources")).Length == 1, "cancel removed original");
            results.Add(new { test = failureKind, originalsCharged = failed.WrittenSources, passed = true });
        }

        // Equal pixels need independent requests/IDs; latest ROI changes revoke input separately.
        foreach (var changedRoi in new[] { false, true })
        {
            var records = new List<JsonObject>(); var pulses = 0;
            DeliveryVisualSummary? summary = null;
            using var stable = new WarehouseEvidenceLease(Path.Combine(root, "stable-" + changedRoi), "offline-delivery", records.Add,
                capturePolicy: CapturePolicy.Delivery, latestSummary: () => summary,
                scrollDown: (_, current) => { if (!current()) return false; pulses++; return true; });
            stable.UpdateContext(new("match-1", target, "map", 32, 32, true, true, ProtocolClock.NowNs() + 70_000_000_000, 1));
            var open = Command("OPEN"); open["leaseToken"] = null; stable.Handle(open);
            var request = Command("REQUEST_PAGE"); request["leaseToken"] = stable.LeaseToken; request["requestOrdinal"] = 1; stable.Handle(request);
            var snapshot = stable.RequestSnapshot()!.Value; var first = Proof(snapshot.Gate, 1);
            summary = new(first.CaptureId, 1, first.ReadbackCompletedNs, "scene", "warehouse", true, ScrollContentRoiSha256: "content");
            Check(stable.TryPublish(new(32, 32, 128, pixels, first.SourceNs, first.ReadbackCompletedNs, "offline", 1,
                "", 0, first, summary, snapshot.Gate, 1), () => true), "first original not saved");
            var originalReceipt = (JsonObject)records.Single(e => (string?)e["event"] == "SOURCE")["source"]!;
            ack = Command("ACK_SOURCE"); ack["leaseToken"] = stable.LeaseToken; ack["requestOrdinal"] = 1; ack["result"] = "SAVED";
            foreach (var k in new[] { "sourceLeaseId", "bmpSha256", "pixelSha256" }) ack[k] = originalReceipt[k]!.DeepClone();
            stable.Handle(ack); Thread.Sleep(260);
            request = Command("REQUEST_PAGE"); request["leaseToken"] = stable.LeaseToken; request["requestOrdinal"] = 2; stable.Handle(request);
            snapshot = stable.RequestSnapshot()!.Value; var second = Proof(snapshot.Gate, 2, first.SourceNs);
            summary = new(second.CaptureId, 1, second.ReadbackCompletedNs, changedRoi ? "different-scene" : "scene", "warehouse", true, ScrollContentRoiSha256: "content");
            Check(!stable.TryPublish(new(32, 32, 128, pixels, second.SourceNs, second.ReadbackCompletedNs, "offline", 2,
                "", 0, second, summary, snapshot.Gate, 1), () => true), "duplicate original saved twice");
            Check(records.Any(e => (string?)e["reason"] == "DUPLICATE_PAGE"), "separate equal support not recorded");
            var scroll = Command("SCROLL_DOWN"); scroll["leaseToken"] = stable.LeaseToken; scroll["requestOrdinal"] = 2;
            scroll["sourceLeaseId"] = originalReceipt["sourceLeaseId"]!.DeepClone(); scroll["pixelSha256"] = originalReceipt["pixelSha256"]!.DeepClone();
            scroll["savedCaptureId"] = first.CaptureId; scroll["stableCaptureId"] = second.CaptureId;
            stable.Handle(scroll);
            Check(pulses == (changedRoi ? 0 : 1), "current ROI/input gate wrong");
            Check(stable.WrittenSources == 1, "equal support counted as a second page");
            results.Add(new { test = "independent-static-support-and-latest-roi", changedRoi, pulses, originals = stable.WrittenSources, passed = true });
        }
        Console.WriteLine(JsonSerializer.Serialize(new { passed = true, gameCapture = false, gameInput = false, results },
            new JsonSerializerOptions { WriteIndented = true }));
    }
}
