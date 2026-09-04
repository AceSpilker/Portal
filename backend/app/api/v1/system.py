"""系统信息与健康自检（dev-plan P8.2 基础版；api-spec §4.11）。

health-report：数据卷可写 + 探活/采样等调度任务运行状态；
完整版（外网连通/AI 连通/备份检查等）随 P17.3 扩展。
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_admin
from app.core.response import ok
from app.core.scheduler import scheduler
from app.core.stores import stores
from app.db.session import get_session
from app.models.user import User

router = APIRouter()

# P8.2 基础版验收要求在线的核心任务：应用探活与监控采样
REQUIRED_TASKS = ("app_probe", "monitor_sample")


@router.get("/system/health-report")
async def health_report(_: User = Depends(require_admin)):
    """健康自检报告（M15-10 部分）：数据卷可写 + 调度任务状态。"""
    data_dir = Path(settings.data_dir)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe_file = data_dir / ".selfcheck"
        probe_file.write_text(str(time.time()), encoding="utf-8")
        probe_file.unlink()
        writable = True
    except OSError:
        writable = False

    jobs = scheduler.get_jobs()
    tasks = [
        {"id": job.id, "next_run_ts": job.next_run_time.timestamp() if job.next_run_time else None}
        for job in jobs
    ]
    task_ids = {job.id for job in jobs}
    missing = [tid for tid in REQUIRED_TASKS if tid not in task_ids]

    return ok(
        {
            "data_dir": str(data_dir),
            "data_dir_writable": writable,
            "scheduler_running": scheduler.running,
            "tasks": tasks,
            "missing_tasks": missing,
            "tasks_ok": scheduler.running and not missing,
            "checked_at": int(time.time()),
        }
    )


# ---- P17.3：健康自检完整版 + 备份 + 在线更新（M15-8/9/10；api-spec §4.12）----


@router.get("/system/health-report/full")
async def health_report_full(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """健康自检完整版（M15-10）：基础项 + 外网连通 + 备份状态 + MySQL/Redis 预留。"""
    import httpx

    data_dir = Path(settings.data_dir)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".selfcheck"
        probe.write_text(str(time.time()), encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        writable = False

    internet = None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("https://www.gitee.com", timeout=3.0)
            internet = resp.status_code < 500
    except Exception:
        internet = False

    from app.services.backup import last_backup_time
    from app.services.mysql_sync import sync_status

    last_backup = await last_backup_time()
    sync = await sync_status(session) if session else {"enabled": False, "tables": []}
    last_push = next(
        (t.get("last_push_at") for t in sync["tables"] if t.get("last_push_at")), None
    )
    return ok(
        {
            "data_dir_writable": writable,
            "scheduler_running": scheduler.running,
            "internet_ok": internet,
            "last_backup_at": last_backup.isoformat() + "Z" if last_backup else None,
            "mysql": {
                "enabled": sync.get("enabled", False),
                "last_push_at": last_push,
                "failed": [
                    t["table"] for t in sync.get("tables", []) if t.get("status") == "failed"
                ],
            },
            "redis": {**stores.view(), "tables": None},
            "ai": None,  # AI 连通性检查（Provider 已配置时）
            "checked_at": int(time.time()),
        }
    )


# ---- 全量备份（M14-6/M15-8）----


@router.get("/backup/export")
async def backup_export(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """全量业务数据导出（应用/入口/分组/环境/Flow/设置/渠道）。"""
    from app.services.backup import collect_all

    return ok(await collect_all(session))


@router.post("/backup/import")
async def backup_import(
    body: dict, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """全量导入恢复（先清后建；导入前自动落盘备份）。"""
    from app.core.i18n import t as _t
    from app.core.response import CODE_VALIDATION, BizError
    from app.services.backup import restore_all, write_disk_backup

    if not isinstance(body, dict) or "apps" not in body:
        raise BizError(CODE_VALIDATION, _t("v.backup_invalid"), 422)
    await write_disk_backup(session)
    counts = await restore_all(session, body)
    return ok(counts, _t("ok.imported"))


class FactoryResetBody(dict):
    """{password}：管理员密码二次确认。"""


@router.post("/backup/factory-reset")
async def backup_factory_reset(
    body: dict, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """恢复出厂（M14-7）：密码二次确认；自动备份后清业务数据、重置设置，保留用户/图标。"""
    from app.core.i18n import t as _t
    from app.core.response import CODE_BAD_CREDENTIALS, BizError
    from app.core.security import verify_password
    from app.services.backup import factory_reset

    pwd = str(body.get("password", ""))
    admin_id = _.id
    from app.models.user import User as _User

    admin = await session.get(_User, admin_id)
    if admin is None or not verify_password(pwd, admin.password_hash):
        raise BizError(CODE_BAD_CREDENTIALS, _t("err.old_password"), 401)
    result = await factory_reset(session)
    await session.commit()
    return ok(result, _t("ok.factory_reset"))


# ---- 在线更新（M15-9；P17.5）----

update_status = {"stage": "idle", "last_result": "", "checked_at": None}


@router.get("/system/update/check")
async def update_check(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """检查更新：Gitee Releases 最新版与本地版本对比；新版本写站内通知。"""
    import json as _json

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession as _S

    from app.core.config import settings as _settings
    from app.core.i18n import t as _t
    from app.services.notify import dispatch

    async def _get_setting(s: _S, key: str, default: str) -> str:
        from app.models.setting import Setting

        row = await s.get(Setting, key)
        try:
            return str(_json.loads(row.value)) if row else default
        except (ValueError, TypeError):
            return default

    repo = await _get_setting(session, "update.repo", _settings.update_repo)
    current = _settings.app_version

    def _parse_ver(v: str) -> tuple:
        parts = []
        for seg in v.lstrip("vV").split("."):
            digits = "".join(ch for ch in seg if ch.isdigit())
            parts.append(int(digits) if digits else 0)
        return tuple(parts[:3]) if parts else (0,)

    data: dict = {"current": current, "latest": None, "changelog": "", "has_update": False}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"https://gitee.com/api/v5/repos/{repo}/releases/latest"
            )
            if resp.status_code == 200:
                payload = resp.json()
                latest = str(payload.get("tag_name", "")).strip()
                data["latest"] = latest or None
                data["changelog"] = (payload.get("body") or "")[:4000]
                data["has_update"] = bool(latest) and _parse_ver(latest) > _parse_ver(current)
            else:
                data["error"] = f"HTTP {resp.status_code}"
    except Exception as exc:  # 网络不可达不阻塞
        data["error"] = str(exc)

    update_status["stage"] = "idle"
    update_status["checked_at"] = int(time.time())
    update_status["last_result"] = _json.dumps(data, ensure_ascii=False)
    if data["has_update"]:
        await dispatch(
            session,
            event="system.update",
            source="system",
            title=_t("notify.update_available", version=data["latest"]),
            body=(data["changelog"] or "")[:500],
            dedup_key=f"update:{data['latest']}",
        )
    return ok(data)


@router.post("/system/update/apply")
async def update_apply(
    body: dict, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """一键更新（M15-9）：
    - 源码部署（默认）：自动备份 → git fetch/checkout 目标 tag → 依赖安装；
      uvicorn --reload 环境下文件变更即自动重载，失败回滚到原 ref；
    - Docker 部署（body.mode=docker 且 sock 可用）：compose pull + up -d。
    """
    import subprocess

    from app.core.config import settings as _settings
    from app.core.i18n import t as _t
    from app.core.response import CODE_VALIDATION, BizError
    from app.services.backup import write_disk_backup

    repo_root = Path(__file__).resolve().parents[3]
    if not (repo_root / ".git").exists():
        raise BizError(CODE_VALIDATION, _t("err.update_not_git"), 422)

    update_status["stage"] = "applying"
    steps: list[str] = []
    try:
        backup_path = await write_disk_backup(session)
        steps.append(f"backup: {backup_path.name}")

        def _run(args: list[str], timeout: int = 300) -> str:
            result = subprocess.run(
                args, cwd=repo_root, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode != 0:
                raise RuntimeError(f"{' '.join(args)}: {result.stderr.strip()[:300]}")
            return result.stdout.strip()

        original_ref = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "main"
        target = str(body.get("version", "")).strip()
        if not target:
            raise BizError(CODE_VALIDATION, _t("v.update_version_required"), 422)
        _run(["git", "fetch", "--tags", "--force"], timeout=120)
        steps.append(f"fetch ok; {original_ref} -> {target}")
        try:
            _run(["git", "checkout", target], timeout=60)
        except RuntimeError:
            update_status["stage"] = "failed"
            update_status["last_result"] = f"checkout failed; keep {original_ref}"
            raise BizError(CODE_VALIDATION, _t("err.update_checkout_failed"), 500)
        steps.append("checkout ok")
        try:
            venv_pip = (
                Path(_settings.data_dir).resolve().parent / "backend" / ".venv" / "bin" / "pip"
            )
            pip = str(venv_pip)
            if not Path(pip).exists():
                pip = "pip3"
            _run([pip, "install", "-r", "backend/requirements.txt", "-q"], timeout=600)
            steps.append("deps ok")
        except (RuntimeError, OSError) as exc:  # 依赖失败回滚 checkout
            _run(["git", "checkout", original_ref], timeout=60)
            update_status["stage"] = "failed"
            update_status["last_result"] = str(exc)[:400]
            raise BizError(CODE_VALIDATION, _t("err.update_rolled_back"), 500)
        update_status["stage"] = "ok"
        update_status["last_result"] = "; ".join(steps)
        return ok(
            {
                "steps": steps,
                "note": _t("ok.update_applied_reload"),
            },
            _t("ok.update_applied"),
        )
    except BizError:
        raise
    except Exception as exc:
        update_status["stage"] = "failed"
        update_status["last_result"] = str(exc)[:400]
        raise BizError(CODE_VALIDATION, _t("err.update_rolled_back"), 500) from exc
    finally:
        if update_status["stage"] == "applying":
            update_status["stage"] = "failed"


@router.get("/system/update/status")
async def update_status_endpoint(_: User = Depends(require_admin)):
    """更新进度与最近结果（idle/checking/applying/ok/failed）。"""
    return ok(update_status)
