"""系统设置 Schema（P7.1；api-spec §4.12：GET/PUT /api/settings，A 读 M 写）。"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.i18n import t

# 可写键白名单 → 每键校验器（防止任意键写入）
WRITABLE_KEYS: set[str] = {
    "general.site_name",
    "general.logo",
    "general.timezone",
    "general.language",
    "appearance.theme_color",
    "appearance.dark_mode",
    "appearance.wallpaper_type",
    "appearance.wallpaper_value",
    "appearance.wallpaper_blur",
    "appearance.wallpaper_mask",
    "apps.tag_options",
    "apps.icon_favorites",
    "sync.enabled",
    "sync.interval_min",
    # 监控（P5）：采样/推送间隔与保留天数
    "guest.enabled",
    "monitor.retention_days",
    "monitor.sample_interval",
    "monitor.push_interval",
}


class SettingsUpdate(BaseModel):
    """批量写：body 即 {key: value} 字典。"""

    values: dict[str, Any] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def _check_keys(cls, v: dict[str, Any]) -> dict[str, Any]:
        bad = set(v) - WRITABLE_KEYS
        if bad:
            raise ValueError(t("err.settings_unknown_keys", keys=", ".join(sorted(bad))))
        for key, value in v.items():
            if key == "general.site_name" and (not isinstance(value, str) or not value.strip()):
                raise ValueError(t("err.site_name_empty"))
            if key == "apps.tag_options":
                if not isinstance(value, list) or not all(
                    isinstance(t, str) and t.strip() for t in value
                ):
                    raise ValueError(t("err.tag_options_invalid"))
                if len(value) > 50:
                    raise ValueError(t("err.tag_options_max"))
            if key == "apps.icon_favorites":
                if not isinstance(value, list) or not all(
                    isinstance(t, str) and t.strip() for t in value
                ):
                    raise ValueError(t("err.icon_fav_invalid"))
                if len(value) > 100:
                    raise ValueError(t("err.icon_fav_max"))
            if key == "sync.interval_min" and (
                not isinstance(value, int) or not 1 <= value <= 1440
            ):
                raise ValueError(t("err.sync_interval"))
            if key == "appearance.wallpaper_type" and value not in (
                "none",
                "solid",
                "gradient",
                "image",
            ):
                raise ValueError(t("err.wallpaper_type"))
            if key in ("appearance.wallpaper_blur", "appearance.wallpaper_mask"):
                limit = 20 if key.endswith("blur") else 90
                if not isinstance(value, int) or not 0 <= value <= limit:
                    raise ValueError(t("err.wallpaper_range"))
            if key == "monitor.retention_days" and (
                not isinstance(value, int) or not 1 <= value <= 365
            ):
                raise ValueError(t("err.monitor_range"))
            if key == "monitor.sample_interval" and (
                not isinstance(value, int) or not 10 <= value <= 3600
            ):
                raise ValueError(t("err.monitor_range"))
            if key == "guest.enabled" and not isinstance(value, bool):
                raise ValueError(t("err.monitor_range"))
            if key == "monitor.push_interval" and (
                not isinstance(value, int) or not 1 <= value <= 60
            ):
                raise ValueError(t("err.monitor_range"))
        return v
