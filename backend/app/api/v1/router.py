from fastapi import APIRouter

from app.api.v1 import apps, auth, categories, crypto, health

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(crypto.router, tags=["crypto"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(categories.router, tags=["portal"])
api_router.include_router(apps.router, tags=["portal"])
