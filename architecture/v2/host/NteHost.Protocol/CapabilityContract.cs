using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;

namespace NteHost.Protocol;

public sealed record CapabilityDescriptor(
    string Name,
    string Category,
    string Status,
    bool IsMandatory,
    string FallbackAction);

/// <summary>
/// Runtime view over architecture/v2/contracts/capability_negotiation_v1.json.
/// Capability negotiation covers advertisement and fallback policy ONLY - ring
/// geometry is never negotiated (scopeBoundary in the contract).
/// </summary>
public sealed class CapabilityContract
{
    public const string Available = "AVAILABLE";
    public const string Unavailable = "UNAVAILABLE";
    public const string Experimental = "EXPERIMENTAL";
    public const string NotMeasured = "NOT_MEASURED";

    public IReadOnlyList<CapabilityDescriptor> Capabilities { get; }
    public string SourcePath { get; }

    private CapabilityContract(string sourcePath, IReadOnlyList<CapabilityDescriptor> capabilities)
    {
        SourcePath = sourcePath;
        Capabilities = capabilities;
    }

    public static CapabilityContract LoadFromFile(string path)
    {
        if (!File.Exists(path))
        {
            throw new FileNotFoundException($"capability negotiation contract not found: {path}");
        }
        var root = JsonNode.Parse(File.ReadAllText(path)) as JsonObject
                   ?? throw new InvalidDataException($"capability contract is not a JSON object: {path}");
        var list = new List<CapabilityDescriptor>();
        foreach (var entry in (JsonArray)root["capabilities"]!)
        {
            var obj = (JsonObject)entry!;
            list.Add(new CapabilityDescriptor(
                (string)obj["name"]!,
                (string?)obj["category"] ?? string.Empty,
                (string)obj["status"]!,
                (bool)obj["isMandatory"]!,
                (string?)obj["fallbackAction"] ?? string.Empty));
        }
        return new CapabilityContract(path, list);
    }

    public static CapabilityContract Load(string? explicitContractsDir, string startDirectory) =>
        LoadFromFile(Path.Combine(
            MessageCatalog.ResolveContractsDirectory(explicitContractsDir, startDirectory),
            "capability_negotiation_v1.json"));

    public IReadOnlyList<string> MandatoryNames =>
        Capabilities.Where(c => c.IsMandatory).Select(c => c.Name).ToList();

    /// <summary>The full capability dictionary advertised in HELLO (hostAdvertisement).</summary>
    public JsonObject BuildAdvertisement()
    {
        var obj = new JsonObject();
        foreach (var capability in Capabilities)
        {
            obj[capability.Name] = capability.Status;
        }
        return obj;
    }

    /// <summary>
    /// Engine-side rule: every mandatory capability must be AVAILABLE, otherwise
    /// HELLO_ACK must be REJECTED_CAPABILITY (fail closed, ERR_CAPABILITY_UNSUPPORTED).
    /// </summary>
    public void ValidateMandatory(JsonObject advertised)
    {
        var missing = new List<string>();
        foreach (var name in MandatoryNames)
        {
            var status = advertised[name] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;
            if (!string.Equals(status, Available, StringComparison.Ordinal))
            {
                missing.Add($"{name}={status ?? "<absent>"}");
            }
        }
        if (missing.Count > 0)
        {
            throw new ProtocolViolationException(ErrorCodes.CapabilityUnsupported,
                $"mandatory capabilities not AVAILABLE: [{string.Join(", ", missing)}]");
        }
    }

    /// <summary>
    /// NOT_MEASURED and EXPERIMENTAL capabilities must never be activated; only
    /// AVAILABLE capabilities may be used by the engine.
    /// </summary>
    public static IReadOnlyList<string> ActivatedCapabilities(JsonObject advertised) =>
        advertised.Where(kv => kv.Value is JsonValue v && v.TryGetValue<string>(out var s) && s == Available)
            .Select(kv => kv.Key)
            .OrderBy(k => k, StringComparer.Ordinal)
            .ToList();

    public static IReadOnlyList<string> NonActivatableCapabilities(JsonObject advertised) =>
        advertised.Where(kv => kv.Value is JsonValue v && v.TryGetValue<string>(out var s)
                               && (s == NotMeasured || s == Experimental))
            .Select(kv => kv.Key)
            .OrderBy(k => k, StringComparer.Ordinal)
            .ToList();
}
