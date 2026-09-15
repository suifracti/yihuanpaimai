using System;
using System.Runtime.InteropServices;

namespace TestDCompSpy
{
    class Program
    {
        [DllImport("dcomp.dll")]
        public static extern int DCompositionCreateDevice(
            IntPtr renderingDevice,
            ref Guid iid,
            out IntPtr dcompositionDevice);

        [DllImport("dcomp.dll")]
        public static extern int DCompositionCreateDevice2(
            IntPtr renderingDevice,
            ref Guid iid,
            out IntPtr dcompositionDevice);

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int QueryInterfaceDelegate(IntPtr self, ref Guid iid, out IntPtr ppv);

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate uint AddRefDelegate(IntPtr self);

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate uint ReleaseDelegate(IntPtr self);

        static QueryInterfaceDelegate qi;
        static AddRefDelegate addRef;
        static ReleaseDelegate release;

        static int CustomQueryInterface(IntPtr self, ref Guid iid, out IntPtr ppv)
        {
            Console.WriteLine("[SPY QI] Requested IID: " + iid.ToString());
            ppv = self;
            return 0; // S_OK
        }

        static uint CustomAddRef(IntPtr self) { return 1; }
        static uint CustomRelease(IntPtr self) { return 1; }

        static void Main()
        {
            qi = CustomQueryInterface;
            addRef = CustomAddRef;
            release = CustomRelease;

            IntPtr[] vtable = new IntPtr[]
            {
                Marshal.GetFunctionPointerForDelegate(qi),
                Marshal.GetFunctionPointerForDelegate(addRef),
                Marshal.GetFunctionPointerForDelegate(release),
            };

            IntPtr pVtable = Marshal.AllocHGlobal(IntPtr.Size * vtable.Length);
            Marshal.Copy(vtable, 0, pVtable, vtable.Length);

            IntPtr pObject = Marshal.AllocHGlobal(IntPtr.Size);
            Marshal.WriteIntPtr(pObject, pVtable);

            Console.WriteLine("Passing dummy object to DCompositionCreateDevice...");
            Guid iidDev = new Guid("c37d2e60-705e-4ce0-9b21-0da398ff4f8c");
            IntPtr pDev;
            int hr = DCompositionCreateDevice(pObject, ref iidDev, out pDev);
            Console.WriteLine("DCompositionCreateDevice result: 0x" + hr.ToString("X8") + ", pDev=" + pDev);

            Console.WriteLine("Passing dummy object to DCompositionCreateDevice2...");
            int hr2 = DCompositionCreateDevice2(pObject, ref iidDev, out pDev);
            Console.WriteLine("DCompositionCreateDevice2 result: 0x" + hr2.ToString("X8") + ", pDev=" + pDev);
        }
    }
}
