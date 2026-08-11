$ErrorActionPreference = 'Stop'

uv sync --extra dev
uv run alembic upgrade head
uv run learning-navigator
