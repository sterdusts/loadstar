"""FastAPI application factory and development entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from learning_navigator.api.router import api_router
from learning_navigator.config import Settings, get_settings
from learning_navigator.domain.exceptions import (
    AIConfigurationError,
    DomainError,
    EntityNotFoundError,
    InvalidPathRevisionError,
    ProgressCheckInRevisionConflictError,
    RevisionConflictError,
)
from learning_navigator.infrastructure.ai.providers import AIProviderError, build_provider
from learning_navigator.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
    initialize_schema,
)
from learning_navigator.infrastructure.security.credentials import (
    CredentialStore,
    KeyringCredentialStore,
)


def create_app(
    settings: Settings | None = None,
    *,
    include_ui: bool = True,
    credential_store: CredentialStore | None = None,
    ai_http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    settings_value = settings or get_settings()
    engine = create_database_engine(settings_value.database_url, echo=settings_value.debug)
    session_factory = create_session_factory(engine)
    owns_ai_http_client = ai_http_client is None
    shared_ai_http_client = ai_http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=15.0),
        follow_redirects=False,
    )
    credential_store_value = credential_store or KeyringCredentialStore()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if settings_value.auto_create_schema:
            initialize_schema(engine)
        try:
            yield
        finally:
            if owns_ai_http_client:
                await shared_ai_http_client.aclose()
            engine.dispose()

    app = FastAPI(
        title=settings_value.app_name,
        version="0.1.0",
        description="Editable knowledge maps, explainable paths and human-reviewed AI proposals.",
        lifespan=lifespan,
    )
    app.state.settings = settings_value
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.credential_store = credential_store_value
    app.state.ai_http_client = shared_ai_http_client
    app.state.ai_provider = build_provider(
        settings_value.ai_provider,
        base_url=settings_value.ai_base_url,
        model=settings_value.ai_model,
        api_key=(
            settings_value.ai_api_key.get_secret_value() if settings_value.ai_api_key else None
        ),
        client=shared_ai_http_client,
    )
    app.include_router(api_router)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
        if isinstance(exc, EntityNotFoundError):
            response_status = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, AIConfigurationError):
            response_status = status.HTTP_400_BAD_REQUEST
        else:
            response_status = status.HTTP_409_CONFLICT
        payload: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if hasattr(exc, "cycle_path"):
            payload["cycle_path"] = exc.cycle_path
        if isinstance(exc, RevisionConflictError | ProgressCheckInRevisionConflictError):
            payload["expected_revision"] = exc.expected_revision
            payload["current_revision"] = exc.current_revision
        if isinstance(exc, ProgressCheckInRevisionConflictError):
            payload["expected_check_in_id"] = exc.expected_check_in_id
            payload["current_check_in_id"] = exc.current_check_in_id
        if isinstance(exc, InvalidPathRevisionError):
            payload["issues"] = exc.issues
        return JSONResponse(status_code=response_status, content={"detail": payload})

    @app.exception_handler(AIProviderError)
    async def ai_provider_error_handler(_request: Request, exc: AIProviderError) -> JSONResponse:
        response_status = {
            "configuration_error": status.HTTP_400_BAD_REQUEST,
            "authentication_error": status.HTTP_401_UNAUTHORIZED,
            "request_error": status.HTTP_400_BAD_REQUEST,
            "rate_limit_error": status.HTTP_429_TOO_MANY_REQUESTS,
            "timeout_error": status.HTTP_504_GATEWAY_TIMEOUT,
            "connection_error": status.HTTP_502_BAD_GATEWAY,
            "upstream_error": status.HTTP_502_BAD_GATEWAY,
            "invalid_response": status.HTTP_502_BAD_GATEWAY,
        }.get(exc.code, status.HTTP_502_BAD_GATEWAY)
        return JSONResponse(
            status_code=response_status,
            content={
                "detail": {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                }
            },
        )

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/ui/") if include_ui else RedirectResponse("/docs")

    if include_ui:
        from learning_navigator.ui.app import mount_ui

        mount_ui(app, settings_value)
    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "learning_navigator.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    run()
