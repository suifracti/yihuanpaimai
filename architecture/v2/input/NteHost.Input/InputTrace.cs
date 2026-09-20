using System.Collections.Concurrent;
using System.Globalization;
using System.Text;

namespace NteHost.Input;

public readonly record struct TraceRecord(long Sequence, long MonotonicNs, string Phase, string Detail);

/// <summary>
/// Raw timeline sink. Every guard decision writes exactly one record here, which
/// is what makes the TOCTOU window auditable after the fact instead of being
/// reconstructed from assertions.
///
/// The sink is also the deterministic injection seam used by the targeted tests:
/// a test sink can react to <see cref="TracePhase.Precheck1Pass"/> by emitting a
/// user input event, which lands exactly between the two prechecks. That keeps
/// the production code free of any test-only hook.
/// </summary>
public interface IInputTraceSink
{
    void Write(string phase, string detail);
}

public sealed class NullInputTraceSink : IInputTraceSink
{
    public static readonly NullInputTraceSink Instance = new();

    public void Write(string phase, string detail)
    {
    }
}

/// <summary>Thread-safe in-memory sink; used for evidence extraction and tests.</summary>
public sealed class InMemoryInputTraceSink : IInputTraceSink
{
    private readonly ConcurrentQueue<TraceRecord> _records = new();
    private long _sequence;

    public void Write(string phase, string detail)
    {
        long seq = Interlocked.Increment(ref _sequence);
        _records.Enqueue(new TraceRecord(seq, TraceClock.NowNs(), phase, detail ?? string.Empty));
    }

    public IReadOnlyList<TraceRecord> Records => _records.ToArray();

    public int Count => _records.Count;

    public bool Contains(string phase) => _records.Any(r => r.Phase == phase);

    public TraceRecord? First(string phase)
    {
        foreach (var record in _records)
        {
            if (record.Phase == phase)
            {
                return record;
            }
        }

        return null;
    }
}

/// <summary>
/// Appends newline-delimited JSON to a file. This is the "raw timeline" artifact
/// kept in Evidence; it is written with an explicit flush on every record so a
/// crash mid-run still leaves the partial timeline on disk.
/// </summary>
public sealed class NdjsonInputTraceSink : IInputTraceSink, IDisposable
{
    private readonly object _gate = new();
    private readonly StreamWriter _writer;
    private long _sequence;

    public NdjsonInputTraceSink(string path)
    {
        var directory = Path.GetDirectoryName(Path.GetFullPath(path));
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        _writer = new StreamWriter(path, append: false, new UTF8Encoding(false))
        {
            AutoFlush = true,
        };
        FilePath = System.IO.Path.GetFullPath(path);
    }

    public string FilePath { get; }

    public void Write(string phase, string detail)
    {
        long seq = Interlocked.Increment(ref _sequence);
        long ns = TraceClock.NowNs();
        lock (_gate)
        {
            _writer.WriteLine(Format(new TraceRecord(seq, ns, phase ?? string.Empty, detail ?? string.Empty)));
        }
    }

    public static string Format(TraceRecord record)
    {
        var sb = new StringBuilder(160);
        sb.Append('{');
        sb.Append("\"seq\":").Append(record.Sequence.ToString(CultureInfo.InvariantCulture)).Append(',');
        sb.Append("\"ns\":").Append(record.MonotonicNs.ToString(CultureInfo.InvariantCulture)).Append(',');
        sb.Append("\"phase\":\"").Append(Escape(record.Phase)).Append("\",");
        sb.Append("\"detail\":\"").Append(Escape(record.Detail)).Append('"');
        sb.Append('}');
        return sb.ToString();
    }

    private static string Escape(string value)
    {
        var sb = new StringBuilder(value.Length + 8);
        foreach (char c in value)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < 0x20)
                    {
                        sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        sb.Append(c);
                    }

                    break;
            }
        }

        return sb.ToString();
    }

    public void Dispose()
    {
        lock (_gate)
        {
            _writer.Flush();
            _writer.Dispose();
        }
    }
}

/// <summary>Fan-out sink: keeps an in-memory copy while also writing raw NDJSON.</summary>
public sealed class TeeInputTraceSink : IInputTraceSink
{
    private readonly IInputTraceSink[] _sinks;

    public TeeInputTraceSink(params IInputTraceSink[] sinks) => _sinks = sinks;

    public void Write(string phase, string detail)
    {
        foreach (var sink in _sinks)
        {
            sink.Write(phase, detail);
        }
    }
}
