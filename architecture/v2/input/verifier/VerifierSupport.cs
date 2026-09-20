using System.Globalization;
using System.Text.Json.Nodes;
using NteHost.Input;

namespace NteHost.Input.Verifier;

internal static class J
{
    public static JsonObject Obj(params (string Key, JsonNode? Value)[] pairs)
    {
        var node = new JsonObject();
        foreach (var (key, value) in pairs)
        {
            node[key] = value;
        }

        return node;
    }

    public static JsonNode? N(string? value) => value is null ? null : JsonValue.Create(value);

    public static JsonNode? N(bool value) => JsonValue.Create(value);

    public static JsonNode? N(long value) => JsonValue.Create(value);

    public static JsonNode? N(int value) => JsonValue.Create(value);

    public static JsonNode? N(double value) => JsonValue.Create(Math.Round(value, 4));

    public static JsonNode? N(ulong value) => JsonValue.Create(value);

    public static string Hex(ulong value) => "0x" + value.ToString("x16", CultureInfo.InvariantCulture);
}

internal sealed class CaseResult
{
    private readonly List<string> _assertions = new();
    private readonly List<string> _failures = new();

    public CaseResult(string id, string kind, string description)
    {
        Id = id;
        Kind = kind;
        Description = description;
    }

    public string Id { get; }

    public string Kind { get; }

    public string Description { get; }

    public string ExpectedReason { get; set; } = string.Empty;

    public string ActualReason { get; set; } = string.Empty;

    public string Stage { get; set; } = string.Empty;

    public long SendCallCount { get; set; }

    public long InputsDelivered { get; set; }

    public string StateAfter { get; set; } = string.Empty;

    public string Note { get; set; } = string.Empty;

    public long CursorSetCalls { get; set; }

    public string CursorRestoreReason { get; set; } = string.Empty;

    public long FocusCaptureCount { get; set; }

    public long ObservedInputCount { get; set; }

    public List<string> TracePhases { get; } = new();

    public bool Passed => _failures.Count == 0;

    public void Check(bool condition, string description)
    {
        _assertions.Add($"{(condition ? "PASS" : "FAIL")}: {description}");
        if (!condition)
        {
            _failures.Add(description);
        }
    }

    public JsonObject ToJson()
    {
        var assertions = new JsonArray();
        foreach (string assertion in _assertions)
        {
            assertions.Add(assertion);
        }

        var failures = new JsonArray();
        foreach (string failure in _failures)
        {
            failures.Add(failure);
        }

        return J.Obj(
            ("id", J.N(Id)),
            ("kind", J.N(Kind)),
            ("description", J.N(Description)),
            ("expectedReason", J.N(ExpectedReason)),
            ("actualReason", J.N(ActualReason)),
            ("stage", J.N(Stage)),
            ("sendInputCalls", J.N(SendCallCount)),
            ("inputsDelivered", J.N(InputsDelivered)),
            ("stateAfter", J.N(StateAfter)),
            ("note", J.N(Note)),
            ("cursorSetCalls", J.N(CursorSetCalls)),
            ("cursorRestoreReason", J.N(CursorRestoreReason)),
            ("focusCaptureCount", J.N(FocusCaptureCount)),
            ("observedInputCount", J.N(ObservedInputCount)),
            ("tracePhases", new JsonArray(TracePhases.Select(J.N).ToArray())),
            ("status", J.N(Passed ? "PASS" : "FAIL")),
            ("assertions", assertions),
            ("failures", failures));
    }
}

/// <summary>Deterministic assembly of a guard wired entirely to injected fakes.</summary>
internal sealed class Fixture
{
    public const long TargetId = 0x4B2B;
    public const long OtherId = 0x9999;

    private Fixture()
    {
    }

    public FakeInputObserver Observer { get; } = new();

    public FakeFocusSnapshotProvider Focus { get; } = new();

    public IFocusSnapshotProvider FocusProvider { get; private set; } = null!;

    public FakeCursorBackend Cursor { get; private set; } = null!;

    public CountingRawInputBackend Raw { get; } = new();

    public InMemoryInputTraceSink Trace { get; } = new();

    public InputSafetyGuard Guard { get; private set; } = null!;

    public static Fixture Create(
        int cursorX = 10,
        int cursorY = 10,
        InputSafetyOptions? options = null,
        IInputTraceSink? trace = null,
        bool startObserver = true,
        IFocusSnapshotProvider? focusProvider = null)
    {
        var fixture = new Fixture();
        fixture.Cursor = new FakeCursorBackend(cursorX, cursorY);
        IFocusSnapshotProvider focus = focusProvider ?? fixture.Focus;
        fixture.FocusProvider = focus;
        if (focusProvider is null)
        {
            fixture.Focus.SetTarget(TargetId);
            fixture.Focus.SetForeground(TargetId);
        }

        fixture.Guard = new InputSafetyGuard(
            fixture.Observer,
            focus,
            fixture.Cursor,
            fixture.Raw,
            trace ?? fixture.Trace,
            options);

        if (startObserver)
        {
            fixture.Observer.Start(evt => fixture.Guard.OnObservedInput(evt));
        }

        return fixture;
    }

    public ArmOutcome Arm(long targetId = TargetId) => Guard.Arm(new ArmRequest(targetId));

    public ObservedInputEvent Marked(
        InputEventKind kind,
        ulong? marker = null,
        int x = 0,
        int y = 0,
        InputEventOrigin origin = InputEventOrigin.Injected) =>
        Observer.Next(kind, origin, marker ?? Guard.Ledger.Marker, x, y);

    public ObservedInputEvent User(InputEventKind kind, int x = 0, int y = 0) =>
        Observer.Next(kind, InputEventOrigin.Hardware, 0, x, y);
}
