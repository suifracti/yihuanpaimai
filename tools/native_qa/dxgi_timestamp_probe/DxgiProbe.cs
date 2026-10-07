using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Loader;
using System.Text.Json;
using NteHost.Protocol;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Windows.Graphics.Capture;

internal static class DxgiProbe
{
    static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    record Sample(long RawTicks, long FrequencyHz, long Nanoseconds, int ManagedThreadId);
    static Sample Clock() { var t = Stopwatch.GetTimestamp(); return new(t, ProtocolClock.Frequency, ProtocolClock.TicksToNs(t), Environment.CurrentManagedThreadId); }
    static void Emit(object o) { Console.WriteLine(JsonSerializer.Serialize(o, Json)); Console.Out.Flush(); }
    static long Deadline; static int Stop;
    static void Check() { if (Volatile.Read(ref Stop) != 0) throw new OperationCanceledException("qa-stopped"); if (ProtocolClock.NowNs() >= Deadline) throw new TimeoutException("work-deadline"); }
    sealed class OwnWindow : Form
    {
        protected override bool ShowWithoutActivation => true;
        public OwnWindow() { Text = "Synthetic DXGI timestamp QA"; ClientSize = new(640,360); StartPosition = FormStartPosition.Manual; Location = new(24,24); FormBorderStyle = FormBorderStyle.FixedSingle; MaximizeBox = false; MinimizeBox = false; ShowInTaskbar = false; }
    }
    [DllImport("kernel32.dll")] static extern bool IsProcessInJob(nint process, nint job, out bool result);
    [DllImport("kernel32.dll")] static extern nint GetCurrentProcess();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(nint hwnd, out uint pid);
    [STAThread] public static int Main(string[] args)
    {
        Emit(new { kind = "ready", clock = Clock() });
        using var cmd = JsonDocument.Parse(Console.ReadLine() ?? throw new Exception("missing-GO"));
        Deadline = cmd.RootElement.GetProperty("workDeadlineNs").GetInt64();
        if (cmd.RootElement.GetProperty("command").GetString() != "GO" || Deadline <= ProtocolClock.NowNs() || Deadline - ProtocolClock.NowNs() > 8_000_000_000L) return 2;
        if (!IsProcessInJob(GetCurrentProcess(), 0, out var inJob) || !inJob) return 2;
        new Thread(() => { try { while (Console.ReadLine() is { } line) { using var c = JsonDocument.Parse(line); if (c.RootElement.GetProperty("command").GetString() == "STOP") Interlocked.Exchange(ref Stop,1); } } finally { Interlocked.Exchange(ref Stop,1); } }) { IsBackground=true }.Start();
        string hostDir = Path.GetFullPath(args[0]);
        AssemblyLoadContext.Default.Resolving += (_, n) => { var p = Path.Combine(hostDir,n.Name+".dll"); return File.Exists(p) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(p) : null; };
        OwnWindow? window=null; object? capture=null; ID3D11Device? device=null; ID3D11DeviceContext? context=null; IDXGISwapChain1? swap=null;
        string? failure=null, cleanupFailure=null; object? firstGateFailure=null;
        int attempts=0, accepted=0, dequeued=0, released=0, readbacks=0, presents=0, statsReads=0, arrivals=0;
        long lastSource=0; uint nonce = (uint)Random.Shared.Next(1,int.MaxValue);
        try
        {
            Check(); window=new(); window.Show(); Application.DoEvents();
            D3D11.D3D11CreateDevice(nint.Zero, DriverType.Hardware, DeviceCreationFlags.BgraSupport, new[] { FeatureLevel.Level_11_0 }, out device, out context).CheckError();
            using var dxgiDevice=device.QueryInterface<IDXGIDevice>(); using var adapter=dxgiDevice.GetAdapter(); using var factory=adapter.GetParent<IDXGIFactory2>();
            swap=factory.CreateSwapChainForHwnd(device,window.Handle,new SwapChainDescription1 { Width=640,Height=360, Format=Format.B8G8R8A8_UNorm, SampleDescription=new(1,0), BufferUsage=Usage.RenderTargetOutput, BufferCount=2, Scaling=Scaling.Stretch, SwapEffect=SwapEffect.FlipSequential, AlphaMode=AlphaMode.Ignore });
            object Stats(string stage)
            {
                Check(); statsReads++; var before=Clock(); var hr=swap.GetFrameStatistics(out var s); var after=Clock();
                var e=new { stage,before,after,hresult=hr.Code, s.PresentCount,s.PresentRefreshCount,s.SyncRefreshCount,s.SyncQPCTime,s.SyncGPUTime, displayCompletionProven=false };
                Emit(new {kind="frame-statistics", evidence=e}); return e;
            }
            void Present(int counter)
            {
                Check(); var pixels=Enumerable.Repeat((byte)255,640*360*4).ToArray();
                ulong code=((ulong)nonce<<16)|(uint)counter;
                for(int bit=0;bit<48;bit++) for(int y=8;y<28;y++) for(int x=8+bit*6;x<12+bit*6;x++) { int k=(y*640+x)*4; bool one=(code&(1UL<<bit))!=0; pixels[k]=(byte)(one?0:255); pixels[k+1]=0; pixels[k+2]=(byte)(one?255:0); }
                var submitBefore=Clock(); using(var back=swap.GetBuffer<ID3D11Texture2D>(0)) context.UpdateSubresource(pixels,back,0,640*4,0); var submitAfter=Clock();
                var presentBefore=Clock(); var hr=swap.Present(1,PresentFlags.None); var presentAfter=Clock(); presents++;
                uint? last=null; string? countError=null; var countBefore=Clock(); try { last=swap.LastPresentCount; } catch(Exception e) { countError=e.GetType().Name; } var countAfter=Clock();
                Emit(new {kind="content-present",counter,nonce,submitBefore,submitAfter,presentBefore,presentAfter,hresult=hr.Code,lastPresentCount=last,countBefore,countAfter,countError,cpuSubmissionOnly=true,displayCompletionProven=false});
                if(hr.Code!=0) throw new Exception("Present-not-S_OK:"+hr.Code);
            }
            Present(0); Stats("baseline");
            var assembly=Assembly.LoadFrom(Path.Combine(hostDir,"WgcLiveHarness.dll")); var type=assembly.GetType("WgcLiveHarness.WgcWindowCapture",true)!;
            capture=type.GetConstructor(new[]{typeof(nint)})!.Invoke(new object[]{window.Handle});
            var pool=(Direct3D11CaptureFramePool)type.GetField("_framePool",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(capture)!;
            var arrived=(AutoResetEvent)type.GetField("_frameArrived",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(capture)!;
            pool.FrameArrived+=(_,_)=>Interlocked.Increment(ref arrivals);
            var map=type.GetMethod("IsClientAreaMappingCurrent")!; var readback=type.GetMethod("ReadBack",BindingFlags.Instance|BindingFlags.NonPublic)!;
            var selector=assembly.GetType("WgcLiveHarness.RequestFrameSelector",true)!.GetMethod("Select")!.MakeGenericMethod(typeof(Direct3D11CaptureFrame));
            var policy=assembly.GetType("WgcLiveHarness.BackgroundObservationPolicy",true)!;
            var abi=typeof(Program).GetMethod("ReadAbi",BindingFlags.Static|BindingFlags.NonPublic)!;
            nint pinnedHwnd=window.Handle;
            bool Mapping() { Check(); if(window.IsDisposed || window.WindowState==FormWindowState.Minimized || !window.IsHandleCreated || window.Handle!=pinnedHwnd || GetWindowThreadProcessId(pinnedHwnd,out var owner)==0 || owner!=Environment.ProcessId || !(bool)map.Invoke(capture,null)!) throw new Exception("own-window-or-mapping-invalid"); return true; }
            Emit(new {kind="construct",ownHwnd=window.Handle.ToInt64(),ownGeneratedOnly=true,nonce,clock=Clock(),mapping=Mapping(),sdk=typeof(Direct3D11CaptureFrame).Assembly.FullName,os=Environment.OSVersion.VersionString,dotnet=RuntimeInformation.FrameworkDescription});
            object Pixels(Direct3D11CaptureFrame f)
            {
                Mapping(); var before=Clock(); var p=readback.Invoke(capture,new object?[]{f,null})!; var after=Clock(); Mapping(); readbacks++;
                T V<T>(string n)=>(T)p.GetType().GetProperty(n)!.GetValue(p)!;
                var bytes=V<byte[]>("Pixels"); int stride=V<int>("Stride"); ulong decoded=0;
                for(int bit=0;bit<48;bit++) {int k=18*stride+(10+bit*6)*4; if(bytes[k+2]>200 && bytes[k]<50) decoded|=1UL<<bit;}
                return new {before,after,sourceNs=V<long>("SourceTimestampNs"),readbackNs=V<long>("CaptureTimestampNs"),width=V<int>("Width"),height=V<int>("Height"),stride,decodedNonce=(uint)(decoded>>16),decodedCounter=(int)(decoded&65535),nonceMatches=(uint)(decoded>>16)==nonce,pixelSha256=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant(),diagnosticOnly=true,displayCompletionProven=false};
            }
            while(attempts<3)
            {
                Mapping(); attempts++; var request=Clock(); long deadline=Math.Min(Deadline,request.Nanoseconds+2_000_000_000L); Present(attempts);
                Emit(new {kind="attempt",attempt=attempts,request,deadline});
                Direct3D11CaptureFrame? pending=null; Sample? dequeueBefore=null,dequeueAfter=null,propertyBefore=null,propertyAfter=null; long ticks=0; object? diagnosticPixels=null;
                Direct3D11CaptureFrame? Take() { Mapping(); Application.DoEvents(); dequeueBefore=Clock(); var f=pool.TryGetNextFrame(); dequeueAfter=Clock(); if(f!=null) dequeued++; return f; }
                long Source(Direct3D11CaptureFrame f) {propertyBefore=Clock();ticks=f.SystemRelativeTime.Ticks;propertyAfter=Clock();pending=f;return checked(ticks*100L);}
                long Compare()
                {
                    var compare=Clock(); var f=pending; pending=null; if(f==null) return compare.Nanoseconds;
                    long sourceNs=checked(ticks*100L); string? reject=sourceNs>compare.Nanoseconds?"source-in-future":null;
                    if(sourceNs<=request.Nanoseconds && reject==null) { Emit(new {kind="old-pool-frame",attempt=attempts,request,dequeueBefore,dequeueAfter,propertyBefore,propertyAfter,ticks,sourceNs,comparison=compare}); return compare.Nanoseconds; }
                    var decision=new {kind="original-decision",attempt=attempts,request,deadline,dequeueBefore,dequeueAfter,propertyBefore,propertyAfter,projectedTicks=ticks,sourceNs,comparison=compare,aheadNs=sourceNs-compare.Nanoseconds,rejection=reject};
                    if(reject!=null) firstGateFailure??=decision; Emit(decision);
                    var raw=abi.Invoke(null,new object[]{f})!; var repeatBefore=Clock(); long repeated=f.SystemRelativeTime.Ticks; var repeatAfter=Clock(); var rawAgain=abi.Invoke(null,new object[]{f})!;
                    var a=JsonSerializer.SerializeToElement(raw,Json);var b=JsonSerializer.SerializeToElement(rawAgain,Json);
                    bool identity=a.GetProperty("sameIdentity").GetBoolean()&&b.GetProperty("sameIdentity").GetBoolean()&&a.GetProperty("frameUnknown").GetInt64()==b.GetProperty("frameUnknown").GetInt64();
                    bool same=identity&&repeated==ticks&&a.GetProperty("duration").GetInt64()==ticks&&a.GetProperty("originalPointerDuration").GetInt64()==ticks&&b.GetProperty("duration").GetInt64()==ticks&&b.GetProperty("originalPointerDuration").GetInt64()==ticks;
                    var size=f.ContentSize;
                    Emit(new {kind="same-frame-getters",attempt=attempts,originalDecision=decision,raw,repeatBefore,projectedAgain=repeated,repeatAfter,rawAgain,sameFrameIdentity=identity,sameValue=same,contentSize=new {size.Width,size.Height},aheadNs=sourceNs-compare.Nanoseconds});
                    if(!same) throw new Exception("same-frame-ABI-mismatch");
                    // Own synthetic pixels only. Original rejection is frozen before this GPU work.
                    diagnosticPixels=Pixels(f); Emit(new {kind="synthetic-content-readback",attempt=attempts,originalRejection=reject,originalComparison=compare,evidence=diagnosticPixels}); Stats("frame-"+attempts);
                    return compare.Nanoseconds;
                }
                void Release(Direct3D11CaptureFrame f) {f.Dispose();released++;}
                object?[] call={ (Func<Direct3D11CaptureFrame?>)Take,(Func<Direct3D11CaptureFrame,long>)Source,(Action<Direct3D11CaptureFrame>)Release,(Func<int,bool>)(ms=>arrived.WaitOne(ms)),(Func<long>)Compare,(Func<bool>)(()=>Volatile.Read(ref Stop)!=0),request.Nanoseconds,deadline,0 };
                var selected=(Direct3D11CaptureFrame)selector.Invoke(null,call)!;
                try { Mapping(); var p=JsonSerializer.SerializeToElement(diagnosticPixels,Json); long source=p.GetProperty("sourceNs").GetInt64(), read=p.GetProperty("readbackNs").GetInt64();
                    string? r=(string?)policy.GetMethod("BackgroundReadbackRejection")!.Invoke(null,new object[]{"background-readonly",source,read,lastSource});
                    r??=(string?)policy.GetMethod("BackgroundPublicationRejection")!.Invoke(null,new object[]{"background-readonly",source,ProtocolClock.NowNs()}); if(r!=null) throw new Exception(r);
                    if(source!=ticks*100L || !p.GetProperty("nonceMatches").GetBoolean()) throw new Exception("source-or-own-content-mismatch");
                    lastSource=source;accepted++;Emit(new {kind="accepted-diagnostic-frame",attempt=attempts,accepted,clock=Clock(),businessPublished=false});
                } finally { Release(selected); }
            }
        }
        catch(Exception e) { while(e is TargetInvocationException && e.InnerException!=null)e=e.InnerException; failure=e.GetType().Name+": "+e.Message; }
        finally
        {
            Emit(new {kind="disposing",attempts,accepted,failure,firstGateFailure,clock=Clock()});
            try { (capture as IDisposable)?.Dispose();swap?.Dispose();context?.Dispose();device?.Dispose();window?.Close();window?.Dispose(); } catch(Exception e) {cleanupFailure=e.GetType().Name+": "+e.Message;}
        }
        Emit(new {kind="result",attempts,acceptedDiagnosticFrames=accepted,dequeued,released,readbacks,presents,statsReads,frameArrivals=arrivals,failure,firstGateFailure,cleanupFailure,completed=Clock(),gameCapture=false,desktopCapture=false,gameInput=false,businessPublishedFrames=0,imagesSaved=0,productionGateChanged=false,displayCompletionProven=false});
        return failure==null&&cleanupFailure==null?0:1;
    }
}
