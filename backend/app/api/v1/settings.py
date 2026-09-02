"""系统设置接口（P7.1 前置落地；api-spec §4.12：GET/PUT /api/settings）。

A 读（登录用户，页面需要站点名/标签候选等），M 写（管理员）。
value 一律以 JSON 存储，返回时解析为原生类型。
"""

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import ok
from app.db.session import get_session
from app.models.setting import Setting
from app.models.user import User
from app.schemas.settings import SettingsUpdate

router = APIRouter()


@router.get("/settings")
async def get_settings(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    rows = (await session.execute(select(Setting))).scalars().all()
    return ok({row.key: row.get_value() for row in rows})


@router.put("/settings")
async def update_settings(
    body: SettingsUpdate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    for key, value in body.values.items():
        await session.merge(Setting(key=key, value=json.dumps(value, ensure_ascii=False)))
    await session.commit()
    return ok(None, t("ok.settings_saved"))
