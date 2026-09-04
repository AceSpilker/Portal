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

from app.db.session import SessionLocal
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


# ---------- 画布图（M06-3/11~14；dev-plan P19） ----------

# 画布节点类型：trigger=开始标记（无副作用）
NODE_TYPES = ("trigger", "condition", "http", "notify", "ssh", "docker", "ai", "delay", "variable")
MAX_NODES = 60
MAX_DEPTH = 100  # 分支展开深度上限（防环兜底，保存时已校验 DAG）
SSH_TIMEOUT = 30.0
DELAY_MAX_SEC = 300


def linear_to_graph(actions: list[dict]) -> dict:
    """表单线性动作 → 画布图（P19.1 互转）：trigger 起头依次串连。

    条件节点：true → 下一步；false → 终点（与线性引擎的 skip 语义等价）。
    """
    nodes: list[dict] = [{"id": "start", "type": "trigger", "name": "开始", "config": {}}]
    edges: list[dict] = []
    prev = "start"
    prev_is_condition = False
    for i, step in enumerate(actions):
        nid = f"n{i + 1}"
        clean = {k: v for k, v in step.items() if k in ("type", "name", "expression", "config")}
        nodes.append({"id": nid, **clean})
        edge = {"source": prev, "target": nid}
        if prev_is_condition:
            edge["source_handle"] = "true"  # 条件后续主路径 = true 分支
        edges.append(edge)
        prev = nid
        prev_is_condition = step.get("type") == "condition"
    return {"nodes": nodes, "edges": edges}


def graph_to_linear(graph: dict) -> list[dict]:
    """画布图 → 表单线性投影（P19.1 互转）：主路径投影（fan-out 取首边）。

    条件节点取 true 分支为后续主路径；start 触发节点不产生动作。
    """
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    out: list[dict] = []
    cur: str | None = next(
        (n["id"] for n in graph.get("nodes", []) if n.get("type") == "trigger"), None
    )
    if cur is None:  # 无触发节点：取无入边节点
        targets = {e["target"] for e in edges}
        cur = next((n["id"] for n in graph.get("nodes", []) if n["id"] not in targets), None)
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        node = nodes.get(cur)
        if node is None:
            break
        if node.get("type") != "trigger":
            step = {k: v for k, v in node.items() if k in ("type", "name", "expression", "config")}
            out.append(step)
        outs = [e for e in edges if e["source"] == cur]
        if node.get("type") == "condition":
            true_edge = next((e for e in outs if e.get("source_handle") == "true"), None)
            cur = (true_edge or outs[0])["target"] if outs else None
        else:
            cur = outs[0]["target"] if outs else None
    return out


def validate_graph(graph: dict) -> None:
    """保存前校验（P19.1）：节点类型/数量/DAG（无环）。"""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("graph 结构不正确")
    if len(nodes) > MAX_NODES:
        raise ValueError(f"节点数超过上限 {MAX_NODES}")
    ids = set()
    has_trigger = False
    for n in nodes:
        nid = str(n.get("id", ""))
        if not nid or nid in ids:
            raise ValueError("节点 id 缺失或重复")
        ids.add(nid)
        if n.get("type") not in NODE_TYPES:
            raise ValueError(f"未知节点类型: {n.get('type')}")
        if n.get("type") == "trigger":
            has_trigger = True
    for e in edges:
        if e.get("source") not in ids or e.get("target") not in ids:
            raise ValueError("连线引用了不存在的节点")
    if nodes and not has_trigger:
        raise ValueError("画布缺少开始节点")

    # DAG 检查（Kahn）
    indeg = {i: 0 for i in ids}
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        adj[e["source"]].append(e["target"])
        indeg[e["target"]] += 1
    queue = [i for i, d in indeg.items() if d == 0]
    visited = 0
    while queue:
        cur = queue.pop()
        visited += 1
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if visited != len(ids):
        raise ValueError("画布存在环（仅支持有向无环图）")


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


async def _run_ssh_action(cfg: dict, variables: dict) -> dict:
    """SSH 命令节点（M06-11；P19.2）：密码认证，输出截断 2KB。"""
    import asyncssh

    host = interpolate(str(cfg.get("host", "")), variables)
    if not host:
        raise ValueError("SSH host 未配置")
    port = int(cfg.get("port") or 22)
    username = interpolate(str(cfg.get("username", "")), variables) or "root"
    password = interpolate(str(cfg.get("password", "")), variables)
    command = interpolate(str(cfg.get("command", "")), variables)
    async with asyncssh.connect(
        host, port=port, username=username, password=password,
        known_hosts=None, login_timeout=10,
    ) as conn:
        result = await asyncio.wait_for(conn.run(command), timeout=SSH_TIMEOUT)
    output = (result.stdout or "")[:2048]
    ok = result.exit_status == 0
    out = {"exit_code": result.exit_status, "output": output, "ok": ok}
    if not ok:
        out["error"] = f"exit {result.exit_status}"
    return out


