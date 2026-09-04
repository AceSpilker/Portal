"""qBittorrent WebUI API 适配（M12-1/2/4；dev-plan P16.3）。

只读联动为主：登录 → 任务列表/添加。v2 API（qBittorrent 4.1+）；
登录拿 SID cookie 后续请求自动携带（httpx Client cookie jar）。
"""

from __future__ import annotations

import httpx

LOGIN_TIMEOUT = 8.0
API_TIMEOUT = 12.0


class QBError(RuntimeError):
    """qB 调用失败（连接/认证/接口错误统一）。"""


class QBittorrentClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.username = username
        self.password = password
        # transport 供测试注入 httpx.MockTransport（约定同探活 mock）
        self.client = httpx.AsyncClient(timeout=API_TIMEOUT, transport=transport)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def login(self) -> None:
        try:
            resp = await self.client.post(
                f"{self.base}/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=LOGIN_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise QBError(f"connect failed: {exc}") from exc
        if resp.status_code != 200 or resp.text.strip() != "Ok.":
            raise QBError(f"login failed: HTTP {resp.status_code}")
        if "SID" not in self.client.cookies:
            raise QBError("login failed: no SID cookie")

    async def torrents_info(self) -> list[dict]:
        resp = await self.client.get(f"{self.base}/api/v2/torrents/info")
        if resp.status_code != 200:
            raise QBError(f"torrents/info failed: HTTP {resp.status_code}")
        return resp.json()  # type: ignore[no-any-return]

    async def add_torrents(self, urls: list[str]) -> None:
        """按 URL/磁力下发（M12-2）：多行 urls 表单字段。"""
        resp = await self.client.post(
            f"{self.base}/api/v2/torrents/add",
            data={"urls": "\n".join(urls)},
        )
        if resp.status_code != 200:
            raise QBError(f"torrents/add failed: HTTP {resp.status_code}")


def _is_complete(t: dict) -> bool:
    """任务是否已完成（进度 100%；state 中 pausedUP/stalledUP 等均视为完成态）。"""
    return float(t.get("progress", 0)) >= 1.0


async def poll_completions(session, client: QBittorrentClient, prev: dict[str, bool]) -> int:
    """轮询任务完成状态（M12-4）：False→True 跳变推通知。返回通知条数。

    prev 由调用方持有（进程内存）；新出现的已完成任务不补发（避免重启刷屏）。
    """
    from app.core.i18n import t
    from app.services.notify import dispatch

    torrents = await client.torrents_info()
    sent = 0
    for torrent in torrents:
        h = torrent.get("hash", "")
        if not h:
            continue
        done = _is_complete(torrent)
        was = prev.get(h)
        prev[h] = done
        if was is False and done:
            await dispatch(
                session,
                event="downloads.complete",
                source="downloads",
                title=t("notify.download_done", name=torrent.get("name", h)),
                body=t("notify.download_done_body"),
            )
            sent += 1
    return sent
