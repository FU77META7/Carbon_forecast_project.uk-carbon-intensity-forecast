.PHONY: setup ingest quality features test lint all

setup:
	uv sync

# Incremental: re-running only fetches periods missing from the database.
ingest:
	uv run python -m carbon_forecast.ingest
	uv run python -m carbon_forecast.quality

quality:
	uv run python -m carbon_forecast.quality

# Runs sql/00-05 in order and materialises the training_set table.
features:
	uv run python -m carbon_forecast.features

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

all: setup ingest features
