.PHONY: setup ingest quality features tune backtest evaluate app notebook test lint all clean

# DuckDB file for every pipeline step; override to rebuild elsewhere, e.g.
#   make all DB=/tmp/fresh.duckdb
DB ?= data/carbon.duckdb

setup:
	uv sync

# Incremental: re-running only fetches periods missing from the database.
ingest:
	uv run python -m carbon_forecast.ingest --db $(DB)
	uv run python -m carbon_forecast.quality --db $(DB)

quality:
	uv run python -m carbon_forecast.quality --db $(DB)

# Runs sql/00-05 in order and materialises the training_set table.
features:
	uv run python -m carbon_forecast.features --db $(DB)

# Time-based validation only; writes config/lgbm_params.yaml and reports/tuning.md.
tune:
	uv run python -m carbon_forecast.models.tune --db $(DB)

# Rolling-origin backtest (monthly retraining).
backtest:
	uv run python -m carbon_forecast.backtest --db $(DB)

# Tables and figures in reports/, and the generated sections of README.md.
evaluate:
	uv run python -m carbon_forecast.evaluate --db $(DB)

# Reads precomputed backtest tables from config's db_path; never trains.
# Stop the app before rebuilding: DuckDB blocks writers while it is open.
app:
	uv run --group app streamlit run app/streamlit_app.py

# Re-executes the EDA notebook in place against the local database.
notebook:
	uv run --group notebook jupyter nbconvert --to notebook --execute --inplace notebooks/01_eda.ipynb

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

# Full rebuild from the public APIs (roughly 15-20 minutes, mostly polite API pacing).
all: setup ingest features tune backtest evaluate

# Deletes the local database; `make all` rebuilds it.
clean:
	rm -f $(DB) $(DB).wal
