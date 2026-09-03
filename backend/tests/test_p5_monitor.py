"""P5 测试关卡：服务器性能监控（采集结构 / 速率计算 / 聚合 / 清理 / 接口权限）。

覆盖 dev-plan P5 单测关卡：采样数据结构与单位换算；清理任务只删过期；
历史聚合空区间/超长区间边界。聚合与清理用独立内存库跑，避免与
TestClient lifespan 启动的采样定时器相互干扰。
"""

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models.monitor import MonitorSample
from app.services.monitor import (
    NetRateCalculator,
    _bucket_avg,
    build_history,
    cleanup_expired,
    collect_cpu,
    collect_mem,
    collect_temps,
    read_int_setting,
    sample_once,
    should_sample,
)

ADMIN_USER = "admin"
ADMIN_PASS = "portal-p2"
ALICE_USER = "alice"
ALICE_PASS = "alice12345"

_tokens: dict = {}


def _reset_db_state() -> None:
    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ADMIN_USER,)).fetchone():
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (hash_password(ADMIN_PASS), ADMIN_USER),
            )
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES (?, ?, 'admin', 1, '{}', 0)",
                (ADMIN_USER, hash_password(ADMIN_PASS)),
            )
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ALICE_USER,)).fetchone() is None:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES (?, ?, 'user', 1, '{}', 0)",
                (ALICE_USER, hash_password(ALICE_PASS)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _setup(client: TestClient):
    _reset_db_state()
    _tokens.clear()


def _admin(client: TestClient) -> dict:
    if "admin" not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens["admin"] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens['admin']}"}


def _alice(client: TestClient) -> dict:
    if "alice" not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ALICE_USER, "password": ALICE_PASS})
        assert resp.status_code == 200, resp.text
        _tokens["alice"] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens['alice']}"}


# ============ 采集服务（M17-1~5；P5.1）============


def test_01_overview_shape_and_units(client: TestClient):
    """实时概览结构完整、取值范围合理（单位：字节/百分比/秒）。"""
    data = client.get("/api/monitor/system", headers=_admin(client)).json()["data"]
    assert set(data) >= {"ts", "system", "cpu", "mem", "disks", "nets"}
    assert data["ts"].endswith("Z")
    assert set(data["system"]) >= {"hostname", "os", "kernel", "arch", "uptime"}
    assert data["system"]["uptime"] >= 0
    assert 0 <= data["cpu"]["percent"] <= 100
    assert isinstance(data["cpu"]["per_core"], list) and data["cpu"]["per_core"]
    assert len(data["cpu"]["load"]) == 3
    assert data["mem"]["total"] > 0 and data["mem"]["used"] <= data["mem"]["total"]
    assert 0 <= data["mem"]["percent"] <= 100
    assert data["disks"], "至少应有一个分区"
    for d in data["disks"]:
        assert set(d) >= {"mount", "total", "used", "percent", "inode_p"}
        assert d["total"] > 0 and 0 <= d["percent"] <= 100
    for n in data["nets"]:
        assert set(n) >= {
            "iface", "rx_rate", "tx_rate", "rx_total", "tx_total", "rx_today", "tx_today"
        }
        assert n["rx_rate"] >= 0 and n["tx_today"] >= 0


def test_02_collect_primitives():
    """采集原语：cpu/mem 结构（psutil 真实数据）。"""
    cpu = collect_cpu()
    assert cpu["cores"] >= 1 and len(cpu["per_core"]) == cpu["cores"]
    mem = collect_mem()
    assert mem["available"] <= mem["total"]
    assert mem["swap_total"] >= mem["swap_used"] >= 0


# ============ 网卡速率与当日流量（M17-5）============


def test_03_net_rate_and_day_baseline():
    """速率 = 计数差/时长；回绕按 0；跨日基线重置当日流量。"""
    calc = NetRateCalculator()
    t0 = time.mktime(time.strptime("2026-09-02 23:59:50", "%Y-%m-%d %H:%M:%S"))
    # 首帧：无速率，当日基线=当前值（当日流量 0）
    rows = calc.feed({"eth0": (1000, 2000)}, ts=t0)
    assert rows[0]["rx_rate"] == 0 and rows[0]["rx_today"] == 0
    # 5s 内收了 500 字节 → 100 B/s（仍在 09-02）
    rows = calc.feed({"eth0": (1500, 2000)}, ts=t0 + 5)
    assert rows[0]["rx_rate"] == 100.0 and rows[0]["tx_rate"] == 0.0
    assert rows[0]["rx_today"] == 500
    # 跨日（00:00:05）：基线取昨日最后快照（1500），当日 = 2500-1500
    rows = calc.feed({"eth0": (2500, 2000)}, ts=t0 + 15)
    assert rows[0]["rx_today"] == 1000
    assert rows[0]["rx_rate"] == 100.0  # (2500-1500)/10s
    # 计数回绕（重启）：负增量钳 0
    rows = calc.feed({"eth0": (10, 5)}, ts=t0 + 20)
    assert rows[0]["rx_rate"] == 0.0 and rows[0]["rx_today"] == 0


