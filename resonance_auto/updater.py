"""업데이트: GitHub 저장소의 최신 릴리스를 확인하고, 더 새 버전이면 받아서 바꾼다.

- 접속하는 곳은 GitHub(api.github.com, github.com, 릴리스 파일 저장소)뿐이고, 사용자가 '업데이트'를 눌렀을 때만 접속한다.
- git으로 받은 폴더면 `git fetch --tags` 후 그 릴리스 태그로 이동(fast-forward만, 직접 고친 파일이 있으면 중단).
- 압축 파일로 받은 폴더면 릴리스에 올라간 zip을 받아, GitHub가 알려 주는 SHA-256 지문과 같은지 확인한 뒤 덮어쓴다.
  바꾸기 전 파일은 %LOCALAPPDATA%\\ResonanceAutoRelogin\\backup\\<버전>에 남긴다.
"""
import hashlib
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
import zipfile

from . import __version__, config
from .winapi import NO_WINDOW

REPO = 'kktrudxo321/reso-alert'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # 저장소(프로그램) 폴더
ALLOWED_HOSTS = ('api.github.com', 'github.com', 'objects.githubusercontent.com',
                 'release-assets.githubusercontent.com')
# 압축 파일에서 덮어쓸 대상(그 밖의 파일은 건드리지 않음)
TOP_LEVEL = ('resonance_auto/', 'README.md', 'SECURITY.md', 'LICENSE', 'requirements.txt',
             '실행.bat', '시작프로그램 등록.bat')


def _get(url, timeout=20):
    u = urllib.parse.urlparse(url)
    if u.scheme != 'https':
        raise RuntimeError(f'https 주소만 허용해요: {url}')
    host = u.hostname or ''
    if not any(host == h or host.endswith('.' + h) for h in ALLOWED_HOSTS):
        raise RuntimeError(f'허용하지 않은 주소: {host}')
    req = urllib.request.Request(url, headers={'User-Agent': f'reso-alert/{__version__}',
                                               'Accept': 'application/vnd.github+json'})
    # https + 허용한 GitHub 호스트만 연다(위에서 확인). 리다이렉트된 최종 주소도 아래에서 다시 확인
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
        final = urllib.parse.urlparse(r.geturl()).hostname or ''
        if not any(final == h or final.endswith('.' + h) for h in ALLOWED_HOSTS):
            raise RuntimeError(f'허용하지 않은 주소로 이동됨: {final}')
        return r.read()


def _ver(tag):
    try:
        return tuple(int(x) for x in tag.lstrip('vV').split('.'))
    except ValueError:
        return (0,)


def latest():
    """(태그, zip 주소, sha256 지문 또는 None)"""
    data = json.loads(_get(f'https://api.github.com/repos/{REPO}/releases/latest'))
    tag = data.get('tag_name', '')
    for a in data.get('assets', []):
        if a.get('name', '').endswith('.zip'):
            digest = a.get('digest') or ''
            return tag, a['browser_download_url'], digest.split(':', 1)[1] if digest.startswith('sha256:') else None
    return tag, None, None


def check():
    """(새 버전 있음?, 현재 버전, 최신 태그)"""
    tag, _, _ = latest()
    return _ver(tag) > _ver(__version__), __version__, tag


def _git(*args):
    return subprocess.run(['git', '-C', ROOT, *args], capture_output=True, text=True, creationflags=NO_WINDOW)


def _update_git(tag):
    if _git('status', '--porcelain', '--untracked-files=no').stdout.strip():
        return False, '직접 고친 파일이 있어서 업데이트를 멈췄어요(git status로 확인해 주세요).'
    r = _git('fetch', '--tags', 'origin')
    if r.returncode:
        return False, 'GitHub에서 받아오지 못했어요: ' + r.stderr.strip()[:200]
    r = _git('merge', '--ff-only', tag)
    if r.returncode:
        return False, '바로 이어 받을 수 없는 상태예요: ' + r.stderr.strip()[:200]
    return True, f'{tag}로 업데이트했어요.'


def _update_zip(tag, url, sha256):
    if not url:
        return False, '릴리스에 압축 파일이 없어요.'
    if not sha256:
        return False, '릴리스 파일의 지문 정보를 받지 못해 안전하게 바꿀 수 없어요.'
    blob = _get(url, timeout=60)
    if hashlib.sha256(blob).hexdigest() != sha256.lower():
        return False, '받은 파일의 지문이 맞지 않아 업데이트를 멈췄어요.'
    config.ensure_dirs()
    tmp = os.path.join(config.TMP_DIR, 'update.zip')
    with open(tmp, 'wb') as f:
        f.write(blob)
    with zipfile.ZipFile(tmp) as z:
        names = z.namelist()
        prefix = os.path.commonprefix(names)
        prefix = prefix[:prefix.rfind('/') + 1]           # 'reso-alert/' 같은 최상위 폴더
        plan = []
        for n in names:
            rel = n[len(prefix):]
            if not rel or n.endswith('/'):
                continue
            if rel.startswith(('/', '\\')) or '..' in rel.replace('\\', '/').split('/') or ':' in rel:
                return False, '압축 파일 안에 이상한 경로가 있어 업데이트를 멈췄어요.'
            if rel.startswith(TOP_LEVEL[0]) or rel in TOP_LEVEL[1:]:
                plan.append((n, rel))
        if not any(rel == 'resonance_auto/__init__.py' for _, rel in plan):
            return False, '압축 파일 구성이 예상과 달라 업데이트를 멈췄어요.'
        backup = os.path.join(config.APP_DIR, 'backup', __version__)
        if os.path.isdir(backup):
            shutil.rmtree(backup)
        shutil.copytree(os.path.join(ROOT, 'resonance_auto'), os.path.join(backup, 'resonance_auto'),
                        ignore=shutil.ignore_patterns('__pycache__'))
        for name in TOP_LEVEL[1:]:
            if os.path.isfile(os.path.join(ROOT, name)):
                shutil.copy2(os.path.join(ROOT, name), backup)
        keep = {rel for _, rel in plan}
        for f in os.listdir(os.path.join(ROOT, 'resonance_auto')):   # 새 버전에 없는 옛 모듈은 지움(백업에는 남아 있음)
            if f.endswith('.py') and f'resonance_auto/{f}' not in keep:
                os.remove(os.path.join(ROOT, 'resonance_auto', f))
        for n, rel in plan:
            dest = os.path.join(ROOT, *rel.split('/'))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(n) as src, open(dest, 'wb') as out:
                shutil.copyfileobj(src, out)
    os.remove(tmp)
    return True, f'{tag}로 업데이트했어요. 이전 파일은 {backup}에 있어요.'


def update():
    """(바뀌었음?, 안내 문구)"""
    try:
        tag, url, sha = latest()
    except Exception as e:
        return False, f'최신 버전을 확인하지 못했어요: {e}'
    if _ver(tag) <= _ver(__version__):
        return False, f'최신 버전이에요 (v{__version__}).'
    try:
        if os.path.isdir(os.path.join(ROOT, '.git')) and shutil.which('git'):
            return _update_git(tag)
        return _update_zip(tag, url, sha)
    except Exception as e:
        return False, f'업데이트 중 문제가 생겼어요: {e}'
