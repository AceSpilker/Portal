"""首页仪表盘接口（M02-2；dev-plan P4.2）：布局读取与保存。权限：A（每用户自己的布局）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, CODE_VALIDATION, BizError, ok
from app.db.session import get_session
from app.models.layout import DashboardLayout
from app.models.user import User

router = APIRouter()

MAX_LAYOUT_JSON_CHARS = 64 * 1024  # 布局体积上限（防膨胀）


class LayoutItem(BaseModel):
    tab: str = Field(default="default", pattern="^[a-zA-Z0-9_-]{1,32}$")
    layout: dict


def _out(row: DashboardLayout) -> dict:
    return {"tab": row.tab, "sort": row.sort, "layout": row.layout}


@router.get("/me/layouts")
async def get_my_layouts(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """当前用户全部标签页的布局（含 0 条）。"""
    rows = (
        (await session.execute(select(DashboardLayout).where(DashboardLayout.user_id == user.id)))
        .scalars()
        .all()
    )
    return ok([_out(r) for r in rows])


@router.put("/me/layouts")
async def save_my_layout(
    body: LayoutItem,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """整份覆盖保存指定标签页的布局（即改即存：前端每次变更后全量 PUT）。"""
    import json

    if len(json.dumps(body.layout, ensure_ascii=False)) > MAX_LAYOUT_JSON_CHARS:
        raise BizError(CODE_VALIDATION, t("v.layout_too_large"), 422)
    row = (
        await session.execute(
            select(DashboardLayout).where(
                DashboardLayout.user_id == user.id, DashboardLayout.tab == body.tab
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DashboardLayout(user_id=user.id, tab=body.tab, layout=body.layout)
        session.add(row)
    else:
        row.layout = body.layout
    await session.commit()
    return ok({"tab": row.tab, "layout": row.layout}, t("ok.layout_saved"))


# ---- 多标签页（M02-5；dev-plan P15.2）----


def _tab_out(row: DashboardLayout) -> dict:
    return {"tab": row.tab, "title": row.title, "sort": row.sort}


async def _my_tab_rows(session: AsyncSession, user_id: int) -> list[DashboardLayout]:
    rows = (
        (
            await session.execute(
                select(DashboardLayout)
                .where(DashboardLayout.user_id == user_id)
                .order_by(DashboardLayout.sort, DashboardLayout.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/me/tabs")
async def list_my_tabs(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """当前用户的标签页清单（每标签页 = 一条布局行；无任何行时返回默认页）。"""
    rows = await _my_tab_rows(session, user.id)
    if not rows:
        return ok([{"tab": "default", "title": "", "sort": 0}])
    return ok([_tab_out(r) for r in rows])


class TabCreate(BaseModel):
    """POST /me/tabs：tab id 服务端生成，仅需标题。"""

    title: str = Field(max_length=64)


class TabItem(BaseModel):
    tab: str = Field(pattern="^[a-zA-Z0-9_-]{1,32}$")
    title: str = Field(default="", max_length=64)
    sort: int = Field(default=0, ge=0, le=9999)


class TabsBody(BaseModel):
    items: list[TabItem] = Field(min_length=1, max_length=20)


@router.post("/me/tabs")
async def create_my_tab(
    body: TabCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """新建标签页（同时创建空白布局行；tab id 由服务端生成，title 必填）。"""
    import secrets

    if not body.title.strip():
        raise BizError(CODE_VALIDATION, t("v.tab_title_required"), 422)
    rows = await _my_tab_rows(session, user.id)
    if len(rows) >= 20:
        raise BizError(CODE_VALIDATION, t("v.tab_too_many"), 422)
    next_sort = (max((r.sort for r in rows), default=0)) + 1
    row = DashboardLayout(
        user_id=user.id,
        tab=secrets.token_hex(4),
        title=body.title.strip(),
        sort=next_sort,
        layout={"order": [], "sizes": {}, "collapsed": {}},
    )
    session.add(row)
    await session.commit()
    return ok(_tab_out(row), t("ok.layout_saved"))


@router.put("/me/tabs")
async def update_my_tabs(
    body: TabsBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """批量更新标签页标题/排序（重命名、拖拽排序；tab id 不可变）。"""
    rows = {r.tab: r for r in await _my_tab_rows(session, user.id)}
    for item in body.items:
        row = rows.get(item.tab)
        if row is None:
            if item.tab != "default":  # 默认页天然存在，首次引用时补建
                raise BizError(CODE_NOT_FOUND, t("err.tab_not_found"), 404)
            row = DashboardLayout(user_id=user.id, tab="default", layout={})
            session.add(row)
            rows["default"] = row
        row.title = item.title.strip()
        row.sort = item.sort
    await session.commit()
    return ok([_tab_out(r) for r in sorted(rows.values(), key=lambda r: (r.sort, r.id))])


@router.delete("/me/tabs/{tab}")
async def delete_my_tab(
    tab: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """删除标签页（连同其布局；默认页不可删）。"""
    if tab == "default":
        raise BizError(CODE_VALIDATION, t("err.tab_default_undeletable"), 422)
    row = (
        await session.execute(
            select(DashboardLayout).where(
                DashboardLayout.user_id == user.id, DashboardLayout.tab == tab
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise BizError(CODE_NOT_FOUND, t("err.tab_not_found"), 404)
    await session.delete(row)
    await session.commit()
    return ok({"tab": tab}, t("ok.layout_saved"))
