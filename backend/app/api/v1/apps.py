"""应用与访问入口接口（M03-1/4、M04-1~6、M03-5/6/13；dev-plan P2.2~2.5）。

权限：列表/详情 A 读，全部写操作 M（管理员）。
注意：export/import/sort/upload-icon/favicon 等固定路径必须先于 /{app_id} 注册。
"""

import base64
import binascii
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, cast, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, CODE_VALIDATION, BizError, ok
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
from app.services.audit import write_audit
from app.services.icon import fetch_favicon, save_icon

router = APIRouter()


async def _get_app(session: AsyncSession, app_id: int, *, with_urls: bool = True) -> App:
    stmt = select(App)
    if with_urls:
        stmt = stmt.options(selectinload(App.urls))
    app = await session.scalar(stmt.where(App.id == app_id, App.deleted.is_(False)))
    if app is None:
        raise BizError(CODE_NOT_FOUND, t("err.app_not_found"), 404)
    return app


async def _ensure_category(session: AsyncSession, category_id: int | None) -> None:
    if category_id is not None and await session.get(Category, category_id) is None:
        raise BizError(CODE_NOT_FOUND, t("err.category_not_found"), 404)


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
    return ok(result, t("ok.imported"))


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
    return ok(None, t("ok.sorted_apps"))


@router.post("/apps/upload-icon")
async def upload_icon(
    body: IconUploadRequest,
    _: User = Depends(require_admin),
):
    """图标上传：base64 随加密信封传输（P24），服务端压方存 data/icons。"""
    try:
        raw = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BizError(2001, t("err.icon_base64"), 422) from exc
    if not raw:
        raise BizError(2001, t("err.icon_empty"), 422)
    url_path = await run_in_threadpool(save_icon, raw, body.filename)
    return ok({"url": url_path})


@router.get("/apps/favicon")
async def fetch_site_favicon(url: str, _: User = Depends(require_admin)):
    """抓取目标站图标（M03-6）：失败/超时按业务失败 4004 返回，不炸接口。"""
    raw = await fetch_favicon(url.strip())
    url_path = await run_in_threadpool(save_icon, raw, "favicon.png")
    return ok({"url": url_path})


# ============ 列表与 CRUD ============


def _visible_to(user: User, app: App) -> bool:
    """非管理员的应用可见性判定（M03-10）：all / public / users(授权列表含自己)。"""
    if app.visibility in ("all", "public"):
        return True
    if app.visibility == "users":
        try:
            return user.id in (json.loads(app.visible_users or "[]"))
        except ValueError:
            return False
    return False


# ---------- P15.1 回收站 / 模板库 / 批量操作（M03-7/13/14~16） ----------


@router.get("/apps/templates")
async def app_templates(_: User = Depends(get_current_user)):
    """内置应用模板库（M03-13）：一键实例化常用自托管服务。"""
    return ok(TEMPLATE_APPS)


class FromTemplateIn(BaseModel):
    key: str
    host: str = Field(min_length=1, max_length=120)  # 如 192.168.1.10，替换 {host}
    category_id: int | None = None


