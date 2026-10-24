"""재접속 한 번: 게임을 껐다 켜서 구글 로그인 → (설정 시) 교정 센터 일괄 수령·구매 → 다음 주문 완료 시각 읽기.

1. 게임과 로그인 웹뷰(Vuplex) 프로세스를 끄고, 완전히 꺼진 걸 확인하면 바로 다시 실행한다.
   (웹뷰가 남아 있으면 새 게임의 구글 로그인 창이 하얀 화면으로 멈춘다)
2. 설정에 창 위치가 있으면 그 자리로 옮긴다.
3. 0.2초마다 화면을 캡처해 단계를 판별하고, 새 단계가 보이면 0.2~0.5초(랜덤) 뒤 누른다.
   - 영상/타이틀: 화면 아래쪽 / U joy 팝업: Sign in with Google / 구글 계정 선택: 첫 번째 계정 / 확인: 계속
   - 구글 로그인 창이 하얗게 로딩 중이면 아무것도 누르지 않는다(5초 넘게 하얀 채면 처음부터 다시)
4. 로그인 완료는 게임 로그(Player.log)에 서버 응답이 찍히는 것으로 판단한다.
5. 교정 센터 구매 화면: 일괄 수령 → 팝업 닫기 → 일괄 구매 → 구매 중 카드의 남은 시간을 OCR로 읽음.
"""
import os
import random
import re
import subprocess
import time
from datetime import datetime

from . import config, ocr, screens as S, winapi as W
from .logbook import log

POLL = 0.2
RETRY_FIRST = 0.5
REPEAT_GAP = 3
UJOY_GAP = 6
GOOGLE_STUCK = 20
WEB_STUCK = 5
TIMEOUT = 300
MAX_ATTEMPTS = 5
OTHER_STUCK = 6
WEBVIEW = 'Vuplex WebView.vuplex'


def jitter():
    return random.uniform(0.2, 0.5)


class Presser:
    """새 단계가 보이면 jitter 뒤 클릭, 그대로면 0.5초+jitter 뒤 한 번 더, 이후 3초+jitter 간격."""
    def __init__(self):
        self.state, self.due, self.tries = None, 0.0, 0

    def see(self, st, now):
        if st != self.state:
            self.state, self.due, self.tries = st, now + jitter(), 0
            return True
        return False

    def ready(self, now):
        return now >= self.due

    def pressed(self):
        self.tries += 1
        gap = UJOY_GAP if self.state == 'ujoy' else (RETRY_FIRST if self.tries == 1 else REPEAT_GAP)
        self.due = time.time() + gap + jitter()


