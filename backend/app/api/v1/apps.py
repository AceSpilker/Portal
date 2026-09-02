"""应用与访问入口接口（M03-1/4、M04-1~6、M03-5/6/13；dev-plan P2.2~2.5）。

权限：列表/详情 A 读，全部写操作 M（管理员）。
注意：export/import/sort/upload-icon/favicon 等固定路径必须先于 /{app_id} 注册。
"""

import base64
import binascii
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import String, cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_admin
from app.core.response import CODE_NOT_FOUND, BizError, ok
from app.db.session import get_session
from app.models.portal import App, AppUrl, Category
from app.models.user import User
from app.schemas.portal import (
    AppCreate,
    AppOut,
    AppSortRequest,
    AppUpdate,
    AppUrlCreate,
    AppUrlOut,
    AppUrlUpdate,
    ExportPayload,
    IconUploadRequest,
)
from app.services.icon import fetch_favicon, save_icon

router = APIRouter()


async def _get_app(session: AsyncSession, app_id: int, *, with_urls: bool = True) -> App:
    stmt = select(App)
    if with_urls:
        stmt = stmt.options(selectinload(App.urls))
    app = await session.scalar(stmt.where(App.id == app_id, App.deleted.is_(False)))
    if app is None:
        raise BizError(CODE_NOT_FOUND, "应用不存在", 404)
    return app


async def _ensure_category(session: AsyncSession, category_id: int | None) -> None:
    if category_id is not None and await session.get(Category, category_id) is None:
        raise BizError(CODE_NOT_FOUND, "目标分组不存在", 404)


# ============ 固定路径（先注册）============


@router.get("/apps/export")
async def export_apps(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """JSON 全量导出（应用+分组+入口，M03-13）；回收站内应用不导出。"""
    cats = (
        (await session.execute(select(Category).order_by(Category.sort, Category.id)))
        .scalars()
        .all()
    )
    apps = (
        (
            await session.execute(
                select(App)
                .options(selectinload(App.urls))
                .where(App.deleted.is_(False))
                .order_by(App.sort, App.id)
            )
        )
        .scalars()
        .all()
    )
    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "icon": c.icon,
                "icon_type": c.icon_type,
                "sort": c.sort,
                "collapsed": c.collapsed,
            }
            for c in cats
        ],
        "apps": [AppOut.model_validate(a).model_dump() for a in apps],
    }
    return ok(payload)


