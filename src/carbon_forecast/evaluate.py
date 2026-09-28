"""Forecast accuracy metrics, backtest report and figures.

python -m carbon_forecast.evaluate  -> reports/results.md, reports/figures/*.png,
                                       DuckDB tables backtest_metrics_by_horizon and
                                       backtest_metrics_overall (read by the app)
"""

import argparse
from datetime import UTC, datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from carbon_forecast.config import REPORTS_DIR, ROOT, load_settings, resolve  # noqa: E402
from carbon_forecast.db import connect  # noqa: E402
from carbon_forecast.reporting import df_to_markdown  # noqa: E402

TARGET = "y_actual_gco2"
REFERENCE = "seasonal_naive_day"  # skill scores are relative to this baseline

# --- metrics -----------------------------------------------------------------


def mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(p - y)))


def rmse(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.sqrt(np.mean((p - y) ** 2)))


def mape(y: np.ndarray, p: np.ndarray) -> float:
    """Mean absolute percentage error in %, over rows with a non-zero actual."""
    nz = y != 0
    return float(np.mean(np.abs((p[nz] - y[nz]) / y[nz])) * 100)


def skill(model_mae: float, reference_mae: float) -> float:
    """1 - MAE_model / MAE_reference: > 0 means better than the reference."""
    return 1.0 - model_mae / reference_mae


def score(y, p) -> dict[str, float]:
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    ok = ~(np.isnan(y) | np.isnan(p))
    y, p = y[ok], p[ok]
    return {"n": int(ok.sum()), "mae": mae(y, p), "rmse": rmse(y, p), "mape": mape(y, p)}


def score_table(df: pd.DataFrame, target: str, prediction_cols: list[str]) -> pd.DataFrame:
    """Metrics for several prediction columns, on rows where ALL of them exist,
    so every model is scored on exactly the same targets."""
    common = df.dropna(subset=[target, *prediction_cols])
    rows = {c: score(common[target], common[c]) for c in prediction_cols}
    return pd.DataFrame(rows).T


# --- models, labels and colours ------------------------------------------------

# Every model keeps one colour in every figure (reference palette, fixed slot order).
MODELS = {
    # column: (label, colour)
    "weather_forecast": ("LightGBM + weather forecast", "#2a78d6"),
    "no_weather": ("LightGBM, no weather", "#eb6834"),
    "seasonal_naive_day": ("Seasonal naive (latest day)", "#1baf7a"),
    "seasonal_naive_week": ("Seasonal naive (week)", "#eda100"),
    "persistence": ("Persistence", "#e87ba4"),
    "no_weather_short": ("LightGBM, no weather, short history", "#008300"),
    "oracle_weather": ("LightGBM + observed weather (leaky oracle)", "#4a3aa7"),
    "neso_stored_forecast": ("NESO stored forecast (short-lead nowcast)", "#898781"),
}
FIGURE_MODELS = [
    "weather_forecast",
    "no_weather",
    "seasonal_naive_day",
    "seasonal_naive_week",
    "persistence",
    "oracle_weather",
]
INK, INK_2, MUTED, GRID, AXIS, SURFACE = (
    "#0b0b0b",
    "#52514e",
    "#898781",
    "#e1e0d9",
    "#c3c2b7",
    "#fcfcfb",
)
SEASONS = {
    12: "Winter (DJF)",
    1: "Winter (DJF)",
    2: "Winter (DJF)",
    3: "Spring (MAM)",
    4: "Spring (MAM)",
    5: "Spring (MAM)",
    6: "Summer (JJA)",
    7: "Summer (JJA)",
    8: "Summer (JJA)",
    9: "Autumn (SON)",
    10: "Autumn (SON)",
    11: "Autumn (SON)",
}
SEASON_ORDER = ["Winter (DJF)", "Spring (MAM)", "Summer (JJA)", "Autumn (SON)"]
TOD_ORDER = ["00-06", "06-12", "12-18", "18-24"]
WIND_ORDER = ["low", "medium", "high"]