class Game:
    def __init__(self, cfg):
        self.cfg = cfg
        self.exe = cfg['game_exe']
        self.image = os.path.basename(self.exe) or config.DEFAULT_GAME_EXE_NAME
        self.player_log = cfg['player_log']
        self._log_start = 0
        self.done_seen = False

    # 창·클릭
    def pid(self):
        return W.find_pid(self.image)

    def hwnd(self):
        pid = self.pid()
        return W.main_window(pid) if pid else None

    def grab(self):
        h = self.hwnd()
        return (h, W.capture(h)) if h else (None, None)

    def click(self, hwnd, img, p):
        if self.cfg.get('screensaver_control'):
            end_screensaver()
        x, y = S.scaled(img, p)
        W.click_screen(hwnd, *W.client_to_screen(hwnd, x, y))

    # 켜고 끄기
    def kill(self):
        pid = self.pid()
        if pid is not None:
            W.terminate(pid)
        # 게임 폴더 안의 로그인 웹뷰만 끈다(같은 이름을 쓰는 다른 프로그램은 건드리지 않음)
        if W.kill_image(WEBVIEW, under=os.path.dirname(self.exe)):
            log('남아 있던 로그인 웹뷰 프로세스 종료')
        if pid is not None:
            end = time.time() + 15
            while self.pid() is not None and time.time() < end:
                time.sleep(0.1)
            if self.pid() is not None:
                log('게임이 꺼지지 않음(관리자 권한으로 실행 중일 수 있어요)')
                return False
            log('게임 종료 확인')
        return True

    def launch(self):
        si = subprocess.STARTUPINFO()
        si.dwFlags, si.wShowWindow = 1, 4                     # SW_SHOWNOACTIVATE
        flags = 0x00000008 | 0x00000200                        # DETACHED_PROCESS | NEW_PROCESS_GROUP
        try:   # 이 프로그램이 중간에 꺼져도 게임은 살아 있도록 작업 그룹에서 떼어 실행
            subprocess.Popen([self.exe], cwd=os.path.dirname(self.exe), startupinfo=si, creationflags=flags | 0x01000000)
        except OSError as e:
            if getattr(e, 'winerror', None) == 740:              # 관리자 권한 필요
                raise RuntimeError('게임이 관리자 권한을 요구해요. 이 프로그램도 관리자 권한으로 실행해 주세요.')
            subprocess.Popen([self.exe], cwd=os.path.dirname(self.exe), startupinfo=si, creationflags=flags)

    def log_size(self):
        try:
            return os.path.getsize(self.player_log)
        except OSError:
            return 0

    def logged_in(self):
        """이번 실행에서 Player.log에 로그인 응답(ReqMainIndex Recv)이 찍혔는지.
        실행 전 로그 크기(self._log_start)를 기억해 두고, 그 뒤에 새로 쓰인 부분만 본다(이전 세션 기록에 속지 않게)."""
        size = self.log_size()
        if size < self._log_start:          # 게임이 로그를 새로 시작함
            self._log_start = 0
        try:
            with open(self.player_log, 'rb') as f:
                f.seek(self._log_start)
                text = f.read().decode('utf-8', 'replace')
        except OSError:
            return False
        return 'ReqMainIndex Recv' in text

    def attempt(self, k):
        if not self.kill():
            return False
        self._log_start = self.log_size()
        started = time.time()
        self.launch()
        log(f'게임 실행 (시도 {k}/{MAX_ATTEMPTS})')
        moved, n, since = False, 0, 0.0
        pr = Presser()
        while time.time() - started < TIMEOUT:
            time.sleep(POLL)
            try:
                fresh = os.path.getmtime(self.player_log) >= started - 1
            except OSError:
                fresh = False
            if fresh and self.logged_in():
                log(f'로그인 완료 ({int(time.time() - started)}초, 클릭 {n}회)')
                return True
            hwnd = self.hwnd()
            if not hwnd:
                continue
            if not moved:
                rect = self.cfg.get('window_rect')
                if rect and W.rect_on_screen(*rect):
                    W.move_window(hwnd, *rect)
                elif rect:
                    log('저장한 창 위치가 지금 모니터 밖이라 옮기지 않았어요(setup을 다시 해 주세요)')
                moved = True
                continue
            now = time.time()
            img = W.capture(hwnd)
            st = S.login_state(img)
            if pr.see(st, now):
                since = now
                if st != 'other':
                    log(f'화면: {st}')
            if st == 'web_loading':
                if now - since > WEB_STUCK:
                    log(f'구글 로그인 창이 {WEB_STUCK}초 넘게 하얀 화면으로 멈춤 → 처음부터 다시')
                    return False
                continue
            if st.startswith('google') and now - since > GOOGLE_STUCK:
                log(f'구글 로그인 창에서 {GOOGLE_STUCK}초 넘게 진행이 없음 → 처음부터 다시')
                return False
            if not pr.ready(now):
                continue
            self.click(hwnd, img, S.LOGIN_TARGET[st])
            pr.pressed()
            n += 1
        log(f'시간 초과({TIMEOUT}초), 로그인 확인 못 함 → 처음부터 다시')
        return False

    # 교정 센터
    def go_to_buy(self):
        t0, last, clicked_buy = time.time(), None, False
        other_since, last_blank = None, 0.0
        pr = Presser()
        while time.time() - t0 < 120:
            time.sleep(POLL)
            hwnd, img = self.grab()
            if not hwnd:
                continue
            st = S.screen_state(img)
            if st != last:
                last = st
            if st == 'back' and clicked_buy:
                log('교정 센터 구매 화면 도착')
                self.bulk()
                return True
            target = {'main': S.PROFILE_ICON, 'menu': S.MENU_REFORM, 'center': S.CENTER_BUY,
                      'report': S.BLANK}.get(st)
            now = time.time()
            if st != 'other':
                other_since = None
            elif other_since is None:
                other_since = now
            elif now - other_since > OTHER_STUCK and now - last_blank > REPEAT_GAP:
                log('넘어가지 않는 화면(출석 보상 등 팝업) → 바깥 빈 곳 터치')
                self.click(hwnd, img, S.BLANK)
                last_blank = now
            pr.see(st, now)
            if target and pr.ready(now):
                self.click(hwnd, img, target)
                pr.pressed()
                clicked_buy = clicked_buy or st == 'center'
        log(f'구매 화면 이동 실패(마지막 화면: {last})')
        return False

    def wait_button(self, limit):
        end = time.time() + limit
        while True:
            hwnd, img = self.grab()
            if not hwnd or S.bulk_button(img) or time.time() > end:
                return hwnd, img
            time.sleep(POLL)

    def bulk(self, depth=0):
        hwnd, img = self.wait_button(3)
        if not hwnd:
            return
        time.sleep(jitter())
        if S.bulk_button(img) == 'collect':
            self.click(hwnd, img, S.BULK_BTN)
            log('일괄 수령')
            time.sleep(2.7 + jitter())
            self.click(hwnd, img, S.BULK_BTN)                 # 받은 물건 팝업 닫기
            time.sleep(0.5)
            hwnd, img = self.wait_button(3)
            time.sleep(jitter())
            if not hwnd:
                return
        if S.bulk_button(img) == 'buy':
            self.click(hwnd, img, S.BULK_BTN)
            log('일괄 구매')
            time.sleep(1)
        at = self.read_next_buy()
        soon = at is not None and at.timestamp() - time.time() < 90
        if depth < 2 and (self.done_seen or soon):
            # 구매 화면을 연 채로 카운트가 끝나면 '일괄 수령'이 안 바뀜 → 뒤로 갔다가 다시 열어 수령
            if soon:
                time.sleep(max(0.0, at.timestamp() - time.time()) + 5)
            log('끝난 주문을 받으려고 구매 화면 다시 열기')
            if self.reenter_buy():
                self.bulk(depth + 1)

    def reenter_buy(self):
        for target, want in [(S.BACK_BTN, 'center'), (S.CENTER_BUY, 'back')]:
            hwnd, img = self.grab()
            if not hwnd:
                return False
            self.click(hwnd, img, target)
            end = time.time() + 10
            while time.time() < end:
                time.sleep(POLL)
                hwnd, img = self.grab()
                if hwnd and S.screen_state(img) == want:
                    break
            else:
                log('구매 화면 다시 열기 실패')
                return False
            time.sleep(jitter())
        return True

    def read_next_buy(self):
        """구매 중 카드의 남은 시간 중 가장 짧은 것 → 완료 시각을 next_buy.txt에 저장.
        구매 중 카드가 없으면(재료 부족 등) 다음 05:00. 못 읽으면 파일을 지우고 None."""
        tmp = os.path.join(config.TMP_DIR, 'ocr_timer.png')
        seen_labels = False
        for _ in range(4):
            time.sleep(1.5)
            hwnd, img = self.grab()
            if not hwnd:
                continue
            a, b = S.scaled(img, S.CARD_STRIP[:2]), S.scaled(img, S.CARD_STRIP[2:])
            c = img.convert('L').crop((*a, *b))
            c.resize((c.width * 3, c.height * 3)).save(tmp)
            words = ocr.words(tmp)
            k = c.width * 3 / 1737                  # 라벨-시간 거리 기준을 창 크기에 맞춤(1076x606 기준 1737px)
            labels = [(x, t) for x, y, t in words if ('남은' in t or '소모' in t)]
            seen_labels = seen_labels or bool(labels)
            left, done = [], False
            for x, y, t in words:
                m = re.fullmatch(r'(\d{1,2}):(\d{2}):(\d{2})', t.strip())
                if not m:
                    continue
                near = [lt for lx, lt in labels if x - 60 * k <= lx <= x + 220 * k]
                sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                if sec < 20:
                    # 00:00:00: 방금 끝났거나 일괄 구매 직후 화면이 아직 안 바뀐 상태 → 구매 화면을 다시 열어 확인
                    done = True
                elif near and '남은' in near[0]:
                    left.append(sec)
            self.done_seen = done
            if left:
                at = datetime.fromtimestamp(time.time() + min(left))
                write_next_buy(at)
                log(f'다음 주문 완료 {at:%H:%M:%S} (구매 중 {len(left)}건)')
                return at
            if done:
                break
            if labels and not any('남은' in t for _, t in labels):
                at = datetime.fromtimestamp(next_5am() - 30)
                write_next_buy(at)
                log(f'구매 중인 주문 없음(재료 부족 등) → 다음 확인 {at:%m-%d %H:%M}')
                return at
        if os.path.exists(config.NEXT_BUY):
            os.remove(config.NEXT_BUY)
        log('다음 주문 완료 시각을 읽지 못함' + ('' if seen_labels else ' (교정 센터 구매 화면이 아닌 것 같아요)'))
        return None


