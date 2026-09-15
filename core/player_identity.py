"""User-provided exact in-game display name, shared by GUI and vision worker."""
import json
import os
import uuid
from runtime_data import resolve_runtime_data_root


def normalize_player_name(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError('本人昵称必须为单行文字')
    value = value.strip()
    if len(value) > 64:
        raise ValueError('本人昵称不能超过64个字符')
    return value


def get_player_name():
    try:
        value = json.loads((resolve_runtime_data_root() / 'state/player-identity.json').read_text(encoding='utf-8'))
        return normalize_player_name(value['displayName'])
    except (OSError, ValueError, TypeError, KeyError):
        return ''


def set_player_name(value):
    value = normalize_player_name(value)
    path = resolve_runtime_data_root() / 'state/player-identity.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps({'displayName': value}, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return value
