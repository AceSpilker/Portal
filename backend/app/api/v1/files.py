"""文件管理接口（M11-1~4/6；dev-plan P16.2；api-spec §4.11）。

- 白名单目录：设置键 files.roots=[{name,path}]，为空时整个模块 404（前端隐藏）；
- 防目录穿越：realpath 归一后必须落在白名单根内（含 symlink 场景）；
- 上传/下载走 JSON+base64（保持 P24 全链路密文），分别限 100MB/64MB；
- 媒体预览（M11-4）需浏览器原生 img/video 直连，无法走信封解密——
  提供 /files/raw?token= 短时签名直链（在 /api 之外，随静态资源豁免；
  生产以 TLS 为基线），令牌 JWT 签发、10 分钟过期。
"""

from __future__ import annotations

import mimetypes
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import CODE_DUPLICATED, CODE_NOT_FOUND, CODE_VALIDATION, BizError, ok
from app.core.security import create_signed_token, decode_token
from app.db.session import get_session
from app.models.user import User

router = APIRouter()

UPLOAD_MAX_B64 = 100 * 1024 * 1024  # base64 后上限（≈74MB 原始）
DOWNLOAD_MAX_B64 = 64 * 1024 * 1024
PREVIEW_TOKEN_TTL_SEC = 600

FileTarget = tuple[Path, str]  # (根路径实际目录, 相对路径)


async def _roots(session: AsyncSession) -> list[dict]:
    """读取白名单（files.roots），路径支持 ~ 展开；空=模块未启用。"""
    from app.models.setting import Setting

    row = await session.get(Setting, "files.roots")
    if not row:
        return []
    import json

    out = []
    for item in json.loads(row.value):
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        out.append({"name": item.get("name") or Path(path).name, "path": path})
    return out


async def _resolve(
    session: AsyncSession, root_name: str, rel: str, must_exist: bool = True
) -> Path:
    roots = await _roots(session)
    root_cfg = next((r for r in roots if r["name"] == root_name), None)
    if root_cfg is None:
        raise BizError(CODE_NOT_FOUND, t("err.file_root_not_found"), 404)
    base = Path(os.path.expanduser(root_cfg["path"])).resolve()
    rel = (rel or "").strip().lstrip("/\\")
    target = (base / rel).resolve() if rel else base
    if target != base and base not in target.parents:
        raise BizError(CODE_VALIDATION, t("err.file_path_forbidden"), 422)
    if must_exist and not target.exists():
        raise BizError(CODE_NOT_FOUND, t("err.file_not_found"), 404)
    return target


def _entry(p: Path) -> dict:
    st = p.stat()
    return {
        "name": p.name,
        "dir": p.is_dir(),
        "size": 0 if p.is_dir() else st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }


