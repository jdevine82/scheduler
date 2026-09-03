"""ServiceM8 sync: pulls queues + unscheduled jobs into the local DB (spec §3).

Sync rules:
- New jobs in a watched queue are added locally as unscheduled (no JobDay rows).
- Jobs already known locally never have their scheduling (JobDay rows,
  status, assignments) touched by sync — only ServiceM8-sourced fields
  (customer, description) refresh.
- Jobs that disappear from all watched queues are flagged, not deleted.
"""

import datetime
import logging

from sqlalchemy.orm import Session

from app import servicem8
from app.models import Job, JobDay, Queue, Status

logger = logging.getLogger(__name__)

DEFAULT_STATUS_FOR_NEW_JOBS = "Loosely Planned"
CANCELLED_STATUS_NAME = "Cancelled"
COMPLETED_STATUS_NAME = "Completed"


def refresh_queues(db: Session, api_key: str) -> int:
    """Upsert the ServiceM8 queue list. Returns count of new queues added."""
    remote_queues = servicem8.fetch_queues(api_key)
    existing = {q.servicem8_queue_uuid: q for q in db.query(Queue).all()}
    added = 0
    for rq in remote_queues:
        if rq["uuid"] in existing:
            existing[rq["uuid"]].name = rq["name"]
        else:
            db.add(Queue(servicem8_queue_uuid=rq["uuid"], name=rq["name"], watched=False))
            added += 1
    db.commit()
    return added


def _apply_completions(db: Session, api_key: str, completion_queue_uuid: str) -> int:
    """Mark local jobs Completed if ServiceM8 now shows them sitting in the
    configured completion queue. Overrides the "never auto-change away from
    Booked with Customer" rule that governs booking write-back/re-sync —
    the queue move is a stronger, more direct signal the work is actually
    done. Returns the count of jobs newly marked Completed."""
    completed_status = db.query(Status).filter(Status.name == COMPLETED_STATUS_NAME).first()
    if completed_status is None:
        return 0

    remote_uuids = {j["uuid"] for j in servicem8.fetch_jobs_in_queue(api_key, completion_queue_uuid)}
    if not remote_uuids:
        return 0

    queue = db.query(Queue).filter(Queue.servicem8_queue_uuid == completion_queue_uuid).first()
    jobs = (
        db.query(Job)
        .filter(Job.servicem8_uuid.in_(remote_uuids), Job.status_id != completed_status.id)
        .all()
    )
    for job in jobs:
        job.status_id = completed_status.id
        if queue:
            job.queue_name = queue.name
        job.flagged_missing_from_queue = False
    return len(jobs)


def sync_jobs(db: Session, api_key: str, completion_queue_uuid: str | None = None) -> dict:
    """Pull jobs from watched queues. Returns a summary dict for logging."""
    watched_queues = db.query(Queue).filter(Queue.watched.is_(True)).all()
    default_status = db.query(Status).filter(Status.name == DEFAULT_STATUS_FOR_NEW_JOBS).first()
    if default_status is None:
        default_status = db.query(Status).order_by(Status.sort_order).first()

    remote_jobs_by_uuid: dict[str, dict] = {}
    for queue in watched_queues:
        for raw_job in servicem8.fetch_jobs_in_queue(api_key, queue.servicem8_queue_uuid):
            raw_job["_queue_name"] = queue.name
            remote_jobs_by_uuid[raw_job["uuid"]] = raw_job

    company_uuids = [j.get("company_uuid") for j in remote_jobs_by_uuid.values() if j.get("company_uuid")]
    company_names = servicem8.fetch_company_names(api_key, company_uuids)

    local_jobs = {j.servicem8_uuid: j for j in db.query(Job).all()}

    added = 0
    updated = 0
    flagged = 0
    unflagged = 0

    for uuid, raw_job in remote_jobs_by_uuid.items():
        customer_name = company_names.get(raw_job.get("company_uuid", ""), "")
        description = raw_job.get("job_description", "")
        job_number = raw_job.get("generated_job_id", raw_job.get("uuid", "")[:8])

        if uuid not in local_jobs:
            db.add(
                Job(
                    servicem8_uuid=uuid,
                    job_number=job_number,
                    customer_name=customer_name,
                    description=description,
                    queue_name=raw_job["_queue_name"],
                    status_id=default_status.id,
                )
            )
            added += 1
        else:
            job = local_jobs[uuid]
            job.customer_name = customer_name
            job.description = description
            job.job_number = job_number
            job.queue_name = raw_job["_queue_name"]
            if job.flagged_missing_from_queue:
                job.flagged_missing_from_queue = False
                unflagged += 1
            updated += 1

    watched_uuids = {q.servicem8_queue_uuid for q in watched_queues}
    for uuid, job in local_jobs.items():
        was_from_watched_queue = uuid in remote_jobs_by_uuid or job.queue_name in {
            q.name for q in watched_queues
        }
        if was_from_watched_queue and uuid not in remote_jobs_by_uuid and not job.flagged_missing_from_queue:
            job.flagged_missing_from_queue = True
            flagged += 1

    db.commit()

    completed = 0
    if completion_queue_uuid:
        try:
            completed = _apply_completions(db, api_key, completion_queue_uuid)
            db.commit()
        except Exception:
            logger.exception("Completion-queue check failed")

    return {"added": added, "updated": updated, "flagged": flagged, "unflagged": unflagged, "completed": completed}


