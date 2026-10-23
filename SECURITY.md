# 보안·안전성 정리

이 문서는 프로그램이 **PC에서 무엇을 하는지 전부** 적어 둔 거예요. 코드가 짧으니 직접 확인해 보세요(`resonance_auto/` 폴더의 파이썬 파일들).

## 실행하는 다른 프로그램

| 무엇 | 왜 | 어디서 |
|---|---|---|
| 게임 실행 파일(`settings.json`의 `game_exe`) | 재접속 | `game.py` `launch` |
| 게임 폴더 안의 로그인 웹뷰 `Vuplex WebView.vuplex` 종료 | 게임을 껐을 때 남는 로그인 창 프로세스 정리(다른 폴더의 같은 이름 프로그램은 건드리지 않음) | `winapi.py` `kill_image` |
| `System32\tasklist.exe` | 위 프로세스가 남아 있는지 확인 | `winapi.py` |
| `System32\taskkill.exe` (설정 시 `scrnsave.scr`만) | 화면 보호기 끄기 | `game.py` |
| 레지스트리에 등록된 화면 보호기 프로그램(설정 시) | 재접속 전에 켜져 있던 화면 보호기를 다시 켜기 | `game.py` `start_screensaver` |
| 기록 파일 열기(`os.startfile`) | 배지 메뉴의 '기록 열기'를 눌렀을 때만 | `badge.py` |
| `System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -NonInteractive -Command -` | Windows 내장 한국어 OCR로 '남은 시간' 글자 읽기. 코드에 적힌 고정 명령을 표준 입력으로만 넘기고, 스크립트 파일을 만들거나 실행 정책을 바꾸지 않아요 | `ocr.py` |
| 같은 파이썬(`-m resonance_auto popup` 등) | 알림 창·반복 시작 | `notify.py`, `badge.py` |

## Windows API

- 프로세스 목록 조회, **게임 프로세스 종료**(`TerminateProcess`, 재접속 목적)
- 창 찾기·이동·'항상 위' 설정·창 순서 조정(`SetWindowPos`, `GetWindow`), 창 스타일 변경(`SetWindowLong`: 배지·알림이 포커스를 가져가지 않게), 창 화면 캡처(`PrintWindow`와 GDI 함수)
- 같은 기능이 두 번 동시에 돌지 않게 이름 있는 뮤텍스(`CreateMutex`)
- 실제 마우스 이동·클릭(`SetCursorPos`, `mouse_event`), 게임 창으로 포커스 옮기기(`AttachThreadInput`, `SetForegroundWindow`)
- 마지막 입력 시각 확인(`GetLastInputInfo`, 1분 전 알림용)
- 설정 시에만: 화면 보호기 잠깐 끄기(`SystemParametersInfo`, 저장하지 않는 변경), 절전 방지(`SetThreadExecutionState`)

다른 프로세스의 **메모리를 읽거나 쓰는 API는 쓰지 않아요**(`ReadProcessMemory`, `WriteProcessMemory`, 코드 주입 없음).

## 파일

- 읽기: 게임 로그 `%USERPROFILE%\AppData\LocalLow\临界\레조넌스\Player.log`(로그인이 끝났는지만 확인)
- 쓰기: `%LOCALAPPDATA%\ResonanceAutoRelogin\` 아래만 (settings.json, relogin.log, 상태·명령 파일, 임시 캡처 이미지, 알림 소리 파일)
- 레지스트리: 설정 시에만 화면 보호기 경로를 **읽기**(`HKCU\Control Panel\Desktop`)

## 네트워크

없어요. `socket`, `urllib`, `requests` 등 네트워크 모듈을 쓰지 않아요.

## 시작 프로그램·자동 실행

스스로 시작 프로그램에 등록하지 않아요. 원하면 README대로 직접 바로 가기를 만들어요.

## 알려진 위험

- `settings.json`의 `game_exe`를 실행해요. 이 파일을 누군가 바꿀 수 있다면 다른 프로그램이 실행될 수 있어요(그 정도 권한이면 이미 PC가 위험한 상태예요).
- 실제 마우스를 움직여요. 재접속 중 다른 창이 앞에 뜨면 잘못 클릭할 수 있어 게임 창을 잠깐 '항상 위'로 두고, 배지가 누르는 자리와 겹치면 비켜 둬요.
- 백신 프로그램이 오탐할 수 있는 동작이 있어요: 창 없이 PowerShell 실행(OCR), 다른 프로세스 종료, 실제 마우스 클릭. 모두 위 표에 적은 목적으로만 써요. 오탐이 나면 코드를 직접 확인하고 판단해 주세요.
- `relogin.log`에는 시각·진행 단계와, 오류가 나면 오류 내용(파일 경로 등)이 남아요. 공유할 때 확인하세요.

## 확인하는 방법

- 소스 코드만 배포해요(실행 파일 없음). `pip install -r requirements.txt`는 Pillow(이미지 처리)만 설치해요.
- 저장소의 GitHub Actions가 코드 문법 검사와 CodeQL 보안 검사를 돌려요.
- 문제를 발견하면 공개 이슈 대신 저장소의 *Security → Report a vulnerability*로 알려 주세요.