@router.get("/files/roots")
async def list_roots(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """白名单根清单（A 可读；为空时前端隐藏文件页签）。"""
    return ok(await _roots(session))


@router.get("/files/list")
async def list_dir(
    root: str,
    path: str = "",
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """目录浏览（M11-1）：条目列表（目录在前、名称排序）。"""
    target = await _resolve(session, root, path)
    if not target.is_dir():
        raise BizError(CODE_VALIDATION, t("err.file_not_dir"), 422)
    entries = []
    try:
        for child in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            if child.name.startswith("."):
                continue
            try:
                entries.append(_entry(child))
            except OSError:
                continue  # 竞态删除/无权限单条跳过
    except OSError as exc:
        raise BizError(CODE_VALIDATION, t("err.file_read_failed"), 422) from exc
    return ok({"root": root, "path": path, "entries": entries})


class FileBody(BaseModel):
    root: str
    path: str = ""


class UploadBody(FileBody):
    filename: str = Field(max_length=255)
    data: str  # base64


class WriteBody(FileBody):
    name: str = Field(max_length=255)


class MoveBody(FileBody):
    dest: str = ""


@router.post("/files/upload")
async def upload_file(
    body: UploadBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """上传（M11-2）：JSON+base64 保持密文传输；已存在同名文件 4003。"""
    import base64 as b64mod

    if len(body.data) > UPLOAD_MAX_B64:
        raise BizError(CODE_VALIDATION, t("err.file_too_large"), 422)
    target = await _resolve(session, body.root, body.path, must_exist=False)
    if not target.is_dir():
        raise BizError(CODE_VALIDATION, t("err.file_not_dir"), 422)
    name = Path(body.filename).name  # 去路径成分
    if not name or name.startswith("."):
        raise BizError(CODE_VALIDATION, t("v.file_name_invalid"), 422)
    dest = target / name
    if dest.exists():
        raise BizError(CODE_DUPLICATED, t("err.file_exists"), 400)
    try:
        dest.write_bytes(b64mod.b64decode(body.data, validate=True))
    except Exception as exc:
        raise BizError(CODE_VALIDATION, t("err.file_b64_invalid"), 422) from exc
    return ok(
        {"path": f"{body.path}/{name}".lstrip("/"), "size": dest.stat().st_size}, t("ok.saved")
    )


@router.get("/files/download")
async def download_file(
    root: str,
    path: str,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """下载（M11-2）：≤64MB 经 base64 JSON 回传；更大文件建议局域网共享。"""
    import base64 as b64mod

    target = await _resolve(session, root, path)
    if target.is_dir():
        raise BizError(CODE_VALIDATION, t("err.file_not_file"), 422)
    size = target.stat().st_size
    if size * 4 / 3 > DOWNLOAD_MAX_B64:
        raise BizError(CODE_VALIDATION, t("err.file_too_large"), 422)
    return ok(
        {
            "filename": target.name,
            "size": size,
            "data": b64mod.b64encode(target.read_bytes()).decode(),
        }
    )


@router.post("/files/mkdir")
async def mkdir(
    body: WriteBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    target = await _resolve(session, body.root, body.path)
    name = Path(body.name).name
    if not name or name.startswith("."):
        raise BizError(CODE_VALIDATION, t("v.file_name_invalid"), 422)
    dest = target / name
    if dest.exists():
        raise BizError(CODE_DUPLICATED, t("err.file_exists"), 400)
    dest.mkdir(parents=False)
    return ok({"path": f"{body.path}/{name}".lstrip("/")}, t("ok.saved"))


@router.post("/files/rename")
async def rename(
    body: WriteBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """重命名（M11-3）：name 只取文件名成分，不改变所在目录。"""
    target = await _resolve(session, body.root, body.path)
    name = Path(body.name).name
    if not name or name.startswith("."):
        raise BizError(CODE_VALIDATION, t("v.file_name_invalid"), 422)
    dest = target.parent / name
    if dest.exists():
        raise BizError(CODE_DUPLICATED, t("err.file_exists"), 400)
    target.rename(dest)
    return ok({"path": str(dest.relative_to(await _root_base(session, body.root)))}, t("ok.saved"))


@router.post("/files/delete")
async def delete_path(
    body: FileBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """删除（M11-3）：目录需为空才能删（防误删整树）。"""
    target = await _resolve(session, body.root, body.path)
    if target == target.resolve() and target.parent == target:  # 根本身不可删
        raise BizError(CODE_VALIDATION, t("err.file_path_forbidden"), 422)
    if target.is_dir():
        try:
            target.rmdir()
        except OSError as exc:
            raise BizError(CODE_VALIDATION, t("err.file_dir_not_empty"), 422) from exc
    else:
        target.unlink()
    return ok({"deleted": body.path}, t("ok.deleted"))


@router.post("/files/move")
async def move_path(
    body: MoveBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """移动/复制（M11-3）：dest 为目标目录（同根内）。"""
    src = await _resolve(session, body.root, body.path)
    dest_dir = await _resolve(session, body.root, body.dest)
    if not dest_dir.is_dir():
        raise BizError(CODE_VALIDATION, t("err.file_not_dir"), 422)
    dest = dest_dir / src.name
    if dest.exists():
        raise BizError(CODE_DUPLICATED, t("err.file_exists"), 400)
    shutil.move(str(src), str(dest))
    return ok({"path": str(dest.relative_to(await _root_base(session, body.root)))}, t("ok.saved"))


async def _root_base(session: AsyncSession, root_name: str) -> Path:
    roots = await _roots(session)
    cfg = next((r for r in roots if r["name"] == root_name), None)
    if cfg is None:
        raise BizError(CODE_NOT_FOUND, t("err.file_root_not_found"), 404)
    return Path(os.path.expanduser(cfg["path"])).resolve()


@router.post("/files/raw-url")
async def raw_url(
    body: FileBody,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """媒体预览直链（M11-4）：签发 10 分钟 JWT 短链（/files/raw，豁免信封）。"""
    target = await _resolve(session, body.root, body.path)
    if target.is_dir():
        raise BizError(CODE_VALIDATION, t("err.file_not_file"), 422)
    token = create_signed_token(
        {"sub": "file-preview", "path": str(target)},
        token_type="file",
        expires_delta=timedelta(seconds=PREVIEW_TOKEN_TTL_SEC),
    )
    return ok({"url": f"/files/raw?token={token}", "expires_in": PREVIEW_TOKEN_TTL_SEC})


async def serve_raw(token: str) -> FileResponse:
    """/files/raw 处理器主体（路由注册在 main.py，/api 之外）。"""
    try:
        payload = decode_token(token, "file")
    except Exception as exc:
        raise BizError(CODE_NOT_FOUND, t("err.file_token_invalid"), 404) from exc
    path = Path(payload.get("path", ""))
    # 二次校验：仍必须在白名单内（防止配置变更后旧 token 越权）
    async with _raw_session() as session:
        roots = await _roots(session)
        ok_paths = [Path(os.path.expanduser(r["path"])).resolve() for r in roots]
    resolved = path.resolve()
    if not any(p in resolved.parents or resolved == p for p in ok_paths):
        raise BizError(CODE_NOT_FOUND, t("err.file_path_forbidden"), 404)
    if not resolved.is_file():
        raise BizError(CODE_NOT_FOUND, t("err.file_not_found"), 404)
    media = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return FileResponse(resolved, media_type=media)


def _raw_session():
    from app.db.session import SessionLocal

    return SessionLocal()


# ---- 文本编辑与空间分析（M11-5/7；dev-plan P22.2）----

TEXT_SUFFIXES = (".txt", ".md", ".conf", ".json", ".yaml", ".yml", ".log", ".csv", ".py", ".sh")


class ContentBody(BaseModel):
    root: str
    path: str
    content: str


@router.get("/files/text")
async def read_text(
    root: str,
    path: str,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """读取小文本文件内容（≤256KB）。"""
    target = await _resolve(session, root, path)
    if target.stat().st_size > 256 * 1024:
        raise BizError(CODE_VALIDATION, t("err.file_too_large"), 422)
    return ok({"content": target.read_text(encoding="utf-8", errors="replace")})


@router.post("/files/content")
async def write_text(
    body: ContentBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """保存文本文件内容（M11-5 文本编辑）。"""
    target = await _resolve(session, body.root, body.path)
    if target.is_dir():
        raise BizError(CODE_VALIDATION, t("err.file_not_file"), 422)
    if len(body.content.encode()) > 256 * 1024:
        raise BizError(CODE_VALIDATION, t("err.file_too_large"), 422)
    target.write_text(body.content, encoding="utf-8")
    return ok({"path": body.path}, t("ok.saved"))


async def _dir_size(path: Path, depth: int = 0, max_depth: int = 3) -> int:
    if depth > max_depth:
        return 0
    total = 0
    try:
        for child in path.iterdir():
            if child.is_dir() and not child.is_symlink():
                total += await _dir_size(child, depth + 1, max_depth)
            elif child.is_file():
                total += child.stat().st_size
    except OSError:
        return total
    return total


@router.get("/files/analyze")
async def analyze_dir(
    root: str,
    path: str = "",
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """空间分析（M11-7）：子目录/文件大小 Top 列表（递归深度 3）。"""
    target = await _resolve(session, root, path)
    if not target.is_dir():
        raise BizError(CODE_VALIDATION, t("err.file_not_dir"), 422)
    entries = []
    try:
        for child in target.iterdir():
            if child.name.startswith("."):
                continue
            if child.is_dir():
                entries.append({"name": child.name, "dir": True, "size": await _dir_size(child)})
            else:
                entries.append({"name": child.name, "dir": False, "size": child.stat().st_size})
    except OSError as exc:
        raise BizError(CODE_VALIDATION, t("err.file_read_failed"), 422) from exc
    entries.sort(key=lambda e: e["size"], reverse=True)
    return ok({"root": root, "path": path, "entries": entries[:30]})
