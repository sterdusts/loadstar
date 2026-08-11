"""Operational health endpoint."""

from fastapi import APIRouter
from sqlalchemy import text

from learning_navigator.api.dependencies import SessionDependency

router = APIRouter(tags=["system"])


@router.get("/health")
def health(session: SessionDependency) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