def _style():
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "sans-serif",
            "font.size": 10,
            "text.color": INK,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": INK_2,
            "axes.titlecolor": INK,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "grid.linestyle": "-",
            "axes.axisbelow": True,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelcolor": INK_2,
            "ytick.labelcolor": INK_2,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "lines.linewidth": 2,
            "lines.solid_capstyle": "round",
            "figure.dpi": 150,
        }
    )


def _line_kw(model: str) -> dict:
    label, colour = MODELS[model]
    return {
        "label": label,
        "color": colour,
        "linewidth": 2,
        "linestyle": "--" if model == "oracle_weather" else "-",
    }


# --- analysis ----------------------------------------------------------------


def add_context(df: pd.DataFrame) -> tuple[pd.DataFrame, tuple[float, float]]:
    df = df.copy()
    df["season"] = df["target_month"].map(SEASONS)
    df["time_of_day"] = pd.cut(
        df["target_local_hour"], [0, 6, 12, 18, 24], right=False, labels=TOD_ORDER
    ).astype(str)
    # Wind regime: terciles of OUTTURN wind share over distinct target periods.
    # Uses actuals, which is fine for slicing errors after the fact.
    per_target = df.drop_duplicates("target_time_utc")["target_actual_wind_pct"].dropna()
    lo, hi = per_target.quantile([1 / 3, 2 / 3])
    df["wind_regime"] = np.select(
        [df["target_actual_wind_pct"] < lo, df["target_actual_wind_pct"] < hi],
        ["low", "medium"],
        default="high",
    )
    df.loc[df["target_actual_wind_pct"].isna(), "wind_regime"] = None
    return df, (float(lo), float(hi))


