"""日程与待办接口（M13-1~5；dev-plan P16.1；api-spec §4.11）。

- GET /calendar/month?ym=YYYY-MM：当月事件展开（含重复规则）+ 农历节日；
- 日历事件/待办 CRUD（数据按 user_id 隔离，admin 亦仅能看自己的——家庭场景日程私有）；
- 提醒由 reminder_job 落 P9 通知（站内+外部渠道走通知规则路由）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import time as dt_time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, CODE_VALIDATION, BizError, ok
from app.db.session import get_session
from app.models.schedule import CalendarEvent, Todo
from app.models.user import User
from app.services.lunar import festivals_for_year, lunar_to_solar

router = APIRouter()

REPEATS = ("none", "daily", "weekly", "monthly", "yearly", "custom")


def _event_out(e: CalendarEvent) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "note": e.note,
        "date": e.event_date.isoformat(),
        "time": e.event_time.isoformat(timespec="minutes") if e.event_time else None,
        "repeat": e.repeat,
        "interval_days": e.interval_days,
        "lunar": e.lunar,
        "remind_minutes": e.remind_minutes,
    }


def _todo_out(td: Todo) -> dict:
    return {
        "id": td.id,
        "title": td.title,
        "done": td.done,
        "date": td.todo_date.isoformat() if td.todo_date else None,
        "sort": td.sort,
    }


def occurs_on(e: CalendarEvent, d: date) -> bool:
    """事件在某公历日是否发生（重复规则展开；农历按 yearly 生日/纪念日换算）。"""
    if d < e.event_date:
        return False
    if e.lunar:
        # 农历口径：(event_date.month, event_date.day) 视为农历月日，
        # 每年映射到对应公历日（生日/纪念日/农历节日统一走此规则）
        solar = lunar_to_solar(d.year, e.event_date.month, e.event_date.day)
        return solar is not None and solar == d
    if e.repeat == "none":
        return d == e.event_date
    if e.repeat == "daily":
        return True
    if e.repeat == "weekly":
        return d.weekday() == e.event_date.weekday()
    if e.repeat == "monthly":
        return d.day == e.event_date.day
    if e.repeat == "yearly":
        return d.day == e.event_date.day and d.month == e.event_date.month
    if e.repeat == "custom":
        return (d - e.event_date).days % max(1, e.interval_days) == 0
    return False


class EventBody(BaseModel):
    title: str = Field(max_length=128)
    note: str = Field(default="", max_length=2000)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    repeat: str = "none"
    interval_days: int = Field(default=1, ge=1, le=3650)
    lunar: bool = False
    remind_minutes: int = Field(default=0, ge=0, le=10080)


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise BizError(CODE_VALIDATION, t("v.date_invalid"), 422) from exc


async def _own_event(session: AsyncSession, user: User, event_id: int) -> CalendarEvent:
    e = await session.get(CalendarEvent, event_id)
    if e is None or e.user_id != user.id:
        raise BizError(CODE_NOT_FOUND, t("err.event_not_found"), 404)
    return e


@router.get("/calendar/month")
async def calendar_month(
    ym: str = Query(pattern=r"^\d{4}-\d{2}$"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """月视图：当月事件展开（重复规则）+ 农历节日（M13-1/4/5）。"""
    year, month = (int(x) for x in ym.split("-"))
    if not 1900 <= year <= 2100 or not 1 <= month <= 12:
        raise BizError(CODE_VALIDATION, t("v.ym_invalid"), 422)
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    rows = (
        (
            await session.execute(
                select(CalendarEvent).where(
                    CalendarEvent.user_id == user.id,
                    CalendarEvent.event_date < end,
                )
            )
        )
        .scalars()
        .all()
    )
    events = []
    d = start
    one_day = timedelta(days=1)
    while d < end:
        for e in rows:
            if occurs_on(e, d):
                events.append({**_event_out(e), "date": d.isoformat()})
        d += one_day
    return ok(
        {
            "ym": ym,
            "events": events,
            "festivals": [f for f in festivals_for_year(year) if f["date"].startswith(ym)],
        }
    )


@router.post("/calendar/events")
async def create_event(
    body: EventBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if body.repeat not in REPEATS:
        raise BizError(CODE_VALIDATION, t("v.repeat_invalid"), 422)
    e = CalendarEvent(
        user_id=user.id,
        title=body.title.strip(),
        note=body.note,
        event_date=_parse_date(body.date),
        event_time=dt_time.fromisoformat(body.time) if body.time else None,
        repeat=body.repeat,
        interval_days=body.interval_days,
        lunar=body.lunar,
        remind_minutes=body.remind_minutes,
    )
    session.add(e)
    await session.commit()
    return ok(_event_out(e), t("ok.saved"))


@router.put("/calendar/events/{event_id}")
async def update_event(
    event_id: int,
    body: EventBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    e = await _own_event(session, user, event_id)
    if body.repeat not in REPEATS:
        raise BizError(CODE_VALIDATION, t("v.repeat_invalid"), 422)
    e.title = body.title.strip()
    e.note = body.note
    e.event_date = _parse_date(body.date)
    e.event_time = dt_time.fromisoformat(body.time) if body.time else None
    e.repeat = body.repeat
    e.interval_days = body.interval_days
    e.lunar = body.lunar
    e.remind_minutes = body.remind_minutes
    await session.commit()
    return ok(_event_out(e), t("ok.saved"))


@router.delete("/calendar/events/{event_id}")
async def delete_event(
    event_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    e = await _own_event(session, user, event_id)
    await session.delete(e)
    await session.commit()
    return ok({"id": event_id}, t("ok.deleted"))


# ---- 待办（M13-2）----


class TodoBody(BaseModel):
    title: str = Field(max_length=128)
    done: bool = False
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.get("/todos")
async def list_todos(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    rows = (
        (
            await session.execute(
                select(Todo)
                .where(Todo.user_id == user.id)
                .order_by(Todo.done, Todo.todo_date.desc().nullsfirst(), Todo.sort, Todo.id)
            )
        )
        .scalars()
        .all()
    )
    return ok([_todo_out(r) for r in rows])


@router.post("/todos")
async def create_todo(
    body: TodoBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    td = Todo(
        user_id=user.id,
        title=body.title.strip(),
        done=body.done,
        todo_date=_parse_date(body.date) if body.date else None,
    )
    session.add(td)
    await session.commit()
    return ok(_todo_out(td), t("ok.saved"))


@router.put("/todos/{todo_id}")
async def update_todo(
    todo_id: int,
    body: TodoBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    td = await session.get(Todo, todo_id)
    if td is None or td.user_id != user.id:
        raise BizError(CODE_NOT_FOUND, t("err.todo_not_found"), 404)
    td.title = body.title.strip()
    td.done = body.done
    td.todo_date = _parse_date(body.date) if body.date else None
    await session.commit()
    return ok(_todo_out(td), t("ok.saved"))


@router.delete("/todos/{todo_id}")
async def delete_todo(
    todo_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    td = await session.get(Todo, todo_id)
    if td is None or td.user_id != user.id:
        raise BizError(CODE_NOT_FOUND, t("err.todo_not_found"), 404)
    await session.delete(td)
    await session.commit()
    return ok({"id": todo_id}, t("ok.deleted"))


# ---- 提醒（M13-3）：调度任务调用 ----


async def reminder_scan(session: AsyncSession, now: datetime) -> int:
    """扫描到期事件并经 P9 通知（每事件 occurrence 只提醒一次）。返回提醒数。"""
    from app.services.notify import dispatch

    today = now.date()
    rows = (
        (
            await session.execute(
                select(CalendarEvent).where(
                    CalendarEvent.user_id.is_not(None),
                    CalendarEvent.event_time.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    sent = 0
    for e in rows:
        if not occurs_on(e, today):
            continue
        assert e.event_time is not None
        due = datetime.combine(today, e.event_time) - timedelta(minutes=e.remind_minutes)
        # 到点后 12h 内仍可提醒（防错过窗口刷屏），超窗丢弃
        if not (due <= now <= due + timedelta(hours=12)):
            continue
        key = f"{e.id}:{today.isoformat()}:{e.event_time.isoformat(timespec='minutes')}"
        if e.last_remind_key == key:
            continue
        await dispatch(
            session,
            event="schedule.reminder",
            source="schedule",
            title=t("notify.schedule_reminder", title=e.title),
            body=t(
                "notify.schedule_reminder_body",
                time=e.event_time.isoformat(timespec="minutes"),
            ),
        )
        e.last_remind_key = key
        sent += 1
    if sent:
        await session.commit()
    return sent
