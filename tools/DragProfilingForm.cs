
using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Diagnostics;
using Microsoft.Web.WebView2.Core;
using NTE.DirectComposition;

namespace NTE.Profiling
{
    public class DragProfilingForm : DirectCompositionHudForm
    {
        public long CountWmNcHitTest = 0;
        public long CountWmMouseMove = 0;
        public long CountWmNcLButtonDown = 0;
        public long CountWmWindowPosChanged = 0;
        public long CountWmMove = 0;
        public long CountWmPaint = 0;
        public long CountSendMouseInput = 0;
        public long CountDCompCommit = 0;
        public long CountEnterSizeMove = 0;
        public long CountExitSizeMove = 0;
        public long CountTotalMessages = 0;

        public DragProfilingForm(int x, int y, int w, int h, bool onTop) : base(x, y, w, h, onTop)
        {
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            CountDCompCommit++;
        }

        protected override void WndProc(ref Message m)
        {
            CountTotalMessages++;
            const int WM_NCHITTEST = 0x0084;
            const int WM_MOUSEMOVE = 0x0200;
            const int WM_NCLBUTTONDOWN = 0x00A1;
            const int WM_WINDOWPOSCHANGED = 0x0047;
            const int WM_MOVE = 0x0003;
            const int WM_PAINT = 0x000F;
            const int WM_ENTERSIZEMOVE = 0x0231;
            const int WM_EXITSIZEMOVE = 0x0232;

            switch (m.Msg)
            {
                case WM_NCHITTEST: CountWmNcHitTest++; break;
                case WM_MOUSEMOVE: CountWmMouseMove++; break;
                case WM_NCLBUTTONDOWN: CountWmNcLButtonDown++; break;
                case WM_WINDOWPOSCHANGED: CountWmWindowPosChanged++; break;
                case WM_MOVE: CountWmMove++; break;
                case WM_PAINT: CountWmPaint++; break;
                case WM_ENTERSIZEMOVE: CountEnterSizeMove++; break;
                case WM_EXITSIZEMOVE: CountExitSizeMove++; break;
            }

            // Count SendMouseInput forwarding
            if (m.Msg == WM_MOUSEMOVE || m.Msg == 0x0201 || m.Msg == 0x0202 || m.Msg == 0x0204 || m.Msg == 0x0205)
            {
                // If it's in client area
                int screenX = unchecked((short)(m.LParam.ToInt64() & 0xFFFF));
                int screenY = unchecked((short)((m.LParam.ToInt64() >> 16) & 0xFFFF));
                Point pt = this.PointToClient(new Point(screenX, screenY));
                if (!(pt.Y >= 0 && pt.Y <= 38 && (pt.X <= 145 || pt.X >= 245)))
                {
                    CountSendMouseInput++;
                }
            }

            base.WndProc(ref m);
        }

        public void ResetTelemetry()
        {
            CountWmNcHitTest = 0;
            CountWmMouseMove = 0;
            CountWmNcLButtonDown = 0;
            CountWmWindowPosChanged = 0;
            CountWmMove = 0;
            CountWmPaint = 0;
            CountSendMouseInput = 0;
            CountDCompCommit = 0;
            CountEnterSizeMove = 0;
            CountExitSizeMove = 0;
            CountTotalMessages = 0;
        }
    }
}
