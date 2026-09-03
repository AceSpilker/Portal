"""传输加密中间件（dev-plan P24.3；api-spec §7）——纯 ASGI 实现。

/api/* 的请求体、响应体、Authorization 头全部密文传输。
豁免：/api/health、/api/crypto/*（公钥下发与握手本身）、/api/public/*（访客免认证）、静态资源。
中间件自身产生的错误（缺会话/解密失败/重放）以明文最小信息返回（1100/1101/1102），
不含任何业务数据，前端据此重新握手。
"""

import json

from app.core.config import settings
from app.core.crypto import transport_crypto

EXEMPT_PATHS = {
    "/api/health",
    "/api/crypto/public-key",
    "/api/crypto/handshake",
    "/api/public/apps",  # 访客免认证端点（P7.5）
}


class TransportEncryptionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.encrypt_enabled:
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        # /api/hooks/*：外部回调（Flow webhook，token 自鉴权），传输加密豁免（api-spec §1）
        if not path.startswith("/api") or path in EXEMPT_PATHS or path.startswith("/api/hooks/"):
            await self.app(scope, receive, send)
            return

        # ---- 会话识别 ----
        sid = ""
        authz = ""
        for k, v in scope["headers"]:
            if k == b"x-session-id":
                sid = v.decode("latin-1")
            elif k == b"authorization":
                authz = v.decode("latin-1")
        aes = transport_crypto.session_key(sid) if sid else None
        if aes is None:
            await self._plain(send, 1100, "secure session required", 400)
            return

        # ---- 读取并解密请求体 ----
        raw_body = b""
        while True:
            message = await receive()
            raw_body += message.get("body", b"")
            if not message.get("more_body"):
                break
        plain_body = b""
        if raw_body:
            try:
                envelope = json.loads(raw_body)
                if envelope.get("enc") != 1:
                    raise ValueError("not encrypted")
                plain_body = transport_crypto.open_envelope(aes, envelope["n"], envelope["p"], sid)
            except ValueError as exc:
                code = 1101 if str(exc) == "replayed nonce" else 1102
                message = "replayed request" if code == 1101 else "undecryptable request body"
                await self._plain(send, code, message, 400)
                return
            except Exception:
                await self._plain(send, 1102, "undecryptable request body", 400)
                return

        # ---- Authorization 头解密（客户端加密 "Bearer <jwt>"，解密后原样回填）----
        new_headers = list(scope["headers"])
        if authz.startswith("ENC "):
            try:
                jwt_value = transport_crypto.decrypt_str(aes, authz[4:].strip())
                new_headers = [
                    (k, jwt_value.encode() if k == b"authorization" else v) for k, v in new_headers
                ]
            except Exception:
                await self._plain(send, 1102, "undecryptable authorization", 400)(
                    scope, receive, send
                )
                return
        scope["headers"] = new_headers

        async def receive_decrypted():
            return {"type": "http.request", "body": plain_body, "more_body": False}

        # ---- 响应加密包装（缓冲完整 JSON 响应后加密封包）----
        start_message: dict | None = None
        resp_chunks: list[bytes] = []

        async def send_wrapper(message):
            nonlocal start_message
            if message["type"] == "http.response.start":
                start_message = message
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            resp_chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return

            full = b"".join(resp_chunks)
            headers = dict(start_message.get("headers", []))
            ctype = headers.get(b"content-type", b"")
            if ctype.startswith(b"application/json"):
                nonce_b64, payload_b64 = transport_crypto.seal(aes, full)
                body = json.dumps({"enc": 1, "n": nonce_b64, "p": payload_b64}).encode()
            else:
                body = full
            headers[b"content-length"] = str(len(body)).encode()
            start_message["headers"] = list(headers.items())
            await send(start_message)
            await send({"type": "http.response.body", "body": body, "more_body": False})

        await self.app(scope, receive_decrypted, send_wrapper)

    @staticmethod
    async def _plain(send, code: int, message: str, status: int = 400):
        """发送明文最小错误（不含业务数据），前端据此重新握手。"""
        body = json.dumps({"code": code, "message": message, "data": None}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
