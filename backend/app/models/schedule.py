"""效率模块模型（M13；dev-plan P16.1）：日历事件与待办。"""

from datetime import date, time

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CalendarEvent(Base, TimestampMixin):
    """日历事件（M13-1/3/4/5）：重复规则 + 提醒 + 农历支持。"""

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(128))
    note: Mapped[str] = mapped_column(Text, default="")
    event_date: Mapped[date] = mapped_column(Date)  # 首次发生日期（重复规则的基准）
    event_time: Mapped[time | None] = mapped_column(Time, default=None)  # 空=全天（不提醒）
    # none/daily/weekly/monthly/yearly/custom（custom 按 interval_days 间隔）
    repeat: Mapped[str] = mapped_column(String(16), default="none")
    interval_days: Mapped[int] = mapped_column(Integer, default=1)
    lunar: Mapped[bool] = mapped_column(Boolean, default=False)  # yearly+lunar：农历生日/节日
    remind_minutes: Mapped[int] = mapped_column(Integer, default=0)  # 提前提醒分钟（0=准点）
    last_remind_key: Mapped[str] = mapped_column(String(64), default="")  # 已提醒的occurrence键


class Todo(Base, TimestampMixin):
    """待办（M13-2）：按日期分组勾选。"""

    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(128))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    todo_date: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
