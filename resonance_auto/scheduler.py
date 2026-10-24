"""반복 재접속.

- 구매 모드(기본): 재접속 때 읽은 '다음 주문 완료 시각'(+30~60초)에 다시 재접속.
  시각을 못 읽으면 5분 → 10분 → … 최대 fallback_minutes 간격으로 다시 시도. 예약이 05:00을 넘으면 05:00:30.
- 간격 모드: 정해진 분 간격으로 재접속(구매 시각과 무관).
재실행 1분 전 PC를 쓰는 중이면 알림(notify.gate). 배지 명령(ctl)으로 미루기·당기기·중지.
설정 relaunch=false(배지 메뉴 '재실행 사용' 끔)면 재접속하지 않고, 구매가 끝나는 시각에 알림만 띄운다.
사용자가 직접 받고 다시 구매한 뒤 [다음 주문 확인]을 누르거나 구매 화면을 열어 두면 다음 알림 시각을 맞춘다.
"""
import os
import random
import time
from datetime import datetime

from . import config, ctl, game, notify, winapi as W
from .logbook import log as _log

RUN_LOCK = 'ResonanceAutoRelogin_run'          # 재접속(반복·한 번)은 동시에 하나만


def run(interval_min=None, first_delay_min=0.0):
    cfg = config.load()
    mode = f'{int(interval_min)}분 반복' if interval_min else '구매 시각 반복'
    log = lambda m: _log(m, mode)
    if os.path.exists(config.STOP):
        os.remove(config.STOP)
    lock = W.single_instance(RUN_LOCK)
    if lock is None:
        log('이미 반복(또는 재접속)이 돌고 있어요. 하나만 실행할게요.')
        return
    nxt = time.time() + first_delay_min * 60
    relaunch = bool(cfg.get('relaunch', True))
    log(f'시작 (첫 실행 {datetime.fromtimestamp(nxt):%H:%M:%S}, 재실행 {"켜짐" if relaunch else "꺼짐(구매 완료 알림만)"})')
    gated, fails = first_delay_min * 60 < 125, 0
    awaiting, last_peek = False, 0.0       # 알림만 모드: 알림 뒤 사용자가 다시 구매해 다음 시각을 알 수 있을 때까지
    try:
        while True:
            cfg = config.load()
            if bool(cfg.get('relaunch', True)) != relaunch:
                relaunch = not relaunch
                log(f'재실행 {"켜짐" if relaunch else "꺼짐(구매가 끝나면 알림만)"}')
                gated = False
                if relaunch and awaiting:
                    awaiting, nxt = False, time.time()
            ctl.beat(nxt, mode=mode, note='구매 확인 필요' if awaiting else ('알림만' if not relaunch else ''))
            if ctl.pending():
                cmd = ctl.take()
                if cmd:
                    nxt = ctl.apply(cmd, nxt, cfg, log)
                    if nxt is None:
                        break
                    gated = False
                    if nxt > time.time() or cmd[0] == 'now':
                        awaiting = False
                    ctl.beat(nxt)
            if os.path.exists(config.STOP):
                os.remove(config.STOP)
                log('중지 요청으로 종료')
                break

            if not relaunch:
                # ---- 알림만 모드: 구매가 끝나는 시각에 알림, 재접속은 하지 않음
                if awaiting:
                    if time.time() - last_peek >= 60:
                        last_peek = time.time()
                        at = game.peek_order(cfg)
                        if at and at.timestamp() > time.time() + 30:
                            nxt, awaiting = ctl.cap_at_5am(at.timestamp()), False
                            log(f'구매 화면에서 다음 주문 확인 → 알림 {datetime.fromtimestamp(nxt):%m-%d %H:%M:%S}')
                elif time.time() >= nxt:
                    log('구매 완료 알림')
                    ctl.beat(nxt, note='구매 확인 필요')
                    note, at = '', None
                    while True:
                        choice = notify.alert(cfg, log, note)
                        if choice != 'check':
                            break
                        at = game.check_order(cfg)
                        if at and at.timestamp() > time.time() + 30:
                            break
                        note = '구매 화면이 아니거나 구매 중인 주문을 못 찾았어요. 다시 구매한 뒤 구매 화면에서 눌러 주세요.'
                    if choice == 'check':
                        nxt = ctl.cap_at_5am(at.timestamp())
                        log(f'알림: 다음 주문 확인 → {datetime.fromtimestamp(nxt):%m-%d %H:%M:%S}')
                    elif choice == 'delay':
                        nxt = ctl.cap_at_5am(time.time() + 300)
                        log(f'알림: 5분 뒤 다시 → {datetime.fromtimestamp(nxt):%H:%M:%S}')
                    elif choice == 'nextday':
                        nxt = game.next_5am()
                        log(f'알림: 다음 날 05시 → {datetime.fromtimestamp(nxt):%m-%d %H:%M}')
                    else:
                        awaiting, last_peek = True, 0.0
                        log('알림 닫음 → 구매 화면을 열면 다음 알림 시각을 맞춰요')
                time.sleep(5)
                continue

            # ---- 재접속 모드
            if not gated and nxt - time.time() <= 125:
                g = notify.gate(nxt, cfg, log)
                gated = True
                if g is None:
                    break
                nxt = g
                continue                       # 게이트 중 들어온 명령을 먼저 처리
            if time.time() >= nxt:
                ctl.beat(nxt, note='재실행 중')
                started = time.time()
                try:
                    game.run_once(cfg)
                except Exception as e:
                    log(f'실행 오류: {e!r}')
                cfg = config.load()            # 실행 중 바뀐 설정 반영
                if interval_min:
                    nxt = time.time() + interval_min * 60
                else:
                    at = None
                    try:
                        if os.path.exists(config.NEXT_BUY) and os.path.getmtime(config.NEXT_BUY) >= started:
                            with open(config.NEXT_BUY) as f:
                                at = datetime.strptime(f.read().strip(), '%Y-%m-%d %H:%M:%S').timestamp()
                    except (OSError, ValueError):
                        at = None
                    if at:
                        fails = 0
                        nxt = at + random.uniform(30, 60)
                    else:
                        fails += 1
                        try:
                            cap = float(cfg.get('fallback_minutes', 31)) * 60
                        except (TypeError, ValueError):
                            cap = 31 * 60
                        nxt = time.time() + min(cap, 5 * 60 * fails)
                    nxt = ctl.cap_at_5am(max(nxt, time.time() + 60))
                log(f'다음 실행 {datetime.fromtimestamp(nxt):%m-%d %H:%M:%S}')
                ctl.beat(nxt, note='')
                gated = False
            time.sleep(5)
    finally:
        ctl.clear()


def stop():
    config.ensure_dirs()
    open(config.STOP, 'w').close()
    if ctl.status():
        ctl.send('stop')
