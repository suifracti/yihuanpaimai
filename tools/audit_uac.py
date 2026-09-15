import ctypes, winreg, os, subprocess
import ctypes.wintypes as wintypes

advapi32 = ctypes.windll.advapi32
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# 1. Check user and SID
def check_user():
    token = wintypes.HANDLE()
    advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token))
    length = wintypes.DWORD()
    advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(length)) # 1 = TokenUser
    buf = ctypes.create_string_buffer(length.value)
    advapi32.GetTokenInformation(token, 1, buf, length.value, ctypes.byref(length))
    p_sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
    
    sub_auth_count = advapi32.GetSidSubAuthorityCount(p_sid)
    count = ctypes.cast(sub_auth_count, ctypes.POINTER(ctypes.c_ubyte)).contents.value
    get_sub = advapi32.GetSidSubAuthority
    get_sub.restype = ctypes.POINTER(wintypes.DWORD)
    rid = get_sub(p_sid, count - 1).contents.value
    
    # String SID
    p_str_sid = wintypes.LPWSTR()
    advapi32.ConvertSidToStringSidW(p_sid, ctypes.byref(p_str_sid))
    str_sid = p_str_sid.value
    kernel32.LocalFree(p_str_sid)
    kernel32.CloseHandle(token)
    return str_sid, rid, (rid == 500)

# 2. Check Explorer processes
def check_explorer():
    try:
        out = subprocess.check_output('powershell -NoProfile -Command "(Get-Process explorer).Id"', shell=True, text=True)
        pids = [int(p.strip()) for p in out.splitlines() if p.strip().isdigit()]
        results = []
        for pid in pids:
            h_proc = kernel32.OpenProcess(0x0400 | 0x0008, False, pid)
            if h_proc:
                token = wintypes.HANDLE()
                if advapi32.OpenProcessToken(h_proc, 0x0008, ctypes.byref(token)):
                    length = wintypes.DWORD()
                    advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(length))
                    buf = ctypes.create_string_buffer(length.value)
                    if advapi32.GetTokenInformation(token, 25, buf, length.value, ctypes.byref(length)):
                        p_sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
                        sub_auth_count = advapi32.GetSidSubAuthorityCount(p_sid)
                        count = ctypes.cast(sub_auth_count, ctypes.POINTER(ctypes.c_ubyte)).contents.value
                        get_sub = advapi32.GetSidSubAuthority
                        get_sub.restype = ctypes.POINTER(wintypes.DWORD)
                        level = get_sub(p_sid, count - 1).contents.value
                        results.append((pid, hex(level), "High" if level == 0x3000 else "Medium" if level == 0x2000 else str(level)))
                    kernel32.CloseHandle(token)
                kernel32.CloseHandle(h_proc)
        return results
    except Exception as e:
        return str(e)

# 3. Check UAC Registry
def check_uac_reg():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System") as k:
            def q(name):
                try:
                    return winreg.QueryValueEx(k, name)[0]
                except Exception:
                    return "Not Found"
            return {
                "EnableLUA": q("EnableLUA"),
                "ConsentPromptBehaviorAdmin": q("ConsentPromptBehaviorAdmin"),
                "FilterAdministratorToken": q("FilterAdministratorToken"),
            }
    except Exception as e:
        return str(e)

# 4. Check Linked Token
def check_linked_token():
    token = wintypes.HANDLE()
    if advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        linked = wintypes.HANDLE()
        length = wintypes.DWORD()
        res = advapi32.GetTokenInformation(token, 19, ctypes.byref(linked), ctypes.sizeof(linked), ctypes.byref(length))
        kernel32.CloseHandle(token)
        if res and linked.value:
            advapi32.GetTokenInformation(linked, 25, None, 0, ctypes.byref(length))
            buf = ctypes.create_string_buffer(length.value)
            advapi32.GetTokenInformation(linked, 25, buf, length.value, ctypes.byref(length))
            p_sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            sub_auth_count = advapi32.GetSidSubAuthorityCount(p_sid)
            count = ctypes.cast(sub_auth_count, ctypes.POINTER(ctypes.c_ubyte)).contents.value
            get_sub = advapi32.GetSidSubAuthority
            get_sub.restype = ctypes.POINTER(wintypes.DWORD)
            level = get_sub(p_sid, count - 1).contents.value
            kernel32.CloseHandle(linked)
            return True, hex(level)
        return False, None
    return False, None

sid, rid, is_admin_500 = check_user()
explorers = check_explorer()
uac = check_uac_reg()
has_linked, linked_lvl = check_linked_token()

print("=== WINDOWS PRIVILEGE & UAC AUDIT ===")
print(f"User SID: {sid}")
print(f"User RID: {rid} -> Built-in Administrator (RID 500): {is_admin_500}")
print(f"Explorer Process Levels: {explorers}")
print(f"UAC Registry Policies: {uac}")
print(f"Has Linked Medium Token: {has_linked}, Linked Level: {linked_lvl}")
