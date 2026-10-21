"""core 域端点（二期 D0.2/D0.3/D0.4）：健康检查、传输加密握手、加密链路探针。

路径与一期完全一致（/api/health、/api/crypto/*）；
/_probe/* 为二期加密链路自检端点（非豁免、免登录），供 D0 关卡 A 验证信封往返。
"""

from base64 import b64decode

from django.conf import settings
from django.db import connection
from ninja import Router, Schema

from apps.core.crypto import transport_crypto
from apps.core.response import BizError, ok

router = Router(tags=["system", "crypto"])


def _users_count() -> int:
    """零用户判定（一期 health 同语义）；D1 模型接管前用裸 SQL，表缺失视为 0。"""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            return int(cur.fetchone()[0] or 0)
    except Exception:
        return 0


@router.get("/health")
def health(request) -> dict:
    """系统健康检查（公开、加密豁免）；initialized 供前端判断是否进入初始化向导。"""
    return ok(
        {
            "status": "ok",
            "app": "portal",
            "version": settings.APP_VERSION,
            "initialized": _users_count() > 0,
        }
    )


@router.get("/crypto/public-key")
async def public_key(request) -> dict:
    """下发 RSA 公钥（base64(SPKI DER)，供 WebCrypto importKey 'spki'）与 key_id。

    加密关闭（ENCRYPT_ENABLED=false，如 HTTP 局域网部署）时返回 enabled:false——
    前端在安全上下文（HTTPS）仍会走到本接口，若不显式告知会继续加密请求体，
    而中间件已旁路、后端按裸 JSON 读包，出现"用户名/密码必填"错配（一期 067 实测路径）。
    """
    if not settings.ENCRYPT_ENABLED:
        return ok({"enabled": False})
    return ok(
        {
            "enabled": True,
            "key_id": transport_crypto.key_id,
            "public_key": transport_crypto.public_key_spki_b64(),
            "algorithm": "RSA-OAEP-SHA256",
        }
    )


class HandshakeRequest(Schema):
    sid: str
    key: str  # base64(RSA-OAEP-SHA256(AES-256 会话密钥))


@router.post("/crypto/handshake")
async def handshake(request, body: HandshakeRequest) -> dict:
    """前端封装的 AES-256 会话密钥注册（密钥只存在于内存/stores）。"""
    try:
        await transport_crypto.register_session(body.sid, b64decode(body.key))
    except Exception:
        raise BizError(1102, "invalid session key", 400)
    return ok({"key_id": transport_crypto.key_id, "session_id": body.sid})


class ProbeEcho(Schema):
    echo: str


@router.post("/_probe/echo")
def probe_echo(request, body: ProbeEcho) -> dict:
    """加密链路自检（非豁免、免登录）：信封解密 → 原样回显 → 响应加密封包。"""
    return ok({"echo": body.echo})
