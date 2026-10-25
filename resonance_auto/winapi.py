"""Windows API 래퍼: 프로세스 찾기·종료, 창 찾기·캡처, 마우스 클릭, 포커스.

다른 프로세스의 메모리를 읽거나 쓰지 않는다. 게임 프로세스에는 '종료'(재실행용)만 요청한다.
"""
import ctypes
import ctypes.wintypes as wt
import os
import random
import re
import subprocess
import time

u32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
gdi = ctypes.windll.gdi32

u32.FindWindowW.restype = wt.HWND
u32.GetForegroundWindow.restype = wt.HWND
u32.GetAncestor.restype = wt.HWND
u32.GetWindow.restype = wt.HWND
u32.GetWindow.argtypes = [wt.HWND, wt.UINT]
u32.SetWindowPos.argtypes = [ctypes.c_ssize_t, ctypes.c_ssize_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]  # 두 번째 인자에 -1/-2(맨 위/해제)도 넘김
u32.GetDC.restype = wt.HDC
u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
gdi.CreateCompatibleDC.restype = wt.HDC
gdi.CreateCompatibleDC.argtypes = [wt.HDC]
gdi.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi.SelectObject.restype = wt.HGDIOBJ
gdi.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
gdi.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi.DeleteDC.argtypes = [wt.HDC]
u32.GetDC.argtypes = [wt.HWND]
u32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
u32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
k32.GetTickCount.restype = wt.DWORD
k32.OpenProcess.restype = wt.HANDLE
k32.CreateMutexW.restype = wt.HANDLE
k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
NO_WINDOW = 0x08000000           # CREATE_NO_WINDOW: 보조 명령(tasklist 등)에 콘솔 창을 띄우지 않음
SYSTEM32 = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')


def system_exe(name):
    """Windows 기본 프로그램은 전체 경로로 실행(현재 폴더의 같은 이름 파일이 대신 실행되지 않게)."""
    return os.path.join(SYSTEM32, name)


def single_instance(name):
    """이름 있는 뮤텍스로 한 번에 하나만 실행. 이미 있으면 None, 아니면 핸들(프로세스가 끝날 때까지 유지)."""
    h = k32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == 183:          # ERROR_ALREADY_EXISTS
        k32.CloseHandle(h)
        return None
    return h


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                ('th32DefaultHeapID', ctypes.c_void_p), ('th32ModuleID', wt.DWORD),
                ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD),
                ('pcPriClassBase', ctypes.c_long), ('dwFlags', wt.DWORD),
                ('szExeFile', ctypes.c_wchar * 260)]


k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


def dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def find_pid(name):
    """실행 파일 이름으로 프로세스 ID 찾기(프로세스 목록만 조회)."""
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)       # TH32CS_SNAPPROCESS
    if not snap or snap == wt.HANDLE(-1).value:
        return None
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() == name.lower():
                return e.th32ProcessID
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return None


def process_alive(pid):
    h = k32.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = wt.DWORD()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == 259                           # STILL_ACTIVE


def terminate(pid, wait=15):
    h = k32.OpenProcess(0x0001 | 0x00100000, False, pid)   # PROCESS_TERMINATE | SYNCHRONIZE
    if not h:
        return False
    k32.TerminateProcess(h, 1)
    k32.WaitForSingleObject(h, int(wait * 1000))
    k32.CloseHandle(h)
    return True


def process_path(pid):
    h = k32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(len(buf))
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ''
    finally:
        k32.CloseHandle(h)


