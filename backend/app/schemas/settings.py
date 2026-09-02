"""系统设置 Schema（P7.1；api-spec §4.12：GET/PUT /api/settings，A 读 M 写）。"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.i18n import t

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
        return v
