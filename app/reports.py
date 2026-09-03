import datetime

from sqlalchemy.orm import Session, selectinload

from app.models import Job, JobDay, JobDayAssignment, Status, Worker
from app.sync import COMPLETED_STATUS_NAME


def incomplete_jobs_for_week(db: Session, monday: datetime.date) -> list[tuple[Worker | None, list[Job]]]:
    """Scheduled jobs (any day within monday..monday+6) not in Completed
    status, grouped by assigned worker. A job with multiple assigned
    workers appears once per worker; jobs with no assigned worker group
    under None. A multi-day job with several of its days in this week and
    the same worker each day appears once in that worker's list, not once
    per day. Workers are sorted by name, with the unassigned group last."""
    sunday = monday + datetime.timedelta(days=6)
    completed_status = db.query(Status).filter(Status.name == COMPLETED_STATUS_NAME).first()

    query = (
        db.query(JobDay)
        .join(Job)
        .options(
            selectinload(JobDay.assignments).selectinload(JobDayAssignment.worker),
            selectinload(JobDay.job),
        )
        .filter(JobDay.day >= monday, JobDay.day <= sunday)
        .order_by(JobDay.day, JobDay.start_time.is_(None), JobDay.start_time)
    )
    if completed_status is not None:
        query = query.filter(Job.status_id != completed_status.id)
    job_days = query.all()

    grouped: dict[int | None, dict[int, Job]] = {}
    workers_by_id: dict[int, Worker] = {}
    for jd in job_days:
        if jd.assignments:
            for a in jd.assignments:
                grouped.setdefault(a.worker_id, {})[jd.job_id] = jd.job
                workers_by_id[a.worker_id] = a.worker
        else:
            grouped.setdefault(None, {})[jd.job_id] = jd.job

    worker_ids_sorted = sorted(
        (wid for wid in grouped if wid is not None),
        key=lambda wid: workers_by_id[wid].name,
    )
    result: list[tuple[Worker | None, list[Job]]] = [
        (workers_by_id[wid], list(grouped[wid].values())) for wid in worker_ids_sorted
    ]
    if None in grouped:
        result.append((None, list(grouped[None].values())))
    return result
