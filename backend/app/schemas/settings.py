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
    # 证书监控域名（P10.5）：["example.com", …] ≤20
    "monitor.cert_hosts",
    # AI 助手（P13/M05）
    "ai.context_rounds",
    "ai.context_aware",
    "ai.active_provider_id",
    # 首页小组件与快捷搜索（P15/M02）
    "home.weather_city",
    "home.search_shortcuts",
    # 效率模块（P16/M11/M12）
    "files.roots",
    "downloads.enabled",
    "downloads.qb_url",
    "downloads.qb_user",
    "downloads.qb_pass",
    "media.jellyfin_url",
    "media.jellyfin_key",
    # 安全与系统完善（P17）
    "security.allow_register",
    "security.password_min_length",
    "security.force_totp",
    "backup.enabled",
    "backup.keep",
    "update.repo",
    "update.channel",
    "update.auto_check",
    "update.auto_apply",
    # 自定义 CSS（P17.2/M14-4）
    "appearance.custom_css",
    # MySQL 同步（P23）：mysql.* 专由 /api/settings/sync 管理端点写入（密码加密）
}


PASSWORD_MIN_DEFAULT = 8


def _min_password_len(setting_value: int | None = None) -> int:
    """密码最小长度（P17.3）：优先取设置键 security.password_min_length。"""
    if setting_value is not None and 4 <= int(setting_value) <= 128:
        return int(setting_value)
    return PASSWORD_MIN_DEFAULT


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
            if key == "home.weather_city" and (
                not isinstance(value, str) or len(value) > 60
            ):
                raise ValueError(t("err.monitor_range"))
            if key == "files.roots" and (
                not isinstance(value, list)
                or len(value) > 20
                or not all(
                    isinstance(x, dict) and isinstance(x.get("path"), str) for x in value
                )
            ):
                raise ValueError(t("err.monitor_range"))
            if key == "downloads.enabled" and not isinstance(value, bool):
                raise ValueError(t("err.monitor_range"))
            if key in ("downloads.qb_url", "downloads.qb_user", "downloads.qb_pass",
                       "media.jellyfin_url", "media.jellyfin_key") and (
                not isinstance(value, str) or len(value) > 500
            ):
                raise ValueError(t("err.monitor_range"))
            if key == "home.search_shortcuts" and (
                not isinstance(value, list)
                or len(value) > 20
                or not all(
                    isinstance(x, dict)
                    and isinstance(x.get("keyword"), str)
                    and isinstance(x.get("url"), str)
                    for x in value
                )
            ):
                raise ValueError(t("err.shortcuts_invalid"))
            if key == "ai.context_rounds" and (
                not isinstance(value, int) or not 0 <= value <= 20
            ):
                raise ValueError(t("err.monitor_range"))
            if key in ("ai.context_aware",) and not isinstance(value, bool):
                raise ValueError(t("err.monitor_range"))
            if key == "ai.active_provider_id" and (
                not isinstance(value, int) or value < 0
            ):
                raise ValueError(t("err.monitor_range"))
            if key == "monitor.cert_hosts" and (
                not isinstance(value, list)
                or len(value) > 20
                or not all(isinstance(h, str) and 0 < len(h) <= 253 for h in value)
            ):
                raise ValueError(t("err.cert_hosts_invalid"))
        return v
