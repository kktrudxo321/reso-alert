"""재실행 1분 전 알림.

재실행 2분 전~1분 전 사이에 키보드·마우스 입력이 있었으면(PC를 쓰는 중) 게임 창 오른쪽 아래에 알림을 띄운다.
[5분 미루기] [다음 주문 확인] [다음 날] [반복 중지]. 아무것도 안 누르면 정해진 시각에 진행.
알림은 포커스를 가져가지 않는다. 입력이 없었으면 알림 없이 진행.
"""
import ctypes
import ctypes.wintypes as wt
import math
import os
import struct
import subprocess
import sys
import time
import wave
from datetime import datetime

from . import config, ctl, winapi as W

DELAY = 5 * 60


def gate(run_at, cfg, log):
    """run_at 1분 전까지 기다렸다가 필요하면 알림. 새 실행 시각(초) / None(반복 중지)."""
    if not cfg.get('notify_before_restart', True) or run_at - time.time() < 55:
        return run_at
    note = ''
    while True:
        check = run_at - 60
        while time.time() < check:
            if os.path.exists(config.STOP) or ctl.pending():
                return run_at                   # 중지·배지 명령은 반복 쪽이 처리
            ctl.beat(run_at)
            time.sleep(min(5, max(0.2, check - time.time())))
        if W.idle_seconds() >= 60:
            return run_at
        log(f'재실행 1분 전 PC 사용 중 → 알림 ({datetime.fromtimestamp(run_at):%H:%M:%S} 예정)')
        out = os.path.join(config.TMP_DIR, 'notify_choice.txt')
        if os.path.exists(out):
            os.remove(out)
        exe = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        try:
            subprocess.run([exe if os.path.exists(exe) else sys.executable, '-m', 'resonance_auto', 'popup',
                            str(run_at), out, note], timeout=180, cwd=_pkg_parent())
        except (OSError, subprocess.TimeoutExpired):
            pass                                 # 알림 창이 멈추거나 못 뜨면 예정대로 진행
        note = ''
        try:
            with open(out) as f:
                choice = f.read().strip() or 'run'
        except OSError:
            choice = 'run'
        if choice == 'delay':
            run_at = ctl.cap_at_5am(run_at + DELAY)
            log(f'알림: 5분 미루기 → {datetime.fromtimestamp(run_at):%H:%M:%S}')
            continue
        if choice == 'check':
            from .game import check_order
            at = check_order(cfg)
            if at:
                run_at = ctl.cap_at_5am(at.timestamp() + 30 + (time.time() % 30))
                log(f'알림: 다음 주문 확인 → {datetime.fromtimestamp(run_at):%H:%M:%S}')
            else:
                note = '구매 화면이 아니거나 구매 중인 주문을 못 찾았어요. 구매 화면을 열고 다시 눌러 주세요.'
            continue
        if choice == 'nextday':
            from .game import next_5am
            run_at = next_5am()
            log(f'알림: 다음 날 → {datetime.fromtimestamp(run_at):%m-%d %H:%M}')
            continue
        if choice == 'stop':
            log('알림: 반복 중지')
            return None
        return run_at


def _pkg_parent():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def game_rect(cfg):
    from .game import Game
    h = Game(cfg).hwnd()
    if h:
        return W.window_rect(h)
    r = cfg.get('window_rect')
    if r:
        return r[0], r[1], r[0] + r[2], r[1] + r[3]
    u = W.u32
    return 0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1)


POP = os.path.join(config.TMP_DIR, 'pop.wav')


def play_pop():
    import winsound
    if not os.path.exists(POP):
        rate, n = 44100, int(44100 * 0.07)
        frames, ph = bytearray(), 0.0
        for i in range(n):
            t = i / n
            ph += 2 * math.pi * (700 + 900 * t) / rate
            env = min(1.0, i / 120) * (1 - t) ** 2
            frames += struct.pack('<h', int(32767 * 0.18 * env * math.sin(ph)))
        with wave.open(POP, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
    try:
        winsound.PlaySound(POP, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


def popup(run_at, out, note=''):
    """알림 창 하나를 띄우고 고른 것(run/delay/check/nextday/stop)을 out 파일에 남긴다."""
    import tkinter as tk
    W.dpi_aware()
    cfg = config.load()
    root = tk.Tk()
    root.withdraw()
    root.title('레조넌스 재실행')
    root.attributes('-topmost', True)
    root.resizable(False, False)
    choice = {'v': 'run'}
    bg, fg, accent = '#1c2322', '#e4e9e6', '#6fb3b6'
    root.configure(bg=bg, padx=18, pady=14)
    tk.Label(root, text='곧 레조넌스를 재실행해요', bg=bg, fg=fg, font=('Malgun Gothic', 12, 'bold')).pack(anchor='w')
    msg = tk.Label(root, text='', bg=bg, fg=accent, font=('Malgun Gothic', 11))
    msg.pack(anchor='w', pady=(4, 10))
    if note:
        tk.Label(root, text=note, bg=bg, fg='#e0857b', font=('Malgun Gothic', 9), wraplength=360,
                 justify='left').pack(anchor='w', pady=(0, 6))
    tk.Label(root, text='게임이 꺼졌다 다시 켜져요. 아무것도 누르지 않으면 정해진 시각에 진행해요.',
             bg=bg, fg=fg, font=('Malgun Gothic', 9), wraplength=360, justify='left').pack(anchor='w', pady=(0, 12))
    row = tk.Frame(root, bg=bg)
    row.pack(anchor='w')

    def pick(v):
        choice['v'] = v
        root.destroy()

    for label, v in [('5분 미루기', 'delay'), ('다음 주문 확인', 'check'), ('다음 날', 'nextday'), ('반복 중지', 'stop')]:
        tk.Button(row, text=label, command=lambda v=v: pick(v), font=('Malgun Gothic', 9), bg='#2f3936', fg=fg,
                  activebackground=accent, relief='flat', padx=10, pady=4).pack(side='left', padx=(0, 6))

    def tick():
        left = run_at - time.time()
        if left <= 0:
            root.destroy()
            return
        msg.config(text=f'{datetime.fromtimestamp(run_at):%H:%M:%S} 재실행 · {int(left)}초 남음')
        W.u32.SetWindowPos(int(root.wm_frame(), 16), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        root.after(500, tick)

    root.update_idletasks()
    hwnd = int(root.wm_frame(), 16)
    W.u32.SetWindowLongW(hwnd, -20, W.u32.GetWindowLongW(hwnd, -20) | 0x08000000 | 0x00000008 | 0x00000080)
    W.u32.ShowWindow(hwnd, 0)                                   # 첫 ShowWindow는 활성화될 수 있어 숨김으로 먼저 씀
    W.u32.ShowWindow(hwnd, 4)                                   # 포커스 없이 표시
    l, t, r, b = game_rect(cfg)
    rc = wt.RECT()
    W.u32.GetWindowRect(hwnd, ctypes.byref(rc))
    W.u32.SetWindowPos(hwnd, -1, r - (rc.right - rc.left) - 16, b - (rc.bottom - rc.top) - 16, 0, 0, 0x0001 | 0x0010)
    root.state('normal')
    play_pop()
    tick()
    root.mainloop()
    with open(out, 'w') as f:
        f.write(choice['v'])
