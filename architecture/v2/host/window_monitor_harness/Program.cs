using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using NteHost.Protocol;
using NteHost.WindowMonitor;

namespace NteHost.WindowMonitor.Harness;

/// <summary>
/// Controlled-window test harness for V2-2A.
///
/// It exists so the window/focus mechanism can be driven for real - a real Win32
/// window in a real separate process, real SetWinEventHook delivery, real
/// SetForegroundWindow - without ever needing the actual game to be installed.
///
/// It is NOT a game emulator: the windows it creates carry an explicit test class
/// name and a process image name of this harness. The default production spec
/// (htgame.exe / UnrealWindow) can never match them, which is exactly why a
/// controlled-window pass can never be presented as the real product positive case.
///
/// Modes:
///   serve    creates controllable windows and executes commands from stdin
///   monitor  runs WindowMonitor against a given spec and dumps events as JSON
/// </summary>
internal static class Program
{
    private static readonly JsonSerializerOptions JsonOut = new() { WriteIndented = false };

    private static int Main(string[] args)
    {
        var mode = Arg(args, "--mode", string.Empty);
        return mode switch
        {
            "serve" => Serve(args),
            "monitor" => Monitor(args),
            "integration" => ControlledIntegrationHarness.Run(args),
            "integration-live" => LiveIntegrationHarness.Run(args),
            "specprobe" => SpecProbe(),
            _ => Fail($"unknown --mode '{mode}' (expected serve|monitor|integration|integration-live)"),
        };
    }

    private static int Fail(string message)
    {
        Console.Error.WriteLine(message);
        return 2;
    }

