"""工具箱模型（M10；api-spec §3.10 wol_targets）。"""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WolTarget(Base, TimestampMixin):
    __tablename__ = "wol_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    mac: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")
