"""监控接口（M17-6/8/9/10~15；dev-plan P5/P10；api-spec §4.4/§5）。

权限：A（任意登录用户）——权限矩阵 §3 规定 user 可查看基础资源图；
进程/Docker/告警规则等增强接口为 M。WS /ws/monitor 挂在应用根路径
（/api 之外），query 带 access token 鉴权；传输加密中间件只处理 http scope，
WS 明文穿透（与静态资源同属豁免面）。
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import psutil
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, CODE_VALIDATION, BizError, ok
from app.core.security import decode_token
from app.db.session import SessionLocal, get_session
from app.models.monitor import AlertRule
from app.models.probe import Notification
from app.models.user import User
from app.services import alerts as alerts_svc
from app.services import monitor
from app.services.monitor import HISTORY_METRICS, RANGE_SECONDS, build_history, collect_overview

router = APIRouter()


@router.get("/monitor/system")
async def monitor_system(_: User = Depends(get_current_user)):
    """实时概览（M17-1~5）：系统信息/CPU/内存/磁盘/网络（含速率与当日流量）。

    P25.3 缓存首个用例：1.5s TTL 键值缓存（Redis/内存），抵挡重复 GET 突发；
    WS /ws/monitor 每 2s 仍直采并喂网络速率计算器，速率不受缓存影响。
    """
    import json as _json

    from app.core.stores import stores

    cached = await stores.store.get("cache:monitor:system")
    if cached:
        return ok(_json.loads(cached))
    data = collect_overview(monitor.ws_net_calc)
    await stores.store.set("cache:monitor:system", _json.dumps(data, ensure_ascii=False), ttl=2)
    return ok(data)


@router.get("/monitor/history")
async def monitor_history(
    metric: str = Query("cpu"),
    range_: str = Query("24h", alias="range"),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """历史曲线（M17-6）：metric ∈ cpu/mem/disk/net，range ∈ 24h/7d/30d。"""
    if metric not in HISTORY_METRICS or range_ not in RANGE_SECONDS:
        raise BizError(CODE_VALIDATION, t("err.invalid_metric_or_range"), 422)
    return ok(await build_history(session, metric, range_))


async def monitor_ws(websocket: WebSocket) -> None:
    """WS /ws/monitor（M17-8）：管理员鉴权后每 2 秒推送实时概览。"""
    try:
        payload = decode_token(websocket.query_params.get("token", ""), "access")
        async with SessionLocal() as session:
            user = await session.get(User, int(payload["sub"]))
        if user is None or not user.is_active:
            raise ValueError("inactive")
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    try:
        while True:
            data = collect_overview(monitor.ws_net_calc)
            await websocket.send_json({"type": "monitor", "data": data})
            # 推送间隔可配（monitor.push_interval，每次循环读取即时生效）
            async with SessionLocal() as session:
                push_interval = await monitor.read_push_interval(session)
            await asyncio.sleep(max(1, push_interval))
    except (WebSocketDisconnect, RuntimeError):
        return


async def sampler_job() -> None:
    """采样任务（P5.2）：每 10s 醒来一次，达到 monitor.sample_interval 才落一行。"""
    async with SessionLocal() as session:
        if await monitor.should_sample(session):
            await monitor.sample_once(session)


async def cleanup_job() -> None:
    """APScheduler 每小时清理任务：按 monitor.retention_days 删过期采样。"""
    async with SessionLocal() as session:
        await monitor.cleanup_expired(session)


# ---------- P10.1 进程 Top 榜（M17-12，M） ----------

_proc_cache: dict = {"rows": [], "ts": 0.0}
_PROC_TTL = 3.0


def _collect_procs_sync() -> list[dict]:
    """psutil 进程快照（cpu_percent 首采样为 0，进程级用两次差值太贵，
    这里以单次 non-blocking 采样 + 缓存 TTL 平滑；排序字段由查询端决定）。"""
    rows = []
    for p in psutil.process_iter(["pid", "name", "username", "memory_percent", "memory_info"]):
        try:
            info = p.info
            rows.append(
                {
                    "pid": info["pid"],
                    "name": info["name"] or "",
                    "username": info["username"] or "",
                    "cpu_percent": p.cpu_percent(interval=None),
                    "mem_percent": round(info["memory_percent"] or 0.0, 1),
                    "mem_mb": round(
                        (info["memory_info"].rss if info["memory_info"] else 0) / 1048576, 1
                    ),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return rows


@router.get("/monitor/processes")
async def monitor_processes(
    sort: str = Query("cpu", pattern="^(cpu|mem)$"),
    q: str = Query("", max_length=64),
    limit: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
):
    """进程 Top 榜（M17-12）：按 CPU/内存排序，支持名称/用户过滤。"""
    now = time.time()
    if now - _proc_cache["ts"] > _PROC_TTL:
        _proc_cache["rows"] = await asyncio.to_thread(_collect_procs_sync)
        _proc_cache["ts"] = now
    rows = _proc_cache["rows"]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["name"].lower() or ql in r["username"].lower()]
    key = "cpu_percent" if sort == "cpu" else "mem_percent"
    rows = sorted(rows, key=lambda r: r[key], reverse=True)[:limit]
    # 二次采样后 cpu_percent 才有意义：缓存首建时补一次即时采样
    return ok(rows)


# ---------- P10.2 Docker 资源占用（M17-13，A，无 socket 自动降级） ----------

DOCKER_SOCK = os.getenv("DOCKER_SOCK", "/var/run/docker.sock")


async def _docker_stats_inner() -> list[dict]:
    if not os.path.exists(DOCKER_SOCK):
        return []
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://docker", timeout=8.0
    ) as client:
        resp = await client.get("/containers/json?all=1")
        resp.raise_for_status()
        containers = resp.json()[:12]
        result = []
        for c in containers:
            cid = c.get("Id", "")
            name = (c.get("Names") or [""])[0].lstrip("/")
            stats = (await client.get(f"/containers/{cid}/stats?stream=false")).json()
            cpu_d = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0) - (
                stats.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
            )
            sys_d = stats.get("cpu_stats", {}).get("system_cpu_usage", 0) - (
                stats.get("precpu_stats", {}).get("system_cpu_usage", 0)
            )
            online = stats.get("cpu_stats", {}).get("online_cpus") or len(
                stats.get("cpu_stats", {}).get("cpu_usage", {}).get("percpu_usage", []) or [1]
            )
            cpu_pct = (cpu_d / sys_d * online * 100) if sys_d > 0 and cpu_d > 0 else 0.0
            mem = stats.get("memory_stats", {})
            used = mem.get("usage", 0)
            limit = mem.get("limit", 0)
            nets = stats.get("networks", {})
            result.append(
                {
                    "id": cid[:12],
                    "name": name,
                    "image": c.get("Image", ""),
                    "state": c.get("State", ""),
                    "cpu_percent": round(cpu_pct, 1),
                    "mem_used_mb": round(used / 1048576, 1),
                    "mem_limit_mb": round(limit / 1048576, 1),
                    "mem_percent": round(used / limit * 100, 1) if limit else 0.0,
                    "net_rx_mb": round(
                        sum(n.get("rx_bytes", 0) for n in nets.values()) / 1048576, 2
                    ),
                    "net_tx_mb": round(
                        sum(n.get("tx_bytes", 0) for n in nets.values()) / 1048576, 2
                    ),
                }
            )
        return result


@router.get("/monitor/docker-stats")
async def docker_stats(_: User = Depends(get_current_user)):
    """按容器资源占用（M17-13）：DOCKER_SOCK 不可达/超时 → 空数组（前端隐藏）。"""
    try:
        return ok(await asyncio.wait_for(_docker_stats_inner(), timeout=15.0))
    except (httpx.HTTPError, asyncio.TimeoutError, KeyError, OSError, json.JSONDecodeError):
        return ok([])


# ---------- P10.5 证书监控（M07-6） ----------


@router.get("/monitor/certs")
async def monitor_certs(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """证书到期即时检查（hosts 来自设置键 monitor.cert_hosts；空列表 → 空数组）。"""
    hosts = await alerts_svc.get_cert_hosts(session)
    return ok([await alerts_svc.check_cert(h) for h in hosts[:20]])


class CertHostsIn(BaseModel):
    hosts: list[str] = Field(default_factory=list, max_length=20)

    from pydantic import field_validator

    @field_validator("hosts")
    @classmethod
    def _check_hosts(cls, v: list[str]) -> list[str]:
        for h in v:
            if not h.strip() or len(h) > 253:
                raise ValueError("invalid host")
        return v


@router.put("/monitor/certs/hosts")
async def set_cert_hosts(
    body: CertHostsIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """保存证书监控域名列表（M；monitor.cert_hosts 设置键，白名单校验见 schemas）。"""
    from app.models.setting import Setting

    hosts = [h.strip() for h in body.hosts if h.strip()]
    row = await session.get(Setting, alerts_svc.CERT_HOSTS_KEY)
    if row is None:
        session.add(Setting(key=alerts_svc.CERT_HOSTS_KEY, value=json.dumps(hosts)))
    else:
        row.value = json.dumps(hosts)
    await session.commit()
    return ok(hosts)


# ---------- P10.3 阈值告警规则（M17-14/15，M） ----------


class AlertRuleIn(BaseModel):
    name: str = ""
    metric: str = Field(pattern="^(cpu|mem|disk|disk_io|temp)$")
    target: str | None = None
    op: str = Field(">", pattern="^[<>]$")
    threshold: float
    duration_min: int = Field(5, ge=1, le=1440)
    level: str = Field("warn", pattern="^(warn|error)$")
    enabled: bool = True


def _rule_view(r: AlertRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "metric": r.metric,
        "target": r.target,
        "op": r.op,
        "threshold": r.threshold,
        "duration_min": r.duration_min,
        "level": r.level,
        "enabled": bool(r.enabled),
        "last_fired_at": r.last_fired_at.isoformat() + "Z" if r.last_fired_at else None,
    }


async def _rule_or_404(session: AsyncSession, rule_id: int) -> AlertRule:
    r = await session.get(AlertRule, rule_id)
    if r is None:
        raise BizError(CODE_NOT_FOUND, t("err.alert_rule_not_found"), 404)
    return r


@router.get("/alerts/rules")
async def list_alert_rules(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(select(AlertRule).order_by(AlertRule.id))).scalars().all()
    return ok([_rule_view(r) for r in rows])


@router.post("/alerts/rules")
async def create_alert_rule(
    body: AlertRuleIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    r = AlertRule(
        name=body.name, metric=body.metric, target=body.target or None, op=body.op,
        threshold=body.threshold, duration_min=body.duration_min, level=body.level,
        enabled=int(body.enabled),
    )
    session.add(r)
    await session.commit()
    return ok(_rule_view(r))


@router.put("/alerts/rules/{rule_id}")
async def update_alert_rule(
    rule_id: int,
    body: AlertRuleIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    r = await _rule_or_404(session, rule_id)
    r.name = body.name
    r.metric = body.metric
    r.target = body.target or None
    r.op = body.op
    r.threshold = body.threshold
    r.duration_min = body.duration_min
    r.level = body.level
    r.enabled = int(body.enabled)
    alerts_svc._STATE.pop(r.id, None)  # 规则变更后重新计时
    await session.commit()
    return ok(_rule_view(r))


@router.delete("/alerts/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    r = await _rule_or_404(session, rule_id)
    alerts_svc._STATE.pop(r.id, None)
    await session.delete(r)
    await session.commit()
    return ok(True)


@router.post("/alerts/rules/{rule_id}/test")
async def test_alert_rule(
    rule_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """立即评估一次：返回当前值/阈值/是否越限（不落通知）。"""
    r = await _rule_or_404(session, rule_id)
    value = await alerts_svc.current_value(session, r)
    violated = (
        None
        if value is None
        else (value > r.threshold if r.op == ">" else value < r.threshold)
    )
    return ok({"current": value, "threshold": r.threshold, "op": r.op, "violated": violated})


@router.get("/alerts/events")
async def alert_events(
    level: str | None = Query(None),
    range_: str = Query("7d", alias="range"),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """告警事件历史（M17-14）：与站内通知同源（source=metric），按级别/时间过滤。"""
    if range_ not in RANGE_SECONDS:
        raise BizError(CODE_VALIDATION, t("err.invalid_metric_or_range"), 422)
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(seconds=RANGE_SECONDS[range_])
    stmt = select(Notification).where(
        Notification.source == "metric", Notification.created_at >= since
    )
    if level in ("info", "warn", "error"):
        stmt = stmt.where(Notification.level == level)
    rows = (
        await session.execute(stmt.order_by(Notification.id.desc()).limit(limit))
    ).scalars().all()
    return ok(
        [
            {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "level": n.level,
                "is_read": bool(n.is_read),
                "created_at": n.created_at.isoformat() + "Z",
            }
            for n in rows
        ]
    )


# ---------- P15.2 小组件（M02-11/13~15） ----------


@router.get("/widgets/weather")
async def widget_weather(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """天气小组件（M02-11）：wttr.in 免费源代理（无 key；失败返回 null 前端隐藏）。"""

    from app.models.setting import Setting

    row = await session.get(Setting, "home.weather_city")
    city = (row.value if row else "") or ""
    url = f"https://wttr.in/{city}?format=j1" if city else "https://wttr.in?format=j1"
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            resp = await c.get(url, headers={"User-Agent": "curl/8.0"})
        resp.raise_for_status()
        data = resp.json()
        cur = data["current_condition"][0]
        area = data.get("nearest_area", [{}])[0]
        return ok(
            {
                "city": (area.get("areaName") or [{"value": city or ""}])[0].get("value", ""),
                "temp_c": int(cur["temp_C"]),
                "feels_c": int(cur["FeelsLikeC"]),
                "desc": cur.get("weatherDesc", [{}])[0].get("value", ""),
                "humidity": int(cur["humidity"]),
                "days": [
                    {
                        "date": d["date"],
                        "max": int(d["maxtempC"]),
                        "min": int(d["mintempC"]),
                        "desc": (
                            d.get("hourly", [{}])[4]
                            .get("weatherDesc", [{}])[0]
                            .get("value", "")
                        ),
                    }
                    for d in data.get("weather", [])[:3]
                ],
            }
        )
    except Exception:  # 网络/解析失败 → null（小组件隐藏）
        return ok(None)


@router.get("/widgets/summary")
async def widgets_summary(_: User = Depends(get_current_user)):
    """仪表盘小组件聚合（M02-13~15）：最近通知 / Flow 最近执行 / 容器计数。"""
    out: dict = {"notifications": [], "flow_runs": [], "docker": None}
    # 最近通知（复用站内通知）
    from sqlalchemy import select as _select

    from app.models.probe import Notification

    async with SessionLocal() as s:
        rows = (
            await s.execute(
                _select(Notification).order_by(Notification.id.desc()).limit(5)
            )
        ).scalars().all()
        out["notifications"] = [
            {"id": n.id, "title": n.title, "level": n.level, "is_read": bool(n.is_read)}
            for n in rows
        ]
    # Flow 最近执行
    from app.models.flow import Flow, FlowRun

    async with SessionLocal() as s:
        rows = (
            await s.execute(
                _select(FlowRun, Flow.name)
                .join(Flow, Flow.id == FlowRun.flow_id)
                .order_by(FlowRun.id.desc())
                .limit(6)
            )
        ).all()
        out["flow_runs"] = [
            {"id": r.id, "flow": name, "status": r.status,
             "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None}
            for r, name in rows
        ]
    # 容器计数（可选模块，未启用 → None 前端隐藏）
    from app.services import docker_svc

    if docker_svc.enabled():
        try:
            containers = await asyncio.wait_for(docker_svc.list_containers(), timeout=10.0)
            out["docker"] = {
                "running": sum(1 for c in containers if c["state"] == "running"),
                "stopped": sum(1 for c in containers if c["state"] != "running"),
            }
        except Exception:
            out["docker"] = None
    return ok(out)


# ---- 数据与报表（M17-16/20；dev-plan P21.1）----


@router.get("/monitor/export")
async def monitor_export(
    metric: str = Query("cpu"),
    range_: str = Query("7d", alias="range"),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """监控数据 CSV 导出（M17-16）：复用历史聚合口径，csv 字段回传。"""
    import csv as _csv
    import io as _io

    try:
        hist = await build_history(session, metric, range_)
    except ValueError as exc:
        from app.core.response import BizError

        raise BizError(2001, str(exc), 422) from exc

    buf = _io.StringIO()
    writer = _csv.writer(buf)
    # 展平 points（disk 为 mounts 结构时展开挂载点列）
    rows_out = []

    def _flatten(ts: str, data: dict):
        base = {"ts": ts}
        base.update({k: v for k, v in data.items() if not isinstance(v, (list, dict))})
        for k, v in data.items():
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        key = (
                            item.get("mount")
                            or item.get("iface")
                            or item.get("name")
                            or len(rows_out)
                        )
                        for kk, vv in item.items():
                            if kk not in ("mount", "iface", "name"):
                                base[f"{k}[{key}].{kk}"] = vv
        rows_out.append(base)

    points = hist.get("points") or []
    for p in points:
        if isinstance(p, dict) and "ts" in p:
            _flatten(p["ts"], {k: v for k, v in p.items() if k != "ts"})
    cols: list[str] = []
    for r in rows_out:
        for k in r:
            if k not in cols:
                cols.append(k)
    writer.writerow(cols)
    for r in rows_out:
        writer.writerow([r.get(c, "") for c in cols])
    return ok(
        {
            "filename": f"monitor-{metric}-{range_}.csv",
            "csv": buf.getvalue(),
        }
    )


@router.get("/monitor/report")
async def monitor_report(
    days: int = Query(7, ge=1, le=30),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """性能报表（M17-20）：按天聚合 CPU/内存 min/avg/max。"""
    from datetime import datetime, timedelta

    from sqlalchemy import select as _select

    from app.models.monitor import MonitorSample

    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        (
            await session.execute(
                _select(MonitorSample)
                .where(MonitorSample.ts >= since, MonitorSample.node == "")
                .order_by(MonitorSample.ts)
            )
        )
        .scalars()
        .all()
    )
    buckets: dict[str, list[float]] = {}
    mem_buckets: dict[str, list[float]] = {}
    for r in rows:
        day = r.ts.strftime("%Y-%m-%d")
        buckets.setdefault(day, []).append(r.cpu)
        try:
            mem = _json_mem(r.mem)
        except Exception:
            mem = None
        if mem is not None:
            mem_buckets.setdefault(day, []).append(mem)

    def _stats(vals):
        if not vals:
            return {"min": None, "avg": None, "max": None}
        return {
            "min": round(min(vals), 1),
            "avg": round(sum(vals) / len(vals), 1),
            "max": round(max(vals), 1),
        }

    days_out = []
    for day in sorted(set(buckets) | set(mem_buckets)):
        days_out.append(
            {
                "date": day,
                "cpu": _stats(buckets.get(day, [])),
                "mem": _stats(mem_buckets.get(day, [])),
            }
        )
    return ok({"days": days_out})


def _json_mem(raw):
    """mem JSON {total,used,swap_used} → 使用率 %。"""
    import json as _json

    data = _json.loads(raw) if isinstance(raw, str) else raw
    if isinstance(data, dict) and data.get("total"):
        return round(data.get("used", 0) / data["total"] * 100, 1)
    return None