def image_pids(image, under=None):
    """이름이 image인 프로세스 ID. under를 주면 그 폴더 아래에서 실행된 것만."""
    r = subprocess.run([system_exe('tasklist.exe'), '/fi', f'imagename eq {image}', '/fo', 'csv', '/nh'],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    pids = {int(m) for m in re.findall(r'^"[^"]*","(\d+)"', r.stdout, re.M)}
    if under:
        root = os.path.normcase(os.path.abspath(under))
        pids = {p for p in pids if os.path.normcase(process_path(p)).startswith(root)}
    return pids


def kill_image(image, under=None):
    """같은 이름(그리고 under 폴더 아래)의 프로세스를 끄고, 더 줄지 않을 때까지만 기다린다."""
    pids = image_pids(image, under)
    if not pids:
        return False
    for p in pids:
        terminate(p, wait=2)
    end = time.time() + 5
    prev, same = None, 0
    while time.time() < end:
        cur = image_pids(image, under)
        if not cur:
            break
        same = same + 1 if cur == prev else 0
        if same >= 2:
            break
        prev = cur
        time.sleep(0.2)
    return True


def main_window(pid):
    """프로세스의 보이는 큰 창 하나."""
    found = []

    def cb(hwnd, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            r = wt.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(r))
            if r.right > 300 and r.bottom > 200:
                found.append(hwnd)
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def window_rect(hwnd):
    r = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def rect_on_screen(x, y, w, h):
    """그 영역이 지금 연결된 모니터 위에 있는지(모니터 구성이 바뀌었으면 False)."""
    r = wt.RECT(x, y, x + w, y + h)
    return bool(u32.MonitorFromRect(ctypes.byref(r), 0))      # MONITOR_DEFAULTTONULL


def move_window(hwnd, x, y, w, h):
    u32.SetWindowPos(hwnd, 0, x, y, w, h, 0x0010 | 0x0004)      # NOACTIVATE | NOZORDER


def set_topmost(hwnd, on):
    u32.SetWindowPos(hwnd, -1 if on else -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(200)
    u32.GetWindowTextW(hwnd, buf, 200)
    return buf.value


def focus(hwnd):
    """키 입력 흉내 없이 포커스만 옮긴다(앞 창의 입력 큐에 잠깐 붙어서 SetForegroundWindow).
    넘어왔는지 확인하고 안 됐으면 몇 번 더 한다. 넘어오면 앞에 있던 게임이 걸어 둔 커서 가둠(ClipCursor)을 푼다
    (FPS 게임처럼 커서를 숨기고 가두는 창이 앞에 있어도 클릭할 수 있게). 앞 창이 관리자 권한으로 실행 중이면
    Windows 보안 때문에 이 프로그램도 관리자 권한이어야 넘어온다. 넘어왔으면 True."""
    for _ in range(5):
        fg = u32.GetForegroundWindow()
        if fg == hwnd:
            break
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, 9)                 # SW_RESTORE
        a = u32.GetWindowThreadProcessId(fg, None)
        b = k32.GetCurrentThreadId()
        if a and a != b:
            u32.AttachThreadInput(b, a, True)
        u32.BringWindowToTop(hwnd)
        u32.SetForegroundWindow(hwnd)
        if a and a != b:
            u32.AttachThreadInput(b, a, False)
        time.sleep(0.2)
    ok = u32.GetForegroundWindow() == hwnd
    if ok:
        u32.ClipCursor(None)
    return ok


def capture(hwnd):
    """게임 창 안쪽(클라이언트 영역) 이미지. 다른 창에 가려져 있어도 캡처된다."""
    from PIL import Image
    r = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right, r.bottom
    hdc = u32.GetDC(hwnd)
    mdc = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
    gdi.SelectObject(mdc, bmp)
    u32.PrintWindow(hwnd, mdc, 3)        # PW_CLIENTONLY | PW_RENDERFULLCONTENT

    class BIH(ctypes.Structure):
        _fields_ = [('biSize', wt.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                    ('biPlanes', wt.WORD), ('biBitCount', wt.WORD), ('biCompression', wt.DWORD),
                    ('biSizeImage', wt.DWORD), ('x', ctypes.c_long), ('y', ctypes.c_long),
                    ('used', wt.DWORD), ('imp', wt.DWORD)]
    bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')


def click_screen(hwnd, x, y, press=0.15):
    """게임 창을 맨 위·포커스로 두고 실제 마우스로 한 번 누른다(백그라운드 메시지는 게임이 무시함).
    포커스를 옮겼으면 True. 못 옮겼으면 앞 창 제목을 담아 False와 함께 돌려준다."""
    set_topmost(hwnd, True)
    ok = focus(hwnd)
    blocker = '' if ok else window_title(u32.GetForegroundWindow())
    time.sleep(0.15)
    for _ in range(3):                      # 커서가 다른 게임에 갇혀 있으면 풀고 다시 옮김
        u32.ClipCursor(None)
        u32.SetCursorPos(x, y)
        time.sleep(0.05)
        pt = wt.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        if (pt.x, pt.y) == (x, y):
            break
        focus(hwnd)
    time.sleep(0.05)
    u32.mouse_event(0x0002, 0, 0, 0, 0)     # LEFTDOWN
    time.sleep(press + random.uniform(-0.03, 0.03))
    u32.mouse_event(0x0004, 0, 0, 0, 0)     # LEFTUP
    return ok, blocker


def client_to_screen(hwnd, x, y):
    pt = wt.POINT(x, y)
    u32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.UINT), ('dwTime', wt.DWORD)]


def idle_seconds():
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    u32.GetLastInputInfo(ctypes.byref(li))
    return ((k32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0


# 화면 보호기(설정에서 켰을 때만 사용)
def screensaver_running():
    on = wt.BOOL()
    u32.SystemParametersInfoW(0x0072, 0, ctypes.byref(on), 0)   # SPI_GETSCREENSAVERRUNNING
    return bool(on.value)


def hold_screen(on):
    """재실행하는 동안만 화면 보호기·화면 꺼짐을 막는다(설정 파일에는 저장하지 않음)."""
    u32.SystemParametersInfoW(0x0011, 0 if on else 1, None, 0)  # SPI_SETSCREENSAVEACTIVE
    k32.SetThreadExecutionState(0x80000000 | (0x00000003 if on else 0))
