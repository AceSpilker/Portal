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
