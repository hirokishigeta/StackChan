.PHONY: setup fmt lint test check run

setup:
	uv sync --extra dev

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	uv run mypy app

test:
	uv run pytest

check: fmt lint test

run:
	uv run uvicorn app.main:app --reload
