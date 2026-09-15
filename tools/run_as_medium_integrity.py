import ctypes, sys, os
import ctypes.wintypes as wintypes

advapi32 = ctypes.windll.advapi32
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_ALL_ACCESS = 0xF01FF

SECURITY_MANDATORY_UNTRUSTED_RID = 0x00000000
SECURITY_MANDATORY_LOW_RID = 0x00001000
SECURITY_MANDATORY_MEDIUM_RID = 0x00002000
SECURITY_MANDATORY_HIGH_RID = 0x00003000

class SID_IDENTIFIER_AUTHORITY(ctypes.Structure):
    _fields_ = [("Value", ctypes.c_byte * 6)]

class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", wintypes.DWORD),
    ]

class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [
        ("Label", SID_AND_ATTRIBUTES),
    ]

class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('lpReserved', wintypes.LPWSTR),
        ('lpDesktop', wintypes.LPWSTR),
        ('lpTitle', wintypes.LPWSTR),
        ('dwX', wintypes.DWORD),
        ('dwY', wintypes.DWORD),
        ('dwXSize', wintypes.DWORD),
        ('dwYSize', wintypes.DWORD),
        ('dwXCountChars', wintypes.DWORD),
        ('dwYCountChars', wintypes.DWORD),
        ('dwFillAttribute', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('wShowWindow', wintypes.WORD),
        ('cbReserved2', wintypes.WORD),
        ('lpReserved2', ctypes.POINTER(wintypes.BYTE)),
        ('hStdInput', wintypes.HANDLE),
        ('hStdOutput', wintypes.HANDLE),
        ('hStdError', wintypes.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('hProcess', wintypes.HANDLE),
        ('hThread', wintypes.HANDLE),
        ('dwProcessId', wintypes.DWORD),
        ('dwThreadId', wintypes.DWORD),
    ]

def launch_medium_integrity(cmd_line):
    # Try getting token from Shell Window (Explorer.exe) which is native Medium Integrity
    hwnd_shell = user32.GetShellWindow()
    h_token_medium = wintypes.HANDLE()
    
    if hwnd_shell:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd_shell, ctypes.byref(pid))
        h_proc = kernel32.OpenProcess(0x0400 | 0x0008, False, pid) # PROCESS_QUERY_INFORMATION
        if h_proc:
            h_token_exp = wintypes.HANDLE()
            if advapi32.OpenProcessToken(h_proc, TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ASSIGN_PRIMARY, ctypes.byref(h_token_exp)):
                advapi32.DuplicateTokenEx(h_token_exp, TOKEN_ALL_ACCESS, None, 2, 1, ctypes.byref(h_token_medium))
                kernel32.CloseHandle(h_token_exp)
            kernel32.CloseHandle(h_proc)
            
    if not h_token_medium.value:
        # Fallback: duplicate current token and lower integrity level to Medium
        h_token_curr = wintypes.HANDLE()
        advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT | TOKEN_ASSIGN_PRIMARY, ctypes.byref(h_token_curr))
        advapi32.DuplicateTokenEx(h_token_curr, TOKEN_ALL_ACCESS, None, 2, 1, ctypes.byref(h_token_medium))
        kernel32.CloseHandle(h_token_curr)
        
        # Set Medium integrity SID
        sid_auth = SID_IDENTIFIER_AUTHORITY((ctypes.c_byte * 6)(0,0,0,0,0,16)) # SECURITY_MANDATORY_LABEL_AUTHORITY
        p_sid = ctypes.c_void_p()
        advapi32.AllocateAndInitializeSid(ctypes.byref(sid_auth), 1, SECURITY_MANDATORY_MEDIUM_RID, 0,0,0,0,0,0,0, ctypes.byref(p_sid))
        
        tml = TOKEN_MANDATORY_LABEL()
        tml.Label.Attributes = 0x00000020 # SE_GROUP_INTEGRITY
        tml.Label.Sid = p_sid
        
        advapi32.SetTokenInformation(h_token_medium, 25, ctypes.byref(tml), ctypes.sizeof(tml))
        advapi32.FreeSid(p_sid)

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    pi = PROCESS_INFORMATION()
    
    # Create process with token
    res = advapi32.CreateProcessWithTokenW(
        h_token_medium,
        0, # LOGON_WITH_PROFILE
        None,
        cmd_line,
        0,
        None,
        None,
        ctypes.byref(si),
        ctypes.byref(pi)
    )
    
    if not res:
        err = kernel32.GetLastError()
        print(f"CreateProcessWithTokenW failed with error code: {err}")
        return None
        
    kernel32.WaitForSingleObject(pi.hProcess, 0xFFFFFFFF)
    kernel32.CloseHandle(pi.hProcess)
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(h_token_medium)
    print("Medium integrity process completed.")

if __name__ == "__main__":
    cmd = f'"{sys.executable}" D:\\yihuanpaimai\\tools\\benchmark_harness.py None ExpA_MediumIntegrity'
    launch_medium_integrity(cmd)
