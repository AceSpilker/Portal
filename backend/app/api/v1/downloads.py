"""下载与媒体接口（M12-1/2/4/5；dev-plan P16.3；api-spec §4.11）。

设置键：downloads.enabled/downloads.qb_url/downloads.qb_user/downloads.qb_pass、
media.jellyfin_url/media.jellyfin_key。未启用时 downloads/summary 等 404，
前端隐藏页签。海报经服务端代理转 data URI，Jellyfin api_key 不落前端。
"""

from __future__ import annotations

import base64
import json

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, BizError, ok
from app.db.session import get_session
from app.models.setting import Setting
from app.models.user import User
from app.services.qbittorrent import QBError, QBittorrentClient, poll_completions

router = APIRouter()

# 进程内完成任务状态（M12-4：False→True 跳变通知；重启后重建不补发）
_prev_complete: dict[str, bool] = {}

DOWNLOAD_KEYS = ("downloads.enabled", "downloads.qb_url", "downloads.qb_user", "downloads.qb_pass")
MEDIA_KEYS = ("media.jellyfin_url", "media.jellyfin_key")


async def _settings_map(session: AsyncSession, keys: tuple[str, ...]) -> dict:
    out: dict = {}
    for k in keys:
        row = await session.get(Setting, k)
        out[k] = json.loads(row.value) if row else None
    return out


async def _client(session: AsyncSession) -> tuple[QBittorrentClient, dict]:
    cfg = await _settings_map(session, DOWNLOAD_KEYS)
    if not cfg["downloads.enabled"] or not cfg["downloads.qb_url"]:
        raise BizError(CODE_NOT_FOUND, t("err.downloads_disabled"), 404)
    client = QBittorrentClient(
        cfg["downloads.qb_url"],
        cfg["downloads.qb_user"] or "",
        cfg["downloads.qb_pass"] or "",
    )
    try:
        await client.login()
    except QBError:
        await client.aclose()
        raise
    return client, cfg


def _torrent_view(x: dict) -> dict:
    return {
        "hash": x.get("hash"),
        "name": x.get("name"),
        "size": x.get("size"),
        "progress": round(float(x.get("progress", 0)) * 100, 1),
        "state": x.get("state"),
        "completed": float(x.get("progress", 0)) >= 1.0,
        "dlspeed": x.get("dlspeed"),
        "upspeed": x.get("upspeed"),
        "num_seeds": x.get("num_seeds"),
        "num_leechs": x.get("num_leechs"),
        "eta": x.get("eta"),
        "category": x.get("category", ""),
    }


@router.get("/downloads/summary")
async def downloads_summary(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """下载概览：{enabled, connected, counts, speed}（M12-1）。"""
    cfg = await _settings_map(session, DOWNLOAD_KEYS)
    if not cfg["downloads.enabled"] or not cfg["downloads.qb_url"]:
        raise BizError(CODE_NOT_FOUND, t("err.downloads_disabled"), 404)
    client = QBittorrentClient(
        cfg["downloads.qb_url"], cfg["downloads.qb_user"] or "", cfg["downloads.qb_pass"] or ""
    )
    try:
        try:
            await client.login()
            torrents = await client.torrents_info()
        except QBError as exc:
            await client.aclose()
            return ok(
                {
                    "enabled": True, "connected": False, "error": str(exc),
                    "counts": {}, "speed": {"dl": 0, "up": 0},
                }
            )
        counts = {"downloading": 0, "completed": 0, "paused": 0, "seeding": 0, "error": 0}
        for x in torrents:
            state = str(x.get("state", ""))
            if float(x.get("progress", 0)) >= 1.0:
                counts["completed"] += 1
            if state in ("downloading", "stalledDL", "metaDL", "forcedDL"):
                counts["downloading"] += 1
            if state.startswith("paused"):
                counts["paused"] += 1
            if state in ("uploading", "stalledUP", "forcedUP"):
                counts["seeding"] += 1
            if "error" in state:
                counts["error"] += 1
        return ok(
            {
                "enabled": True,
                "connected": True,
                "counts": counts,
                "speed": {
                    "dl": sum(x.get("dlspeed", 0) for x in torrents),
                    "up": sum(x.get("upspeed", 0) for x in torrents),
                },
            }
        )
    finally:
        await client.aclose()


@router.get("/downloads/tasks")
async def downloads_tasks(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """任务列表（M12-1）：进度/速度/状态。"""
    client, _cfg = await _client(session)
    try:
        torrents = await client.torrents_info()
        return ok([_torrent_view(x) for x in torrents])
    finally:
        await client.aclose()


class AddBody(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)


@router.post("/downloads/tasks")
async def add_download(
    body: AddBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """添加下载任务（M12-2）：磁力/URL，多行。"""
    urls = [u.strip() for u in body.urls if u.strip()]
    if not urls:
        raise BizError(CODE_NOT_FOUND, t("v.url_invalid"), 422)
    client, _cfg = await _client(session)
    try:
        await client.add_torrents(urls)
    finally:
        await client.aclose()
    return ok({"count": len(urls)}, t("ok.saved"))


@router.get("/media/recent")
async def media_recent(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """媒体最近入库（M12-5）：Jellyfin/Emby 海报墙（≤12 项，海报 data URI）。"""
    cfg = await _settings_map(session, MEDIA_KEYS)
    url, key = cfg["media.jellyfin_url"], cfg["media.jellyfin_key"]
    if not url or not key:
        raise BizError(CODE_NOT_FOUND, t("err.media_disabled"), 404)
    base = url.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{base}/Items/Latest",
                params={"Limit": 12, "IncludeItemTypes": "Movie,Episode,Series", "api_key": key},
            )
            resp.raise_for_status()
            items = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BizError(CODE_NOT_FOUND, t("err.media_unreachable"), 404) from exc
        out = []
        for it in items[:12]:
            poster = None
            if it.get("ImageTags", {}).get("Primary"):
                try:
                    img = await client.get(
                        f"{base}/Items/{it['Id']}/Images/Primary",
                        params={"maxWidth": 200, "api_key": key},
                    )
                    if img.status_code == 200:
                        poster = (
                            "data:image/jpeg;base64,"
                            + base64.b64encode(img.content).decode()
                        )
                except httpx.HTTPError:
                    poster = None
            out.append(
                {
                    "id": it.get("Id"),
                    "title": it.get("Name"),
                    "series": it.get("SeriesName") or it.get("Album") or "",
                    "added_at": (it.get("DateCreated") or "")[:10],
                    "poster": poster,
                }
            )
        return ok({"items": out})


async def downloads_job() -> None:
    """下载完成轮询（M12-4；每 60s）：完成跳变 → P9 通知。"""
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        cfg = await _settings_map(session, DOWNLOAD_KEYS)
        if not cfg["downloads.enabled"] or not cfg["downloads.qb_url"]:
            return
        client = QBittorrentClient(
            cfg["downloads.qb_url"], cfg["downloads.qb_user"] or "", cfg["downloads.qb_pass"] or ""
        )
        try:
            await poll_completions(session, client, _prev_complete)
        except QBError:
            pass  # 不可达时静默（下载器离线不告警，避免噪声）
        finally:
            await client.aclose()
