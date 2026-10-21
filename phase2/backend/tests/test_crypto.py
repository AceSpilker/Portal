"""D0.3 关卡：传输加密全链路（握手 → 信封往返 → 重放/缺会话/坏信封 → ENC 头）。

用 Python cryptography 模拟前端 WebCrypto 行为（一期 test_crypto.py 的 FakeSession 移植）。
通过 httpx ASGITransport 走完整 ASGI 栈（加密中间件在 Django 之外，Django test Client 不可达）。
"""

import base64
import functools
import inspect
import json
import secrets

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.test import override_settings


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text)


class FakeSession:
    """模拟浏览器侧会话：AES-256 密钥 + 信封加解密。"""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.sid = secrets.token_hex(8)
        self.aes = AESGCM(raw)

    def seal(self, obj: dict) -> dict:
        nonce = secrets.token_bytes(12)
        payload = self.aes.encrypt(nonce, json.dumps(obj).encode(), None)
        return {"enc": 1, "n": b64(nonce), "p": b64(payload)}

    def open(self, body: dict) -> dict:
        return json.loads(self.aes.decrypt(unb64(body["n"]), unb64(body["p"]), None))


def _enable(fn):
    """装饰器：用例内开启加密，结束后还原（其余用例按明文契约测试）。兼容 async 用例。"""

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def awrapper(*args, **kwargs):
            with override_settings(ENCRYPT_ENABLED=True):
                return await fn(*args, **kwargs)

        return awrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with override_settings(ENCRYPT_ENABLED=True):
            return fn(*args, **kwargs)

    return wrapper


async def _handshake(client: httpx.Client, sess: FakeSession) -> None:
    info = (await client.get("/api/crypto/public-key")).json()["data"]
    assert info["enabled"] is True
    pub = serialization.load_der_public_key(unb64(info["public_key"]))
    wrapped = pub.encrypt(
        sess.raw,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    resp = await client.post(
        "/api/crypto/handshake", json={"sid": sess.sid, "key": b64(wrapped)}
    )
    assert resp.status_code == 200


@_enable
async def test_01_public_key_disabled_flag_and_handshake(asgi_client: httpx.Client):
    sess = FakeSession(secrets.token_bytes(32))
    await _handshake(asgi_client, sess)
    # 公钥接口本身在加密豁免清单内：明文可达
    resp = await asgi_client.get("/api/crypto/public-key")
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is True


@_enable
async def test_02_encrypted_roundtrip(asgi_client: httpx.Client):
    """信封解密 → 端点处理 → 响应加密封包（完整往返）。"""
    sess = FakeSession(secrets.token_bytes(32))
    await _handshake(asgi_client, sess)
    resp = await asgi_client.post(
        "/api/_probe/echo",
        json=sess.seal({"echo": "加密链路往返"}),
        headers={"X-Session-Id": sess.sid, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("enc") == 1, "响应必须是密文信封：" + resp.text[:200]
    data = sess.open(body)
    assert data == {"code": 200, "msg": "ok", "data": {"echo": "加密链路往返"}}


@_enable
async def test_03_missing_session_1100(asgi_client: httpx.Client):
    resp = await asgi_client.post("/api/_probe/echo", json={"echo": "x"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 1100
    assert body["msg"] == "secure session required"


@_enable
async def test_04_replayed_nonce_1101(asgi_client: httpx.Client):
    sess = FakeSession(secrets.token_bytes(32))
    await _handshake(asgi_client, sess)
    envelope = sess.seal({"echo": "same"})
    headers = {"X-Session-Id": sess.sid, "Content-Type": "application/json"}
    first = await asgi_client.post("/api/_probe/echo", json=envelope, headers=headers)
    assert first.status_code == 200
    # 同一信封重放 → 1101
    replay = await asgi_client.post("/api/_probe/echo", json=envelope, headers=headers)
    assert replay.status_code == 400
    assert replay.json()["code"] == 1101


@_enable
async def test_05_bad_envelope_1102(asgi_client: httpx.Client):
    sess = FakeSession(secrets.token_bytes(32))
    await _handshake(asgi_client, sess)
    # 明文 JSON 体（非信封）→ 1102
    resp = await asgi_client.post(
        "/api/_probe/echo",
        json={"echo": "plaintext"},
        headers={"X-Session-Id": sess.sid},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1102


@_enable
async def test_06_health_exempt_under_encryption(asgi_client: httpx.Client):
    """加密开启时 /api/health 仍明文可达（豁免清单）。"""
    resp = await asgi_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"


@_enable
async def test_07_enc_authorization_header(asgi_client: httpx.Client):
    """ENC Authorization 头：解密后原样回填（D2 认证依赖读取；本阶段用探针证明透传语义）。

    探针端点不读 Authorization，此处验证坏 ENC 头 → 1102（解密失败路径）。
    """
    sess = FakeSession(secrets.token_bytes(32))
    await _handshake(asgi_client, sess)
    resp = await asgi_client.post(
        "/api/_probe/echo",
        json=sess.seal({"echo": "x"}),
        headers={
            "X-Session-Id": sess.sid,
            "Authorization": "ENC " + sess.seal({"junk": True})["p"],  # 非法格式
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1102
