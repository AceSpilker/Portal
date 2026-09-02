"""Portal 后端入口（dev-plan P0.2）。

- /api/...     JSON 接口（统一响应，见 api-spec §1/§2）
- /            前端构建产物（存在时托管，单容器部署）
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.middleware import TransportEncryptionMiddleware
from app.core.response import CODE_VALIDATION, BizError, fail
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Portal API", version="0.1.0", lifespan=lifespan)

# 传输加密（P24）：/api 请求体/响应体/Authorization 头密文传输
app.add_middleware(TransportEncryptionMiddleware)


@app.exception_handler(BizError)
async def biz_error_handler(_: Request, exc: BizError):
    return fail(exc.code, exc.message, exc.http_status)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    return fail(CODE_VALIDATION, f"参数校验失败：{exc.errors()[:3]}", 422)


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
