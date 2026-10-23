"""설정과 데이터 폴더.

모든 기록·설정 파일은 %LOCALAPPDATA%\\ResonanceAutoRelogin 아래에만 쓴다(프로그램 폴더에는 쓰지 않음).
설정 파일(settings.json)은 `python -m resonance_auto setup`으로 만들고, 메모장으로 고칠 수도 있다.
"""
import json
import os

APP_DIR = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'ResonanceAutoRelogin')
SETTINGS = os.path.join(APP_DIR, 'settings.json')
LOG = os.path.join(APP_DIR, 'relogin.log')
STATUS = os.path.join(APP_DIR, 'loop_status.json')
CMD = os.path.join(APP_DIR, 'loop_cmd.txt')
STOP = os.path.join(APP_DIR, 'stop_loop')
NEXT_BUY = os.path.join(APP_DIR, 'next_buy.txt')
BADGE_POS = os.path.join(APP_DIR, 'badge_pos.json')
TMP_DIR = os.path.join(APP_DIR, 'tmp')

# 한국 PC 클라이언트 기본값
DEFAULT_GAME_EXE_NAME = '레조넌스.exe'
DEFAULT_PLAYER_LOG = os.path.join(os.path.expanduser('~'), 'AppData', 'LocalLow', '临界', '레조넌스', 'Player.log')

DEFAULTS = {
    'game_exe': '',                 # 게임 실행 파일 전체 경로 (setup에서 찾거나 고름)
    'player_log': DEFAULT_PLAYER_LOG,
    'window_rect': None,            # [x, y, 너비, 높이]: 재실행 때 게임 창을 이 자리로 옮김. None이면 옮기지 않음
    'buy_automation': True,         # 로그인 뒤 교정 센터 일괄 수령·구매까지 할지
    'notify_before_restart': True,  # 재실행 1분 전에 PC를 쓰는 중이면 알림 창 띄우기
    'screensaver_control': False,   # 재실행 중 화면 보호기를 잠깐 끄고 끝나면 다시 켜기(PC 설정을 건드림 → 기본 끔)
    'fallback_minutes': 31,         # 다음 주문 시각을 못 읽었을 때 다시 시도할 간격
    'station_id': '83000003',       # 로그인 때 기록할 역 발전도(기본 황원역). 빈 값이면 기록 안 함
}


def ensure_dirs():
    os.makedirs(APP_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)


def load():
    ensure_dirs()
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            data.update(json.load(f))
    except (OSError, ValueError):
        pass
    return data


def save(data):
    ensure_dirs()
    tmp = SETTINGS + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS)


def find_game_exe():
    """흔한 설치 위치에서 게임 실행 파일을 찾는다. 못 찾으면 빈 문자열."""
    roots = []
    for drive in 'CDEFGH':
        for base in (r'Program Files (x86)', r'Program Files', ''):
            roots.append(os.path.join(f'{drive}:\\', base, 'Resonance'))
    for r in roots:
        p = os.path.join(r, DEFAULT_GAME_EXE_NAME)
        if os.path.isfile(p):
            return p
    return ''
