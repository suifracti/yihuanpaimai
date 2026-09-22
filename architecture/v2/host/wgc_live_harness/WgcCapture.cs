using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Threading;
using NteHost.Protocol;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Windows.Graphics.Capture;
using Windows.Graphics.DirectX;
using Windows.Graphics.DirectX.Direct3D11;
using WinRT;

namespace WgcLiveHarness;

internal sealed record CapturedBgraFrame(
    int Width,
    int Height,
    int Stride,
    byte[] Pixels,
    long CaptureTimestampNs);

/// <summary>
/// Minimal WGC -> D3D11 readback for the V2-3 live probe. It deliberately owns
/// no input path and does not resize frames: the frozen V2-0 geometry is the
/// acceptance boundary.
/// </summary>
internal sealed class WgcWindowCapture : IDisposable
{
    private static readonly Guid GraphicsCaptureItemGuid =
        new("79C3F95B-31F7-4EC2-A464-632EF5D30760");
    private static readonly Guid GraphicsCaptureItemInteropGuid =
        new("3628E81B-3CAC-4C60-B7F4-23CE0E0C3356");
    private static readonly Guid D3D11Texture2DGuid =
        new("6F15AAF2-D208-4E89-9AB4-489535D34F9C");
    private static readonly Guid Direct3DDxgiInterfaceAccessGuid =
        new("A9B3D012-3DF2-4EE3-B8D1-8695F457D3C1");

    private readonly ID3D11Device _device;
    private readonly ID3D11DeviceContext _context;
    private readonly GraphicsCaptureItem _item;
    private readonly Direct3D11CaptureFramePool _framePool;
    private readonly GraphicsCaptureSession _session;
    private readonly AutoResetEvent _frameArrived = new(false);
    private bool _disposed;

    public int Width { get; }
    public int Height { get; }

    public WgcWindowCapture(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero)
        {
            throw new InvalidOperationException("WGC target HWND is zero");
        }

