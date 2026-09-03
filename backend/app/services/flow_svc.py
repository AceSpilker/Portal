"""Flow 自动化服务（M06；dev-plan P14；api-spec §3.7/§4.7/§4 hooks）。

- 表达式沙箱（M06-8）：ast 白名单解析（比较/逻辑/算术/属性/下标/常量），
  禁调用/导入/lambda 等；上下文仅 prev（上步输出）与 vars；
- 变量插值（M06-10）：{key} / {prev.xxx} 简单模板；
- 执行引擎：条件不满足跳过后续；HTTP/通知动作；失败重试 retry×retry_interval；
  失败 dispatch flow_failed（P9 出口）；每次执行落 flow_runs（steps_log）；
- 触发器：cron（APScheduler，调度器由 main 传入）/ webhook（随机 token，可重置）/
  manual / event（notify.dispatch 事件钩子触发，event 枚举见 notify）。
"""

from __future__ import annotations

import ast
import asyncio
import json
import secrets
import time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow import Flow, FlowRun
from app.services import notify

HTTP_TIMEOUT = 15.0
EVENT_HOOK_IGNORED = {"system"}  # flow 动作产生的通知 event 用 system，不触发事件 Flow（防自激）


# ---------- 表达式沙箱（M06-8；单测关卡） ----------

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.Constant, ast.Name, ast.Attribute, ast.Subscript, ast.Load,
    ast.List, ast.Tuple, ast.Dict, ast.Slice,
)


class UnsafeExpression(ValueError):
    """表达式包含沙箱禁止的语法。"""


class _AttrNS(dict):
    """dict 同时支持属性访问（prev.status_code）；递归包装子级。"""

    def __getattr__(self, k: str):
        v = self.get(k)
        if isinstance(v, dict):
            return _AttrNS(v)
        if v is None:
            raise AttributeError(k)
        return v


def _wrap_vars(variables: dict) -> dict:
    return {k: _AttrNS(v) if isinstance(v, dict) else v for k, v in variables.items()}