@router.post("/apps/import")
async def import_apps(
    body: ExportPayload,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """JSON 全量导入（覆盖式：清空现有应用/分组/入口后按文件重建，id 保留）。"""
    await session.execute(delete(AppUrl))
    await session.execute(delete(App))
    await session.execute(delete(Category))

    for c in body.categories:
        session.add(Category(id=c.id, name=c.name, icon=c.icon, sort=c.sort, collapsed=c.collapsed))
    url_count = 0
    for a in body.apps:
        session.add(
            App(
                id=a.id,
                name=a.name,
                description=a.description,
                icon=a.icon,
                icon_type=a.icon_type,
                category_id=a.category_id,
                sort=a.sort,
                enabled=a.enabled,
                health_type=a.health_type,
                health_target=a.health_target,
                health_interval=a.health_interval,
                open_mode=a.open_mode,
                visibility=a.visibility,
                favorite=a.favorite,
                tags=a.tags,
                remark=a.remark,
                doc_url=a.doc_url,
            )
        )
        for idx, u in enumerate(a.urls):
            session.add(
                AppUrl(
                    app_id=a.id,
                    access_type=u.access_type,
                    url=u.url,
                    label=u.label,
                    sort=u.sort if u.sort is not None else idx,
                )
            )
            url_count += 1
    await session.commit()
    result = {"categories": len(body.categories), "apps": len(body.apps), "urls": url_count}
    return ok(result, "导入成功")


@router.put("/apps/sort")
async def sort_apps(
    body: AppSortRequest,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """批量保存排序与所属分组（幂等：重复提交结果一致）。"""
    for item in body.items:
        app = await session.get(App, item.id)
        if app is None or app.deleted:
            continue
        app.sort = item.sort
        if item.category_id is not None:
            await _ensure_category(session, item.category_id)
            app.category_id = item.category_id
    await session.commit()
    return ok(None, "排序已保存")


@router.post("/apps/upload-icon")
async def upload_icon(
    body: IconUploadRequest,
    _: User = Depends(require_admin),
):
    """图标上传：base64 随加密信封传输（P24），服务端压方存 data/icons。"""
    try:
        raw = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BizError(2001, "图标数据不是有效的 base64", 422) from exc
    if not raw:
        raise BizError(2001, "图标数据为空", 422)
    url_path = await run_in_threadpool(save_icon, raw, body.filename)
    return ok({"url": url_path})


@router.get("/apps/favicon")
async def fetch_site_favicon(url: str, _: User = Depends(require_admin)):
    """抓取目标站图标（M03-6）：失败/超时按业务失败 4004 返回，不炸接口。"""
    raw = await fetch_favicon(url.strip())
    url_path = await run_in_threadpool(save_icon, raw, "favicon.png")
    return ok({"url": url_path})


# ============ 列表与 CRUD ============


@router.get("/apps")
async def list_apps(
    keyword: str = "",
    category: int | None = None,
    tag: str = "",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """应用列表：关键词（名称/描述/标签）、分组、标签过滤 + 可见性过滤。"""
    stmt = select(App).options(selectinload(App.urls)).where(App.deleted.is_(False))
    if user.role != "admin":
        stmt = stmt.where(App.visibility == "all")
    if keyword.strip():
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            App.name.ilike(kw) | App.description.ilike(kw) | cast(App.tags, String).ilike(kw)
        )
    if category is not None:
        stmt = stmt.where(App.category_id == category)
    if tag.strip():
        stmt = stmt.where(cast(App.tags, String).ilike(f'%"{tag.strip()}"%'))
    apps = (await session.execute(stmt.order_by(App.sort, App.id))).scalars().all()
    return ok([AppOut.model_validate(a).model_dump() for a in apps])


@router.post("/apps")
async def create_app(
    body: AppCreate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await _ensure_category(session, body.category_id)
    app = App(**body.model_dump())
    app.urls = []  # 预加载空关系，避免响应序列化触发异步惰性加载
    session.add(app)
    await session.commit()  # flush 已回填自增 id；不 refresh 以免 urls 关系被置回未加载态
    return ok(AppOut.model_validate(app).model_dump())


@router.get("/apps/{app_id}")
async def get_app(
    app_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(session, app_id)
    if user.role != "admin" and app.visibility != "all":
        raise BizError(CODE_NOT_FOUND, "应用不存在", 404)
    return ok(AppOut.model_validate(app).model_dump())


@router.put("/apps/{app_id}")
async def update_app(
    app_id: int,
    body: AppUpdate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(session, app_id)
    changes = body.model_dump(exclude_unset=True)
    if "category_id" in changes:
        await _ensure_category(session, changes["category_id"])
    for key, value in changes.items():
        setattr(app, key, value)
    await session.commit()
    return ok(AppOut.model_validate(app).model_dump())


@router.delete("/apps/{app_id}")
async def delete_app(
    app_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """删除应用（M03-12 回收站）：软删除，30 天内可恢复（恢复入口 M2 落地）。"""
    app = await _get_app(session, app_id, with_urls=False)
    app.deleted = True
    app.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    return ok(None, "已移入回收站")


# ============ 访问入口（M04-1~6）============


@router.get("/apps/{app_id}/urls")
async def list_urls(
    app_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _get_app(session, app_id, with_urls=False)
    urls = (
        (
            await session.execute(
                select(AppUrl).where(AppUrl.app_id == app_id).order_by(AppUrl.sort, AppUrl.id)
            )
        )
        .scalars()
        .all()
    )
    return ok([AppUrlOut.model_validate(u).model_dump() for u in urls])


@router.post("/apps/{app_id}/urls")
async def create_url(
    app_id: int,
    body: AppUrlCreate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await _get_app(session, app_id, with_urls=False)
    if body.sort is None:
        max_sort = await session.scalar(
            select(func.max(AppUrl.sort)).where(AppUrl.app_id == app_id)
        )
        body.sort = (max_sort or 0) + 1
    url = AppUrl(app_id=app_id, **body.model_dump())
    session.add(url)
    await session.commit()
    await session.refresh(url)
    return ok(AppUrlOut.model_validate(url).model_dump())


@router.put("/app-urls/{url_id}")
async def update_url(
    url_id: int,
    body: AppUrlUpdate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    url = await session.get(AppUrl, url_id)
    if url is None:
        raise BizError(CODE_NOT_FOUND, "入口不存在", 404)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(url, key, value)
    await session.commit()
    return ok(AppUrlOut.model_validate(url).model_dump())


@router.delete("/app-urls/{url_id}")
async def delete_url(
    url_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    url = await session.get(AppUrl, url_id)
    if url is None:
        raise BizError(CODE_NOT_FOUND, "入口不存在", 404)
    await session.delete(url)
    await session.commit()
    return ok(None, "入口已删除")
