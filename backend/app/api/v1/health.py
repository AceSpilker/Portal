"""系统健康检查（api-spec 4.12；dev-plan P0.2）。"""
from fastapi import APIRouter

from app.core.response import ok

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """健康检查：公开访问，供容器探活与前端联调自检。"""
    return ok({"status": "ok", "app": "portal", "version": "0.1.0"})
