"""共享密钥加密盒（P23/P25）：设置内敏感字段（MySQL/Redis 密码）Fernet 加密存储。

密钥文件 data/keys/sync.key 自动生成；密钥更换后旧密文解密返回空（需重录）。
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings

_KEY_FILE = "keys/sync.key"


def _key_path() -> Path:
    return Path(settings.data_dir) / _KEY_FILE


def _fernet():
    from cryptography.fernet import Fernet

    path = _key_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Fernet.generate_key())
    return Fernet(path.read_bytes())


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode() if plain else ""


def decrypt_secret(cipher: str) -> str:
    if not cipher:
        return ""
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except Exception:
        return ""
