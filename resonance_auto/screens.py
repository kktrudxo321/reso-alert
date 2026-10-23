"""게임 화면 판별(픽셀 색 비교)과 클릭 좌표.

좌표는 게임 창 안쪽 1076x606 기준으로 잰 값이고, 실제 창 크기에 비례해 바꿔 쓴다.
→ 16:9 창 모드라면 창 크기와 관계없이 맞는다. 화면 배율이 다른 비율이면 판별이 틀릴 수 있다.
"""
CW, CH = 1076, 606

# 로그인 단계
CENTER = (538, 303)             # Sign in with Google
TAP = (538, 510)                # 영상 넘기기·타이틀 터치 (가운데를 누르면 Sign in 버튼이 두 번 눌릴 수 있음)
GOOGLE_ACCOUNT = (600, 262)     # 구글 계정 선택 창의 첫 번째 계정
GOOGLE_CONTINUE = (682, 358)    # 구글 로그인 확인 '계속'
DOWNLOAD_OK = (538, 426)        # 리소스 다운로드 안내 '확인'
PANEL_PROBES = [(320, 450), (760, 120), (310, 480)]

# 로그인 뒤 교정 센터 구매 화면까지
PROFILE_ICON = (133, 555)
MENU_REFORM = (131, 530)
CENTER_BUY = (213, 530)
BACK_BTN = (70, 30)
BLANK = (110, 300)              # 팝업 바깥 빈 곳('빈 곳을 터치하여 닫기')
BULK_BTN = (295, 560)           # 일괄 수령 / 일괄 구매
CARD_STRIP = (497, 360, 1076, 420)   # 구매 카드들의 '남은 시간 / 소모 시간' 줄


def scaled(img, p):
    return int(p[0] * img.width / CW), int(p[1] * img.height / CH)


def near(c, ref, tol=18):
    return max(abs(a - b) for a, b in zip(c, ref)) <= tol


def _px(img):
    return lambda p: img.getpixel(scaled(img, p))


def web_loading(img):
    px = _px(img)
    cs = [px(p) for p in [(320, 120), (760, 480), (538, 303), (320, 480), (760, 120)]]
    return all(min(c) >= 190 and max(c) - min(c) <= 8 for c in cs)


def in_google_panel(img):
    px = _px(img)
    return all(near(px(p), (30, 31, 32), 6) for p in PANEL_PROBES)


def google_confirm(img):
    box = img.crop((*scaled(img, (640, 348)), *scaled(img, (725, 368)))).convert('L')
    return sum(1 for v in box.getdata() if v > 100) > 40


def ujoy_popup(img):
    px = _px(img)
    return near(px((620, 256)), (254, 114, 0), 20) and near(px((620, 345)), (30, 200, 0), 60)


def download_popup(img):
    px = _px(img)
    return all(near(px(p), (60, 116, 230), 20) for p in [(330, 426), (440, 426), (640, 426), (750, 426)]) \
        and all(max(px(p)) <= 80 for p in [(100, 300), (538, 300), (1000, 300)])


def login_state(img):
    if web_loading(img):
        return 'web_loading'
    if in_google_panel(img):
        return 'google_confirm' if google_confirm(img) else 'google_account'
    if ujoy_popup(img):
        return 'ujoy'
    if download_popup(img):
        return 'download'
    return 'other'


LOGIN_TARGET = {'ujoy': CENTER, 'google_account': GOOGLE_ACCOUNT, 'google_confirm': GOOGLE_CONTINUE,
                'download': DOWNLOAD_OK, 'other': TAP}


def screen_state(img):
    px = _px(img)
    if near(px((214, 583)), (204, 172, 71)):
        return 'main'                       # 메인 화면(좌측 하단 자산 코인)
    if near(px((35, 150)), (49, 105, 222)) and near(px((40, 30)), (49, 105, 222)):
        return 'menu'                       # 왼쪽 파란 메뉴
    back_white = min(px((40, 30))) >= 230
    if back_white and near(px((213, 530)), (214, 214, 214)) and near(px((214, 583)), (152, 153, 153), 25):
        return 'center'                     # 교정 센터
    if back_white:
        return 'back'                       # 뒤로가기 버튼이 있는 하위 화면(구매 목록 등)
    if all(near(px(p), (182, 55, 57), 30) for p in [(240, 60), (520, 40), (820, 130)]) \
            and all(min(px(p)) >= 200 for p in [(300, 400), (700, 450)]):
        return 'report'                     # '탈옥 보고' 팝업
    if near(px((240, 60)), (90, 124, 189), 30) and all(min(px(p)) >= 220 for p in [(520, 40), (300, 400), (700, 450)]):
        return 'report'                     # '교정 센터 일보' 팝업
    return 'other'


def bulk_button(img):
    """'collect'(연녹색 일괄 수령) / 'buy'(파란색 일괄 구매) / None"""
    cs = [img.getpixel(scaled(img, p)) for p in [(210, 560), (370, 560), (380, 548)]]
    if all(near(c, (129, 177, 19), 30) for c in cs):
        return 'collect'
    if all(c[2] >= 150 and c[2] - c[0] >= 60 for c in cs):
        return 'buy'
    return None
