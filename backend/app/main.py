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

from app.api.v1.monitor import cleanup_job, monitor_ws, sampler_job
from app.api.v1.ports import ports_job
from app.api.v1.probe import notify_ws, probe_job
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.i18n import set_locale
from app.core.middleware import TransportEncryptionMiddleware
from app.core.response import CODE_VALIDATION, BizError, fail, format_validation_errors
from app.core.scheduler import scheduler as _scheduler
from app.db.session import SessionLocal, init_db
from app.services.alerts import check_certs_and_notify, evaluate_alerts
from app.services.monitor import prime_cpu_counters, refresh_gpu_cache, setup_host_sources


async def alerts_evaluate_job() -> None:
    """阈值告警评估（P10.3）：每 30s 对启用规则跑一次状态机。"""
    async with SessionLocal() as session:
        await evaluate_alerts(session)


async def certs_check_job() -> None:
    """证书到期检查（P10.5）：每 6h 对 monitor.cert_hosts 做分级提醒。"""
    async with SessionLocal() as session:
        await check_certs_and_notify(session)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
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


@app.websocket("/ws/notify")
async def ws_notify(websocket: WebSocket):
    """状态变化广播（P6.3；api-spec §5）。"""
    await notify_ws(websocket)


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
