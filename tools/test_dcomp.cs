using System;
using System.Runtime.InteropServices;

class Program
{
    [DllImport("d3d11.dll")]
    static extern int D3D11CreateDevice(
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

    [DllImport("dcomp.dll")]
    static extern int DCompositionCreateDevice(
        IntPtr dxgiDevice,
        ref Guid iid,
        out IntPtr dcompositionDevice);

    [DllImport("dcomp.dll")]
    static extern int DCompositionCreateDevice2(
        IntPtr renderingDevice,
        ref Guid iid,
        out IntPtr dcompositionDevice);

    [DllImport("dcomp.dll")]
    static extern int DCompositionCreateDevice3(
        IntPtr renderingDevice,
        ref Guid iid,
        out IntPtr dcompositionDevice);

    static void Main()
    {
        IntPtr d3dDevice, context;
        int featureLevel;
        int hr = D3D11CreateDevice(IntPtr.Zero, 1, IntPtr.Zero, 0x20, IntPtr.Zero, 0, 7, out d3dDevice, out featureLevel, out context);
        Console.WriteLine("D3D11CreateDevice: 0x" + hr.ToString("X8") + ", ptr=" + d3dDevice);

        IntPtr dxgiDevice;
        Guid iidDxgi = new Guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c");
        hr = Marshal.QueryInterface(d3dDevice, ref iidDxgi, out dxgiDevice);
        Console.WriteLine("QueryInterface IDXGIDevice: 0x" + hr.ToString("X8") + ", ptr=" + dxgiDevice);

        Guid[] guids = new Guid[]
        {
            new Guid("C37D2E60-705E-4CE0-9B21-0DA398FF4F8C"), // IDCompositionDevice
            new Guid("5F4633EC-0B43-4B87-B626-4F46094F9D0E"), // IDCompositionDesktopDevice
            new Guid("75010A3E-9F12-427E-83CE-7F48E21A0C6A"), // IDCompositionDevice2
            new Guid("09874977-CE04-45E0-9E11-37E1C7E6D779"), // IDCompositionDevice3
            new Guid("00000000-0000-0000-C000-000000000046"), // IUnknown
        };

        foreach (var g in guids)
        {
            Guid g1 = g;
            IntPtr ptr1;
            int hr1 = DCompositionCreateDevice(dxgiDevice, ref g1, out ptr1);
            Console.WriteLine("DCompositionCreateDevice(" + g + "): 0x" + hr1.ToString("X8") + ", ptr=" + ptr1);

            Guid g2 = g;
            IntPtr ptr2;
            int hr2 = DCompositionCreateDevice2(dxgiDevice, ref g2, out ptr2);
            Console.WriteLine("DCompositionCreateDevice2(" + g + "): 0x" + hr2.ToString("X8") + ", ptr=" + ptr2);

            Guid g3 = g;
            IntPtr ptr3;
            int hr3 = DCompositionCreateDevice3(dxgiDevice, ref g3, out ptr3);
            Console.WriteLine("DCompositionCreateDevice3(" + g + "): 0x" + hr3.ToString("X8") + ", ptr=" + ptr3);
        }
    }
}
