from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ReportWindow:
    target_date: date
    start_utc: datetime
    end_utc: datetime


def beijing_previous_day_window(now: datetime | None = None) -> ReportWindow:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    beijing_now = current.astimezone(BEIJING_TZ)
    target = beijing_now.date() - timedelta(days=1)
    start_bjt = datetime.combine(target, time.min, tzinfo=BEIJING_TZ)
    end_bjt = datetime.combine(target, time(23, 59, 59), tzinfo=BEIJING_TZ)
    return ReportWindow(
        target_date=target,
        start_utc=start_bjt.astimezone(timezone.utc),
        end_utc=end_bjt.astimezone(timezone.utc),
    )


def beijing_date_window(target: date) -> ReportWindow:
    start_bjt = datetime.combine(target, time.min, tzinfo=BEIJING_TZ)
    end_bjt = datetime.combine(target, time(23, 59, 59), tzinfo=BEIJING_TZ)
    return ReportWindow(
        target_date=target,
        start_utc=start_bjt.astimezone(timezone.utc),
        end_utc=end_bjt.astimezone(timezone.utc),
    )
