import datetime

from sqlalchemy.orm import Session

from app.config import WEEK_VIEW_END_HOUR, WEEK_VIEW_START_HOUR
from app.models import Job

PX_PER_HOUR = 56
SHORT_BLOCK_THRESHOLD_PX = 45


def week_start(d: datetime.date) -> datetime.date:
    """Monday of the week containing d."""
    return d - datetime.timedelta(days=d.weekday())


def hour_labels(start_hour: int = WEEK_VIEW_START_HOUR, end_hour: int = WEEK_VIEW_END_HOUR) -> list[str]:
    labels = []
    for h in range(start_hour, end_hour):
        suffix = "am" if h < 12 else "pm"
        display = h if h <= 12 else h - 12
        if display == 0:
            display = 12
        labels.append(f"{display}{suffix}")
    return labels


def _time_to_minutes(t: datetime.time) -> int:
    return t.hour * 60 + t.minute


def duration_minutes(start: datetime.time | None, end: datetime.time | None) -> int | None:
    if start is None or end is None:
        return None
    return _time_to_minutes(end) - _time_to_minutes(start)


def _format_time(t: datetime.time) -> str:
    h = t.hour
    suffix = "am" if h < 12 else "pm"
    display = h if h <= 12 else h - 12
    if display == 0:
        display = 12
    if t.minute:
        return f"{display}:{t.minute:02d}{suffix}"
    return f"{display}{suffix}"


def build_day_lanes(
    db: Session,
    day: datetime.date,
    start_hour: int = WEEK_VIEW_START_HOUR,
    end_hour: int = WEEK_VIEW_END_HOUR,
) -> tuple[list[dict], int]:
    """Return (lanes, lane_body_height_px) for a single day.

    Each lane: {"worker": Worker, "blocks": [block, ...]}
    Each block: {"job", "top", "height", "short", "linked", "other_workers"}
    Only workers with >=1 job that day get a lane, per spec §6.2.
    """
    lane_body_height = (end_hour - start_hour) * PX_PER_HOUR

    jobs = (
        db.query(Job)
        .filter(Job.day == day)
        .filter(Job.start_time.isnot(None))
        .filter(Job.end_time.isnot(None))
        .all()
    )

    workers_seen = {}
    for job in jobs:
        for a in job.assignments:
            workers_seen.setdefault(a.worker.id, a.worker)

    active_workers = sorted(workers_seen.values(), key=lambda w: w.id)

    lanes = []
    for worker in active_workers:
        blocks = []
        for job in jobs:
            assigned_worker_ids = [a.worker_id for a in job.assignments]
            if worker.id not in assigned_worker_ids:
                continue

            start_min = _time_to_minutes(job.start_time)
            end_min = _time_to_minutes(job.end_time)
            range_start_min = start_hour * 60
            top = round((start_min - range_start_min) / 60 * PX_PER_HOUR)
            height = max(round((end_min - start_min) / 60 * PX_PER_HOUR), 18)
            top = max(top, 0)
            height = min(height, lane_body_height - top)

            other_workers = [a.worker.name for a in job.assignments if a.worker_id != worker.id]

            blocks.append(
                {
                    "job": job,
                    "top": top,
                    "height": height,
                    "short": height < SHORT_BLOCK_THRESHOLD_PX,
                    "linked": len(job.assignments) > 1,
                    "other_workers": other_workers,
                    "time_label": f"{_format_time(job.start_time)}–{_format_time(job.end_time)}",
                    "duration_min": end_min - start_min,
                }
            )
        lanes.append({"worker": worker, "blocks": blocks})

    return lanes, lane_body_height
