namespace NteHost.DomainActions;

// Hardware activity yields the current edit; it does not cancel the run.
public sealed class UserInputCourtesy
{
    public const long IdleNs = 1_500_000_000;
    long lastInputNs;
    long sequence;
    public long Sequence => Interlocked.Read(ref sequence);
    public void HardwareInput(long nowNs)
    {
        Interlocked.Exchange(ref lastInputNs, nowNs);
        Interlocked.Increment(ref sequence);
    }
    public bool IsIdle(long nowNs) => nowNs - Interlocked.Read(ref lastInputNs) >= IdleNs;
    public bool Uninterrupted(long startedSequence) => Sequence == startedSequence;
    // Only retry returning focus, never the game action. A different foreground
    // window means the user has chosen where to work: leave it alone.
    public static bool ReturnFocus(Func<bool> stillBorrowed, Func<bool> restore, Action pause)
    {
        for (int attempt = 0; attempt < 3; attempt++)
        {
            if (!stillBorrowed()) return false;
            if (restore()) return true;
            if (attempt < 2) pause();
        }
        return false;
    }
    public static bool CanRetry(PortOutcome result, bool interrupted) => interrupted
        && !result.Completed && !(result.BidConfirmationAttempted ?? result.SideEffectAttempted);
}
