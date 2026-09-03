"""Flow 自动化接口（M06；dev-plan P14；api-spec §4.7）。

- Flow CRUD（A 读 M 写；webhook 触发器自动生成随机 token，PUT type 变更时重置）；
- 手动执行 / dry-run（M）；执行历史（A 读）；
- POST /hooks/flow/{token}（P，token 鉴权；传输加密豁免面见 middleware）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, CODE_VALIDATION, BizError, ok
from app.core.scheduler import scheduler
from app.db.session import get_session
from app.models.flow import Flow, FlowRun
from app.models.user import User
from app.services import flow_svc

router = APIRouter()

TRIGGERS = ("cron", "webhook", "manual", "event")


def _flow_view(f: Flow) -> dict:
    try:
        cfg = json.loads(f.trigger_config or "{}")
    except json.JSONDecodeError:
        cfg = {}
    return {
        "id": f.id,
        "name": f.name,
        "description": f.description,
        "trigger_type": f.trigger_type,
        "trigger_config": cfg,
        "actions": json.loads(f.actions or "[]"),
        "enabled": bool(f.enabled),
        "webhook_token": f.webhook_token,
        "retry": f.retry,
        "retry_interval": f.retry_interval,
        "last_run_at": f.last_run_at.isoformat() + "Z" if f.last_run_at else None,
    }


async def _flow_or_404(session: AsyncSession, flow_id: int) -> Flow:
    f = await session.get(Flow, flow_id)
    if f is None:
        raise BizError(CODE_NOT_FOUND, t("err.flow_not_found"), 404)
    return f


class FlowIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""
    trigger_type: str = "manual"
    trigger_config: dict = Field(default_factory=dict)
    actions: list[dict] = Field(default_factory=list)
    enabled: bool = False
    retry: int = Field(0, ge=0, le=10)
    retry_interval: int = Field(60, ge=5, le=3600)


def _validate(body: FlowIn) -> None:
    if body.trigger_type not in TRIGGERS:
        raise BizError(CODE_VALIDATION, t("err.flow_bad_trigger"), 422)
    if body.trigger_type == "cron" and not str(body.trigger_config.get("cron", "")).strip():
        raise BizError(CODE_VALIDATION, t("err.flow_bad_trigger"), 422)
    if body.trigger_type == "event":
        ev = body.trigger_config.get("event")
        if ev not in ("app_down", "app_up", "metric_alert", "port_down", "port_up", "flow_failed"):
            raise BizError(CODE_VALIDATION, t("err.flow_bad_trigger"), 422)
    for step in body.actions:
        if step.get("type") not in ("http", "notify", "condition"):
            raise BizError(CODE_VALIDATION, t("err.flow_bad_action"), 422)


@router.get("/flows")
async def list_flows(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(select(Flow).order_by(Flow.id))).scalars().all()
    return ok([_flow_view(f) for f in rows])


@router.get("/flows/{flow_id}")
async def get_flow(
    flow_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    f = await _flow_or_404(session, flow_id)
    return ok(_flow_view(f))


@router.post("/flows")
async def create_flow(
    body: FlowIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _validate(body)
    token = flow_svc.gen_webhook_token() if body.trigger_type == "webhook" else None
    f = Flow(
        name=body.name, description=body.description, trigger_type=body.trigger_type,
        trigger_config=json.dumps(body.trigger_config), actions=json.dumps(body.actions),
        enabled=int(body.enabled), webhook_token=token,
        retry=body.retry, retry_interval=body.retry_interval,
    )
    session.add(f)
    await session.commit()
    flow_svc.sync_cron_job(scheduler, f)
    return ok(_flow_view(f))


@router.put("/flows/{flow_id}")
async def update_flow(
    flow_id: int,
    body: FlowIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _validate(body)
    f = await _flow_or_404(session, flow_id)
    f.name = body.name
    f.description = body.description
    f.trigger_type = body.trigger_type
    f.trigger_config = json.dumps(body.trigger_config)
    f.actions = json.dumps(body.actions)
    f.enabled = int(body.enabled)
    f.retry = body.retry
    f.retry_interval = body.retry_interval
    if body.trigger_type == "webhook" and not f.webhook_token:
        f.webhook_token = flow_svc.gen_webhook_token()
    if body.trigger_type != "webhook":
        f.webhook_token = None
    await session.commit()
    flow_svc.sync_cron_job(scheduler, f)
    return ok(_flow_view(f))


@router.delete("/flows/{flow_id}")
async def delete_flow(
    flow_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    f = await _flow_or_404(session, flow_id)
    flow_svc.sync_cron_job(scheduler, f)  # disabled 状态 → 移除 job
    await session.delete(f)
    await session.commit()
    return ok(True)


@router.post("/flows/{flow_id}/reset-token")
async def reset_token(
    flow_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """吊销并重置 webhook token（M06-5）。"""
    f = await _flow_or_404(session, flow_id)
    f.webhook_token = flow_svc.gen_webhook_token()
    await session.commit()
    return ok({"webhook_token": f.webhook_token})


@router.post("/flows/{flow_id}/run")
async def run_flow(
    flow_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    f = await _flow_or_404(session, flow_id)
    run = await flow_svc.execute_flow(session, f, "manual")
    return ok({"run_id": run.id, "status": run.status})


@router.post("/flows/{flow_id}/dry-run")
async def dry_run_flow(
    flow_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    f = await _flow_or_404(session, flow_id)
    run = await flow_svc.execute_flow(session, f, "manual", dry_run=True)
    return ok({"run_id": run.id, "status": run.status, "steps": json.loads(run.steps_log)})


@router.get("/flows/{flow_id}/runs")
async def flow_runs(
    flow_id: int,
    limit: int = Query(20, ge=1, le=100),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _flow_or_404(session, flow_id)
    rows = (
        await session.execute(
            select(FlowRun)
            .where(FlowRun.flow_id == flow_id)
            .order_by(FlowRun.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return ok([_run_view(r) for r in rows])


@router.get("/flow-runs/{run_id}")
async def run_detail(
    run_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    r = await session.get(FlowRun, run_id)
    if r is None:
        raise BizError(CODE_NOT_FOUND, t("err.flow_run_not_found"), 404)
    return ok(_run_view(r))


def _run_view(r: FlowRun) -> dict:
    return {
        "id": r.id,
        "flow_id": r.flow_id,
        "trigger": r.trigger,
        "status": r.status,
        "steps": json.loads(r.steps_log or "[]"),
        "started_at": r.started_at.isoformat() + "Z" if r.started_at else None,
        "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None,
        "duration_ms": r.duration_ms,
    }


class HookBody(BaseModel):
    payload: dict = Field(default_factory=dict)


@router.post("/hooks/flow/{token}")
async def hook_flow(
    token: str,
    body: HookBody | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Webhook 触发入口（P，token 鉴权；传输加密豁免）。"""
    f = await flow_svc.get_flow_by_token(session, token)
    if f is None:
        raise BizError(CODE_NOT_FOUND, t("err.flow_token_invalid"), 404)
    payload = body.payload if body else {}
    run = await flow_svc.execute_flow(session, f, "webhook", extra_vars={"payload": payload})
    return ok({"run_id": run.id, "status": run.status})
