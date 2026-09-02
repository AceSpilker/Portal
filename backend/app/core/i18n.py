"""后端国际化（i18n）：按请求 Accept-Language 返回对应语言的提示文案。

- 中间件在每请求开始时 set_locale()（api-spec §1：Accept-Language 约定）；
- 业务代码统一用 t(key, **kwargs) 取文案；默认 zh-CN；
- pydantic 校验器在请求上下文内执行，同样经 t() 本地化。
"""

from __future__ import annotations

import contextvars

_locale: contextvars.ContextVar[str] = contextvars.ContextVar("locale", default="zh-CN")

SUPPORTED = ("zh-CN", "en")


def get_locale() -> str:
    return _locale.get()


def set_locale(lang: str | None) -> None:
    _locale.set("en" if (lang or "").lower().startswith("en") else "zh-CN")


def t(key: str, **kwargs) -> str:
    msg = MESSAGES.get(key, {}).get(get_locale())
    if msg is None:
        msg = MESSAGES.get(key, {}).get("zh-CN", key)
    return msg.format(**kwargs) if kwargs else msg


MESSAGES: dict[str, dict[str, str]] = {
    # ---- 认证 ----
    "err.already_initialized": {"zh-CN": "系统已初始化", "en": "System already initialized"},
    "err.login_locked": {
        "zh-CN": "失败次数过多，请 1 分钟后再试",
        "en": "Too many failures. Try again in 1 minute",
    },
    "err.bad_credentials": {"zh-CN": "用户名或密码错误", "en": "Incorrect username or password"},
    "err.account_disabled": {"zh-CN": "账号已被禁用", "en": "Account disabled"},
    "err.token_missing": {"zh-CN": "缺少 refresh token", "en": "Missing refresh token"},
    "err.token_invalid": {"zh-CN": "登录状态无效", "en": "Invalid session"},
    "err.refresh_invalid": {"zh-CN": "refresh token 无效", "en": "Invalid refresh token"},
    "err.account_invalid": {"zh-CN": "账号不存在或已禁用", "en": "Account not found or disabled"},
    "err.token_expired": {
        "zh-CN": "登录已过期，请重新登录",
        "en": "Session expired, please sign in again",
    },
    "err.password_changed": {
        "zh-CN": "密码已变更，请重新登录",
        "en": "Password changed, please sign in again",
    },
    "err.old_password": {"zh-CN": "旧密码不正确", "en": "Old password is incorrect"},
    "ok.password_changed": {
        "zh-CN": "密码已修改，请重新登录",
        "en": "Password changed, please sign in again",
    },
    "ok.logged_out": {"zh-CN": "已登出", "en": "Signed out"},
    # ---- 权限 ----
    "err.admin_required": {"zh-CN": "需要管理员权限", "en": "Administrator privilege required"},
    # ---- 分组 ----
    "err.category_dup": {"zh-CN": "分组名已存在", "en": "Group name already exists"},
    "err.category_not_found": {"zh-CN": "分组不存在", "en": "Group not found"},
    "ok.category_deleted": {"zh-CN": "分组已删除", "en": "Group deleted"},
    "ok.sorted": {"zh-CN": "排序已保存", "en": "Order saved"},
    # ---- 应用 ----
    "err.app_not_found": {"zh-CN": "应用不存在", "en": "App not found"},
    "ok.app_recycled": {"zh-CN": "已移入回收站", "en": "Moved to recycle bin"},
    "ok.imported": {"zh-CN": "导入成功", "en": "Import successful"},
    "ok.sorted_apps": {"zh-CN": "排序已保存", "en": "Order saved"},
    # ---- 图标 ----
    "err.icon_not_found": {"zh-CN": "图标不存在", "en": "Icon not found"},
    "err.icon_dup": {"zh-CN": "图标名称已存在", "en": "Icon name already exists"},
    "err.icon_base64": {
        "zh-CN": "图标数据不是有效的 base64",
        "en": "Icon data is not valid base64",
    },
    "err.icon_empty": {"zh-CN": "图标数据为空", "en": "Icon data is empty"},
    "err.icon_too_large": {"zh-CN": "图标文件不能超过 2MB", "en": "Icon file must be ≤2MB"},
    "err.icon_unrecognized": {"zh-CN": "无法识别的图片文件", "en": "Unrecognized image file"},
    "err.icon_in_use": {
        "zh-CN": "该图标正被 {n} 个应用/分组使用，请先更换图标后再删除",
        "en": "This icon is used by {n} app(s)/group(s). Replace it before deleting",
    },
    "ok.icon_deleted": {"zh-CN": "图标已删除", "en": "Icon deleted"},
    "err.bad_url": {
        "zh-CN": "url 需为合法的 http(s) 地址",
        "en": "url must be a valid http(s) address",
    },
    "err.favicon_failed": {
        "zh-CN": "抓取图标失败：{reason}",
        "en": "Failed to fetch favicon: {reason}",
    },
    "err.favicon_not_found": {
        "zh-CN": "未能获取目标站图标",
        "en": "Could not fetch the site favicon",
    },
    # ---- 设置 ----
    "ok.settings_saved": {"zh-CN": "设置已保存", "en": "Settings saved"},
    "err.settings_unknown_keys": {
        "zh-CN": "不支持的设置项：{keys}",
        "en": "Unsupported setting keys: {keys}",
    },
    "err.site_name_empty": {"zh-CN": "站点名称不能为空", "en": "Site name must not be empty"},
    "err.tag_options_invalid": {
        "zh-CN": "标签选项需为非空字符串数组",
        "en": "Tag options must be an array of non-empty strings",
    },
    "err.tag_options_max": {"zh-CN": "标签选项最多 50 个", "en": "Up to 50 tag options"},
    "err.icon_fav_invalid": {
        "zh-CN": "常用图标需为非空字符串数组",
        "en": "Favorites must be an array of non-empty strings",
    },
    "err.icon_fav_max": {"zh-CN": "常用图标最多 100 个", "en": "Up to 100 favorite icons"},
    "err.sync_interval": {
        "zh-CN": "同步间隔需为 1~1440 分钟",
        "en": "Sync interval must be 1-1440 minutes",
    },
    # ---- 校验（schemas 校验器）----
    "v.category_empty": {"zh-CN": "分组名不能为空", "en": "Group name must not be empty"},
    "v.app_name_empty": {"zh-CN": "应用名不能为空", "en": "App name must not be empty"},
    "v.url_empty": {"zh-CN": "url 不能为空", "en": "url must not be empty"},
    "v.username_rule": {
        "zh-CN": "用户名需 3~32 位，仅限字母/数字/下划线/中划线",
        "en": "Username must be 3-32 chars: letters/digits/underscore/hyphen only",
    },
    "v.password_rule": {
        "zh-CN": "密码至少 8 位，且同时包含字母与数字",
        "en": "Password needs 8+ characters with both letters and digits",
    },
    "v.icon_name_empty": {"zh-CN": "图标名称不能为空", "en": "Icon name must not be empty"},
    "v.icon_data_empty": {"zh-CN": "图标数据不能为空", "en": "Icon data must not be empty"},
    # ---- 校验格式化（response.py）----
    "v.prefix": {"zh-CN": "参数校验失败：", "en": "Validation failed: "},
    "v.missing": {"zh-CN": "{field} 为必填项", "en": "{field} is required"},
    "v.too_short": {
        "zh-CN": "{field} 长度不能少于 {n} 个字符",
        "en": "{field} must be at least {n} characters",
    },
    "v.too_long": {
        "zh-CN": "{field} 长度不能超过 {n} 个字符",
        "en": "{field} must be at most {n} characters",
    },
    "v.pattern": {"zh-CN": "{field} 格式不正确", "en": "{field} has an invalid format"},
    "v.string_type": {"zh-CN": "{field} 需为字符串", "en": "{field} must be a string"},
    "v.int_parsing": {"zh-CN": "{field} 需为数字", "en": "{field} must be a number"},
    "v.gte": {"zh-CN": "{field} 不能小于 {n}", "en": "{field} must be ≥ {n}"},
    "v.lte": {"zh-CN": "{field} 不能大于 {n}", "en": "{field} must be ≤ {n}"},
    "v.invalid": {"zh-CN": "{field} 参数不合法", "en": "{field} is invalid"},
}
