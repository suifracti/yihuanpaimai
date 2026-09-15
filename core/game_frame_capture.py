"""Capture one tracked game client without changing the image coordinate space."""
from datetime import datetime, timedelta, timezone


def capture_tracked_game_frame(tracker, capture_manager, sct, window_exists):
    captured_at = datetime.now(timezone(timedelta(hours=8))).isoformat()
    hwnd = tracker.find_game_window()
    if hwnd is None or not window_exists(hwnd):
        return None, None, captured_at, "none"
    frame, source = capture_manager.capture_game_client(hwnd, sct=sct)
    # The manager already retries using the client rectangle. A full desktop
    # retry would silently change every downstream ROI's coordinate system.
    return hwnd, frame, captured_at, source if frame is not None else "none"
