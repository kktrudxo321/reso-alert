"""사용법

  python -m resonance_auto setup              처음 설정(게임 경로·창 위치 저장, 글자 인식 점검)
  python -m resonance_auto once               재접속 한 번(+ 설정 시 교정 센터 일괄 수령·구매)
  python -m resonance_auto start              구매 완료 시각마다 반복 재접속
  python -m resonance_auto start --interval 31   31분마다 반복 재접속
  python -m resonance_auto stop               반복 중지
  python -m resonance_auto badge              게임 창 위 타이머 배지
  python -m resonance_auto status             지금 예약 보기
  python -m resonance_auto update             GitHub 최신 릴리스로 업데이트
  python -m resonance_auto version            지금 버전

  옵션: start --delay 10   첫 재접속을 10분 뒤에
"""
import os
import sys
from datetime import datetime

from . import config


def setup():
    from . import ocr, winapi as W
    W.dpi_aware()
    cfg = config.load()
    print('== 레조넌스 자동 재접속 설정 ==')
    print(f'설정 파일: {config.SETTINGS}')
    exe = cfg.get('game_exe') or config.find_game_exe()
    if not exe or not os.path.isfile(exe):
        try:
            import tkinter as tk
            from tkinter import filedialog
            tk.Tk().withdraw()
            exe = filedialog.askopenfilename(title='레조넌스 실행 파일을 골라 주세요', filetypes=[('실행 파일', '*.exe')])
        except Exception:
            exe = input('레조넌스 실행 파일 전체 경로: ').strip().strip('"')
    if not exe or not os.path.isfile(exe):
        print('게임 실행 파일을 찾지 못했어요. 다시 setup을 실행해 주세요.')
        return 1
    cfg['game_exe'] = os.path.normpath(exe)
    print(f'게임: {cfg["game_exe"]}')
    if not os.path.isfile(cfg['player_log']):
        print(f'주의: 게임 로그를 찾지 못했어요({cfg["player_log"]}). 게임을 한 번 켰다 끈 뒤 다시 setup 해 주세요.')
    pid = W.find_pid(os.path.basename(cfg['game_exe']))
    hwnd = W.main_window(pid) if pid else None
    if hwnd:
        l, t, r, b = W.window_rect(hwnd)
        cfg['window_rect'] = [l, t, r - l, b - t]
        print(f'지금 게임 창 위치를 저장했어요: x={l}, y={t}, {r - l}x{b - t}. 재접속 때 이 자리로 옮겨요.')
        img = W.capture(hwnd)
        ratio = img.width / max(1, img.height)
        if abs(ratio - 16 / 9) > 0.03:
            print(f'주의: 게임 화면 비율이 16:9가 아니에요({img.width}x{img.height}). 화면 판별이 틀릴 수 있으니 16:9 창 모드로 바꿔 주세요.')
    else:
        print('게임이 꺼져 있어서 창 위치는 저장하지 않았어요(재접속 때 창을 옮기지 않음).')
        print('원하는 자리에 게임 창을 두고 켜 둔 상태에서 setup을 다시 하면 저장돼요.')
    if ocr.korean_available():
        print('글자 인식(Windows 한국어 OCR): 정상')
    else:
        print('글자 인식: Windows에 한국어 OCR 언어 팩이 없어요. 구매 시각을 읽으려면')
        print('  설정 → 시간 및 언어 → 언어 및 지역 → 한국어 추가(또는 한국어 옵션에서 "광학 문자 인식" 설치)를 해 주세요.')
    config.save(cfg)
    print('설정을 저장했어요.')
    return 0


def status():
    from . import ctl
    st = ctl.status()
    if not st:
        print('반복 재접속이 꺼져 있어요.')
    else:
        print(f"{st['mode']}: 다음 실행 {datetime.fromtimestamp(st['next_run']):%m-%d %H:%M:%S} {st.get('note', '')}")


def main(argv):
    for stream in (sys.stdout, sys.stderr):           # 영문 Windows 콘솔에서도 한글 출력이 깨지거나 멈추지 않게
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == 'setup':
        return setup()
    if cmd == 'once':
        from . import game, scheduler, winapi as W
        lock = W.single_instance(scheduler.RUN_LOCK)
        if lock is None:
            print('반복 재접속이 돌고 있어요. 지금 한 번 하려면 배지 메뉴의 "지금 실행"을 쓰세요.')
            return 1
        return 0 if game.run_once(config.load()) else 1
    if cmd == 'start':
        from . import scheduler
        interval = float(rest[rest.index('--interval') + 1]) if '--interval' in rest else None
        delay = float(rest[rest.index('--delay') + 1]) if '--delay' in rest else 0.0
        scheduler.run(interval, delay)
        return 0
    if cmd == 'stop':
        from . import scheduler
        scheduler.stop()
        print('중지 요청을 보냈어요.')
        return 0
    if cmd == 'badge':
        from . import badge
        badge.run(int(rest[rest.index('--after') + 1]) if '--after' in rest else None)
        return 0
    if cmd == 'update':
        from . import updater
        changed, msg = updater.update()
        print(msg)
        if changed:
            print('반복이나 배지가 켜져 있으면 껐다 다시 켜야 새 버전이 적용돼요(배지 메뉴의 업데이트는 자동으로 다시 켜요).')
        return 0
    if cmd == 'version':
        from . import __version__
        print(__version__)
        return 0
    if cmd == 'status':
        status()
        return 0
    if cmd == 'popup':                      # 내부용: 알림 창
        from . import notify
        notify.popup(float(rest[0]), rest[1], rest[2] if len(rest) > 2 else '', rest[3] if len(rest) > 3 else 'restart')
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
