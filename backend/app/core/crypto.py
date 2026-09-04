"""传输加密引擎（dev-plan P24 / api-spec §7）。

- 密钥交换：RSA-3072，OAEP(SHA-256)；私钥持久化于 data/keys/transport_rsa.pem
- 会话信封：AES-256-GCM（12 字节 nonce）；前端每次会话生成 AES 密钥并以公钥封装
- 重放防护：同一会话内 nonce 去重（LRU 上限）
"""

import base64
import hashlib
import secrets
import threading
from collections import OrderedDict
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

NONCE_SIZE = 12
SESSION_TTL = 7 * 24 * 3600  # 会话密钥存储 TTL（7 天，随刷新续期）
SESSION_MAX = 500  # 内存模式保留的会话密钥数（LRU）
NONCE_MAX = 512  # 每会话记录的最近 nonce 数（重放检测）


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text)


class TransportCrypto:
    def __init__(self) -> None:
        self._priv: rsa.RSAPrivateKey | None = None
        self._pub_spki_b64 = ""
        self._kid = ""
        self._sessions: OrderedDict[str, bytes] = OrderedDict()
        self._seen: dict[str, OrderedDict[str, None]] = {}
        self._lock = threading.Lock()

    # ---- RSA 密钥对（持久化） ----

    def _ensure_rsa(self) -> None:
        if self._priv is not None:
            return
        key_dir = Path(settings.data_dir) / "keys"
        key_dir.mkdir(parents=True, exist_ok=True)
        key_file = key_dir / "transport_rsa.pem"
        if key_file.is_file():
            self._priv = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
        else:
            self._priv = rsa.generate_private_key(
                public_exponent=65537, key_size=settings.transport_rsa_bits
            )
            key_file.write_bytes(
                self._priv.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        pub_der = self._priv.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self._pub_spki_b64 = b64(pub_der)
        self._kid = hashlib.sha256(pub_der).hexdigest()[:16]

    @property
    def key_id(self) -> str:
        self._ensure_rsa()
        return self._kid

    def public_key_spki_b64(self) -> str:
        """WebCrypto 直用格式：base64(SPKI DER)。"""
        self._ensure_rsa()
        return self._pub_spki_b64

    # ---- 会话密钥 ----

    async def register_session(self, session_id: str, wrapped_key: bytes) -> None:
        """用 RSA 私钥解开前端封装的 AES-256 会话密钥并缓存（P25.2 迁入 stores：
        Redis 模式重启不丢；未配置 Redis 时 MemoryStore 等价原 LRU 行为）。"""
        self._ensure_rsa()
        aes = self._priv.decrypt(
            wrapped_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        if len(aes) != 32:
            raise ValueError("session key must be 32 bytes")
        from app.core.stores import stores

        await stores.store.set(f"cs:{session_id}", aes.hex(), ttl=SESSION_TTL)

    async def session_key(self, session_id: str) -> bytes | None:
        from app.core.stores import stores

        raw = await stores.store.get(f"cs:{session_id}")
        if not raw:
            return None
        try:
            return bytes.fromhex(raw)
        except ValueError:
            return None

    # ---- 信封 ----

    def open_envelope(self, aes: bytes, nonce_b64: str, payload_b64: str, session_id: str) -> bytes:
        """解密信封；nonce 重复视为重放（1101）。"""
        nonce = unb64(nonce_b64)
        with self._lock:
            seen = self._seen.setdefault(session_id, OrderedDict())
            if nonce_b64 in seen:
                raise ValueError("replayed nonce")
            seen[nonce_b64] = None
            while len(seen) > NONCE_MAX:
                seen.popitem(last=False)
        return AESGCM(aes).decrypt(nonce, unb64(payload_b64), None)

    def seal(self, aes: bytes, data: bytes) -> tuple[str, str]:
        nonce = secrets.token_bytes(NONCE_SIZE)
        return b64(nonce), b64(AESGCM(aes).encrypt(nonce, data, None))

    # ---- 字符串（Authorization 头）----

    def encrypt_str(self, aes: bytes, text: str) -> str:
        nonce, payload = self.seal(aes, text.encode("utf-8"))
        return f"{nonce}:{payload}"

    def decrypt_str(self, aes: bytes, text: str) -> str:
        nonce_b64, payload_b64 = text.split(":", 1)
        return self.open_envelope(aes, nonce_b64, payload_b64, session_id="__hdr__").decode("utf-8")

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
            self._seen.pop(session_id, None)


transport_crypto = TransportCrypto()