@router.post("/apps/from-template")
async def from_template(
    body: FromTemplateIn,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """模板一键创建（M03-13）：{host} 占位替换后生成应用 + 内网入口。"""
    tpl = next((x for x in TEMPLATE_APPS if x["key"] == body.key), None)
    if tpl is None:
        raise BizError(CODE_NOT_FOUND, t("err.template_not_found"), 404)
    url = tpl["health_target"].format(host=body.host)
    app = App(
        name=tpl["name"], description=tpl["description"], icon=tpl["icon"], icon_type="emoji",
        category_id=body.category_id, health_type=tpl["health_type"], health_target=url,
        tags=tpl["tags"], visibility="all",
    )
    session.add(app)
    await session.commit()
    session.add(AppUrl(app_id=app.id, access_type="lan", url=url, sort=0))
    await session.commit()
    return ok({"id": app.id, "name": app.name, "entry": url})


class BatchIn(BaseModel):
    ids: list[int] = Field(min_length=1)
    op: str = Field(pattern="^(enable|disable|recycle|move)$")
    category_id: int | None = None


@router.post("/apps/batch")
async def batch_apps(
    body: BatchIn,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """批量操作（M03-14~16）：启用/停用/回收站/移动分组。"""
    if body.op == "move" and body.category_id is not None and body.category_id != 0:
        if await session.get(Category, body.category_id) is None:
            raise BizError(CODE_VALIDATION, t("err.category_not_found"), 422)
    from datetime import datetime as dt

    count = 0
    for app_id in body.ids[:100]:
        a = await session.get(App, app_id)
        if a is None or a.deleted:
            continue
        if body.op == "enable":
            a.enabled = True
        elif body.op == "disable":
            a.enabled = False
        elif body.op == "recycle":
            a.deleted = True
            a.deleted_at = dt.utcnow()
        elif body.op == "move":
            a.category_id = body.category_id if body.category_id else None
        count += 1
    await session.commit()
    await write_audit(session, admin.id, "apps_batch", f"批量 {body.op} {count} 个应用", "")
    await session.commit()
    return ok({"count": count})


@router.post("/apps/{app_id}/restore")
async def restore_app(
    app_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """回收站恢复（M03-7）。"""
    a = await session.get(App, app_id)
    if a is None or not a.deleted:
        raise BizError(CODE_NOT_FOUND, t("err.app_not_found"), 404)
    a.deleted = False
    a.deleted_at = None
    await session.commit()
    return ok({"id": a.id})


@router.delete("/apps/{app_id}/purge")
async def purge_app(
    app_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """彻底删除（M03-7）：物理删除应用与入口。"""
    a = await session.get(App, app_id)
    if a is None:
        raise BizError(CODE_NOT_FOUND, t("err.app_not_found"), 404)
    urls = (
        await session.execute(select(AppUrl).where(AppUrl.app_id == app_id))
    ).scalars().all()
    for u in urls:
        await session.delete(u)
    await session.delete(a)
    await session.commit()
    return ok(True)


# ---- P22.2 远期子集：最近使用 ----


@router.post("/apps/{app_id}/opened")
async def mark_app_opened(
    app_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """记录应用被打开（M02-8 最近使用）。"""
    from datetime import datetime

    app = await session.get(App, app_id)
    if app is None or app.deleted:
        raise BizError(CODE_NOT_FOUND, t("err.app_not_found"), 404)
    app.last_opened_at = datetime.utcnow()
    await session.commit()
    return ok({"id": app_id})


@router.get("/apps/recent")
async def recent_apps(
    limit: int = 6,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """最近使用的应用（M02-8）：按 last_opened_at 倒序。"""
    rows = (
        (
            await session.execute(
                select(App)
                .where(App.deleted.is_(False), App.last_opened_at.is_not(None))
                .order_by(App.last_opened_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return ok(
        [
            {"id": a.id, "name": a.name, "icon": a.icon, "icon_type": a.icon_type,
             "last_opened_at": a.last_opened_at.isoformat() + "Z" if a.last_opened_at else None}
            for a in rows
        ]
    )


@router.get("/apps/recycle-bin")
async def recycle_bin(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """回收站列表（M03-7）。"""
    rows = (
        await session.execute(
            select(App).where(App.deleted.is_(True)).order_by(App.deleted_at.desc())
        )
    ).scalars().all()
    return ok(
        [
            {"id": a.id, "name": a.name, "description": a.description,
             "deleted_at": a.deleted_at.isoformat() + "Z" if a.deleted_at else None}
            for a in rows
        ]
    )


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
        # 可见性四级：all=所有登录用户 / users=授权列表 / admin=仅管理员 / public=含访客
        # JSON1 精确匹配授权用户 id（避免字符串子串误命中）
        uid = str(user.id)
        stmt = stmt.where(
            or_(
                App.visibility == "all",
                App.visibility == "public",
                and_(
                    App.visibility == "users",
                    text(
                        "EXISTS (SELECT 1 FROM json_each(apps.visible_users)"
                        " WHERE CAST(json_each.value AS INTEGER) = :uid)"
                    ).bindparams(uid=uid),
                ),
            )
        )
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
    data = body.model_dump()
    if data.get("visible_users") is not None:
        data["visible_users"] = json.dumps(data["visible_users"])
    app = App(**data)
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
    if user.role != "admin" and not _visible_to(user, app):
        raise BizError(CODE_NOT_FOUND, t("err.app_not_found"), 404)
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
    if "visible_users" in changes and changes["visible_users"] is not None:
        changes["visible_users"] = json.dumps(changes["visible_users"])
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
    return ok(None, t("ok.app_recycled"))


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


# ============ 智能解析（M04-10；dev-plan P3.3）============


def _order_urls_by_prefer(urls: list[AppUrl], prefer_types: list[str]) -> list[AppUrl]:
    """按档案的入口类型优先顺序稳定排序；不在偏好中的类型排在末尾（保持原相对次序）。"""
    if not prefer_types:
        return list(urls)

    def _key(u: AppUrl):
        try:
            return (prefer_types.index(u.access_type), u.sort, u.id)
        except ValueError:
            return (len(prefer_types), u.sort, u.id)

    return sorted(urls, key=_key)


async def _effective_profile(session: AsyncSession, user: User, env: str, request: Request):
    """确定解析用的目标档案：显式 pid > 用户手动偏好 > 来源 IP 自动识别（M04-9/10）。"""
    from app.models.network import NetworkProfile
    from app.services.network import client_ip_from_request, enabled_profiles, match_profile

    if env != "auto":
        if not env.isdigit():
            raise BizError(CODE_VALIDATION, t("v.invalid", field="env"), 422)
        profile = await session.get(NetworkProfile, int(env))
        if profile is None:
            raise BizError(CODE_NOT_FOUND, t("err.profile_not_found"), 404)
        return profile
    # 手动偏好优先；档案被删/停用时回退自动识别
    try:
        pref_id = (json.loads(user.prefs or "{}")).get("env_profile_id")
    except ValueError:
        pref_id = None
    if pref_id:
        profile = await session.get(NetworkProfile, int(pref_id))
        if profile is not None and profile.enabled:
            return profile
    return match_profile(client_ip_from_request(request), await enabled_profiles(session))


@router.get("/apps/{app_id}/resolve")
async def resolve_app(
    app_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    env: str = "auto",
    session: AsyncSession = Depends(get_session),
):
    """按当前环境的入口优先级返回推荐入口 + 备选列表（api-spec §4.2）。"""
    app = await _get_app(session, app_id)
    if user.role != "admin" and not _visible_to(user, app):
        raise BizError(CODE_NOT_FOUND, t("err.app_not_found"), 404)
    profile = await _effective_profile(session, user, env, request)
    prefer = (profile.prefer_types if profile else []) or []
    ordered = _order_urls_by_prefer(list(app.urls), prefer)
    recommended = AppUrlOut.model_validate(ordered[0]).model_dump() if ordered else None
    alternatives = [AppUrlOut.model_validate(u).model_dump() for u in ordered[1:]]
    return ok({"recommended": recommended, "alternatives": alternatives})


# ============ 收藏（M02-9；dev-plan P4.5）============


@router.post("/apps/{app_id}/favorite")
async def toggle_favorite(
    app_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """收藏/取消（全局标记，非用户维度；api-spec §4.2 权限 A）。"""
    app = await _get_app(session, app_id, with_urls=False)
    app.favorite = not app.favorite
    await session.commit()
    return ok({"id": app.id, "favorite": app.favorite})


# 内置应用模板库（M03-13）：{host} 由实例化时的主机地址替换
TEMPLATE_APPS = [
    {"key": "qbittorrent", "name": "qBittorrent", "description": "BT/磁力下载工具",
     "icon": "📥", "category": "下载", "health_type": "http",
     "health_target": "http://{host}:8080", "tags": ["下载"]},
    {"key": "jellyfin", "name": "Jellyfin", "description": "免费开源媒体服务器",
     "icon": "🎬", "category": "媒体", "health_type": "http",
     "health_target": "http://{host}:8096", "tags": ["媒体", "影音"]},
    {"key": "plex", "name": "Plex", "description": "媒体服务器",
     "icon": "🎞️", "category": "媒体", "health_type": "http",
     "health_target": "http://{host}:32400", "tags": ["媒体"]},
    {"key": "homeassistant", "name": "Home Assistant", "description": "智能家居中枢",
     "icon": "🏠", "category": "工具", "health_type": "http",
     "health_target": "http://{host}:8123", "tags": ["家庭", "工具"]},
    {"key": "transmission", "name": "Transmission", "description": "轻量 BT 下载",
     "icon": "🧲", "category": "下载", "health_type": "http",
     "health_target": "http://{host}:9091", "tags": ["下载"]},
    {"key": "portainer", "name": "Portainer", "description": "Docker 可视化管理",
     "icon": "🐋", "category": "工具", "health_type": "http",
     "health_target": "http://{host}:9000", "tags": ["工具", "开发"]},
]
