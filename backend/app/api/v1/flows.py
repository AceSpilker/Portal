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
        "graph": json.loads(f.graph) if f.graph else None,
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
    graph: dict | None = None  # P19.1 画布图（提供时优先生效，actions 存线性投影）
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
        if step.get("type") not in flow_svc.NODE_TYPES:
            raise BizError(CODE_VALIDATION, t("err.flow_bad_action"), 422)
    if body.graph is not None:
        try:
            flow_svc.validate_graph(body.graph)
        except ValueError as exc:
            raise BizError(CODE_VALIDATION, t("err.flow_bad_graph", reason=str(exc)), 422) from exc


@router.get("/flows")
async def list_flows(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(select(Flow).order_by(Flow.id))).scalars().all()
    return ok([_flow_view(f) for f in rows])




FLOW_TEMPLATES: list[dict] = [
    {
        "key": "offline-restart",
        "name": "离线自动重启",
        "description": "应用离线事件 → Docker 重启该容器 → 失败则升级 error 通知（画布含条件分支）",
        "trigger_type": "event",
        "trigger_config": {"event": "app_down"},
        "graph": {
            "nodes": [
                {"id": "start", "type": "trigger", "name": "开始", "config": {}},
                {"id": "n1", "type": "docker", "name": "重启容器",
                 "config": {"container": "{vars.name}", "op": "restart"}},
                {"id": "n2", "type": "condition", "name": "重启成功？",
                 "expression": "prev.ok == True", "config": {}},
                {"id": "n3", "type": "notify", "name": "重启成功通知",
                 "config": {"title": "已自动重启：{vars.name}",
                            "body": "检测到离线并已自动重启容器", "level": "info"}},
                {"id": "n4", "type": "notify", "name": "升级告警",
                 "config": {"title": "自动重启失败：{vars.name}",
                            "body": "容器重启失败，请人工介入", "level": "error"}},
            ],
            "edges": [
                {"source": "start", "target": "n1"},
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n3", "source_handle": "true"},
                {"source": "n2", "target": "n4", "source_handle": "false"},
            ],
        },
    },
    {
        "key": "download-digest",
        "name": "每日下载摘要",
        "description": "每天 08:00 查询 qBittorrent 信息 → 校验接口成功 → 站内通知摘要",
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 8 * * *"},
        "graph": {
            "nodes": [
                {"id": "start", "type": "trigger", "name": "开始", "config": {}},
                {"id": "n1", "type": "http", "name": "查询 qBittorrent",
                 "config": {"method": "GET",
                            "url": "http://127.0.0.1:8080/api/v2/transfer/info"}},
                {"id": "n2", "type": "condition", "name": "接口正常？",
                 "expression": "prev.status_code == 200", "config": {}},
                {"id": "n3", "type": "notify", "name": "推送摘要",
                 "config": {"title": "下载器状态", "body": "{prev.body}", "level": "info"}},
            ],
            "edges": [
                {"source": "start", "target": "n1"},
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n3", "source_handle": "true"},
            ],
        },
    },
    {
        "key": "http-watchdog",
        "name": "定时巡检+延时复检",
        "description": "每 10 分钟 HTTP 巡检服务 → 失败等 60 秒复检思路（延时节点演示）→ 通知",
        "trigger_type": "cron",
        "trigger_config": {"cron": "*/10 * * * *"},
        "graph": {
            "nodes": [
                {"id": "start", "type": "trigger", "name": "开始", "config": {}},
                {"id": "n1", "type": "variable", "name": "记录目标",
                 "config": {"name": "target", "value": "http://127.0.0.1:8080"}},
                {"id": "n2", "type": "http", "name": "巡检",
                 "config": {"method": "GET", "url": "{vars.target}"}},
                {"id": "n3", "type": "delay", "name": "等待 60 秒", "config": {"seconds": 60}},
                {"id": "n4", "type": "notify", "name": "巡检结果",
                 "config": {"title": "巡检完成",
                            "body": "状态码 {prev.status_code}", "level": "info"}},
            ],
            "edges": [
                {"source": "start", "target": "n1"},
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n3"},
                {"source": "n3", "target": "n4"},
            ],
        },
    },
]


