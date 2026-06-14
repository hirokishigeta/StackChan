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

# ws-ping-timeout is generous: the CoreS3 can't answer the server ping for many
# seconds while busy decoding a long TTS reply, and the default 20s timeout would
# drop the WebSocket mid-playback (truncating long replies). See ubuntu runbook.
run:
	uv run uvicorn app.main:app --reload --ws-ping-interval 30 --ws-ping-timeout 120