def test_04_net_rate_second_iface():
    """中途新增网卡不参与上一窗口速率，也不影响其他网卡。"""
    calc = NetRateCalculator()
    t0 = 1_000_000.0
    calc.feed({"eth0": (100, 100)}, ts=t0)
    rows = calc.feed({"eth0": (300, 150), "wlan0": (10, 5)}, ts=t0 + 20)
    by = {r["iface"]: r for r in rows}
    assert by["eth0"]["rx_rate"] == 10.0
    assert by["wlan0"]["rx_rate"] == 0.0  # 新网卡首帧无速率
    assert by["wlan0"]["rx_today"] == 0  # 首见基线=当前值，当日流量从 0 起算
    rows = calc.feed({"eth0": (400, 150), "wlan0": (60, 5)}, ts=t0 + 30)
    by = {r["iface"]: r for r in rows}
    assert by["wlan0"]["rx_rate"] == 5.0 and by["wlan0"]["rx_today"] == 50


def test_04b_net_rate_short_interval_keeps_last():
    """间隔过短的快照不重算速率（沿用上一窗口），避免除以极小间隔产生尖峰。"""
    calc = NetRateCalculator()
    t0 = 1_000_000.0
    calc.feed({"eth0": (100, 100)}, ts=t0)
    rows = calc.feed({"eth0": (2100, 100)}, ts=t0 + 10)  # 200 B/s
    assert rows[0]["rx_rate"] == 200.0
    # 0.2s 后又一帧（如 HTTP 与 WS 两路交替）：沿用 200 而不是 400/0.2
    rows = calc.feed({"eth0": (2500, 100)}, ts=t0 + 10.2)
    assert rows[0]["rx_rate"] == 200.0


# ============ 历史聚合（M17-6；P5.4）============


def _row(cpu, mem_used, nets, disks, minutes_ago, cores=None, temps=None):
    return MonitorSample(
        ts=datetime.utcnow() - timedelta(minutes=minutes_ago),
        cpu=cpu,
        cpu_cores=json.dumps(cores) if cores else None,
        mem=json.dumps({"total": 1000, "used": mem_used}),
        nets=json.dumps(nets),
        disks=json.dumps(disks),
        temps=json.dumps(temps) if temps else None,
    )


def test_05_bucket_avg_merges_and_picks_last_ts():
    """桶平均：同桶多点取均值，ts 取桶内最后一行。"""
    rows = [
        _row(10.0, 100, [], [], 25),
        _row(30.0, 300, [], [], 15),
        _row(20.0, 200, [], [], 5),
    ]
    points = _bucket_avg(rows, 20 * 60, lambda r: {"cpu": r.cpu})
    assert len(points) == 2
    assert points[0]["cpu"] == 20.0  # (10+30)/2
    assert points[0]["ts"] == rows[1].ts.isoformat() + "Z"  # 桶内最后一行
    assert points[1]["cpu"] == 20.0


