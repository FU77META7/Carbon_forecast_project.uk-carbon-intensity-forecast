.PHONY: setup ingest quality features tune backtest evaluate test lint all

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

# Time-based validation only; writes config/lgbm_params.yaml and reports/tuning.md.
tune:
	uv run python -m carbon_forecast.models.tune

# Rolling-origin backtest (monthly retraining), then tables and figures.
backtest:
	uv run python -m carbon_forecast.backtest

evaluate:
	uv run python -m carbon_forecast.evaluate

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

all: setup ingest features tune backtest evaluate
