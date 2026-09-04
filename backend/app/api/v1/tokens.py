"""开放 API Token 管理（M14-1；dev-plan P17.2；api-spec §4.12）。

Token 明文仅创建响应返回一次（plt_ 前缀 + 32 hex），库内只存 SHA-256；
scope: ro（仅 GET）/ rw；可设过期时间；鉴权通道见 core/deps.py。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, BizError, ok
from app.db.session import get_session
from app.models.api_token import ApiToken
from app.models.user import User

router = APIRouter()


def _view(row: ApiToken) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.token_prefix,
        "scope": row.scope,
        "revoked": row.revoked,
        "expires_at": row.expires_at.isoformat() + "Z" if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() + "Z" if row.last_used_at else None,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "note": row.note,
    }


class TokenBody(BaseModel):
    name: str = Field(max_length=64)
    scope: str = Field(default="ro", pattern="^(ro|rw)$")
    expires_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str = Field(default="", max_length=200)


@router.get("/tokens")
async def list_tokens(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """当前用户的 Token 清单（管理页展示前缀，不回明文）。"""
    rows = (
        (
            await session.execute(
                select(ApiToken)
                .where(ApiToken.user_id == user.id, ApiToken.revoked.is_(False))
                .order_by(ApiToken.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return ok([_view(r) for r in rows])


@router.post("/tokens")
async def create_token(
    body: TokenBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """生成 Token：明文仅此一次返回。"""
    raw = f"plt_{secrets.token_hex(16)}"
    row = ApiToken(
        user_id=user.id,
        name=body.name.strip() or "token",
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        token_prefix=raw[:8],
        scope=body.scope,
        expires_at=datetime.fromisoformat(body.expires_at) if body.expires_at else None,
        note=body.note,
    )
    session.add(row)
    await session.commit()
    return ok({**_view(row), "token": raw}, t("ok.token_created"))


@router.delete("/tokens/{token_id}")
async def revoke_token(
    token_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """吊销 Token（软删，审计留痕）。"""
    row = await session.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise BizError(CODE_NOT_FOUND, t("err.token_not_found"), 404)
    row.revoked = True
    await session.commit()
    return ok({"id": token_id}, t("ok.token_revoked"))
