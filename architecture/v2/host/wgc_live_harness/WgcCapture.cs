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
    long CaptureTimestampNs,
    string CapturedAtUtc,
    long SourceTimestampNs);

/// <summary>
/// Minimal WGC -> D3D11 readback for the Native observation profile. It
/// deliberately owns no input path and never resizes pixels. WGC may expose a
/// top-level HWND including non-client chrome; the explicit client-area map
/// below removes only those pixels before the result enters fixed-v1 MMF.
/// </summary>
internal sealed class WgcWindowCapture : IDisposable
{
    private static readonly Guid GraphicsCaptureItemGuid =
        new("79C3F95B-31F7-4EC2-A464-632EF5D30760");
    private static readonly Guid GraphicsCaptureItemInteropGuid =
        new("3628E81B-3CAC-4C60-B7F4-23CE0E0C3356");
    private static readonly Guid D3D11Texture2DGuid =
        new("6F15AAF2-D208-4E89-9AB4-489535D34F9C");

    private readonly ID3D11Device _device;
    private readonly ID3D11DeviceContext _context;
    private readonly GraphicsCaptureItem _item;
    private readonly Direct3D11CaptureFramePool _framePool;
    private readonly GraphicsCaptureSession _session;
    private readonly AutoResetEvent _frameArrived = new(false);
    private readonly IntPtr _hwnd;
    private readonly ClientAreaMapping _clientArea;
    private readonly WarehouseBoundsSource _warehouseBoundsSource;
    private bool _disposed;

    public int Width { get; }
    public int Height { get; }
    public int CaptureItemWidth { get; }
    public int CaptureItemHeight { get; }
    public int ClientOffsetX => _clientArea.X;
    public int ClientOffsetY => _clientArea.Y;
    public int LastRequestDiscardedQueuedFrames { get; private set; }
    public bool EnableRequestClockDiagnostics { get; set; }
    public string? LastRequestClockDiagnosticsJson { get; private set; }

    public WgcWindowCapture(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero)
        {
            throw new InvalidOperationException("WGC target HWND is zero");
        }

        _hwnd = hwnd;
        var stage = "create-d3d11-device";
        try
        {
            (_device, _context) = CreateD3D11Device();
            stage = "create-capture-item";
            _item = CreateCaptureItem(hwnd);
            CaptureItemWidth = _item.Size.Width;
            CaptureItemHeight = _item.Size.Height;
            ValidateCaptureSourceGeometry(CaptureItemWidth, CaptureItemHeight);
            _clientArea = ResolveClientAreaMapping(hwnd, CaptureItemWidth, CaptureItemHeight);
            Width = _clientArea.Width;
            Height = _clientArea.Height;
            ValidateFixedV1Geometry(Width, Height);
            _warehouseBoundsSource = ResolveWarehouseBoundsProof();

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

        return ReadBack(frame);
    }

