using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using NteHost.Protocol;

namespace NteHost;

/// <summary>
/// Structured JSONL trace. Every line carries the correlation keys required by
/// V2-1 item 14 so a single request can be followed across the Host and the child
/// engine log.
/// </summary>
public sealed class TraceLog : IDisposable
{
    private readonly StreamWriter? _writer;
    private readonly long? _maxBytes;
    private readonly object _gate = new();
    public string Path { get; }
    public string SessionId { get; }
    public string SessionNonceShort { get; private set; }

    /// <summary>Updated on every new child generation so each trace line carries the
    /// nonce of the generation it belongs to (short form only; never the full value).</summary>
    public void SetGenerationNonce(string sessionNonce)
    {
        SessionNonceShort = sessionNonce.Length <= 8 ? sessionNonce : sessionNonce[..8];
    }

    public TraceLog(string? path, string sessionId, string sessionNonce, long? maxBytes = null)
    {
        if (maxBytes is <= 0) throw new ArgumentOutOfRangeException(nameof(maxBytes));
        _maxBytes = maxBytes;
        Path = path ?? string.Empty;
        SessionId = sessionId;
        SessionNonceShort = sessionNonce.Length <= 8 ? sessionNonce : sessionNonce[..8];
        if (!string.IsNullOrEmpty(path))
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(path))!);
            _writer = new StreamWriter(new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.Read))
            {
                AutoFlush = true,
            };
        }
    }

    public void Event(string eventName, int generationId, object? details = null,
        string? requestId = null, string? correlationId = null)
    {
        var record = new Dictionary<string, object?>
        {
            ["tsNs"] = ProtocolClock.NowNs(),
            ["event"] = eventName,
            ["sessionId"] = SessionId,
            ["sessionNonceShort"] = SessionNonceShort,
            ["generationId"] = generationId,
            ["requestId"] = requestId,
            ["correlationId"] = correlationId,
            ["details"] = details,
        };

        var line = JsonSerializer.Serialize(record, new JsonSerializerOptions { WriteIndented = false });
        lock (_gate)
        {
            if (_writer is not null && _maxBytes is long limit)
            {
                var bytes = Encoding.UTF8.GetByteCount(line + Environment.NewLine);
                if (bytes > limit) return;
                _writer.Flush();
                if (_writer.BaseStream.Position + bytes > limit)
                {
                    _writer.BaseStream.SetLength(0);
                    _writer.BaseStream.Position = 0;
                }
            }
            _writer?.WriteLine(line);
            Console.Error.WriteLine("[host] " + line);
        }
    }

    public void Dispose()
    {
        lock (_gate)
        {
            _writer?.Flush();
            _writer?.Dispose();
        }
    }
}

/// <summary>Small helpers for compact JSON writing shared by the scenarios.</summary>
internal static class Json
{
    public static string Serialize<T>(T value) =>
        JsonSerializer.Serialize(value, new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping });

    public static void WriteFile<T>(string path, T value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        File.WriteAllText(path, Serialize(value) + Environment.NewLine, new UTF8Encoding(false));
    }

    public static string Hex(byte[] bytes)
    {
        var sb = new StringBuilder(bytes.Length * 2);
        foreach (var b in bytes)
        {
            sb.Append(b.ToString("x2", CultureInfo.InvariantCulture));
        }
        return sb.ToString();
    }
}
