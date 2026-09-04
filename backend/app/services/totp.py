"""TOTP 两步验证（M01-7；dev-plan P17.1）。

RFC 6238：HMAC-SHA1、30s 步长、6 位数字，±1 窗口时钟偏移容差。
不引第三方依赖（hmac/struct/base64 标准库实现）；恢复码 8 条，
SHA-256 哈希存储，单次有效。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

STEP = 30
DIGITS = 6
WINDOW = 1  # 允许 ±1 个步长的时钟偏移
RECOVERY_COUNT = 8


def generate_secret() -> str:
    """生成 160bit Base32 密钥。"""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    val = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(val % 10**DIGITS).zfill(DIGITS)


def verify_code(secret: str, code: str, now: float | None = None) -> bool:
    """校验 6 位验证码（±WINDOW 容差；防时序攻击用恒时比较）。"""
    if not code or not code.strip().isdigit() or len(code.strip()) != DIGITS:
        return False
    ts = now if now is not None else time.time()
    counter = int(ts // STEP)
    target = code.strip()
    return any(
        hmac.compare_digest(_code_at(secret, counter + off), target)
        for off in range(-WINDOW, WINDOW + 1)
    )


def provisioning_uri(secret: str, username: str, issuer: str = "Portal") -> str:
    """otpauth:// URI（前端转二维码供验证器扫描）。"""
    from urllib.parse import quote

    return f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def generate_recovery_codes() -> list[str]:
    """8 条恢复码（展示一次，落库为 SHA-256）。"""
    return [
        "-".join((secrets.token_hex(2), secrets.token_hex(2))).upper()
        for _ in range(RECOVERY_COUNT)
    ]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def verify_recovery_code(code: str, hashed: list[str]) -> bool:
    if not code.strip():
        return False
    target = hash_recovery_code(code)
    return any(hmac.compare_digest(target, h) for h in hashed)
