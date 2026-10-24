"""레조넌스 창 위 타이머 배지.

레조넌스가 켜져 있을 때만 게임 창 바로 위 층에 붙어 보인다(다른 창이 게임을 가리면 배지도 가려지고,
게임을 최소화·종료하면 같이 사라짐). 포커스를 가져가지 않는다. 재접속 중에도 '재실행 중'으로 보이고,
배지가 누르는 자리와 겹치면 그동안만 게임 화면 가운데 맨 위로 비켜 뒀다가 끝나면 원래 자리로 돌아간다.
- 클릭: 메뉴(지금 실행 / 미루기 / 다음 주문 확인 / 다음 날 05시 / 시각 지정 / '알림 시점에 재실행' 켜고 끄기 / 반복 중지·시작)
- 드래그: 위치를 게임 창 가장자리 기준(px)으로 기억 → 창을 옮기거나 크기를 바꿔도 같은 자리
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta

from . import __version__, config, ctl, screens as S, winapi as W

# 재접속 때 누르는 자리. 배지가 이 근처에 있으면 재접속 동안만 게임 화면 가운데 맨 위로 비켜 둔다.
CLICK_POINTS = [S.CENTER, S.TAP, S.GOOGLE_ACCOUNT, S.GOOGLE_CONTINUE, S.DOWNLOAD_OK, S.PROFILE_ICON,
                S.MENU_REFORM, S.CENTER_BUY, S.BULK_BTN, S.BLANK, S.BACK_BTN]
CLICK_RADIUS = 40

BG, FG, MUTED, ACCENT, BUSY, OFF, WARN = '#1c2322', '#e4e9e6', '#9aa5a0', '#6fb3b6', '#d8ad52', '#7d8783', '#e0857b'
FONT = 'Malgun Gothic'


class Badge:
    def __init__(self):
        W.dpi_aware()
        self.cfg = config.load()
        self.root = r = tk.Tk()
        r.overrideredirect(True)
        r.configure(bg=BG)
        r.withdraw()
        self.label = tk.Label(r, text='', bg=BG, fg=FG, font=(FONT, 10, 'bold'), padx=10, pady=3,
                              highlightthickness=1, highlightbackground=ACCENT, cursor='hand2')
        self.label.pack()
        self.label.bind('<ButtonPress-1>', self.press)
        self.label.bind('<B1-Motion>', self.drag)
        self.label.bind('<ButtonRelease-1>', self.release)
        self.label.bind('<Button-3>', lambda e: self.menu())
        r.update_idletasks()
        self.me = W.u32.GetAncestor(self.label.winfo_id(), 2)
        W.u32.SetWindowLongW(self.me, -20, W.u32.GetWindowLongW(self.me, -20) | 0x08000000 | 0x00000080)
        # 프로세스의 첫 ShowWindow 호출은 지정한 방식을 무시하고 창을 활성화할 수 있음 → 숨김으로 한 번 써 둠
        W.u32.ShowWindow(self.me, 0)
        self.game = None
        self.shown = False
        self.dragging = None
        self.last_text = 0
        self.busy = False
        self.pos = self.load_pos()
        self.tick()

    def load_pos(self):
        try:
            with open(config.BADGE_POS) as f:
                d = json.load(f)
            return d['right'], d['top']
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def game_hwnd(self):
        image = os.path.basename(self.cfg.get('game_exe') or '') or config.DEFAULT_GAME_EXE_NAME
        pid = W.find_pid(image)
        return W.main_window(pid) if pid else None

    def text(self):
        st = ctl.status()
        if not st:
            return '⏱ 재실행 꺼짐', OFF
        if st.get('note') == '재실행 중':
            return '⏱ 재실행 중', BUSY
        if st.get('note') == '구매 확인 필요':
            return '🔔 구매 확인 필요', BUSY
        icon = '⏱' if self.cfg_relaunch() else '🔔'            # 🔔 = 재실행 끔(구매 완료 알림만)
        nr = datetime.fromtimestamp(st['next_run'])
        sec = max(0, int(st['next_run'] - time.time()))
        left = f'{sec // 3600}:{sec % 3600 // 60:02d}' if sec >= 3600 else f'{sec // 60}분'
        day = '' if nr.date() == datetime.now().date() else f' ({nr:%m/%d})'
        return f'{icon} {nr:%H:%M}{day} · {left}', ACCENT

    def client_box(self, g):
        r = W.wt.RECT()
        W.u32.GetClientRect(g, W.ctypes.byref(r))
        x, y = W.client_to_screen(g, 0, 0)
        return x, y, x + r.right, y + r.bottom

    def blocks_click(self, g, x, y, w, h):
        cl, ct, cr, cb = self.client_box(g)
        sx, sy = (cr - cl) / S.CW, (cb - ct) / S.CH
        pad = CLICK_RADIUS * sx
        return any(x - pad <= cl + px * sx <= x + w + pad and y - pad <= ct + py * sy <= y + h + pad
                   for px, py in CLICK_POINTS)

    def place(self, g):
        l, t, r, b = W.window_rect(g)
        ml, mt, mr, mb = W.window_rect(self.me)
        w, h = mr - ml, mb - mt
        right, top = self.pos if self.pos else ((r - l) * 0.44, (b - t) * 0.075)
        x, y = int(r - right - w / 2), int(t + top)
        if self.busy and self.blocks_click(g, x, y, w, h):
            cl, ct, cr, cb = self.client_box(g)
            x, y = int((cl + cr - w) / 2), ct + 4
        if (x, y) != (ml, mt):
            W.u32.SetWindowPos(self.me, 0, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)

    def keep_above(self, g):
        """게임 창 바로 위 층에 둔다(다른 창이 게임을 가리면 배지도 가려짐). 게임 창을 '소유자'로 지정하는 방식은
        지정하는 순간 배지가 포커스를 가져가서 쓰지 않음. 재접속 중 게임이 '항상 위'가 되면 배지도 따라 올림."""
        flags = 0x0001 | 0x0002 | 0x0010
        game_top = bool(W.u32.GetWindowLongW(g, -20) & 0x8)
        me_top = bool(W.u32.GetWindowLongW(self.me, -20) & 0x8)
        if game_top:
            if not me_top or W.u32.GetWindow(g, 3) != self.me:
                W.u32.SetWindowPos(self.me, -1, 0, 0, 0, 0, flags)
            return
        if me_top:
            W.u32.SetWindowPos(self.me, -2, 0, 0, 0, 0, flags)
        above = W.u32.GetWindow(g, 3)
        if above != self.me:
            W.u32.SetWindowPos(self.me, above or 0, 0, 0, 0, 0, flags)

    def tick(self):
        try:
            g = self.game if (self.game and W.u32.IsWindow(self.game)) else self.game_hwnd()
            self.game = g
            st = ctl.status() if time.time() - self.last_text >= 1 else None
            if st is not None:
                self.busy = st.get('note') == '재실행 중'
            if g and W.u32.IsWindowVisible(g) and not W.u32.IsIconic(g):
                if time.time() - self.last_text >= 1:
                    txt, color = self.text()
                    self.label.config(text=txt, fg=color, highlightbackground=color)
                    self.last_text = time.time()
                if not self.shown:
                    W.u32.ShowWindow(self.me, 4)        # SW_SHOWNOACTIVATE
                    self.shown = True
                self.keep_above(g)
                if not self.dragging:
                    self.place(g)
            elif self.shown:
                W.u32.ShowWindow(self.me, 0)
                self.shown = False
        except Exception:
            pass
        self.root.after(100, self.tick)

    def press(self, e):
        l, t, _, _ = W.window_rect(self.me)
        self.dragging = (e.x_root, e.y_root, l, t, False)

    def drag(self, e):
        if not self.dragging:
            return
        x0, y0, wx, wy, moved = self.dragging
        dx, dy = e.x_root - x0, e.y_root - y0
        if moved or abs(dx) + abs(dy) > 4:
            self.dragging = (x0, y0, wx, wy, True)
            W.u32.SetWindowPos(self.me, 0, wx + dx, wy + dy, 0, 0, 0x0001 | 0x0004 | 0x0010)

    def release(self, e):
        d, self.dragging = self.dragging, None
        if not d:
            return
        if not d[4]:
            self.menu()
            return
        if self.game:
            l, t, r, b = W.window_rect(self.game)
            ml, mt, mr, mb = W.window_rect(self.me)
            self.pos = (r - (ml + mr) / 2, mt - t)
            try:
                with open(config.BADGE_POS, 'w') as f:
                    json.dump({'right': self.pos[0], 'top': self.pos[1]}, f)
            except OSError:
                pass

    def start(self, *args):
        exe = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        subprocess.Popen([exe if os.path.exists(exe) else sys.executable, '-m', 'resonance_auto', *args],
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), creationflags=0x00000008)

    def menu(self):
        st = ctl.status()
        m = tk.Menu(self.root, tearoff=0, font=(FONT, 9))
        txt, _ = self.text()
        m.add_command(label=(st.get('mode', '') + ' · ' if st else '') + txt.replace('⏱ ', '').replace('🔔 ', '알림 '),
                      state='disabled')
        m.add_separator()
        if st:
            on = self.cfg_relaunch()
            m.add_command(label='지금 실행' if on else '지금 알림', command=lambda: ctl.send('now'))
            m.add_command(label='5분 미루기', command=lambda: ctl.send('delay', 300))
            m.add_command(label='30분 미루기', command=lambda: ctl.send('delay', 1800))
            m.add_command(label='다음 주문 확인', command=lambda: ctl.send('check'))
            m.add_command(label='다음 날 05시', command=lambda: ctl.send('nextday'))
            m.add_command(label='시각 지정…', command=self.ask_time)
            m.add_separator()
            self.relaunch_var = tk.BooleanVar(value=on)
            m.add_checkbutton(label='알림 시점에 재실행', variable=self.relaunch_var,
                              command=lambda: config.set_value('relaunch', bool(self.relaunch_var.get())))
            m.add_command(label='반복 중지', command=lambda: ctl.send('stop'))
        else:
            m.add_command(label='구매 시각 반복 시작', command=lambda: self.start('start'))
            m.add_command(label='31분 반복 시작', command=lambda: self.start('start', '--interval', '31'))
        m.add_separator()
        m.add_command(label='기록 열기', command=lambda: os.startfile(config.LOG) if os.path.exists(config.LOG) else None)
        m.add_command(label=f'업데이트 확인 (지금 v{__version__})', command=self.update)
        m.add_command(label='배지 위치 처음으로', command=self.reset_pos)
        m.add_separator()
        m.add_command(label='프로그램 종료', command=self.quit_all)
        ml, mt, mr, mb = W.window_rect(self.me)
        self.popup_menu(m, ml, mb)

    def popup_menu(self, m, x, y):
        """메뉴를 띄우는 동안만 배지를 활성 창으로 만든다. Windows 팝업 메뉴는 주인 창이 활성 창이어야
        바깥을 누르거나 다른 창을 쓰면 닫힌다(배지는 평소 포커스를 안 가져가는 창이라 그대로면 안 닫힘)."""
        ex = W.u32.GetWindowLongW(self.me, -20)
        W.u32.SetWindowLongW(self.me, -20, ex & ~0x08000000)        # 잠깐 WS_EX_NOACTIVATE 해제
        W.u32.SetForegroundWindow(self.me)                           # 사용자가 배지를 누른 직후라 허용됨
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()
            W.u32.SetWindowLongW(self.me, -20, ex)

    def quit_all(self):
        """반복 재접속을 멈추고 배지도 닫는다. 반복이 알림 창 응답을 기다리는 중이라 명령을 못 받으면 강제로 끈다."""
        st = ctl.status()
        if st:
            ctl.send('stop')
            open(config.STOP, 'w').close()
            end = time.time() + 8
            while W.process_alive(st['pid']) and time.time() < end:
                time.sleep(0.3)
            if W.process_alive(st['pid']):
                subprocess.run([W.system_exe('taskkill.exe'), '/f', '/t', '/pid', str(st['pid'])],
                               capture_output=True, creationflags=W.NO_WINDOW)
                ctl.clear()
                try:
                    os.remove(config.STOP)
                except OSError:
                    pass
        self.root.destroy()

    # 업데이트
    def toast(self, text, color=FG, ms=6000):
        """배지 아래에 잠깐 뜨는 안내."""
        if getattr(self, '_toast', None):
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
        w = self._toast = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.configure(bg=BG, highlightthickness=1, highlightbackground=ACCENT)
        tk.Label(w, text=text, bg=BG, fg=color, font=(FONT, 9), padx=10, pady=5, wraplength=360, justify='left').pack()
        ml, mt, mr, mb = W.window_rect(self.me)
        w.geometry(f'+{ml}+{mb + 4}')
        w.attributes('-topmost', True)
        if ms:
            w.after(ms, lambda: w.winfo_exists() and w.destroy())

    def update(self):
        self.toast('최신 버전을 확인하는 중이에요…', MUTED, 0)

        def work():
            from . import updater
            changed, msg = updater.update()
            self.root.after(0, lambda: self.after_update(changed, msg))
        threading.Thread(target=work, daemon=True).start()

    def after_update(self, changed, msg):
        if not changed:
            self.toast(msg, FG if '최신' in msg else WARN)
            return
        self.toast(msg + ' 새 버전으로 다시 시작해요.', ACCENT, 0)
        self.root.after(1500, self.restart_all)

    def restart_all(self):
        """반복이 돌고 있으면 같은 예약으로 새 버전에서 다시 켜고, 배지도 새 버전으로 다시 띄운다."""
        st = ctl.status()
        if st:
            mode = st.get('mode', '')
            delay = max(0.0, (st['next_run'] - time.time()) / 60)
            ctl.send('stop')
            end = time.time() + 30
            while ctl.status() and time.time() < end:
                time.sleep(0.5)
            args = ['start', '--delay', f'{delay:.2f}']
            m = re.match(r'(\d+)분 반복', mode)
            if m:
                args += ['--interval', m.group(1)]
            self.start(*args)
        self.start('badge', '--after', str(os.getpid()))
        self.root.destroy()

    def cfg_relaunch(self):
        return bool(config.load().get('relaunch', True))

    def reset_pos(self):
        self.pos = None
        try:
            os.remove(config.BADGE_POS)
        except OSError:
            pass

    def ask_time(self):
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.configure(bg=BG, padx=10, pady=8, highlightthickness=1, highlightbackground=ACCENT)
        ml, mt, mr, mb = W.window_rect(self.me)
        w.geometry(f'+{ml}+{mb + 4}')
        tk.Label(w, text='재실행 시각', bg=BG, fg=MUTED, font=(FONT, 9)).pack(side='left', padx=(0, 6))
        e = tk.Entry(w, width=7, font=(FONT, 10), bg='#242d2b', fg=FG, insertbackground=FG, relief='flat', justify='center')
        e.insert(0, datetime.now().strftime('%H:%M'))
        e.pack(side='left', ipady=2)
        msg = tk.Label(w, text='', bg=BG, fg=WARN, font=(FONT, 8))

        def ok(_=None):
            m = re.fullmatch(r'\s*(\d{1,2})\s*[:시]?\s*(\d{2})\s*분?\s*', e.get())
            if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
                msg.config(text='14:30처럼')
                msg.pack(side='left', padx=4)
                return
            now = datetime.now()
            t = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
            if t <= now:
                t += timedelta(days=1)
            ctl.send('set', t.timestamp())
            w.destroy()

        tk.Button(w, text='적용', command=ok, font=(FONT, 9), bg='#2f3936', fg=FG, relief='flat', padx=8).pack(side='left', padx=4)
        tk.Button(w, text='취소', command=w.destroy, font=(FONT, 9), bg='#2f3936', fg=MUTED, relief='flat', padx=8).pack(side='left')
        e.bind('<Return>', ok)
        e.bind('<Escape>', lambda _: w.destroy())
        w.after(50, lambda: (w.focus_force(), e.focus_set(), e.select_range(0, 'end')))


def run(after_pid=None):
    if after_pid:                                # 업데이트 뒤 다시 띄울 때: 이전 배지가 끝날 때까지 기다림
        end = time.time() + 15
        while W.process_alive(after_pid) and time.time() < end:
            time.sleep(0.2)
    lock = W.single_instance('ResonanceAutoRelogin_badge')
    if lock is None:
        return
    Badge().root.mainloop()
