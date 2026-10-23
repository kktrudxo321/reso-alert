import sys
from datetime import datetime

from . import config


def log(msg, tag=''):
    config.ensure_dirs()
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {('[' + tag + '] ') if tag else ''}{msg}"
    with open(config.LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    if sys.stdout:
        try:
            print(line, flush=True)
        except Exception:
            pass
