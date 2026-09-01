"""站点键值配置（M15；api-spec §3.11 settings）。"""
import json
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# 默认设置（键名分组约定：general.* / appearance.* / ai.* / ...）
DEFAULT_SETTINGS: dict[str, str] = {
    "general.site_name": json.dumps("Portal", ensure_ascii=False),
    "general.language": json.dumps("zh-CN"),
    "appearance.theme_color": json.dumps("#4f6ef7"),
    "appearance.dark_mode": json.dumps("auto"),
    "sync.enabled": json.dumps(False),
    "sync.interval_min": json.dumps(30),
}


class Setting(Base, TimestampMixin):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="null")  # JSON 字符串

    def get_value(self) -> Any:
        return json.loads(self.value)
