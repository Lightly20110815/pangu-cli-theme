"""Paths, settings and the error log."""
import json
import os
import time
import traceback
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
# The folder holding the package: the install folder (or a checkout of the repository).
HOME = Path(os.environ.get('PANGU_HOME') or PACKAGE.parent)
CONFIG = HOME / 'config.json'
LOG = HOME / 'error.log'


def load_config():
    try:
        data = json.loads(CONFIG.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def app_config(key):
    apps = load_config().get('apps')
    cfg = apps.get(key) if isinstance(apps, dict) else None
    return cfg if isinstance(cfg, dict) else {}


def log_error(where):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write('--- %s %s\n%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), where, traceback.format_exc()))
    except OSError:
        pass