async def _run_docker_action(cfg: dict, variables: dict) -> dict:
    """Docker 操作节点（M06-12；P19.2）：start/stop/restart。"""
    from app.services import docker_svc

    container = interpolate(str(cfg.get("container", "")), variables)
    op = str(cfg.get("op", "restart"))
    if op not in ("start", "stop", "restart"):
        raise ValueError(f"不支持的容器操作: {op}")
    if not container:
        raise ValueError("容器名未配置")
    result = await docker_svc.container_op(container, op)
    return {"ok": True, "container": container, "op": op, "detail": result}


async def _run_ai_action(session, cfg: dict, variables: dict) -> dict:
    """AI 调用节点（M06-13；P19.2）：上游输出交给 AI 处理，结果传下游。"""
    import httpx as _httpx

    from app.services import ai as ai_svc

    prompt = interpolate(str(cfg.get("prompt", "")), variables)
    provider = await ai_svc.active_provider(session)
    if provider is None:
        raise ValueError("未配置 AI Provider")
    prev_text = _json_default(variables.get("prev", {}))
    messages = [
        {"role": "system", "content": str(cfg.get("system", "你是 NAS 助手，简洁回答。"))},
        {"role": "user", "content": f"{prompt}\n\n上游数据：{prev_text}"},
    ]
    base = (provider.get("base_url") or "").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    payload = {
        "model": provider.get("model", ""),
        "messages": messages,
        "max_tokens": int(cfg.get("max_tokens", 500)),
    }
    async with _httpx.AsyncClient(timeout=60.0) as c:
        resp = await c.post(f"{base}/chat/completions", json=payload, headers=headers)
    if resp.status_code >= 400:
        raise ValueError(f"AI HTTP {resp.status_code}: {resp.text[:160]}")
    text = (resp.json().get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
    return {"reply": str(text)[:2000]}


def _json_default(obj) -> str:
    try:
        import json as _json

        return _json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


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
    elif stype == "delay":
        cfg = step.get("config") or {}
        seconds = min(int(cfg.get("seconds", 0) or 0), DELAY_MAX_SEC)
        log["delay_seconds"] = seconds
        if dry_run:
            log["dry_run"] = True
            return log
        if seconds > 0:
            await asyncio.sleep(seconds)
        log["output"] = {"waited": seconds}
    elif stype == "variable":
        cfg = step.get("config") or {}
        name = str(cfg.get("name", "")).strip()
        if not name:
            log["error"] = "变量名未配置"
            return log
        value = interpolate(str(cfg.get("value", "")), variables)
        variables.setdefault("vars", {})[name] = value
        log["output"] = {"name": name, "value": value[:200]}
    elif stype == "ssh":
        cfg = step.get("config") or {}
        if dry_run:
            log["dry_run"] = True
            log["would_run"] = interpolate(str(cfg.get("command", "")), variables)[:200]
            return log
        try:
            result = await _run_ssh_action(cfg, variables)
            log["output"] = result
            variables["prev"] = result
            if "error" in result:
                log["error"] = result["error"]
        except Exception as exc:
            log["error"] = f"ssh failed: {str(exc)[:140]}"
            variables["prev"] = {"error": log["error"]}
            raise
    elif stype == "docker":
        cfg = step.get("config") or {}
        if dry_run:
            log["dry_run"] = True
            log["would_docker"] = f"{cfg.get('op', 'restart')} {cfg.get('container', '')}"
            return log
        try:
            result = await _run_docker_action(cfg, variables)
            log["output"] = result
            variables["prev"] = result
        except Exception as exc:
            log["error"] = str(exc)[:160]
            variables["prev"] = {"error": log["error"]}
            raise
    elif stype == "ai":
        cfg = step.get("config") or {}
        if dry_run:
            log["dry_run"] = True
            log["would_ask_ai"] = interpolate(str(cfg.get("prompt", "")), variables)[:200]
            return log
        try:
            result = await _run_ai_action(session, cfg, variables)
            log["output"] = result
            variables["prev"] = result
        except Exception as exc:
            log["error"] = str(exc)[:160]
            variables["prev"] = {"error": log["error"]}
            raise
    else:
        log["error"] = f"unknown action type: {stype}"
    return log


async def _execute_node(
    session: AsyncSession,
    flow: Flow,
    node: dict,
    variables: dict,
    dry_run: bool,
) -> dict:
    """画布单节点执行：条件/动作复用 _execute_step，带节点重试策略。

    动作节点异常（http/ssh/docker/ai 抛出）转为 error 日志参与重试；
    重试耗尽后返回最后日志（调用方按 error 标记支线失败）。
    """
    attempts = (flow.retry or 0) + 1 if not dry_run else 1
    last_log: dict = {}
    for attempt in range(attempts):
        try:
            log = await _execute_step(session, dict(node), variables, dry_run)
            last_log = log
        except Exception as exc:  # noqa: BLE001 —— 异常转错误日志走重试
            message = str(exc) or getattr(exc, "message", "") or type(exc).__name__
            last_log = {"error": message[:200], "attempt": attempt + 1}
        if "error" not in last_log:
            break
        if attempt < attempts - 1 and not dry_run:
            await asyncio.sleep(min(flow.retry_interval or 60, 10))
    return last_log


async def _walk_branch(
    session: AsyncSession,
    flow: Flow,
    graph: dict,
    start: str,
    variables: dict,
    dry_run: bool,
    steps_log: list,
    depth: int = 0,
) -> bool:
    """从 start 沿边深度优先执行一条支线；fan-out 并行展开（asyncio.gather）。

    条件节点按 source_handle（true/false）路由；分支失败停止该支线并返回 False。
    """
    if depth > MAX_DEPTH:
        steps_log.append({"error": "branch depth exceeded"})
        return False
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    cur: str | None = start
    while cur:
        node = nodes.get(cur)
        if node is None:
            return False
        ntype = node.get("type")
        if ntype == "trigger":
            pass  # 开始标记：无副作用
        else:
            log = await _execute_node(session, flow, node, variables, dry_run)
            log = {"node": cur, **log}
            steps_log.append(log)
            if "error" in log:
                return False
        outs = [e for e in edges if e["source"] == cur]
        if not outs:
            return True
        if ntype == "condition":
            # 条件独占路由：真走 true 边，假走 false 边；无边则支线成功终止
            handle = "true" if log.get("result") is True else "false"
            edge = next((e for e in outs if e.get("source_handle") == handle), None)
            if edge is None:
                return True
            return await _walk_branch(
                session, flow, graph, edge["target"], variables,
                dry_run, steps_log, depth + 1,
            )
        if len(outs) == 1:
            cur = outs[0]["target"]
            continue
        # fan-out：并行分支，变量副本 + 独立会话（SQLite 会话不可并发共享）
        import copy as _copy

        branch_vars = [_copy.deepcopy(variables) for _ in outs]
        results = await asyncio.gather(
            *(
                _walk_branch(
                    SessionLocal(), flow, graph, e["target"], branch_vars[i],
                    dry_run, steps_log, depth + 1,
                )
                for i, e in enumerate(outs)
            ),
            return_exceptions=True,
        )
        branch_failed = False
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                steps_log.append({"node": outs[i]["target"], "error": str(res)[:200]})
                branch_failed = True
            elif res is False:
                branch_failed = True
            else:
                # 分支产物合并回主线（vars 合并、prev 取最后一个完成分支）
                variables["vars"].update(branch_vars[i].get("vars", {}))
                variables["prev"] = branch_vars[i].get("prev", variables.get("prev"))
        if branch_failed:
            return False
        return True
    return True


async def execute_graph_flow(
    session: AsyncSession,
    flow: Flow,
    trigger: str,
    dry_run: bool = False,
    extra_vars: dict | None = None,
) -> FlowRun:
    """画布 Flow 执行（P19.1）：图遍历（条件路由/分支并行），失败告警同线性。"""
    graph = _json_loads(flow.graph or "{}")
    validate_graph(graph)
    run = FlowRun(flow_id=flow.id, trigger=trigger)
    session.add(run)
    await session.commit()

    variables: dict = {"vars": {}, "prev": {}, **(extra_vars or {})}
    steps_log: list[dict] = []
    started = time.perf_counter()
    status = "success"
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    targets = {e["target"] for e in edges}
    starts = [n["id"] for n in nodes if n["id"] not in targets]
    branch_failed = False
    try:
        for start in starts:
            ok = await _walk_branch(session, flow, graph, start, variables, dry_run, steps_log)
            if not ok:
                branch_failed = True
                break
    except Exception as exc:  # noqa: BLE001 —— 引擎兜底，失败也要落 runs
        steps_log.append({"error": str(exc)[:200]})
        branch_failed = True
    status = "failed" if branch_failed else "success"

    run.status = status
    run.steps_log = _json_default(steps_log)
    run.finished_at = datetime.utcnow()
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    if not dry_run:
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


def _json_loads(raw: str):
    import json as _json

    return _json.loads(raw)


async def execute_flow(
    session: AsyncSession,
    flow: Flow,
    trigger: str,
    dry_run: bool = False,
    extra_vars: dict | None = None,
) -> FlowRun:
    """执行 Flow：表单线性数组或画布图（P19.1），重试策略与失败告警（M06-15~18）。"""
    if flow.graph:
        try:
            probe = _json_loads(flow.graph)
            if probe.get("nodes"):
                return await execute_graph_flow(
                    session, flow, trigger, dry_run=dry_run, extra_vars=extra_vars
                )
        except ValueError as exc:
            if "环" in str(exc) or "节点" in str(exc):
                raise
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
