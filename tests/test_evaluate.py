from datetime import datetime

import pytest

from carbon_forecast.db import connect
from carbon_forecast.evaluate import neso_lead_check, replace_block


def test_replace_block_only_touches_the_marked_section():
    text = "intro\n<!-- a:start -->\nold\n<!-- a:end -->\noutro"
    out = replace_block(text, "a", "new\nlines")
    assert out == "intro\n<!-- a:start -->\nnew\nlines\n<!-- a:end -->\noutro"
    assert replace_block(out, "a", "new\nlines") == out  # idempotent
    with pytest.raises(ValueError):
        replace_block(text, "missing", "x")


def test_neso_lead_check_against_persistence():
    con = connect()
    # A linear ramp: persistence at lag k half-hours is off by exactly 2k; the
    # "NESO" forecast is off by 3, so it sits between the 30-min and 1-h lags.
    con.execute("""
        CREATE TABLE calendar AS
        SELECT unnest(generate_series(TIMESTAMP '2025-01-01', TIMESTAMP '2025-01-10',
                                      INTERVAL 30 MINUTE)) AS period_start_utc;
        CREATE TABLE stg_intensity AS
        SELECT period_start_utc,
               (row_number() OVER (ORDER BY period_start_utc) * 2)::DOUBLE AS actual_gco2,
               (row_number() OVER (ORDER BY period_start_utc) * 2 + 3)::DOUBLE AS forecast_gco2
        FROM calendar;
    """)
    t = neso_lead_check(con, datetime(2025, 1, 5), datetime(2025, 1, 9)).set_index("predictor")
    assert t.loc["NESO stored forecast", "mae"] == pytest.approx(3.0)
    assert t.loc["Persistence (30 min lag)", "mae"] == pytest.approx(2.0)
    assert t.loc["Persistence (1 h lag)", "mae"] == pytest.approx(4.0)
    assert t.loc["Persistence (48 h lag)", "mae"] == pytest.approx(192.0)
    assert t["n"].nunique() == 1
