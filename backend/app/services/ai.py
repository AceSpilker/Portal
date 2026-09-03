"""AI 助手服务（M05；dev-plan P13；api-spec §3.9/§4.8/§5）。

- Provider 配置存设置键 `ai.providers`（JSON 数组：name/base_url/api_key/model），
  key 回传掩码、保存时 ****** 保持原值（与 P9 渠道同构）；
- Prompt 组装：意图导航（应用清单注入 + navigate 协议）+ NAS 状态摘要（可开关）
  + 上下文轮数截断（M05-9/10/11）；
- parse_navigate：assistant 输出首行 `{"action":"navigate","app_id":N}` 协议解析，
  非法输出兜底返回 None（M05-10）；
- chat_frames：OpenAI 兼容 /chat/completions 流式拉取，产出 delta 帧（异步生成器）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx
import psutil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiMessage
from app.models.portal import App
from app.models.setting import Setting

log = logging.getLogger("portal.ai")

PROVIDERS_KEY = "ai.providers"
CONTEXT_ROUNDS_KEY = "ai.context_rounds"
CONTEXT_AWARE_KEY = "ai.context_aware"
ACTIVE_PROVIDER_KEY = "ai.active_provider_id"

NAVIGATE_PROTOCOL_HINT = (
    "当用户想打开某个门户应用时，仅输出一行 JSON："
    '{{"action":"navigate","app_id":<应用ID>}}，不要输出其他内容。'
)


async def _get_setting_json(session: AsyncSession, key: str, default):
    row = await session.get(Setting, key)
    if not row:
        return default
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return default


async def list_providers(session: AsyncSession, mask: bool = True) -> list[dict]:
    providers = await _get_setting_json(session, PROVIDERS_KEY, [])
    out = []
    for p in providers:
        item = dict(p)
        if mask and item.get("api_key"):
            item["api_key"] = "******"
        out.append(item)
    return out


async def save_providers(session: AsyncSession, providers: list[dict]) -> None:
    # ****** 保持原值
    existing = {p.get("id"): p for p in await _get_setting_json(session, PROVIDERS_KEY, [])}
    merged = []
    for p in providers:
        p = dict(p)
        if p.get("api_key") == "******" and p.get("id") in existing:
            p["api_key"] = existing[p["id"]].get("api_key", "")
        merged.append(p)
    row = await session.get(Setting, PROVIDERS_KEY)
    value = json.dumps(merged, ensure_ascii=False)
    if row is None:
        session.add(Setting(key=PROVIDERS_KEY, value=value))
    else:
        row.value = value
    await session.commit()


async def active_provider(session: AsyncSession) -> dict | None:
    providers = await _get_setting_json(session, PROVIDERS_KEY, [])
    active_id = await _get_setting_json(session, ACTIVE_PROVIDER_KEY, None)
    if not providers:
        return None
    if active_id is not None:
        for p in providers:
            if p.get("id") == active_id:
                return p
    return providers[0]


def mask_key(key: str) -> str:
    return "******" if key else ""


async def test_provider(base_url: str, api_key: str) -> dict:
    """连通性测试：GET {base}/models（OpenAI 兼容；Ollama 同路径）。"""
    base = (base_url or "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            resp = await c.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            )
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}", "models": []}
        data = resp.json()
        models = [m.get("id") for m in data.get("data", []) if m.get("id")]
        return {"ok": True, "models": models}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": str(exc)[:120], "models": []}


# ---------- Prompt 组装（单测关卡） ----------

NAV_PROMPT_TEMPLATE = (
    "你是 NAS 门户 Portal 的 AI 助手。"
    + NAVIGATE_PROTOCOL_HINT
    + "\n门户应用清单（id|名称|描述）:\n{app_list}"
)

CONTEXT_TEMPLATE = (
    "\n\n当前 NAS 状态摘要（供参考回答）:\n"
    "CPU {cpu:.0f}% / 内存 {mem:.0f}% / 磁盘峰值 {disk:.0f}% / 运行容器 {containers} 个"
)


def build_navigate_block(apps: list[App]) -> str:
    lines = [f"{a.id}|{a.name}|{(a.description or '').strip()[:40]}" for a in apps]
    return NAV_PROMPT_TEMPLATE.format(app_list="\n".join(lines) or "(无)")


def build_context_block(cpu: float, mem: float, disk: float, containers: int) -> str:
    return CONTEXT_TEMPLATE.format(cpu=cpu, mem=mem, disk=disk, containers=containers)


def build_system_prompt(
    apps: list[App], context_aware: bool, stats: dict | None = None
) -> str:
    prompt = build_navigate_block(apps)
    if context_aware and stats:
        prompt += build_context_block(
            stats.get("cpu", 0),
            stats.get("mem", 0),
            stats.get("disk", 0),
            stats.get("containers", 0),
        )
    return prompt


def trim_history(messages: list["AiMessage"], max_rounds: int) -> list[tuple[str, str]]:
    """上下文轮数截断（M05-9）：只保留最近 max_rounds 轮 user/assistant 对。"""
    pairs = [
        (m.role, m.content) for m in messages if m.role in ("user", "assistant")
    ]
    max_items = max(0, max_rounds) * 2
    return pairs[-max_items:] if max_items else []


# ---------- navigate 协议解析（M05-10；单测关卡） ----------


def parse_navigate(content: str) -> int | None:
    """识别首行 navigate 协议；格式错误/普通回答兜底 None。"""
    if not content:
        return None
    first = content.strip().splitlines()[0].strip()
    if not first.startswith("{"):
        return None
    try:
        data = json.loads(first)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("action") != "navigate":
        return None
    app_id = data.get("app_id")
    if not isinstance(app_id, int) or app_id <= 0:
        return None
    return app_id


# ---------- 流式对话（M05-6；WS /ws/ai-chat 消费） ----------


async def chat_frames(
    base_url: str, api_key: str, model: str, messages: list[dict]
):
    """OpenAI 兼容流式对话，逐段产出文本 delta（异步生成器）。"""
    base = (base_url or "").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"model": model, "messages": messages, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            async with c.stream(
                "POST", f"{base}/chat/completions", json=payload, headers=headers
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")[:200]
                    yield {"type": "error", "error": f"HTTP {resp.status_code}: {body}"}
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = (
                        data.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if delta:
                        yield {"type": "delta", "delta": delta}
    except httpx.HTTPError as exc:
        yield {"type": "error", "error": str(exc)[:160]}


def nas_stats_snapshot(session: AsyncSession) -> dict:
    """NAS 状态摘要（M05-11，尽力而为）。"""
    from app.services.monitor import collect_disks

    try:
        mem = psutil.virtual_memory()
        disks = collect_disks()
        disk_peak = max((d.get("percent", 0) for d in disks), default=0)
        return {
            "cpu": psutil.cpu_percent(interval=None),
            "mem": mem.percent,
            "disk": disk_peak,
            "containers": 0,
        }
    except Exception:
        return {"cpu": 0, "mem": 0, "disk": 0, "containers": 0}


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


async def load_history(session: AsyncSession, conversation_id: int) -> list[AiMessage]:
    return list(
        (
            await session.execute(
                select(AiMessage)
                .where(AiMessage.conversation_id == conversation_id)
                .order_by(AiMessage.id)
            )
        ).scalars()
    )
