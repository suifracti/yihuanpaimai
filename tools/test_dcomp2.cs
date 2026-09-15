using System;
using System.Runtime.InteropServices;

namespace TestDComp
{
    class Program
    {
        [DllImport("d3d11.dll", PreserveSig = true)]
        public static extern int D3D11CreateDevice(
            IntPtr pAdapter,
            int DriverType,
            IntPtr Software,
            uint Flags,
            IntPtr pFeatureLevels,
            uint FeatureLevels,
            uint SDKVersion,
            out IntPtr ppDevice,
            out int pFeatureLevel,
            out IntPtr ppImmediateContext);

        [DllImport("dcomp.dll", PreserveSig = true)]
        public static extern int DCompositionCreateDevice(
            IntPtr dxgiDevice,
            [In] ref Guid iid,
            out IntPtr dcompositionDevice);

        [DllImport("dcomp.dll", PreserveSig = true)]
        public static extern int DCompositionCreateDevice2(
            IntPtr renderingDevice,
            [In] ref Guid iid,
            out IntPtr dcompositionDevice);

        static void Main()
        {
            IntPtr d3dDevice, ctx;
            int feat;
            int hr = D3D11CreateDevice(IntPtr.Zero, 1, IntPtr.Zero, 0x20, IntPtr.Zero, 0, 7, out d3dDevice, out feat, out ctx);
            Console.WriteLine("D3D11CreateDevice: 0x" + hr.ToString("X8"));

            IntPtr dxgi;
            Guid iidDxgi = typeof(IDXGIDevice).GUID;
            hr = Marshal.QueryInterface(d3dDevice, ref iidDxgi, out dxgi);
            Console.WriteLine("QueryInterface IDXGIDevice: 0x" + hr.ToString("X8") + ", ptr=" + dxgi);

            Guid iidDev = typeof(IDCompositionDevice).GUID;
            Console.WriteLine("IDCompositionDevice GUID: " + iidDev);

            IntPtr pDev;
            hr = DCompositionCreateDevice(dxgi, ref iidDev, out pDev);
            Console.WriteLine("DCompositionCreateDevice: 0x" + hr.ToString("X8") + ", pDev=" + pDev);

            IntPtr pDev2;
            hr = DCompositionCreateDevice2(dxgi, ref iidDev, out pDev2);
            Console.WriteLine("DCompositionCreateDevice2: 0x" + hr.ToString("X8") + ", pDev2=" + pDev2);
        }
    }

    [ComImport]
    [Guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IDXGIDevice
    {
    }

    [ComImport]
    [Guid("C37D2E60-705E-4CE0-9B21-0DA398FF4F8C")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IDCompositionDevice
    {
        [PreserveSig]
        int Commit();
        [PreserveSig]
        int WaitForCommitCompletion();
        [PreserveSig]
        int GetFrameStatistics(IntPtr statistics);
        [PreserveSig]
        int CreateTargetForHwnd(IntPtr hwnd, bool topmost, out IntPtr target);
        [PreserveSig]
        int CreateVisual(out IntPtr visual);
    }
}
