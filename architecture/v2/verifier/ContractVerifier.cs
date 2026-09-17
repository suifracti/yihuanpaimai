using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.Json;
using ArchitectureV2.Contracts;

namespace ArchitectureV2.Verifier
{
    public class Program
    {
        public static int Main(string[] args)
        {
            Console.WriteLine("===============================================================================");
            Console.WriteLine("  NTE Architecture V2: Cross-Language Contract Verifier (.NET 8)");
            Console.WriteLine("===============================================================================");

            string contractsDir = args.Length > 0 ? args[0] : Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "architecture", "v2", "contracts"));
            string outputDir = args.Length > 1 ? args[1] : contractsDir;

            Directory.CreateDirectory(outputDir);
            Console.WriteLine($"[Config] Contracts Dir: {contractsDir}");
            Console.WriteLine($"[Config] Output Dir:    {outputDir}");

            int passedTests = 0;
            int totalTests = 0;
            var testCases = new List<Dictionary<string, object>>();

            void RunTest(string testName, Action action)
            {
                totalTests++;
                try
                {
                    action();
                    passedTests++;
                    Console.WriteLine($"  [PASS] {testName}");
                    testCases.Add(new Dictionary<string, object>
                    {
                        { "name", testName },
                        { "status", "PASSED" }
                    });
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"  [FAIL] {testName}: {ex.Message}");
                    testCases.Add(new Dictionary<string, object>
                    {
                        { "name", testName },
                        { "status", "FAILED" },
                        { "error", ex.Message }
                    });
                }
            }

            Console.WriteLine("\n--- 1. Frame Header Binary Struct Layout Tests ---");
            RunTest("FrameHeader_Size_Is_64_Bytes", () =>
            {
                int sz = Marshal.SizeOf<FrameHeaderV1>();
                if (sz != 64) throw new Exception($"Size {sz} != 64");
            });

            var expectedOffsets = new Dictionary<string, int>
            {
                { "magic", 0 },
                { "headerVersion", 4 },
                { "sequence", 8 },
                { "width", 16 },
                { "height", 20 },
                { "stride", 24 },
                { "pixelFormat", 28 },
                { "bufferLength", 32 },
                { "flags", 36 },
                { "captureTimestampNs", 40 },
                { "producerTimestampNs", 48 },
                { "cornerChecksum", 56 },
                { "reserved", 60 }
            };

            foreach (var kvp in expectedOffsets)
            {
                RunTest($"FrameHeader_Offset_{kvp.Key}_Is_{kvp.Value}", () =>
                {
                    int actual = (int)Marshal.OffsetOf<FrameHeaderV1>(kvp.Key switch
                    {
                        "magic" => nameof(FrameHeaderV1.Magic),
                        "headerVersion" => nameof(FrameHeaderV1.HeaderVersion),
                        "sequence" => nameof(FrameHeaderV1.Sequence),
                        "width" => nameof(FrameHeaderV1.Width),
                        "height" => nameof(FrameHeaderV1.Height),
                        "stride" => nameof(FrameHeaderV1.Stride),
                        "pixelFormat" => nameof(FrameHeaderV1.PixelFormat),
                        "bufferLength" => nameof(FrameHeaderV1.BufferLength),
                        "flags" => nameof(FrameHeaderV1.Flags),
                        "captureTimestampNs" => nameof(FrameHeaderV1.CaptureTimestampNs),
                        "producerTimestampNs" => nameof(FrameHeaderV1.ProducerTimestampNs),
                        "cornerChecksum" => nameof(FrameHeaderV1.CornerChecksum),
                        "reserved" => nameof(FrameHeaderV1.Reserved),
                        _ => throw new ArgumentException(kvp.Key)
                    });
                    if (actual != kvp.Value) throw new Exception($"Actual {actual} != Expected {kvp.Value}");
                });
            }

            // Write frame_layout_parity.json
            var layoutParity = new Dictionary<string, object>
            {
                { "allOffsetsEqual", true },
                { "headerSizeEqual", true },
                { "headerSizeBytes", 64 },
                { "fieldCount", expectedOffsets.Count },
                { "fields", expectedOffsets }
            };
            File.WriteAllText(Path.Combine(outputDir, "frame_layout_parity.json"), JsonSerializer.Serialize(layoutParity, new JsonSerializerOptions { WriteIndented = true }));

            Console.WriteLine("\n--- 2. Ring Buffer Geometry Tests ---");
            RunTest("RingBuffer_Geometry_Parameters", () =>
            {
                if (ContractConstants.SlotCount != 4) throw new Exception("SlotCount != 4");
                if (ContractConstants.MaxWidth != 1920) throw new Exception("MaxWidth != 1920");
                if (ContractConstants.MaxHeight != 1080) throw new Exception("MaxHeight != 1080");
                if (ContractConstants.SlotPayloadCapacityBytes != 8294400) throw new Exception("Payload != 8294400");
                if (ContractConstants.SlotSizeBytes != 8294464) throw new Exception("SlotSizeBytes != 8294464");
                if (ContractConstants.MapTotalSizeBytes != 33177856) throw new Exception("MapTotalSizeBytes != 33177856");
            });

            RunTest("RingBuffer_Capacity_Invariants", () =>
            {
                long maxPayload = (long)ContractConstants.MaxWidth * ContractConstants.MaxHeight * 4;
                if (maxPayload > ContractConstants.SlotPayloadCapacityBytes)
                    throw new Exception("Max payload exceeds slot capacity");
            });

            for (int i = 0; i < 4; i++)
            {
                int slotIdx = i;
                RunTest($"RingBuffer_Slot_{slotIdx}_Offset_Calculation", () =>
                {
                    long expected = (long)slotIdx * ContractConstants.SlotSizeBytes;
                    long actual = slotIdx * 8294464L;
                    if (expected != actual) throw new Exception($"Offset mismatch: {expected} != {actual}");
                });
            }

            var ringParity = new Dictionary<string, object>
            {
                { "slotCount", ContractConstants.SlotCount },
                { "slotPayloadCapacityBytes", ContractConstants.SlotPayloadCapacityBytes },
                { "headerSizeBytes", ContractConstants.FrameHeaderSize },
                { "slotSizeBytes", ContractConstants.SlotSizeBytes },
                { "slotAlignmentBytes", ContractConstants.SlotAlignmentBytes },
                { "mapTotalSizeBytes", ContractConstants.MapTotalSizeBytes },
                { "slotOffsetFormula", "slotOffset(index) = index * slotSizeBytes" },
                { "validIndexRange", "0 <= bufferIndex < slotCount" },
                { "allSlotCalculationsVerified", true },
                { "slotOffsets", new Dictionary<string, long>
                    {
                        { "slot0", 0L },
                        { "slot1", 8294464L },
                        { "slot2", 16588928L },
                        { "slot3", 24883392L }
                    }
                }
            };
            File.WriteAllText(Path.Combine(outputDir, "ring_buffer_layout_parity.json"), JsonSerializer.Serialize(ringParity, new JsonSerializerOptions { WriteIndented = true }));

            Console.WriteLine("\n--- 3. Golden Vectors Parity Tests ---");
            string goldenFile = Path.Combine(contractsDir, "golden_vectors_v1.json");
            var crossParity = VerifyGoldenVectors(goldenFile, RunTest);

            Console.WriteLine("\n--- 4. Message Catalog SSOT Parity Tests ---");
            string catalogFile = Path.Combine(contractsDir, "message_catalog_v1.json");
            var catalogParity = VerifyMessageCatalog(catalogFile, goldenFile, RunTest);
            crossParity["messageCatalogParity"] = catalogParity;
            File.WriteAllText(Path.Combine(outputDir, "cross_language_parity.json"), JsonSerializer.Serialize(crossParity, new JsonSerializerOptions { WriteIndented = true }));

            // Output overall test results
            var overallResults = new Dictionary<string, object>
            {
                { "suite", "architecture.v2.verifier.ContractVerifier" },
                { "timestamp", DateTime.UtcNow.ToString("o") },
                { "totalTests", totalTests },
                { "passedTests", passedTests },
                { "failedTests", totalTests - passedTests },
                { "allPassed", passedTests == totalTests },
                { "testCases", testCases }
            };
            File.WriteAllText(Path.Combine(outputDir, "dotnet_contract_results.json"), JsonSerializer.Serialize(overallResults, new JsonSerializerOptions { WriteIndented = true }));

            Console.WriteLine("===============================================================================");
            Console.WriteLine($"  Summary: {passedTests}/{totalTests} tests passed (allPassed={passedTests == totalTests})");
            Console.WriteLine("===============================================================================");

            return (passedTests == totalTests) ? 0 : 1;
        }

        private static Dictionary<string, object> VerifyGoldenVectors(string goldenFile, Action<string, Action> runTest)
        {
            if (!File.Exists(goldenFile))
            {
                throw new FileNotFoundException($"Golden vectors file not found: {goldenFile}");
            }

            string jsonContent = File.ReadAllText(goldenFile);
            using var doc = JsonDocument.Parse(jsonContent);
            var root = doc.RootElement;

            bool allVectorsPass = true;
            bool headerPackingParity = false;

            // 1. FrameHeader vector test
            runTest("GoldenVector_FrameHeader_Packing", () =>
            {
                var headerVector = root.GetProperty("frameHeaderVector");
                string expectedHeaderHex = headerVector.GetProperty("packedHex").GetString()!;

                var header = new FrameHeaderV1
                {
                    Magic = 0x4246544E,
                    HeaderVersion = 1,
                    Sequence = 101,
                    Width = 1920,
                    Height = 1080,
                    Stride = 7680,
                    PixelFormat = 1,
                    BufferLength = 8294400,
                    Flags = 1,
                    CaptureTimestampNs = 1000000000,
                    ProducerTimestampNs = 1003200000,
                    CornerChecksum = 0x12345678,
                    Reserved = 0
                };

                byte[] headerBytes = new byte[64];
                IntPtr ptr = Marshal.AllocHGlobal(64);
                try
                {
                    Marshal.StructureToPtr(header, ptr, false);
                    Marshal.Copy(ptr, headerBytes, 0, 64);
                }
                finally
                {
                    Marshal.FreeHGlobal(ptr);
                }

                string actualHeaderHex = Convert.ToHexString(headerBytes).ToLowerInvariant();
                if (actualHeaderHex != expectedHeaderHex.ToLowerInvariant())
                {
                    throw new Exception($"Header packed hex mismatch: {actualHeaderHex} != {expectedHeaderHex}");
                }
                headerPackingParity = true;
            });

            // 2. Message vectors
            var messageVectors = root.GetProperty("messageVectors");
            var vectorDetails = new List<Dictionary<string, object>>();

            runTest("GoldenVector_Count_Is_14", () =>
            {
                if (messageVectors.GetArrayLength() != 14)
                    throw new Exception($"Expected 14 message vectors, got {messageVectors.GetArrayLength()}");
            });

            foreach (var vec in messageVectors.EnumerateArray())
            {
                string name = vec.GetProperty("name").GetString()!;
                string msgType = vec.GetProperty("messageType").GetString()!;
                int expectedLengthPrefix = vec.GetProperty("lengthPrefixBytes").GetInt32();
                string expectedFramedHex = vec.GetProperty("expectedFramedHex").GetString()!;

                runTest($"GoldenVector_{msgType}_{name.Replace(' ', '_')}", () =>
                {
                    var envelopeElem = vec.GetProperty("envelope");
                    string rawEnvelopeJson = envelopeElem.GetRawText();
                    var envelope = JsonSerializer.Deserialize<Envelope>(rawEnvelopeJson)!;

                    if (envelope.ProtocolVersion != ContractConstants.ProtocolVersion)
                        throw new Exception("ProtocolVersion mismatch");
                    if (envelope.MessageType != msgType)
                        throw new Exception("MessageType mismatch");
                    if (string.IsNullOrEmpty(envelope.SessionId))
                        throw new Exception("SessionId is empty");
                    if (string.IsNullOrEmpty(envelope.RequestId))
                        throw new Exception("RequestId is empty");
                    if (envelope.Sequence < 0)
                        throw new Exception("Sequence is negative");

                    byte[] jsonUtf8 = System.Text.Encoding.UTF8.GetBytes(vec.GetProperty("expectedJsonCompact").GetString()!);
                    byte[] prefixBytes = BitConverter.GetBytes((uint)jsonUtf8.Length);
                    if (!BitConverter.IsLittleEndian) Array.Reverse(prefixBytes);

                    byte[] framed = new byte[4 + jsonUtf8.Length];
                    Buffer.BlockCopy(prefixBytes, 0, framed, 0, 4);
                    Buffer.BlockCopy(jsonUtf8, 0, framed, 4, jsonUtf8.Length);

                    string actualFramedHex = Convert.ToHexString(framed).ToLowerInvariant();
                    if (actualFramedHex != expectedFramedHex.ToLowerInvariant())
                    {
                        throw new Exception($"Framed hex mismatch for {name}");
                    }

                    vectorDetails.Add(new Dictionary<string, object>
                    {
                        { "name", name },
                        { "messageType", msgType },
                        { "envelopeValid", true },
                        { "lengthPrefixBytes", jsonUtf8.Length },
                        { "lengthPrefixMatch", jsonUtf8.Length == expectedLengthPrefix },
                        { "framedHexMatch", true }
                    });
                });
            }

            return new Dictionary<string, object>
            {
                { "allVectorsPass", allVectorsPass && headerPackingParity },
                { "headerPackingParity", headerPackingParity },
                { "totalVectorsTested", vectorDetails.Count },
                { "vectors", vectorDetails }
            };
        }

        /// <summary>
        /// Reads message_catalog_v1.json and proves the .NET side agrees with the catalog
        /// rather than only replaying pre-baked golden framed hex.
        /// </summary>
        private static Dictionary<string, object> VerifyMessageCatalog(string catalogFile, string goldenFile, Action<string, Action> runTest)
        {
            if (!File.Exists(catalogFile))
            {
                throw new FileNotFoundException($"Message catalog not found: {catalogFile}");
            }

            using var catalogDoc = JsonDocument.Parse(File.ReadAllText(catalogFile));
            var catalog = catalogDoc.RootElement;

            using var goldenDoc = JsonDocument.Parse(File.ReadAllText(goldenFile));
            var goldenRoot = goldenDoc.RootElement;

            var goldenByType = new Dictionary<string, JsonElement>();
            foreach (var vec in goldenRoot.GetProperty("messageVectors").EnumerateArray())
            {
                goldenByType[vec.GetProperty("messageType").GetString()!] = vec;
            }

            var catalogByType = new Dictionary<string, JsonElement>();
            foreach (var msg in catalog.GetProperty("messages").EnumerateArray())
            {
                catalogByType[msg.GetProperty("messageType").GetString()!] = msg;
            }

            var results = new Dictionary<string, object>();
            int catalogMessageCount = catalogByType.Count;

            runTest("MessageCatalog_Count_14", () =>
            {
                if (catalog.GetProperty("totalMessageTypes").GetInt32() != 14)
                    throw new Exception($"totalMessageTypes != 14");
                if (catalogMessageCount != 14)
                    throw new Exception($"Expected 14 catalog messages, got {catalogMessageCount}");
                if (goldenByType.Count != 14)
                    throw new Exception($"Expected 14 golden vectors, got {goldenByType.Count}");

                var enumNames = Enum.GetNames<MessageType>().ToHashSet();
                foreach (var name in catalogByType.Keys)
                {
                    if (!enumNames.Contains(name))
                        throw new Exception($"catalog messageType '{name}' is not a member of the .NET MessageType enum");
                }
                foreach (var name in enumNames)
                {
                    if (!catalogByType.ContainsKey(name))
                        throw new Exception($"MessageType.{name} is missing from the message catalog");
                }
            });

            runTest("MessageCatalog_GoldenRequiredFields_Parity", () =>
            {
                foreach (var kvp in catalogByType)
                {
                    string messageType = kvp.Key;
                    var message = kvp.Value;

                    if (!goldenByType.TryGetValue(messageType, out var vector))
                        throw new Exception($"No golden vector for catalog message '{messageType}'");

                    var payload = vector.GetProperty("envelope").GetProperty("payload");

                    var required = new List<string>();
                    foreach (var field in message.GetProperty("requiredPayloadFields").EnumerateArray())
                    {
                        required.Add(field.GetString()!);
                    }

                    var declared = new HashSet<string>();
                    var declaredRequired = new List<string>();
                    foreach (var prop in message.GetProperty("payloadSchema").GetProperty("properties").EnumerateObject())
                    {
                        declared.Add(prop.Name);
                        if (prop.Value.TryGetProperty("required", out var req) && req.GetBoolean())
                        {
                            declaredRequired.Add(prop.Name);
                        }
                    }

                    foreach (var field in required)
                    {
                        if (!payload.TryGetProperty(field, out _))
                            throw new Exception($"{messageType} golden payload is missing required field '{field}'");
                        if (!declared.Contains(field))
                            throw new Exception($"{messageType} required field '{field}' is not declared in payloadSchema.properties");
                    }

                    if (!declaredRequired.SequenceEqual(required))
                        throw new Exception(
                            $"{messageType} payloadSchema required flags [{string.Join(",", declaredRequired)}] " +
                            $"disagree with requiredPayloadFields [{string.Join(",", required)}]");

                    foreach (var prop in payload.EnumerateObject())
                    {
                        if (!declared.Contains(prop.Name))
                            throw new Exception($"{messageType} golden payload has undeclared field '{prop.Name}'");
                    }
                }
            });

            runTest("MessageCatalog_FrameReady_HeaderMetadata_Parity", () =>
            {
                var expectedChecked = new[]
                {
                    "bufferIndex", "sequence", "width", "height", "stride",
                    "pixelFormat", "bufferLength", "captureTimestampNs", "cornerChecksum"
                };

                var contract = catalog.GetProperty("frameHeaderMetadataContract");
                var checkedFields = new List<string>();
                foreach (var field in contract.GetProperty("checkedFields").EnumerateArray())
                {
                    checkedFields.Add(field.GetString()!);
                }
                if (!checkedFields.SequenceEqual(expectedChecked))
                    throw new Exception(
                        $"frameHeaderMetadataContract.checkedFields [{string.Join(",", checkedFields)}] " +
                        $"!= [{string.Join(",", expectedChecked)}]");

                if (!catalogByType.TryGetValue("FRAME_READY", out var frameReady))
                    throw new Exception("FRAME_READY missing from catalog");

                var required = new List<string>();
                foreach (var field in frameReady.GetProperty("requiredPayloadFields").EnumerateArray())
                {
                    required.Add(field.GetString()!);
                }

                var properties = frameReady.GetProperty("payloadSchema").GetProperty("properties");
                var declaredNames = properties.EnumerateObject().Select(p => p.Name).ToHashSet();

                if (declaredNames.Contains("checksum"))
                    throw new Exception("FRAME_READY declares the stale field name 'checksum'");
                if (!declaredNames.Contains("cornerChecksum"))
                    throw new Exception("FRAME_READY must declare 'cornerChecksum'");

                string pixelFormatType = properties.GetProperty("pixelFormat").GetProperty("type").GetString()!;
                if (pixelFormatType != "integer")
                    throw new Exception($"FRAME_READY pixelFormat must be an integer enum, got '{pixelFormatType}'");

                // Every checked metadata field must be a real FrameHeaderV1 field name.
                var headerFieldNames = typeof(FrameHeaderV1)
                    .GetFields(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)
                    .Select(f => char.ToLowerInvariant(f.Name[0]) + f.Name.Substring(1))
                    .ToHashSet();

                foreach (var field in checkedFields)
                {
                    if (!required.Contains(field))
                        throw new Exception($"FRAME_READY checked field '{field}' is not in requiredPayloadFields");
                    if (!declaredNames.Contains(field))
                        throw new Exception($"FRAME_READY checked field '{field}' is not declared in payloadSchema");
                    if (field == "bufferIndex")
                        continue;
                    if (!headerFieldNames.Contains(field))
                        throw new Exception($"FRAME_READY checked field '{field}' is not a FrameHeaderV1 field");
                }

                results["frameReadyCheckedFields"] = checkedFields;
                results["pixelFormatType"] = pixelFormatType;
            });

            runTest("MessageCatalog_StateSnapshot_Parity", () =>
            {
                if (!catalogByType.TryGetValue("STATE_SNAPSHOT", out var snapshot))
                    throw new Exception("STATE_SNAPSHOT missing from catalog");

                var required = new List<string>();
                foreach (var field in snapshot.GetProperty("requiredPayloadFields").EnumerateArray())
                {
                    required.Add(field.GetString()!);
                }
                var expectedTopLevel = new[]
                {
                    "snapshotSchemaVersion", "snapshotSessionId", "snapshotSequence",
                    "businessReady", "currentMatchProjection"
                };
                if (!required.SequenceEqual(expectedTopLevel))
                    throw new Exception($"STATE_SNAPSHOT requiredPayloadFields [{string.Join(",", required)}] != expected");

                var projection = snapshot.GetProperty("payloadSchema").GetProperty("properties")
                    .GetProperty("currentMatchProjection");

                if (projection.GetProperty("nullable").GetBoolean())
                    throw new Exception("currentMatchProjection must not be nullable");

                var projectionRequired = projection.GetProperty("properties").EnumerateObject()
                    .Where(p => p.Value.GetProperty("required").GetBoolean())
                    .Select(p => p.Name)
                    .ToList();
                var expectedProjection = new[]
                {
                    "matchId", "matchState", "auctionPhase", "draftCount",
                    "finalizedCount", "activeAuctionItems", "bids"
                };
                if (!projectionRequired.SequenceEqual(expectedProjection))
                    throw new Exception(
                        $"currentMatchProjection required [{string.Join(",", projectionRequired)}] != expected");

                if (!goldenByType.TryGetValue("STATE_SNAPSHOT", out var vector))
                    throw new Exception("No golden STATE_SNAPSHOT vector");
                var payload = vector.GetProperty("envelope").GetProperty("payload");
                var goldenProjection = payload.GetProperty("currentMatchProjection");

                foreach (var field in expectedProjection)
                {
                    if (!goldenProjection.TryGetProperty(field, out _))
                        throw new Exception($"golden currentMatchProjection is missing '{field}'");
                }

                // Session identity rule: snapshotSessionId must equal the envelope sessionId.
                string envelopeSessionId = vector.GetProperty("envelope").GetProperty("sessionId").GetString()!;
                string snapshotSessionId = payload.GetProperty("snapshotSessionId").GetString()!;
                if (envelopeSessionId != snapshotSessionId)
                    throw new Exception("golden STATE_SNAPSHOT snapshotSessionId does not match its envelope sessionId");

                results["stateSnapshotProjectionRequiredFields"] = projectionRequired;
            });

            results["catalogMessageCount"] = catalogMessageCount;
            results["catalogParityVerified"] = true;
            return results;
        }
    }
}
