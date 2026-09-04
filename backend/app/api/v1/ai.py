"""AI 助手接口（M05；dev-plan P13；api-spec §4.8）。

- Provider 配置 CRUD（M，key 掩码回传/保存保持）+ 连接测试 + 模型列表；
- 会话管理（A，按 user_id 隔离）；
- AI 生成应用草稿（A，返回结构化草稿，前端人工确认入库）；
- 流式对话走 WS /ws/ai-chat（见 main.py；加密中间件豁免面与 /ws/* 同构）。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, BizError, ok
from app.db.session import get_session
from app.models.ai import AiConversation, AiMessage
from app.models.portal import App
from app.models.user import User
from app.services import ai

log = logging.getLogger("portal.ai")

router = APIRouter()


# ---------- Provider（M） ----------


class ProviderIn(BaseModel):
    id: int | None = None
    name: str
    base_url: str
    api_key: str = ""
    model: str = ""
    enabled: bool = True


def _provider_id(providers: list[dict]) -> int:
    return max((p.get("id", 0) for p in providers), default=0) + 1


@router.get("/ai/providers")
async def providers_list(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return ok(await ai.list_providers(session))


@router.post("/ai/providers")
async def providers_add(
    body: ProviderIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    providers = await ai.list_providers(session, mask=False)
    p = body.model_dump()
    p["id"] = _provider_id(providers)
    providers.append(p)
    await ai.save_providers(session, providers)
    masked = dict(p)
    masked["api_key"] = ai.mask_key(p.get("api_key", ""))
    return ok(masked)


@router.put("/ai/providers/{provider_id}")
async def providers_update(
    provider_id: int,
    body: ProviderIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    providers = await ai.list_providers(session, mask=False)
    for i, p in enumerate(providers):
        if p.get("id") == provider_id:
            providers[i] = {**body.model_dump(), "id": provider_id}
            await ai.save_providers(session, providers)
            masked = dict(providers[i])
            masked["api_key"] = ai.mask_key(providers[i].get("api_key", ""))
            return ok(masked)
    raise BizError(CODE_NOT_FOUND, t("err.provider_not_found"), 404)


@router.delete("/ai/providers/{provider_id}")
async def providers_delete(
    provider_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    providers = await ai.list_providers(session, mask=False)
    left = [p for p in providers if p.get("id") != provider_id]
    if len(left) == len(providers):
        raise BizError(CODE_NOT_FOUND, t("err.provider_not_found"), 404)
    await ai.save_providers(session, left)
    return ok(True)


class ProviderTestIn(BaseModel):
    base_url: str
    api_key: str = ""


@router.post("/ai/providers/test")
async def providers_test(
    body: ProviderTestIn,
    _: User = Depends(require_admin),
):
    """连接测试 + 模型列表（M05-3）；api_key 为 ****** 时按已存 key 测试。"""
    key = "" if body.api_key == "******" else body.api_key
    return ok(await ai.test_provider(body.base_url, key))


class ProviderModelsIn(BaseModel):
    base_url: str
    api_key: str = ""


@router.post("/ai/providers/models")
async def providers_models(
    body: ProviderTestIn,
    _: User = Depends(require_admin),
):
    result = await ai.test_provider(body.base_url, body.api_key)
    return ok({"models": result.get("models", []), "ok": result.get("ok", False)})


# ---------- 会话（A，按用户隔离） ----------


@router.get("/ai/conversations")
async def conversations_list(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(AiConversation)
            .where(AiConversation.user_id == _.id)
            .order_by(AiConversation.id.desc())
        )
    ).scalars().all()
    return ok(
        [
            {
                "id": c.id,
                "title": c.title,
                "provider": c.provider,
                "created_at": c.created_at.isoformat() + "Z",
            }
            for c in rows
        ]
    )


class ConversationIn(BaseModel):
    title: str = "新对话"
    provider: str = ""


@router.post("/ai/conversations")
async def conversations_create(
    body: ConversationIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    c = AiConversation(user_id=user.id, title=body.title or "新对话", provider=body.provider)
    session.add(c)
    await session.commit()
    return ok({"id": c.id, "title": c.title, "provider": c.provider})


@router.get("/ai/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    c = await session.get(AiConversation, conversation_id)
    if c is None or c.user_id != user.id:
        raise BizError(CODE_NOT_FOUND, t("err.conversation_not_found"), 404)
    rows = await ai.load_history(session, conversation_id)
    return ok(
        [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() + "Z",
            }
            for m in rows
            if m.role in ("user", "assistant")
        ]
    )


@router.delete("/ai/conversations/{conversation_id}")
async def conversations_delete(
    conversation_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    c = await session.get(AiConversation, conversation_id)
    if c is None or c.user_id != user.id:
        raise BizError(CODE_NOT_FOUND, t("err.conversation_not_found"), 404)
    msgs = (
        await session.execute(select(AiMessage).where(AiMessage.conversation_id == conversation_id))
    ).scalars().all()
    for m in msgs:
        await session.delete(m)
    await session.delete(c)
    await session.commit()
    return ok(True)


@router.put("/ai/conversations/{conversation_id}")
async def conversations_rename(
    conversation_id: int,
    body: ConversationIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    c = await session.get(AiConversation, conversation_id)
    if c is None or c.user_id != user.id:
        raise BizError(CODE_NOT_FOUND, t("err.conversation_not_found"), 404)
    c.title = body.title or c.title
    await session.commit()
    return ok(True)


# ---------- AI 生成应用草稿（M05-13） ----------


class DraftIn(BaseModel):
    description: str = Field(min_length=5, max_length=2000)


DRAFT_PROMPT = (
    "根据下面的服务描述，输出一个 JSON 对象（只输出 JSON，不要其他文字）"
    '：{{"name":"应用名(≤20字)","description":"一句话描述(≤40字)",'
    '"health_type":"http|tcp|keyword|none","health_target":"探测目标(URL 或 host:port 或空)",'
    '"tags":["标签"]}}\n服务描述：\n{desc}'
)


def parse_draft(content: str) -> dict | None:
    """从模型输出提取 JSON 草稿（容忍 ```json 包裹）；非法返回 None。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("name"):
        return None
    return data


@router.post("/ai/generate/app-draft")
async def generate_app_draft(
    body: DraftIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    provider = await ai.active_provider(session)
    if provider is None:
        raise BizError(400, t("err.ai_no_provider"), 400)
    messages = [{"role": "user", "content": DRAFT_PROMPT.format(desc=body.description)}]
    parts: list[str] = []
    async for frame in ai.chat_frames(
        provider.get("base_url", ""),
        provider.get("api_key", ""),
        provider.get("model", ""),
        messages,
    ):
        if frame["type"] == "delta":
            parts.append(frame["delta"])
        else:
            raise BizError(502, t("err.ai_upstream") + frame.get("error", ""), 502)
    draft = parse_draft("".join(parts))
    if draft is None:
        raise BizError(502, t("err.ai_bad_draft"), 502)
    return ok(
        {
            "name": str(draft.get("name", ""))[:50],
            "description": str(draft.get("description", ""))[:100],
            "health_type": (
                draft.get("health_type")
                if draft.get("health_type") in ("http", "tcp", "keyword", "none")
                else "none"
            ),
            "health_target": str(draft.get("health_target", "") or ""),
            "tags": [str(x) for x in (draft.get("tags") or [])][:5],
        }
    )


# ---------- 流式对话（WS /ws/ai-chat；M05-6/10/11；P13.2/P13.3/P13.4） ----------


async def ai_chat_ws(websocket) -> None:
    """AI 流式对话 WS：query token 鉴权（豁免面同 /ws/*）。

    收帧：{"conversation_id": int, "content": str}（可省 content → 仅重放）；
    发帧：{"type":"delta","delta":…} / {"type":"done","content","navigate_app_id"}
        / {"type":"error","error"}。
    """
    from app.core.security import decode_token
    from app.db.session import SessionLocal

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

    async def send(frame: dict) -> bool:
        try:
            await websocket.send_json(frame)
            return True
        except Exception:
            return False

    try:
        while True:
            raw = await websocket.receive_json()
            conversation_id = int(raw.get("conversation_id") or 0)
            content = str(raw.get("content") or "").strip()
            if not conversation_id or not content:
                await send({"type": "error", "error": "conversation_id and content required"})
                continue

            async with SessionLocal() as session:
                conv = await session.get(AiConversation, conversation_id)
                if conv is None or conv.user_id != user.id:
                    await send({"type": "error", "error": "conversation not found"})
                    continue
                provider = await ai.active_provider(session)
                if provider is None:
                    await send({"type": "error", "error": t("err.ai_no_provider")})
                    continue
                rounds = await ai._get_setting_json(session, ai.CONTEXT_ROUNDS_KEY, 6)
                aware = await ai._get_setting_json(session, ai.CONTEXT_AWARE_KEY, False)

                # 落库用户消息
                session.add(AiMessage(conversation_id=conv.id, role="user", content=content))
                if conv.title == "新对话":
                    conv.title = content[:24]
                await session.commit()

                history = await ai.load_history(session, conv.id)
                pairs = ai.trim_history(history[:-1], rounds)
                apps_list = list(
                    (await session.execute(
                        select(App).where(App.deleted.is_(False), App.enabled.is_(True))
                    )).scalars()
                )
                stats = ai.nas_stats_snapshot(session) if aware else None
                system_prompt = ai.build_system_prompt(apps_list, aware, stats)
                messages = [{"role": "system", "content": system_prompt}]
                for role, text in pairs:
                    messages.append({"role": role, "content": text})
                messages.append({"role": "user", "content": content})

            full: list[str] = []
            async for frame in ai.chat_frames(
                provider.get("base_url", ""),
                provider.get("api_key", ""),
                provider.get("model", ""),
                messages,
            ):
                if frame["type"] == "delta":
                    full.append(frame["delta"])
                    if not await send(frame):
                        return
                else:
                    await send(frame)
                    return
            answer = "".join(full)
            nav_id = ai.parse_navigate(answer)
            async with SessionLocal() as session:
                session.add(AiMessage(conversation_id=conv.id, role="assistant", content=answer))
                await session.commit()
            await send({"type": "done", "content": answer, "navigate_app_id": nav_id})
    except Exception as exc:  # 连接异常退出
        log.debug("ai chat ws closed: %s", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/ai/usage")
async def ai_usage(
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """AI 用量统计（M05-15）：按日统计消息数与 token 数。"""
    from collections import defaultdict
    from datetime import datetime, timedelta

    rows = (
        (
            await session.execute(
                select(AiMessage)
                .where(AiMessage.role == "assistant")
                .order_by(AiMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    by_day: dict = defaultdict(lambda: {"messages": 0, "tokens": 0})
    cutoff = datetime.utcnow() - timedelta(days=days)
    for m in rows:
        if m.created_at < cutoff:
            continue
        day = m.created_at.strftime("%Y-%m-%d")
        by_day[day]["messages"] += 1
        by_day[day]["tokens"] += m.tokens or 0
    return ok({"days": [{"date": d, **v} for d, v in sorted(by_day.items())]})
