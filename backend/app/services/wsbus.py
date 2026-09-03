"""站内 WS 事件总线（P9 重构）：/ws/notify 连接的注册与广播。

原实现挂在 services/probe.py（P6.3 仅有探活状态点事件）；通知中心（P9.2）
需要广播 notification 事件，为避免 probe ← notify 循环依赖，把连接组
下沉为独立模块。事件形如 {"type": "app_status"|"notification", "data": {...}}。
"""

from __future__ import annotations

_WS_CLIENTS: set = set()


def register_ws(ws) -> None:
    _WS_CLIENTS.add(ws)


def unregister_ws(ws) -> None:
    _WS_CLIENTS.discard(ws)


async def broadcast(event: dict) -> None:
    """向所有 /ws/notify 连接广播事件；发送失败静默移除连接。"""
    for ws in list(_WS_CLIENTS):
        try:
            await ws.send_json(event)
        except Exception:
            _WS_CLIENTS.discard(ws)