def safe_eval(expression: str, variables: dict) -> bool:
    """条件表达式安全求值；非法语法/名称/求值错误抛 UnsafeExpression。"""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpression(f"syntax error: {exc}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpression(f"disallowed syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in variables:
            raise UnsafeExpression(f"unknown name: {node.id}")
    try:
        # eval 用空 builtins；名称仅限注入的上下文（dict 兼容属性访问）
        return bool(
            eval(compile(tree, "<flow>", "eval"), {"__builtins__": {}}, _wrap_vars(variables))  # noqa: S307
        )
    except UnsafeExpression:
        raise
    except Exception as exc:
        raise UnsafeExpression(f"eval error: {exc}") from exc


def interpolate(template: str, variables: dict) -> str:
    """{key} / {prev.field} 变量插值；未知占位保持原样。"""

    def repl(match: "re.Match[str]") -> str:
        key = match.group(1).strip()
        node: object = variables
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return match.group(0)
        return str(node)

    import re

    return re.sub(r"\{([^{}]+)\}", repl, template)


# ---------- 触发器辅助 ----------


def gen_webhook_token() -> str:
    return secrets.token_urlsafe(24)


async def get_flow_by_token(session: AsyncSession, token: str) -> Flow | None:
    return (
        await session.execute(
            select(Flow).where(Flow.webhook_token == token, Flow.enabled.is_(True))
        )
    ).scalars().first()


# ---------- 执行引擎（M06-9/10/15~18） ----------


async def _run_http_action(cfg: dict, variables: dict) -> dict:
    method = str(cfg.get("method", "GET")).upper()
    url = interpolate(str(cfg.get("url", "")), variables)
    headers = {k: interpolate(str(v), variables) for k, v in (cfg.get("headers") or {}).items()}
    body = cfg.get("body")
    if isinstance(body, str):
        body = interpolate(body, variables)
    is_str = isinstance(body, str)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        resp = await c.request(
            method, url, headers=headers,
            content=body if is_str else None,
            json=None if is_str else body,
        )
    try:
        out: object = resp.json()
    except ValueError:
        out = resp.text[:500]
    result = {"status_code": resp.status_code, "body": out}
    if resp.status_code >= 400:
        result["error"] = f"HTTP {resp.status_code}"  # 非 2xx 视为动作失败（进重试）
    return result


async def _run_notify_action(session: AsyncSession, cfg: dict, variables: dict) -> dict:
    title = interpolate(str(cfg.get("title", "")), variables)
    body = interpolate(str(cfg.get("body", "")), variables)
    await notify.dispatch(
        session,
        event="system",
        source="flow",
        title=title or "Flow 通知",
        body=body,
        level=str(cfg.get("level", "info")),
    )
    return {"sent": True, "title": title}


async def _execute_step(
    session: AsyncSession,
    step: dict,
    variables: dict,
    dry_run: bool,
) -> dict:
    """执行单步（条件节点/HTTP/通知），返回步骤日志。"""
    stype = step.get("type")
    ts = datetime.utcnow().isoformat() + "Z"
    log: dict = {"type": stype, "name": step.get("name", ""), "ts": ts}
    if stype == "condition":
        expr = str(step.get("expression", ""))
        log["expression"] = expr
        try:
            log["result"] = safe_eval(expr, variables)
        except UnsafeExpression as exc:
            # 条件求值失败 ≠ 执行失败：按不满足处理（跳过后续），单独记 eval_error
            log["eval_error"] = str(exc)
            log["result"] = False
        return log

    # 条件不满足时后续动作跳过（由调用方根据 variables["_skip"] 判断）
    if variables.get("_skip"):
        log["skipped"] = True
        return log

    if stype == "http":
        cfg = step.get("config") or {}
        log["request"] = {
            "method": str(cfg.get("method", "GET")),
            "url": interpolate(str(cfg.get("url", "")), variables),
        }
        if dry_run:
            log["dry_run"] = True
            return log
        try:
            result = await _run_http_action(cfg, variables)
            log["output"] = result
            variables["prev"] = result
            if "error" in result:
                log["error"] = result["error"]  # 上层按失败重试
        except httpx.HTTPError as exc:
            log["error"] = str(exc)[:160]
            variables["prev"] = {"status_code": 0, "error": log["error"]}
            raise
    elif stype == "notify":
        cfg = step.get("config") or {}
        if dry_run:
            log["dry_run"] = True
            log["would_notify"] = interpolate(str(cfg.get("title", "")), variables)
            return log
        log["output"] = await _run_notify_action(session, cfg, variables)
    else:
        log["error"] = f"unknown action type: {stype}"
    return log


async def execute_flow(
    session: AsyncSession,
    flow: Flow,
    trigger: str,
    dry_run: bool = False,
    extra_vars: dict | None = None,
) -> FlowRun:
    """执行 Flow：逐步执行动作数组，重试策略与失败告警（M06-15~18）。"""
    try:
        actions = json.loads(flow.actions or "[]")
    except json.JSONDecodeError:
        actions = []

    run = FlowRun(flow_id=flow.id, trigger=trigger)
    session.add(run)
    await session.commit()

    variables: dict = {"vars": {}, "prev": {}, **(extra_vars or {})}
    steps_log: list[dict] = []
    status = "success"
    started = time.perf_counter()
    try:
        for step in actions:
            attempts = (flow.retry or 0) + 1 if not dry_run else 1
            last_log: dict | None = None
            for attempt in range(attempts):
                if step.get("type") == "condition":
                    log = await _execute_step(session, step, variables, dry_run)
                    if log.get("result") is False:
                        variables["_skip"] = True  # 条件不满足 → 跳过后续动作（M06-8）
                    last_log = log
                    break
                try:
                    last_log = await _execute_step(session, step, variables, dry_run)
                    if "error" not in last_log:
                        break
                except httpx.HTTPError:
                    last_log = last_log or {"error": "http failed"}
                if attempt < attempts - 1 and not dry_run:
                    log_with_attempt = dict(last_log or {})
                    log_with_attempt["attempt"] = attempt + 1
                    steps_log.append(log_with_attempt)
                    await asyncio.sleep(min(flow.retry_interval or 60, 10))
                    last_log = None
            if last_log is not None:
                steps_log.append(last_log)
            if last_log is not None and "error" in last_log:
                status = "failed"
                break
    except Exception as exc:  # noqa: BLE001 —— 引擎兜底，失败也要落 runs
        steps_log.append({"error": str(exc)[:200]})
        status = "failed"

    if dry_run:
        # dry-run 不落库副作用（M06-15）
        run_obj = FlowRun(
            flow_id=flow.id, trigger=trigger, status="success" if status == "success" else "failed",
            steps_log=json.dumps(steps_log, ensure_ascii=False, default=str),
            started_at=datetime.utcnow(), finished_at=datetime.utcnow(),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        session.add(run_obj)
        await session.commit()
        return run_obj

    run.status = status
    run.steps_log = json.dumps(steps_log, ensure_ascii=False, default=str)
    run.finished_at = datetime.utcnow()
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    flow.last_run_at = run.finished_at
    await session.commit()
    if status == "failed":
        await notify.dispatch(
            session,
            event="flow_failed",
            source="flow",
            title=f"Flow「{flow.name}」执行失败",
            body=trigger,
            level="warn",
            dedup_key=f"flow-fail-{flow.id}-{int(time.time() // 300)}",
        )

    return run


# ---------- 事件触发（M06-7；经 notify.dispatch 钩子） ----------


async def trigger_event_flows(session: AsyncSession, event: str, payload: dict) -> None:
    """事件触发器：event 匹配且启用的 Flow 逐个执行（system 事件不触发，防自激）。"""
    if event in EVENT_HOOK_IGNORED:
        return
    flows = (
        await session.execute(
            select(Flow).where(
                Flow.enabled.is_(True),
                Flow.trigger_type == "event",
            )
        )
    ).scalars().all()
    for flow in flows:
        try:
            cfg = json.loads(flow.trigger_config or "{}")
        except json.JSONDecodeError:
            continue
        if cfg.get("event") != event:
            continue
        await execute_flow(session, flow, "event")


# ---------- cron 触发器调度（M06-4） ----------


def sync_cron_job(scheduler, flow: Flow) -> None:
    """按 Flow 当前状态注册/移除 cron job（CRUD 与启动恢复时调用）。"""
    job_id = f"flow-cron-{flow.id}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    if flow.enabled and flow.trigger_type == "cron":
        from apscheduler.triggers.cron import CronTrigger

        try:
            cfg = json.loads(flow.trigger_config or "{}")
            trigger = CronTrigger.from_crontab(cfg.get("cron", ""))
        except (json.JSONDecodeError, ValueError):
            return  # 非法 cron 表达式不注册（保存时已校验格式）
        scheduler.add_job(
            _cron_tick, trigger, id=job_id, args=[flow.id],
            max_instances=1, replace_existing=True,
        )


async def _cron_tick(flow_id: int) -> None:
    from app.core.scheduler import scheduler as _  # noqa: F401 确保调度器已导入
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        flow = await session.get(Flow, flow_id)
        if flow is not None and flow.enabled:
            await execute_flow(session, flow, "cron")


async def restore_cron_jobs(scheduler) -> None:
    """启动时恢复全部启用中的 cron Flow（lifespan 内 await）。"""
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        flows = (
            await session.execute(
                select(Flow).where(Flow.enabled.is_(True), Flow.trigger_type == "cron")
            )
        ).scalars().all()
        for flow in flows:
            sync_cron_job(scheduler, flow)