    private static string Arg(string[] args, string name, string fallback)
    {
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == name)
            {
                return args[i + 1];
            }
        }
        return fallback;
    }

    private static bool Flag(string[] args, string name) => args.Contains(name);

    private static void Emit(object payload) =>
        Console.WriteLine(JsonSerializer.Serialize(payload, JsonOut));

    // =========================================================== serve mode ===

    private static int Serve(string[] args)
    {
        var className = Arg(args, "--class", "NteV22ControlledWindow");
        var otherClassName = Arg(args, "--other-class", className + "Other");
        var titlePrefix = Arg(args, "--title-prefix", "nte-controlled");
        var initialCount = int.Parse(Arg(args, "--count", "2"));
        var width = int.Parse(Arg(args, "--width", "340"));
        var height = int.Parse(Arg(args, "--height", "220"));

        var host = new ControlledWindowHost(className, otherClassName, titlePrefix, width, height);
        if (!host.TryRegisterClass(out var registerError))
        {
            Emit(new { phase = "error", error = registerError });
            return 3;
        }

        for (var i = 0; i < initialCount; i++)
        {
            host.Create(i);
        }

        // Windows only grants foreground rights to a process that is the foreground
        // process, received the last input, or was just started. Grabbing foreground
        // immediately at launch is therefore the only reliable window: once this
        // process owns the foreground it may freely switch between its own windows.
        var grab = Flag(args, "--grab-foreground");
        object? grabResult = null;
        if (grab && initialCount > 0)
        {
            var result = host.SetForeground(0, attempts: 12);
            host.Pump(250);
            grabResult = new
            {
                callOk = result.CallOk,
                callError = result.Error,
                hwnd = result.Hwnd,
                fg = host.Foreground(),
                tookEffect = host.Foreground() == result.Hwnd,
            };
        }

        Emit(new
        {
            phase = "ready",
            pid = Environment.ProcessId,
            imageName = System.Diagnostics.Process.GetCurrentProcess().ProcessName + ".exe",
            className,
            otherClassName,
            width,
            height,
            windows = host.Describe(),
            grabForeground = grabResult,
        });

        // stdin reader on a background thread; commands execute on the pump thread so
        // SetForegroundWindow runs on the window-owning thread.
        var commands = new System.Collections.Concurrent.ConcurrentQueue<string>();
        var reader = new Thread(() =>
        {
            string? line;
            while ((line = Console.ReadLine()) is not null)
            {
                commands.Enqueue(line);
            }
            commands.Enqueue("exit");
        })
        {
            IsBackground = true,
            Name = "harness-stdin",
        };
        reader.Start();

        while (true)
        {
            host.Pump(10);

            while (commands.TryDequeue(out var line))
            {
                var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length == 0)
                {
                    continue;
                }

                switch (parts[0])
                {
                    case "exit":
                        host.DestroyAll();
                        Emit(new { phase = "exited" });
                        return 0;

                    case "create":
                    {
                        var id = int.Parse(parts[1]);
                        var hwnd = host.Create(id);
                        host.Pump(60);
                        Emit(new { phase = "cmd", cmd = "create", id, hwnd, fg = host.Foreground() });
                        break;
                    }

                    case "createother":
                    {
                        // A window that shares the process image but NOT the target
                        // class, so the spec must reject it.
                        var id = int.Parse(parts[1]);
                        var hwnd = host.CreateOther(id);
                        host.Pump(60);
                        Emit(new { phase = "cmd", cmd = "createother", id, hwnd, fg = host.Foreground() });
                        break;
                    }

                    case "destroy":
                    {
                        var id = int.Parse(parts[1]);
                        host.Destroy(id);
                        host.Pump(60);
                        Emit(new { phase = "cmd", cmd = "destroy", id, fg = host.Foreground() });
                        break;
                    }

                    case "hide":
                    {
                        var id = int.Parse(parts[1]);
                        host.Hide(id);
                        host.Pump(60);
                        Emit(new { phase = "cmd", cmd = "hide", id, fg = host.Foreground() });
                        break;
                    }

                    case "show":
                    {
                        var id = int.Parse(parts[1]);
                        host.Show(id);
                        host.Pump(60);
                        Emit(new { phase = "cmd", cmd = "show", id, fg = host.Foreground() });
                        break;
                    }

                    case "fg":
                    {
                        var id = int.Parse(parts[1]);
                        var result = host.SetForeground(id);
                        host.Pump(200);
                        Emit(new
                        {
                            phase = "cmd",
                            cmd = "fg",
                            id,
                            requested = result.Requested,
                            callOk = result.CallOk,
                            callError = result.Error,
                            hwnd = result.Hwnd,
                            fg = host.Foreground(),
                            tookEffect = host.Foreground() == result.Hwnd,
                        });
                        break;
                    }

                    case "recreate":
                    {
                        var id = int.Parse(parts[1]);
                        host.Destroy(id);
                        host.Pump(80);
                        var hwnd = host.Create(id);
                        host.Pump(80);
                        Emit(new { phase = "cmd", cmd = "recreate", id, hwnd, fg = host.Foreground() });
                        break;
                    }

                    case "describe":
                        Emit(new { phase = "cmd", cmd = "describe", windows = host.Describe(), fg = host.Foreground() });
                        break;

                    default:
                        Emit(new { phase = "cmd", cmd = parts[0], error = "unknown command" });
                        break;
                }
            }
        }
    }

    // ======================================================= specprobe mode ===

    /// <summary>
    /// Machine-checks the target window definition as a pure rule, so the semantic
    /// target (htgame.exe / UnrealWindow) can be verified without the game being
    /// installed and without pretending a test window is the game.
    /// </summary>
    private static int SpecProbe()
    {
        var spec = TargetWindowSpec.Default;
        var cases = new (string Image, string Class)[]
        {
            ("htgame.exe", "UnrealWindow"),
            ("HTGAME.EXE", "unrealwindow"),
            ("htgame.exe", "Chrome_WidgetWin_1"),
            ("chrome.exe", "UnrealWindow"),
            ("htgame.exe", ""),
            ("", "UnrealWindow"),
            ("htgame.exe", "UnrealWindowChild"),
            ("htgame_launcher.exe", "UnrealWindow"),
            ("WindowMonitorHarness.exe", "NteV22ControlledWindow"),
            ("WindowMonitorHarness.exe", "NteV22ControlledWindowOther"),
        };

        var results = cases.Select(c => new
        {
            processImageName = c.Image,
            windowClass = c.Class,
            matches = spec.Matches(c.Image, c.Class),
        }).ToArray();

        Emit(new
        {
            phase = "specprobe",
            spec = new { processImageName = spec.ProcessImageName, windowClass = spec.WindowClass },
            describe = spec.Describe(),
            cases = results,
            matchCount = results.Count(r => r.matches),
        });
        return 0;
    }

    // ========================================================= monitor mode ===

    private static int Monitor(string[] args)
    {
        var specImage = Arg(args, "--spec-image", "htgame.exe");
        var specClass = Arg(args, "--spec-class", "UnrealWindow");
        var outPath = Arg(args, "--out", string.Empty);
        var durationMs = int.Parse(Arg(args, "--duration-ms", "15000"));
        var requireVisible = !Flag(args, "--allow-hidden");
        var skipOwn = Flag(args, "--skip-own-process");
        var identityDelayMs = int.Parse(Arg(args, "--identity-delay-ms", "0"));
        var queueCapacity = int.Parse(Arg(args, "--queue-capacity", "4096"));

        var spec = new TargetWindowSpec(specImage, specClass);
        var options = new WindowMonitorOptions
        {
            Spec = spec,
            RequireVisible = requireVisible,
            SkipOwnProcessInHook = skipOwn,
            IdentityWorkDelayMsForDiagnostics = identityDelayMs,
            EventQueueCapacity = queueCapacity,
        };

        var monitor = new WindowMonitor(options);
        monitor.Start();
        monitor.WaitForIdle(1500);

        var initialObservation = monitor.ReadIntegrationObservation();
        var initialSnapshot = initialObservation.Snapshot;

        Emit(new
        {
            phase = "monitoring",
            pid = Environment.ProcessId,
            spec = new { processImageName = spec.ProcessImageName, windowClass = spec.WindowClass },
            hookInstalled = monitor.IsHookInstalled,
            initialSnapshot = Describe(initialSnapshot),
            initialObservation = DescribeIntegrationObservation(initialObservation),
        });

        // Run until the duration elapses or the parent says stop.
        var stop = new System.Collections.Concurrent.ConcurrentQueue<string>();
        var reader = new Thread(() =>
        {
            string? line;
            while ((line = Console.ReadLine()) is not null)
            {
                stop.Enqueue(line);
            }
            stop.Enqueue("stop");
        })
        {
            IsBackground = true,
            Name = "monitor-stdin",
        };
        reader.Start();

        var deadline = Environment.TickCount64 + durationMs;
        var stopRequested = false;
        while (Environment.TickCount64 < deadline && !stopRequested)
        {
            while (stop.TryDequeue(out var cmd))
            {
                var parts = cmd.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length == 0)
                {
                    continue;
                }

                switch (parts[0])
                {
                    case "stop":
                    case "exit":
                        stopRequested = true;
                        break;

                    case "inject":
                    {
                        // Stress seam: push N synthetic raw events through exactly the
                        // path the WinEvent callback uses, and report how long the
                        // ingestion took.
                        var count = parts.Length > 1 ? int.Parse(parts[1]) : 1;
                        var rawEnqueuedBefore = monitor.RawEnqueuedEventCountForDiagnostics;
                        var started = System.Diagnostics.Stopwatch.GetTimestamp();
                        for (var i = 0; i < count; i++)
                        {
                            monitor.InjectRawEventForDiagnostics(
                                WindowMonitor.DiagnosticCreateEventType, 0);
                        }
                        var elapsedUs = System.Diagnostics.Stopwatch.GetElapsedTime(started).TotalMicroseconds;
                        var rawEnqueuedAfter = monitor.RawEnqueuedEventCountForDiagnostics;
                        Emit(new
                        {
                            phase = "cmd", cmd = "inject", count,
                            totalUs = elapsedUs,
                            perEventUs = count > 0 ? elapsedUs / count : 0.0,
                            processedEvents = monitor.ProcessedEventCount,
                            rawEnqueuedCountBefore = rawEnqueuedBefore,
                            rawEnqueuedCountAfter = rawEnqueuedAfter,
                            rawEnqueuedCountDelta = rawEnqueuedAfter - rawEnqueuedBefore,
                        });
                        break;
                    }

                    case "holdraw":
                    {
                        // Stress seam: hold the raw queue lock for a while. Proves the
                        // worker does not need that lock, so there is no deadlock and no
                        // mutual serialisation between ingestion and the state machine.
                        var ms = parts.Length > 1 ? int.Parse(parts[1]) : 100;
                        var started = System.Diagnostics.Stopwatch.GetTimestamp();
                        monitor.HoldRawQueueLockForDiagnostics(ms);
                        Emit(new
                        {
                            phase = "cmd", cmd = "holdraw", requestedMs = ms,
                            actualUs = System.Diagnostics.Stopwatch.GetElapsedTime(started).TotalMicroseconds,
                        });
                        break;
                    }

                    case "holdrawstart":
                    {
                        // Deterministic direction-B seam: start the holder on its own
                        // thread and acknowledge only after the queue lock is confirmed
                        // acquired. The monitor command loop remains available for an
                        // independent producer and the explicit release signal.
                        var ms = parts.Length > 1 ? int.Parse(parts[1]) : 100;
                        var queueCountBeforeHold = monitor.TryRawQueueCountForDiagnostics;
                        monitor.BeginRawQueueLockHoldForDiagnostics(ms);
                        var acquired = monitor.WaitForRawQueueLockAcquiredForDiagnostics(5000);
                        Emit(new
                        {
                            phase = "cmd", cmd = "holdrawstart", requestedMs = ms,
                            acquired, queueCount = queueCountBeforeHold,
                        });
                        break;
                    }

                    case "releaseraw":
                    {
                        // Release the confirmed holder, then wait for a producer that
                        // may have been blocked on the real queue lock to finish.
                        monitor.ReleaseRawQueueLockForDiagnostics();
                        var producerCompleted = monitor.WaitForRawProducerCompletedForDiagnostics(5000);
                        Emit(new
                        {
                            phase = "cmd", cmd = "releaseraw", released = true,
                            producerCompleted, queueCount = monitor.RawQueueCount,
                        });
                        break;
                    }

                    case "identityprobe":
                    {
                        // Stress seam: report the identity-cache generation and the
                        // number of real image resolutions so far, so a test can prove
                        // cache invalidation actually happened at an identity boundary.
                        Emit(new
                        {
                            phase = "cmd", cmd = "identityprobe",
                            cacheGeneration = monitor.IdentityCacheGeneration,
                            imageNameResolutions = monitor.ImageNameResolutions,
                            rawCallbackCount = monitor.RawCallbackCount,
                            processedEvents = monitor.ProcessedEventCount,
                            droppedEvents = monitor.DroppedEventCount,
                            queueCount = monitor.TryRawQueueCountForDiagnostics,
                        });
                        break;
                    }

                    case "statusprobe":
                    {
                        // Stress seam: the counters the lock-isolation and overflow
                        // regression tests assert on.
                        Emit(new
                        {
                            phase = "cmd", cmd = "statusprobe",
                            processedEvents = monitor.ProcessedEventCount,
                            droppedEvents = monitor.DroppedEventCount,
                            overflowObservations = monitor.OverflowObservationCount,
                            recoveryScans = monitor.RecoveryScanCount,
                            rawCallbackCount = monitor.RawCallbackCount,
                            stateGateHeld = monitor.IsStateGateHeldForDiagnostics,
                            workerBusy = monitor.IsWorkerBusyForDiagnostics,
                            rawIngestionInFlight = monitor.RawIngestionInFlightForDiagnostics,
                            rawEnqueuedCount = monitor.RawEnqueuedEventCountForDiagnostics,
                            queueCount = monitor.TryRawQueueCountForDiagnostics,
                        });
                        break;
                    }

                    case "observe":
                    {
                        var observation = monitor.ReadIntegrationObservation();
                        Emit(new
                        {
                            phase = "cmd", cmd = "observe",
                            observation = DescribeIntegrationObservation(observation),
                        });
                        break;
                    }

                    case "holdstate":
                    {
                        // Stress seam: hold the STATE lock from a test-controlled thread
                        // and report once it is actually taken. This makes direction A
                        // deterministic: the hold is proven, not inferred.
                        var ms = parts.Length > 1 ? int.Parse(parts[1]) : 300;
                        monitor.HoldStateGateForDiagnostics(ms);
                        var acquired = monitor.WaitForStateGateAcquiredForDiagnostics(5000);
                        Emit(new
                        {
                            phase = "cmd", cmd = "holdstate", requestedMs = ms,
                            acquired,
                            stateGateHeld = monitor.IsStateGateHeldForDiagnostics,
                        });
                        break;
                    }

                    case "releasestate":
                    {
                        monitor.ReleaseStateGateForDiagnostics();
                        Emit(new { phase = "cmd", cmd = "releasestate", released = true });
                        break;
                    }

                    case "suppress":
                    {
                        var on = parts.Length > 1 && parts[1] == "1";
                        monitor.SetRawIngestionSuppressedForDiagnostics(on);
                        Emit(new { phase = "cmd", cmd = "suppress", suppressed = on });
                        break;
                    }

                    case "overflow":
                    {
                        // Stress seam: push N events straight into the bounded queue,
                        // bypassing suppression, so a small-capacity queue overflows on
                        // demand rather than by luck.
                        var count = parts.Length > 1 ? int.Parse(parts[1]) : 1;
                        monitor.OverflowQueueForDiagnostics(count);
                        Emit(new
                        {
                            phase = "cmd", cmd = "overflow", count,
                            droppedEvents = monitor.DroppedEventCount,
                        });
                        break;
                    }

                    case "rawpush":
                    {
                        // Stress seam: enqueue through the raw queue without the
                        // suppression toggle, to prove ingestion resumes after a hold.
                        var count = parts.Length > 1 ? int.Parse(parts[1]) : 1;
                        for (var i = 0; i < count; i++)
                        {
                            monitor.EnqueueRawEventBypassingSuppressionForDiagnostics(
                                WindowMonitor.DiagnosticCreateEventType, 0);
                        }
                        Emit(new { phase = "cmd", cmd = "rawpush", count });
                        break;
                    }

                    case "rawpushstart":
                    {
                        // Start an independent producer. It is allowed to block in the
                        // real enqueue while the raw lock holder is confirmed active;
                        // the producer must not be sequenced after lock release.
                        var count = parts.Length > 1 ? int.Parse(parts[1]) : 1;
                        monitor.StartRawProducerForDiagnostics(count);
                        var started = monitor.WaitForRawProducerStartedForDiagnostics(5000);
                        Emit(new
                        {
                            phase = "cmd", cmd = "rawpushstart", count, started,
                            completed = monitor.IsRawProducerCompletedForDiagnostics,
                        });
                        break;
                    }

                    default:
                        Emit(new { phase = "cmd", cmd = parts[0], error = "unknown command" });
                        break;
                }
            }
            Thread.Sleep(20);
        }

        monitor.WaitForIdle(2000);
        var runObservation = monitor.ReadIntegrationObservation();
        var runSnapshot = runObservation.Snapshot;
        var events = monitor.Events;

        var rawBeforeDispose = monitor.RawCallbackCount;
        var hookInstalledBeforeDispose = monitor.IsHookInstalled;
        var processedBeforeDispose = monitor.ProcessedEventCount;
        var droppedBeforeDispose = monitor.DroppedEventCount;
        var cacheGenerationBeforeDispose = monitor.IdentityCacheGeneration;
        var resolutionsBeforeDispose = monitor.ImageNameResolutions;
        var recoveryScansBeforeDispose = monitor.RecoveryScanCount;

        var disposeWatch = System.Diagnostics.Stopwatch.GetTimestamp();
        monitor.Dispose();
        var disposeElapsedUs = System.Diagnostics.Stopwatch.GetElapsedTime(disposeWatch).TotalMicroseconds;

        // Settle point. UnhookWinEvent stops future callbacks but cannot revoke one
        // that Windows already delivered to the pump thread; that callback may be
        // executing while we read the counter. Waiting for the module's own idle
        // signal (rather than sleeping an arbitrary amount) makes "after Dispose"
        // mean "after the unsubscribe has provably taken effect" instead of racing
        // the last in-flight callback.
        monitor.WaitForIdle(2000);
        var rawImmediatelyAfterDispose = monitor.RawCallbackCount;
        var hookInstalledAfterDispose = monitor.IsHookInstalled;

        Emit(new
        {
            phase = "disposed",
            rawCallbackCount = rawBeforeDispose,
            hookInstalledAfterDispose,
            disposeElapsedUs,
        });

        // Phase 2: the parent now generates window churn while we hold no hook. If any
        // callback were still wired up, the counter would move.
        var reportRequested = false;
        var phase2Deadline = Environment.TickCount64 + 20000;
        while (Environment.TickCount64 < phase2Deadline && !reportRequested)
        {
            while (stop.TryDequeue(out var cmd))
            {
                if (cmd.Trim() == "report")
                {
                    reportRequested = true;
                }
            }
            Thread.Sleep(20);
        }

        var rawAfterChurn = monitor.RawCallbackCount;

        var payload = new
        {
            schemaVersion = "v2.2a.window.monitor.harness.v1",
            spec = new { processImageName = spec.ProcessImageName, windowClass = spec.WindowClass },
            requireVisible,
            skipOwnProcessInHook = skipOwn,
            identityWorkDelayMsForDiagnostics = identityDelayMs,
            hookInstalled = hookInstalledBeforeDispose,
            hookInstalledAfterDispose,
            disposeElapsedUs,
            counters = new
            {
                rawCallbackCount = rawBeforeDispose,
                rawCallbackCountImmediatelyAfterDispose = rawImmediatelyAfterDispose,
                rawCallbackCountAfterExternalChurn = rawAfterChurn,
                processedEvents = processedBeforeDispose,
                droppedEvents = droppedBeforeDispose,
                recoveryScans = recoveryScansBeforeDispose,
                imageNameResolutions = resolutionsBeforeDispose,
                identityCacheGeneration = cacheGenerationBeforeDispose,
            },
            noResidualCallback = rawAfterChurn == rawImmediatelyAfterDispose
                                && rawImmediatelyAfterDispose == rawBeforeDispose,
            initialSnapshot = Describe(initialSnapshot),
            initialObservation = DescribeIntegrationObservation(initialObservation),
            finalSnapshot = Describe(runSnapshot),
            finalObservation = DescribeIntegrationObservation(runObservation),
            eventCount = events.Count,
            events = events.Select(DescribeEvent),
        };

        var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
        if (!string.IsNullOrEmpty(outPath))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath))!);
            File.WriteAllText(outPath, json + Environment.NewLine, new UTF8Encoding(false));
        }
        Console.WriteLine(json);
        return 0;
    }

    private static object Describe(WindowMonitorSnapshot s) => new
    {
        targetHwnd = s.TargetHwnd,
        targetPid = s.TargetPid,
        foregroundHwnd = s.ForegroundHwnd,
        isTargetAlive = s.IsTargetAlive,
        isTargetForeground = s.IsTargetForeground,
        generation = s.Generation,
        observedAtNs = s.ObservedAtNs,
        reason = s.Reason,
        targetImageName = s.TargetIdentity?.ProcessImageName ?? string.Empty,
        targetClassName = s.TargetIdentity?.ClassName ?? string.Empty,
    };

    private static object DescribeIntegrationObservation(WindowMonitorIntegrationObservation observation) => new
    {
        rawRevisionBeforeBatch = observation.RawRevisionBeforeBatch,
        rawRevision = observation.RawRevision,
        hasPendingEvents = observation.HasPendingEvents,
        droppedSinceLastRead = observation.DroppedSinceLastRead,
        snapshot = Describe(observation.Snapshot),
        rawEventRevisions = observation.RawEventRevisions,
        events = observation.Events.Select(DescribeEvent),
    };

    private static object DescribeEvent(WindowMonitorEvent e) => new
    {
        sequence = e.Sequence,
        rawRevision = e.RawRevision,
        kind = e.Kind.ToString(),
        sourceEvent = e.SourceEvent,
        targetHwnd = e.TargetHwnd,
        targetPid = e.TargetPid,
        targetImageName = e.TargetImageName,
        targetClassName = e.TargetClassName,
        foregroundHwnd = e.ForegroundHwnd,
        isTargetAlive = e.IsTargetAlive,
        isTargetForeground = e.IsTargetForeground,
        generation = e.Generation,
        observedAtNs = e.ObservedAtNs,
        reason = e.Reason,
    };

    // ================================================= controlled window host ===

    private sealed class ControlledWindowHost
    {
        private readonly string _className;
        private readonly string _otherClassName;
        private readonly string _titlePrefix;
        private readonly int _width;
        private readonly int _height;
        private readonly Dictionary<int, IntPtr> _windows = new();
        private readonly WndProcDelegate _wndProc;

        public ControlledWindowHost(string className, string otherClassName, string titlePrefix, int width, int height)
        {
            _className = className;
            _otherClassName = otherClassName;
            _titlePrefix = titlePrefix;
            _width = Math.Max(64, width);
            _height = Math.Max(64, height);
            _wndProc = WindowProc;
        }

        public bool TryRegisterClass(out string error)
        {
            foreach (var name in new[] { _className, _otherClassName })
            {
                var wc = new WNDCLASSEXW
                {
                    cbSize = (uint)Marshal.SizeOf<WNDCLASSEXW>(),
                    style = 0,
                    lpfnWndProc = _wndProc,
                    hInstance = GetModuleHandleW(null),
                    lpszClassName = name,
                };

                if (RegisterClassExW(ref wc) == 0)
                {
                    error = $"RegisterClassExW('{name}') failed: {Marshal.GetLastWin32Error()}";
                    return false;
                }
            }

            error = string.Empty;
            return true;
        }

        public long Create(int id) => CreateInClass(id, _className);

        public long CreateOther(int id) => CreateInClass(id, _otherClassName);

        private long CreateInClass(int id, string className)
        {
            var hwnd = CreateWindowExW(
                0, className, $"{_titlePrefix}-{id}", WS_OVERLAPPEDWINDOW,
                120 + (id * 60), 120 + (id * 40), _width, _height,
                IntPtr.Zero, IntPtr.Zero, GetModuleHandleW(null), IntPtr.Zero);

            if (hwnd == IntPtr.Zero)
            {
                return 0;
            }

            _windows[id] = hwnd;
            ShowWindow(hwnd, SW_SHOW);
            UpdateWindow(hwnd);
            return hwnd.ToInt64();
        }

        public void Destroy(int id)
        {
            if (_windows.Remove(id, out var hwnd))
            {
                DestroyWindow(hwnd);
            }
        }

        public void Hide(int id)
        {
            if (_windows.TryGetValue(id, out var hwnd))
            {
                ShowWindow(hwnd, SW_HIDE);
            }
        }

        public void Show(int id)
        {
            if (_windows.TryGetValue(id, out var hwnd))
            {
                ShowWindow(hwnd, SW_SHOW);
            }
        }

        public void DestroyAll()
        {
            foreach (var hwnd in _windows.Values)
            {
                DestroyWindow(hwnd);
            }
            _windows.Clear();
        }

        public (bool Requested, bool CallOk, int Error, long Hwnd) SetForeground(int id, int attempts = 1)
        {
            if (!_windows.TryGetValue(id, out var hwnd))
            {
                return (false, false, 0, 0);
            }

            // Called on the window-owning thread. A process may bring its own window
            // to the foreground; a foreign process generally may not, which is why the
            // controlled window must live in its own process for these tests.
            //
            // Windows' foreground lock still refuses the request sometimes, so the
            // plain call is retried and then combined with AttachThreadInput against
            // the current foreground thread, which is the documented workaround.
            var lastOk = false;
            var lastError = 0;
            for (var attempt = 0; attempt < attempts; attempt++)
            {
                BringWindowToTop(hwnd);
                lastOk = SetForegroundWindow(hwnd);
                lastError = Marshal.GetLastWin32Error();
                Pump(40);
                if (GetForegroundWindow() == hwnd)
                {
                    return (true, lastOk, lastError, hwnd.ToInt64());
                }

                var foreground = GetForegroundWindow();
                var foregroundThread = GetWindowThreadProcessId(foreground, out _);
                var thisThread = GetCurrentThreadId();
                if (foregroundThread != 0 && foregroundThread != thisThread)
                {
                    if (AttachThreadInput(thisThread, foregroundThread, true))
                    {
                        BringWindowToTop(hwnd);
                        SetForegroundWindow(hwnd);
                        AttachThreadInput(thisThread, foregroundThread, false);
                        Pump(40);
                        if (GetForegroundWindow() == hwnd)
                        {
                            return (true, true, 0, hwnd.ToInt64());
                        }
                    }
                }

                Thread.Sleep(120);
            }

            return (true, lastOk, lastError, hwnd.ToInt64());
        }

        public long Foreground() => GetForegroundWindow().ToInt64();

        public object Describe() => _windows.ToDictionary(
            kv => kv.Key.ToString(),
            kv => kv.Value.ToInt64());

        public void Pump(int ms)
        {
            var deadline = Environment.TickCount64 + ms;
            var msg = default(MSG);
            while (Environment.TickCount64 < deadline)
            {
                while (PeekMessageW(ref msg, IntPtr.Zero, 0, 0, PM_REMOVE))
                {
                    TranslateMessage(ref msg);
                    DispatchMessageW(ref msg);
                }
                Thread.Sleep(2);
            }
        }

        private IntPtr WindowProc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam)
        {
            if (msg == WM_PAINT)
            {
                var hdc = GetDC(hwnd);
                if (hdc != IntPtr.Zero)
                {
                    var client = default(RECT);
                    GetClientRect(hwnd, ref client);
                    var whole = CreateSolidBrush(0x00202020);
                    FillRect(hdc, ref client, whole);
                    DeleteObject(whole);

                    var cells = new[]
                    {
                        (0x00D05A3A, 24, 24, 300, 150),
                        (0x0030A0D0, 330, 24, 620, 150),
                        (0x0050B050, 650, 24, 940, 150),
                        (0x00C0A040, 970, 24, 1240, 150),
                        (0x009050C0, 24, 190, 620, 470),
                        (0x0040A0A0, 650, 190, 1240, 470),
                    };
                    foreach (var (color, left, top, right, bottom) in cells)
                    {
                        var rect = new RECT
                        {
                            left = Math.Min(left, client.right),
                            top = Math.Min(top, client.bottom),
                            right = Math.Min(right, client.right),
                            bottom = Math.Min(bottom, client.bottom),
                        };
                        if (rect.right > rect.left && rect.bottom > rect.top)
                        {
                            var brush = CreateSolidBrush((uint)color);
                            FillRect(hdc, ref rect, brush);
                            DeleteObject(brush);
                        }
                    }
                    ReleaseDC(hwnd, hdc);
                }
                ValidateRect(hwnd, IntPtr.Zero);
                return IntPtr.Zero;
            }

            return DefWindowProcW(hwnd, msg, wParam, lParam);
        }
    }

    // ---- Win32 surface (harness-local; the library keeps its own narrow copy) ----

    private const int WS_OVERLAPPEDWINDOW = 0x00CF0000;
    private const int SW_SHOW = 5;
    private const int SW_HIDE = 0;
    private const uint PM_REMOVE = 0x0001;
    private const uint WM_PAINT = 0x000F;

    private delegate IntPtr WndProcDelegate(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WNDCLASSEXW
    {
        public uint cbSize;
        public uint style;
        public WndProcDelegate lpfnWndProc;
        public int cbClsExtra;
        public int cbWndExtra;
        public IntPtr hInstance;
        public IntPtr hIcon;
        public IntPtr hCursor;
        public IntPtr hbrBackground;
        public string? lpszMenuName;
        public string lpszClassName;
        public IntPtr hIconSm;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MSG
    {
        public IntPtr hwnd;
        public uint message;
        public IntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public int ptX;
        public int ptY;
        public uint lPrivate;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT
    {
        public int left;
        public int top;
        public int right;
        public int bottom;
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern ushort RegisterClassExW(ref WNDCLASSEXW lpwcx);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateWindowExW(uint dwExStyle, string lpClassName, string lpWindowName,
        int dwStyle, int x, int y, int nWidth, int nHeight, IntPtr hWndParent, IntPtr hMenu,
        IntPtr hInstance, IntPtr lpParam);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool DestroyWindow(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UpdateWindow(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr DefWindowProcW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr GetDC(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern int ReleaseDC(IntPtr hWnd, IntPtr hDC);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool GetClientRect(IntPtr hWnd, ref RECT lpRect);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool ValidateRect(IntPtr hWnd, IntPtr lpRect);

    [DllImport("gdi32.dll", SetLastError = true)]
    private static extern IntPtr CreateSolidBrush(uint colorRef);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern int FillRect(IntPtr hDC, ref RECT lprc, IntPtr hbr);

    [DllImport("gdi32.dll", SetLastError = true)]
    private static extern bool DeleteObject(IntPtr hObject);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern bool PeekMessageW(ref MSG lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax,
        uint wRemoveMsg);

    [DllImport("user32.dll")]
    private static extern bool TranslateMessage(ref MSG lpMsg);

    [DllImport("user32.dll")]
    private static extern IntPtr DispatchMessageW(ref MSG lpMsg);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr GetModuleHandleW(string? lpModuleName);
}