        var stage = "create-d3d11-device";
        try
        {
            (_device, _context) = CreateD3D11Device();
            stage = "create-capture-item";
            _item = CreateCaptureItem(hwnd);
            Width = _item.Size.Width;
            Height = _item.Size.Height;
            ValidateFixedV1Geometry(Width, Height);

            stage = "create-winrt-direct3d-device";
            var direct3DDevice = CreateWinRtDirect3DDevice(_device);
            stage = "create-frame-pool";
            _framePool = Direct3D11CaptureFramePool.CreateFreeThreaded(
                direct3DDevice,
                DirectXPixelFormat.B8G8R8A8UIntNormalized,
                2,
                _item.Size);
            stage = "start-capture-session";
            _framePool.FrameArrived += OnFrameArrived;
            _session = _framePool.CreateCaptureSession(_item);
            _session.StartCapture();
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException(
                $"WGC initialization failed at {stage}: {ex.GetType().Name}: {ex.Message}", ex);
        }
        finally
        {
            if (_framePool is null)
            {
                _context?.Dispose();
                _device?.Dispose();
            }
        }
    }

    public CapturedBgraFrame Capture(int timeoutMs)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (!_frameArrived.WaitOne(timeoutMs))
        {
            throw new TimeoutException($"WGC frame did not arrive within {timeoutMs}ms");
        }

        using var frame = _framePool.TryGetNextFrame();
        if (frame is null)
        {
            throw new InvalidOperationException("WGC signalled FrameArrived but TryGetNextFrame returned null");
        }

        var size = frame.ContentSize;
        ValidateFixedV1Geometry(size.Width, size.Height);
        if (size.Width != Width || size.Height != Height)
        {
            throw new InvalidOperationException(
                $"WGC content size changed from {Width}x{Height} to {size.Width}x{size.Height}; " +
                "fixed-v1 probe fails closed instead of resizing or changing the contract");
        }

        using var sourceTexture = GetTexture(frame.Surface);
        var sourceDescription = sourceTexture.Description;
        if (sourceDescription.Format != Format.B8G8R8A8_UNorm)
        {
            throw new InvalidOperationException(
                $"WGC surface format {sourceDescription.Format} is not BGRA8");
        }
        if (sourceDescription.Width != (uint)Width || sourceDescription.Height != (uint)Height)
        {
            throw new InvalidOperationException(
                $"WGC texture description is {sourceDescription.Width}x{sourceDescription.Height}, " +
                $"expected {Width}x{Height}");
        }

        var stagingDescription = new Texture2DDescription(
            Format.B8G8R8A8_UNorm,
            (uint)Width,
            (uint)Height,
            1,
            1,
            BindFlags.None,
            ResourceUsage.Staging,
            CpuAccessFlags.Read,
            1,
            0,
            ResourceOptionFlags.None);
        using var staging = _device.CreateTexture2D(stagingDescription);
        _context.CopyResource(staging, sourceTexture);
        var mapResult = _context.Map(staging, 0, MapMode.Read, Vortice.Direct3D11.MapFlags.None, out var mapped);
        mapResult.CheckError();
        try
        {
            var stride = checked(Width * 4);
            var pixels = new byte[checked(stride * Height)];
            for (var y = 0; y < Height; y++)
            {
                Marshal.Copy(
                    IntPtr.Add(mapped.DataPointer, checked(y * (int)mapped.RowPitch)),
                    pixels,
                    checked(y * stride),
                    stride);
            }

            return new CapturedBgraFrame(Width, Height, stride, pixels, ProtocolClock.NowNs());
        }
        finally
        {
            _context.Unmap(staging, 0);
        }
    }

    private void OnFrameArrived(Direct3D11CaptureFramePool sender, object args) =>
        _frameArrived.Set();

    private static (ID3D11Device Device, ID3D11DeviceContext Context) CreateD3D11Device()
    {
        var featureLevels = new[] { FeatureLevel.Level_11_0 };
        var result = D3D11.D3D11CreateDevice(
            IntPtr.Zero,
            DriverType.Hardware,
            DeviceCreationFlags.BgraSupport,
            featureLevels,
            out var device,
            out var context);
        result.CheckError();
        return (device, context);
    }

    private static GraphicsCaptureItem CreateCaptureItem(IntPtr hwnd)
    {
        var classNameText = "Windows.Graphics.Capture.GraphicsCaptureItem";
        var createStringHr = WindowsCreateString(
            classNameText,
            classNameText.Length,
            out var className);
        Marshal.ThrowExceptionForHR(createStringHr);
        var factoryIid = GraphicsCaptureItemInteropGuid;
        var factoryPointer = IntPtr.Zero;
        try
        {
            var hr = RoGetActivationFactory(className, ref factoryIid, out factoryPointer);
            Marshal.ThrowExceptionForHR(hr);
            var interop = (IGraphicsCaptureItemInterop)Marshal.GetObjectForIUnknown(factoryPointer);
            var itemIid = GraphicsCaptureItemGuid;
            var itemPointer = interop.CreateForWindow(hwnd, ref itemIid);
            if (itemPointer == IntPtr.Zero)
            {
                throw new InvalidOperationException("IGraphicsCaptureItemInterop.CreateForWindow returned null");
            }
            try
            {
                return ComWrappersSupport.CreateRcwForComObject<GraphicsCaptureItem>(itemPointer);
            }
            finally
            {
                Marshal.Release(itemPointer);
            }
        }
        finally
        {
            if (factoryPointer != IntPtr.Zero)
            {
                Marshal.Release(factoryPointer);
            }
            WindowsDeleteString(className);
        }
    }

    private static IDirect3DDevice CreateWinRtDirect3DDevice(ID3D11Device device)
    {
        using var dxgiDevice = device.QueryInterface<IDXGIDevice>();
        var hr = CreateDirect3D11DeviceFromDXGIDevice(dxgiDevice.NativePointer, out var unknown);
        Marshal.ThrowExceptionForHR(hr);
        try
        {
            return ComWrappersSupport.CreateRcwForComObject<IDirect3DDevice>(unknown);
        }
        finally
        {
            Marshal.Release(unknown);
        }
    }

    private static ID3D11Texture2D GetTexture(IDirect3DSurface surface)
    {
        var surfaceUnknown = Marshal.GetIUnknownForObject(surface);
        try
        {
            var accessPointer = IntPtr.Zero;
            var accessIid = Direct3DDxgiInterfaceAccessGuid;
            var hr = Marshal.QueryInterface(
                surfaceUnknown,
                ref accessIid,
                out accessPointer);
            Marshal.ThrowExceptionForHR(hr);
            try
            {
                var access = (IDirect3DDxgiInterfaceAccess)Marshal.GetObjectForIUnknown(accessPointer);
                var texturePointer = IntPtr.Zero;
                var textureIid = D3D11Texture2DGuid;
                hr = access.GetInterface(ref textureIid, out texturePointer);
                Marshal.ThrowExceptionForHR(hr);
                try
                {
                    return new ID3D11Texture2D(texturePointer);
                }
                finally
                {
                    // ID3D11Texture2D owns the returned COM reference after its
                    // wrapper is constructed; do not release it here.
                    texturePointer = IntPtr.Zero;
                }
            }
            finally
            {
                Marshal.Release(accessPointer);
            }
        }
        finally
        {
            Marshal.Release(surfaceUnknown);
        }
    }

    private static void ValidateFixedV1Geometry(int width, int height)
    {
        if (width <= 0 || height <= 0
            || width > ProtocolConstants.MaxFrameWidth
            || height > ProtocolConstants.MaxFrameHeight)
        {
            throw new InvalidOperationException(
                $"real WGC window is {width}x{height}, outside fixed-v1 capacity " +
                $"{ProtocolConstants.MaxFrameWidth}x{ProtocolConstants.MaxFrameHeight}; fail-closed");
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        _framePool.FrameArrived -= OnFrameArrived;
        _session.Dispose();
        _framePool.Dispose();
        _frameArrived.Dispose();
        _context.Dispose();
        _device.Dispose();
    }

    [DllImport("d3d11.dll", ExactSpelling = true)]
    private static extern int CreateDirect3D11DeviceFromDXGIDevice(
        IntPtr dxgiDevice,
        out IntPtr graphicsDevice);

    [DllImport("combase.dll", CharSet = CharSet.Unicode)]
    private static extern int RoGetActivationFactory(
        IntPtr activatableClassId,
        [In] ref Guid iid,
        out IntPtr factory);

    [DllImport("combase.dll", CharSet = CharSet.Unicode)]
    private static extern int WindowsCreateString(
        string sourceString,
        int length,
        out IntPtr hstring);

    [DllImport("combase.dll")]
    private static extern int WindowsDeleteString(IntPtr hstring);

    [ComImport]
    [Guid("3628E81B-3CAC-4C60-B7F4-23CE0E0C3356")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IGraphicsCaptureItemInterop
    {
        IntPtr CreateForWindow([In] IntPtr window, [In] ref Guid iid);
        IntPtr CreateForMonitor([In] IntPtr monitor, [In] ref Guid iid);
    }

    [ComImport]
    [Guid("A9B3D012-3DF2-4EE3-B8D1-8695F457D3C1")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IDirect3DDxgiInterfaceAccess
    {
        int GetInterface([In] ref Guid iid, out IntPtr p);
    }
}
