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
from app.services import knowledge_fs, knowledge_git

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
        # 浏览根自动探测：/host/*（服务器目录透传，NAS 上把 /volume1 挂到 /host/volume1）、
        # /knowledge（推荐挂载点）、数据卷内 knowledge（git 克隆区）
        roots: list[dict] = []
        host = Path("/host")
        if host.is_dir():
            for child in sorted(host.iterdir(), key=lambda x: x.name):
                if child.is_dir() and not child.name.startswith("."):
                    roots.append({"path": str(child), "label": f"服务器 /{child.name}"})
        if Path("/knowledge").is_dir():
            roots.append({"path": "/knowledge", "label": "/knowledge（推荐挂载点）"})
        dk = Path(settings.data_dir) / "knowledge"
        if dk.is_dir():
            roots.append({"path": str(dk), "label": "数据卷 knowledge（git 克隆区）"})
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
    offset: int = Query(0, ge=0),
    chunk: int = Query(0, ge=0, le=4194304),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """读取内容：text/code/markdown 返回文本（md 前端渲染）；office 返回转换后 HTML。

    098 分片加载：带 offset+chunk 时只读指定字节段（文本按 UTF-8 解码，切片边界
    的残缺多字节字符以替换符兜底），响应附 size/has_more 供前端续传——大文件
    不再整文件传输。不带 offset 时保持整读（向后兼容）。
    """
    src = await _get_source(source_id, session)

    def _read() -> dict:
        p = knowledge_fs.safe_join(_root_of(src), path)
        if not p.is_file():
            raise FileNotFoundError(path)
        kind = knowledge_fs.file_kind(p)
        if kind in ("markdown", "text", "code"):
            size = p.stat().st_size
            if chunk > 0:
                with p.open("rb") as f:
                    f.seek(offset)
                    data = f.read(chunk)
                # 末尾不完整的多字节序列归还下一段（098）：定位末字符首字节，
                # 序列不完整则整字符让给下一段，next_offset 告知客户端真实消费位置
                cut = len(data)
                if cut > 0:
                    start = cut - 1
                    while start > 0 and (data[start] & 0xC0) == 0x80:
                        start -= 1
                    lead = data[start]
                    if lead & 0xF8 == 0xF0:
                        seq = 4
                    elif lead & 0xF0 == 0xE0:
                        seq = 3
                    elif lead & 0xE0 == 0xC0:
                        seq = 2
                    else:
                        seq = 1
                    if cut - start < seq:
                        cut = start
                done = offset + cut >= size
                return {
                    "kind": kind,
                    "editable": src.kind == "local" and done,
                    "text": data[:cut].decode("utf-8", errors="replace"),
                    "next_offset": offset + cut,
                    "size": size,
                    "has_more": not done,
                }
            text = p.read_text(encoding="utf-8", errors="replace")
            return {
                "kind": kind,
                "editable": src.kind == "local",
                "text": text,
                "size": size,
                "has_more": False,
            }
        if kind == "zip":
            return {"kind": kind, "editable": False, "entries": _zip_entries(p)}
        # docx/xlsx/pptx：前端组件库渲染（docx-preview/SheetJS/pptx-preview），只回类型
        # doc/ppt 老格式：前端走 office-pdf 转换预览（converter 不可用时提示下载）
        return {
            "kind": kind,
            "editable": False,
            "converter": bool(settings.office_convert_url) if kind == "legacy" else None,
        }

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
    entry: str = Query(""),
    convert: str = Query(""),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """签发 raw/zip-entry 短期签名 URL（iframe/img/video 加载用，10 分钟有效）。"""
    await _get_source(source_id, session)
    if entry:
        exp = int(time.time()) + 600
        sig = _sign_entry(source_id, path, entry, exp)
        url = (
            f"/api/knowledge/{source_id}/zip-entry?path={quote(path)}"
            f"&entry={quote(entry)}&exp={exp}&sig={sig}"
        )
        return ok({"url": url})
    if convert == "1":
        import hashlib
        import hmac as _hmac

        exp = int(time.time()) + 600
        sig = _hmac.new(
            settings.secret_key.encode(),
            f"{source_id}:office:{path}:{exp}".encode(),
            hashlib.sha256,
        ).hexdigest()
        url = (
            f"/api/knowledge/{source_id}/office-pdf?path={quote(path)}"
            f"&exp={exp}&sig={sig}"
        )
        return ok({"url": url})
    return ok({"url": _raw_url(source_id, path)})


