"""传输加密握手接口（dev-plan P24.1；api-spec §7）。"""
from base64 import b64decode

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import transport_crypto
from app.core.response import BizError, ok
from app.db.session import get_session

router = APIRouter()


@router.get("/crypto/public-key")
async def public_key(_: AsyncSession = Depends(get_session)):
    """下发 RSA 公钥与 key_id（公开访问；信封不含敏感数据）。"""
    return ok(
        {
            "key_id": transport_crypto.key_id,
            "public_key": transport_crypto.public_key_pem(),
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
        transport_crypto.register_session(body.sid, b64decode(body.key))
    except Exception:
        raise BizError(1102, "invalid session key", 400)
    return ok({"key_id": transport_crypto.key_id, "session_id": body.sid})
