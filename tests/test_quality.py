from datetime import date

from carbon_forecast.config import load_settings
from carbon_forecast.quality import build_report


def test_report_flags_gaps_and_dst_days(con):
    con.execute("""
        INSERT INTO raw_intensity
        SELECT ts, ts + INTERVAL 30 MINUTE, 150, 140, 'moderate', now()::TIMESTAMP
        FROM (SELECT unnest(generate_series(TIMESTAMP '2019-10-25', TIMESTAMP '2019-10-30 23:30',
                                            INTERVAL 30 MINUTE)) AS ts)
        WHERE ts NOT BETWEEN TIMESTAMP '2019-10-29 10:00' AND TIMESTAMP '2019-10-29 11:00'
    """)
    con.execute(
        "UPDATE raw_intensity SET forecast_gco2 = 9899 "
        "WHERE period_start_utc = TIMESTAMP '2019-10-26 12:00'"
    )
    settings = load_settings()
    settings["start_date"] = date(2019, 10, 25)
    report = build_report(con, settings)

    assert "| intensity | 285 |" in report  # 6 days * 48 - 3 missing
    assert "| 2019-10-29 10:00:00 | 2019-10-29 11:00:00 | 3 |" in report
    assert "| 2019-10-27 | 50 | 50 | yes |" in report
    # The day with the hole is the only calendar mismatch.
    assert "Days whose period count differs from the calendar: 1" in report
    assert "| 2019-10-29 | 45 | 48 |" in report
    assert "Suspect intensity values (> 1,000 or exactly 0): 1" in report
    assert "| 2019-10-26 12:00:00 | 9,899 | 140 | forecast > 1000 |" in report
