"""多机纳管 Agent 接口（M17-18/19；dev-plan P21.3；api-spec §4.4）。

- POST /api/monitor/agents/report：Agent 上报（token 鉴权，SHA-256 存储）；
- GET /api/monitor/agents：被纳管节点清单；
- POST /api/monitor/agents：注册节点 / 重置 token（明文仅此一次）；
- GET /api/monitor/agents/script：生成轻量上报脚本（psutil+httpx）；
- POST /api/monitor/snmp/test：SNMP v2c GET 探测（M17-19，纯标准库实现）。
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import socket
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.i18n import t
from app.core.response import CODE_VALIDATION, BizError, ok
from app.db.session import get_session
from app.models.agent import AgentNode
from app.models.setting import Setting
from app.models.user import User

router = APIRouter()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _agent_token(session: AsyncSession) -> str:
    row = await session.get(Setting, "monitor.agent_token")
    return row.value.strip('"') if row else ""


class ReportBody(BaseModel):
    token: str
    hostname: str = Field(max_length=120)
    cpu_pct: float = Field(ge=0, le=100)
    mem_pct: float = Field(ge=0, le=100)
    disk_pct: float = Field(ge=0, le=100)
    uptime_s: int = Field(default=0, ge=0)
    version: str = Field(default="", max_length=80)


@router.post("/monitor/agents/report")
async def agent_report(body: ReportBody, session: AsyncSession = Depends(get_session)):
    """Agent 指标上报（P21.3）：token 鉴权（免登录会话），upsert 最新快照。"""
    expected = await _agent_token(session)
    if not expected:
        raise BizError(CODE_VALIDATION, t("err.agents_disabled"), 403)
    if not secrets.compare_digest(_token_hash(body.token), _token_hash(expected)):
        raise BizError(CODE_VALIDATION, t("err.agents_bad_token"), 401)
    node = (
        await session.execute(
            select(AgentNode).where(AgentNode.hostname == body.hostname)
        )
    ).scalar_one_or_none()
    if node is None:
        node = AgentNode(hostname=body.hostname, token_hash=_token_hash(body.token))
        session.add(node)
    node.cpu_pct = body.cpu_pct
    node.mem_pct = body.mem_pct
    node.disk_pct = body.disk_pct
    node.uptime_s = body.uptime_s
    node.version = body.version[:80]
    node.last_seen_at = datetime.utcnow()
    await session.commit()
    return ok({"hostname": node.hostname}, t("ok.saved"))


@router.get("/monitor/agents")
async def list_agents(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """被纳管节点清单 + 最近上报（180s 内视为在线）。"""
    rows = (
        (await session.execute(select(AgentNode).order_by(AgentNode.hostname)))
        .scalars()
        .all()
    )
    now = datetime.utcnow()
    return ok(
        [
            {
                "hostname": n.hostname,
                "cpu_pct": n.cpu_pct,
                "mem_pct": n.mem_pct,
                "disk_pct": n.disk_pct,
                "uptime_s": n.uptime_s,
                "last_seen_at": n.last_seen_at.isoformat() + "Z",
                "online": (now - n.last_seen_at).total_seconds() < 180,
            }
            for n in rows
        ]
    )


class RegisterBody(BaseModel):
    hostname: str = Field(max_length=120)


@router.post("/monitor/agents")
async def register_agent(
    body: RegisterBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """注册节点：生成该节点的上报 token（明文仅此一次），写入 monitor.agent_token。"""
    token = secrets.token_urlsafe(24)
    node = (
        await session.execute(
            select(AgentNode).where(AgentNode.hostname == body.hostname)
        )
    ).scalar_one_or_none()
    if node is None:
        node = AgentNode(hostname=body.hostname, token_hash=_token_hash(token))
        session.add(node)
    else:
        node.token_hash = _token_hash(token)
    await session.merge(
        Setting(key="monitor.agent_token", value=_json_dumps(token))
    )
    await session.commit()
    return ok({"hostname": body.hostname, "token": token}, t("ok.saved"))


def _json_dumps(value) -> str:
    import json

    return json.dumps(value)


@router.get("/monitor/agents/script")
async def agent_script(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """生成轻量上报脚本（psutil+httpx），token 嵌入脚本内。"""
    import json as _json

    hostname = socket.gethostname()
    token = await _agent_token(session)
    script = AGENT_TEMPLATE.format(base="", token=token, hostname=_json.dumps(hostname))
    return ok({"hostname": hostname, "token": token, "script": script})


AGENT_TEMPLATE = '''"""Portal 轻量纳管 Agent：每 60s 上报本机 CPU/内存/磁盘。"""
import platform
import time
import psutil
import httpx

BASE = {base}
TOKEN = {token}
HOSTNAME = {hostname}


def collect():
    du = psutil.disk_usage("/")
    return {{
        "cpu_pct": psutil.cpu_percent(interval=1),
        "mem_pct": psutil.virtual_memory().percent,
        "disk_pct": du.percent,
        "uptime_s": int(time.time() - psutil.boot_time()),
        "version": platform.platform(),
    }}


def main():
    while True:
        m = collect()
        try:
            r = httpx.post(
                BASE + "/api/monitor/agents/report",
                json={{"token": TOKEN, "hostname": HOSTNAME, **m}},
                timeout=10,
            )
            print(r.status_code)
        except Exception as e:
            print("report failed:", e)
        time.sleep(60)


if __name__ == "__main__":
    main()
'''


class SnmpBody(BaseModel):
    host: str
    community: str = "public"
    oid: str = "1.3.6.1.2.1.1.1.0"


class _SnmpProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.future: asyncio.Future = asyncio.get_event_loop().create_future()

    def datagram_received(self, data, addr):
        if not self.future.done():
            self.future.set_result(data)

    def error_received(self, exc):
        if not self.future.done():
            self.future.set_exception(exc)


@router.post("/monitor/snmp/test")
async def snmp_test(
    body: SnmpBody, _: User = Depends(require_admin)
):
    """SNMP v2c GET 探测（M17-19）：UDP 单请求，2s 超时。"""
    from app.services.snmp import build_get, parse_response

    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _SnmpProtocol, remote_addr=(body.host, 161)
    )
    try:
        transport.sendto(build_get(body.oid, body.community))
        payload = await asyncio.wait_for(protocol.future, timeout=2.0)
    except (asyncio.TimeoutError, OSError) as exc:
        return ok({"ok": False, "error": str(exc)[:160]})
    finally:
        transport.close()
    err, oid, value = parse_response(payload)
    if err:
        return ok({"ok": False, "error": f"snmp error status {err}"})
    return ok({"ok": True, "oid": oid, "value": str(value)[:300]})
