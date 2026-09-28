# GB Carbon Intensity Forecast

Forecasting GB national grid carbon intensity (gCO2/kWh) 24–48 hours ahead at
30-minute resolution. Work in progress; see `reports/data_quality.md` for the
current state of the ingested data.

## Quick start

```bash
uv sync
make ingest   # pulls Carbon Intensity + Open-Meteo data into data/carbon.duckdb
make test
```

`data/` is gitignored and fully rebuilt by `make ingest`.
