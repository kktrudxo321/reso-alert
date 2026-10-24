@echo off
rem reso-alert 실행: 파이썬·부품이 없으면 설치하고, 처음이면 설정한 뒤 반복 재접속과 배지를 켜요.
rem 인자: (없음) 실행 / autostart 시작프로그램 등록·해제
setlocal
cd /d "%~dp0"
title reso-alert
set "RA_CMD=launch"
if /i "%~1"=="autostart" set "RA_CMD=autostart"

call :findpy
if defined PY goto havepy
echo Python 3.10 이상이 없어서 지금 설치할게요. 1~2분 걸려요...
where winget >nul 2>nul
if errorlevel 1 goto nowinget
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call :findpy
if not defined PY goto nopy
echo Python 설치를 마쳤어요.
echo.

:havepy
"%PY%" -c "import PIL" >nul 2>nul
if not errorlevel 1 goto run
echo 필요한 부품 Pillow를 설치할게요...
"%PY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto pipfail
echo.

:run
"%PY%" -m resonance_auto %RA_CMD%
if errorlevel 1 goto fail
echo.
if /i "%RA_CMD%"=="autostart" goto done
echo 이 창은 10초 뒤 저절로 닫혀요. 닫혀도 프로그램은 계속 돌아요.
"%SystemRoot%\System32\timeout.exe" /t 10 >nul
exit /b 0

:done
pause
exit /b 0

:nowinget
echo 자동 설치 도구 winget이 없어서 직접 설치가 필요해요.
goto manual
:nopy
echo Python을 자동으로 설치하지 못했어요.
:manual
echo 열리는 페이지에서 Python을 받아 설치한 뒤 이 파일을 다시 실행해 주세요.
echo 설치 첫 화면에서 "Add python.exe to PATH"를 꼭 체크하세요.
start "" https://www.python.org/downloads/
pause
exit /b 1

:pipfail
echo 부품 설치에 실패했어요. 인터넷 연결을 확인하고 다시 실행해 주세요.
pause
exit /b 1

:fail
echo 문제가 생겨 멈췄어요. 위 안내를 확인해 주세요.
pause
exit /b 1

rem ---- Python 3.10 이상 찾기: py 런처, PATH의 python, 기본 설치 폴더 순서
:findpy
set "PY="
for /f "delims=" %%p in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do call :trypy "%%p"
if defined PY exit /b 0
for /f "delims=" %%p in ('python -c "import sys;print(sys.executable)" 2^>nul') do call :trypy "%%p"
if defined PY exit /b 0
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*") do call :trypy "%%~d\python.exe"
exit /b 0

:trypy
if defined PY exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import sys;sys.exit(sys.version_info<(3,10))" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0