def _zip_entries(p: Path) -> list[dict]:
    import zipfile

    out = []
    with zipfile.ZipFile(p) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX"):
                continue
            out.append(
                {
                    "name": info.filename,
                    "size": info.file_size,
                    "compress_size": info.compress_size,
                }
            )
    return out


def _sign_entry(source_id: int, path: str, entry: str, exp: int) -> str:
    import hashlib
    import hmac

    msg = f"{source_id}:{path}!{entry}:{exp}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


@router.get("/knowledge/{source_id}/zip-entry")
async def zip_entry_file(
    request: Request,
    source_id: int,
    path: str = Query(...),
    entry: str = Query(...),
    exp: int | None = Query(None),
    sig: str | None = Query(None),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
):
    """zip 内单文件提取流（鉴权同 raw：头或签名）。"""
    from app.core.deps import get_auth_context

    signature_ok = False
    if exp is not None and sig and exp >= int(time.time()):
        signature_ok = hmac.compare_digest(
            _sign_entry(source_id, path, entry, exp), sig
        )
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
    try:
        p = knowledge_fs.safe_join(_root_of(src), path)
    except PermissionError:
        raise BizError(CODE_VALIDATION, t("err.knowledge_path_escape"), 422)

    import mimetypes
    import zipfile

    if not p.is_file():
        raise BizError(CODE_NOT_FOUND, t("err.knowledge_file_missing"), 404)
    with zipfile.ZipFile(p) as z:
        names = {i.filename: i for i in z.infolist()}
        target = entry if entry in names else next(
            (n for n in names if n.endswith("/" + entry)), None
        )
        if target is None:
            raise BizError(CODE_NOT_FOUND, t("err.knowledge_file_missing"), 404)
        data = z.read(names[target])
    if len(data) > 200 * 1024 * 1024:
        raise BizError(CODE_VALIDATION, t("err.knowledge_read_failed", msg="entry too large"), 422)
    media = mimetypes.guess_type(entry)[0] or "application/octet-stream"
    from fastapi.responses import Response

    return Response(content=data, media_type=media, headers={
        "Content-Disposition": 'inline; filename*=UTF-8''{quote(entry)}',
    })


def _office_cache_path(p: Path) -> Path:
    import hashlib

    st = p.stat()
    digest = hashlib.sha1(f"{p}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()
    return Path(settings.data_dir) / "knowledge" / ".office-cache" / f"{digest}.pdf"


async def _convert_office_to_pdf(p: Path) -> Path:
    """gotenberg(LibreOffice) 把 .doc/.ppt 转 PDF；结果按内容指纹缓存。"""
    import httpx

    cache = _office_cache_path(p)
    if cache.is_file():
        return cache
    if not settings.office_convert_url:
        raise BizError(CODE_VALIDATION, t("err.office_convert_unavailable"), 422)
    cache.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=120.0) as client:
        with p.open("rb") as f:
            resp = await client.post(
                f"{settings.office_convert_url.rstrip('/')}/forms/libreoffice/convert",
                files={"files": (p.name, f)},
            )
    resp.raise_for_status()
    tmp = cache.with_suffix(".tmp")
    tmp.write_bytes(resp.content)
    tmp.replace(cache)
    return cache


@router.get("/knowledge/{source_id}/office-pdf")
async def office_pdf(
    request: Request,
    source_id: int,
    path: str = Query(...),
    exp: int | None = Query(None),
    sig: str | None = Query(None),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
):
    """.doc/.ppt → PDF 流（097：gotenberg 转换 + 缓存；鉴权同 raw）。"""
    import hashlib
    import hmac as _hmac

    signature_ok = False
    if exp is not None and sig and exp >= int(time.time()):
        expect = _hmac.new(
            settings.secret_key.encode(),
            f"{source_id}:office:{path}:{exp}".encode(),
            hashlib.sha256,
        ).hexdigest()
        signature_ok = _hmac.compare_digest(expect, sig)
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
    try:
        p = knowledge_fs.safe_join(_root_of(src), path)
    except PermissionError:
        raise BizError(CODE_VALIDATION, t("err.knowledge_path_escape"), 422)
    if not p.is_file():
        raise BizError(CODE_NOT_FOUND, t("err.knowledge_file_missing"), 404)
    pdf = await _convert_office_to_pdf(p)
    return FileResponse(
        pdf,
        media_type="application/pdf",
        filename=p.stem + ".pdf",
        content_disposition_type="inline",  # attachment 会让 iframe 直接变下载（097）
    )


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
