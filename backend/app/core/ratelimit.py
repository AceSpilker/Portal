"""登录失败限速（M01-6）：同 IP 60 秒内失败 5 次即临时锁定。"""
import time

_WINDOW = 60.0
_MAX_FAILS = 5
_failed: dict[str, list[float]] = {}


def _prune(ip: str, now: float) -> list[float]:
    hits = [t for t in _failed.get(ip, []) if now - t < _WINDOW]
    if hits:
        _failed[ip] = hits
    else:
        _failed.pop(ip, None)
    return _failed.get(ip, [])


def is_locked(ip: str) -> bool:
    return len(_prune(ip, time.time())) >= _MAX_FAILS


def record_fail(ip: str) -> None:
    now = time.time()
    hits = _prune(ip, now)
    hits.append(now)
    _failed[ip] = hits


def record_success(ip: str) -> None:
    _failed.pop(ip, None)


def reset(ip: str) -> None:
    """测试辅助：清除指定 IP 的失败记录。"""
    _failed.pop(ip, None)
