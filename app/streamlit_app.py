"""GB carbon intensity forecast: backtest explorer.

Run with `make app` (or `uv run --group app streamlit run app/streamlit_app.py`).
Reads precomputed backtest outputs from DuckDB; it never trains or refits a model.
"""

from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from carbon_forecast import app_data
from carbon_forecast.config import load_settings, resolve
from carbon_forecast.evaluate import MODELS

st.set_page_config(page_title="GB carbon intensity forecast", layout="wide")

# Colours follow the model, the same as in the report figures. Dark mode uses the
# same hues stepped for a dark surface.
DARK_COLOURS = {
    "weather_forecast": "#3987e5",
    "no_weather": "#d95926",
    "seasonal_naive_day": "#199e70",
    "seasonal_naive_week": "#c98500",
    "persistence": "#d55181",
    "no_weather_short": "#008300",
    "oracle_weather": "#9085e9",
    "neso_stored_forecast": "#898781",
}
DEFAULT_SERIES = ["weather_forecast", "no_weather", "seasonal_naive_day"]
HORIZON_DEFAULT = [
    "weather_forecast",
    "no_weather",
    "seasonal_naive_day",
    "seasonal_naive_week",
    "persistence",
    "oracle_weather",
]
METRICS = {
    "MAE (gCO2/kWh)": "mae",
    "RMSE (gCO2/kWh)": "rmse",
    "MAPE (%)": "mape",
    "Skill vs seasonal naive (latest day)": "skill_vs_seasonal_naive_day",
}

theme = getattr(getattr(st.context, "theme", None), "type", None)
dark = theme == "dark"
INK = "#ffffff" if dark else "#0b0b0b"
GRID = "#2c2c2a" if dark else "#e1e0d9"


def colour(model: str) -> str:
    return DARK_COLOURS[model] if dark else MODELS[model][1]


def label(model: str) -> str:
    return MODELS[model][0]


@st.cache_resource
def get_connection():
    path = resolve(load_settings()["db_path"])
    if not path.exists():
        return None
    return app_data.connect_readonly(path)


con = get_connection()
if con is None or app_data.missing_tables(con):
    st.error(
        "Backtest outputs not found. Build them first with `make all` "
        "(or `make features tune backtest evaluate` if the data is already ingested)."
    )
    st.stop()


@st.cache_data
def load_static():
    return (
        app_data.overall(con),
        app_data.metrics_by_horizon(con),
        app_data.interval_coverage(con),
        app_data.target_date_range(con),
    )


overall, by_horizon, coverage, (first_day, last_day) = load_static()

# --- header ------------------------------------------------------------------
st.title("GB grid carbon intensity, 24-48 hours ahead")
wf, sn = overall.loc["weather_forecast"], overall.loc["seasonal_naive_day"]
cov_all = coverage[coverage["horizons"] == "all horizons"].set_index("interval")
st.caption(
    f"Rolling-origin backtest over {first_day:%d %b %Y} to {last_day:%d %b %Y}: "
    f"{int(wf['n']):,} forecasts, monthly retraining. Errors in gCO2/kWh. All numbers are "
    "read from the backtest tables; nothing is trained in this app."
)
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Model MAE",
    f"{wf['mae']:.1f}",
    help="Mean absolute error of LightGBM + weather forecast, in gCO2/kWh.",
)
c2.metric(
    "Baseline MAE",
    f"{sn['mae']:.1f}",
    help="Seasonal naive: the same half-hour on the latest day already published "
    "when the forecast is issued (2-3 days earlier). gCO2/kWh.",
)
c3.metric(
    "Skill vs baseline",
    f"{wf['skill_vs_seasonal_naive_day']:.2f}",
    help="1 - model MAE / baseline MAE. 0 = no better than the baseline.",
)
c4.metric(
    "Interval coverage",
    f"{cov_all.loc['conformal (CQR)', 'coverage_%']:.1f}%",
    help="Share of actuals inside the conformal 10-90% interval (target 80%). "
    "The raw quantile models covered "
    f"{cov_all.loc['raw quantile', 'coverage_%']:.1f}% before calibration.",
)

tab_forecast, tab_horizon, tab_how = st.tabs(
    ["Forecast vs actual", "Accuracy by horizon", "How it works"]
)

