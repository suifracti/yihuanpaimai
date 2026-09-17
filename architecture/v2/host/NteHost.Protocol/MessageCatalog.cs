using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;

namespace NteHost.Protocol;

/// <summary>
/// Runtime view over architecture/v2/contracts/message_catalog_v1.json.
///
/// V2-1 deliberately does NOT hardcode payload field tables: the catalog is the
/// single schema truth, so the host reads it and validates against it. Only the
/// small set of scalar constants that appear on the wire (geometry, timeouts,
/// version) are mirrored in ProtocolConstants, and those mirrors are checked
/// against the catalog by HostSupervisorVerifier.
/// </summary>
public sealed class MessageCatalog
{
    private readonly JsonObject _root;
    private readonly Dictionary<string, JsonObject> _payloadSchemas = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<string>> _requiredPayloadFields = new(StringComparer.Ordinal);

    public string SourcePath { get; }
    public string SchemaVersion { get; }
    public string ProtocolVersion { get; }
    public IReadOnlyList<string> MessageTypeList { get; }
    public IReadOnlyList<string> FailClosedErrorCodes { get; }
    public JsonObject EnvelopeSchema { get; }
    public JsonObject RingBufferGeometry { get; }
    public JsonObject FrameHeaderMetadataContract { get; }
    public JsonObject ReadinessContract { get; }

    private MessageCatalog(string sourcePath, JsonObject root)
    {
        SourcePath = sourcePath;
        _root = root;
        SchemaVersion = (string?)root["schemaVersion"] ?? string.Empty;
        ProtocolVersion = (string?)root["protocolVersion"] ?? string.Empty;

        var messages = (JsonArray)root["messages"]!;
        var types = new List<string>();
        foreach (var entry in messages)
        {
            var messageType = (string?)entry!["messageType"]! ?? throw new InvalidDataException("catalog entry without messageType");
            types.Add(messageType);
            _payloadSchemas[messageType] = (JsonObject)entry["payloadSchema"]!;
            var required = new List<string>();
            foreach (var field in (JsonArray)entry["requiredPayloadFields"]!)
            {
                required.Add((string)field!);
            }
            _requiredPayloadFields[messageType] = required;
        }
        MessageTypeList = types;

        var codes = new List<string>();
        foreach (var code in (JsonArray)root["failClosedErrorCodes"]!)
        {
            codes.Add((string)code!);
        }
        FailClosedErrorCodes = codes;

        EnvelopeSchema = (JsonObject)root["envelopeSchema"]!;
        RingBufferGeometry = (JsonObject)root["ringBufferGeometry"]!;
        FrameHeaderMetadataContract = (JsonObject)root["frameHeaderMetadataContract"]!;
        ReadinessContract = (JsonObject)root["readinessContract"]!;
    }

    public static MessageCatalog LoadFromFile(string path)
    {
        if (!File.Exists(path))
        {
            throw new FileNotFoundException($"message catalog not found: {path}");
        }
        var root = JsonNode.Parse(File.ReadAllText(path)) as JsonObject
                   ?? throw new InvalidDataException($"catalog is not a JSON object: {path}");
        return new MessageCatalog(path, root);
    }

