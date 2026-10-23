"""Windows 내장 OCR(Windows.Media.Ocr)로 이미지 속 글자와 위치를 읽는다.

PowerShell 스크립트 파일을 만들거나 실행 정책을 바꾸지 않는다. 고정된 명령을 표준 입력으로 넘겨
PowerShell이 Windows 기본 OCR을 부르게 할 뿐이고, 인터넷에 보내는 것은 없다.
"""
import os
import subprocess

from .winapi import NO_WINDOW, system_exe

POWERSHELL = system_exe(os.path.join('WindowsPowerShell', 'v1.0', 'powershell.exe'))

_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait() | Out-Null; $task.Result }
$path = $env:RAR_OCR_IMAGE
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('ko'))
if ($engine -eq $null) { [Console]::Error.WriteLine('NO_KOREAN_OCR'); $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) { foreach ($w in $line.Words) { $r = $w.BoundingRect; '{0:F0} {1:F0} {2}' -f $r.X, $r.Y, $w.Text } }
$stream.Dispose()
'''


def korean_available():
    """한국어 OCR 언어 팩이 있는지."""
    from PIL import Image
    import tempfile
    path = os.path.join(tempfile.gettempdir(), 'rar_ocr_probe.png')
    Image.new('L', (40, 20), 255).save(path)
    env = dict(os.environ, RAR_OCR_IMAGE=path)
    try:
        r = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', '-'],
                           input=_SCRIPT.encode('utf-8'), capture_output=True, env=env, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return b'NO_KOREAN_OCR' not in r.stderr and r.returncode == 0


def words(image_path, timeout=30):
    """[(x, y, 글자), ...]. 실패하면 빈 목록."""
    env = dict(os.environ, RAR_OCR_IMAGE=os.path.abspath(image_path))
    try:
        r = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', '-'],
                           input=_SCRIPT.encode('utf-8'), capture_output=True, env=env,
                           timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in r.stdout.decode('utf-8', 'ignore').splitlines():
        p = line.strip().split(' ', 2)
        if len(p) == 3 and p[0].lstrip('-').isdigit() and p[1].lstrip('-').isdigit():
            out.append((int(p[0]), int(p[1]), p[2]))
    return out
