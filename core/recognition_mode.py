"""One persisted recognition preference shared by GUI and vision worker."""
import json
import os
import uuid
from runtime_data import resolve_runtime_data_root


def get_recognition_mode():
    path = resolve_runtime_data_root() / 'state/recognition-mode.json'
    try:
        mode = json.loads(path.read_text(encoding='utf-8')).get('mode')
        return mode if mode in ('manual', 'auto') else 'manual'
    except (OSError, ValueError, TypeError):
        return 'manual'


def set_recognition_mode(mode):
    if mode not in ('manual', 'auto'):
        raise ValueError('识别模式必须为 manual 或 auto')
    path = resolve_runtime_data_root() / 'state/recognition-mode.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps({'mode': mode}), encoding='utf-8')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return mode
