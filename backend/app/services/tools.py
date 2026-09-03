"""工具箱后端服务（M10-1/3；dev-plan 7.3）：WoL 魔术包与 TCP 端口测试。"""

import re
import socket
import time

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-]?){5}([0-9A-Fa-f]{2})$")


def normalize_mac(mac: str) -> str:
    """MAC 规范化为 12 位十六进制大写（去分隔符）；非法抛 ValueError。"""
    raw = (mac or "").strip()
    if not _MAC_RE.match(raw):
        raise ValueError("invalid mac")
    return raw.replace(":", "").replace("-", "").upper()


def build_magic_packet(mac: str) -> bytes:
    """WoL 魔术包：6 字节 0xFF + 目标 MAC 重复 16 次（M10-1）。"""
    normalized = normalize_mac(mac)
    mac_bytes = bytes.fromhex(normalized)
    return b"\xff" * 6 + mac_bytes * 16


def send_wol(mac: str, port: int = 9, broadcast: str = "255.255.255.255") -> int:
    """广播魔术包（UDP），返回发送字节数。SO_BROADCAST 必须显式开启。"""
    packet = build_magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
    return len(packet)


def check_tcp_port(host: str, port: int, timeout: float = 3.0) -> dict:
    """TCP 端口连通测试（M10-3）：返回 {ok, latency_ms}。阻塞调用，需在线程池执行。"""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency = int((time.perf_counter() - start) * 1000)
            return {"ok": True, "latency_ms": latency}
    except OSError:
        return {"ok": False, "latency_ms": None}
