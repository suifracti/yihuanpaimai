using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using ArchitectureV2.NativeHost.Contracts;

namespace ArchitectureV2.NativeHost
{
    public static class ContractVerifier
    {
        public static void RunVerification(string contractsDir, string outputDir)
        {
            Console.WriteLine("=== NTE Architecture V2: Host-Engine Contract Verifier ===");
            Directory.CreateDirectory(outputDir);

            // 1. Frame Layout Parity Verification
            var layoutResults = VerifyFrameLayout(contractsDir);
            string layoutJson = JsonSerializer.Serialize(layoutResults, new JsonSerializerOptions { WriteIndented = true });
            string layoutPath = Path.Combine(outputDir, "frame_layout_parity.json");
            File.WriteAllText(layoutPath, layoutJson);
            Console.WriteLine($"[Layout] Parity result written to: {layoutPath} (allOffsetsEqual={layoutResults["allOffsetsEqual"]})");

            // 2. Cross-Language Golden Vector Parity Verification
            var vectorResults = VerifyGoldenVectors(contractsDir);
            string vectorJson = JsonSerializer.Serialize(vectorResults, new JsonSerializerOptions { WriteIndented = true });
            string vectorPath = Path.Combine(outputDir, "cross_language_parity.json");
            File.WriteAllText(vectorPath, vectorJson);
            Console.WriteLine($"[GoldenVectors] Parity result written to: {vectorPath} (allVectorsPass={vectorResults["allVectorsPass"]})");
        }

        private static Dictionary<string, object> VerifyFrameLayout(string contractsDir)
        {
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

            var actualOffsets = new Dictionary<string, int>
            {
                { "magic", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.Magic)) },
                { "headerVersion", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.HeaderVersion)) },
                { "sequence", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.Sequence)) },
                { "width", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.Width)) },
                { "height", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.Height)) },
                { "stride", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.Stride)) },
                { "pixelFormat", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.PixelFormat)) },
                { "bufferLength", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.BufferLength)) },
                { "flags", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.Flags)) },
                { "captureTimestampNs", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.CaptureTimestampNs)) },
                { "producerTimestampNs", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.ProducerTimestampNs)) },
                { "cornerChecksum", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.CornerChecksum)) },
                { "reserved", (int)Marshal.OffsetOf<FrameHeaderV1>(nameof(FrameHeaderV1.Reserved)) }
            };

            int actualSize = Marshal.SizeOf<FrameHeaderV1>();
            bool headerSizeEqual = (actualSize == 64);
            bool allOffsetsEqual = headerSizeEqual;

            var offsetComparison = new Dictionary<string, object>();
            foreach (var kvp in expectedOffsets)
            {
                int actual = actualOffsets[kvp.Key];
                bool match = (actual == kvp.Value);
                if (!match) allOffsetsEqual = false;
                offsetComparison[kvp.Key] = new
                {
                    expectedOffset = kvp.Value,
                    actualOffset = actual,
                    match = match
                };
            }

            return new Dictionary<string, object>
            {
                { "allOffsetsEqual", allOffsetsEqual },
                { "headerSizeEqual", headerSizeEqual },
                { "headerSizeBytes", actualSize },
                { "fieldCount", expectedOffsets.Count },
                { "fields", offsetComparison }
            };
        }

        private static Dictionary<string, object> VerifyGoldenVectors(string contractsDir)
        {
            string goldenFile = Path.Combine(contractsDir, "golden_vectors_v1.json");
            if (!File.Exists(goldenFile))
            {
                throw new FileNotFoundException($"Golden vectors file not found: {goldenFile}");
            }

            string jsonContent = File.ReadAllText(goldenFile);
            using var doc = JsonDocument.Parse(jsonContent);
            var root = doc.RootElement;

            // 1. Verify frame header packing
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
            bool headerPackingParity = (actualHeaderHex == expectedHeaderHex.ToLowerInvariant());

            // 2. Verify message vectors
            var messageVectors = root.GetProperty("messageVectors");
            var vectorDetails = new List<Dictionary<string, object>>();
            bool allVectorsPass = headerPackingParity;

            foreach (var vec in messageVectors.EnumerateArray())
            {
                string name = vec.GetProperty("name").GetString()!;
                string msgType = vec.GetProperty("messageType").GetString()!;
                var envelopeElem = vec.GetProperty("envelope");
                string rawEnvelopeJson = envelopeElem.GetRawText();
                
                // Parse into Envelope object
                var envelope = JsonSerializer.Deserialize<Envelope>(rawEnvelopeJson)!;
                bool envelopeValid = !string.IsNullOrEmpty(envelope.ProtocolVersion) &&
                                     !string.IsNullOrEmpty(envelope.SessionId) &&
                                     !string.IsNullOrEmpty(envelope.MessageType) &&
                                     !string.IsNullOrEmpty(envelope.RequestId) &&
                                     envelope.MessageType == msgType;

                int expectedLengthPrefix = vec.GetProperty("lengthPrefixBytes").GetInt32();
                string expectedFramedHex = vec.GetProperty("expectedFramedHex").GetString()!;

                // Re-encode JSON and length prefix in C#
                byte[] jsonUtf8 = System.Text.Encoding.UTF8.GetBytes(vec.GetProperty("expectedJsonCompact").GetString()!);
                byte[] prefixBytes = BitConverter.GetBytes((uint)jsonUtf8.Length);
                if (!BitConverter.IsLittleEndian) Array.Reverse(prefixBytes);

                byte[] framed = new byte[4 + jsonUtf8.Length];
                Buffer.BlockCopy(prefixBytes, 0, framed, 0, 4);
                Buffer.BlockCopy(jsonUtf8, 0, framed, 4, jsonUtf8.Length);

                string actualFramedHex = Convert.ToHexString(framed).ToLowerInvariant();
                bool hexMatch = (actualFramedHex == expectedFramedHex.ToLowerInvariant());

                if (!envelopeValid || !hexMatch) allVectorsPass = false;

                vectorDetails.Add(new Dictionary<string, object>
                {
                    { "name", name },
                    { "messageType", msgType },
                    { "envelopeValid", envelopeValid },
                    { "lengthPrefixBytes", jsonUtf8.Length },
                    { "lengthPrefixMatch", jsonUtf8.Length == expectedLengthPrefix },
                    { "framedHexMatch", hexMatch }
                });
            }

            return new Dictionary<string, object>
            {
                { "allVectorsPass", allVectorsPass },
                { "headerPackingParity", headerPackingParity },
                { "totalVectorsTested", vectorDetails.Count },
                { "vectors", vectorDetails }
            };
        }
    }
}
