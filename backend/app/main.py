"""Portal 后端入口（dev-plan P0.2）。

- /api/...     JSON 接口（统一响应，见 api-spec §1/§2）
- /ws/monitor  监控实时推送（api-spec §5）
- /            前端构建产物（存在时托管，单容器部署）
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from app.api.v1 import downloads
from app.api.v1.ai import ai_chat_ws
from app.api.v1.files import serve_raw
from app.api.v1.monitor import cleanup_job, monitor_ws, sampler_job
from app.api.v1.ports import ports_job
from app.api.v1.probe import notify_ws, probe_job
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.i18n import set_locale
from app.core.middleware import TransportEncryptionMiddleware
from app.core.response import CODE_VALIDATION, BizError, fail, format_validation_errors
from app.core.scheduler import scheduler as _scheduler
from app.core.stores import stores
from app.db.session import SessionLocal, init_db
from app.services.alerts import check_certs_and_notify, evaluate_alerts
from app.services.flow_svc import restore_cron_jobs as flow_restore
from app.services.monitor import prime_cpu_counters, refresh_gpu_cache, setup_host_sources


async def alerts_evaluate_job() -> None:
    """阈值告警评估（P10.3）：每 30s 对启用规则跑一次状态机。"""
    async with SessionLocal() as session:
        await evaluate_alerts(session)


async def mysql_sync_job() -> None:
    """MySQL 镜像推送（P23.3/23.4）：每 60s 醒来判断到期（成功按 interval，失败退避）。"""
    import json as _json
    from datetime import datetime, timedelta

    from app.models.setting import Setting
    from app.services.mysql_sync import push_all

    async with SessionLocal() as session:
        row = await session.get(Setting, "mysql.enabled")
        if row is None or not _json.loads(row.value):
            return
        # 到期判定：最近一次成功推送 + interval，或失败退避由 push_all 内部处理
        interval_row = await session.get(Setting, "mysql.interval_min")
        interval_min = int(_json.loads(interval_row.value)) if interval_row else 30
        due_row = await session.get(Setting, "sync.last_push")
        due = None
        if due_row:
            try:
                due = datetime.fromisoformat(_json.loads(due_row.value))
            except (ValueError, TypeError):
                due = None
        now = datetime.utcnow()
        if due is not None and now < due + timedelta(minutes=interval_min):
            return
        await push_all(session)
        await session.merge(
            Setting(key="sync.last_push", value=_json.dumps(now.isoformat()))
        )
        await session.commit()


async def tunnel_reaper_job() -> None:
    """隧道巡检（P20.1）：断线重连 + 空闲回收。"""
    from app.services import tunnel_svc

    async with SessionLocal() as session:
        await tunnel_svc.reap_and_reconnect(session)


async def ports_advanced_job() -> None:
    """端口进阶（P20.3）：监听快照差异 + 采样清理。"""
    from app.services.ports import cleanup_port_samples, record_listen_snapshot

    async with SessionLocal() as session:
        await record_listen_snapshot(session)
        await cleanup_port_samples(session)


async def redis_recheck_job() -> None:
    """Redis 健康回切（P25.4）：每 30s PING；断连降级内存、恢复自动回切。"""

    from app.api.v1.redis import get_config as redis_get_config
    from app.core.stores import stores

    async with SessionLocal() as session:
        cfg = await redis_get_config(session)
        if not (cfg["enabled"] and cfg["host"]):
            return
        if stores.mode == "redis":
            await stores.ping()  # 已连接：探活防静默断连
        else:
            # 降级/初始：尝试（重）连接回切
            await stores.configure_redis(
                cfg["host"], cfg["port"], cfg["password"], cfg["db"], cfg["key_prefix"]
            )


async def backup_job() -> None:
    """自动备份（P17.3/M15-8）：每日落盘 data/backups，保留 N 份。"""
    import json as _json

    from app.models.setting import Setting
    from app.services.backup import write_disk_backup

    async with SessionLocal() as session:
        row = await session.get(Setting, "backup.enabled")
        if row is None or _json.loads(row.value):
            await write_disk_backup(session)


async def update_check_job() -> None:
    """版本更新定时检查（P17.5/M15-9）：默认 6h，仅提醒不自动更新。"""
    import json as _json

    from sqlalchemy import select as _select

    from app.api.v1.system import update_check
    from app.models.setting import Setting
    from app.models.user import User

    async with SessionLocal() as session:
        row = await session.get(Setting, "update.auto_check")
        if row is not None and not _json.loads(row.value):
            return
        admin = (
            (await session.execute(_select(User).where(User.role == "admin"))).scalars().first()
        )
        if admin is None:
            return
        try:
            await update_check(_=admin, session=session)  # 网络异常不打扰
        except Exception:
            pass


async def schedule_reminder_job() -> None:
    """日程提醒扫描（M13-3；P16.1）：每 30s 检查到期事件，经 P9 通知。"""
    from datetime import datetime

    from app.api.v1.schedule import reminder_scan

    async with SessionLocal() as session:
        await reminder_scan(session, datetime.utcnow())


async def urls_probe_job() -> None:
    """入口延迟轮询（P15.4/M04-14）：每 5min 探测全部入口并记录采样。"""
    from app.services.connectivity import probe_all_urls

    async with SessionLocal() as session:
        await probe_all_urls(session)


async def urls_probe_cleanup_job() -> None:
    """入口延迟采样清理（P15.4）：每小时清一次过期数据。"""
    from app.services.connectivity import cleanup_url_samples

    async with SessionLocal() as session:
        await cleanup_url_samples(session)


async def certs_check_job() -> None:
    """证书到期检查（P10.5）：每 6h 对 monitor.cert_hosts 做分级提醒。"""
    async with SessionLocal() as session:
        await check_certs_and_notify(session)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    # Redis 存储初始化（P25.1）：读取配置并连接（失败降级内存，由回切任务重试）
    from app.api.v1.redis import get_config as redis_get_config

    async with SessionLocal() as session:
        cfg = await redis_get_config(session)
        if cfg["enabled"] and cfg["host"]:
            await stores.configure_redis(
                cfg["host"], cfg["port"], cfg["password"], cfg["db"], cfg["key_prefix"]
            )
    # 监控采集（P5.1/P5.2）：宿主机数据源 + cpu_percent 预热 + 分钟采样/小时清理
    setup_host_sources()
    prime_cpu_counters()
    _scheduler.add_job(
        sampler_job, "interval", seconds=10, id="monitor_sample",
        max_instances=1, replace_existing=True,
    )
    _scheduler.add_job(
        cleanup_job, "interval", hours=1, id="monitor_cleanup",
        max_instances=1, replace_existing=True,
    )
    # GPU 缓存刷新（nvidia-smi 子进程查询不能阻塞推送循环）
    _scheduler.add_job(
        refresh_gpu_cache, "interval", seconds=5, id="monitor_gpu",
        max_instances=1, replace_existing=True,
    )
    # 应用探活（P6.1/P6.2）：每 10s 巡检到期应用
    _scheduler.add_job(
        probe_job, "interval", seconds=10, id="app_probe",
        max_instances=1, replace_existing=True,
    )
    # 阈值告警评估（P10.3/M17-14）：每 30s 跑一次状态机
    _scheduler.add_job(
        alerts_evaluate_job, "interval", seconds=30, id="alerts_evaluate",
        max_instances=1, replace_existing=True,
    )
    # 证书到期检查（P10.5/M07-6）：每 6h，dedup 按天
    _scheduler.add_job(
        certs_check_job, "interval", hours=6, id="certs_check",
        max_instances=1, replace_existing=True,
    )
    # 入口延迟历史（P15.4/M04-14）：5min 轮询 + 每小时清理
    _scheduler.add_job(
        urls_probe_job, "interval", seconds=300, id="url_probe",
        max_instances=1, replace_existing=True,
    )
    _scheduler.add_job(
        urls_probe_cleanup_job, "interval", hours=1, id="url_probe_cleanup",
        max_instances=1, replace_existing=True,
    )
    # 日程提醒（P16.1/M13-3）与下载完成轮询（P16.3/M12-4）
    _scheduler.add_job(
        schedule_reminder_job, "interval", seconds=30, id="schedule_reminder",
        max_instances=1, replace_existing=True,
    )
    _scheduler.add_job(
        downloads.downloads_job, "interval", seconds=60, id="downloads_poll",
        max_instances=1, replace_existing=True,
    )
    # MySQL 镜像同步（P23）：60s 心跳判断到期
    _scheduler.add_job(
        mysql_sync_job, "interval", seconds=60, id="mysql_sync",
        max_instances=1, replace_existing=True,
    )
    # 隧道巡检（P20.1）与端口进阶（P20.3）
    _scheduler.add_job(
        tunnel_reaper_job, "interval", seconds=30, id="tunnel_reaper",
        max_instances=1, replace_existing=True,
    )
    _scheduler.add_job(
        ports_advanced_job, "interval", seconds=60, id="ports_advanced",
        max_instances=1, replace_existing=True,
    )
    # Redis 健康回切（P25.4）
    _scheduler.add_job(
        redis_recheck_job, "interval", seconds=30, id="redis_recheck",
        max_instances=1, replace_existing=True,
    )
    # 自动备份（P17.3）与版本检查（P17.5）
    _scheduler.add_job(
        backup_job, "interval", hours=24, id="auto_backup",
        max_instances=1, replace_existing=True,
    )
    _scheduler.add_job(
        update_check_job, "interval", hours=6, id="update_check",
        max_instances=1, replace_existing=True,
    )
    # Flow cron 触发器（P14.1/M06-4）：恢复启用中的 cron Flow
    await flow_restore(_scheduler)
    # 端口探活（P11.2/M18-2）：每 10s 巡检到期监控项
    _scheduler.add_job(
        ports_job, "interval", seconds=10, id="port_probe",
        max_instances=1, replace_existing=True,
    )
    if not _scheduler.running:  # 测试环境会多次进入 lifespan
        _scheduler.start()
    yield
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="Portal API", version="0.1.0", lifespan=lifespan)

# 传输加密（P24）：/api 请求体/响应体/Authorization 头密文传输
app.add_middleware(TransportEncryptionMiddleware)


@app.middleware("http")
async def locale_middleware(request: Request, call_next):
    """按 Accept-Language 设置本请求的文案语言（api-spec §1）。"""
    set_locale(request.headers.get("accept-language", ""))
    return await call_next(request)


async def _tunnel_proxy(request: Request, tunnel_id: int, path: str):
    """隧道反代（P20.2）：签名 token/cookie 校验 → 经本地转发端口反代 HTTP。"""

    from app.core.security import decode_token
    from app.services import tunnel_svc

    token = request.query_params.get("t", "")
    mode = "query"
    if not token:
        cookie = request.cookies.get(f"ptun_{tunnel_id}", "")
        mode = "cookie" if cookie else ""
        token = cookie
    valid = False
    if token:
        try:
            payload = decode_token(token, "tunnel")
            valid = int(payload.get("tid", -1)) == tunnel_id
        except Exception:
            valid = False
    if not valid:
        return fail(4001, "tunnel link invalid", 404)
    port = await tunnel_svc.open_local_port(tunnel_id)
    if port is None:
        return fail(4004, "tunnel not running", 404)
    tunnel_svc.touch(tunnel_id)

    import httpx

    target = f"http://127.0.0.1:{port}/{path}"
    if request.url.query:
        target += "?" + request.url.query
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "cookie", "authorization", "x-session-id")
    }
    body = await request.body()
    client = httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}", timeout=30.0,
    )
    try:
        query = ("?" + request.url.query) if request.url.query else ""
        resp = await client.request(
            request.method,
            f"/{path}{query}",
            headers=headers,
            content=body if request.method not in ("GET", "HEAD") else None,
            follow_redirects=False,
        )
        resp_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in ("content-length", "transfer-encoding", "connection")
        }
        from starlette.responses import Response as StarletteResponse

        response = StarletteResponse(
            content=resp.content, status_code=resp.status_code,
            headers=resp_headers, media_type=resp.headers.get("content-type"),
        )
        if mode == "query":
            response.set_cookie(
                f"ptun_{tunnel_id}", token,
                max_age=1800, httponly=True, samesite="lax", path="/",
            )
        return response
    except httpx.HTTPError as exc:
        return fail(4004, f"tunnel upstream error: {str(exc)[:120]}", 502)
    finally:
        await client.aclose()


_TUNNEL_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


@app.api_route("/tunnel/{tunnel_id}/{path:path}", methods=_TUNNEL_METHODS)
@app.api_route("/tunnel/{tunnel_id}", methods=_TUNNEL_METHODS)
async def tunnel_proxy_entry(request: Request, tunnel_id: int, path: str = ""):
    return await _tunnel_proxy(request, tunnel_id, path)


@app.get("/files/raw")
async def files_raw(token: str):
    """文件预览直链（P16.2/M11-4）：短时签名 token，/api 之外豁免信封。"""
    return await serve_raw(token)


@app.websocket("/ws/notify")
async def ws_notify(websocket: WebSocket):
    """状态变化广播（P6.3；api-spec §5）。"""
    await notify_ws(websocket)


@app.websocket("/ws/ai-chat")
async def ws_ai_chat(websocket: WebSocket):
    """AI 流式对话（M05-6；P13.2）：query token 鉴权，双向 JSON 帧流。"""
    await ai_chat_ws(websocket)


@app.websocket("/ws/monitor")
async def ws_monitor(websocket: WebSocket):
    """监控实时推送（P5.3；api-spec §5）：管理员 token 鉴权后每 2 秒推送。"""
    await monitor_ws(websocket)


@app.exception_handler(BizError)
async def biz_error_handler(_: Request, exc: BizError):
    return fail(exc.code, exc.message, exc.http_status)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    return fail(CODE_VALIDATION, format_validation_errors(exc.errors()), 422)


app.include_router(api_router, prefix="/api")


def _mount_icons() -> None:
    """上传图标静态托管（P2.4）：/icons → data/icons（静态资源豁免传输加密）。"""
    icons = Path(settings.data_dir) / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    app.mount("/icons", StaticFiles(directory=str(icons)), name="icons")


def _mount_frontend() -> None:
    """前端构建产物托管（存在则启用；生产镜像内位于 frontend/dist）。"""
    dist = (
        Path(settings.frontend_dist)
        if settings.frontend_dist
        else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")


_mount_icons()
_mount_frontend()
