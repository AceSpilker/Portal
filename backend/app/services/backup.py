"""全量备份与恢复出厂（M14-6/M15-8/10；dev-plan P17.3）。

collect_all 输出业务数据全集（应用/入口/分组/环境档案/Flow/设置/图标），
用于：手动导出 JSON、自动定时备份（data/backups，保留 N 份）、
恢复出厂前的安全备份。restore_all 反向导入（按主键重建）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.ai import AiConversation, AiMessage
from app.models.flow import Flow, FlowRun
from app.models.network import NetworkProfile
from app.models.notify import NotifyChannel, NotifyRule
from app.models.portal import App, AppUrl, Category
from app.models.setting import DEFAULT_SETTINGS, Setting
from app.models.tools import WolTarget

EXPORT_VERSION = 2


async def collect_all(session: AsyncSession) -> dict:
    """业务数据全量导出（不含用户/会话/Token/审计/监控采样等敏感或大表）。"""
    cats = (await session.execute(select(Category))).scalars().all()
    apps = (
        (await session.execute(select(App).options(selectinload(App.urls))))
        .scalars()
        .all()
    )
    profiles = (await session.execute(select(NetworkProfile))).scalars().all()
    flows = (await session.execute(select(Flow))).scalars().all()
    settings_rows = (await session.execute(select(Setting))).scalars().all()
    wol = (await session.execute(select(WolTarget))).scalars().all()
    channels = (await session.execute(select(NotifyChannel))).scalars().all()
    rules = (await session.execute(select(NotifyRule))).scalars().all()
    return {
        "_export_version": EXPORT_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "categories": [
            {"id": c.id, "name": c.name, "icon": c.icon, "icon_type": c.icon_type,
             "sort": c.sort, "collapsed": c.collapsed}
            for c in cats
        ],
        "apps": [
            {
                "id": a.id, "name": a.name, "description": a.description, "icon": a.icon,
                "icon_type": a.icon_type, "category_id": a.category_id, "sort": a.sort,
                "enabled": a.enabled, "health_type": a.health_type,
                "health_target": a.health_target,
                "health_interval": a.health_interval, "open_mode": a.open_mode,
                "visibility": a.visibility, "visible_users": a.visible_users,
                "favorite": a.favorite, "tags": a.tags, "remark": a.remark, "doc_url": a.doc_url,
                "urls": [
                    {"id": u.id, "access_type": u.access_type, "url": u.url,
                     "label": u.label, "sort": u.sort}
                    for u in a.urls
                ],
            }
            for a in apps
        ],
        "network_profiles": [
            {"id": p.id, "name": p.name, "match_type": p.match_type, "cidrs": p.cidrs,
             "prefer_types": p.prefer_types, "enabled": p.enabled}
            for p in profiles
        ],
        "flows": [
            {"id": f.id, "name": f.name, "trigger_type": f.trigger_type,
             "trigger_config": f.trigger_config, "actions": f.actions,
             "enabled": f.enabled, "webhook_token": f.webhook_token}
            for f in flows
        ],
        "settings": {r.key: r.get_value() for r in settings_rows},
        "wol_targets": [{"name": w.name, "mac": w.mac, "note": w.note} for w in wol],
        "notify_channels": [
            {"id": c.id, "name": c.name, "type": c.type, "config": c.config, "enabled": c.enabled}
            for c in channels
        ],
        "notify_rules": [
            {"event": r.event, "channel_ids": r.channel_ids, "enabled": r.enabled,
             "quiet_start": r.quiet_start, "quiet_end": r.quiet_end}
            for r in rules
        ],
    }


async def restore_all(session: AsyncSession, data: dict) -> dict:
    """全量导入（先清后建，应用/入口/分组/档案/Flow/设置/渠道规则）。"""
    if int(data.get("_export_version", 0)) > EXPORT_VERSION:
        raise ValueError("export version too new")

    await session.execute(delete(AppUrl))
    await session.execute(delete(App))
    await session.execute(delete(Category))
    await session.execute(delete(NetworkProfile))
    await session.execute(delete(FlowRun))
    await session.execute(delete(Flow))
    for row in (await session.execute(select(Setting))).scalars():
        await session.delete(row)
    await session.execute(delete(WolTarget))
    await session.execute(delete(NotifyRule))
    await session.execute(delete(NotifyChannel))
    await session.flush()

    for c in data.get("categories", []):
        session.add(Category(id=c["id"], name=c["name"], icon=c.get("icon"),
                             icon_type=c.get("icon_type"), sort=c.get("sort", 0),
                             collapsed=c.get("collapsed", False)))
    for a in data.get("apps", []):
        app = App(
            id=a["id"], name=a["name"], description=a.get("description", ""),
            icon=a.get("icon"), icon_type=a.get("icon_type", "url"),
            category_id=a.get("category_id"), sort=a.get("sort", 0),
            enabled=a.get("enabled", True), health_type=a.get("health_type", ""),
            health_target=a.get("health_target"), health_interval=a.get("health_interval", 60),
            open_mode=a.get("open_mode", "newtab"), visibility=a.get("visibility", "all"),
            visible_users=a.get("visible_users", "[]"), favorite=a.get("favorite", False),
            tags=a.get("tags", []), remark=a.get("remark", ""), doc_url=a.get("doc_url"),
        )
        session.add(app)
        session.flush()
        for u in a.get("urls", []):
            session.add(AppUrl(
                id=u.get("id"), app_id=app.id, access_type=u["access_type"],
                url=u["url"], label=u.get("label", ""), sort=u.get("sort", 0),
            ))
    for p in data.get("network_profiles", []):
        session.add(NetworkProfile(
            id=p["id"], name=p["name"], match_type=p.get("match_type", "cidr"),
            cidrs=p.get("cidrs", "[]"),
            prefer_types=p.get("prefer_types", "[]"), enabled=p.get("enabled", True),
        ))
    for f in data.get("flows", []):
        session.add(Flow(
            id=f["id"], name=f["name"], trigger_type=f.get("trigger_type", "manual"),
            trigger_config=f.get("trigger_config", "{}"), actions=f.get("actions", "[]"),
            enabled=f.get("enabled", 0), webhook_token=f.get("webhook_token"),
        ))
    for key, value in (data.get("settings") or {}).items():
        await session.merge(Setting(key=key, value=json.dumps(value, ensure_ascii=False)))
    for w in data.get("wol_targets", []):
        session.add(WolTarget(name=w["name"], mac=w["mac"]))
    for c in data.get("notify_channels", []):
        session.add(NotifyChannel(id=c["id"], name=c["name"], type=c["type"],
                                  config=c.get("config", "{}"), enabled=c.get("enabled", True)))
    for r in data.get("notify_rules", []):
        session.add(NotifyRule(
            event=r["event"], channel_ids=r.get("channel_ids", "[]"),
            enabled=r.get("enabled", 1),
            quiet_start=r.get("quiet_start"), quiet_end=r.get("quiet_end"),
        ))
    await session.commit()
    counts = {
        "categories": len(data.get("categories", [])),
        "apps": len(data.get("apps", [])),
        "flows": len(data.get("flows", [])),
        "settings": len((data.get("settings") or {})),
    }
    return counts


async def write_disk_backup(session: AsyncSession) -> Path:
    """自动备份（M15-8）：写 data/backups/backup-*.json，并按 keep 份数裁剪。"""
    data = await collect_all(session)
    backup_dir = Path(settings.data_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    path = backup_dir / f"backup-{stamp}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    keep = await _backup_keep(session)
    backups = sorted(backup_dir.glob("backup-*.json"))
    for old in backups[:-keep] if len(backups) > keep else []:
        old.unlink(missing_ok=True)
    return path


async def _backup_keep(session: AsyncSession) -> int:
    row = await session.get(Setting, "backup.keep")
    try:
        return max(1, int(json.loads(row.value))) if row else 7
    except (ValueError, TypeError):
        return 7


async def last_backup_time() -> datetime | None:
    backup_dir = Path(settings.data_dir) / "backups"
    files = sorted(backup_dir.glob("backup-*.json"))
    if not files:
        return None
    return datetime.fromtimestamp(files[-1].stat().st_mtime)


async def factory_reset(session: AsyncSession) -> dict:
    """恢复出厂（M14-7）：先落盘备份，再清业务数据+重置设置，保留用户与图标库。"""
    await write_disk_backup(session)
    counts = {"apps": 0, "flows": 0}
    for table in (AppUrl, App, Category, NetworkProfile, FlowRun, Flow, WolTarget,
                  NotifyRule, NotifyChannel, AiMessage, AiConversation):
        counts[table.__tablename__] = await session.execute(delete(table))
    counts["apps"] = counts[App.__tablename__].rowcount or 0
    counts["flows"] = counts[Flow.__tablename__].rowcount or 0
    # 设置恢复默认（用户改过的全部回默认值）
    for key in list((await session.execute(select(Setting.key))).scalars()):
        if key not in DEFAULT_SETTINGS:
            await session.execute(delete(Setting).where(Setting.key == key))
    for key, value in DEFAULT_SETTINGS.items():
        await session.merge(Setting(key=key, value=value))
    await session.commit()
    return {"apps": counts["apps"], "flows": counts["flows"]}
