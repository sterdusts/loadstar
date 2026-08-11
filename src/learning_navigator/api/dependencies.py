"""FastAPI dependency wiring."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from learning_navigator.application.services import NavigatorApplication
from learning_navigator.config import Settings
from learning_navigator.domain.exceptions import ConcurrentRevisionConflictError
from learning_navigator.infrastructure.ai.providers import AIProvider
from learning_navigator.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyKnowledgeRepository,
)


def get_session(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
        session.commit()
    except StaleDataError as exc:
        session.rollback()
        raise ConcurrentRevisionConflictError() from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDependency = Annotated[Session, Depends(get_session)]


def get_application(request: Request, session: SessionDependency) -> NavigatorApplication:
    settings: Settings = request.app.state.settings
    provider: AIProvider = request.app.state.ai_provider
    return NavigatorApplication(
        SqlAlchemyKnowledgeRepository(session),
        settings,
        provider,
        request.app.state.credential_store,
        request.app.state.ai_http_client,
    )


ApplicationDependency = Annotated[NavigatorApplication, Depends(get_application)]


def get_current_user_id(
    application: ApplicationDependency,
    x_user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
) -> str:
    if x_user_id:
        if not application.settings.allow_test_user_header:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "unsafe_user_header_disabled",
                    "message": "User switching is disabled in the local product runtime",
                },
            )
        application.repository.get_user(x_user_id)
        return x_user_id
    return str(application.ensure_local_user()["id"])


CurrentUserDependency = Annotated[str, Depends(get_current_user_id)]
