"""系统设置 Schema（P7.1；api-spec §4.12：GET/PUT /api/settings，A 读 M 写）。"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

# 可写键白名单 → 每键校验器（防止任意键写入）
WRITABLE_KEYS: set[str] = {
    "general.site_name",
    "general.language",
    "appearance.theme_color",
    "appearance.dark_mode",
    "apps.tag_options",
    "apps.icon_favorites",
    "sync.enabled",
    "sync.interval_min",
}


class SettingsUpdate(BaseModel):
    """批量写：body 即 {key: value} 字典。"""

    values: dict[str, Any] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def _check_keys(cls, v: dict[str, Any]) -> dict[str, Any]:
        bad = set(v) - WRITABLE_KEYS
        if bad:
            raise ValueError(f"不支持的设置项：{', '.join(sorted(bad))}")
        for key, value in v.items():
            if key == "general.site_name" and (not isinstance(value, str) or not value.strip()):
                raise ValueError("站点名称不能为空")
            if key == "apps.tag_options":
                if not isinstance(value, list) or not all(
                    isinstance(t, str) and t.strip() for t in value
                ):
                    raise ValueError("标签选项需为非空字符串数组")
                if len(value) > 50:
                    raise ValueError("标签选项最多 50 个")
            if key == "apps.icon_favorites":
                if not isinstance(value, list) or not all(
                    isinstance(t, str) and t.strip() for t in value
                ):
                    raise ValueError("常用图标需为非空字符串数组")
                if len(value) > 100:
                    raise ValueError("常用图标最多 100 个")
            if key == "sync.interval_min" and (
                not isinstance(value, int) or not 1 <= value <= 1440
            ):
                raise ValueError("同步间隔需为 1~1440 分钟")
        return v
