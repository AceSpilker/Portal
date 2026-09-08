"""法定节假日动态获取（077；用户需求：休几天/调休哪天须动态可见）。

数据源：NateScarlet/holiday-cn 开源数据集（国务院公告全年休班安排，
含调休上班日），按 CDN 优先级多源抓取；两级缓存——进程内存（1h）+
Setting 表年度持久化（离线时仍可读上次成功抓取，数据按年发布后基本不变）。
存储约定与全库一致：仍由前端显示层做 UTC/时区无关处理（date 为纯日期串）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting

_SOURCES = (
    "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://fastly.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://gcore.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
)
_MEM: dict[int, tuple[dict, datetime]] = {}
_MEM_TTL_S = 3600
_KEY_FMT = "calendar.holidays_{year}"

# 内置兜底（国务院公告休班安排；外源全挂时保证功能可用）。
# 结构：年份 → [(节日, 起始, 结束, [调休日])]
_BUILTIN_RANGES: dict[int, list[tuple[str, str, str, list[str]]]] = {
    2025: [
        ("元旦", "2025-01-01", "2025-01-01", []),
        ("春节", "2025-01-28", "2025-02-04", ["2025-01-26", "2025-02-08"]),
        ("清明节", "2025-04-04", "2025-04-06", []),
        ("劳动节", "2025-05-01", "2025-05-05", ["2025-04-27"]),
        ("端午节", "2025-05-31", "2025-06-02", []),
        ("国庆节", "2025-10-01", "2025-10-08", ["2025-09-28", "2025-10-11"]),  # 含中秋 10/6
    ],
    2026: [
        ("元旦", "2026-01-01", "2026-01-03", ["2026-01-04"]),
        ("春节", "2026-02-15", "2026-02-23", ["2026-02-14", "2026-02-28"]),
        ("清明节", "2026-04-04", "2026-04-06", []),
        ("劳动节", "2026-05-01", "2026-05-05", ["2026-05-09"]),
        ("端午节", "2026-06-19", "2026-06-21", []),
        ("中秋节", "2026-09-25", "2026-09-27", []),
        ("国庆节", "2026-10-01", "2026-10-07", ["2026-09-20", "2026-10-10"]),
    ],
}


def _builtin_days(year: int) -> dict | None:
    """由内置区间展开 days 列表（与外源数据同构，source 标注 builtin）。"""
    ranges = _BUILTIN_RANGES.get(year)
    if not ranges:
        return None
    days: list[dict] = []
    for name, start, end, makeup in ranges:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
        d = d0
        while d <= d1:
            days.append({"name": name, "date": d.isoformat(), "isOffDay": True})
            d += timedelta(days=1)
        for m in makeup:
            days.append({"name": name, "date": m, "isOffDay": False})
    days.sort(key=lambda x: x["date"])
    return {"year": year, "days": days, "source": "builtin"}


def summarize(days: list[dict]) -> list[dict]:
    """按节日名聚合：休息天数/起止区间 + 调休上班日期（纯函数，便于测试）。"""
    out: dict[str, dict] = {}
    for d in sorted(days, key=lambda x: x["date"]):
        info = out.setdefault(d["name"], {"rest": [], "makeup": []})
        (info["rest"] if d["isOffDay"] else info["makeup"]).append(d["date"])
    result = []
    for name, info in out.items():
        result.append(
            {
                "name": name,
                "rest_days": len(info["rest"]),
                "rest_ranges": _ranges(info["rest"]),
                "makeup_dates": info["makeup"],
            }
        )
    return sorted(result, key=lambda x: x["rest_ranges"][0]["start"] if x["rest_ranges"] else "")


def _ranges(dates: list[str]) -> list[dict]:
    if not dates:
        return []
    ds = sorted(date.fromisoformat(d) for d in dates)
    spans: list[dict] = []
    start = prev = ds[0]
    for d in ds[1:]:
        if (d - prev).days == 1:
            prev = d
            continue
        spans.append(
            {"start": start.isoformat(), "end": prev.isoformat(), "days": (prev - start).days + 1}
        )
        start = prev = d
    spans.append(
        {"start": start.isoformat(), "end": prev.isoformat(), "days": (prev - start).days + 1}
    )
    return spans


async def get_year(session: AsyncSession, year: int, force: bool = False) -> dict | None:
    """取某年度休班数据：内存 → DB → 外源抓取；全部失败返回 None。"""
    now = datetime.utcnow()
    hit = _MEM.get(year)
    if hit and not force and (now - hit[1]).total_seconds() < _MEM_TTL_S:
        return hit[0]
    key = _KEY_FMT.format(year=year)
    row = await session.get(Setting, key)
    if row and not force:
        try:
            data = json.loads(row.value)
            _MEM[year] = (data, now)
            return data
        except ValueError:
            pass
    data = await _fetch(year)
    if not data:
        # 外源全部不可达（内网/网络波动）：内置国务院公告数据兜底，保证功能可用
        data = _builtin_days(year)
    if data:
        await session.merge(Setting(key=key, value=json.dumps(data, ensure_ascii=False)))
        await session.commit()
        _MEM[year] = (data, now)
        return data
    return None


# 本机网络环境常见 IPv6 路由黑洞：httpx 先试 v6 会一直 ConnectTimeout（curl 因
# Happy Eyeballs 可用而掩盖问题）。强制 v4 源地址即可稳定访问（077 实测）。
_V4_TRANSPORT = httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=1)


async def _fetch_one(client: httpx.AsyncClient, src: str, year: int) -> dict | None:
    r = await client.get(src.format(year=year))
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("year") != year or not isinstance(data.get("days"), list):
        return None
    return {
        "year": year,
        "days": [
            {"name": d["name"], "date": d["date"], "isOffDay": bool(d["isOffDay"])}
            for d in data["days"]
        ],
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


async def _fetch(year: int) -> dict | None:
    """多源并发竞速：谁先成功用谁（串行最坏 4×超时会拖垮前端 15s 预算，077 实测）。"""
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(
                    _fetch_one(httpx.AsyncClient(timeout=8, transport=_V4_TRANSPORT), src, year)
                    for src in _SOURCES
                ),
                return_exceptions=True,
            ),
            timeout=10,
        )
    except (TimeoutError, asyncio.TimeoutError):
        return None
    for r in results:
        if isinstance(r, dict):
            return r
        # 单源异常（超时/解析失败）继续看其他源的结果
    return None
