from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo("Asia/Shanghai")
POLL_SECONDS = 600


def next_beijing_run(
    now_utc: datetime | None = None,
    hour: int = 7,
    minute: int = 30,
) -> datetime:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    now_beijing = now_utc.astimezone(BEIJING)
    candidate = datetime.combine(
        now_beijing.date(),
        time(hour=hour, minute=minute),
        tzinfo=BEIJING,
    )
    if now_beijing >= candidate:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def seconds_until_next_beijing_run(now_utc: datetime | None = None) -> int:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = next_beijing_run(now) - now.astimezone(timezone.utc)
    return max(1, int(delta.total_seconds()))


def should_run_daily(
    now_utc: datetime | None = None,
    last_run_beijing_date: str | None = None,
    hour: int = 7,
    minute: int = 30,
) -> bool:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    now_beijing = now_utc.astimezone(BEIJING)
    run_date = now_beijing.date().isoformat()
    target = datetime.combine(
        now_beijing.date(),
        time(hour=hour, minute=minute),
        tzinfo=BEIJING,
    )
    return now_beijing >= target and last_run_beijing_date != run_date


def current_beijing_date(now_utc: datetime | None = None) -> str:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(BEIJING).date().isoformat()


def _read_last_run_date(path: Path) -> str | None:
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily report schedule helpers.")
    parser.add_argument("--poll", action="store_true", help="Print poll decision for the current time.")
    parser.add_argument("--last-run-file", type=Path, help="File containing last successful Beijing run date.")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    if args.poll:
        last_run = _read_last_run_date(args.last_run_file) if args.last_run_file else None
        run_date = current_beijing_date(now)
        action = "run" if should_run_daily(now, last_run) else "wait"
        print(f"{action}\t{run_date}\t{POLL_SECONDS}")
        return 0

    next_run = next_beijing_run(now)
    seconds = seconds_until_next_beijing_run(now)
    print(f"{seconds}\t{next_run.isoformat()}\t{next_run.astimezone(BEIJING).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
