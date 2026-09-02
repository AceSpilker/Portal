"""分组管理接口（M03-2/4；dev-plan P2.1）。权限：A 读 / M 写。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.response import CODE_DUPLICATED, CODE_NOT_FOUND, BizError, ok
from app.db.session import get_session
from app.models.portal import App, Category
from app.models.user import User
from app.schemas.portal import CategoryCreate, CategoryOut, CategorySortRequest, CategoryUpdate

router = APIRouter()


async def _name_taken(session: AsyncSession, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Category.id).where(Category.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    return await session.scalar(stmt) is not None


@router.get("/categories")
async def list_categories(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """分组列表（含未分组外应用计数），按 sort, id 稳定排序。"""
    cats = (
        (await session.execute(select(Category).order_by(Category.sort, Category.id)))
        .scalars()
        .all()
    )
    counts: dict[int, int] = dict(
        (
            await session.execute(
                select(App.category_id, func.count())
                .where(App.deleted.is_(False), App.category_id.is_not(None))
                .group_by(App.category_id)
            )
        ).all()
    )
    data = [
        CategoryOut.model_validate(c).model_dump() | {"app_count": counts.get(c.id, 0)}
        for c in cats
    ]
    return ok(data)


@router.post("/categories")
async def create_category(
    body: CategoryCreate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if await _name_taken(session, body.name):
        raise BizError(CODE_DUPLICATED, "分组名已存在", 409)
    cat = Category(name=body.name, icon=body.icon, sort=body.sort, collapsed=body.collapsed)
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return ok(CategoryOut.model_validate(cat).model_dump())


@router.put("/categories/sort")
async def sort_categories(
    body: CategorySortRequest,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """批量保存排序（幂等：重复提交结果一致）。"""
    for item in body.items:
        await session.execute(update(Category).where(Category.id == item.id).values(sort=item.sort))
    await session.commit()
    return ok(None, "排序已保存")


@router.put("/categories/{category_id}")
async def update_category(
    category_id: int,
    body: CategoryUpdate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    cat = await session.get(Category, category_id)
    if cat is None:
        raise BizError(CODE_NOT_FOUND, "分组不存在", 404)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != cat.name:
        if await _name_taken(session, changes["name"], exclude_id=category_id):
            raise BizError(CODE_DUPLICATED, "分组名已存在", 409)
    for key, value in changes.items():
        setattr(cat, key, value)
    await session.commit()
    await session.refresh(cat)
    return ok(CategoryOut.model_validate(cat).model_dump())


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """删除分组：组内应用不删除，仅移出分组（category_id 置空）。"""
    cat = await session.get(Category, category_id)
    if cat is None:
        raise BizError(CODE_NOT_FOUND, "分组不存在", 404)
    await session.execute(
        update(App).where(App.category_id == category_id).values(category_id=None)
    )
    await session.delete(cat)
    await session.commit()
    return ok(None, "分组已删除")
