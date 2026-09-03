"""通知中心服务（M09；dev-plan P9.1/P9.3；api-spec §3.8/§4.9）。

- 渠道抽象：payload 构造为纯函数（单测关卡），send_channel 负责 IO；
  支持 bark/telegram/smtp/webhook/wecom/dingtalk/feishu/ntfy 八类
  （wecom/dingtalk/feishu 为群机器人 webhook 的专用 JSON 格式）；
- dispatch：站内通知（带聚合去重窗口）→ 查路由规则 → 规则级免打扰判定
  （站内始终写入，免打扰仅抑制外部渠道）→ 逐渠道发送（失败静默记日志）；
- 探活接入：probe.apply_result 状态翻转时调用 dispatch（P6.4 事件源 → P9 出口）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.utils import formataddr

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notify import NotifyChannel, NotifyRule
from app.models.probe import Notification
from app.services import wsbus

log = logging.getLogger("portal.notify")

# 聚合去重窗口（M09-12）：同 dedup_key 在窗口内的重复事件合并为一条
DEDUP_WINDOW_SEC = 300
SMTP_TIMEOUT = 15

# httpx AsyncClient 工厂（测试用 httpx.MockTransport 注入覆盖）
_http_transport: httpx.AsyncBaseTransport | None = None


def set_http_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _http_transport
    _http_transport = transport


# ---------- 渠道 payload 构造（纯函数，单测关卡） ----------


def build_bark(cfg: dict, title: str, body: str, level: str) -> tuple[str, str, None]:
    """Bark：GET {server}/{key}/{title}/{body}?level=。返回 (method, url, json)。"""
    server = (cfg.get("server") or "https://api.day.app").rstrip("/")
    key = cfg.get("device_key", "")
    from urllib.parse import quote

    url = f"{server}/{quote(key, safe='')}/{quote(title)}/{quote(body)}?level={level}"
    return "GET", url, None


def build_telegram(cfg: dict, title: str, body: str, level: str) -> tuple[str, str, dict]:
    url = f"https://api.telegram.org/bot{cfg.get('bot_token', '')}/sendMessage"
    text = f"[{level}] {title}" + (f"\n{body}" if body else "")
    return "POST", url, {"chat_id": cfg.get("chat_id", ""), "text": text}


def build_webhook(cfg: dict, title: str, body: str, level: str, event: str, source: str):
    json_body = {
        "event": event,
        "source": source,
        "level": level,
        "title": title,
        "body": body,
        "timestamp": int(time.time()),
    }
    return "POST", cfg.get("url", ""), json_body


def build_wecom(cfg: dict, title: str, body: str) -> tuple[str, str, dict]:
    """企业微信群机器人。"""
    content = {"msgtype": "text", "text": {"content": f"{title}\n{body}".strip()}}
    return "POST", cfg.get("url", ""), content


def build_dingtalk(cfg: dict, title: str, body: str) -> tuple[str, str, dict]:
    """钉钉群机器人（自定义关键词安全策略由用户在钉钉侧配置）。"""
    content = {"msgtype": "text", "text": {"content": f"{title}\n{body}".strip()}}
    return "POST", cfg.get("url", ""), content


def build_feishu(cfg: dict, title: str, body: str) -> tuple[str, str, dict]:
    """飞书群机器人。"""
    content = {"msg_type": "text", "content": {"text": f"{title}\n{body}".strip()}}
    return "POST", cfg.get("url", ""), content


def build_ntfy(cfg: dict, title: str, body: str, level: str) -> tuple[str, str, str, dict]:
    """ntfy：POST {server}/{topic}，纯文本 body + Title/ Priority 头。"""
    server = (cfg.get("server") or "https://ntfy.sh").rstrip("/")
    url = f"{server}/{cfg.get('topic', '')}"
    headers = {"Title": title, "Priority": "high" if level in ("warn", "error") else "default"}
    return "POST", url, body, headers


def build_smtp_message(cfg: dict, title: str, body: str, level: str) -> MIMEText:
    """SMTP：构造 MIME 文本邮件（发送经线程池，见 _smtp_send）。"""
    msg = MIMEText(f"{body}\n", "plain", "utf-8")
    msg["Subject"] = f"[Portal][{level}] {title}"
    sender = cfg.get("username") or cfg.get("from_addr") or "portal@localhost"
    msg["From"] = formataddr(("Portal", sender))
    tos = cfg.get("to_addrs") or []
    msg["To"] = ",".join(tos) if isinstance(tos, list) else str(tos)
    return msg


# ---------- 渠道发送 ----------


async def _smtp_send(cfg: dict, msg: MIMEText) -> None:
    """smbplib 为同步 IO，放线程池；测试中可 monkeypatch 本函数。"""

    def _send() -> None:
        with smtplib.SMTP(cfg.get("host", ""), int(cfg.get("port", 25)), timeout=SMTP_TIMEOUT) as s:
            if cfg.get("use_tls"):
                s.starttls()
            user, pwd = cfg.get("username"), cfg.get("password")
            if user and pwd:
                s.login(user, pwd)
            to_list = [a.strip() for a in (msg["To"] or "").split(",") if a.strip()]
            s.sendmail(msg["From"], to_list, msg.as_string())

    await asyncio.to_thread(_send)


async def send_channel(
    channel: NotifyChannel,
    *,
    event: str,
    source: str,
    title: str,
    body: str,
    level: str,
) -> bool:
    """按渠道类型发送；网络失败返回 False 不抛出（测试经 set_http_transport 注入）。"""
    try:
        cfg = json.loads(channel.config or "{}")
    except json.JSONDecodeError:
        cfg = {}
    try:
        ctype = channel.type
        if ctype == "smtp":
            await _smtp_send(cfg, build_smtp_message(cfg, title, body, level))
            return True
        if ctype == "ntfy":
            method, url, data, headers = build_ntfy(cfg, title, body, level)
            kwargs = {"content": data.encode("utf-8"), "headers": headers}
        elif ctype == "bark":
            method, url, payload = build_bark(cfg, title, body, level)
            kwargs = {"follow_redirects": True}
        else:
            builder = {
                "telegram": build_telegram,
                "webhook": build_webhook,
                "wecom": build_wecom,
                "dingtalk": build_dingtalk,
                "feishu": build_feishu,
            }.get(ctype)
            if builder is None:
                return False
            if ctype == "webhook":
                method, url, payload = builder(cfg, title, body, level, event, source)
            else:
                method, url, payload = builder(cfg, title, body)
            kwargs = {"json": payload}

        client_kwargs: dict = {"timeout": 10.0}
        if _http_transport is not None:
            client_kwargs["transport"] = _http_transport
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.request(method, url, **kwargs)
        return resp.status_code < 400
    except Exception as exc:  # 渠道失败不影响主流程
        log.warning("notify channel %s(%s) failed: %s", channel.name, channel.type, exc)
        return False


# ---------- 免打扰与规则（M09-10/11） ----------


def is_quiet_now(
    quiet_start: str | None, quiet_end: str | None, now: datetime | None = None
) -> bool:
    """规则级免打扰判定：HH:MM~HH:MM，支持跨午夜（22:00~08:00）。

    start==end 视为全天免打扰；仅配置其一视为不启用。
    """
    if not quiet_start or not quiet_end:
        return False
    try:
        sh, sm = (int(x) for x in quiet_start.split(":")[:2])
        eh, em = (int(x) for x in quiet_end.split(":")[:2])
    except (ValueError, AttributeError):
        return False
    now_t = (now or datetime.now()).time()
    cur = now_t.hour * 60 + now_t.minute
    start, end = sh * 60 + sm, eh * 60 + em
    if start == end:
        return True
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end  # 跨午夜


async def load_enabled_rules(session: AsyncSession, event: str) -> list[NotifyRule]:
    rules = (
        await session.execute(select(NotifyRule).where(NotifyRule.enabled.is_(True)))
    ).scalars().all()
    return [r for r in rules if r.event == event]


# ---------- 站内 + 编排（M09-1/2/12） ----------


def _notification_view(n: Notification) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "level": n.level,
        "source": n.source,
        "is_read": bool(n.is_read),
        "created_at": n.created_at.isoformat() + "Z",
    }


async def dispatch(
    session: AsyncSession,
    *,
    event: str,
    source: str,
    title: str,
    body: str = "",
    level: str = "info",
    dedup_key: str | None = None,
) -> dict | None:
    """事件出口：站内通知（去重合并）→ 路由规则 → 外部渠道。

    返回新建站内通知的视图（被去重合并或无通知时返回 None）。
    站内始终写入（去重除外）；免打扰仅抑制外部渠道（M09-11）。
    """
    if dedup_key:
        since = datetime.utcnow() - timedelta(seconds=DEDUP_WINDOW_SEC)
        dup = await session.execute(
            select(Notification.id)
            .where(
                Notification.dedup_key == dedup_key,
                Notification.created_at >= since,
            )
            .limit(1)
        )
        if dup.first() is not None:
            return None

    n = Notification(title=title, body=body, level=level, source=source, dedup_key=dedup_key)
    session.add(n)
    await session.commit()
    view = _notification_view(n)
    await wsbus.broadcast({"type": "notification", "data": view})

    rules = await load_enabled_rules(session, event)
    if rules:
        channels = {
            c.id: c
            for c in (
                await session.execute(select(NotifyChannel).where(NotifyChannel.enabled.is_(True)))
            ).scalars()
        }
        for rule in rules:
            if is_quiet_now(rule.quiet_start, rule.quiet_end):
                continue
            try:
                ids = json.loads(rule.channel_ids or "[]")
            except json.JSONDecodeError:
                continue
            for cid in ids:
                ch = channels.get(int(cid))
                if ch is not None:
                    await send_channel(
                        ch, event=event, source=source, title=title, body=body, level=level
                    )
    return view