    /// <summary>
    /// Locates architecture/v2/contracts from a starting directory, walking upward.
    /// </summary>
    public static string ResolveContractsDirectory(string? explicitDir, string startDirectory)
    {
        if (!string.IsNullOrEmpty(explicitDir))
        {
            if (!Directory.Exists(explicitDir))
            {
                throw new DirectoryNotFoundException($"--contracts directory does not exist: {explicitDir}");
            }
            return explicitDir;
        }

        var dir = new DirectoryInfo(startDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "architecture", "v2", "contracts");
            if (File.Exists(Path.Combine(candidate, "message_catalog_v1.json")))
            {
                return candidate;
            }
            dir = dir.Parent;
        }
        throw new DirectoryNotFoundException(
            $"could not locate architecture/v2/contracts starting from '{startDirectory}'");
    }

    public static MessageCatalog Load(string? explicitContractsDir, string startDirectory) =>
        LoadFromFile(Path.Combine(ResolveContractsDirectory(explicitContractsDir, startDirectory), "message_catalog_v1.json"));

    public JsonObject PayloadSchema(string messageType) =>
        _payloadSchemas.TryGetValue(messageType, out var schema)
            ? schema
            : throw new ProtocolViolationException(ErrorCodes.UnknownMessageType,
                $"no payload schema declared for messageType '{messageType}'");

    public IReadOnlyList<string> RequiredPayloadFields(string messageType) =>
        _requiredPayloadFields.TryGetValue(messageType, out var fields) ? fields : Array.Empty<string>();

    public JsonObject RawRoot => _root;

    // ------------------------------------------------------------------
    // Generic, no-coercion payload validation (mirror of models.py).
    // ------------------------------------------------------------------

    public void ValidatePayload(string messageType, JsonNode? payload)
    {
        if (payload is not JsonObject obj)
        {
            throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                $"payload for {messageType} must be a JSON object");
        }

        foreach (var field in RequiredPayloadFields(messageType))
        {
            if (!obj.ContainsKey(field))
            {
                throw new ProtocolViolationException(ErrorCodes.MissingRequiredField,
                    $"Payload for {messageType} missing required field: '{field}'");
            }
        }

        var schema = PayloadSchema(messageType);
        if (schema["properties"] is not JsonObject properties)
        {
            return;
        }

        foreach (var (name, specNode) in properties)
        {
            if (!obj.ContainsKey(name))
            {
                continue;
            }
            ValidateValue($"{messageType}.{name}", obj[name], (JsonObject)specNode!);
        }

        if (schema["additionalProperties"] is JsonValue apv && apv.TryGetValue<bool>(out var allowExtra) && !allowExtra)
        {
            var unknown = obj.Select(kv => kv.Key).Where(k => !properties.ContainsKey(k)).OrderBy(k => k, StringComparer.Ordinal).ToList();
            if (unknown.Count > 0)
            {
                throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                    $"Payload for {messageType} contains undeclared fields: [{string.Join(", ", unknown)}]");
            }
        }
    }

    private static void ValidateValue(string fieldPath, JsonNode? value, JsonObject spec)
    {
        var nullable = spec["nullable"] is JsonValue nv && nv.TryGetValue<bool>(out var nb) && nb;

        if (value is null)
        {
            if (nullable)
            {
                return;
            }
            throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                $"Payload field '{fieldPath}' must not be null");
        }

        var fieldType = (string?)spec["type"] ?? "object";
        if (!TypeAccepts(fieldType, value))
        {
            throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                $"Payload field '{fieldPath}' must be {fieldType}, got {JsonTypeName(value)} (no coercion allowed)");
        }

        if (spec["enum"] is JsonArray enumValues)
        {
            var allowed = enumValues.Select(e => e?.ToJsonString() ?? "null").ToList();
            var actual = value.ToJsonString();
            if (!allowed.Contains(actual))
            {
                throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                    $"Payload field '{fieldPath}' value {actual} is not one of [{string.Join(", ", allowed)}]");
            }
        }

        if (fieldType == "array" && spec["items"] is JsonObject itemSpec && value is JsonArray array)
        {
            for (var i = 0; i < array.Count; i++)
            {
                ValidateValue($"{fieldPath}[{i}]", array[i], itemSpec);
            }
        }
        else if (fieldType == "object" && value is JsonObject nestedValue)
        {
            if (spec["properties"] is JsonObject nested)
            {
                foreach (var (nestedName, nestedSpecNode) in nested)
                {
                    var nestedSpec = (JsonObject)nestedSpecNode!;
                    if (!nestedValue.ContainsKey(nestedName))
                    {
                        var required = nestedSpec["required"] is JsonValue rv && rv.TryGetValue<bool>(out var rb) && rb;
                        if (required)
                        {
                            throw new ProtocolViolationException(ErrorCodes.MissingRequiredField,
                                $"Payload object '{fieldPath}' missing required field: '{nestedName}'");
                        }
                        continue;
                    }
                    ValidateValue($"{fieldPath}.{nestedName}", nestedValue[nestedName], nestedSpec);
                }

                if (spec["additionalProperties"] is JsonValue ap && ap.TryGetValue<bool>(out var allow) && !allow)
                {
                    var unknown = nestedValue.Select(kv => kv.Key)
                        .Where(k => !nested.ContainsKey(k))
                        .OrderBy(k => k, StringComparer.Ordinal).ToList();
                    if (unknown.Count > 0)
                    {
                        throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                            $"Payload object '{fieldPath}' contains undeclared fields: [{string.Join(", ", unknown)}]");
                    }
                }
            }
        }
    }

    private static bool TypeAccepts(string fieldType, JsonNode value)
    {
        switch (fieldType)
        {
            case "integer":
                return value is JsonValue iv && iv.TryGetValue<long>(out _);
            case "number":
                return value is JsonValue dv && (dv.TryGetValue<double>(out _) || dv.TryGetValue<long>(out _));
            case "string":
                return value is JsonValue sv && sv.TryGetValue<string>(out _);
            case "boolean":
                return value is JsonValue bv && bv.TryGetValue<bool>(out _);
            case "object":
                return value is JsonObject;
            case "array":
                return value is JsonArray;
            default:
                return false;
        }
    }

    private static string JsonTypeName(JsonNode value) => value switch
    {
        JsonObject => "object",
        JsonArray => "array",
        JsonValue v when v.TryGetValue<bool>(out _) => "boolean",
        JsonValue v when v.TryGetValue<long>(out _) => "integer",
        JsonValue v when v.TryGetValue<double>(out _) => "number",
        JsonValue v when v.TryGetValue<string>(out _) => "string",
        _ => value.GetType().Name,
    };

    // ------------------------------------------------------------------
    // Frozen contract helpers that V2-1 exercises directly.
    // ------------------------------------------------------------------

    public int MapTotalSizeBytes =>
        (int?)RingBufferGeometry["mapTotalSizeBytes"]
        ?? throw new InvalidDataException("catalog ringBufferGeometry.mapTotalSizeBytes missing");

    /// <summary>models.py::validate_hello_fixed_geometry</summary>
    public static void ValidateHelloFixedGeometry(JsonObject helloPayload, int expectedMapTotalSizeBytes)
    {
        var declaredNode = helloPayload["frameBufferSize"];
        if (declaredNode is not JsonValue jv || !jv.TryGetValue<long>(out var declared))
        {
            throw new ProtocolViolationException(ErrorCodes.RingGeometryMismatch,
                $"HELLO 'frameBufferSize' must be an integer equal to the fixed v1 mapTotalSizeBytes {expectedMapTotalSizeBytes}");
        }
        if (declared != expectedMapTotalSizeBytes)
        {
            throw new ProtocolViolationException(ErrorCodes.RingGeometryMismatch,
                $"HELLO 'frameBufferSize'={declared} does not equal the fixed v1 mapTotalSizeBytes {expectedMapTotalSizeBytes}; v1 ring geometry is NOT negotiated");
        }
    }

    /// <summary>models.py::validate_hello_ack_readiness</summary>
    public static void ValidateHelloAckReadiness(JsonObject helloAckPayload, IReadOnlyList<string> readinessEnum)
    {
        var readinessNode = helloAckPayload["readiness"];
        if (readinessNode is not JsonValue rv || !rv.TryGetValue<string>(out var readiness) || !readinessEnum.Contains(readiness))
        {
            throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                $"HELLO_ACK 'readiness' must be one of [{string.Join(", ", readinessEnum)}]");
        }

        var statusNode = helloAckPayload["status"];
        var status = statusNode is JsonValue sv && sv.TryGetValue<string>(out var s) ? s : null;

        var businessNode = helloAckPayload["engineBusinessReady"];
        if (businessNode is not JsonValue bv || !bv.TryGetValue<bool>(out var businessReady))
        {
            throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                "HELLO_ACK 'engineBusinessReady' must be a boolean");
        }

        if (status == "ACCEPTED")
        {
            if (readiness == "READY" && !businessReady)
            {
                throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                    "HELLO_ACK readiness == READY requires engineBusinessReady == true (lifecycle READY gate)");
            }
            if ((readiness == "STARTING" || readiness == "LOADING") && businessReady)
            {
                throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                    $"HELLO_ACK readiness == {readiness} must not advertise engineBusinessReady == true");
            }
        }
        if (status != "ACCEPTED" && businessReady)
        {
            throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed,
                $"HELLO_ACK status == {status} must not advertise engineBusinessReady == true");
        }
    }

    /// <summary>
    /// models.py::validate_state_snapshot - session identity is evaluated BEFORE the
    /// projection schema so a stale snapshot can never be partially applied.
    /// </summary>
    public void ValidateStateSnapshot(Envelope snapshotEnvelope, string activeSessionId)
    {
        if (!string.Equals(snapshotEnvelope.MessageType, MessageTypes.StateSnapshot, StringComparison.Ordinal))
        {
            throw new ProtocolViolationException(ErrorCodes.UnknownMessageType, "expected STATE_SNAPSHOT message");
        }
        var payload = snapshotEnvelope.Payload as JsonObject
                      ?? throw new ProtocolViolationException(ErrorCodes.SchemaValidationFailed, "STATE_SNAPSHOT payload must be an object");

        var snapshotSessionId = payload["snapshotSessionId"] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;
        if (!string.Equals(snapshotSessionId, activeSessionId, StringComparison.Ordinal))
        {
            throw new ProtocolViolationException(ErrorCodes.StaleSession,
                $"STATE_SNAPSHOT snapshotSessionId '{snapshotSessionId}' does not match active session '{activeSessionId}'");
        }

        ValidatePayload(MessageTypes.StateSnapshot, payload);
    }
}
