from fastapi import APIRouter

from app.api.v1 import auth, crypto, health

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(crypto.router, tags=["crypto"])
api_router.include_router(auth.router, tags=["auth"])
