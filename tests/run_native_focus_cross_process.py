"""Windows opt-in integration check: actual Host activation, two owned processes.

No game window, capture, keyboard or mouse input. Run only outside live automation.
Pass an output JSON path under build/; build the three existing .NET projects first.
"""
import subprocess,json,pathlib,sys
root=pathlib.Path(__file__).resolve().parents[1]
harness=root/'architecture/v2/host/window_monitor_harness/bin/Release/net8.0/WindowMonitorHarness.exe'
check=root/'tests/native_preparation_confirmation/bin/Debug/net8.0-windows10.0.19041.0/confirmation.exe'
host=root/'architecture/v2/host/wgc_live_harness/bin/Release/net8.0-windows10.0.19041.0/WgcLiveHarness.dll'
processes=[]; results=[]
try:
    for _ in range(2):
        p=subprocess.Popen([str(harness),'--mode','serve','--grab-foreground'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        processes.append(p)
        ready=json.loads(p.stdout.readline())
        if len(processes)==1: target=ready['windows']['0']
    for i in range(12):
        p.stdin.write('fg 1\n');p.stdin.flush()
        foreground=json.loads(p.stdout.readline())
        r=subprocess.run([str(check),'--host',str(host),'--controlled-focus',str(target)],capture_output=True,text=True,timeout=8)
        results.append(dict(index=i,foreground=foreground,exit=r.returncode,stdout=r.stdout,stderr=r.stderr))
finally:
    for p in processes:
        p.stdin.write('exit\n');p.stdin.flush();p.wait(timeout=5)
out=pathlib.Path(sys.argv[1]);out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(total=len(results),passed=sum(r['exit']==0 for r in results),evidence=str(out))))
sys.exit(0 if len(results)==12 and all(r['exit']==0 for r in results) else 1)
