.PHONY: setup ingest quality test lint all

setup:
	uv sync

# Incremental: re-running only fetches periods missing from the database.
ingest:
	uv run python -m carbon_forecast.ingest
	uv run python -m carbon_forecast.quality

quality:
	uv run python -m carbon_forecast.quality

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

all: setup ingest