def overall(common: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    t = score_table(common, TARGET, models)
    t["n"] = t["n"].astype(int)
    t["skill_vs_" + REFERENCE] = [skill(v, t.loc[REFERENCE, "mae"]) for v in t["mae"]]
    t.insert(0, "model", [MODELS[m][0] for m in t.index])
    return t


def by_group(common: pd.DataFrame, col: str, models: list[str], order=None) -> pd.DataFrame:
    rows = []
    for key, g in common.groupby(col, sort=True):
        ref = mae(g[TARGET].to_numpy(), g[REFERENCE].to_numpy())
        for mdl in models:
            s = score(g[TARGET], g[mdl])
            rows.append(
                {col: key, "model": mdl, **s, "skill_vs_" + REFERENCE: skill(s["mae"], ref)}
            )
    out = pd.DataFrame(rows)
    if order is not None:
        out[col] = pd.Categorical(out[col], order, ordered=True)
        out = out.sort_values([col, "model"])
    return out


def wide(long: pd.DataFrame, col: str, metric: str, models: list[str]) -> pd.DataFrame:
    w = long.pivot(index=col, columns="model", values=metric)[models]
    w.columns = [MODELS[m][0] for m in models]
    return w.reset_index()


INTERVALS = {"raw quantile": "p", "conformal (CQR)": "cp"}


def coverage_table(common: pd.DataFrame, kind: str = "p") -> pd.DataFrame:
    """Coverage of the weather-forecast 10-90% band; kind "p" = raw quantile
    models, "cp" = conformalized."""
    lo, hi = common[f"weather_forecast_{kind}10"], common[f"weather_forecast_{kind}90"]
    y = common[TARGET]
    buckets = pd.cut(
        common["horizon_h"],
        [24, 30, 36, 42, 48.01],
        right=False,
        labels=["24-29.5h", "30-35.5h", "36-41.5h", "42-48h"],
    )
    rows = []
    for name, mask in [
        ("all horizons", slice(None)),
        *[(b, buckets == b) for b in buckets.cat.categories],
    ]:
        yy, ll, hh = y[mask], lo[mask], hi[mask]
        rows.append(
            {
                "horizons": name,
                "n": len(yy),
                "coverage_%": 100 * ((yy >= ll) & (yy <= hh)).mean(),
                "below_p10_%": 100 * (yy < ll).mean(),
                "above_p90_%": 100 * (yy > hh).mean(),
                "mean_width": (hh - ll).mean(),
            }
        )
    return pd.DataFrame(rows)


def pick_sample_week(df: pd.DataFrame) -> pd.DataFrame:
    """Continuous day-ahead view: origins at 12:00 UTC with horizons 24-47.5h cover
    every target exactly once. The week shown is the complete ISO week whose
    weather-forecast MAE is closest to the median weekly MAE (a typical week,
    chosen by rule, not by eye)."""
    daily = df[(df["origin_time_utc"].dt.hour == 12) & (df["horizon_h"] < 48)].copy()
    daily["week"] = daily["target_time_utc"].dt.to_period("W-SUN")
    stats = daily.groupby("week").agg(
        n=(TARGET, "size"),
        mae=("weather_forecast", lambda s: np.nan),
    )
    for wk, g in daily.groupby("week"):
        stats.loc[wk, "mae"] = mae(g[TARGET].to_numpy(), g["weather_forecast"].to_numpy())
    full = stats[stats["n"] == 7 * 48]
    week = (full["mae"] - full["mae"].median()).abs().idxmin()
    return daily[daily["week"] == week].sort_values("target_time_utc")


# --- figures -----------------------------------------------------------------


def fig_mae_by_horizon(h: pd.DataFrame, path):
    fig, ax = plt.subplots(figsize=(8, 4.6))
    for mdl in FIGURE_MODELS:
        g = h[h["model"] == mdl]
        ax.plot(g["horizon_h"], g["mae"], **_line_kw(mdl))
    ax.set_xlabel("Forecast horizon (hours ahead)")
    ax.set_ylabel("MAE (gCO2/kWh)")
    ax.set_title("Error by forecast horizon, 12-month rolling-origin backtest")
    ax.set_xlim(24, 48)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def fig_sample_week(week: pd.DataFrame, path):
    fig, ax = plt.subplots(figsize=(10, 4.6))
    t = week["target_time_utc"]
    ax.fill_between(
        t,
        week["weather_forecast_cp10"],
        week["weather_forecast_cp90"],
        color=MODELS["weather_forecast"][1],
        alpha=0.12,
        linewidth=0,
        label="LightGBM + weather forecast, 10-90% interval (conformal)",
    )
    ax.plot(t, week[TARGET], color=INK, linewidth=2, label="Actual")
    for mdl in ("weather_forecast", "no_weather", "seasonal_naive_day"):
        ax.plot(t, week[mdl], **_line_kw(mdl))
    first, last = t.iloc[0], t.iloc[-1]
    ax.set_title(
        f"Day-ahead forecasts vs actual, {first:%d %b} to {last:%d %b %Y} "
        "(origins 12:00 UTC, 24-47.5h ahead)"
    )
    ax.set_ylabel("Carbon intensity (gCO2/kWh)")
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%a %d"))
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def fig_importance(imp: pd.DataFrame, model: str, path, top: int = 15):
    g = imp[imp["model"] == model].nlargest(top, "mean_abs_shap").iloc[::-1]
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.barh(g["feature"], g["mean_abs_shap"], height=0.6, color=MODELS[model][1])
    ax.set_xlabel("Mean |SHAP value| (gCO2/kWh)")
    fold = pd.Timestamp(g["fold_start_utc"].iloc[0])
    ax.set_title(
        f"What drives the {MODELS[model][0]} model\n"
        f"(TreeSHAP on the final fold, origins from {fold:%b %Y})"
    )
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def fig_residuals(common: pd.DataFrame, path):
    fig, ax = plt.subplots(figsize=(8, 4.4))
    bins = np.arange(-160, 161, 5)
    for mdl in ("weather_forecast", "no_weather", "seasonal_naive_day"):
        err = (common[mdl] - common[TARGET]).clip(-160, 160)
        ax.hist(
            err,
            bins=bins,
            density=True,
            histtype="step",
            linewidth=2,
            color=MODELS[mdl][1],
            label=f"{MODELS[mdl][0]} (median {err.median():+.1f})",
        )
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.set_xlabel("Forecast error, predicted minus actual (gCO2/kWh; clipped at +/-160)")
    ax.set_ylabel("Density")
    ax.set_title("Residual distribution, all horizons")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def fig_grouped_bars(long: pd.DataFrame, col: str, order: list[str], title: str, xlabel: str, path):
    models = [m for m in FIGURE_MODELS if m != "persistence"]
    x = np.arange(len(order))
    width = 0.8 / len(models)
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    for i, mdl in enumerate(models):
        g = long[long["model"] == mdl].set_index(col).reindex(order)
        ax.bar(
            x + (i - (len(models) - 1) / 2) * width,
            g["mae"],
            width=width * 0.9,
            color=MODELS[mdl][1],
            label=MODELS[mdl][0],
        )
    ax.set_xticks(x, order)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("MAE (gCO2/kWh)")
    ax.set_title(title)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def fig_by_hour(common: pd.DataFrame, path):
    fig, ax = plt.subplots(figsize=(8, 4.4))
    hours = np.floor(common["target_local_hour"]).astype(int)
    for mdl in FIGURE_MODELS:
        m = (common[mdl] - common[TARGET]).abs().groupby(hours).mean()
        ax.plot(m.index, m.values, **_line_kw(mdl))
    ax.set_xlabel("Target time of day (UK local hour)")
    ax.set_ylabel("MAE (gCO2/kWh)")
    ax.set_title("Error by time of day")
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlim(0, 23)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# --- NESO lead-time check --------------------------------------------------------

# Persistence lags (in half-hours) to compare the stored NESO forecast against.
NESO_CHECK_LAGS = {"30 min": 1, "1 h": 2, "2 h": 4, "6 h": 12, "24 h": 48, "48 h": 96}


def neso_lead_check(con, start: datetime, end: datetime) -> pd.DataFrame:
    """MAE of the NESO stored forecast next to persistence at increasing lags, on the
    same half-hours. If the stored forecast were issued 24-48h ahead, its error could
    not match persistence at a lag of an hour or two."""
    lags = ", ".join(f"lag(i.actual_gco2, {n}) OVER w AS p{n}" for n in NESO_CHECK_LAGS.values())
    maes = ", ".join(f"avg(abs(p{n} - y)) AS p{n}" for n in NESO_CHECK_LAGS.values())
    not_null = " AND ".join(f"p{n} IS NOT NULL" for n in NESO_CHECK_LAGS.values())
    row = (
        con.execute(
            f"""
        WITH s AS (
            SELECT c.period_start_utc AS t, i.actual_gco2 AS y, i.forecast_gco2 AS neso, {lags}
            FROM calendar c
            LEFT JOIN stg_intensity i USING (period_start_utc)
            WINDOW w AS (ORDER BY c.period_start_utc)
        )
        SELECT count(*) AS n, avg(abs(neso - y)) AS neso, {maes}
        FROM s
        WHERE t >= $start AND t <= $end AND y IS NOT NULL AND neso IS NOT NULL AND {not_null}
        """,
            {"start": start, "end": end},
        )
        .df()
        .iloc[0]
    )
    rows = [{"predictor": "NESO stored forecast", "mae": row["neso"], "n": int(row["n"])}]
    rows += [
        {"predictor": f"Persistence ({name} lag)", "mae": row[f"p{n}"], "n": int(row["n"])}
        for name, n in NESO_CHECK_LAGS.items()
    ]
    return pd.DataFrame(rows)


def wf_mae_floor(h: pd.DataFrame) -> float:
    """Lowest MAE of any non-NESO model at any horizon."""
    return float(h[h["model"] != "neso_stored_forecast"]["mae"].min())


# --- README ----------------------------------------------------------------------


def replace_block(text: str, name: str, content: str) -> str:
    """Replace the text between <!-- name:start --> and <!-- name:end -->."""
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    i, j = text.find(start), text.find(end)
    if i == -1 or j == -1 or j < i:
        raise ValueError(f"markers for {name!r} not found")
    return text[: i + len(start)] + "\n" + content.strip() + "\n" + text[j:]


# --- report --------------------------------------------------------------------


def build(con, settings) -> str:
    df = con.execute("SELECT * FROM backtest_results").df()
    imp = con.execute("SELECT * FROM backtest_feature_importance").df()
    df, (wind_lo, wind_hi) = add_context(df)
    all_models = [m for m in MODELS if m in df.columns]
    fair = [m for m in all_models if m != "neso_stored_forecast"]
    interval_cols = [f"weather_forecast_{k}{q}" for k in INTERVALS.values() for q in (10, 90)]
    common = df.dropna(subset=[TARGET, *all_models, *interval_cols, "wind_regime"])

    # Tables
    tab_overall = overall(common, all_models)
    h = by_group(common, "horizon_h", all_models)
    monthly = by_group(common, "fold_start_utc", fair)
    season = by_group(common, "season", fair, SEASON_ORDER)
    tod = by_group(common, "time_of_day", fair, TOD_ORDER)
    wind = by_group(common, "wind_regime", fair, WIND_ORDER)
    cov = pd.concat(
        [coverage_table(common, k).assign(interval=name) for name, k in INTERVALS.items()]
    )
    cov = cov[["interval", *[c for c in cov.columns if c != "interval"]]]
    calib = con.execute("SELECT * FROM backtest_interval_calibration ORDER BY 1").df()
    fold_cov = []
    for fold, g in common.groupby("fold_start_utc"):
        y = g[TARGET]
        row = {"fold_start_utc": fold}
        for k in INTERVALS.values():
            inside = (y >= g[f"weather_forecast_{k}10"]) & (y <= g[f"weather_forecast_{k}90"])
            row[f"test_coverage_%_{k}"] = 100 * inside.mean()
        fold_cov.append(row)
    calib = calib.merge(pd.DataFrame(fold_cov), on="fold_start_utc")
    calib_tab = pd.DataFrame(
        {
            "fold": calib["fold_start_utc"].dt.strftime("%Y-%m"),
            "calibration_window": calib["calibration_start_utc"].dt.strftime("%Y-%m"),
            "n_calibration": calib["n_calibration"],
            "calibration_raw_coverage_%": 100 * calib["calibration_raw_coverage"],
            "adjustment_gco2": calib["conformal_adjustment"],
            "test_coverage_raw_%": calib["test_coverage_%_p"],
            "test_coverage_conformal_%": calib["test_coverage_%_cp"],
        }
    )
    week = pick_sample_week(df.dropna(subset=[TARGET, "weather_forecast", *interval_cols]))
    test_start = datetime.combine(settings["evaluation"]["test_start"], datetime.min.time())
    neso = neso_lead_check(con, test_start, df["target_time_utc"].max())
    neso_mae = neso.loc[0, "mae"]
    persist = neso.iloc[1:].reset_index(drop=True)
    below = persist[persist["mae"] <= neso_mae]["predictor"].tolist()
    above = persist[persist["mae"] > neso_mae]["predictor"].tolist()
    neso_sentence = (
        f"The stored NESO forecast (MAE {neso_mae:.1f}) is "
        + (f"worse than {below[-1].lower()} " if below else "")
        + ("but " if below and above else "")
        + (f"better than {above[0].lower()}" if above else "")
        + ". A forecast issued 24-48 hours ahead could not match persistence at such short "
        "lags: the lowest MAE of any 24-48h model at any horizon in this backtest is "
        f"{wf_mae_floor(h):.1f}. The "
        "stored value is therefore a short-lead nowcast, and comparing it with the 24-48h "
        "models is not like-for-like."
    )

    h.assign(model_label=h["model"].map(lambda m: MODELS[m][0])).to_csv(
        REPORTS_DIR / "metrics_by_horizon.csv", index=False, float_format="%.4f"
    )
    # The app reads these tables, so its numbers always match this report.
    overall_df = tab_overall.rename(columns={"model": "model_label"}).rename_axis("model")
    for name, frame in (
        ("backtest_metrics_by_horizon", h),
        ("backtest_metrics_overall", overall_df.reset_index()),
        ("backtest_interval_coverage", cov),
    ):
        con.register("tmp_df", frame)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM tmp_df")
        con.unregister("tmp_df")

    # Figures
    figs = REPORTS_DIR / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    _style()
    fig_mae_by_horizon(h, figs / "mae_by_horizon.png")
    fig_sample_week(week, figs / "sample_week.png")
    fig_importance(imp, "weather_forecast", figs / "feature_importance_weather_forecast.png")
    fig_importance(imp, "no_weather", figs / "feature_importance_no_weather.png")
    fig_residuals(common, figs / "residuals.png")
    fig_grouped_bars(
        season,
        "season",
        SEASON_ORDER,
        "Error by season",
        "Target season",
        figs / "error_by_season.png",
    )
    fig_grouped_bars(
        wind,
        "wind_regime",
        WIND_ORDER,
        f"Error by wind conditions (outturn wind share terciles: "
        f"<{wind_lo:.0f}%, {wind_lo:.0f}-{wind_hi:.0f}%, >{wind_hi:.0f}%)",
        "Wind regime at the target time",
        figs / "error_by_wind.png",
    )
    fig_by_hour(common, figs / "error_by_hour.png")

    # Markdown
    folds = sorted(df["fold_start_utc"].dropna().unique())
    wf, nw = (tab_overall.loc[m] for m in ("weather_forecast", "no_weather"))
    wins = monthly.pivot(index="fold_start_utc", columns="model", values="mae")
    wf_months = int((wins["weather_forecast"] < wins[REFERENCE]).sum())
    nw_months = int((wins["no_weather"] < wins[REFERENCE]).sum())
    hsel = h[h["horizon_h"].isin([24, 30, 36, 42, 48])]
    sk = "skill_vs_" + REFERENCE
    top_imp = imp[imp["model"] == "weather_forecast"].nlargest(10, "mean_abs_shap")[
        ["feature", "mean_abs_shap", "gain"]
    ]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    L = [
        "# Backtest results",
        "",
        f"Generated {now} by `python -m carbon_forecast.evaluate` from the `backtest_results` "
        "table written by `python -m carbon_forecast.backtest`. Every number below comes from "
        "that run.",
        "",
        "## Set-up",
        "",
        f"- Rolling-origin backtest over origins {pd.Timestamp(folds[0]):%Y-%m-%d} to "
        f"{df['origin_time_utc'].max():%Y-%m-%d %H:%M} UTC: {len(folds)} monthly folds, "
        "expanding training window, every model retrained at the start of each month on all "
        "rows whose target precedes that month.",
        "- Forecast origins every 6 hours (00/06/12/18 UTC); 49 horizons from 24h to 48h ahead "
        "at 30-minute resolution.",
        f"- All models are scored on the same {len(common):,} (origin, horizon) rows: those "
        "where every model, the NESO reference and the interval forecasts exist.",
        "- Hyperparameters were tuned once on the six months before the test period "
        "(`reports/tuning.md`) and not revisited.",
        "- Skill = 1 - MAE / MAE of the seasonal naive (latest published day) baseline.",
        "",
        "**Reading the table:** `LightGBM + observed weather` uses outturn weather at the target "
        "time and is a leaky upper bound, not a deployable model. The NESO stored forecast is a "
        "short-lead nowcast (its error matches ~1h persistence), so it is not a like-for-like "
        "comparison with 24-48h forecasts and is shown for reference only.",
        "",
        "## Overall",
        "",
        df_to_markdown(tab_overall.reset_index(drop=True), ".3f"),
        "",
        f"The deployable weather-forecast model has MAE {wf['mae']:.1f} gCO2/kWh "
        f"(skill {wf[sk]:.2f}); without weather, MAE {nw['mae']:.1f} (skill {nw[sk]:.2f}). "
        f"Month by month, the weather-forecast model beats the seasonal naive baseline in "
        f"{wf_months} of {len(wins)} folds and the no-weather model in {nw_months} of {len(wins)}.",
        "",
        "## Is the NESO comparison like-for-like?",
        "",
        "The Carbon Intensity API keeps one stored forecast per half-hour, and its lead time is "
        "not documented. Its error next to persistence at increasing lags, on the same "
        "half-hours of the test period:",
        "",
        df_to_markdown(neso, ".2f"),
        "",
        neso_sentence,
        "",
        "## By horizon",
        "",
        "MAE (gCO2/kWh) at selected horizons; all 49 horizons are in "
        "`reports/metrics_by_horizon.csv` and the `backtest_metrics_by_horizon` table.",
        "",
        df_to_markdown(wide(hsel, "horizon_h", "mae", all_models), ".2f"),
        "",
        "Skill vs seasonal naive (latest published day):",
        "",
        df_to_markdown(wide(hsel, "horizon_h", sk, fair), ".3f"),
        "",
        "RMSE (gCO2/kWh):",
        "",
        df_to_markdown(wide(hsel, "horizon_h", "rmse", all_models), ".2f"),
        "",
        "MAPE (%):",
        "",
        df_to_markdown(wide(hsel, "horizon_h", "mape", all_models), ".1f"),
        "",
        "![Error by horizon](figures/mae_by_horizon.png)",
        "",
        "## By month (fold)",
        "",
        df_to_markdown(
            wide(
                monthly.assign(fold_start_utc=monthly["fold_start_utc"].dt.strftime("%Y-%m")),
                "fold_start_utc",
                "mae",
                fair,
            ),
            ".2f",
        ),
        "",
        "## Error breakdowns (MAE, gCO2/kWh)",
        "",
        "### By season",
        "",
        df_to_markdown(wide(season, "season", "mae", fair), ".2f"),
        "",
        "![Error by season](figures/error_by_season.png)",
        "",
        "### By time of day (UK local hour of the target)",
        "",
        df_to_markdown(wide(tod, "time_of_day", "mae", fair), ".2f"),
        "",
        "![Error by time of day](figures/error_by_hour.png)",
        "",
        "### By wind conditions",
        "",
        f"Terciles of outturn wind share at the target time: low < {wind_lo:.1f}%, "
        f"medium {wind_lo:.1f}-{wind_hi:.1f}%, high > {wind_hi:.1f}%. Outturn is used only to "
        "slice errors after the fact, never as a model input.",
        "",
        df_to_markdown(wide(wind, "wind_regime", "mae", fair), ".2f"),
        "",
        "![Error by wind conditions](figures/error_by_wind.png)",
        "",
        "## Prediction intervals (weather-forecast model)",
        "",
        "A well-calibrated 10-90% interval covers 80% of actuals. **Raw quantile**: LightGBM "
        "at the 10th and 90th percentiles, same features and settings as the point model, "
        "trained on targets up to one month before each fold. **Conformal (CQR)**: the raw band "
        "widened on both sides by the conformity-score quantile measured on that held-out "
        "month (Romano et al., 2019), which lies strictly before the fold, so no test data is "
        "used. CQR's coverage guarantee assumes exchangeable data; time series are not, so "
        "coverage here is measured, not guaranteed.",
        "",
        df_to_markdown(cov, ".1f"),
        "",
        "Per fold: calibration window, the adjustment it produced, and the coverage achieved "
        "on the fold's test month.",
        "",
        df_to_markdown(calib_tab, ".1f"),
        "",
        "## Feature attribution (weather-forecast model, final fold)",
        "",
        df_to_markdown(top_imp.reset_index(drop=True), ".2f"),
        "",
        "![Feature importance](figures/feature_importance_weather_forecast.png)",
        "",
        "## Other figures",
        "",
        "- Sample week (typical week by rule: weekly MAE closest to the median). The seasonal "
        "naive line jumps at 11:00 UTC each day because for horizons of 47h and more it must "
        "fall back to 3 days earlier: ![Sample week](figures/sample_week.png)",
        "- Residual distribution: ![Residuals](figures/residuals.png)",
        "- No-weather model attribution: "
        "![No-weather feature importance](figures/feature_importance_no_weather.png)",
        "",
    ]
    readme = readme_blocks(
        tab_overall, h, cov, neso, neso_sentence, folds, df, wf_months, len(wins)
    )
    return "\n".join(L), readme


def readme_blocks(tab_overall, h, cov, neso, neso_sentence, folds, df, wf_months, n_months):
    """Generated README sections, so its numbers always come from this run."""
    sk = "skill_vs_" + REFERENCE
    wf, sn = tab_overall.loc["weather_forecast"], tab_overall.loc[REFERENCE]
    conformal = cov[(cov["interval"] == "conformal (CQR)") & (cov["horizons"] == "all horizons")]
    raw = cov[(cov["interval"] == "raw quantile") & (cov["horizons"] == "all horizons")]
    first, last = pd.Timestamp(folds[0]), df["target_time_utc"].max()
    headline = (
        f"Over a 12-month rolling-origin backtest ({first:%b %Y} to {last:%b %Y}, "
        f"{int(wf['n']):,} forecasts, monthly retraining), LightGBM with leakage-free weather "
        f"forecasts has an MAE of **{wf['mae']:.1f} gCO2/kWh** across 24-48 hour horizons, "
        f"{100 * wf[sk]:.0f}% lower than a seasonal naive baseline ({sn['mae']:.1f}), and beats "
        f"that baseline in {wf_months} of {n_months} months. Its conformally calibrated 10-90% "
        f"intervals cover {conformal['coverage_%'].iloc[0]:.1f}% of outcomes (target 80%)."
    )
    t = tab_overall[["model", "mae", "rmse", "mape", sk]].rename(
        columns={
            "model": "Model",
            "mae": "MAE",
            "rmse": "RMSE",
            "mape": "MAPE %",
            sk: "Skill",
        }
    )
    key = ["weather_forecast", "no_weather", REFERENCE, "oracle_weather"]
    hsel = h[h["horizon_h"].isin([24, 30, 36, 42, 48]) & h["model"].isin(key)]
    results = "\n".join(
        [
            f"All models are scored on the same {int(wf['n']):,} forecasts (origins every 6 hours, "
            "49 horizons from 24h to 48h). Errors in gCO2/kWh; skill = 1 - MAE / MAE of the "
            "seasonal naive baseline.",
            "",
            df_to_markdown(t.reset_index(drop=True), ".2f"),
            "",
            "*Observed weather* is a leaky upper bound (it uses the weather that actually "
            "happened). The *NESO stored forecast* is a short-lead nowcast, not a 24-48h "
            "forecast; see [Limitations](#limitations--honest-caveats).",
            "",
            "MAE by horizon:",
            "",
            df_to_markdown(wide(hsel, "horizon_h", "mae", key), ".1f"),
            "",
            f"Prediction intervals (10-90%): raw quantile LightGBM covers "
            f"{raw['coverage_%'].iloc[0]:.1f}% of actuals; after conformal calibration, "
            f"{conformal['coverage_%'].iloc[0]:.1f}% (mean width "
            f"{raw['mean_width'].iloc[0]:.0f} -> {conformal['mean_width'].iloc[0]:.0f} gCO2/kWh).",
        ]
    )
    neso_block = "\n".join([df_to_markdown(neso, ".1f"), "", neso_sentence])
    return {"headline": headline, "results": results, "neso": neso_block}


def main(argv: list[str] | None = None) -> None:
    settings = load_settings()
    p = argparse.ArgumentParser(prog="python -m carbon_forecast.evaluate")
    p.add_argument("--db", default=settings["db_path"])
    args = p.parse_args(argv)
    with connect(resolve(args.db)) as con:
        report, readme = build(con, settings)
    out = REPORTS_DIR / "results.md"
    out.write_text(report)
    print(report)
    print(f"written to {out}")
    readme_path = ROOT / "README.md"
    text = readme_path.read_text()
    if "<!-- results:start -->" in text:
        for name, content in readme.items():
            text = replace_block(text, name, content)
        readme_path.write_text(text)
        print(f"updated generated sections in {readme_path}")


if __name__ == "__main__":
    main()