@router.get("/flows/templates")
async def list_flow_templates(_: User = Depends(get_current_user)):
    """内置 Flow 模板清单（P19.3）。"""
    return ok(
        [
            {k: t for k, t in tpl.items() if k != "graph"} | {"has_canvas": True}
            for tpl in FLOW_TEMPLATES
        ]
    )




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
    actions = body.actions
    if body.graph is not None:
        actions = flow_svc.graph_to_linear(body.graph)  # 线性投影（表单视图/兼容）
    f = Flow(
        name=body.name, description=body.description, trigger_type=body.trigger_type,
        trigger_config=json.dumps(body.trigger_config), actions=json.dumps(actions),
        graph=json.dumps(body.graph) if body.graph is not None else None,
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
    f.actions = json.dumps(
        flow_svc.graph_to_linear(body.graph) if body.graph is not None else body.actions
    )
    f.graph = json.dumps(body.graph) if body.graph is not None else None
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



# ---- Flow 导入导出（P19.3）----

@router.post("/flows/from-template")
async def create_from_template(
    body: dict,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """从模板一键创建 Flow（P19.3）：graph 存画布，actions 存线性投影。"""
    key = str(body.get("key", ""))
    tpl = next((t for t in FLOW_TEMPLATES if t["key"] == key), None)
    if tpl is None:
        raise BizError(CODE_NOT_FOUND, t("err.template_not_found"), 404)
    name = str(body.get("name", "")).strip() or tpl["name"]
    token = flow_svc.gen_webhook_token() if tpl["trigger_type"] == "webhook" else None
    f = Flow(
        name=name,
        description=tpl["description"],
        trigger_type=tpl["trigger_type"],
        trigger_config=json.dumps(tpl["trigger_config"]),
        actions=json.dumps(flow_svc.graph_to_linear(tpl["graph"])),
        graph=json.dumps(tpl["graph"]),
        enabled=0,
        webhook_token=token,
    )
    session.add(f)
    await session.commit()
    flow_svc.sync_cron_job(scheduler, f)
    return ok(_flow_view(f), t("ok.saved"))


@router.get("/flows/{flow_id}/export")
async def export_flow(
    flow_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """导出单个 Flow 为可分享 JSON（P19.3，不含运行历史与 token）。"""
    f = await _flow_or_404(session, flow_id)
    view = _flow_view(f)
    view.pop("webhook_token", None)
    view.pop("id", None)
    return ok({"_flow_export_version": 1, **view})


@router.post("/flows/import")
async def import_flow(
    body: dict,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """导入分享的 Flow JSON：重生成 webhook token，默认停用待检查。"""
    if not isinstance(body, dict) or not str(body.get("name", "")).strip():
        raise BizError(CODE_VALIDATION, t("v.flow_import_invalid"), 422)
    graph = body.get("graph")
    actions = body.get("actions") or []
    if graph is None:
        graph = flow_svc.linear_to_graph(actions)  # 旧分享格式升级为画布
    try:
        flow_svc.validate_graph(graph)
    except ValueError as exc:
        raise BizError(CODE_VALIDATION, t("err.flow_bad_graph", reason=str(exc)), 422) from exc
    f = Flow(
        name=str(body.get("name", "")).strip()[:60],
        description=str(body.get("description", "")),
        trigger_type=str(body.get("trigger_type", "manual")),
        trigger_config=json.dumps(body.get("trigger_config") or {}),
        actions=json.dumps(flow_svc.graph_to_linear(graph)),
        graph=json.dumps(graph),
        enabled=0,
        webhook_token=(
            flow_svc.gen_webhook_token()
            if str(body.get("trigger_type", "manual")) == "webhook"
            else None
        ),
        retry=int(body.get("retry") or 0),
        retry_interval=int(body.get("retry_interval") or 60),
    )
    session.add(f)
    await session.commit()
    flow_svc.sync_cron_job(scheduler, f)
    return ok(_flow_view(f), t("ok.imported"))
