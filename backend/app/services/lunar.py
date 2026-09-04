"""农历换算与节日（M13-5；dev-plan P16.1）。

通行农历数据表（1900-2100，每年一个十六进制值：0x0F 位闰月、
0x10000 位闰月大小、高位为 1~12 月大小）。清明/冬至等节气不在此
实现（需节气表，非"固定农历日"），除夕按"次年正月初一的前一天"推算。
"""

from __future__ import annotations

from datetime import date, timedelta

# 1900-2100 农历信息表（通行实现）
_LUNAR_INFO = [
    0x04BD8, 0x04AE0, 0x0A570, 0x054D5, 0x0D260, 0x0D950, 0x16554, 0x056A0, 0x09AD0, 0x055D2,
    0x04AE0, 0x0A5B6, 0x0A4D0, 0x0D250, 0x1D255, 0x0B540, 0x0D6A0, 0x0ADA2, 0x095B0, 0x14977,
    0x04970, 0x0A4B0, 0x0B4B5, 0x06A50, 0x06D40, 0x1AB54, 0x02B60, 0x09570, 0x052F2, 0x04970,
    0x06566, 0x0D4A0, 0x0EA50, 0x06E95, 0x05AD0, 0x02B60, 0x186E3, 0x092E0, 0x1C8D7, 0x0C950,
    0x0D4A0, 0x1D8A6, 0x0B550, 0x056A0, 0x1A5B4, 0x025D0, 0x092D0, 0x0D2B2, 0x0A950, 0x0B557,
    0x06CA0, 0x0B550, 0x15355, 0x04DA0, 0x0A5B0, 0x14573, 0x052B0, 0x0A9A8, 0x0E950, 0x06AA0,
    0x0AEA6, 0x0AB50, 0x04B60, 0x0AAE4, 0x0A570, 0x05260, 0x0F263, 0x0D950, 0x05B57, 0x056A0,
    0x096D0, 0x04DD5, 0x04AD0, 0x0A4D0, 0x0D4D4, 0x0D250, 0x0D558, 0x0B540, 0x0B6A0, 0x195A6,
    0x095B0, 0x049B0, 0x0A974, 0x0A4B0, 0x0B27A, 0x06A50, 0x06D40, 0x0AF46, 0x0AB60, 0x09570,
    0x04AF5, 0x04970, 0x064B0, 0x074A3, 0x0EA50, 0x06B58, 0x05AC0, 0x0AB60, 0x096D5, 0x092E0,
    0x0C960, 0x0D954, 0x0D4A0, 0x0DA50, 0x07552, 0x056A0, 0x0ABB7, 0x025D0, 0x092D0, 0x0CAB5,
    0x0A950, 0x0B4A0, 0x0BAA4, 0x0AD50, 0x055D9, 0x04BA0, 0x0A5B0, 0x15176, 0x052B0, 0x0A930,
    0x07954, 0x06AA0, 0x0AD50, 0x05B52, 0x04B60, 0x0A6E6, 0x0A4E0, 0x0D260, 0x0EA65, 0x0D530,
    0x05AA0, 0x076A3, 0x096D0, 0x04AFB, 0x04AD0, 0x0A4D0, 0x1D0B6, 0x0D250, 0x0D520, 0x0DD45,
    0x0B5A0, 0x056D0, 0x055B2, 0x049B0, 0x0A577, 0x0A4B0, 0x0AA50, 0x1B255, 0x06D20, 0x0ADA0,
    0x14B63, 0x09370, 0x049F8, 0x04970, 0x064B0, 0x168A6, 0x0EA50, 0x06B20, 0x1A6C4, 0x0AAE0,
    0x0A2E0, 0x0D2E3, 0x0C960, 0x0D557, 0x0D4A0, 0x0DA50, 0x05D55, 0x056A0, 0x0A6D0, 0x055D4,
    0x052D0, 0x0A9B8, 0x0A950, 0x0B4A0, 0x0B6A6, 0x0AD50, 0x055A0, 0x0ABA4, 0x0A5B0, 0x052B0,
    0x0B273, 0x06930, 0x07337, 0x06AA0, 0x0AD50, 0x14B55, 0x04B60, 0x0A570, 0x054E4, 0x0D160,
    0x0E968, 0x0D520, 0x0DAA0, 0x16AA6, 0x056D0, 0x04AE0, 0x0A9D4, 0x0A2D0, 0x0D150, 0x0F252,
    0x0D520,
]

