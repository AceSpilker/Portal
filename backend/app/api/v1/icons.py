"""图标库管理接口（v2：内置 + 自定义图标统一实体，全部可改名/换图/删除）。

- GET  /api/icons        图标列表（A 读；hidden 项不返回）
- POST /api/icons/seed   播种内置图标名（A；幂等，已删除的内置图标不会复活）
- POST /api/icons        新增自定义图标（M，base64 压方存储）
- PUT  /api/icons/{id}   编辑（M，改名级联引用与常用精选 / 换图覆盖原路径）
- DELETE /api/icons/{id} 删除（M，被引用时 4003；内置软删、自定义物理删除）

内置图标渲染依赖前端 Element 组件（element_name），自定义/覆盖图渲染 /icons/ 路径。
"""

import base64
import binascii
import io
import json
import os

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import CODE_CONFLICT, CODE_DUPLICATED, CODE_NOT_FOUND, BizError, ok
from app.db.session import get_session
from app.models.portal import App, Category, Icon
from app.models.setting import Setting
from app.models.user import User
from app.schemas.icons import CustomIconCreate, IconOut, IconSeedRequest, IconUpdate
from app.services.icon import icons_dir, save_icon

router = APIRouter()

_FAV_KEY = "apps.icon_favorites"


async def _get_or_404(session: AsyncSession, icon_id: int) -> Icon:
    icon = await session.get(Icon, icon_id)
    if icon is None or icon.hidden:
        raise BizError(CODE_NOT_FOUND, t("err.icon_not_found"), 404)
    return icon


async def _decode(data: str) -> bytes:
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BizError(2001, t("err.icon_base64"), 422) from exc
    if not raw:
        raise BizError(2001, t("err.icon_empty"), 422)
    return raw


async def _name_taken(session: AsyncSession, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Icon.id).where(Icon.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Icon.id != exclude_id)
    return await session.scalar(stmt) is not None


@router.get("/icons")
async def list_icons(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """图标列表：自定义在前、内置其后，均按名称排序。"""
    rows = (
        (
            await session.execute(
                select(Icon)
                .where(Icon.hidden.is_(False))
                .order_by(Icon.source.desc(), Icon.name)
            )
        )
        .scalars()
        .all()
    )
    return ok([IconOut.model_validate(r).model_dump() for r in rows])


@router.post("/icons/seed")
async def seed_builtin_icons(
    body: IconSeedRequest,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """播种内置图标：仅插入缺失行；已删除（hidden）或已存在的不复活。"""
    existing = {
        name
        for (name,) in (
            await session.execute(select(Icon.element_name).where(Icon.source == "builtin"))
        ).all()
        if name
    }
    missing = [n for n in body.names if n not in existing]
    for name in missing:
        session.add(Icon(name=name, source="builtin", element_name=name))
    if missing:
        await session.commit()
    return ok({"seeded": len(missing)})


@router.post("/icons")
async def create_icon(
    body: CustomIconCreate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if await _name_taken(session, body.name.strip()):
        raise BizError(CODE_DUPLICATED, t("err.icon_dup"), 409)
    raw = await _decode(body.data)
    path = await run_in_threadpool(save_icon, raw, body.filename)
    icon = Icon(name=body.name.strip(), source="custom", path=path)
    session.add(icon)
    await session.commit()
    await session.refresh(icon)
    return ok(IconOut.model_validate(icon).model_dump())


@router.put("/icons/{icon_id}")
async def update_icon(
    icon_id: int,
    body: IconUpdate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """编辑图标：改名（级联引用与常用精选）与换图（覆盖原路径，引用不受影响）。"""
    icon = await _get_or_404(session, icon_id)
    changes = body.model_dump(exclude_unset=True)

    if "name" in changes and changes["name"] != icon.name:
        old_name = icon.name
        if await _name_taken(session, changes["name"], exclude_id=icon_id):
            raise BizError(CODE_DUPLICATED, t("err.icon_dup"), 409)
        icon.name = changes["name"]
        await _cascade_rename(session, old_name, changes["name"])

    if changes.get("data"):
        raw = await _decode(changes["data"])
        if icon.path:
            # 覆盖同一文件：引用该路径的应用/分组自动获得新图
            current = icon.path

            def _overwrite(bytes_raw: bytes, file_path: str) -> str:
                from app.services.icon import ICON_SIZE

                target = icons_dir() / os.path.basename(file_path)
                from PIL import Image

                with Image.open(io.BytesIO(bytes_raw)) as im:
                    im = im.convert("RGBA")
                    side = min(im.size)
                    square = im.crop(
                        ((im.width - side) // 2, (im.height - side) // 2,
                         (im.width + side) // 2, (im.height + side) // 2)
                    ).resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                    square.save(target, "PNG")
                return file_path

            icon.path = await run_in_threadpool(_overwrite, raw, current)
        else:
            # 内置图标首次设置覆盖图
            icon.path = await run_in_threadpool(save_icon, raw, body.filename)

    await session.commit()
    return ok(IconOut.model_validate(icon).model_dump())


async def _cascade_rename(session: AsyncSession, old_name: str, new_name: str) -> None:
    """内置图标改名后，同步引用（应用/分组/常用精选），避免悬空。"""
    from sqlalchemy import update

    await session.execute(
        update(App).where(App.icon == old_name, App.icon_type == "element").values(icon=new_name)
    )
    await session.execute(
        update(Category)
        .where(Category.icon == old_name, Category.icon_type == "element")
        .values(icon=new_name)
    )
    setting = await session.scalar(select(Setting).where(Setting.key == _FAV_KEY))
    if setting and setting.get_value() and old_name in setting.get_value():
        favs = [new_name if f == old_name else f for f in setting.get_value()]
        setting.value = json.dumps(favs, ensure_ascii=False)


@router.delete("/icons/{icon_id}")
async def delete_icon(
    icon_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """删除图标：被引用时 4003；内置软删（不复活），自定义物理删除并清理文件。"""
    icon = await _get_or_404(session, icon_id)
    used_apps = await session.scalar(
        select(func.count()).where(
            App.icon == (icon.element_name or icon.name)
            if icon.source == "builtin"
            else App.icon == icon.path
        )
    )
    used_cats = await session.scalar(
        select(func.count()).where(
            Category.icon == (icon.element_name or icon.name)
            if icon.source == "builtin"
            else Category.icon == icon.path
        )
    )
    used = (used_apps or 0) + (used_cats or 0)
    if used:
        raise BizError(
            CODE_CONFLICT, t("err.icon_in_use", n=used), 409
        )
    if icon.source == "builtin":
        icon.hidden = True  # 软删除：前端重新播种不会复活
    else:
        await session.delete(icon)
        if icon.path:
            try:
                os.remove(icons_dir() / os.path.basename(icon.path))
            except OSError:
                pass
    await session.commit()
    return ok(None, t("ok.icon_deleted"))
