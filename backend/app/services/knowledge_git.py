"""知识库 Git 同步服务（091）：dulwich 纯 Python 实现（容器内免装 git）。

- clone/pull 均走 https（公库匿名；私库凭据拼 URL，密码 Fernet 密文存储）；
- 同步策略：先 pull（fast-forward），失败（断连/非快进/损坏）自动删除本地克隆重建；
- 克隆位置：{DATA_DIR}/knowledge/{source_id}/（数据卷持久化，容器重建不丢）。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.core.config import settings

# dulwich 走 urllib3/ssl 默认上下文：显式指到 certifi CA 束，
# 修复 macOS venv 等无系统 CA 环境的 CERTIFICATE_VERIFY_FAILED
try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:  # pragma: no cover
    pass


def clone_dir(source_id: int) -> Path:
    return Path(settings.data_dir) / "knowledge" / str(source_id)


def _authed_url(url: str, username: str, password: str) -> str:
    """https 私库凭据注入；无凭据原样返回。"""
    if not username or not password or not url.startswith("https://"):
        return url
    return url.replace("https://", f"https://{username}:{password}@", 1)


def head_commit(path: Path) -> str:
    """当前 HEAD 短哈希；非仓库返回空串。"""
    try:
        from dulwich.repo import Repo

        with Repo(path) as repo:
            return repo.head().decode()[:12]
    except Exception:
        return ""


def sync_repo(source_id: int, url: str, branch: str, username: str, password: str) -> dict:
    """克隆/拉取（同步阻塞，调用方放线程池）。返回 {cloned, commit}。"""
    from dulwich import porcelain

    target = clone_dir(source_id)
    authed = _authed_url(url, username, password)
    cloned = False
    if target.is_dir():
        try:
            with porcelain.open_repo_closing(str(target)) as repo:
                porcelain.pull(
                    repo,
                    authed,
                    refspecs=(f"refs/heads/{branch}",) if branch else None,
                    fast_forward=True,
                )
        except Exception:
            # 拉取失败（历史丢失/强推/网络中断）→ 重建克隆
            shutil.rmtree(target, ignore_errors=True)
    if not target.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        porcelain.clone(
            authed,
            str(target),
            branch=branch.encode() if branch else None,
            depth=1,
            checkout=True,
        )
        cloned = True
    return {"cloned": cloned, "commit": head_commit(target)}
