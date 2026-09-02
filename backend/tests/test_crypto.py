"""P24 测试关卡：传输加密全链路（握手 → 加密封往来 → 重放/缺会话/明文拒绝）。

用 Python cryptography 模拟前端 WebCrypto 行为（RSA-OAEP-SHA256 + AES-256-GCM）。
依赖 test_auth 先行执行（管理员账号已初始化，最终密码为 NEW_PASS）。
"""

import base64
import functools
import json
import os
import secrets

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from test_auth import ADMIN_USER
from test_auth import NEW_PASS as ADMIN_PASS

from app.core.config import settings


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


sess = FakeSession(os.urandom(32))
_tokens: dict = {}


def _enable(fn):
    """装饰器：用例内开启加密，结束后还原（其余用例按明文契约测试）。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        prev = settings.encrypt_enabled
        settings.encrypt_enabled = True
        try:
            return fn(*args, **kwargs)
        finally:
            settings.encrypt_enabled = prev

    return wrapper


@_enable
def test_01_public_key_and_handshake(client: TestClient):
    resp = client.get("/api/crypto/public-key")
    assert resp.status_code == 200
    info = resp.json()["data"]
    assert info["key_id"]

    pub = serialization.load_der_public_key(unb64(info["public_key"]))
    wrapped = pub.encrypt(
        sess.raw,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    resp = client.post("/api/crypto/handshake", json={"sid": sess.sid, "key": b64(wrapped)})
    assert resp.status_code == 200


@_enable
def test_02_encrypted_login_roundtrip(client: TestClient):
    resp = client.post(
        "/api/auth/login",
        json=sess.seal({"username": ADMIN_USER, "password": ADMIN_PASS}),
        headers={"X-Session-Id": sess.sid, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    if body.get("enc") != 1:
        import sys as _sys

        print(f"[DBG] test_02 resp: {resp.text[:200]}", file=_sys.stderr)
    assert body.get("enc") == 1, "响应必须是密文信封：" + resp.text[:200]
    tokens = sess.open(body)["data"]
    assert tokens["user"]["role"] == "admin"
    _tokens["access"] = tokens["access_token"]


@_enable
def test_03_encrypted_me_with_encrypted_authorization(client: TestClient):
    nonce = secrets.token_bytes(12)
    raw_auth = f"Bearer {_tokens['access']}".encode()
    enc_auth = b64(nonce) + ":" + b64(sess.aes.encrypt(nonce, raw_auth, None))
    resp = client.get(
        "/api/auth/me",
        headers={"X-Session-Id": sess.sid, "Authorization": f"ENC {enc_auth}"},
    )
    assert resp.status_code == 200
    me = sess.open(resp.json())["data"]
    assert me["username"] == ADMIN_USER


@_enable
def test_04_replay_rejected(client: TestClient):
    """同一 nonce 的密文重放 → 1101。"""
    nonce = secrets.token_bytes(12)
    body = sess.seal({"username": ADMIN_USER, "password": ADMIN_PASS})
    body["n"] = b64(nonce)
    body["p"] = b64(sess.aes.encrypt(nonce, json.dumps({"ping": True}).encode(), None))
    headers = {"X-Session-Id": sess.sid, "Content-Type": "application/json"}
    first = client.post("/api/auth/login", json=body, headers=headers)
    replay = client.post("/api/auth/login", json=body, headers=headers)
    assert first.status_code == 422  # 信封解密成功后才进入业务校验（{"ping": true} 缺字段）
    assert replay.json()["code"] == 1101


@_enable
def test_05_missing_session_rejected(client: TestClient):
    resp = client.post(
        "/api/auth/login",
        json={"enc": 1, "n": b64(secrets.token_bytes(12)), "p": b64(secrets.token_bytes(32))},
    )
    assert resp.json()["code"] == 1100


@_enable
def test_06_health_remains_plaintext(client: TestClient):
    """豁免清单：/api/health 保持明文（容器探活用）。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"


@_enable
def test_07_plaintext_body_rejected(client: TestClient):
    resp = client.post(
        "/api/auth/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
        headers={"X-Session-Id": sess.sid, "Content-Type": "application/json"},
    )
    assert resp.json()["code"] == 1102


@_enable
def test_08_full_flow_over_encryption(client: TestClient):
    """加密链路下的完整业务流：登录 → me → 修改密码 → 旧 token 失效 → 重新登录。"""

    def call(method: str, url: str, token: str | None = None, obj: dict | None = None) -> dict:
        headers = {"X-Session-Id": sess.sid}
        if token:
            nonce = secrets.token_bytes(12)
            enc = b64(nonce) + ":" + b64(sess.aes.encrypt(nonce, f"Bearer {token}".encode(), None))
            headers["Authorization"] = f"ENC {enc}"
        body = sess.seal(obj) if obj is not None else None
        resp = client.request(method, url, json=body, headers=headers)
        # 信封解密后为统一响应体 {code, message, data}，整体返回供断言
        return sess.open(resp.json())

    login = call("POST", "/api/auth/login", obj={"username": ADMIN_USER, "password": ADMIN_PASS})[
        "data"
    ]
    assert login["user"]["username"] == ADMIN_USER
    me = call("GET", "/api/auth/me", token=login["access_token"])["data"]
    assert me["username"] == ADMIN_USER
    changed_resp = call(
        "PUT",
        "/api/auth/password",
        token=login["access_token"],
        obj={"old_password": ADMIN_PASS, "new_password": "rotated999"},
    )
    assert changed_resp["code"] == 0  # 成功
    stale = call("GET", "/api/auth/me", token=login["access_token"])
    assert stale["code"] == 1003  # 旧 token 失效
    relogin = call(
        "POST", "/api/auth/login", obj={"username": ADMIN_USER, "password": "rotated999"}
    )
    assert relogin["data"]["user"]["username"] == ADMIN_USER
