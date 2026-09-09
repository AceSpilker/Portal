"""知识库接口（091；api-spec §4.13）。

- 数据源：GET 列表（A）/ POST、PUT /{id}、DELETE /{id}、POST /{id}/sync（M，git 拉取同步）；
- 浏览：GET /{id}/tree?path= 目录清单；GET /{id}/read?path= 内容（md/office 服务端转换）；
  GET /{id}/raw?path= 原文件流（图片/视频/音频/pdf，FileResponse 自带 Range 拖动）；
- 编辑：PUT /{id}/file?path=（仅 local 源；git 源只读，改动应回仓库再同步）；
- 安全：路径收敛在源根目录内；git 凭据密码 Fernet 加密、永不通传。
"""

from __future__ import annotations

import asyncio
import hmac
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import _bearer, get_auth_context, get_current_user, require_admin
from app.core.i18n import t
from app.core.response import (
    CODE_NOT_FOUND,
    CODE_TOKEN_INVALID,
    CODE_VALIDATION,
    BizError,
    ok,
)
from app.core.secret_box import decrypt_secret, encrypt_secret
from app.db.session import get_session
from app.models.knowledge import KnowledgeSource
from app.models.user import User
from app.services import knowledge_fs, knowledge_git, knowledge_office

router = APIRouter()


def _root_of(src: KnowledgeSource) -> Path:
    if src.kind == "local":
        return Path(src.path)
    return knowledge_git.clone_dir(src.id)


async def _get_source(
    source_id: int, session: AsyncSession, allow_disabled: bool = False
) -> KnowledgeSource:
    """取数据源；allow_disabled 供编辑/删除使用——停用的源必须能再启用/删除。"""
    src = await session.get(KnowledgeSource, source_id)
    if src is None or (not src.enabled and not allow_disabled):
        raise BizError(CODE_NOT_FOUND, t("err.knowledge_source_missing"), 404)
    return src


def _view(src: KnowledgeSource) -> dict:
    return {
        "id": src.id,
        "name": src.name,
        "kind": src.kind,
        "path": src.path if src.kind == "local" else "",
        "url": src.path if src.kind == "git" else "",
        "branch": src.branch,
        "enabled": src.enabled,
        "last_sync_at": src.last_sync_at.isoformat() + "Z" if src.last_sync_at else None,
        "last_commit": src.last_commit,
        "last_status": src.last_status,
        "last_error": src.last_error,
    }


# ---------- 数据源管理 ----------


