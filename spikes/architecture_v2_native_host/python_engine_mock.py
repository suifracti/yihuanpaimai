import sys
import json
import time
import os

def run_stdio_engine():
    """Simulated Python Intelligence Engine communicating via length-prefixed JSON over stdio."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdin.reconfigure(encoding='utf-8')
    
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            err_resp = json.dumps({"status": "error", "message": str(e)})
            sys.stdout.write(err_resp + "\n")
            sys.stdout.flush()
            continue

        cmd = req.get("cmd")
        req_id = req.get("id", 0)

        if cmd == "ping":
            resp = {"id": req_id, "status": "ok", "cmd": "pong", "server_time": time.time()}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        elif cmd == "frame_infer":
            t0 = time.perf_counter()
            frame_seq = req.get("frame_seq", 0)
            time.sleep(0.005)
            dt_ms = (time.perf_counter() - t0) * 1000
            resp = {
                "id": req_id,
                "status": "ok",
                "cmd": "frame_result",
                "frame_seq": frame_seq,
                "in_auction": True,
                "bids": [{"seat": 1, "price": 1200}, {"seat": 2, "price": 1500}],
                "processing_ms": dt_ms
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        elif cmd == "read_mmf":
            import mmap
            import struct
            import numpy as np

            t0 = time.perf_counter()
            map_name = req.get("map_name", "NteFrameBuffer_V2_Spike").replace("Local\\", "")
            expected_seq = req.get("expected_seq", 0)
            total_size = req.get("total_size", 8294464)

            t_map_start = time.perf_counter()
            try:
                global _cached_mm, _cached_map_name
                if '_cached_mm' not in globals() or _cached_mm is None or _cached_map_name != map_name:
                    _cached_mm = mmap.mmap(-1, total_size, tagname=map_name, access=mmap.ACCESS_READ)
                    _cached_map_name = map_name
                mm = _cached_mm
                t_map_end = time.perf_counter()
                mapping_latency_ms = (t_map_end - t_map_start) * 1000

                # Unpack 64-byte header: <IiqqiIIIIi
                header = struct.unpack_from("<IiqqiIIIIi", mm, 0)
                magic, version, seq, ts_ticks, width, height, stride, datalen, checksum, _ = header

                # Zero-copy view into pixel memory
                frame_view = np.frombuffer(mm, dtype=np.uint8, count=datalen, offset=64)

                c1 = int(frame_view[0])
                c2 = int(frame_view[stride - 4])
                c3 = int(frame_view[-stride])
                c4 = int(frame_view[-4])
                actual_checksum = (c1 + c2 + c3 + c4) & 0xFFFFFFFF

                checksum_ok = (checksum == actual_checksum)
                seq_ok = (seq == expected_seq)
                magic_ok = (magic == 0x4246544E)

                t_total_ms = (time.perf_counter() - t0) * 1000
                del frame_view

                resp = {
                    "id": req_id,
                    "status": "ok" if (checksum_ok and seq_ok and magic_ok) else "integrity_failed",
                    "cmd": "read_mmf_ack",
                    "seq": seq,
                    "expected_seq": expected_seq,
                    "magic_ok": magic_ok,
                    "seq_monotonic": seq_ok,
                    "checksum_verified": checksum_ok,
                    "mapping_latency_ms": mapping_latency_ms,
                    "consumer_processing_ms": t_total_ms,
                    "producer_timestamp_ticks": ts_ticks
                }
            except Exception as ex:
                resp = {
                    "id": req_id,
                    "status": "error",
                    "cmd": "read_mmf_ack",
                    "message": str(ex)
                }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        elif cmd == "simulate_crash":
            sys.stderr.write("Simulating engine crash as requested.\n")
            sys.stderr.flush()
            os._exit(42)
        elif cmd == "shutdown":
            resp = {"id": req_id, "status": "ok", "cmd": "shutdown_ack"}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            break
        else:
            resp = {"id": req_id, "status": "unknown_cmd", "cmd": cmd}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    run_stdio_engine()
