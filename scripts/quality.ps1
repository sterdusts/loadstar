$ErrorActionPreference = 'Stop'

uv run ruff format --check .
uv run ruff check .
uv run mypy src/learning_navigator
uv run pytest
