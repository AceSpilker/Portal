"""阈值告警引擎与证书监控（M17-14/15、M07-6；dev-plan P10.3/P10.5）。

- evaluate_alerts：每 30s 评估启用的规则。持续 duration_min 分钟越限才触发
  （内存态 violating_since，重启重计可接受）；触发经 services.notify.dispatch
  走 metric_alert 事件（P9 出口），冷却 5 分钟（dedup 窗口一致）；
  恢复（不再越限）发 info 级恢复通知并清状态。
- check_certs：对 monitor.cert_hosts 设置键里的域名做 TLS 握手取到期天数，
  ≤1 error / ≤7 warn / ≤30 info，dedup 按天（每日最多提醒一次）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import ssl
import time
from datetime import datetime

import psutil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitor import AlertRule
from app.models.setting import Setting
from app.services import notify
from app.services.monitor import IoRateCalculator, collect_temps, io_snapshot

log = logging.getLogger("portal.alerts")

CERT_HOSTS_KEY = "monitor.cert_hosts"
# 触发后的冷却窗口（与通知去重窗口一致，避免每个采样周期重复推送）
FIRE_COOLDOWN_SEC = 300

# {rule_id: {"since": ts, "firing": bool}} —— 内存态，进程重启后重新计时
_STATE: dict[int, dict] = {}
# disk_io 告警专用速率器（阈值单位：IOPS，读写合计）
_alert_io_calc = IoRateCalculator()


def _fmt_num(v: float) -> str:
    return f"{v:.1f}" if v < 100 else str(int(round(v)))


async def current_value(session: AsyncSession, rule: AlertRule) -> float | None:
    """取规则指标的当前值；无法取得（如传感器缺失/挂载点不存在）返回 None。"""
    metric = rule.metric
    target = (rule.target or "").strip()
    if metric == "cpu":
        return psutil.cpu_percent(interval=None)
    if metric == "mem":
        return psutil.virtual_memory().percent
    if metric == "disk":
        mount = target or "/"
        try:
            return psutil.disk_usage(mount).percent
        except OSError:
            return None
    if metric == "disk_io":
        # 阈值单位为 IOPS（读写合计）；速率器需相邻两次快照，首次评估返回 None 跳过
        rates = await asyncio.to_thread(_alert_io_calc.feed, io_snapshot())
        if rates is None:
            return None
        return float(rates["read_iops"] + rates["write_iops"])
    if metric == "temp":
        temps = await asyncio.to_thread(collect_temps)
        if target:
            for t in temps:
                if t.get("name") == target:
                    return t.get("current")
            return None
        return temps[0].get("current") if temps else None
    return None


async def evaluate_alerts(session: AsyncSession) -> None:
    """告警状态机（M17-14）：越限持续 N 分钟触发，恢复发 info 通知。"""
    rules = (
        await session.execute(select(AlertRule).where(AlertRule.enabled.is_(True)))
    ).scalars().all()
    now = time.time()
    live_ids: set[int] = set()
    for rule in rules:
        live_ids.add(rule.id)
        value = await current_value(session, rule)
        if value is None:
            continue
        violated = value > rule.threshold if rule.op == ">" else value < rule.threshold
        st = _STATE.get(rule.id)
        if violated:
            if st is None:
                _STATE[rule.id] = {"since": now, "firing": False}
                continue
            if not st["firing"] and now - st["since"] >= rule.duration_min * 60:
                last = rule.last_fired_at.timestamp() if rule.last_fired_at else 0
                if now - last >= FIRE_COOLDOWN_SEC:
                    title = (
                        f"{rule.name or rule.metric} 告警：{_fmt_num(value)} "
                        f"{rule.op} {rule.threshold}"
                    )
                    await notify.dispatch(
                        session,
                        event="metric_alert",
                        source="metric",
                        title=title,
                        body=f"已持续 {int((now - st['since']) / 60)} 分钟",
                        level=rule.level,
                        dedup_key=f"alert-{rule.id}-{int(now // FIRE_COOLDOWN_SEC)}",
                    )
                    rule.last_fired_at = datetime.utcnow()
                    await session.commit()
                st["firing"] = True
        else:
            if st is not None and st["firing"]:
                title = (
                    f"{rule.name or rule.metric} 已恢复："
                    f"当前 {_fmt_num(value)} {rule.op} {rule.threshold}"
                )
                await notify.dispatch(
                    session,
                    event="metric_alert",
                    source="metric",
                    title=title,
                    level="info",
                    dedup_key=f"alert-ok-{rule.id}-{int(now // FIRE_COOLDOWN_SEC)}",
                )
            if st is not None:
                _STATE.pop(rule.id, None)
    # 清理已删除规则的状态
    for rid in [r for r in _STATE if r not in live_ids]:
        _STATE.pop(rid, None)


# ---------- 证书监控（M07-6） ----------


def parse_not_after(raw: str | None) -> datetime | None:
    """解析 X.509 notAfter（如 'Sep  1 12:00:00 2027 GMT'）。"""
    if not raw:
        return None
    return datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z")


def _cert_not_after_sync(host: str, port: int = 443, timeout: float = 8.0) -> datetime | None:
    # 证书监控只关心有效期，不校验信任链（CERT_NONE + 取 peer cert，等价 openssl s_client）
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            # CERT_NONE 下 getpeercert() 需 binary_form=True 才返回证书
            der = tls.getpeercert(binary_form=True)
    if not der:
        return None
    from cryptography import x509

    cert = x509.load_der_x509_certificate(der)
    # 统一 naive UTC（全库约定）；not_valid_after_utc 为 aware
    return cert.not_valid_after_utc.replace(tzinfo=None)


async def get_cert_hosts(session: AsyncSession) -> list[str]:
    row = await session.get(Setting, CERT_HOSTS_KEY)
    if not row:
        return []
    try:
        hosts = json.loads(row.value)
        return [h.strip() for h in hosts if isinstance(h, str) and h.strip()]
    except json.JSONDecodeError:
        return []


async def check_cert(host: str) -> dict:
    """单域名证书到期信息；失败返回 error 字段。"""
    try:
        not_after = await asyncio.to_thread(_cert_not_after_sync, host)
    except (OSError, ssl.SSLError, ValueError) as exc:
        return {"host": host, "error": str(exc)[:120]}
    if not_after is None:
        return {"host": host, "error": "no notAfter"}
    days_left = (not_after - datetime.utcnow()).total_seconds() / 86400
    if days_left <= 1:
        level = "error"
    elif days_left <= 7:
        level = "warn"
    elif days_left <= 30:
        level = "info"
    else:
        level = "ok"
    return {
        "host": host,
        "days_left": int(days_left),
        "not_after": not_after.strftime("%Y-%m-%d"),
        "level": level,
    }


async def check_certs_and_notify(session: AsyncSession) -> list[dict]:
    """定时检查（每 6h）：到期分级提醒，dedup 按天（每日最多一次）。"""
    hosts = await get_cert_hosts(session)
    results = []
    for host in hosts:
        info = await check_cert(host)
        results.append(info)
        if info.get("error") or info["level"] == "ok":
            continue
        await notify.dispatch(
            session,
            event="system",
            source="system",
            title=f"证书 {host} 将于 {info['days_left']} 天后到期（{info['not_after']}）",
            level=info["level"],
            dedup_key=f"cert-{host}-{datetime.utcnow().strftime('%Y%m%d')}",
        )
    return results
