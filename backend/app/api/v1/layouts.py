"""首页仪表盘接口（M02-2；dev-plan P4.2）：布局读取与保存。权限：A（每用户自己的布局）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.i18n import t
from app.core.response import CODE_VALIDATION, BizError, ok
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
