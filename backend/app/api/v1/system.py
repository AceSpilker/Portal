"""系统信息与健康自检（dev-plan P8.2 基础版；api-spec §4.11）。

health-report：数据卷可写 + 探活/采样等调度任务运行状态；
完整版（外网连通/AI 连通/备份检查等）随 P17.3 扩展。
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.deps import require_admin
from app.core.response import ok
from app.core.scheduler import scheduler
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
