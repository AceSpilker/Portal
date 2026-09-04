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
    "v.tab_title_required": {"zh-CN": "标签页名称不能为空", "en": "Tab title is required"},
    "v.tab_too_many": {"zh-CN": "标签页最多 20 个", "en": "At most 20 tabs"},
    "err.tab_not_found": {"zh-CN": "标签页不存在", "en": "Tab not found"},
    "v.credential_secret_required": {
        "zh-CN": "密码与私钥至少填写一项", "en": "Password or private key required"
    },
    "err.credential_not_found": {
        "zh-CN": "SSH 凭据不存在", "en": "SSH credential not found"
    },
    "err.tunnel_not_found": {"zh-CN": "隧道不存在", "en": "Tunnel not found"},
    "err.tunnel_not_running": {"zh-CN": "隧道未在运行", "en": "Tunnel is not running"},
    "err.tunnel_start_failed": {
        "zh-CN": "隧道启动失败：{reason}", "en": "Tunnel start failed: {reason}"
    },
    "ok.tunnel_started": {"zh-CN": "隧道已启动", "en": "Tunnel started"},
    "ok.tunnel_stopped": {"zh-CN": "隧道已停止", "en": "Tunnel stopped"},
    "ok.tunnel_running": {"zh-CN": "隧道运行中", "en": "Tunnel already running"},
    "err.flow_bad_graph": {"zh-CN": "画布图不合法：{reason}", "en": "Invalid flow graph: {reason}"},
    "v.flow_import_invalid": {
        "zh-CN": "导入的 Flow 数据不合法", "en": "Invalid flow import payload"
    },
    "err.redis_not_configured": {"zh-CN": "Redis 未配置", "en": "Redis not configured"},
    "err.redis_unreachable": {
        "zh-CN": "Redis 连接失败，已保持内存模式", "en": "Redis unreachable, kept memory mode"
    },
    "err.mysql_not_configured": {"zh-CN": "MySQL 未配置", "en": "MySQL not configured"},
    "err.restore_confirm_required": {
        "zh-CN": "缺少 confirm=true 覆盖确认", "en": "confirm=true required"
    },
    "ok.restored": {"zh-CN": "已从 MySQL 恢复", "en": "Restored from MySQL"},
    "err.totp_code_required": {"zh-CN": "请输入两步验证码", "en": "TOTP code required"},
    "err.totp_code_invalid": {
        "zh-CN": "验证码或恢复码不正确", "en": "Invalid TOTP code or recovery code"
    },
    "err.totp_already": {"zh-CN": "两步验证已开启", "en": "TOTP already enabled"},
    "err.totp_not_setup": {"zh-CN": "请先生成 TOTP 密钥", "en": "Run TOTP setup first"},
    "err.totp_not_enabled": {"zh-CN": "两步验证未开启", "en": "TOTP not enabled"},
    "err.register_disabled": {"zh-CN": "未开放注册", "en": "Registration is disabled"},
    "err.username_taken": {"zh-CN": "用户名已存在", "en": "Username already taken"},
    "err.session_not_found": {"zh-CN": "会话不存在", "en": "Session not found"},
    "err.session_revoked_login": {
        "zh-CN": "会话已被吊销，请重新登录", "en": "Session revoked, please sign in again"
    },
    "err.token_not_found": {"zh-CN": "Token 不存在", "en": "Token not found"},
    "err.token_readonly": {
        "zh-CN": "只读 Token 不允许写操作", "en": "Read-only token cannot write"
    },
    "err.update_not_git": {
        "zh-CN": "当前部署不是源码仓库，无法在线更新", "en": "Not a git deployment"
    },
    "err.update_checkout_failed": {
        "zh-CN": "切换版本失败，已保持原版本", "en": "Checkout failed, kept current version"
    },
    "err.update_rolled_back": {
        "zh-CN": "更新失败已回滚，请查看状态", "en": "Update failed and rolled back"
    },
    "v.password_short": {"zh-CN": "密码低于最小长度要求", "en": "Password too short"},
    "v.backup_invalid": {"zh-CN": "备份文件格式不正确", "en": "Invalid backup payload"},
    "v.update_version_required": {"zh-CN": "请提供目标版本号", "en": "Target version required"},
    "ok.registered": {"zh-CN": "注册成功，请登录", "en": "Registered, please sign in"},
    "ok.totp_enabled": {"zh-CN": "两步验证已开启", "en": "TOTP enabled"},
    "ok.totp_disabled": {"zh-CN": "两步验证已关闭", "en": "TOTP disabled"},
    "ok.session_revoked": {"zh-CN": "会话已下线", "en": "Session revoked"},
    "ok.token_created": {"zh-CN": "Token 已生成（仅显示一次）", "en": "Token created (shown once)"},
    "ok.token_revoked": {"zh-CN": "Token 已吊销", "en": "Token revoked"},
    "ok.factory_reset": {"zh-CN": "已恢复出厂设置", "en": "Factory reset done"},
    "ok.update_applied": {"zh-CN": "更新已应用", "en": "Update applied"},
    "ok.update_applied_reload": {
        "zh-CN": "文件已更新，服务将在数秒内自动重载",
        "en": "Files updated, service reloads in seconds",
    },
    "notify.update_available": {
        "zh-CN": "发现新版本 {version}", "en": "New version {version} available"
    },
    "err.event_not_found": {"zh-CN": "日程事件不存在", "en": "Event not found"},
    "err.todo_not_found": {"zh-CN": "待办不存在", "en": "Todo not found"},
    "err.file_root_not_found": {
        "zh-CN": "白名单目录不存在或未启用", "en": "Whitelisted root not found or disabled"
    },
    "err.file_not_found": {"zh-CN": "文件不存在", "en": "File not found"},
    "err.file_not_dir": {"zh-CN": "目标不是目录", "en": "Target is not a directory"},
    "err.file_not_file": {"zh-CN": "目标不是文件", "en": "Target is not a file"},
    "err.file_path_forbidden": {"zh-CN": "路径越出白名单范围", "en": "Path escapes whitelist"},
    "err.file_read_failed": {"zh-CN": "目录读取失败", "en": "Failed to read directory"},
    "err.file_too_large": {"zh-CN": "文件超出大小限制", "en": "File exceeds size limit"},
    "err.file_exists": {"zh-CN": "同名文件/目录已存在", "en": "File or directory already exists"},
    "err.file_b64_invalid": {
        "zh-CN": "文件内容 base64 解码失败", "en": "Invalid base64 file content"
    },
    "err.file_dir_not_empty": {"zh-CN": "目录非空，无法删除", "en": "Directory not empty"},
    "err.file_token_invalid": {
        "zh-CN": "预览链接无效或已过期", "en": "Preview link invalid or expired"
    },
    "err.downloads_disabled": {
        "zh-CN": "下载器未启用或未配置", "en": "Downloader not enabled or configured"
    },
    "err.media_disabled": {
        "zh-CN": "媒体库未启用或未配置", "en": "Media server not enabled or configured"
    },
    "err.media_unreachable": {"zh-CN": "媒体库连接失败", "en": "Media server unreachable"},
    "v.date_invalid": {"zh-CN": "日期格式应为 YYYY-MM-DD", "en": "Date must be YYYY-MM-DD"},
    "v.ym_invalid": {"zh-CN": "月份格式应为 YYYY-MM", "en": "Month must be YYYY-MM"},
    "v.repeat_invalid": {"zh-CN": "重复规则无效", "en": "Invalid repeat rule"},
    "v.file_name_invalid": {"zh-CN": "名称不合法", "en": "Invalid name"},
    "v.url_invalid": {"zh-CN": "下载地址不能为空", "en": "Download URL required"},
    "ok.saved": {"zh-CN": "已保存", "en": "Saved"},
    "ok.deleted": {"zh-CN": "已删除", "en": "Deleted"},
    "notify.schedule_reminder": {"zh-CN": "日程提醒：{title}", "en": "Reminder: {title}"},
    "notify.schedule_reminder_body": {
        "zh-CN": "事件即将开始（{time}）", "en": "Event starting at {time}"
    },
    "notify.download_done": {"zh-CN": "下载完成：{name}", "en": "Download completed: {name}"},
    "notify.download_done_body": {
        "zh-CN": "qBittorrent 任务已 100%", "en": "qBittorrent task reached 100%"
    },
    "err.tab_default_undeletable": {
        "zh-CN": "默认标签页不可删除", "en": "Default tab cannot be deleted"
    },
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
    # ---- 首页小组件/快捷搜索（M02/P15）----
    "err.template_not_found": {"zh-CN": "模板不存在", "en": "Template not found"},
    "err.shortcuts_invalid": {
        "zh-CN": "快捷搜索需为 {keyword, url} 数组",
        "en": "Search shortcuts must be a list of {keyword, url}",
    },
    # ---- Flow 自动化（M06/P14）----
    "err.flow_not_found": {"zh-CN": "Flow 不存在", "en": "Flow not found"},
    "err.flow_run_not_found": {"zh-CN": "执行记录不存在", "en": "Flow run not found"},
        "err.flow_bad_trigger": {
        "zh-CN": "触发器类型或参数不合法",
        "en": "Invalid trigger type or config",
    },
    "err.flow_bad_action": {"zh-CN": "动作节点类型不合法", "en": "Invalid action node type"},
    "err.flow_token_invalid": {"zh-CN": "Webhook token 无效", "en": "Invalid webhook token"},
    # ---- AI 助手（M05/P13）----
    "err.provider_not_found": {"zh-CN": "AI Provider 不存在", "en": "AI provider not found"},
    "err.conversation_not_found": {"zh-CN": "会话不存在", "en": "Conversation not found"},
    "err.ai_no_provider": {
        "zh-CN": "请先在 设置 → AI 中配置 Provider",
        "en": "Configure an AI provider in Settings → AI first",    },

    "err.ai_upstream": {"zh-CN": "上游调用失败：", "en": "Upstream error: "},
    "err.ai_bad_draft": {
        "zh-CN": "AI 未返回有效的应用草稿",
        "en": "AI returned no valid app draft",
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
