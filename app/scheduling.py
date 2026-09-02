import datetime

from sqlalchemy.orm import Session, selectinload

from app.config import WEEK_VIEW_END_HOUR, WEEK_VIEW_START_HOUR
from app.models import Job, JobAssignment, Worker, WorkerLeave

PX_PER_HOUR = 56
SHORT_BLOCK_THRESHOLD_PX = 45


def week_start(d: datetime.date) -> datetime.date:
    """Monday of the week containing d."""
    return d - datetime.timedelta(days=d.weekday())


def week_label(monday: datetime.date) -> str:
    """Human-readable range for the week starting on `monday`, e.g. '01 Sep – 07 Sep 2026'."""
    sunday = monday + datetime.timedelta(days=6)
    return f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"


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


def leave_worker_ids_for_day(db: Session, day: datetime.date) -> set[int]:
    """Ids of workers with a leave period covering `day`."""
    rows = (
        db.query(WorkerLeave.worker_id)
        .filter(WorkerLeave.start_date <= day, WorkerLeave.end_date >= day)
        .all()
    )
    return {r[0] for r in rows}


def leave_worker_ids_by_day(db: Session, dates: list[datetime.date]) -> dict[datetime.date, set[int]]:
    """Batched version of leave_worker_ids_for_day for a range of dates —
    one query instead of one per date, for callers (e.g. a week view) that
    need leave data across several days at once."""
    if not dates:
        return {}
    rows = (
        db.query(WorkerLeave.worker_id, WorkerLeave.start_date, WorkerLeave.end_date)
        .filter(WorkerLeave.start_date <= max(dates), WorkerLeave.end_date >= min(dates))
        .all()
    )
    result: dict[datetime.date, set[int]] = {d: set() for d in dates}
    for worker_id, start, end in rows:
        for d in dates:
            if start <= d <= end:
                result[d].add(worker_id)
    return result


def worker_on_leave_conflict(db: Session, day: datetime.date | None, worker_ids: set[int]) -> Worker | None:
    """First worker in worker_ids who is on leave on `day`, or None if no conflict."""
    if not day or not worker_ids:
        return None
    conflicting = worker_ids & leave_worker_ids_for_day(db, day)
    return db.get(Worker, next(iter(conflicting))) if conflicting else None


def workers_needing_leave_check(
    old_worker_ids: set[int], new_worker_ids: set[int], day_changed: bool
) -> set[int]:
    """Which of a job's post-change assigned workers should be validated
    against leave for the (possibly new) day — only ones whose assignment is
    actually changing with this request. A day move re-checks everyone
    staying assigned, since moving into a leave day is itself the trigger;
    otherwise only newly-added workers are checked, so a pre-existing
    conflict (e.g. a holiday added after a worker was already assigned)
    doesn't block unrelated edits on every future save. Shared by the
    drag-and-drop schedule endpoint and the job-modal save endpoint, which
    otherwise compute new_worker_ids differently but agree on this rule."""
    return new_worker_ids if day_changed else (new_worker_ids - old_worker_ids)


def build_day_lanes(
    db: Session,
    day: datetime.date,
    start_hour: int = WEEK_VIEW_START_HOUR,
    end_hour: int = WEEK_VIEW_END_HOUR,
    active_workers: list[Worker] | None = None,
    leave_ids: set[int] | None = None,
) -> tuple[list[dict], int]:
    """Return (lanes, lane_body_height_px) for a single day.

    Each lane: {"worker": Worker, "blocks": [block, ...], "on_leave": bool}
    Each block: {"job", "top", "height", "short", "linked", "other_workers"}
    Every active worker gets a lane every day, regardless of whether they
    have a job that day — this keeps a drop target available for any
    worker, and keeps on-leave workers visible (greyed out) even with an
    empty day.

    A caller building lanes for several days at once (e.g. a week view)
    should fetch `active_workers` and per-day `leave_ids` once up front and
    pass them in, rather than letting each call re-query the same data —
    this function runs once per day, so the default (re-query if not
    supplied) would otherwise mean the same worker/leave rows are fetched
    repeatedly within a single request.
    """
    lane_body_height = (end_hour - start_hour) * PX_PER_HOUR

    # Eager-load assignments -> worker and status in the same round trip —
    # without this, each job.assignments / assignment.worker / job.status
    # access below would fire its own query (N+1), and this function runs
    # up to 7x per week-view request (once per day).
    jobs = (
        db.query(Job)
        .options(
            selectinload(Job.assignments).selectinload(JobAssignment.worker),
            selectinload(Job.status),
        )
        .filter(Job.day == day)
        .filter(Job.start_time.isnot(None))
        .filter(Job.end_time.isnot(None))
        .all()
    )

    jobs_by_worker_id: dict[int, list[Job]] = {}
    for job in jobs:
        for a in job.assignments:
            jobs_by_worker_id.setdefault(a.worker_id, []).append(job)

    if leave_ids is None:
        leave_ids = leave_worker_ids_for_day(db, day)
    if active_workers is None:
        active_workers = db.query(Worker).filter(Worker.active.is_(True)).order_by(Worker.id).all()

    lanes = []
    for worker in active_workers:
        blocks = []
        for job in jobs_by_worker_id.get(worker.id, []):
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
        lanes.append({"worker": worker, "blocks": blocks, "on_leave": worker.id in leave_ids})

    return lanes, lane_body_height
