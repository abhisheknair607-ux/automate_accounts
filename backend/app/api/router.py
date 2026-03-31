from fastapi import APIRouter

from app.api.routes import cases, exports, health


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(cases.router, prefix="/cases", tags=["cases"])
api_router.include_router(exports.router, prefix="/exports", tags=["exports"])
