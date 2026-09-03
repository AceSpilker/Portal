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
    # ---- 监控 ----
    "err.invalid_metric_or_range": {
        "zh-CN": "不支持的指标或时间区间",
        "en": "Unsupported metric or range",
    },
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
    # ---- 网络环境（M04-7/8；P3）----
    "err.profile_not_found": {"zh-CN": "网络环境档案不存在", "en": "Network profile not found"},
    "err.default_profile_exists": {
        "zh-CN": "默认兜底档案已存在（全库仅可有一个）",
        "en": "Default fallback profile already exists (only one allowed)",
    },
    "ok.profile_deleted": {"zh-CN": "环境档案已删除", "en": "Network profile deleted"},
    "ok.env_saved": {"zh-CN": "环境偏好已保存", "en": "Environment preference saved"},
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
    # ---- 布局 / 壁纸（M02；P4）----
    "ok.layout_saved": {"zh-CN": "布局已保存", "en": "Layout saved"},
    "v.layout_too_large": {"zh-CN": "布局数据过大", "en": "Layout payload too large"},
    "err.wallpaper_type": {
        "zh-CN": "壁纸类型仅支持 none/solid/gradient/image",
        "en": "Wallpaper type must be none/solid/gradient/image",
    },
    "err.wallpaper_range": {
        "zh-CN": "壁纸模糊/遮罩取值超出范围",
        "en": "Wallpaper blur/mask value out of range",
    },
    "err.monitor_range": {
        "zh-CN": "监控设置取值超出允许范围",
        "en": "Monitor setting value out of allowed range",
    },
    "err.username_dup": {"zh-CN": "用户名已存在", "en": "Username already exists"},
    "err.user_not_found": {"zh-CN": "用户不存在", "en": "User not found"},
    "err.guest_disabled": {"zh-CN": "访客模式未开启", "en": "Guest mode is disabled"},
    "err.user_self_action": {"zh-CN": "不能对自己执行{action}", "en": "Cannot {action} yourself"},
    "err.last_admin": {
        "zh-CN": "需至少保留一个启用中的管理员，无法{action}",
        "en": "At least one enabled admin must remain, cannot {action}",
    },
    "u.action.disable": {"zh-CN": "禁用", "en": "disable"},
    "u.action.kick": {"zh-CN": "踢出", "en": "kick"},
    "u.action.demote": {"zh-CN": "降级", "en": "demote"},
    "u.action.change_role": {"zh-CN": "修改自己的角色", "en": "change your own role"},
    "ok.user_password_reset": {
        "zh-CN": "密码已重置，该用户需重新登录",
        "en": "Password reset; the user must sign in again",
    },
    "ok.user_kicked": {"zh-CN": "已强制下线", "en": "User kicked"},
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
    "v.profile_name_empty": {
        "zh-CN": "环境档案名称不能为空",
        "en": "Profile name must not be empty",
    },
    "v.cidr_required": {
        "zh-CN": "CIDR 档案至少需要一个网段",
        "en": "A CIDR profile needs at least one network segment",
    },
    "v.cidr_invalid": {
        "zh-CN": "存在无效的 CIDR 网段（如 192.168.1.0/24）",
        "en": "Invalid CIDR segment (e.g. 192.168.1.0/24)",
    },
    "v.prefer_invalid": {
        "zh-CN": "入口优先顺序包含未知入口类型",
        "en": "Entry preference contains an unknown access type",
    },
    "v.prefer_duplicated": {
        "zh-CN": "入口优先顺序不能重复",
        "en": "Entry preference must not contain duplicates",
    },
    # ---- Docker 管理（M08/P12，可选模块）----
    "err.docker_disabled": {
        "zh-CN": "Docker 管理未启用（需开启 DOCKER_SOCK_ENABLED 并挂载 sock）",
        "en": "Docker management is disabled (enable DOCKER_SOCK_ENABLED and mount the sock)",
    },
    "err.docker_not_found": {"zh-CN": "容器不存在", "en": "Container not found"},
    "err.docker_bad_op": {"zh-CN": "不支持的操作", "en": "Unsupported operation"},
    # ---- 端口监控（M18/P11）----
    "err.port_monitor_not_found": {"zh-CN": "端口监控项不存在", "en": "Port monitor not found"},
    "err.port_import_line": {
        "zh-CN": "导入行格式应为 host:port 或 名称|host:port",
        "en": "Import lines must be host:port or name|host:port",
    },
    # ---- 监控告警/证书（M17/P10）----
    "err.alert_rule_not_found": {"zh-CN": "告警规则不存在", "en": "Alert rule not found"},
    "err.cert_hosts_invalid": {
        "zh-CN": "证书监控域名需为 ≤20 条的字符串数组",
        "en": "Certificate hosts must be a list of ≤20 strings",
    },
    # ---- 通知中心（M09/P9）----
    "err.channel_not_found": {"zh-CN": "通知渠道不存在", "en": "Notification channel not found"},
    "notify.test_title": {"zh-CN": "Portal 测试消息", "en": "Portal test message"},
    "notify.test_body": {
        "zh-CN": "这是一条测试通知，收到即表示渠道配置可用",
        "en": "This is a test notification. Receiving it means the channel works",
    },
    # ---- 工具箱（M10）----
    "v.mac_invalid": {
        "zh-CN": "MAC 地址格式不正确",
        "en": "Invalid MAC address",
    },
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