def write_next_buy(at):
    with open(config.NEXT_BUY, 'w') as f:
        f.write(f'{at:%Y-%m-%d %H:%M:%S}')


def next_5am():
    now = datetime.now()
    five = now.replace(hour=5, minute=0, second=30, microsecond=0)
    if five <= now:
        five = datetime.fromtimestamp(five.timestamp() + 86400)
    return five.timestamp()


def end_screensaver():
    r = subprocess.run([W.system_exe('taskkill.exe'), '/f', '/im', 'scrnsave.scr'], capture_output=True,
                       creationflags=W.NO_WINDOW)
    if r.returncode == 0 or W.screensaver_running():
        time.sleep(1)
        return True
    return False


def start_screensaver():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Control Panel\Desktop') as key:
            scr = winreg.QueryValueEx(key, 'SCRNSAVE.EXE')[0]
        subprocess.Popen([scr, '/s'], creationflags=0x00000008)
    except Exception:
        pass


def run_once(cfg, buy=None):
    """재접속 한 번. 로그인에 성공하면 True."""
    W.dpi_aware()
    if not cfg.get('game_exe') or not os.path.isfile(cfg['game_exe']):
        log('게임 실행 파일을 찾을 수 없어요. 먼저 setup을 해 주세요.')
        return False
    g = Game(cfg)
    buy = cfg.get('buy_automation', True) if buy is None else buy
    log('재접속 시작')
    saver = bool(cfg.get('screensaver_control'))
    if saver:
        W.hold_screen(True)
        saver_was_on = end_screensaver()
    try:
        for k in range(1, MAX_ATTEMPTS + 1):
            try:
                ok = g.attempt(k)
            except RuntimeError as e:
                log(str(e))
                return False
            if ok:
                if buy:
                    g.go_to_buy()
                return True
        log(f'{MAX_ATTEMPTS}번 모두 실패')
        return False
    finally:
        h = g.hwnd()
        if h:
            W.set_topmost(h, False)
        if saver:
            W.hold_screen(False)
            if saver_was_on:
                start_screensaver()


def check_order(cfg):
    """재접속 없이 지금 화면이 구매 화면이면 다음 주문 완료 시각을 읽는다."""
    W.dpi_aware()
    g = Game(cfg)
    hwnd, img = g.grab()
    if not hwnd or S.screen_state(img) != 'back':
        log('다음 주문 확인: 구매 화면이 아님')
        return None
    return g.read_next_buy()
