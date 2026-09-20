using System.Security.Cryptography;

namespace NteHost.Input;

public readonly record struct ExemptionDecision(bool Exempted, string Reason);

/// <summary>
/// Bounded self-injection ledger: the mechanism that lets the guard recognise
/// input *it* produced without ever letting a marker become a blanket waiver.
///
/// TRUST BOUNDARY — read this before changing anything here.
/// The exemption is a CONJUNCTION of four independent conditions:
///
///   1. the OS low-level hook marked the event as injected
///      (LLKHF_INJECTED / LLMHF_INJECTED). This is set by the OS, so it proves
///      "not physical hardware". It does NOT prove "produced by us": every other
///      process using SendInput produces the same flag.
///   2. the event is NOT flagged as lower-integrity injected
///      (LLKHF/LLMHF_LOWER_IL_INJECTED).
///   3. <c>dwExtraInfo</c> exactly equals the per-arming marker. This value is
///      attacker-forgeable by any process that can call SendInput, so on its own
///      it is a correlation hint and NOT a security primitive. It is made
///      unguessable by rotating a fresh random marker on every arming generation,
///      which bounds replay to a single arming.
///   4. a matching *pending, unconsumed, unexpired* intent exists in this ledger
///      for that exact event kind (and exact coordinates for cursor moves), AND
///      the per-arming exemption budget has not been exhausted.
///
/// Condition 4 is what actually bounds the waiver. A forged marker, a replayed
/// marker, an over-budget marker, an expired intent, or a second identical event
/// after the one-shot intent was consumed all fall through to
/// <see cref="ExemptionDecision.Exempted"/> = false, which the guard turns into a
/// user takeover. In other words: spoofing the marker cannot buy silence, it can
/// only buy a cancel.
///
/// Key events are never exemptible: this module never injects keys, so a key
/// event always means a human, and it can never be hidden.
/// </summary>
public sealed class SelfInjectionLedger
{
    private sealed class Intent
    {
        public ulong Id;
        public InputActionKind Kind;
        public int X;
        public int Y;
        public int TolerancePx;
        public long RegisteredNs;
        public long ExpiresNs;
        public bool Consumed;
        public bool Abandoned;
    }

    private readonly object _gate = new();
    private readonly List<Intent> _intents = new();
    private readonly Func<ulong> _markerFactory;
    private readonly Func<long> _clock;
    private ulong _marker;
    private ulong _intentSequence;
    private long _ttlNs = 250_000_000;
    private int _maxExemptions = 16;
    private int _exemptionsUsed;
    private int _generation;

    public SelfInjectionLedger(Func<ulong>? markerFactory = null, Func<long>? clock = null)
    {
        _markerFactory = markerFactory ?? NewRandomMarker;
        _clock = clock ?? TraceClock.NowNs;
        _marker = CreateMarker();
    }

    public ulong Marker
    {
        get { lock (_gate) { return _marker; } }
    }

    public int Generation
    {
        get { lock (_gate) { return _generation; } }
    }

    public int ExemptionsUsed
    {
        get { lock (_gate) { return _exemptionsUsed; } }
    }

    public int MaxExemptions
    {
        get { lock (_gate) { return _maxExemptions; } }
    }

    public int PendingIntentCount
    {
        get
        {
            lock (_gate)
            {
                return _intents.Count(i => !i.Consumed && !i.Abandoned);
            }
        }
    }

    /// <summary>
    /// Starts a new arming generation: fresh unguessable marker, fresh budget,
    /// and no inherited intents. Called exactly once per <c>Arm</c>.
    /// </summary>
    public ulong BeginGeneration(int maxExemptions, int ttlMs)
    {
        lock (_gate)
        {
            _generation++;
            _marker = CreateMarker();
            _maxExemptions = Math.Max(0, maxExemptions);
            _ttlNs = Math.Max(1, (long)ttlMs) * 1_000_000L;
            _exemptionsUsed = 0;
            _intents.Clear();
            _intentSequence = 0;
            return _marker;
        }
    }

    public void Clear()
    {
        lock (_gate)
        {
            _intents.Clear();
            _exemptionsUsed = 0;
        }
    }

    /// <summary>
    /// Registers a one-shot intent for an action this process is about to perform.
    /// MUST be called before the OS call that will generate the event, otherwise
    /// the hook can legitimately observe an unregistered event and the guard will
    /// (correctly) treat it as user input.
    /// </summary>
    public ulong Register(InputActionKind kind, int x, int y, int tolerancePx)
    {
        if (!IsExemptibleKind(kind))
        {
            throw new InvalidOperationException($"Kind {kind} is never exemptible.");
        }

        lock (_gate)
        {
            long now = _clock();
            var intent = new Intent
            {
                Id = ++_intentSequence,
                Kind = kind,
                X = x,
                Y = y,
                TolerancePx = Math.Max(0, tolerancePx),
                RegisteredNs = now,
                ExpiresNs = now + _ttlNs,
            };
            _intents.Add(intent);
            return intent.Id;
        }
    }

