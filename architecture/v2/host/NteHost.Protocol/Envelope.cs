using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace NteHost.Protocol;

/// <summary>
/// The frozen 8-field protocol-1.0.0 envelope. Field order is part of the wire
/// contract: protocolVersion, sessionId, messageType, requestId, correlationId,
/// sequence, monotonicTimestampNs, payload.
/// </summary>
public sealed class Envelope
{
    public string ProtocolVersion { get; set; } = ProtocolConstants.ProtocolVersion;
    public string SessionId { get; set; } = string.Empty;
    public string MessageType { get; set; } = string.Empty;
    public string RequestId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public long Sequence { get; set; }
    public long MonotonicTimestampNs { get; set; }
    public JsonNode Payload { get; set; } = new JsonObject();

    private static readonly string[] RequiredFields =
    {
        "protocolVersion", "sessionId", "messageType", "requestId",
        "correlationId", "sequence", "monotonicTimestampNs", "payload",
    };

    public void WriteCompact(Utf8JsonWriter writer)
    {
        writer.WriteStartObject();
        writer.WriteString("protocolVersion", ProtocolVersion);
        writer.WriteString("sessionId", SessionId);
        writer.WriteString("messageType", MessageType);
        writer.WriteString("requestId", RequestId);
        if (CorrelationId is null)
        {
            writer.WriteNull("correlationId");
        }
        else
        {
            writer.WriteString("correlationId", CorrelationId);
        }
        writer.WriteNumber("sequence", Sequence);
        writer.WriteNumber("monotonicTimestampNs", MonotonicTimestampNs);
        writer.WritePropertyName("payload");
        Payload.WriteTo(writer);
        writer.WriteEndObject();
    }

    public string ToCompactJson()
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = false, SkipValidation = false }))
        {
            WriteCompact(writer);
        }
        return Encoding.UTF8.GetString(stream.ToArray());
    }

    /// <summary>
    /// Strict envelope validation. No coercion: a wrong JSON type is a failure,
    /// never a silent conversion (compatibility_policy_v1.md section 3.1).
    /// </summary>
    public static Envelope Parse(JsonNode? node)
    {
        if (node is not JsonObject obj)
        {
            throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope, "envelope root must be a JSON object");
        }

        foreach (var field in RequiredFields)
        {
            if (!obj.ContainsKey(field))
            {
                throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope,
                    $"envelope is missing required field '{field}'");
            }
        }

        string RequireString(string field)
        {
            var value = obj[field];
            if (value is not JsonValue jv || !jv.TryGetValue<string>(out var s) || s is null)
            {
                throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope,
                    $"envelope field '{field}' must be a string (no coercion)");
            }
            return s;
        }

        string? RequireNullableString(string field)
        {
            var value = obj[field];
            if (value is null)
            {
                return null;
            }
            if (value is not JsonValue jv || !jv.TryGetValue<string>(out var s))
            {
                throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope,
                    $"envelope field '{field}' must be a string or null (no coercion)");
            }
            return s;
        }

        long RequireInt64(string field)
        {
            var value = obj[field];
            if (value is not JsonValue jv || !TryGetInt64(jv, out var v))
            {
                throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope,
                    $"envelope field '{field}' must be an integer (no coercion)");
            }
            return v;
        }

        var protocolVersion = RequireString("protocolVersion");
        if (!string.Equals(protocolVersion, ProtocolConstants.ProtocolVersion, StringComparison.Ordinal))
        {
            throw new ProtocolViolationException(ErrorCodes.ProtocolVersionMismatch,
                $"protocolVersion '{protocolVersion}' is not exactly '{ProtocolConstants.ProtocolVersion}'");
        }

        var sessionId = RequireString("sessionId");
        if (sessionId.Length == 0)
        {
            throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope, "envelope 'sessionId' must be non-empty");
        }

        var messageType = RequireString("messageType");
        if (!MessageTypes.IsKnown(messageType))
        {
            throw new ProtocolViolationException(ErrorCodes.UnknownMessageType,
                $"messageType '{messageType}' is not declared in message_catalog_v1.json");
        }

        var requestId = RequireString("requestId");
        if (requestId.Length == 0)
        {
            throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope, "envelope 'requestId' must be non-empty");
        }

        var sequence = RequireInt64("sequence");
        if (sequence < 0)
        {
            throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope, $"negative sequence {sequence} is not allowed");
        }

        var timestamp = RequireInt64("monotonicTimestampNs");
        if (timestamp < 0)
        {
            throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope,
                $"negative monotonicTimestampNs {timestamp} is not allowed");
        }

        if (obj["payload"] is not JsonObject payload)
        {
            throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope, "envelope 'payload' must be a non-null JSON object");
        }

        return new Envelope
        {
            ProtocolVersion = protocolVersion,
            SessionId = sessionId,
            MessageType = messageType,
            RequestId = requestId,
            CorrelationId = RequireNullableString("correlationId"),
            Sequence = sequence,
            MonotonicTimestampNs = timestamp,
            Payload = payload,
        };
    }

    /// <summary>
    /// Reads an integral JSON value. A JsonNode parsed from UTF-8 text is
    /// JsonElement-backed and answers TryGetValue&lt;long&gt;; a JsonValue built in
    /// code may be primitive-backed and only answer its own CLR type. Both are
    /// integral, so neither path is a coercion - a non-integral number such as 1.5
    /// still fails both and is rejected.
    /// </summary>
    internal static bool TryGetInt64(JsonValue value, out long result)
    {
        if (value.TryGetValue<long>(out result))
        {
            return true;
        }
        if (value.TryGetValue<int>(out var asInt))
        {
            result = asInt;
            return true;
        }
        result = 0;
        return false;
    }

    public static Envelope Parse(ReadOnlySpan<byte> utf8Json)
    {
        JsonNode? node;
        try
        {
            node = JsonNode.Parse(utf8Json);
        }
        catch (JsonException ex)
        {
            throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope, $"envelope is not valid JSON: {ex.Message}");
        }
        return Parse(node);
    }

    public static Envelope Create(string sessionId, string messageType, string requestId, long sequence,
        long monotonicTimestampNs, JsonNode payload, string? correlationId = null) => new()
        {
            ProtocolVersion = ProtocolConstants.ProtocolVersion,
            SessionId = sessionId,
            MessageType = messageType,
            RequestId = requestId,
            CorrelationId = correlationId,
            Sequence = sequence,
            MonotonicTimestampNs = monotonicTimestampNs,
            Payload = payload,
        };
}
