"""传输加密中间件（二期 D0.3：自一期纯 ASGI 实现逐行移植，仅信封字段 message→msg）。

/api/* 的请求体、响应体、Authorization 头全部密文传输。
豁免：/api/health、/api/crypto/*（公钥下发与握手本身）、/api/public/*（访客免认证）、
非 /api 路径；/api/hooks/*（外部回调 token 自鉴权）与 /api/knowledge/*?sig= 签名直链豁免。
中间件自身错误（缺会话/解密失败/重放）以明文最小信息返回（1100/1101/1102），
不含任何业务数据，前端据此重新握手。
"""

import json

from django.conf import settings

from apps.core.crypto import transport_crypto

EXEMPT_PATHS = {
    "/api/health",
    "/api/crypto/public-key",
    "/api/crypto/handshake",
    "/api/public/apps",  # 访客免认证端点
}


class TransportEncryptionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.ENCRYPT_ENABLED:
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        # /api/hooks/*：外部回调（Flow webhook，token 自鉴权），传输加密豁免（api-spec §1）
        query = (scope.get("query_string") or b"").decode("latin-1")
        # 知识库 raw 签名 URL：HMAC+有效期本身即授权票据，豁免信封加密，
        # 否则 iframe/img/video 无法携带加密会话头被 1100 拦截
        signed_raw = path.startswith("/api/knowledge/") and "sig=" in query
        if (
            not path.startswith("/api")
            or path in EXEMPT_PATHS
            or path.startswith("/api/hooks/")
            or signed_raw
        ):
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
        aes = await transport_crypto.session_key(sid) if sid else None
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
                await self._plain(send, 1102, "undecryptable authorization", 400)
                return
        scope["headers"] = new_headers

        # 有状态 receive：首调返回解密体；后续消息（http.disconnect 等）转发原始通道。
        # （一期 Starlette 容忍无状态实现；Django ASGI 处理器读体后会再 receive 监听断连——
        # 每次都回 http.request 会触发 "Invalid ASGI message"，记 D0.3 移植差异。）
        body_sent = False

        async def receive_decrypted():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": plain_body, "more_body": False}
            return await receive()

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
            # Django ASGI 的头名保留原始大小写（如 Content-Type），Starlette 恒小写——
            # 统一小写后再查（记 D0.3 移植差异）
            headers = {k.lower(): v for k, v in start_message.get("headers", [])}
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
        body = json.dumps({"code": code, "msg": message, "data": None}).encode()
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