    // Explicit requests retain the caller's QPC gate and original deadline.
    // Ordinary continuous Capture/FRAME keeps its existing selection policy.
    public CapturedBgraFrame CaptureAfterRequest(int timeoutMs, long requestNs,
        long absoluteWorkDeadlineNs, Func<bool> stopped)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(stopped);
        var deadlineNs = RequestFrameSelector.DeadlineForRequest(timeoutMs, requestNs, absoluteWorkDeadlineNs);
        var discarded = 0;
        LastRequestDiscardedQueuedFrames = 0;
        LastRequestClockDiagnosticsJson = null;
        var diagnostics = EnableRequestClockDiagnostics ? new RequestClockDiagnostics(requestNs, deadlineNs) : null;
        void CheckAvailable()
        {
            if (stopped()) throw new OperationCanceledException("Explicit frame request stopped.");
            if (ProtocolClock.NowNs() >= deadlineNs)
                throw new TimeoutException("Explicit frame request reached its original deadline.");
            if (stopped()) throw new OperationCanceledException("Explicit frame request stopped.");
        }
        try
        {
            using var frame = RequestFrameSelector.Select(
                () => _framePool.TryGetNextFrame(),
                candidate => diagnostics is null ? checked(candidate.SystemRelativeTime.Ticks * 100L)
                    : diagnostics.Source(candidate.SystemRelativeTime.Ticks),
                candidate => candidate.Dispose(),
                remainingMs => _frameArrived.WaitOne(remainingMs),
                diagnostics is null ? ProtocolClock.NowNs : diagnostics.SelectionClock,
                stopped, requestNs, deadlineNs, out discarded);
            CheckAvailable();
            var result = ReadBack(frame, diagnostics);
            CheckAvailable();
            return result;
        }
        catch (Exception ex)
        {
            if (diagnostics is not null) diagnostics.Failure = ex.GetType().Name + ": " + ex.Message;
            throw;
        }
        finally
        {
            LastRequestDiscardedQueuedFrames = discarded;
            if (diagnostics is not null) LastRequestClockDiagnosticsJson = diagnostics.ToJson();
        }
    }

    private CapturedBgraFrame ReadBack(Direct3D11CaptureFrame frame, RequestClockDiagnostics? diagnostics = null)
    {

        var size = frame.ContentSize;
        ValidateCaptureSourceGeometry(size.Width, size.Height);
        if (size.Width != CaptureItemWidth || size.Height != CaptureItemHeight)
        {
            throw new InvalidOperationException(
                $"WGC capture item size changed from {CaptureItemWidth}x{CaptureItemHeight} " +
                $"to {size.Width}x{size.Height}; client-area map is no longer stable");
        }
        var currentClientArea = ResolveClientAreaMapping(_hwnd, size.Width, size.Height);
        if (currentClientArea != _clientArea)
        {
            throw new InvalidOperationException(
                $"WGC client-area map changed from {_clientArea} to {currentClientArea}; " +
                "fail-closed instead of publishing a frame with uncertain coordinates");
        }

        using var sourceTexture = GetTexture(frame.Surface);
        var sourceDescription = sourceTexture.Description;
        if (sourceDescription.Format != Format.B8G8R8A8_UNorm)
        {
            throw new InvalidOperationException(
                $"WGC surface format {sourceDescription.Format} is not BGRA8");
        }
        if (sourceDescription.Width != (uint)CaptureItemWidth
            || sourceDescription.Height != (uint)CaptureItemHeight)
        {
            throw new InvalidOperationException(
                $"WGC texture description is {sourceDescription.Width}x{sourceDescription.Height}, " +
                $"expected capture item {CaptureItemWidth}x{CaptureItemHeight}");
        }

        var stagingDescription = new Texture2DDescription(
            Format.B8G8R8A8_UNorm,
            (uint)CaptureItemWidth,
            (uint)CaptureItemHeight,
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
                    IntPtr.Add(
                        mapped.DataPointer,
                        checked(((_clientArea.Y + y) * (int)mapped.RowPitch) + (_clientArea.X * 4))),
                    pixels,
                    checked(y * stride),
                    stride);
            }

            if (diagnostics is not null)
            {
                var sample = QpcClockSample.Read();
                var utc = DateTimeOffset.UtcNow.ToString("O");
                var rawSourceTicks = frame.SystemRelativeTime.Ticks;
                var sourceNs = checked(rawSourceTicks * 100L);
                diagnostics.Readback(rawSourceTicks, sample);
                return new CapturedBgraFrame(Width, Height, stride, pixels, sample.Nanoseconds, utc, sourceNs);
            }
            return new CapturedBgraFrame(
                Width,
                Height,
                stride,
                pixels,
                ProtocolClock.NowNs(),
                DateTimeOffset.UtcNow.ToString("O"),
                checked(frame.SystemRelativeTime.Ticks * 100L));
        }
        finally
        {
            _context.Unmap(staging, 0);
        }
    }

    // Source-only gate: the business Capture/FRAME path keeps its existing mapping policy.
    public bool IsClientAreaMappingCurrent()
    {
        if (_disposed || _warehouseBoundsSource == WarehouseBoundsSource.Unproven) return false;
        try
        {
            var size = _item.Size;
            return size.Width == CaptureItemWidth && size.Height == CaptureItemHeight
                && WarehouseMappingMatches(_clientArea, CaptureItemWidth, CaptureItemHeight,
                    ReadWarehouseMappingObservation(_warehouseBoundsSource));
        }
        catch (Exception)
        {
            // An unavailable mapping cannot authorise an original-frame publication.
            return false;
        }
    }

    private WarehouseBoundsSource ResolveWarehouseBoundsProof()
    {
        foreach (var source in new[] { WarehouseBoundsSource.WindowRect, WarehouseBoundsSource.DwmExtendedFrameBounds })
        {
            if (WarehouseMappingMatches(_clientArea, CaptureItemWidth, CaptureItemHeight,
                    ReadWarehouseMappingObservation(source))) return source;
        }
        return WarehouseBoundsSource.Unproven;
    }

    private WarehouseMappingObservation? ReadWarehouseMappingObservation(WarehouseBoundsSource source)
    {
        try
        {
            if (!GetClientRect(_hwnd, out var client)) return null;
            var origin = new Point32();
            if (!ClientToScreen(_hwnd, ref origin)) return null;
            Rect32 bounds;
            if (source == WarehouseBoundsSource.WindowRect)
            {
                if (!GetWindowRect(_hwnd, out bounds)) return null;
            }
            else if (source == WarehouseBoundsSource.DwmExtendedFrameBounds)
            {
                if (DwmGetWindowAttribute(_hwnd, DwmExtendedFrameBounds, out bounds,
                        (uint)Marshal.SizeOf<Rect32>()) != 0) return null;
            }
            else return null;
            return new WarehouseMappingObservation(checked(client.Right - client.Left), checked(client.Bottom - client.Top),
                origin.X, origin.Y, bounds.Left, bounds.Top,
                checked(bounds.Right - bounds.Left), checked(bounds.Bottom - bounds.Top));
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static bool WarehouseMappingMatches(ClientAreaMapping expected, int itemWidth, int itemHeight,
        WarehouseMappingObservation? observed) => observed is { } value
        && value.ClientWidth == expected.Width && value.ClientHeight == expected.Height
        && value.BoundsWidth == itemWidth && value.BoundsHeight == itemHeight
        && (long)value.ClientOriginX - value.BoundsLeft == expected.X
        && (long)value.ClientOriginY - value.BoundsTop == expected.Y;

    private enum WarehouseBoundsSource { Unproven, WindowRect, DwmExtendedFrameBounds }
    private readonly record struct WarehouseMappingObservation(int ClientWidth, int ClientHeight,
        int ClientOriginX, int ClientOriginY, int BoundsLeft, int BoundsTop, int BoundsWidth, int BoundsHeight);

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
        // The surface is a C#/WinRT projection. CLR Marshal round-trips can
        // return the managed projection instead of the requested COM interface.
        // As<T> queries the underlying WinRT object using its projection helper.
        var access = surface.As<IDirect3DDxgiInterfaceAccess>();
        var textureIid = D3D11Texture2DGuid;
        var hr = access.GetInterface(ref textureIid, out var texturePointer);
        Marshal.ThrowExceptionForHR(hr);
        // Vortice owns the reference returned by GetInterface.
        return new ID3D11Texture2D(texturePointer);
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

    private static void ValidateCaptureSourceGeometry(int width, int height)
    {
        // The fixed protocol applies to the mapped customer-area payload. A
        // small bounded allowance is permitted only for top-level non-client
        // chrome; it is never sent through MMF and never changes the protocol.
        var sourceMaxWidth = checked(ProtocolConstants.MaxFrameWidth + 256);
        var sourceMaxHeight = checked(ProtocolConstants.MaxFrameHeight + 256);
        if (width <= 0 || height <= 0 || width > sourceMaxWidth || height > sourceMaxHeight)
        {
            throw new InvalidOperationException(
                $"WGC capture item is {width}x{height}, outside bounded customer-area " +
                $"mapping capacity {sourceMaxWidth}x{sourceMaxHeight}; fail-closed");
        }
    }

    private static ClientAreaMapping ResolveClientAreaMapping(
        IntPtr hwnd,
        int captureWidth,
        int captureHeight)
    {
        if (!GetClientRect(hwnd, out var clientRect))
        {
            throw new InvalidOperationException(
                $"GetClientRect failed for HWND {hwnd}");
        }

        var clientWidth = clientRect.Right - clientRect.Left;
        var clientHeight = clientRect.Bottom - clientRect.Top;
        if (clientWidth <= 0 || clientHeight <= 0)
        {
            throw new InvalidOperationException(
                $"target client area is {clientWidth}x{clientHeight}; fail-closed");
        }
        ValidateFixedV1Geometry(clientWidth, clientHeight);

        // A borderless/fullscreen item may already be exactly the client area.
        if (captureWidth == clientWidth && captureHeight == clientHeight)
        {
            return new ClientAreaMapping(0, 0, clientWidth, clientHeight);
        }

        var clientOrigin = new Point32();
        if (!ClientToScreen(hwnd, ref clientOrigin))
        {
            throw new InvalidOperationException(
                $"ClientToScreen failed for HWND {hwnd}");
        }

        var bounds = new List<Rect32>();
        if (GetWindowRect(hwnd, out var windowRect))
        {
            bounds.Add(windowRect);
        }
        if (DwmGetWindowAttribute(
                hwnd,
                DwmExtendedFrameBounds,
                out var extendedBounds,
                (uint)Marshal.SizeOf<Rect32>()) == 0)
        {
            bounds.Add(extendedBounds);
        }

        foreach (var candidate in bounds.Distinct())
        {
            var x = clientOrigin.X - candidate.Left;
            var y = clientOrigin.Y - candidate.Top;
            if (x >= 0 && y >= 0
                && x + clientWidth <= captureWidth
                && y + clientHeight <= captureHeight)
            {
                return new ClientAreaMapping(x, y, clientWidth, clientHeight);
            }
        }

        throw new InvalidOperationException(
            $"cannot map client area {clientWidth}x{clientHeight} at screen " +
            $"({clientOrigin.X},{clientOrigin.Y}) into WGC item {captureWidth}x{captureHeight}; " +
            "fail-closed without resizing or guessing coordinates");
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

    private const uint DwmExtendedFrameBounds = 9;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool GetClientRect(IntPtr hwnd, out Rect32 rect);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool ClientToScreen(IntPtr hwnd, ref Point32 point);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool GetWindowRect(IntPtr hwnd, out Rect32 rect);

    [DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmGetWindowAttribute(
        IntPtr hwnd,
        uint attribute,
        out Rect32 value,
        uint valueSize);

    [StructLayout(LayoutKind.Sequential)]
    private readonly record struct Point32(int X, int Y);

    [StructLayout(LayoutKind.Sequential)]
    private readonly record struct Rect32(int Left, int Top, int Right, int Bottom);

    private readonly record struct ClientAreaMapping(int X, int Y, int Width, int Height);

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
        [PreserveSig]
        int GetInterface([In] ref Guid iid, out IntPtr p);
    }
}
