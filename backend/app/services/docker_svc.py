"""Docker 容器管理服务（M08-1~4；dev-plan P12；api-spec §4.6）。

可选模块：settings.docker_sock_enabled（env DOCKER_SOCK_ENABLED）开关，
默认关闭；关闭或 sock 不可达时 API 返回 503，前端模块隐藏（P12 退出标准：
未挂载 sock 时系统零报错）。
- 封装 httpx UDS 调 Docker Engine API；transport 可注入（单测 MockTransport）；
- 敏感环境变量脱敏（M08-4）：KEY 命中 token/secret/pass/key/pwd 的值打码。
"""

from __future__ import annotations

import httpx

from app.core.config import settings

_SENSITIVE_HINTS = ("token", "secret", "pass", "pwd", "key", "credential")

_http_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _http_transport
    _http_transport = transport


def sock_path() -> str:
    import os

    return os.getenv("DOCKER_SOCK", "/var/run/docker.sock")


def enabled() -> bool:
    import os

    return bool(settings.docker_sock_enabled) and os.path.exists(sock_path())


class DockerDisabled(RuntimeError):
    """模块未启用或 sock 不可达。"""


def _client() -> httpx.AsyncClient:
    kwargs: dict = {"timeout": 10.0}
    if _http_transport is not None:
        kwargs["transport"] = _http_transport
    else:
        kwargs["transport"] = httpx.AsyncHTTPTransport(uds=sock_path())
    return httpx.AsyncClient(base_url="http://docker", **kwargs)


def mask_env(env: list[str]) -> list[str]:
    """环境变量脱敏：KEY 命中敏感词（token/secret/pass/pwd/key/credential）时值打码。"""
    out = []
    for item in env or []:
        k, _, v = item.partition("=")
        if any(h in k.lower() for h in _SENSITIVE_HINTS) and v:
            out.append(f"{k}=******")
        else:
            out.append(item)
    return out


async def list_containers() -> list[dict]:
    """容器列表（M08-1）：全部容器（含停止），运行中的附带 CPU/内存占用。"""
    if not enabled():
        raise DockerDisabled()
    async with _client() as c:
        resp = await c.get("/containers/json?all=1")
        resp.raise_for_status()
        containers = resp.json()
        result = []
        for item in containers[:50]:
            cid = item.get("Id", "")
            entry = {
                "id": cid[:12],
                "name": (item.get("Names") or [""])[0].lstrip("/"),
                "image": item.get("Image", ""),
                "state": item.get("State", ""),
                "status": item.get("Status", ""),
            }
            if entry["state"] == "running":
                try:
                    stats = (await c.get(f"/containers/{cid}/stats?stream=false")).json()
                    cpu = stats.get("cpu_stats", {})
                    pre = stats.get("precpu_stats", {})
                    cpu_d = cpu.get("cpu_usage", {}).get("total_usage", 0) - pre.get(
                        "cpu_usage", {}
                    ).get("total_usage", 0)
                    sys_d = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
                    online = cpu.get("online_cpus") or 1
                    mem = stats.get("memory_stats", {})
                    used, limit = mem.get("usage", 0), mem.get("limit", 0)
                    entry["cpu_percent"] = (
                        round(cpu_d / sys_d * online * 100, 1) if sys_d > 0 and cpu_d > 0 else 0.0
                    )
                    entry["mem_used_mb"] = round(used / 1048576, 1)
                    entry["mem_percent"] = round(used / limit * 100, 1) if limit else 0.0
                except Exception:
                    pass
            result.append(entry)
        # 运行中排前（M08-1）
        result.sort(key=lambda x: (x["state"] != "running", x["name"]))
        return result


async def container_op(name: str, op: str) -> dict:
    """生命周期操作（M08-2）：start/stop/restart。"""
    if not enabled():
        raise DockerDisabled()
    if op not in ("start", "stop", "restart"):
        raise ValueError(f"unsupported op: {op}")
    async with _client() as c:
        resp = await c.post(f"/containers/{name}/{op}")
        if resp.status_code == 404:
            raise KeyError(name)
        resp.raise_for_status()
        return {"ok": True, "op": op, "name": name}


async def container_logs(name: str, tail: int = 200) -> str:
    """尾部日志（M08-3）：stdout+stderr 纯文本。"""
    if not enabled():
        raise DockerDisabled()
    async with _client() as c:
        resp = await c.get(
            f"/containers/{name}/logs",
            params={"tail": min(max(tail, 1), 1000), "stdout": "true", "stderr": "true"},
        )
        if resp.status_code == 404:
            raise KeyError(name)
        resp.raise_for_status()
        text = resp.text
    # Engine API 多路复用帧前缀（8 字节头）在非 tty 容器上会出现；尽力清洗
    lines = []
    for line in text.splitlines():
        mux = len(line) > 8 and line[:8].startswith("\x01\x00\x00\x00")
        lines.append(line[8:] if mux else line)
    return "\n".join(lines)


async def container_detail(name: str) -> dict:
    """容器详情（M08-4）：端口映射/卷挂载/环境变量（脱敏）。"""
    if not enabled():
        raise DockerDisabled()
    async with _client() as c:
        resp = await c.get(f"/containers/{name}/json")
        if resp.status_code == 404:
            raise KeyError(name)
        resp.raise_for_status()
        info = resp.json()
    ports = []
    for key, bindings in (info.get("NetworkSettings", {}).get("Ports") or {}).items():
        for b in bindings or []:
            ports.append(
                {
                    "container": key,
                    "host_ip": b.get("HostIp", ""),
                    "host_port": b.get("HostPort", ""),
                }
            )
    mounts = [
        {
            "source": m.get("Source", ""),
            "destination": m.get("Destination", ""),
            "mode": m.get("Mode", ""),
        }
        for m in info.get("Mounts", [])
    ]
    return {
        "id": info.get("Id", "")[:12],
        "name": (info.get("Name") or "").lstrip("/"),
        "image": info.get("Config", {}).get("Image", ""),
        "state": info.get("State", {}).get("Status", ""),
        "ports": ports,
        "mounts": mounts,
        "env": mask_env(info.get("Config", {}).get("Env") or []),
    }
