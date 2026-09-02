"""统一响应与业务异常（契约见 api-spec §1/§2）。"""

from typing import Any

from fastapi.responses import JSONResponse

from app.core.i18n import get_locale, t

# 错误码（api-spec §2）
CODE_OK = 0
CODE_BAD_CREDENTIALS = 1001
CODE_TOKEN_INVALID = 1002
CODE_TOKEN_EXPIRED = 1003
CODE_NOT_INITIALIZED = 1004
CODE_ALREADY_INITIALIZED = 1005
CODE_LOGIN_LOCKED = 1006
CODE_VALIDATION = 2001
CODE_FORBIDDEN = 3001
CODE_NOT_FOUND = 4001
CODE_DUPLICATED = 4002
CODE_CONFLICT = 4003
CODE_TARGET_UNREACHABLE = 4004
CODE_INTERNAL = 5001
CODE_DEPENDENCY_UNAVAILABLE = 5002


class BizError(Exception):
    """业务异常：路由中 raise，由全局处理器转换为统一响应。"""

    def __init__(self, code: int, message: str, http_status: int = 200):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """成功响应体。"""
    return {"code": CODE_OK, "message": message, "data": data}


def fail(code: int, message: str, http_status: int = 200) -> JSONResponse:
    """失败响应体。"""
    return JSONResponse(
        status_code=http_status,
        content={"code": code, "message": message, "data": None},
    )


# ---- 参数校验错误人性化格式化（§2：2001 message 按请求语言本地化）----

_FIELD_LABELS: dict[str, dict[str, str]] = {
    "username": {"zh-CN": "用户名", "en": "username"},
    "password": {"zh-CN": "密码", "en": "password"},
    "old_password": {"zh-CN": "旧密码", "en": "old password"},
    "new_password": {"zh-CN": "新密码", "en": "new password"},
    "site_name": {"zh-CN": "站点名称", "en": "site name"},
    "name": {"zh-CN": "名称", "en": "name"},
    "description": {"zh-CN": "描述", "en": "description"},
    "url": {"zh-CN": "地址", "en": "url"},
    "label": {"zh-CN": "标签", "en": "label"},
    "sort": {"zh-CN": "排序", "en": "sort"},
    "access_type": {"zh-CN": "入口类型", "en": "entry type"},
    "icon_type": {"zh-CN": "图标类型", "en": "icon type"},
    "icon": {"zh-CN": "图标", "en": "icon"},
    "category_id": {"zh-CN": "分组", "en": "group"},
    "open_mode": {"zh-CN": "打开方式", "en": "open mode"},
    "visibility": {"zh-CN": "可见性", "en": "visibility"},
    "health_type": {"zh-CN": "探活方式", "en": "health check type"},
    "health_target": {"zh-CN": "探活目标", "en": "health target"},
    "health_interval": {"zh-CN": "探活间隔", "en": "check interval"},
    "tags": {"zh-CN": "标签", "en": "tags"},
    "remark": {"zh-CN": "备注", "en": "remark"},
    "doc_url": {"zh-CN": "文档链接", "en": "docs link"},
    "values": {"zh-CN": "设置值", "en": "setting values"},
    "apps.tag_options": {"zh-CN": "标签选项", "en": "tag options"},
    "apps.icon_favorites": {"zh-CN": "常用图标", "en": "favorite icons"},
    "general.site_name": {"zh-CN": "站点名称", "en": "site name"},
    "filename": {"zh-CN": "文件名", "en": "filename"},
    "data": {"zh-CN": "数据", "en": "data"},
}


def _field_label(loc: tuple) -> str:
    """取 loc 末段字段名（跳过 body）并翻译为当前语言的标签；未知字段原样返回。"""
    segments = [str(seg) for seg in loc if seg != "body"]
    leaf = segments[-1] if segments else ""
    labels = _FIELD_LABELS.get(leaf)
    if labels:
        return labels.get(get_locale()) or labels["zh-CN"]
    return leaf


def _format_one_error(err: dict) -> str:
    etype = str(err.get("type", ""))
    ctx = err.get("ctx") or {}
    label = _field_label(err.get("loc", ()))
    if etype == "value_error":
        # 项目自定义校验器的 message 已在抛出时本地化（自描述），直接使用
        return str(ctx.get("error", err.get("msg", t("v.invalid", field=label))))
    if etype == "missing":
        return t("v.missing", field=label)
    if etype == "string_too_short":
        return t("v.too_short", field=label, n=ctx.get("min_length", "?"))
    if etype == "string_too_long":
        return t("v.too_long", field=label, n=ctx.get("max_length", "?"))
    if etype == "string_pattern_mismatch":
        return t("v.pattern", field=label)
    if etype == "string_type":
        return t("v.string_type", field=label)
    if etype == "int_parsing":
        return t("v.int_parsing", field=label)
    if etype in ("greater_than_equal", "greater_than"):
        return t("v.gte", field=label, n=ctx.get("ge", ctx.get("gt", "?")))
    if etype in ("less_than_equal", "less_than"):
        return t("v.lte", field=label, n=ctx.get("le", ctx.get("lt", "?")))
    # 兜底：清理 pydantic 前缀后使用原始 message
    msg = str(err.get("msg", t("v.invalid", field=label))).removeprefix("Value error, ")
    if label and not msg.startswith(label):
        return f"{label} {msg}"
    return msg


def format_validation_errors(errors: list[dict]) -> str:
    """把 pydantic 错误列表格式化为当前语言、用户可读的 message。"""
    parts = [_format_one_error(err) for err in errors[:3]]
    return t("v.prefix") + "；".join(parts)
