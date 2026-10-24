using System.Text.Json.Nodes;

namespace WgcLiveHarness;

internal static class EngineStateFile
{
    public static JsonObject? Read(string path, bool diagnosticOnly = false)
    {
        try
        {
            if (!File.Exists(path)) return null;
            // The writer atomically replaces the snapshot. Readers must allow
            // that replacement; an open handle still reads its complete version.
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete);
            return JsonNode.Parse(stream) as JsonObject;
        }
        catch (Exception ex) when (diagnosticOnly && ex is IOException or System.Text.Json.JsonException)
        {
            Console.Error.WriteLine("[source diagnostic state unavailable] " + ex.GetType().Name);
            return null; // no business facts; SOURCE pixels have their own admission
        }
    }
}
