"""站点键值配置（M15；api-spec §3.11 settings）。"""

import json
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# 默认设置（键名分组约定：general.* / appearance.* / apps.* / ai.* / sync.* / ...）
DEFAULT_SETTINGS: dict[str, str] = {
    "general.site_name": json.dumps("Portal", ensure_ascii=False),
    "general.language": json.dumps("zh-CN"),
    "appearance.theme_color": json.dumps("#4f6ef7"),
    "appearance.dark_mode": json.dumps("auto"),
    # 壁纸（M02-20）：none / solid（纯色）/ gradient（渐变）/ image（图片 URL）
    "appearance.wallpaper_type": json.dumps("none"),
    "appearance.wallpaper_value": json.dumps(""),
    "appearance.wallpaper_blur": json.dumps(0),
    "appearance.wallpaper_mask": json.dumps(35),
    # 应用表单的标签候选（M03-3，系统配置→应用配置中维护）
    "apps.tag_options": json.dumps(
        ["媒体", "影音", "下载", "工具", "开发", "监控", "网络", "网盘", "家庭", "工作"],
        ensure_ascii=False,
    ),
    # 图标库「常用」精选（M03-5，系统配置→图标库中维护，元素为 Element 图标名）
    "apps.icon_favorites": json.dumps(
        [
            "Monitor",
            "Folder",
            "FolderOpened",
            "Cpu",
            "Download",
            "Upload",
            "Cloudy",
            "VideoPlay",
            "Camera",
            "HomeFilled",
            "Link",
            "Setting",
        ],
        ensure_ascii=False,
    ),
    "sync.enabled": json.dumps(False),
    "sync.interval_min": json.dumps(30),
    # 监控采样保留天数（M17-7，超出自动清理）；采样/推送间隔（秒）
    "monitor.retention_days": json.dumps(7),
    "monitor.sample_interval": json.dumps(60),
    "monitor.push_interval": json.dumps(2),
}


class Setting(Base, TimestampMixin):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="null")  # JSON 字符串

    def get_value(self) -> Any:
        return json.loads(self.value)