def test_06_history_isolated_db():
    """独立内存库端到端：cpu/mem/net 原始粒度点值、disk 多挂载点共享对齐时间轴。"""

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(MonitorSample.metadata.create_all)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as s:
            s.add_all(
                [
                    _row(11.0, 200, [{"iface": "eth0", "rx_rate": 5, "tx_rate": 7}],
                         [{"mount": "/test", "percent": 40}], 30, cores=[10, 30]),
                    _row(22.0, 400, [{"iface": "eth0", "rx_rate": 9, "tx_rate": 11}],
                         [{"mount": "/test", "percent": 60},
                          {"mount": "/data", "percent": 80}], 10, cores=[20, 50]),
                ]
            )
            await s.commit()
            cpu = await build_history(s, "cpu", "24h")
            mem = await build_history(s, "mem", "24h")
            net = await build_history(s, "net", "24h")
            disk = await build_history(s, "disk", "24h")
            disk7 = await build_history(s, "disk", "7d")
            empty = await build_history(s, "cpu", "30d")
            long7 = await build_history(s, "cpu", "7d")
        await engine.dispose()
        return cpu, mem, net, disk, disk7, empty, long7

    cpu, mem, net, disk, disk7, empty, long7 = asyncio.run(_run())
    assert [p["cpu"] for p in cpu["points"]] == [11.0, 22.0]
    # 每核序列原样透传（原始粒度）；相邻桶各自透传本桶行
    assert cpu["points"][0]["cores"] == [10, 30]
    assert long7["points"][0]["cores"] == [10.0, 30.0]
    assert long7["points"][1]["cores"] == [20.0, 50.0]
    # 30d（1h 桶）：两行同桶，每核按位平均 -> [15, 40]
    assert empty["points"][0]["cores"] == [15.0, 40.0]
    assert mem["points"][0]["percent"] == 20.0 and mem["points"][1]["percent"] == 40.0
    assert net["points"][0] == {"ts": net["points"][0]["ts"], "rx": 5, "tx": 7}
    # disk：/data 只在末行出现，两挂载点序列必须等长且缺失补 null（x 轴对齐契约）
    by_mount = {m["mount"]: m["points"] for m in disk["mounts"]}
    assert set(by_mount) == {"/test", "/data"}
    assert [p["percent"] for p in by_mount["/test"]] == [40, 60]
    assert [p["percent"] for p in by_mount["/data"]] == [None, 80]
    assert [p["ts"] for p in by_mount["/test"]] == [p["ts"] for p in by_mount["/data"]]
    # 7d 桶模式（20min 桶，origin=首行）：两行恰落相邻两桶，各挂载点输出等长对齐序列
    d7 = {m["mount"]: m["points"] for m in disk7["mounts"]}
    assert len(d7["/test"]) == len(d7["/data"]) == 2
    assert [p["percent"] for p in d7["/test"]] == [40.0, 60.0]
    assert [p["percent"] for p in d7["/data"]] == [None, 80.0]
    assert [p["ts"] for p in d7["/test"]] == [p["ts"] for p in d7["/data"]]
    # 30d 区间走 1h 桶聚合：相距 20 分钟的两行合并为 1 个均值点
    assert empty["metric"] == "cpu" and len(empty["points"]) == 1
    assert empty["points"][0]["cpu"] == 16.5
    assert long7["range"] == "7d" and long7["points"]


def test_07_cleanup_only_expired():
    """清理任务只删过期行（7 天保留）。"""

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(MonitorSample.metadata.create_all)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as s:
            s.add_all(
                [
                    MonitorSample(ts=datetime.utcnow() - timedelta(days=8), cpu=1.0),
                    MonitorSample(ts=datetime.utcnow() - timedelta(days=30), cpu=2.0),
                    MonitorSample(ts=datetime.utcnow() - timedelta(days=6), cpu=3.0),
                    MonitorSample(ts=datetime.utcnow(), cpu=4.0),
                ]
            )
            await s.commit()
            removed = await cleanup_expired(s, retention_days=7)
            remain = list((await s.execute(select(MonitorSample))).scalars())
        await engine.dispose()
        return removed, remain

    removed, remain = asyncio.run(_run())
    assert removed == 2
    assert sorted(r.cpu for r in remain) == [3.0, 4.0]


# ============ 接口契约与权限（P5.3/P5.4）============


def test_08_history_validation_and_permission(client: TestClient):
    assert client.get("/api/monitor/history").status_code == 401
    # 权限矩阵 §3：user 可查看基础资源图（监控接口权限 A）
    assert client.get("/api/monitor/history", headers=_alice(client)).status_code == 200
    assert client.get("/api/monitor/system", headers=_alice(client)).status_code == 200
    assert (
        client.get("/api/monitor/history?metric=bogus", headers=_admin(client)).status_code == 422
    )
    assert client.get("/api/monitor/history?range=2h", headers=_admin(client)).status_code == 422
    resp = client.get("/api/monitor/history?metric=cpu&range=24h", headers=_admin(client))
    assert resp.status_code == 200
    assert resp.json()["data"]["metric"] == "cpu"