_EPOCH = date(1900, 1, 31)  # 1900 年正月初一

LUNAR_FESTIVALS: dict[tuple[int, int], str] = {
    (1, 1): "春节",
    (1, 15): "元宵节",
    (2, 2): "龙抬头",
    (5, 5): "端午节",
    (7, 7): "七夕",
    (7, 15): "中元节",
    (8, 15): "中秋节",
    (9, 9): "重阳节",
    (12, 8): "腊八节",
}


def _info(year: int) -> int:
    return _LUNAR_INFO[year - 1900]


def _leap_month(year: int) -> int:
    return _info(year) & 0x0F


def _leap_days(year: int) -> int:
    return 30 if (_info(year) & 0x10000) else 29


def _month_days(year: int, month: int) -> int:
    return 30 if (_info(year) & (0x10000 >> month)) else 29


def _year_days(year: int) -> int:
    total = sum(_month_days(year, m) for m in range(1, 13))
    leap = _leap_month(year)
    return total + (_leap_days(year) if leap else 0)


def solar_to_lunar(d: date) -> tuple[int, int, int, bool] | None:
    """公历 → 农历 (year, month, day, is_leap)；超出支持范围返回 None。

    闰月排在同号常规月之后（如 2025 闰六月在六月后）。
    """
    offset = (d - _EPOCH).days
    if offset < 0:
        return None
    year = 1900
    while year <= 2100:
        days = _year_days(year)
        if offset < days:
            break
        offset -= days
        year += 1
    else:
        return None
    leap_m = _leap_month(year)
    m, day = 1, offset + 1
    while m <= 12:
        md = _month_days(year, m)
        if day <= md:  # 常规月在前
            return (year, m, day, False)
        day -= md
        if leap_m == m:  # 随后是闰月
            ld = _leap_days(year)
            if day <= ld:
                return (year, m, day, True)
            day -= ld
        m += 1
    return None


def lunar_to_solar(year: int, month: int, day: int, leap: bool = False) -> date | None:
    """农历 → 公历；超出支持范围或日期非法返回 None。"""
    if year < 1900 or year > 2100 or not 1 <= month <= 12 or day < 1:
        return None
    leap_m = _leap_month(year)
    if leap and leap_m != month:  # 该年没有这个闰月
        return None
    offset = sum(_year_days(y) for y in range(1900, year))
    cur = day
    for m in range(1, month + 1):
        if m == month and not leap:
            if cur <= _month_days(year, m):
                return _EPOCH + timedelta(days=offset + cur - 1)
            return None
        offset += _month_days(year, m)  # 越过常规月
        if leap_m == m:  # 常规月之后是闰月
            if leap:  # 目标即此闰月
                if cur <= _leap_days(year):
                    return _EPOCH + timedelta(days=offset + cur - 1)
                return None
            offset += _leap_days(year)  # 非目标闰月：整月跳过
    return None


def festivals_for_year(year: int) -> list[dict]:
    """某公历年的农历节日（含除夕，按次年正月初一倒推一天）。"""
    out: list[dict] = []
    for (m, d), name in LUNAR_FESTIVALS.items():
        solar = lunar_to_solar(year, m, d)
        if solar is not None:
            out.append({"date": solar.isoformat(), "name": name})
    # 除夕 = 当年春节（公历年内的农历正月初一）的前一天
    cny = lunar_to_solar(year, 1, 1)
    if cny is not None:
        out.append({"date": (cny - timedelta(days=1)).isoformat(), "name": "除夕"})
    return sorted(out, key=lambda x: x["date"])