# --- forecast vs actual ------------------------------------------------------------
with tab_forecast:
    left, mid, right = st.columns([2, 1.4, 3])
    default_start = max(first_day, last_day - timedelta(days=6))
    picked = left.date_input(
        "Target dates (UTC)",
        value=(default_start, last_day),
        min_value=first_day,
        max_value=last_day,
    )
    issue_hour = mid.selectbox(
        "Issued at (UTC, day before)",
        app_data.ISSUE_HOURS,
        index=2,
        format_func=lambda h: f"{h:02d}:00",
    )
    options = [m for m in MODELS if m != "no_weather_short"]
    shown = right.multiselect("Series", options, default=DEFAULT_SERIES, format_func=label)
    show_band = st.checkbox(
        "Show 10-90% interval (conformal) for LightGBM + weather forecast", value=True
    )

    if not isinstance(picked, tuple) or len(picked) != 2:
        st.info("Pick a start and an end date.")
        st.stop()
    start, end = picked
    if (end - start).days > 62:
        st.warning("Showing the first 62 days of the selection.")
        end = start + timedelta(days=62)

    long, wide = app_data.day_ahead(con, start, end, issue_hour, shown)
    if wide.empty:
        st.info("No forecasts for this selection.")
    else:
        long["label"] = long["series"].map(lambda s: "Actual" if s == "y_actual_gco2" else label(s))
        # Explicit UTC: Vega-Lite would otherwise read naive timestamps as the
        # viewer's local time and shift or drop hours around their DST changes.
        for frame in (long, wide):
            frame["t_utc"] = frame["target_time_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        wide["t_label"] = wide["target_time_utc"].dt.strftime("%a %d %b %H:%M UTC")
        domain = ["Actual", *[label(m) for m in shown]]
        palette = [INK, *[colour(m) for m in shown]]
        x = alt.X(
            "t_utc:T",
            title="Target time (UTC)",
            scale=alt.Scale(type="utc"),
            axis=alt.Axis(format="%a %d %b", labelAngle=0),
        )
        y = alt.Y("gco2:Q", title="Carbon intensity (gCO2/kWh)", scale=alt.Scale(zero=True))

        lines = (
            alt.Chart(long)
            .mark_line(strokeWidth=2)
            .encode(
                x=x,
                y=y,
                color=alt.Color(
                    "label:N",
                    scale=alt.Scale(domain=domain, range=palette),
                    legend=alt.Legend(title=None, orient="bottom", labelLimit=0, columns=3),
                ),
                strokeDash=alt.condition(
                    alt.datum.series == "oracle_weather", alt.value([6, 4]), alt.value([1, 0])
                ),
            )
        )
        layers = []
        if show_band:
            layers.append(
                alt.Chart(wide)
                .mark_area(opacity=0.14, color=colour("weather_forecast"))
                .encode(x=x, y="weather_forecast_cp10:Q", y2="weather_forecast_cp90:Q")
            )
        layers.append(lines)

        # Crosshair tooltip: one rule per target time carrying every shown value.
        hover = alt.selection_point(
            fields=["t_utc"],
            nearest=True,
            on="pointerover",
            empty=False,
            clear="pointerout",
        )
        tips = [
            alt.Tooltip("t_label:N", title="Target"),
            alt.Tooltip("horizon_h:Q", title="Hours ahead"),
            alt.Tooltip("y_actual_gco2:Q", title="Actual", format=".0f"),
        ]
        tips += [alt.Tooltip(f"{m}:Q", title=label(m), format=".0f") for m in shown]
        if show_band:
            tips += [
                alt.Tooltip("weather_forecast_cp10:Q", title="Interval low", format=".0f"),
                alt.Tooltip("weather_forecast_cp90:Q", title="Interval high", format=".0f"),
            ]
        layers.append(
            alt.Chart(wide)
            .mark_rule(color=GRID, strokeWidth=12)
            .encode(
                x=x,
                opacity=alt.condition(hover, alt.value(0.6), alt.value(0)),
                tooltip=tips,
            )
            .add_params(hover)
        )
        layers.append(
            lines.mark_point(filled=True, size=50)
            .encode(opacity=alt.condition(hover, alt.value(1), alt.value(0)))
            .transform_filter(hover)
        )
        st.altair_chart(alt.layer(*layers).properties(height=420), width="stretch")

        scores = app_data.window_scores(wide, shown) if shown else pd.DataFrame()
        cov = app_data.window_coverage(wide)
        cap = (
            f"Each target half-hour is forecast once, by the run issued at "
            f"{issue_hour:02d}:00 UTC the day before (24-47.5 hours ahead)."
        )
        if cov is not None and show_band:
            cap += f" Interval coverage in this window: {100 * cov:.0f}% (target 80%)."
        st.caption(cap)
        if not scores.empty:
            st.dataframe(
                scores,
                hide_index=True,
                column_config={
                    "MAE (gCO2/kWh)": st.column_config.NumberColumn(format="%.1f"),
                    "bias (gCO2/kWh)": st.column_config.NumberColumn(format="%+.1f"),
                },
            )
        if "neso_stored_forecast" in shown:
            st.warning(
                "The NESO stored forecast is a short-lead nowcast (its error matches "
                "roughly 1-hour persistence), not a 24-48h forecast. It is shown for "
                "reference and is not a like-for-like comparison."
            )
        if "oracle_weather" in shown:
            st.warning(
                "LightGBM + observed weather uses the weather that actually happened at "
                "the target time. It is a leaky upper bound, not a deployable forecast."
            )

# --- accuracy by horizon --------------------------------------------------------------
with tab_horizon:
    a, b = st.columns([1, 3])
    metric_name = a.selectbox("Metric", list(METRICS))
    metric = METRICS[metric_name]
    avail = [m for m in MODELS if m in set(by_horizon["model"])]
    if metric == "skill_vs_seasonal_naive_day":
        avail = [m for m in avail if m != "neso_stored_forecast"]
    picked_models = b.multiselect(
        "Models", avail, default=[m for m in HORIZON_DEFAULT if m in avail], format_func=label
    )
    h = by_horizon[by_horizon["model"].isin(picked_models)].copy()
    h["label"] = h["model"].map(label)
    hover_h = alt.selection_point(
        fields=["horizon_h"], nearest=True, on="pointerover", empty=False, clear="pointerout"
    )
    base = alt.Chart(h).encode(
        x=alt.X(
            "horizon_h:Q", title="Forecast horizon (hours ahead)", scale=alt.Scale(domain=[24, 48])
        ),
        y=alt.Y(
            f"{metric}:Q",
            title=metric_name,
            scale=alt.Scale(zero=metric != "skill_vs_seasonal_naive_day"),
        ),
        color=alt.Color(
            "label:N",
            legend=alt.Legend(title=None, orient="bottom", labelLimit=0, columns=3),
            scale=alt.Scale(
                domain=[label(m) for m in picked_models], range=[colour(m) for m in picked_models]
            ),
        ),
    )
    horizon_chart = alt.layer(
        base.mark_line(strokeWidth=2).encode(
            strokeDash=alt.condition(
                alt.datum.model == "oracle_weather", alt.value([6, 4]), alt.value([1, 0])
            )
        ),
        base.mark_point(filled=True, size=50)
        .encode(
            opacity=alt.condition(hover_h, alt.value(1), alt.value(0)),
            tooltip=[
                alt.Tooltip("label:N", title="Model"),
                alt.Tooltip("horizon_h:Q", title="Hours ahead"),
                alt.Tooltip(f"{metric}:Q", title=metric_name, format=".2f"),
                alt.Tooltip("n:Q", title="Forecasts", format=","),
            ],
        )
        .add_params(hover_h),
    ).properties(height=420)
    st.altair_chart(horizon_chart, width="stretch")
    st.caption(
        "Every model is scored on the same forecasts. The weather-forecast model's error steps "
        "up from about 40 hours ahead: beyond that, only weather forecasts made three days "
        "before the target were available at the time the forecast was issued."
    )
    if "neso_stored_forecast" in picked_models:
        st.warning(
            "The NESO line is flat because the stored value is a single short-lead "
            "nowcast per period, not a forecast at each horizon."
        )
    table = h.pivot(index="horizon_h", columns="label", values=metric).reset_index()
    with st.expander("Table view"):
        st.dataframe(table, hide_index=True)

# --- how it works --------------------------------------------------------------
with tab_how:
    st.markdown(f"""
**Question.** How well can GB national grid carbon intensity be forecast 24-48 hours ahead,
at 30-minute resolution, compared with simple baselines?

**Pipeline.**
1. **Ingest** half-hourly actual intensity and generation mix from the Carbon Intensity API,
   and hourly weather from Open-Meteo for six GB sites (offshore and onshore wind, solar,
   London demand) into DuckDB. Re-runs fetch only missing periods.
2. **Feature engineering in SQL** (`sql/01-05`): staging, a DST-aware settlement-period calendar
   with UK bank holidays, window-function lags and rolling statistics, weather aligned to
   half-hours, and a training table with one row per (forecast origin, horizon).
3. **Model**: one LightGBM model with the horizon as a feature (direct multi-horizon),
   tuned on a time-based validation block before the test period.
4. **Backtest**: forecasts issued every 6 hours; the model is retrained at the start of each
   month on everything before it, then scored on that month.
5. **Intervals**: quantile LightGBM (10th / 90th percentile), then conformal calibration on the
   month before each fold.

**Leakage rules.** A feature is used only if it was published by the time the forecast is issued:
actual intensity and generation mix 60 minutes after each half-hour ends, and weather forecasts
8 hours after the time they were made. The "seasonal naive" baseline therefore uses the same time
2 days earlier (3 days beyond 46.5 hours ahead), because yesterday's value is not yet known.
A leak test rebuilds the features with all later data corrupted and checks nothing changes.

**Caveats.**
- The NESO forecast stored by the API is a short-lead nowcast, so it is not a fair comparison
  with 24-48h forecasts (MAE {overall.loc["neso_stored_forecast", "mae"]:.1f} gCO2/kWh here).
- "Observed weather" is a leaky upper bound; the deployable model uses weather *forecasts*,
  which are only archived from March 2024.
- National scope only; historical actuals are revised values, not the first published estimates.
- Interval coverage varies from month to month even after calibration.

Full tables are in `reports/results.md`; the code is in the repository.
""")
