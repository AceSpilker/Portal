"""网络环境档案接口（M04-7/8；dev-plan P3.1/P3.2）。权限：A 读 / M 写。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import CODE_DUPLICATED, CODE_NOT_FOUND, BizError, ok
from app.db.session import get_session
from app.models.network import NetworkProfile
from app.models.portal import App
from app.models.user import User
from app.schemas.network import (
    NetworkProfileCreate,
    NetworkProfileOut,
    NetworkProfileSortRequest,
    NetworkProfileUpdate,
)
from app.services.network import client_ip_from_request, enabled_profiles, match_profile

router = APIRouter()


def _ensure_default_unique(
    target: NetworkProfileCreate | NetworkProfileUpdate,
    current: NetworkProfile | None,
    default_id: int | None,
) -> None:
    """默认兜底档案全库唯一：switch 到 default 时若已有其他默认档案则拒绝。"""
    match_type = target.match_type
    if match_type is None and current is not None:
        match_type = current.match_type
    if match_type != "default":
        return
    if current is not None and current.match_type == "default":
        return  # 自身已是默认档案，保持不变
    if default_id is not None:
        raise BizError(CODE_DUPLICATED, t("err.default_profile_exists"), 409)


async def _default_profile_id(session: AsyncSession, exclude_id: int | None = None) -> int | None:
    stmt = select(NetworkProfile.id).where(NetworkProfile.match_type == "default")
    if exclude_id is not None:
        stmt = stmt.where(NetworkProfile.id != exclude_id)
    return await session.scalar(stmt)


@router.get("/network-profiles")
async def list_profiles(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """档案列表（含停用，管理页需要），按 sort, id 稳定排序。"""
    rows = (
        (
            await session.execute(
                select(NetworkProfile).order_by(NetworkProfile.sort, NetworkProfile.id)
            )
        )
        .scalars()
        .all()
    )
    return ok([NetworkProfileOut.model_validate(p).model_dump() for p in rows])


@router.post("/network-profiles")
async def create_profile(
    body: NetworkProfileCreate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _ensure_default_unique(body, None, await _default_profile_id(session))
    profile = NetworkProfile(
        name=body.name,
        match_type=body.match_type,
        cidrs=body.cidrs,
        prefer_types=body.prefer_types,
        is_default=body.match_type == "default",
        sort=body.sort,
        enabled=body.enabled,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return ok(NetworkProfileOut.model_validate(profile).model_dump())


@router.put("/network-profiles/sort")
async def sort_profiles(
    body: NetworkProfileSortRequest,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """批量保存排序（幂等：重复提交结果一致）。"""
    for item in body.items:
        await session.execute(
            update(NetworkProfile).where(NetworkProfile.id == item.id).values(sort=item.sort)
        )
    await session.commit()
    return ok(None, t("ok.sorted"))


@router.put("/network-profiles/{profile_id}")
async def update_profile(
    profile_id: int,
    body: NetworkProfileUpdate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    profile = await session.get(NetworkProfile, profile_id)
    if profile is None:
        raise BizError(CODE_NOT_FOUND, t("err.profile_not_found"), 404)
    changes = body.model_dump(exclude_unset=True)
    _ensure_default_unique(body, profile, await _default_profile_id(session, exclude_id=profile_id))
    # 切为 default 档案时清空 cidrs；保持 cidr 档案至少一个网段
    if changes.get("match_type") == "default":
        changes["cidrs"] = []
    merged = changes | {
        "match_type": changes.get("match_type", profile.match_type),
        "cidrs": changes.get("cidrs", profile.cidrs),
    }
    if merged["match_type"] == "cidr" and not merged["cidrs"]:
        raise BizError(2001, t("v.cidr_required"), 422)
    if "match_type" in changes:
        changes["is_default"] = changes["match_type"] == "default"
    for key, value in changes.items():
        setattr(profile, key, value)
    await session.commit()
    await session.refresh(profile)
    return ok(NetworkProfileOut.model_validate(profile).model_dump())


@router.delete("/network-profiles/{profile_id}")
async def delete_profile(
    profile_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    profile = await session.get(NetworkProfile, profile_id)
    if profile is None:
        raise BizError(CODE_NOT_FOUND, t("err.profile_not_found"), 404)
    await session.delete(profile)
    await session.commit()
    return ok(None, t("ok.profile_deleted"))


@router.post("/network-profiles/detect")
async def detect_profile(
    request: Request,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """环境自动识别（M04-8）：按请求来源 IP 匹配 CIDR，未命中走默认兜底。

    返回 {client_ip, matched_profile, candidates}；candidates 为启用档案
    （按优先序），供前端切换器展示与自动命中高亮。
    """
    client_ip = client_ip_from_request(request)
    profiles = await enabled_profiles(session)
    matched = match_profile(client_ip, profiles)
    return ok(
        {
            "client_ip": client_ip,
            "matched_profile": (
                NetworkProfileOut.model_validate(matched).model_dump() if matched else None
            ),
            "candidates": [
                NetworkProfileOut.model_validate(p).model_dump() for p in profiles
            ],
        }
    )


@router.get("/connectivity/matrix")
async def connectivity_matrix(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """全应用×全入口连通性矩阵（M04-13；api-spec §4.3：A 读 M 执行 → 探测仅管理员）。"""
    from app.services.connectivity import probe_apps, record_url_samples

    rows = (
        (
            await session.execute(
                select(App)
                .where(App.deleted.is_(False))
                .order_by(App.sort, App.id)
                .options(selectinload(App.urls))
            )
        )
        .scalars()
        .all()
    )
    matrix = await probe_apps(list(rows))
    # M04-14（P15.4）：矩阵探测结果同写入入口延迟历史
    results = [u for row in matrix["apps"] for u in row["urls"]]
    url_app = {u.id: a.id for a in rows for u in a.urls}
    await record_url_samples(session, results, url_app)
    return ok(matrix)
