"""全站写操作审计中间件（072 建立 / 087 详情增强）：写操作自动落 audit_logs。

- 087 起记录完整执行详情：method/path/query/status/duration_ms/user_agent 拆列入库，
  >=400 时从统一响应 JSON 提取 message 存 error_msg（截断 300 字，杜绝敏感回显）；
  2xx 不落响应体；
- detail 保持人读摘要 `status=200 45ms`（兼容旧展示）；
- 同步 logger 输出一行执行日志：INFO（2xx）/WARNING（4xx）/ERROR（5xx）——
  WARNING+ 由 SystemLogHandler 落 system_logs，与日志中心联动；
- user_id 从 Authorization JWT payload 解出（验签已由认证依赖完成，此处只取展示字段；
  未认证的写操作记 user_id=None，同样入库便于发现异常探测）；
- 登录/刷新已由 auth 模块手写业务语义审计，豁免防重复；
- 写入用独立 Session 并静默失败，审计故障不影响业务。
"""

from __future__ import annotations

import base64
import json
import logging
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from app.db.session import SessionLocal
from app.models.audit import AuditLog

log = logging.getLogger("portal.audit")

_AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_PATHS = {"/api/auth/login", "/api/auth/refresh"}
_ERROR_MSG_MAX = 300
_JSON_TYPES = ("application/json",)


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


def _header(headers, name: bytes) -> str:
    for k, v in headers:
        if k == name:
            return v.decode("latin-1", errors="replace")
    return ""


def _extract_error_message(content_type: str, body: bytes) -> str:
    """>=400 时从统一响应 {code, message} 提取人读错误（截断 300 字）。"""
    if body and any(t in content_type for t in _JSON_TYPES):
        try:
            msg = json.loads(body[:8192]).get("message")
            if isinstance(msg, str) and msg:
                return msg[:_ERROR_MSG_MAX]
        except Exception:
            pass
    return ""


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

        headers = scope.get("headers", [])
        user_id = _user_id_from_auth_header(headers)
        status_holder = {"code": 500}
        body_holder = {"ctype": "", "body": b""}
        start = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                body_holder["ctype"] = _header(message.get("headers", []), b"content-type")
            elif message["type"] == "http.response.body" and status_holder["code"] >= 400:
                # 只收集错误响应体（成功体可能很大且无审计价值）
                if len(body_holder["body"]) < 8192:
                    body_holder["body"] += message.get("body", b"")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000)
            status = status_holder["code"]
            error_msg = (
                _extract_error_message(body_holder["ctype"], body_holder["body"])
                if status >= 400
                else ""
            )
            # 执行日志输出：2xx=INFO，4xx=WARNING，5xx=ERROR（WARNING+ 落 system_logs）
            level = (
                logging.INFO if status < 400 else logging.WARNING if status < 500 else logging.ERROR
            )
            log.log(
                level,
                "audit %s %s -> %d %dms user=%s ip=%s %s",
                scope.get("method", ""), path, status, elapsed_ms,
                user_id if user_id is not None else "-",
                _client_ip(scope), error_msg,
            )
            try:
                import asyncio

                asyncio.get_running_loop().create_task(
                    _write(
                        scope, path, user_id, status, elapsed_ms,
                        _header(headers, b"user-agent")[:200],
                        error_msg,
                    )
                )
            except Exception:  # noqa: S110 审计失败绝不影响业务
                pass


async def _write(
    scope: Scope, path: str, user_id: int | None, status: int, ms: int,
    user_agent: str, error_msg: str,
) -> None:
    try:
        async with SessionLocal() as session:
            session.add(
                AuditLog(
                    user_id=user_id,
                    action=f"{scope.get('method', '')} {path}",
                    detail=f"status={status} {ms}ms",
                    ip=_client_ip(scope),
                    method=scope.get("method", ""),
                    path=path,
                    query=(scope.get("query_string") or b"").decode("latin-1")[:500],
                    status=status,
                    duration_ms=ms,
                    user_agent=user_agent,
                    error_msg=error_msg,
                )
            )
            await session.commit()
    except Exception:  # noqa: S110 同上
        pass


def _client_ip(scope: Scope) -> str:
    # 反向代理场景优先取 X-Forwarded-For 首段（与 services/audit.client_ip 同口径）
    headers = scope.get("headers", [])
    for k, v in headers:
        if k == b"x-forwarded-for":
            return v.decode("latin-1", errors="replace").split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else ""
