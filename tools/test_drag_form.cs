using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

public class DragTestForm : Form
{
    public DragTestForm()
    {
        this.FormBorderStyle = FormBorderStyle.None;
        this.StartPosition = FormStartPosition.Manual;
        this.Location = new Point(300, 300);
        this.Size = new Size(390, 450);
        this.BackColor = Color.FromArgb(0x12, 0x16, 0x1F);
    }

    protected override void WndProc(ref Message m)
    {
        const int WM_NCHITTEST = 0x0084;
        const int HTCLIENT = 1;
        const int HTCAPTION = 2;

        if (m.Msg == WM_NCHITTEST)
        {
            int x = unchecked((short)(m.LParam.ToInt64() & 0xFFFF));
            int y = unchecked((short)((m.LParam.ToInt64() >> 16) & 0xFFFF));
            Point pt = this.PointToClient(new Point(x, y));
            Console.WriteLine("[WM_NCHITTEST] Screen: (" + x + "," + y + "), Client: (" + pt.X + "," + pt.Y + ")");

            if (pt.Y >= 0 && pt.Y <= 38 && (pt.X <= 145 || pt.X >= 245))
            {
                m.Result = (IntPtr)HTCAPTION;
                Console.WriteLine(" -> Returned HTCAPTION");
                return;
            }
            m.Result = (IntPtr)HTCLIENT;
            return;
        }

        base.WndProc(ref m);
    }
}

class Program
{
    [DllImport("user32.dll")]
    static extern bool SetCursorPos(int X, int Y);

    [DllImport("user32.dll")]
    static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

    static void Main()
    {
        DragTestForm form = new DragTestForm();

        Thread simThread = new Thread(() =>
        {
            Thread.Sleep(600);
            Point pBefore = Point.Empty;
            form.Invoke(new Action(() => { pBefore = form.Location; }));
            Console.WriteLine("Form pos before: " + pBefore);

            int startX = pBefore.X + 60;
            int startY = pBefore.Y + 15;
            SetCursorPos(startX, startY);
            Thread.Sleep(50);
            mouse_event(2, 0, 0, 0, UIntPtr.Zero); // DOWN
            Thread.Sleep(50);

            for (int i = 1; i <= 10; i++)
            {
                SetCursorPos(startX + i * 10, startY + i * 8);
                Thread.Sleep(20);
            }

            Thread.Sleep(50);
            mouse_event(4, 0, 0, 0, UIntPtr.Zero); // UP
            Thread.Sleep(100);

            Point pAfter = Point.Empty;
            form.Invoke(new Action(() => { pAfter = form.Location; }));
            Console.WriteLine("Form pos after: " + pAfter);
            Console.WriteLine("Delta: (" + (pAfter.X - pBefore.X) + ", " + (pAfter.Y - pBefore.Y) + ")");

            form.Invoke(new Action(() => { form.Close(); }));
        });

        simThread.Start();
        Application.Run(form);
    }
}
