"""Operational health endpoint."""

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

from learning_navigator.api.dependencies import SessionDependency

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request, session: SessionDependency) -> dict[str, Any]:
    session.execute(text("SELECT 1"))
    identity = request.app.state.runtime_identity
    return {
        "status": "ok",
        "database": "reachable",
        "product_id": identity.product_id,
        "source_fingerprint": identity.source_fingerprint,
        "instance_token": identity.instance_token,
        "process_id": identity.process_id,
    }
