"""반복 재실행 ↔ 배지(오버레이) 사이 상태·명령 주고받기.

- 반복 쪽은 몇 초마다 loop_status.json에 다음 실행 시각을 남긴다.
- 배지는 loop_cmd.txt에 명령 한 줄을 쓰고, 반복 쪽이 읽어 처리한 뒤 지운다.
  명령: now / delay <초> / set <epoch> / check / nextday / stop
"""
import json
import os
import time
from datetime import datetime

from . import config
from .winapi import process_alive

_state = {'mode': '', 'note': ''}


def beat(next_run, mode=None, note=None):
    if mode is not None:
        _state['mode'] = mode
    if note is not None:
        _state['note'] = note
    data = dict(mode=_state['mode'], next_run=next_run, note=_state['note'], updated=time.time(), pid=os.getpid())
    try:
        tmp = config.STATUS + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, config.STATUS)
    except OSError:
        pass


def clear():
    for p in (config.STATUS, config.CMD):
        try:
            os.remove(p)
        except OSError:
            pass


def pending():
    return os.path.exists(config.CMD)


def take():
    """명령 파일을 먼저 다른 이름으로 옮긴 뒤 읽는다(쓰는 중인 파일을 반쯤 읽거나 새 명령을 지우지 않게)."""
    grabbed = config.CMD + '.taken'
    try:
        os.replace(config.CMD, grabbed)
        with open(grabbed, encoding='utf-8') as f:
            line = f.read().strip()
        os.remove(grabbed)
    except OSError:
        return None
    return line.split() if line else None


def send(*parts):
    config.ensure_dirs()
    tmp = config.CMD + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(' '.join(str(p) for p in parts))
    os.replace(tmp, config.CMD)


def status():
    """반복이 살아 있으면 상태 dict, 아니면 None."""
    try:
        with open(config.STATUS, encoding='utf-8') as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None
    return st if st.get('pid') and process_alive(st['pid']) else None


def cap_at_5am(t):
    """예약이 다음 05:00을 넘으면 05:00:30으로(05:00에 구매 목록 초기화)."""
    from .game import next_5am
    return min(t, next_5am())


def apply(cmd, nxt, cfg, log):
    """명령을 적용한 새 다음 실행 시각. None이면 반복 중지."""
    from .game import check_order, next_5am
    name, args = cmd[0], cmd[1:]
    if name == 'now':
        log('지금 실행')
        return time.time()
    if name == 'delay':
        nxt = cap_at_5am(nxt + float(args[0] if args else 300))
        log(f'미루기 → {datetime.fromtimestamp(nxt):%H:%M:%S}')
        return nxt
    if name == 'set' and args:
        nxt = float(args[0])
        log(f'시각 지정 → {datetime.fromtimestamp(nxt):%m-%d %H:%M}')
        return nxt
    if name == 'check':
        at = check_order(cfg)
        if at:
            # 재실행이 켜져 있으면 완료 30~60초 뒤 재실행, 꺼져 있으면(알림만) 완료 시각 그대로 알림
            relaunch = config.load().get('relaunch', True)
            nxt = cap_at_5am(at.timestamp() + (30 + (time.time() % 30) if relaunch else 0))
            log(f'다음 주문 확인 → {datetime.fromtimestamp(nxt):%H:%M:%S}')
            beat(nxt, note='')
        else:
            beat(nxt, note='다음 주문 확인 실패: 구매 화면을 열고 다시 눌러 주세요.')
        return nxt
    if name == 'nextday':
        nxt = next_5am()
        log(f'다음 날 → {datetime.fromtimestamp(nxt):%m-%d %H:%M}')
        return nxt
    if name == 'stop':
        log('반복 중지')
        return None
    return nxt
