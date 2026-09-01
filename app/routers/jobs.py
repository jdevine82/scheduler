import datetime
import logging
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import servicem8, sync
from app.database import get_db
from app.deps import get_current_user
from app.models import Job, JobAssignment, Status, User
from app.routers.settings import get_setting
from app.scheduling import week_start

logger = logging.getLogger(__name__)

router = APIRouter()

BOOKED_STATUS_NAME = "Booked with Customer"
MANUAL_TASK_QUEUE_NAME = "Manual task"


def _touch(job: Job, user: User) -> None:
    job.last_modified_by_id = user.id
    job.last_modified_at = datetime.datetime.utcnow()


def _set_assigned_workers(job: Job, worker_ids: set[int]) -> None:
    """Diff current assignments against the desired worker set, rather than
    clear-then-readd, which would insert a duplicate row before the delete of
    the same (job_id, worker_id) pair flushes and trip the unique constraint."""
    current = {a.worker_id: a for a in job.assignments}
    for worker_id, assignment in list(current.items()):
        if worker_id not in worker_ids:
            job.assignments.remove(assignment)
    for worker_id in worker_ids:
        if worker_id not in current:
            job.assignments.append(JobAssignment(worker_id=worker_id))


@router.post("/jobs/purge-past")
def purge_past_jobs(
    return_to: str = Form("/week"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete local records for anything scheduled before this week.

    This only removes the local scheduling record — if the job is still sitting
    in a watched ServiceM8 queue, the next sync will pull it back in as
    unscheduled (spec §3: sync only ever adds jobs it doesn't already know about).
    """
    cutoff = week_start(datetime.date.today())
    old_jobs = db.query(Job).filter(Job.day.isnot(None), Job.day < cutoff).all()
    count = len(old_jobs)
    for job in old_jobs:
        db.delete(job)
    db.commit()
    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{separator}purged={count}", status_code=303)


@router.post("/jobs/manual")
async def create_manual_job(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    return_to: str = Form("/week"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a task with no ServiceM8 job behind it. Behaves like any other job
    once created — schedulable, editable, deletable — except it can never be
    booked or touched by ServiceM8 sync (its servicem8_uuid is just a local
    placeholder, never matched by anything ServiceM8 returns)."""
    default_status = db.query(Status).order_by(Status.sort_order).first()
    job = Job(
        servicem8_uuid=f"manual-{uuid.uuid4()}",
        job_number=f"M-{db.query(Job).filter(Job.is_manual.is_(True)).count() + 1}",
        customer_name=title,
        description=description,
        queue_name=MANUAL_TASK_QUEUE_NAME,
        status_id=default_status.id,
        is_manual=True,
    )
    db.add(job)
    db.flush()
    _touch(job, user)
    db.commit()
    return RedirectResponse(return_to, status_code=303)


@router.post("/jobs/{job_id}")
async def update_job(
    job_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    return_to = form.get("return_to") or "/week"
    job = db.get(Job, job_id)
    if job is None:
        return RedirectResponse(return_to, status_code=303)

    # Only a manual task's modal actually submits these fields — a
    # ServiceM8-sourced job's title/description stay read-only in the UI.
    if job.is_manual:
        if "customer_name" in form:
            job.customer_name = form.get("customer_name") or job.customer_name
        if "description" in form:
            job.description = form.get("description", "")

    status_id = form.get("status_id")
    if status_id:
        job.status_id = int(status_id)

    day = form.get("day")
    job.day = datetime.date.fromisoformat(day) if day else None

    start_time = form.get("start_time")
    job.start_time = datetime.time.fromisoformat(start_time) if start_time else None

    end_time = form.get("end_time")
    job.end_time = datetime.time.fromisoformat(end_time) if end_time else None

    worker_ids = {int(v) for v in form.getlist("worker_ids")}
    _set_assigned_workers(job, worker_ids)

    _touch(job, user)
    db.commit()
    return RedirectResponse(return_to, status_code=303)


@router.post("/jobs/{job_id}/delete")
async def delete_job(
    job_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    return_to_raw = form.get("return_to") or "/week"
    # Strip the now-deleted job's id out of the redirect target.
    return_to = return_to_raw.split("&job=")[0].split("?job=")[0]
    job = db.get(Job, job_id)
    if job:
        db.delete(job)
        db.commit()
    return RedirectResponse(return_to, status_code=303)


@router.post("/jobs/{job_id}/book-in-servicem8")
def book_in_servicem8(
    job_id: int,
    return_to: str = Form("/week"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Write the booking back to ServiceM8 (spec §3): create/update the
    JobActivity with activity_was_scheduled=1, then force the local status to
    'Booked with Customer' — booking always forces this, no exceptions."""
    separator = "&" if "?" in return_to else "?"
    job = db.get(Job, job_id)
    if job is None:
        return RedirectResponse(return_to, status_code=303)

    if job.is_manual:
        return RedirectResponse(f"{return_to}{separator}booked=manual", status_code=303)

    if job.day is None or job.start_time is None or job.end_time is None:
        return RedirectResponse(f"{return_to}{separator}booked=notscheduled", status_code=303)

    api_key = get_setting(db, "servicem8_api_key")
    if not api_key:
        return RedirectResponse(f"{return_to}{separator}booked=nokey", status_code=303)

    start_dt = f"{job.day.isoformat()} {job.start_time.strftime('%H:%M:%S')}"
    end_dt = f"{job.day.isoformat()} {job.end_time.strftime('%H:%M:%S')}"

    # ServiceM8's JobActivity appears to require a staff_uuid — use the first
    # assigned worker's linked ServiceM8 staff member (Settings → Workers), if any.
    staff_uuid = None
    for assignment in job.assignments:
        if assignment.worker.servicem8_staff_uuid:
            staff_uuid = assignment.worker.servicem8_staff_uuid
            break

    try:
        activity_uuid = servicem8.create_scheduled_activity(
            api_key, job.servicem8_uuid, start_dt, end_dt, job.servicem8_activity_uuid, staff_uuid
        )
    except Exception:
        logger.exception("ServiceM8 booking write-back failed for job %s", job_id)
        return RedirectResponse(f"{return_to}{separator}booked=error", status_code=303)

    if activity_uuid:
        job.servicem8_activity_uuid = activity_uuid
    job.servicem8_booked = True
    job.servicem8_last_synced_at = datetime.datetime.utcnow()

    booked_status = db.query(Status).filter(Status.name == BOOKED_STATUS_NAME).first()
    if booked_status:
        job.status_id = booked_status.id

    _touch(job, user)
    db.commit()
    return RedirectResponse(f"{return_to}{separator}booked=ok", status_code=303)


@router.post("/jobs/{job_id}/resync-booking")
def resync_booking(
    job_id: int,
    return_to: str = Form("/week"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pull the booking's real state from ServiceM8 and reconcile the local copy:
    - gone/deactivated there -> unlock locally and set status to Cancelled.
    - still there but a different date/time -> adopt ServiceM8's date/time, stay locked.
    - matches -> just refresh the synced timestamp."""
    separator = "&" if "?" in return_to else "?"
    job = db.get(Job, job_id)
    if job is None:
        return RedirectResponse(return_to, status_code=303)

    if not job.servicem8_booked or not job.servicem8_activity_uuid:
        return RedirectResponse(f"{return_to}{separator}booked=notbooked", status_code=303)

    api_key = get_setting(db, "servicem8_api_key")
    if not api_key:
        return RedirectResponse(f"{return_to}{separator}booked=nokey", status_code=303)

    try:
        outcome = sync.reconcile_booking(db, api_key, job)
    except Exception:
        logger.exception("ServiceM8 booking re-sync failed for job %s", job_id)
        return RedirectResponse(f"{return_to}{separator}booked=error", status_code=303)

    _touch(job, user)
    db.commit()
    return RedirectResponse(f"{return_to}{separator}booked={outcome}", status_code=303)


@router.post("/api/jobs/{job_id}/schedule")
async def schedule_job(
    job_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = await request.json()
    job = db.get(Job, job_id)
    if job is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    if payload.get("day"):
        job.day = datetime.date.fromisoformat(payload["day"])
    if payload.get("start_time"):
        job.start_time = datetime.time.fromisoformat(payload["start_time"])
    if payload.get("end_time"):
        job.end_time = datetime.time.fromisoformat(payload["end_time"])

    # ServiceM8 never carries scheduling info, so a job dropped onto the board
    # for the first time (day just set, no time ever recorded) has nothing to
    # base a time on — default to a sensible 8am-9am slot instead of leaving
    # it blank. Jobs being reshuffled that already have a time keep it as-is.
    if job.day is not None and job.start_time is None and job.end_time is None:
        job.start_time = datetime.time(8, 0)
        job.end_time = datetime.time(9, 0)

    if payload.get("worker_id"):
        _set_assigned_workers(job, {int(payload["worker_id"])})

    _touch(job, user)
    db.commit()
    # Tell the caller if this job still has nobody assigned — happens when a
    # brand-new job is dropped somewhere with no lane to infer a worker from
    # (e.g. an empty day). The frontend uses this to open the edit modal so a
    # worker can be picked, rather than silently leaving the job invisible.
    return JSONResponse({"ok": True, "needs_worker": len(job.assignments) == 0})
