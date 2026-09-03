"""通知中心接口（M09-1~3/9/10；dev-plan P9；api-spec §4.9）。

- GET /notifications?level=&unread=&limit=&offset=：站内通知（分页 + 级别筛选）；
- GET /notifications/unread-count：角标未读数；
- PUT /notifications/read-all · /{id}/read · DELETE /{id}：已读管理与删除（A）；
- GET/POST/PUT/DELETE /notify-channels…：渠道 CRUD（M，config 敏感字段回传脱敏）；
- POST /notify-channels/{id}/test：渠道测试发送（M）；
- GET/PUT /notify-rules：事件→渠道路由矩阵（M，PUT 全量保存）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.response import CODE_NOT_FOUND, CODE_VALIDATION, BizError, ok
from app.db.session import get_session
from app.models.notify import NotifyChannel, NotifyRule
from app.models.probe import Notification
from app.models.user import User
from app.services import notify

router = APIRouter()

# 各渠道 config 中的敏感字段：回传时替换为 ******，保存时 ****** 表示保持原值
SENSITIVE_KEYS = ("device_key", "bot_token", "password")


def _mask(cfg: dict) -> dict:
    return {k: ("******" if k in SENSITIVE_KEYS and v else v) for k, v in cfg.items()}


def _channel_view(c: NotifyChannel) -> dict:
    try:
        cfg = json.loads(c.config or "{}")
    except json.JSONDecodeError:
        cfg = {}
    return {
        "id": c.id,
        "type": c.type,
        "name": c.name,
        "enabled": bool(c.enabled),
        "config": _mask(cfg),
    }


def _rule_view(r: NotifyRule) -> dict:
    try:
        ids = json.loads(r.channel_ids or "[]")
    except json.JSONDecodeError:
        ids = []
    return {
        "id": r.id,
        "event": r.event,
        "channel_ids": ids,
        "enabled": bool(r.enabled),
        "quiet_start": r.quiet_start,
        "quiet_end": r.quiet_end,
    }


# ---------- 站内通知（A） ----------


@router.get("/notifications")
async def list_notifications(
    level: str | None = Query(None),
    unread: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """站内通知（P9.2）：分页 + 级别筛选 + 未读总数。"""
    stmt = select(Notification)
    if level in ("info", "warn", "error"):
        stmt = stmt.where(Notification.level == level)
    if unread:
        stmt = stmt.where(Notification.is_read == 0)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(Notification.id.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    unread_total = (
        await session.execute(
            select(func.count()).select_from(Notification).where(Notification.is_read == 0)
        )
    ).scalar_one()
    return ok(
        {
            "items": [
                {
                    "id": n.id,
                    "title": n.title,
                    "body": n.body,
                    "level": n.level,
                    "source": n.source,
                    "is_read": bool(n.is_read),
                    "created_at": n.created_at.isoformat() + "Z",
                }
                for n in rows
            ],
            "total": total,
            "unread": unread_total,
        }
    )


@router.get("/notifications/unread-count")
async def unread_count(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """顶栏角标未读数（M09-1）。"""
    n = (
        await session.execute(
            select(func.count()).select_from(Notification).where(Notification.is_read == 0)
        )
    ).scalar_one()
    return ok({"unread": n})


@router.put("/notifications/read-all")
async def read_all(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await session.execute(
        Notification.__table__.update().where(Notification.is_read == 0).values(is_read=1)
    )
    await session.commit()
    return ok(True)


@router.put("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    n = await session.get(Notification, notification_id)
    if n:
        n.is_read = 1
        await session.commit()
    return ok(True)


@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    n = await session.get(Notification, notification_id)
    if n:
        await session.delete(n)
        await session.commit()
    return ok(True)


# ---------- 渠道（M，P9.1） ----------


class ChannelIn(BaseModel):
    type: str = Field(pattern="^(bark|telegram|smtp|webhook|wecom|dingtalk|feishu|ntfy)$")
    name: str = ""
    enabled: bool = True
    config: dict = Field(default_factory=dict)


async def _channel_or_404(session: AsyncSession, channel_id: int) -> NotifyChannel:
    ch = await session.get(NotifyChannel, channel_id)
    if ch is None:
        from app.core.i18n import t

        raise BizError(CODE_NOT_FOUND, t("err.channel_not_found"), 404)
    return ch


def _merge_secret(existing: dict, incoming: dict) -> dict:
    """****** 表示保持原值（前端未改动敏感字段时回传掩码）。"""
    merged = dict(incoming)
    for k in SENSITIVE_KEYS:
        if merged.get(k) == "******" and k in existing:
            merged[k] = existing[k]
    return merged


@router.get("/notify-channels")
async def list_channels(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(select(NotifyChannel).order_by(NotifyChannel.id))).scalars().all()
    return ok([_channel_view(c) for c in rows])


@router.post("/notify-channels")
async def create_channel(
    body: ChannelIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    c = NotifyChannel(
        type=body.type, name=body.name, enabled=int(body.enabled),
        config=json.dumps(body.config, ensure_ascii=False),
    )
    session.add(c)
    await session.commit()
    return ok(_channel_view(c))


@router.put("/notify-channels/{channel_id}")
async def update_channel(
    channel_id: int,
    body: ChannelIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    c = await _channel_or_404(session, channel_id)
    try:
        existing = json.loads(c.config or "{}")
    except json.JSONDecodeError:
        existing = {}
    c.type = body.type
    c.name = body.name
    c.enabled = int(body.enabled)
    c.config = json.dumps(_merge_secret(existing, body.config), ensure_ascii=False)
    await session.commit()
    return ok(_channel_view(c))


@router.delete("/notify-channels/{channel_id}")
async def delete_channel(
    channel_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    c = await _channel_or_404(session, channel_id)
    await session.delete(c)
    await session.commit()
    return ok(True)


@router.post("/notify-channels/{channel_id}/test")
async def test_channel(
    channel_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """渠道测试发送（M09-9）：站内不落库，仅向该渠道发一条测试消息。"""
    from app.core.i18n import t

    c = await _channel_or_404(session, channel_id)
    sent = await notify.send_channel(
        c, event="system", source="system",
        title=t("notify.test_title"), body=t("notify.test_body"),
        level="info",
    )
    return ok({"sent": sent})


# ---------- 路由规则（M，P9.3） ----------


class RuleIn(BaseModel):
    event: str
    channel_ids: list[int] = Field(default_factory=list)
    enabled: bool = True
    quiet_start: str | None = None
    quiet_end: str | None = None


class RulesIn(BaseModel):
    rules: list[RuleIn]


@router.get("/notify-rules")
async def list_rules(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(select(NotifyRule).order_by(NotifyRule.id))).scalars().all()
    return ok([_rule_view(r) for r in rows])


@router.put("/notify-rules")
async def replace_rules(
    body: RulesIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """全量保存路由矩阵（设置页矩阵 UI 每次整体提交）。"""
    for r in body.rules:
        if r.event not in (
            "app_down", "app_up", "metric_alert",
            "port_down", "port_up", "flow_failed", "system",
        ):
            raise BizError(CODE_VALIDATION, f"unknown event: {r.event}", 422)
        for p in (r.quiet_start, r.quiet_end):
            if p is not None and len(p.split(":")) != 2:
                raise BizError(CODE_VALIDATION, "quiet time must be HH:MM", 422)
    rows = (await session.execute(select(NotifyRule))).scalars().all()
    for r in rows:
        await session.delete(r)
    for r in body.rules:
        session.add(
            NotifyRule(
                event=r.event,
                channel_ids=json.dumps(r.channel_ids),
                enabled=int(r.enabled),
                quiet_start=r.quiet_start,
                quiet_end=r.quiet_end,
            )
        )
    await session.commit()
    rows = (await session.execute(select(NotifyRule).order_by(NotifyRule.id))).scalars().all()
    return ok([_rule_view(r) for r in rows])
