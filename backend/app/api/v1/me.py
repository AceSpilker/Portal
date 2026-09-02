"""当前用户接口（M04-9；dev-plan P3.4）：手动网络环境偏好。

偏好存于 users.prefs（JSON）的 env_profile_id 键；置 null 清除手动覆盖，
恢复自动识别。已删/停用的档案在解析时自动回退自动识别（见 apps.resolve）。
"""

import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, BizError, ok
from app.db.session import get_session
from app.models.network import NetworkProfile
from app.models.user import User
from app.schemas.network import NetworkProfileOut
from app.services.network import client_ip_from_request, enabled_profiles, match_profile

router = APIRouter()

PREF_KEY = "env_profile_id"


class MeEnvRequest(BaseModel):
    profile_id: int | None = None


def _load_prefs(user: User) -> dict:
    try:
        return json.loads(user.prefs or "{}")
    except ValueError:
        return {}


def _profile_out(profile: NetworkProfile | None) -> dict | None:
    return NetworkProfileOut.model_validate(profile).model_dump() if profile else None


@router.get("/me/env")
async def get_my_env(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """当前环境状态（切换器数据源）：自动识别 + 手动偏好 + 实际生效。"""
    auto = match_profile(client_ip_from_request(request), await enabled_profiles(session))
    pref_id = _load_prefs(user).get(PREF_KEY)
    manual = None
    if pref_id:
        manual = await session.get(NetworkProfile, int(pref_id))
        if manual is not None and not manual.enabled:
            manual = None  # 停用档案不再作为手动偏好生效
    effective = manual if manual is not None else auto
    return ok(
        {
            "auto_profile": _profile_out(auto),
            "manual_profile": _profile_out(manual),
            "effective_profile": _profile_out(effective),
        }
    )


@router.put("/me/env")
async def set_my_env(
    body: MeEnvRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """手动环境偏好（M04-9）：覆盖自动识别，选择被记忆。"""
    manual = None
    if body.profile_id is not None:
        manual = await session.get(NetworkProfile, body.profile_id)
        if manual is None:
            raise BizError(CODE_NOT_FOUND, t("err.profile_not_found"), 404)

    prefs = _load_prefs(user)
    if body.profile_id is None:
        prefs.pop(PREF_KEY, None)
    else:
        prefs[PREF_KEY] = body.profile_id
    user.prefs = json.dumps(prefs, ensure_ascii=False)
    await session.commit()

    # 回传自动/手动/生效三类档案，供顶栏切换器直接渲染
    auto = match_profile(client_ip_from_request(request), await enabled_profiles(session))
    effective = manual if manual is not None else auto
    return ok(
        {
            "auto_profile": _profile_out(auto),
            "manual_profile": _profile_out(manual),
            "effective_profile": _profile_out(effective),
        }
    )
