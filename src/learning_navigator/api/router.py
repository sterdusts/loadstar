"""Top-level API router."""

from fastapi import APIRouter

from learning_navigator.api.routers import ai, collaboration, data, health, learning, spaces

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(spaces.router)
api_router.include_router(learning.router)
api_router.include_router(ai.router)
api_router.include_router(collaboration.router)
api_router.include_router(data.router)
