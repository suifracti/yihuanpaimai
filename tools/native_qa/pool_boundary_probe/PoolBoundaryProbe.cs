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

internal static class PoolBoundaryProbe
{
    record Sample(long RawTicks, long FrequencyHz, long Nanoseconds, int Thread);
    static Sample Clock() { var t = Stopwatch.GetTimestamp(); return new(t, ProtocolClock.Frequency, ProtocolClock.TicksToNs(t), Environment.CurrentManagedThreadId); }
    static readonly object LogGate = new();
    static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    static void Emit(object item) { lock (LogGate) { Console.WriteLine(JsonSerializer.Serialize(item, Json)); Console.Out.Flush(); } }
    static long Deadline; static int Stop, PresentCounter;
    static void Check() { if (Volatile.Read(ref Stop) != 0) throw new OperationCanceledException("qa-stop"); if (ProtocolClock.NowNs() >= Deadline) throw new TimeoutException("qa-work-deadline"); }
    [DllImport("kernel32.dll")] static extern bool IsProcessInJob(nint process, nint job, out bool result);
    [DllImport("kernel32.dll")] static extern nint GetCurrentProcess();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(nint hwnd, out uint pid);
    sealed class OwnWindow : Form
    {
        protected override bool ShowWithoutActivation => true;
        public OwnWindow() { Text="Synthetic continuous pool QA"; ClientSize=new(640,360); Location=new(24,24); StartPosition=FormStartPosition.Manual; FormBorderStyle=FormBorderStyle.FixedSingle; ShowInTaskbar=false; MaximizeBox=false; MinimizeBox=false; }
    }
    [STAThread] public static int Main(string[] args)
    {
        Emit(new {kind="ready",clock=Clock()});
        using var go=JsonDocument.Parse(Console.ReadLine() ?? throw new Exception("GO missing"));
        Deadline=go.RootElement.GetProperty("workDeadlineNs").GetInt64();
        if(go.RootElement.GetProperty("command").GetString()!="GO" || Deadline<=ProtocolClock.NowNs() || Deadline-ProtocolClock.NowNs()>8_000_000_000L || !IsProcessInJob(GetCurrentProcess(),0,out var inJob) || !inJob) return 2;
        new Thread(()=>{ try { while(Console.ReadLine() is {} line) { using var c=JsonDocument.Parse(line); if(c.RootElement.GetProperty("command").GetString()=="STOP") Interlocked.Exchange(ref Stop,1); } } finally { Interlocked.Exchange(ref Stop,1); } }) { IsBackground=true }.Start();
        var host=Path.GetFullPath(args[0]);
        var integrated=Environment.GetEnvironmentVariable("NTE_POOL_PROBE_INTEGRATED")=="1";
        AssemblyLoadContext.Default.Resolving+=(_,n)=>{var p=Path.Combine(host,n.Name+".dll");return File.Exists(p)?AssemblyLoadContext.Default.LoadFromAssemblyPath(p):null;};
        string? failure=null,cleanupFailure=null; int attempts=0,arrivals=0,released=0,dequeued=0,heldMax=0,emptyOld=0,emptyHeld=0,deliveries=0;
        var nonce=(uint)Random.Shared.Next(1,int.MaxValue);
        OwnWindow? window=null; ID3D11Device? device=null; ID3D11DeviceContext? context=null; IDXGISwapChain1? swap=null; Thread? owner=null;
        using var done=new ManualResetEventSlim();
        try
        {
            Check(); window=new(); window.Show(); Application.DoEvents(); var hwnd=window.Handle;
            D3D11.D3D11CreateDevice(0,DriverType.Hardware,DeviceCreationFlags.BgraSupport,new[]{FeatureLevel.Level_11_0},out device,out context).CheckError();
            using var dxgi=device.QueryInterface<IDXGIDevice>(); using var adapter=dxgi.GetAdapter(); using var factory=adapter.GetParent<IDXGIFactory2>();
            swap=factory.CreateSwapChainForHwnd(device,hwnd,new SwapChainDescription1 {Width=640,Height=360,Format=Format.B8G8R8A8_UNorm,SampleDescription=new(1,0),BufferUsage=Usage.RenderTargetOutput,BufferCount=2,Scaling=Scaling.Stretch,SwapEffect=SwapEffect.FlipSequential,AlphaMode=AlphaMode.Ignore});
            void Present()
            {
                Check(); var counter=Interlocked.Increment(ref PresentCounter); var pixels=Enumerable.Repeat((byte)255,640*360*4).ToArray(); ulong code=((ulong)nonce<<16)|(uint)counter;
                for(int bit=0;bit<48;bit++) for(int y=8;y<28;y++) for(int x=8+bit*6;x<12+bit*6;x++){int k=(y*640+x)*4;bool one=(code&(1UL<<bit))!=0;pixels[k]=(byte)(one?0:255);pixels[k+1]=0;pixels[k+2]=(byte)(one?255:0);}
                var before=Clock(); using(var back=swap.GetBuffer<ID3D11Texture2D>(0)) context.UpdateSubresource(pixels,back,0,640*4,0); var submitAfter=Clock(); var hr=swap.Present(1,PresentFlags.None); var after=Clock(); hr.CheckError();
                Emit(new {kind="content-present",counter,nonce,before,submitAfter,after,displayCompletionProven=false});
            }
            Present();
            owner=new Thread(()=>{
                object? capture=null;
                try
                {
                    var assembly=Assembly.LoadFrom(Path.Combine(host,"WgcLiveHarness.dll")); var type=assembly.GetType("WgcLiveHarness.WgcWindowCapture",true)!;
                    capture=type.GetConstructor(new[]{typeof(nint)})!.Invoke(new object[]{hwnd});
                    var pool=(Direct3D11CaptureFramePool)type.GetField("_framePool",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(capture)!;
                    var read=type.GetMethod("ReadBack",BindingFlags.NonPublic|BindingFlags.Instance)!; var map=type.GetMethod("IsClientAreaMappingCurrent")!;
                    pool.FrameArrived+=(_,_)=>{var n=Interlocked.Increment(ref arrivals);Emit(new {kind="frame-arrived-hint",ordinal=n,clock=Clock(),exactFrameAssociationProven=false});};
                    void Valid(){Check();if(GetWindowThreadProcessId(hwnd,out var pid)==0 || pid!=Environment.ProcessId || !(bool)map.Invoke(capture,null)!) throw new Exception("own-window-identity-or-map-invalid");}
                    (int Counter,long Marker) Inspect(Direct3D11CaptureFrame f,int attempt,int take)
                    {
                        var before=Clock();var raw=f.SystemRelativeTime.Ticks;var after=Clock();var p=read.Invoke(capture,new object?[]{f,null})!;
                        T V<T>(string n)=>(T)p.GetType().GetProperty(n)!.GetValue(p)!;
                        var bytes=V<byte[]>("Pixels");var stride=V<int>("Stride");ulong decoded=0;
                        for(int bit=0;bit<48;bit++){int k=18*stride+(10+bit*6)*4;if(bytes[k+2]>200 && bytes[k]<50)decoded|=1UL<<bit;}
                        if((uint)(decoded>>16)!=nonce)throw new Exception("content-not-own-generated-nonce");
                        var counter=(int)(decoded&65535);Emit(new {kind="frame-inspection",attempt,take,before,after,rawSourceTicks=raw,sourceNs=checked(raw*100L),decodedCounter=counter,nonceMatches=true,readbackNs=V<long>("CaptureTimestampNs")});return(counter,checked(raw*100L));
                    }
                    Emit(new {kind="construct",ownHwnd=hwnd.ToInt64(),ownPid=Environment.ProcessId,ownGeneratedOnly=true,buffers=2,nonce,clock=Clock()});
                    Thread.Sleep(180);
                    if(integrated)
                    {
                        var captureDelivered=type.GetMethod("CaptureDelivered")!;
                        for(int iteration=0;iteration<3;iteration++)
                        {
                            Valid(); attempts++; var attempt=attempts; var request=ProtocolClock.NowNs();
                            var session="own-window-retained-qa"; var counterAtRequest=Volatile.Read(ref PresentCounter);
                            Emit(new {kind="boundary-request",attempt,requestNs=request,counterAtRequest,maximumTakes=3,productionSelector=true});
                            object packet;
                            int disposedCalls=0;
                            try { packet=captureDelivered.Invoke(capture,new object[]{1000,request,Deadline,
                                (Func<bool>)(()=>{Valid();return false;}),session,1L})!; }
                            finally
                            {
                                var diagnostic=(string?)type.GetProperty("LastDeliveryDiagnosticJson")!.GetValue(capture);
                                if(diagnostic!=null)
                                {
                                    var recorded=JsonSerializer.Deserialize<JsonElement>(diagnostic);
                                    foreach(var release in recorded.GetProperty("frameReleases").EnumerateArray())
                                    {
                                        if(release.GetProperty("error").ValueKind!=JsonValueKind.Null)throw new Exception("production-release-failed");
                                        disposedCalls++;
                                    }
                                    Emit(new {kind="production-boundary-diagnostic",attempt,diagnostic=recorded,observedDisposeCalls=disposedCalls});
                                }
                            }
                            var ptype=packet.GetType();
                            T V<T>(string n)=>(T)ptype.GetProperty(n)!.GetValue(packet)!;
                            var bytes=V<byte[]>("Pixels"); var stride=V<int>("Stride"); ulong decoded=0;
                            for(int bit=0;bit<48;bit++){int k=18*stride+(10+bit*6)*4;if(bytes[k+2]>200 && bytes[k]<50)decoded|=1UL<<bit;}
                            if((uint)(decoded>>16)!=nonce)throw new Exception("production-content-not-own-generated-nonce");
                            var proof=ptype.GetProperty("DeliveryProof")!.GetValue(packet)!;
                            var proofJson=(System.Text.Json.Nodes.JsonObject)proof.GetType().GetMethod("ToJson")!.Invoke(proof,null)!;
                            if(proofJson["deliveryQualified"]!.GetValue<bool>()!=true
                                || proofJson["boundaryKind"]!.GetValue<string>()!="retained-pool-buffers.v1"
                                || proofJson["releaseCompletedNs"]!.GetValue<long>()>proofJson["dequeueBeforeNs"]!.GetValue<long>())
                                throw new Exception("production-boundary-proof-invalid");
                            var held=proofJson["boundaryHeldCount"]!.GetValue<int>(); heldMax=Math.Max(heldMax,held);
                            // CaptureDelivered owns/disposes all WGC surfaces before returning its private BGRA packet.
                            if(disposedCalls!=held+1)throw new Exception("production-release-count-mismatch");
                            dequeued+=held+1; released+=disposedCalls; emptyHeld++; deliveries++;
                            Emit(new {kind="post-boundary-delivery",attempt,productionSelector=true,deliveryProof=proofJson,
                                decodedCounter=(int)(decoded&65535),counterAtRequest,nonceMatches=true,
                                originAbsoluteAgeProven=false,renderAfterRequestProven=false});
                            Thread.Sleep(80);
                        }
                    }
                    else foreach(var retain in new[]{false,true}) for(int iteration=0;iteration<3;iteration++)
                    {
                        Valid();attempts++;var attempt=attempts;var request=Clock();var counterAtRequest=Volatile.Read(ref PresentCounter);var arrivedAtRequest=Volatile.Read(ref arrivals);var held=new List<Direct3D11CaptureFrame>(2);bool empty=false;long marker=0;
                        Emit(new {kind="boundary-request",attempt,retain,request,counterAtRequest,arrivedAtRequest,maximumTakes=3,controlledGapMs=30});
                        try
                        {
                            for(int take=1;take<=3;take++)
                            {
                                Valid();var before=Clock();var f=pool.TryGetNextFrame();var after=Clock();
                                Emit(new {kind="pool-take",attempt,take,retain,before,after,frameAvailable=f!=null,arrivalsNow=Volatile.Read(ref arrivals),presentCounterNow=Volatile.Read(ref PresentCounter),held=held.Count});
                                if(f==null){empty=true;if(retain)emptyHeld++;else emptyOld++;break;}
                                dequeued++;
                                if(retain) { if(held.Count==2){f.Dispose();released++;throw new Exception("more-than-two-live-pool-frames");} held.Add(f);heldMax=Math.Max(heldMax,held.Count); }
                                try {var (_,m)=Inspect(f,attempt,take);marker=Math.Max(marker,m);}
                                finally {if(!retain){var b=Clock();f.Dispose();released++;Emit(new {kind="release",attempt,take,before=b,after=Clock(),held=false});}}
                                // Deliberately let the independent producer run during consumption.
                                // This tests refill mechanics; it is not a claim about identical game timing.
                                Thread.Sleep(30);
                            }
                            Emit(new {kind="boundary-result",attempt,retain,emptyBoundaryProven=empty,clock=Clock(),highestDiscardMarkerNs=marker});
                        }
                        finally {foreach(var f in held){var b=Clock();f.Dispose();released++;Emit(new {kind="release",attempt,before=b,after=Clock(),held=true});}held.Clear();}
                        if(retain && !empty)throw new Exception("retained-buffer-boundary-unproven");
                        if(retain)
                        {
                            // New dequeue after the retained buffers were returned, still same pool.
                            var releaseCompleted=Clock();Direct3D11CaptureFrame? next=null;var waitDeadline=Math.Min(Deadline,ProtocolClock.NowNs()+1_000_000_000);
                            try
                            {
                                while(next==null){Valid();if(ProtocolClock.NowNs()>=waitDeadline)throw new TimeoutException("post-release-delivery-deadline");next=pool.TryGetNextFrame();if(next==null)Thread.Sleep(1);}
                                dequeued++;var before=Clock();var raw=next.SystemRelativeTime.Ticks;var compared=Clock();var decoded=Inspect(next,attempt,4);var repeat=next.SystemRelativeTime.Ticks;
                                if(raw!=repeat || decoded.Marker<=marker)throw new Exception("post-release-source-not-advancing-or-changed");
                                deliveries++;Emit(new {kind="post-boundary-delivery",attempt,releaseCompleted,dequeueRead=before,compared,rawSourceTicks=raw,sourceFuture=raw*100L>compared.Nanoseconds,decodedCounter=decoded.Counter,counterAtRequest,originAbsoluteAgeProven=false,renderAfterRequestProven=false});
                            }
                            finally{if(next!=null){next.Dispose();released++;}}
                        }
                        Thread.Sleep(80);
                    }
                }
                catch(Exception e){while(e is TargetInvocationException && e.InnerException!=null)e=e.InnerException;failure=e.GetType().Name+":"+e.Message;}
                finally{try{(capture as IDisposable)?.Dispose();}catch(Exception e){cleanupFailure=e.Message;}done.Set();}
            }){IsBackground=true,Name="own-window-WGC-owner"};owner.SetApartmentState(ApartmentState.MTA);owner.Start();
            while(!done.IsSet){Check();Application.DoEvents();Present();}
            owner.Join(500);
        }
        catch(Exception e){failure??=e.GetType().Name+":"+e.Message;Interlocked.Exchange(ref Stop,1);}
        finally
        {
            if(owner is not null && !owner.Join(500))cleanupFailure="owner-exit-unconfirmed";
            try{swap?.Dispose();context?.Dispose();device?.Dispose();window?.Close();window?.Dispose();}catch(Exception e){cleanupFailure??=e.Message;}
        }
        Emit(new {kind="result",attempts,productionSelector=integrated,
            releaseCountsMeaning=integrated?"observed production Dispose calls; acquired count bound to boundary witness":"observed explicit calls",
            emptyImmediateRequests=emptyOld,emptyRetainedRequests=emptyHeld,postBoundaryDeliveries=deliveries,dequeued,released,heldMax,frameArrivals=arrivals,presents=PresentCounter,failure,cleanupFailure,completed=Clock(),gameCapture=false,desktopCapture=false,gameInput=false,productionGateChanged=false});
        return failure==null && cleanupFailure==null && dequeued==released?0:1;
    }
}