    /// <summary>
    /// Marks an intent as abandoned. Used when the prepare step could not be
    /// applied as planned, so the intent must not be allowed to absorb a later
    /// unrelated event.
    /// </summary>
    public void Abandon(ulong intentId)
    {
        lock (_gate)
        {
            foreach (var intent in _intents)
            {
                if (intent.Id == intentId)
                {
                    intent.Abandoned = true;
                    return;
                }
            }
        }
    }

    public static bool IsExemptibleKind(InputActionKind kind) =>
        kind is InputActionKind.MouseWheel or InputActionKind.MouseHorizontalWheel or InputActionKind.CursorMove;

    /// <summary>
    /// Decides whether an observed event is this process's own input.
    /// A false result is never "ignore"; the caller turns it into a takeover.
    /// </summary>
    public ExemptionDecision Evaluate(in ObservedInputEvent observed)
    {
        lock (_gate)
        {
            if (observed.Origin == InputEventOrigin.LowerIntegrityInjected)
            {
                return new ExemptionDecision(false, InputSafetyReasons.DenyLowerIntegrityInjected);
            }

            if (observed.Origin != InputEventOrigin.Injected)
            {
                return new ExemptionDecision(false, InputSafetyReasons.DenyNotInjected);
            }

            if (!InputMarker.ExactMatch(_marker, observed.ExtraInfo))
            {
                return new ExemptionDecision(false, InputSafetyReasons.DenyMarkerMismatch);
            }

            if (observed.Kind is InputEventKind.KeyDown or InputEventKind.MouseButtonDown)
            {
                return new ExemptionDecision(false, InputSafetyReasons.DenyKindNeverExemptible);
            }

            InputActionKind wanted = observed.Kind switch
            {
                InputEventKind.MouseWheel => InputActionKind.MouseWheel,
                InputEventKind.MouseHorizontalWheel => InputActionKind.MouseHorizontalWheel,
                InputEventKind.MouseMove => InputActionKind.CursorMove,
                _ => InputActionKind.CursorMove,
            };

            long now = _clock();
            Intent? consumedMatch = null;
            Intent? expiredMatch = null;
            Intent? coordinateMismatch = null;
            Intent? abandonedMatch = null;
            Intent? liveMatch = null;

            foreach (var intent in _intents)
            {
                if (intent.Kind != wanted)
                {
                    continue;
                }

                bool coordinatesOk = intent.Kind != InputActionKind.CursorMove ||
                                     (Math.Abs(intent.X - observed.X) <= intent.TolerancePx &&
                                      Math.Abs(intent.Y - observed.Y) <= intent.TolerancePx);

                if (intent.Abandoned)
                {
                    abandonedMatch ??= intent;
                    continue;
                }

                if (intent.Consumed)
                {
                    consumedMatch ??= intent;
                    continue;
                }

                if (now > intent.ExpiresNs)
                {
                    expiredMatch ??= intent;
                    continue;
                }

                if (!coordinatesOk)
                {
                    coordinateMismatch ??= intent;
                    continue;
                }

                liveMatch = intent;
                break;
            }

            if (liveMatch is null)
            {
                if (coordinateMismatch is not null)
                {
                    return new ExemptionDecision(false, InputSafetyReasons.DenyCoordinateMismatch);
                }

                if (consumedMatch is not null)
                {
                    return new ExemptionDecision(false, InputSafetyReasons.DenyIntentAlreadyConsumed);
                }

                if (expiredMatch is not null)
                {
                    return new ExemptionDecision(false, InputSafetyReasons.DenyIntentExpired);
                }

                if (abandonedMatch is not null)
                {
                    return new ExemptionDecision(false, InputSafetyReasons.DenyIntentAbandoned);
                }

                return new ExemptionDecision(false, InputSafetyReasons.DenyNoPendingIntent);
            }

            if (_exemptionsUsed >= _maxExemptions)
            {
                return new ExemptionDecision(false, InputSafetyReasons.DenyBudgetExhausted);
            }

            liveMatch.Consumed = true;
            _exemptionsUsed++;
            return new ExemptionDecision(true, InputSafetyReasons.Ok);
        }
    }

    /// <summary>
    /// Marker layout: a complete non-zero 32-bit cryptographically random
    /// transport value. There is no fixed low-bit tag and no wider value that
    /// could be silently truncated at the native boundary.
    /// </summary>
    public static ulong NewRandomMarker()
    {
        return InputMarker.NewRandom();
    }

    private ulong CreateMarker()
    {
        ulong marker = _markerFactory();
        if (!InputMarker.IsValid(marker))
        {
            throw new InvalidOperationException("MarkerFactory must return a non-zero 32-bit transport marker.");
        }

        return marker;
    }
}
