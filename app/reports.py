import datetime

from sqlalchemy.orm import Session, selectinload

from app.models import Job, JobAssignment, Status, Worker
from app.sync import COMPLETED_STATUS_NAME


def incomplete_jobs_for_week(db: Session, monday: datetime.date) -> list[tuple[Worker | None, list[Job]]]:
    """Scheduled jobs (day within monday..monday+6) not in Completed status,
    grouped by assigned worker. A job with multiple assigned workers appears
    once per worker; jobs with no assigned worker group under None. Workers
    are sorted by name, with the unassigned group listed last."""
    sunday = monday + datetime.timedelta(days=6)
    completed_status = db.query(Status).filter(Status.name == COMPLETED_STATUS_NAME).first()

    query = (
        db.query(Job)
        .options(selectinload(Job.assignments).selectinload(JobAssignment.worker))
        .filter(Job.day >= monday, Job.day <= sunday)
        .order_by(Job.day, Job.start_time.is_(None), Job.start_time)
    )
    if completed_status is not None:
        query = query.filter(Job.status_id != completed_status.id)
    jobs = query.all()

    grouped: dict[int | None, list[Job]] = {}
    workers_by_id: dict[int, Worker] = {}
    for job in jobs:
        if job.assignments:
            for a in job.assignments:
                grouped.setdefault(a.worker_id, []).append(job)
                workers_by_id[a.worker_id] = a.worker
        else:
            grouped.setdefault(None, []).append(job)

    worker_ids_sorted = sorted(
        (wid for wid in grouped if wid is not None),
        key=lambda wid: workers_by_id[wid].name,
    )
    result: list[tuple[Worker | None, list[Job]]] = [
        (workers_by_id[wid], grouped[wid]) for wid in worker_ids_sorted
    ]
    if None in grouped:
        result.append((None, grouped[None]))
    return result
