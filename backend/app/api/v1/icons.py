"""自定义图标管理接口（图标库；dev-plan P2.4 增强）。

- GET    /api/icons        列表（A 读：选择器全用户可用）
- POST   /api/icons        新增（M，上传 base64 压方存储）
- PUT    /api/icons/{id}   编辑（M，改名 / 换图）
- DELETE /api/icons/{id}   删除（M，被应用/分组引用时阻止）

内置 Element 图标不入库：只读、经 settings 的 apps.icon_favorites 管理「常用」。
"""
import base64
import binascii
import os

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.response import CODE_CONFLICT, CODE_DUPLICATED, CODE_NOT_FOUND, BizError, ok
from app.db.session import get_session
from app.models.portal import App, Category, CustomIcon
from app.models.user import User
from app.schemas.icons import CustomIconCreate, CustomIconOut, CustomIconUpdate
from app.services.icon import icons_dir, save_icon

router = APIRouter()


async def _get_or_404(session: AsyncSession, icon_id: int) -> CustomIcon:
    icon = await session.get(CustomIcon, icon_id)
    if icon is None:
        raise BizError(CODE_NOT_FOUND, "图标不存在", 404)
    return icon


@router.get("/icons")
async def list_icons(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    rows = (
        (await session.execute(select(CustomIcon).order_by(CustomIcon.name)))
        .scalars()
        .all()
    )
    return ok([CustomIconOut.model_validate(r).model_dump() for r in rows])


async def _decode(data: str) -> bytes:
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BizError(2001, "图标数据不是有效的 base64", 422) from exc
    if not raw:
        raise BizError(2001, "图标数据为空", 422)
    return raw


@router.post("/icons")
async def create_icon(
    body: CustomIconCreate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    dup = await session.scalar(select(CustomIcon.id).where(CustomIcon.name == body.name.strip()))
    if dup is not None:
        raise BizError(CODE_DUPLICATED, "图标名称已存在", 409)
    raw = await _decode(body.data)
    path = await run_in_threadpool(save_icon, raw, body.filename)
    icon = CustomIcon(name=body.name.strip(), path=path)
    session.add(icon)
    await session.commit()
    await session.refresh(icon)
    return ok(CustomIconOut.model_validate(icon).model_dump())


@router.put("/icons/{icon_id}")
async def update_icon(
    icon_id: int,
    body: CustomIconUpdate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    icon = await _get_or_404(session, icon_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != icon.name:
        dup = await session.scalar(
            select(CustomIcon.id).where(
                CustomIcon.name == changes["name"], CustomIcon.id != icon_id
            )
        )
        if dup is not None:
            raise BizError(CODE_DUPLICATED, "图标名称已存在", 409)
        icon.name = changes["name"]
    if changes.get("data"):
        raw = await _decode(changes["data"])
        old_path = icon.path
        icon.path = await run_in_threadpool(save_icon, raw, body.filename)
        # 旧文件不再被任何记录引用时尝试清理（best effort）
        ref_apps = await session.scalar(
            select(func.count()).where(App.icon == old_path, App.icon_type == "upload")
        )
        ref_cats = await session.scalar(
            select(func.count()).where(Category.icon == old_path, Category.icon_type == "upload")
        )
        if not ref_apps and not ref_cats:
            try:
                os.remove(icons_dir() / os.path.basename(old_path))
            except OSError:
                pass
    await session.commit()
    return ok(CustomIconOut.model_validate(icon).model_dump())


@router.delete("/icons/{icon_id}")
async def delete_icon(
    icon_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """删除自定义图标：被应用/分组引用时阻止（4003），避免悬空引用。"""
    icon = await _get_or_404(session, icon_id)
    used_apps = await session.scalar(
        select(func.count()).where(App.icon == icon.path, App.icon_type == "upload")
    )
    used_cats = await session.scalar(
        select(func.count()).where(Category.icon == icon.path, Category.icon_type == "upload")
    )
    used = (used_apps or 0) + (used_cats or 0)
    if used:
        raise BizError(
            CODE_CONFLICT, f"该图标正被 {used} 个应用/分组使用，请先更换图标后再删除", 409
        )
    await session.delete(icon)
    await session.commit()
    try:
        os.remove(icons_dir() / os.path.basename(icon.path))
    except OSError:
        pass
    return ok(None, "图标已删除")
