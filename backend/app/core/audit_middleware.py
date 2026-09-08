"""全站写操作审计中间件（072）：/api 的 POST/PUT/PATCH/DELETE 自动落 audit_logs。

- detail 仅记录 状态码+耗时（不落请求体，杜绝密码等敏感信息入库）；
- user_id 从 Authorization JWT payload 解出（验签已由认证依赖完成，此处只取展示字段；
  未认证的写操作记 user_id=None，同样入库便于发现异常探测）；
- 登录/刷新已由 auth 模块手写业务语义审计，豁免防重复；
- 写入用独立 Session 并静默失败，审计故障不影响业务。
"""

from __future__ import annotations

import base64
import json
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from app.db.session import SessionLocal
from app.models.audit import AuditLog

_AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_PATHS = {"/api/auth/login", "/api/auth/refresh"}


def _user_id_from_auth_header(headers) -> int | None:
    authz = ""
    for k, v in headers:
        if k == b"authorization":
            authz = v.decode("latin-1")
            break
    token = authz[7:].strip() if authz.startswith("Bearer ") else ""
    if not token or token.count(".") != 2:
        return None
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None


class AuditMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _AUDIT_METHODS:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api") or path in _SKIP_PATHS or path.startswith("/api/hooks/"):
            await self.app(scope, receive, send)
            return

        user_id = _user_id_from_auth_header(scope.get("headers", []))
        status_holder = {"code": 500}
        start = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000)
            try:
                import asyncio

                asyncio.get_running_loop().create_task(
                    _write(scope, path, user_id, status_holder["code"], elapsed_ms)
                )
            except Exception:  # noqa: S110 审计失败绝不影响业务
                pass


async def _write(scope: Scope, path: str, user_id: int | None, status: int, ms: int) -> None:
    try:
        async with SessionLocal() as session:
            session.add(
                AuditLog(
                    user_id=user_id,
                    action=f"{scope.get('method', '')} {path}",
                    detail=f"status={status} {ms}ms",
                    ip=_client_ip(scope),
                )
            )
            await session.commit()
    except Exception:  # noqa: S110 同上
        pass


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else ""