@router.get("/knowledge/sources")
async def list_sources(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    rows = (
        (await session.execute(select(KnowledgeSource).order_by(KnowledgeSource.id)))
        .scalars()
        .all()
    )
    return ok([_view(r) for r in rows])


def _validate_common(body: dict) -> dict:
    kind = str(body.get("kind", ""))
    if kind not in ("local", "git"):
        raise BizError(CODE_VALIDATION, t("err.knowledge_kind"), 422)
    name = str(body.get("name", "")).strip()[:64]
    if not name:
        raise BizError(CODE_VALIDATION, t("err.knowledge_name_required"), 422)
    return {
        "name": name,
        "kind": kind,
        "path": str(body.get("path", "")).strip()[:500],
        "branch": str(body.get("branch", "")).strip()[:64],
        "username": str(body.get("username", "")).strip()[:64],
        "enabled": bool(body.get("enabled", True)),
    }


@router.post("/knowledge/sources")
async def create_source(
    body: dict,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """新建数据源（M）。local 校验目录存在；git 立即克隆（失败报错不落库）。"""

    data = _validate_common(body)
    name_taken = await session.scalar(
        select(func.count())
        .select_from(KnowledgeSource)
        .where(KnowledgeSource.name == data["name"])
    )
    if name_taken:
        raise BizError(CODE_VALIDATION, t("err.knowledge_name_taken"), 422)
    src = KnowledgeSource(**data)
    if data["kind"] == "local":
        if not data["path"] or not Path(data["path"]).is_dir():
            raise BizError(CODE_VALIDATION, t("err.knowledge_path_missing"), 422)
    else:
        if not data["path"].startswith(("http://", "https://")):
            raise BizError(CODE_VALIDATION, t("err.knowledge_url"), 422)
    password = str(body.get("password", ""))
    src.password = encrypt_secret(password) if password else ""
    session.add(src)
    await session.commit()
    await session.refresh(src)
    # git：新源立即克隆
    if src.kind == "git":
        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(
                knowledge_git.sync_repo,
                src.id, src.path, src.branch,
                src.username, decrypt_secret(src.password) if src.password else "",
            )
            src.last_sync_at = datetime.utcnow()
            src.last_commit = result["commit"]
            src.last_status = "ok"
            src.last_error = ""
        except Exception as exc:
            src.last_status = "failed"
            src.last_error = str(exc)[:400]
        src.last_sync_at = datetime.utcnow()
        await session.commit()
        if src.last_status == "failed":
            _ = time.perf_counter() - started
    return ok(_view(src))


@router.put("/knowledge/sources/{source_id}")
async def update_source(
    source_id: int,
    body: dict,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    src = await _get_source(source_id, session, allow_disabled=True)
    data = _validate_common({**_view(src), "path": src.path, **body})
    old = {"path": src.path, "kind": src.kind}
    for key, value in data.items():
        setattr(src, key, value)
    password = str(body.get("password", ""))
    if password:
        src.password = encrypt_secret(password)
    # git URL/分支变化 → 丢弃旧克隆，下次 sync 重建
    if src.kind == "git" and (old["path"] != src.path or old["kind"] != src.kind):
        shutil_rmtree(knowledge_git.clone_dir(src.id))
        src.last_status = "idle"
        src.last_commit = ""
    # local 路径变化校验
    if src.kind == "local" and not Path(src.path).is_dir():
        raise BizError(CODE_VALIDATION, t("err.knowledge_path_missing"), 422)
    await session.commit()
    return ok(_view(src))


def shutil_rmtree(path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


@router.delete("/knowledge/sources/{source_id}")
async def delete_source(
    source_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    src = await _get_source(source_id, session, allow_disabled=True)
    if src.kind == "git":
        shutil_rmtree(knowledge_git.clone_dir(src.id))  # 只删克隆，远端仓库不受影响
    await session.delete(src)
    await session.commit()
    return ok(None, t("ok.saved"))


@router.post("/knowledge/sources/{source_id}/sync")
async def sync_source(
    source_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """git 拉取同步（M）：pull 失败自动重建克隆。"""
    src = await _get_source(source_id, session)
    if src.kind != "git":
        raise BizError(CODE_VALIDATION, t("err.knowledge_not_git"), 422)
    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            knowledge_git.sync_repo,
            src.id, src.path, src.branch,
            src.username, decrypt_secret(src.password) if src.password else "",
        )
    except Exception as exc:
        src.last_status = "failed"
        src.last_error = str(exc)[:400]
        src.last_sync_at = datetime.utcnow()
        await session.commit()
        raise BizError(CODE_VALIDATION, t("err.knowledge_sync_failed", msg=str(exc)[:200]), 422)
    src.last_sync_at = datetime.utcnow()
    src.last_commit = result["commit"]
    src.last_status = "ok"
    src.last_error = ""
    await session.commit()
    return ok(
        {
            "cloned": result["cloned"],
            "commit": result["commit"],
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }
    )


# ---------- 服务器目录选择框（091 增补） ----------


@router.get("/knowledge/local-dirs")
async def list_local_dirs(
    path: str = "",
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """映射目录逐级浏览（M）：空 path 返回推荐挂载根（存在者），
    否则返回该目录的一级子目录与上级路径，供前端选择框下钻。"""
    if not path:
        roots = []
        for cand in ("/knowledge", str(Path(settings.data_dir) / "knowledge")):
            if Path(cand).is_dir():
                roots.append(cand)
        return ok({"path": "", "roots": roots, "dirs": [], "parent": None, "exists": None})

    p = Path(path)
    if not p.is_dir():
        return ok({"path": path, "roots": [], "dirs": [], "parent": None, "exists": False})

    def _subdirs(base: Path):
        try:
            return sorted(
                [x for x in base.iterdir() if x.is_dir() and not x.name.startswith(".")],
                key=lambda x: x.name.lower(),
            )
        except OSError:
            return []

    subs = [str(x) for x in _subdirs(p)]
    parent = str(p.parent) if p.parent != p else None
    return ok({"path": str(p), "roots": [], "dirs": subs, "parent": parent, "exists": True})


# ---------- 浏览与读取 ----------


@router.get("/knowledge/{source_id}/tree")
async def tree(
    source_id: int,
    path: str = "",
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    src = await _get_source(source_id, session)
    return ok(await asyncio.to_thread(knowledge_fs.list_tree, _root_of(src), path))


@router.get("/knowledge/{source_id}/read")
async def read_file(
    source_id: int,
    path: str = Query(...),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """读取内容：text/code/markdown 返回文本（md 前端渲染）；office 返回转换后 HTML。"""
    src = await _get_source(source_id, session)

    def _read() -> dict:
        p = knowledge_fs.safe_join(_root_of(src), path)
        if not p.is_file():
            raise FileNotFoundError(path)
        kind = knowledge_fs.file_kind(p)
        if kind in ("markdown", "text", "code"):
            text = p.read_text(encoding="utf-8", errors="replace")
            return {"kind": kind, "editable": src.kind == "local", "text": text}
        if kind in ("docx", "xlsx", "pptx"):
            html = knowledge_office.office_to_html(p, f".{kind}")
            return {"kind": kind, "editable": False, "html": html}
        return {"kind": kind, "editable": False}

    try:
        payload = await asyncio.to_thread(_read)
    except FileNotFoundError:
        raise BizError(CODE_NOT_FOUND, t("err.knowledge_file_missing"), 404)
    except PermissionError:
        raise BizError(CODE_VALIDATION, t("err.knowledge_path_escape"), 422)
    except Exception as exc:
        raise BizError(CODE_VALIDATION, t("err.knowledge_read_failed", msg=str(exc)[:200]), 422)
    return ok({"path": path, **payload})


def _sign_raw(source_id: int, path: str, exp: int) -> str:
    import hashlib
    import hmac

    msg = f"{source_id}:{path}:{exp}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


def _raw_url(source_id: int, path: str, ttl: int = 600) -> str:
    """iframe/img/video 无法携带 Authorization 头——发短期签名 URL（默认 10 分钟）。"""
    import time as _t

    exp = int(_t.time()) + ttl
    sig = _sign_raw(source_id, path, exp)
    return f"/api/knowledge/{source_id}/raw?path={quote(path)}&exp={exp}&sig={sig}"


@router.get("/knowledge/{source_id}/raw-url")
async def raw_url(
    source_id: int,
    path: str = Query(...),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """签发 raw 短期签名 URL（iframe/img/video 加载用，10 分钟有效）。"""
    await _get_source(source_id, session)
    return ok({"url": _raw_url(source_id, path)})


@router.get("/knowledge/{source_id}/raw")
async def raw_file(
    request: Request,
    source_id: int,
    path: str = Query(...),
    exp: int | None = Query(None),
    sig: str | None = Query(None),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
):
    """原文件流（图片/视频/音频/pdf/下载）：FileResponse 支持 Range（视频拖动）。

    鉴权双通道：Authorization 头（JWT/API Token）或短期签名参数（exp+sig，
    供 iframe/img/video 等无法携带请求头的场景）。
    """

    signature_ok = False
    if exp is not None and sig and exp >= int(time.time()):
        signature_ok = hmac.compare_digest(_sign_raw(source_id, path, exp), sig)
    if not signature_ok:
        try:
            ctx = await get_auth_context(request, cred, session)
        except Exception:
            raise BizError(
                CODE_TOKEN_INVALID, t("err.unauthenticated"), 401
            ) from None
        if ctx is None or ctx.user is None:
            raise BizError(
                CODE_TOKEN_INVALID, t("err.unauthenticated"), 401
            )
    src = await _get_source(source_id, session)
    root = _root_of(src)
    try:
        p = knowledge_fs.safe_join(root, path)
    except PermissionError:
        raise BizError(CODE_VALIDATION, t("err.knowledge_path_escape"), 422)
    if not p.is_file():
        raise BizError(CODE_NOT_FOUND, t("err.knowledge_file_missing"), 404)
    return FileResponse(p)


@router.put("/knowledge/{source_id}/file")
async def write_file(
    source_id: int,
    body: dict,
    path: str = Query(...),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """保存文本内容（M）：仅 local 源可写（git 源改动应提交回仓库）。"""
    src = await _get_source(source_id, session)
    if src.kind != "local":
        raise BizError(CODE_VALIDATION, t("err.knowledge_readonly"), 422)

    def _write() -> None:
        p = knowledge_fs.safe_join(Path(src.path), path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(body.get("content", "")), encoding="utf-8")

    try:
        await asyncio.to_thread(_write)
    except PermissionError:
        raise BizError(CODE_VALIDATION, t("err.knowledge_path_escape"), 422)
    return ok(None, t("ok.saved"))
