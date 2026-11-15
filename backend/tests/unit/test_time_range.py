from datetime import UTC, datetime, timedelta, timezone

import pytest

from tutor_calendar.domain.scheduling import TimeRange


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 17, hour, minute, tzinfo=UTC)


def test_rejects_naive_datetimes() -> None:
    naive = datetime(2026, 11, 17, 10, 0)  # noqa: DTZ001 - the point of the test
    with pytest.raises(ValueError, match="timezone-aware"):
        TimeRange(naive, utc(11))


def test_rejects_empty_and_reversed_ranges() -> None:
    with pytest.raises(ValueError, match="before"):
        TimeRange(utc(10), utc(10))
    with pytest.raises(ValueError, match="before"):
        TimeRange(utc(11), utc(10))


def test_normalises_to_utc_so_equal_instants_are_equal_ranges() -> None:
    warsaw_winter = timezone(timedelta(hours=1))
    local = TimeRange(
        datetime(2026, 11, 17, 11, 0, tzinfo=warsaw_winter),
        datetime(2026, 11, 17, 12, 0, tzinfo=warsaw_winter),
    )
    assert local == TimeRange(utc(10), utc(11))
    assert local.start.tzinfo is UTC


def test_touching_ranges_do_not_overlap() -> None:
    assert not TimeRange(utc(10), utc(11)).overlaps(TimeRange(utc(11), utc(12)))


def test_overlap_is_symmetric() -> None:
    first = TimeRange(utc(10), utc(11, 30))
    second = TimeRange(utc(11), utc(12))
    assert first.overlaps(second)
    assert second.overlaps(first)


def test_contains() -> None:
    outer = TimeRange(utc(10), utc(12))
    assert outer.contains(TimeRange(utc(10), utc(12)))
    assert outer.contains(TimeRange(utc(10, 30), utc(11)))
    assert not outer.contains(TimeRange(utc(11), utc(12, 1)))
