"""传输加密握手接口（dev-plan P24.1；api-spec §7）。"""

from base64 import b64decode

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import transport_crypto
from app.core.response import BizError, ok
from app.db.session import get_session

router = APIRouter()


@router.get("/crypto/public-key")
async def public_key(_: AsyncSession = Depends(get_session)):
    """下发 RSA 公钥（base64(SPKI DER)，供 WebCrypto importKey 'spki'）与 key_id。

    加密关闭（ENCRYPT_ENABLED=false，如 HTTP 局域网部署）时返回 enabled:false——
    前端在安全上下文（HTTPS）仍会走到本接口，若不显式告知会继续加密请求体，
    而中间件已旁路、后端按裸 JSON 读包，出现"用户名/密码必填"错配（067 实测路径）。
    """
    if not settings.encrypt_enabled:
        return ok({"enabled": False})
    return ok(
        {
            "enabled": True,
            "key_id": transport_crypto.key_id,
            "public_key": transport_crypto.public_key_spki_b64(),
            "algorithm": "RSA-OAEP-SHA256",
        }
    )


class HandshakeRequest(BaseModel):
    sid: str
    key: str  # base64(RSA-OAEP-SHA256(AES-256 会话密钥))


@router.post("/crypto/handshake")
async def handshake(body: HandshakeRequest, _: AsyncSession = Depends(get_session)):
    """前端封装的 AES-256 会话密钥注册（密钥只存在于内存）。"""
    try:
        await transport_crypto.register_session(body.sid, b64decode(body.key))
    except Exception:
        raise BizError(1102, "invalid session key", 400)
    return ok({"key_id": transport_crypto.key_id, "session_id": body.sid})
