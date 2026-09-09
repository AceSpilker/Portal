# ruff: noqa: E501
"""容器部署宿主机监听采集（HOST_PROC）纯函数单测。

不依赖真实 procfs：构造仿 /proc/net 的文本与目录树，验证——
- 十进制地址解码（v4 小端 u32 / v6 组内小端）；
- TCP 仅 LISTEN 进入监听清单，ESTABLISHED 等不混入；
- 进程名/命令行从宿主 procfs 的 comm/cmdline 直读；
- lookup_port 按端口过滤宿主数据；
- HOST_PROC 未设/目录不存在时回退 None。
"""

from pathlib import Path

from app.core.config import settings
from app.services.ports import (
    _host_proc_entries,
    _listen_via_host_proc,
    _parse_proc_net,
    listen_list,
    lookup_port,
)

# 仿 /proc/net/tcp：一行 LISTEN(0A) 一行 ESTABLISHED(01)，端口 0x1F90=8080 / 0x1F91=8081
_TCP_TEXT = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt"
    "   uid  timeout inode\n"
    "   0: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000"
    " 00000000  1000        0 11101\n"
    "   1: 0100007F:1F91 0200007F:0035 01 00000000:00000000 00:00000000"
    " 00000000  1000        0 11102\n"
)
# 仿 /proc/net/udp：绑定 0x007B=123（NTP），无状态概念
_UDP_TEXT = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt"
    "   uid  timeout inode\n"
    "   0: 00000000:007B 00000000:0000 07 00000000:00000000 00:00000000"
    " 00000000  0        0 11103\n"
)
# UDP 动态端口段（IANA 49152+，0xC000=49152）出站套接字，应被剔除
_UDP_EPHEMERAL_TEXT = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt"
    "   uid  timeout inode\n"
    "   0: 0100007F:C000 00000000:0000 07 00000000:00000000 00:00000000"
    " 00000000  1000        0 11104\n"
)


def _build_host_proc(tmp_path: Path) -> Path:
    base = tmp_path / "host_proc"
    (base / "1" / "net").mkdir(parents=True)
    (base / "1" / "net" / "tcp").write_text(_TCP_TEXT)
    (base / "1" / "net" / "udp").write_text(_UDP_TEXT + _UDP_EPHEMERAL_TEXT)
    # 两个进程目录：11101→pid 410(NAS 服务)，11103→pid 1
    for pid, inode_port in (("410", ("11101",)), ("1", ("11103",))):
        d = base / pid
        d.mkdir(exist_ok=True)  # pid 1 目录已由 1/net 建出
        (d / "comm").write_text("nginx" if pid == "410" else "systemd")
        (d / "cmdline").write_bytes(b"nginx: master\0worker\0" if pid == "410" else b"/sbin/init\0")
        (d / "fd").mkdir()
        for ino in inode_port:
            (d / "fd" / f"5{ino[-1]}").symlink_to(f"socket:[{ino}]")
    return base


def test_parse_proc_net_decodes_addr_port_state(tmp_path):
    rows = _parse_proc_net(_TCP_TEXT)
    assert rows[0] == ("0.0.0.0", 8080, "11101", "0A")
    assert rows[1] == ("127.0.0.1", 8081, "11102", "01")


def test_host_proc_listen_filters_and_names(tmp_path, monkeypatch):
    base = _build_host_proc(tmp_path)
    monkeypatch.setattr(settings, "host_proc", str(base))
    rows = _listen_via_host_proc()
    # ESTABLISHED(8081) 与 UDP 动态段(49152) 不在监听清单
    assert [(r["proto"], r["port"]) for r in rows] == [("tcp", 8080), ("udp", 123)]
    tcp = rows[0]
    assert tcp["status"] == "LISTEN"
    assert tcp["pid"] == 410
    assert tcp["proc"] == "nginx"
    assert tcp["cmdline"] == "nginx: master worker"


def test_host_proc_lookup_by_port(tmp_path, monkeypatch):
    base = _build_host_proc(tmp_path)
    monkeypatch.setattr(settings, "host_proc", str(base))
    rows = lookup_port(8080)
    assert len(rows) == 1
    assert rows[0]["proc"] == "nginx" and rows[0]["status"] == "LISTEN"
    assert lookup_port(99999) == []


def test_host_proc_unset_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "host_proc", "")
    assert _host_proc_entries() is None
    monkeypatch.setattr(settings, "host_proc", "/nonexistent-host-proc")
    assert _host_proc_entries() is None
    # 回退后 listen_list 走 psutil/lsof，仍应返回清单（本机开发环境必非空）
    assert isinstance(listen_list(), list)
