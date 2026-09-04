from fastapi import APIRouter

from app.api.v1 import (
    ai,
    apps,
    auth,
    categories,
    crypto,
    docker,
    downloads,
    files,
    flows,
    health,
    icons,
    layouts,
    me,
    monitor,
    network_profiles,
    notify,
    ports,
    probe,
    schedule,
    settings,
    system,
    tools,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(crypto.router, tags=["crypto"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(me.router, tags=["auth"])
api_router.include_router(layouts.router, tags=["dashboard"])
api_router.include_router(schedule.router, tags=["schedule"])
api_router.include_router(files.router, tags=["files"])
api_router.include_router(downloads.router, tags=["downloads"])
api_router.include_router(icons.router, tags=["portal"])
api_router.include_router(categories.router, tags=["portal"])
api_router.include_router(apps.router, tags=["portal"])
api_router.include_router(network_profiles.router, tags=["network"])
api_router.include_router(monitor.router, tags=["monitor"])
api_router.include_router(probe.router, tags=["probe"])
api_router.include_router(users.router, tags=["users"])
api_router.include_router(tools.router, tags=["tools"])
api_router.include_router(system.router, tags=["system"])
api_router.include_router(notify.router, tags=["notify"])
api_router.include_router(ports.router, tags=["ports"])
api_router.include_router(docker.router, tags=["docker"])
api_router.include_router(ai.router, tags=["ai"])
api_router.include_router(flows.router, tags=["flows"])
