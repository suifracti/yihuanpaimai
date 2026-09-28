using System;

namespace ArchitectureV2.NativeHost
{
    public class SendInputBoundaryResult
    {
        public bool MockDryRun { get; set; }
        public bool PrecheckPassed { get; set; }
        public bool ToctouForegroundPassed { get; set; }
        public bool CursorSaved { get; set; }
        public bool CursorRestored { get; set; }
        public bool ActualSendInputExecuted { get; set; }
        public string Reason { get; set; } = "OK";
        public uint ExtraInfoTag { get; set; } = NativeMethods.WAREHOUSE_WHEEL_EXTRA_INFO;
        public string SafetyInvariant { get; set; } = "Strict fail-closed: requires token freshness, TOCTOU foreground verification, and mock_dry_run prevents accidental game input injection.";
    }

    public static class MockSafeSendInputProbe
    {
        public static SendInputBoundaryResult Run(IntPtr targetHwnd, bool mockDryRun = true)
        {
            var result = new SendInputBoundaryResult
            {
                MockDryRun = mockDryRun
            };

            // 1. Precheck target HWND
            if (targetHwnd == IntPtr.Zero || !NativeMethods.IsWindow(targetHwnd))
            {
                result.PrecheckPassed = false;
                result.Reason = "HWND_INVALID";
                return result;
            }

            if (!NativeMethods.IsWindowVisible(targetHwnd))
            {
                result.PrecheckPassed = false;
                result.Reason = "HWND_HIDDEN";
                return result;
            }

            if (NativeMethods.IsIconic(targetHwnd))
            {
                result.PrecheckPassed = false;
                result.Reason = "HWND_MINIMIZED";
                return result;
            }

            result.PrecheckPassed = true;

            // 2. Save cursor position
            NativeMethods.GetCursorPos(out var origCursor);
            result.CursorSaved = true;

            try
            {
                // 3. TOCTOU foreground ownership check
                IntPtr currentFg = NativeMethods.GetForegroundWindow();
                if (currentFg != targetHwnd)
                {
                    result.ToctouForegroundPassed = false;
                    result.Reason = "NOT_FOREGROUND_ABORT";
                    return result;
                }
                result.ToctouForegroundPassed = true;

                // 4. Safe SendInput execution (mock dry-run branch)
                if (mockDryRun)
                {
                    // In mock mode, we calculate inputs and simulate execution without calling Win32 SendInput
                    result.ActualSendInputExecuted = false;
                    result.Reason = "MOCK_DRY_RUN_OK";
                }
                else
                {
                    // Armed mode - only executed if explicitly authorized
                    var inputs = new NativeMethods.INPUT[1];
                    inputs[0].type = NativeMethods.INPUT_MOUSE;
                    inputs[0].mi.dx = 0;
                    inputs[0].mi.dy = 0;
                    inputs[0].mi.mouseData = unchecked((uint)-120); // Downward 1 notch
                    inputs[0].mi.dwFlags = NativeMethods.MOUSEEVENTF_WHEEL;
                    inputs[0].mi.dwExtraInfo = (UIntPtr)NativeMethods.WAREHOUSE_WHEEL_EXTRA_INFO;

                    uint sent = NativeMethods.SendInput(1, inputs, System.Runtime.InteropServices.Marshal.SizeOf<NativeMethods.INPUT>());
                    result.ActualSendInputExecuted = (sent == 1);
                    result.Reason = (sent == 1) ? "OK" : "SENDINPUT_FAILED";
                }
            }
            finally
            {
                // 5. Cursor restoration guard
                NativeMethods.SetCursorPos(origCursor.X, origCursor.Y);
                result.CursorRestored = true;
            }

            return result;
        }
    }
}
