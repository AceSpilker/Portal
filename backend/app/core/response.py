"""统一响应与业务异常（契约见 api-spec §1/§2）。"""

from typing import Any

from fastapi.responses import JSONResponse

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


# ---- 参数校验错误的人性化格式化（api-spec §2：2001 message 携带明细）----

_FIELD_LABELS = {
    "username": "用户名",
    "password": "密码",
    "old_password": "旧密码",
    "new_password": "新密码",
    "site_name": "站点名称",
    "name": "名称",
    "description": "描述",
    "url": "地址",
    "label": "标签",
    "sort": "排序",
    "access_type": "入口类型",
    "icon_type": "图标类型",
    "icon": "图标",
    "category_id": "分组",
    "open_mode": "打开方式",
    "visibility": "可见性",
    "health_type": "探活方式",
    "health_target": "探活目标",
    "health_interval": "探活间隔",
    "tags": "标签",
    "remark": "备注",
    "doc_url": "文档链接",
    "values": "设置值",
    "apps.tag_options": "标签选项",
    "general.site_name": "站点名称",
    "filename": "文件名",
    "data": "数据",
}


def _field_label(loc: tuple) -> str:
    """取 loc 末段字段名（跳过 body）并翻译为中文标签；未知字段原样返回。"""
    segments = [str(seg) for seg in loc if seg != "body"]
    leaf = segments[-1] if segments else ""
    return _FIELD_LABELS.get(leaf, leaf)


def _format_one_error(err: dict) -> str:
    etype = str(err.get("type", ""))
    ctx = err.get("ctx") or {}
    label = _field_label(err.get("loc", ()))
    if etype == "value_error":
        # 项目自定义校验器的中文 message 已自描述，直接使用
        return str(ctx.get("error", err.get("msg", "参数不合法")))
    if etype == "missing":
        return f"{label} 为必填项" if label else "缺少必填参数"
    if etype == "string_too_short":
        return f"{label} 长度不能少于 {ctx.get('min_length', '?')} 个字符"
    if etype == "string_too_long":
        return f"{label} 长度不能超过 {ctx.get('max_length', '?')} 个字符"
    if etype == "string_pattern_mismatch":
        return f"{label} 格式不正确"
    if etype == "string_type":
        return f"{label} 需为字符串" if label else "参数需为字符串"
    if etype == "int_parsing":
        return f"{label} 需为数字"
    if etype in ("greater_than_equal", "greater_than"):
        return f"{label} 不能小于 {ctx.get('ge', ctx.get('gt', '?'))}"
    if etype in ("less_than_equal", "less_than"):
        return f"{label} 不能大于 {ctx.get('le', ctx.get('lt', '?'))}"
    # 兜底：清理 pydantic 前缀后使用原始 message
    msg = str(err.get("msg", "参数不合法")).removeprefix("Value error, ")
    if label and not msg.startswith(label):
        return f"{label} {msg}"
    return msg


def format_validation_errors(errors: list[dict]) -> str:
    """把 pydantic 错误列表格式化为用户可读的中文 message。"""
    parts = [_format_one_error(err) for err in errors[:3]]
    return "参数校验失败：" + "；".join(parts)
