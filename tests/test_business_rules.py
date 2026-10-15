"""Focused, database-free tests for the deterministic business-rule helpers."""
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.main import (
    attendance_date_for,
    compute_late_minutes,
    compute_overtime,
    work_hours,
    parse_epoch_ms,
    weekday_count,
    round2,
    round4,
)

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))


def ist_dt(day, hh, mm, ss=0):
    return datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=IST).astimezone(UTC)


def test_late_grace_boundary_and_flooring():
    d = date(2026, 7, 6)
    assert compute_late_minutes(ist_dt(d, 9, 40, 0), "09:30", d) == 0
    assert compute_late_minutes(ist_dt(d, 9, 40, 1), "09:30", d) == 10
    assert compute_late_minutes(ist_dt(d, 10, 15, 59), "09:30", d) == 45


def test_overnight_attendance_date_and_overtime():
    d = date(2026, 7, 6)
    early_morning = ist_dt(date(2026, 7, 7), 2, 0)
    assert attendance_date_for(early_morning, "22:00", "06:00") == d
    assert compute_overtime(ist_dt(date(2026, 7, 7), 6, 29), "22:00", "06:00", d) == 0
    assert compute_overtime(ist_dt(date(2026, 7, 7), 6, 30), "22:00", "06:00", d) == 30


def test_work_hours_uses_half_up_rounding():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert work_hours(start, start + timedelta(seconds=3600 * 1.125)) == 1.13
    assert work_hours(start, None) is None


def test_epoch_timestamp_rejects_seconds_float_and_string():
    for bad in (1_783_312_500, 1_783_312_500_000.0, "1783312500000", 9_999_999_999_999):
        with pytest.raises(HTTPException) as exc:
            parse_epoch_ms(bad)
        assert exc.value.status_code == 422


def test_weekday_count_and_half_up_report_rounding():
    assert weekday_count(date(2026, 7, 6), date(2026, 7, 12)) == 5
    assert round2(Decimal("1.125")) == 1.13
    assert round4(Decimal("1.23445")) == 1.2345