def reconcile_booking(db: Session, api_key: str, job_day: JobDay) -> str:
    """Pull one day's real booking state from ServiceM8 and reconcile locally:
    - gone/deactivated there -> unlock locally and set the job's status to Cancelled.
    - still there but a different date/time -> adopt ServiceM8's date/time, stay locked.
    - matches -> just refresh the synced timestamp.

    Returns 'cancelled' | 'updated' | 'insync'. Caller is responsible for
    committing and for touching last_modified (only meaningful for a manual,
    user-triggered re-sync — not the bulk/background case)."""
    activity = servicem8.fetch_activity(api_key, job_day.servicem8_activity_uuid)

    if activity is None:
        job_day.servicem8_booked = False
        job_day.servicem8_activity_uuid = None
        cancelled_status = db.query(Status).filter(Status.name == CANCELLED_STATUS_NAME).first()
        if cancelled_status:
            job_day.job.status_id = cancelled_status.id
        return "cancelled"

    sm8_start = datetime.datetime.strptime(activity["start_date"], "%Y-%m-%d %H:%M:%S")
    sm8_end = datetime.datetime.strptime(activity["end_date"], "%Y-%m-%d %H:%M:%S")

    changed = (
        job_day.day != sm8_start.date()
        or job_day.start_time != sm8_start.time()
        or job_day.end_time != sm8_end.time()
    )
    if changed:
        job_day.day = sm8_start.date()
        job_day.start_time = sm8_start.time()
        job_day.end_time = sm8_end.time()

    job_day.servicem8_last_synced_at = datetime.datetime.utcnow()
    return "updated" if changed else "insync"


def resync_all_bookings(db: Session, api_key: str) -> dict:
    """Re-check every locally-booked day against ServiceM8 — used by the
    top-bar Sync Now button so a booking removed or moved in ServiceM8 gets
    caught without having to open each job individually."""
    booked_days = (
        db.query(JobDay)
        .join(Job)
        .filter(
            JobDay.servicem8_booked.is_(True),
            JobDay.servicem8_activity_uuid.isnot(None),
            Job.is_manual.is_(False),
        )
        .all()
    )
    updated = 0
    cancelled = 0
    errors = 0
    for job_day in booked_days:
        try:
            outcome = reconcile_booking(db, api_key, job_day)
        except Exception:
            logger.exception("Booking re-sync failed for job %s day %s", job_day.job_id, job_day.id)
            errors += 1
            continue
        if outcome == "updated":
            updated += 1
        elif outcome == "cancelled":
            cancelled += 1
    db.commit()
    return {"checked": len(booked_days), "updated": updated, "cancelled": cancelled, "errors": errors}