def test_09_ws_requires_login_token(client: TestClient):
    """WS：无 token / 无效 token 拒绝（4401）；任意登录用户（含 user）可订阅。"""
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/monitor"):
            pass
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/monitor?token=invalid"):
            pass
    with client.websocket_connect(f"/ws/monitor?token={_tokens['alice']}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "monitor"
        assert "cpu" in msg["data"]
    with client.websocket_connect(f"/ws/monitor?token={_tokens['admin']}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "monitor"


# ============ 温度采集（M17-11）============


def test_10_collect_temps_shape():
    """温度采集返回列表；元素结构固定（本机无传感器时为空列表，同样合法）。"""
    temps = collect_temps()
    assert isinstance(temps, list)
    for t in temps:
        assert set(t) >= {"name", "current", "high", "critical"}


def test_11_history_temp_aligned(client: TestClient):
    """温度历史：按传感器名对齐共享时间轴，缺失补 null（与 disk 同契约）。"""

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(MonitorSample.metadata.create_all)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as s:
            s.add_all(
                [
                    _row(10.0, 100, [], [], 20,
                         temps=[{"name": "CPU", "current": 45.0, "high": 80, "critical": 95}]),
                    _row(20.0, 200, [], [], 5,
                         temps=[{"name": "CPU", "current": 52.0, "high": 80, "critical": 95},
                                {"name": "nvme", "current": 40.0, "high": 70, "critical": 85}]),
                ]
            )
            await s.commit()
            temp = await build_history(s, "temp", "24h")
        await engine.dispose()
        return temp

    temp = asyncio.run(_run())
    by_name = {s["name"]: s["points"] for s in temp["sensors"]}
    assert set(by_name) == {"CPU", "nvme"}
    assert [p["current"] for p in by_name["CPU"]] == [45.0, 52.0]
    assert [p["current"] for p in by_name["nvme"]] == [None, 40.0]  # 后出现的传感器首刻补 null
    assert [p["ts"] for p in by_name["CPU"]] == [p["ts"] for p in by_name["nvme"]]


def test_12_should_sample_and_int_setting():
    """采样间隔判断：无样本即采样；未达间隔跳过；非法设置回退默认。"""

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as s:
            first = await should_sample(s)  # 空库 → 采样
            await sample_once(s)
            just_sampled = await should_sample(s)  # 刚采过（默认间隔 60s）→ 跳过
            await s.merge(Setting(key="monitor.sample_interval", value=json.dumps(10)))
            await s.commit()
            after_cfg = await read_int_setting(s, "monitor.sample_interval", 60)
            await s.merge(Setting(key="monitor.sample_interval", value=json.dumps("bad")))
            await s.commit()
            fallback = await read_int_setting(s, "monitor.sample_interval", 60)
        await engine.dispose()
        return first, just_sampled, after_cfg, fallback

    from app.models import Base
    from app.models.setting import Setting

    first, just_sampled, after_cfg, fallback = asyncio.run(_run())
    assert first is True
    assert just_sampled is False
    assert after_cfg == 10
    assert fallback == 60


def test_13_hwmon_reader(tmp_path):
    """HOST_SYS hwmon 直读：毫度换算、label/max/crit 解析、缺省容错。"""
    from app.services.monitor import _read_hwmon

    chip = tmp_path / "class" / "hwmon" / "coretemp"
    chip.mkdir(parents=True)
    (chip / "temp1_input").write_text("45000")
    (chip / "temp1_label").write_text("Package id 0")
    (chip / "temp1_max").write_text("80000")
    (chip / "temp1_crit").write_text("95000")
    (chip / "temp2_input").write_text("41000")  # 无 label/阈值
    (chip / "tempBad_input").write_text("not-a-number")  # 非法值跳过
    (chip / "temp4_input").write_text("")  # 空文件跳过

    out = _read_hwmon(tmp_path / "class" / "hwmon")
    by_name = {t["name"]: t for t in out}
    assert set(by_name) == {"coretemp Package id 0", "coretemp temp2"}
    cpu = by_name["coretemp Package id 0"]
    assert cpu["current"] == 45.0 and cpu["high"] == 80.0 and cpu["critical"] == 95.0
    assert by_name["coretemp temp2"]["current"] == 41.0
    assert by_name["coretemp temp2"]["high"] is None


def test_14_read_int_setting_fallback(client):
    """read_int_setting：缺失/非法回退默认值（sample_interval 最小 10）。"""
    import asyncio
    import json

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.models import Base
    from app.models.setting import Setting
    from app.services.monitor import SAMPLE_INTERVAL_DEFAULT, read_int_setting

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as s:
            missing = await read_int_setting(s, "monitor.sample_interval", SAMPLE_INTERVAL_DEFAULT)
            await s.merge(Setting(key="monitor.sample_interval", value=json.dumps(15)))
            await s.commit()
            custom = await read_int_setting(s, "monitor.sample_interval", SAMPLE_INTERVAL_DEFAULT)
            await s.merge(Setting(key="monitor.sample_interval", value=json.dumps(5)))  # 低于下限
            await s.commit()
            too_low = await read_int_setting(
                s, "monitor.sample_interval", SAMPLE_INTERVAL_DEFAULT, minimum=10
            )
            n = len((await s.execute(select(Setting))).scalars().all())
        await engine.dispose()
        return missing, custom, too_low, n

    missing, custom, too_low, _ = asyncio.run(_run())
    assert missing == 60 and custom == 15 and too_low == 60
