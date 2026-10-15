import datetime
import logging
import uuid
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app import servicem8, sync
from app.database import get_db
from app.deps import get_current_user
from app.models import Job, JobDay, JobDayAssignment, Status, User
from app.routers.settings import get_setting
from app.scheduling import week_start, worker_on_leave_conflict, workers_needing_leave_check
from app.templating import strip_query_param

logger = logging.getLogger(__name__)

router = APIRouter()

BOOKED_STATUS_NAME = "Booked with Customer"
MANUAL_TASK_QUEUE_NAME = "Manual task"


def _touch(job: Job, user: User) -> None:
    job.last_modified_by_id = user.id
    job.last_modified_at = datetime.datetime.utcnow()


def _set_assigned_workers(job_day: JobDay, worker_ids: set[int]) -> None:
    """Diff current assignments against the desired worker set, rather than
    clear-then-readd, which would insert a duplicate row before the delete of
    the same (job_day_id, worker_id) pair flushes and trip the unique constraint."""
    current = {a.worker_id: a for a in job_day.assignments}
    for worker_id, assignment in list(current.items()):
        if worker_id not in worker_ids:
            job_day.assignments.remove(assignment)
    for worker_id in worker_ids:
        if worker_id not in current:
            job_day.assignments.append(JobDayAssignment(worker_id=worker_id))


def _clean_return_to(return_to_raw: str) -> str:
    """Strip job/day query params out of a redirect target — used after
    deleting the job or day they referred to, so the page doesn't reopen a
    modal for something that no longer exists."""
    return strip_query_param(strip_query_param(return_to_raw, "job"), "day")


@router.post("/jobs/purge-past")
def purge_past_jobs(
    return_to: str = Form("/week"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete local scheduling for anything before this week.

    Only the JobDay (the scheduling record for one day) is removed — the
    parent Job survives and simply goes back to unscheduled if all of its
    days end up purged. If the job is still sitting in a watched ServiceM8
    queue, the next sync will pull it back in as unscheduled anyway
    (spec §3: sync only ever adds jobs it doesn't already know about).
    """
    cutoff = week_start(datetime.date.today())
    old_days = db.query(JobDay).filter(JobDay.day < cutoff).all()
    count = len(old_days)
    for jd in old_days:
        db.delete(jd)
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


@router.post("/jobs/{job_id}/days/{job_day_id}")
async def update_job_day(
    job_id: int,
    job_day_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Modal save for one specific day of a job. `status_id` is shared across
    every day of the job; day/start_time/end_time/worker_ids belong to just
    this JobDay."""
    form = await request.form()
    return_to = form.get("return_to") or "/week"
    job = db.get(Job, job_id)
    job_day = db.get(JobDay, job_day_id)
    if job is None or job_day is None or job_day.job_id != job_id:
        return RedirectResponse(return_to, status_code=303)

    day_str = form.get("day")
    new_day = datetime.date.fromisoformat(day_str) if day_str else job_day.day
    new_worker_ids = {int(v) for v in form.getlist("worker_ids")}
    current_worker_ids = {a.worker_id for a in job_day.assignments}
    day_changed = new_day != job_day.day
    separator = "&" if "?" in return_to else "?"

    if day_changed:
        clash = (
            db.query(JobDay)
            .filter(JobDay.job_id == job_id, JobDay.day == new_day, JobDay.id != job_day_id)
            .first()
        )
        if clash is not None:
            message = "This job is already scheduled that day."
            return RedirectResponse(
                f"{return_to}{separator}job={job_id}&day={job_day_id}&leave_conflict={quote_plus(message)}",
                status_code=303,
            )

    # Only validate workers whose assignment is actually changing here — a
    # worker already assigned to this day may have become conflicted by a
    # holiday added *after* they were booked (spec decision: flag it, don't
    # auto-unassign), and that pre-existing conflict shouldn't block
    # unrelated edits (status, description, ...) on every future save.
    check_worker_ids = workers_needing_leave_check(current_worker_ids, new_worker_ids, day_changed)
    conflict = worker_on_leave_conflict(db, new_day, check_worker_ids)
    if conflict:
        message = f"Can't save — {conflict.name} is on leave on {new_day.strftime('%d %b %Y')}."
        return RedirectResponse(
            f"{return_to}{separator}job={job_id}&day={job_day_id}&leave_conflict={quote_plus(message)}",
            status_code=303,
        )

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

    job_day.day = new_day

    start_time = form.get("start_time")
    job_day.start_time = datetime.time.fromisoformat(start_time) if start_time else None

    end_time = form.get("end_time")
    job_day.end_time = datetime.time.fromisoformat(end_time) if end_time else None

    _set_assigned_workers(job_day, new_worker_ids)

    _touch(job, user)
    db.commit()
    return RedirectResponse(return_to, status_code=303)


@router.post("/jobs/{job_id}/days/{job_day_id}/delete")
async def remove_job_day(
    job_id: int,
    job_day_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove just one day of a job — if it's the job's only day, this is
    exactly "unschedule back to the sidebar" (the Job row survives)."""
    form = await request.form()
    return_to = _clean_return_to(form.get("return_to") or "/week")
    job_day = db.get(JobDay, job_day_id)
    if job_day is not None and job_day.job_id == job_id:
        job = job_day.job
        db.delete(job_day)
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
    return_to = _clean_return_to(form.get("return_to") or "/week")
    job = db.get(Job, job_id)
    if job:
        db.delete(job)
        db.commit()
    return RedirectResponse(return_to, status_code=303)


@router.post("/jobs/{job_id}/days/{job_day_id}/book-in-servicem8")
def book_in_servicem8(
    job_id: int,
    job_day_id: int,
    return_to: str = Form("/week"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Write one day's booking back to ServiceM8 (spec §3): create/update the
    JobActivity with activity_was_scheduled=1, then force the job's shared
    status to 'Booked with Customer' — booking always forces this, no
    exceptions, and it applies to the whole job even though the booking
    itself is per-day."""
    separator = "&" if "?" in return_to else "?"
    job = db.get(Job, job_id)
    job_day = db.get(JobDay, job_day_id)
    if job is None or job_day is None or job_day.job_id != job_id:
        return RedirectResponse(return_to, status_code=303)

    if job.is_manual:
        return RedirectResponse(f"{return_to}{separator}booked=manual", status_code=303)

    if job_day.start_time is None or job_day.end_time is None:
        return RedirectResponse(f"{return_to}{separator}booked=notscheduled", status_code=303)

    api_key = get_setting(db, "servicem8_api_key")
    if not api_key:
        return RedirectResponse(f"{return_to}{separator}booked=nokey", status_code=303)

    start_dt = f"{job_day.day.isoformat()} {job_day.start_time.strftime('%H:%M:%S')}"
    end_dt = f"{job_day.day.isoformat()} {job_day.end_time.strftime('%H:%M:%S')}"

    # ServiceM8's JobActivity appears to require a staff_uuid — use the first
    # of this day's assigned workers with a linked ServiceM8 staff member
    # (Settings → Workers), if any.
    staff_uuid = None
    for assignment in job_day.assignments:
        if assignment.worker.servicem8_staff_uuid:
            staff_uuid = assignment.worker.servicem8_staff_uuid
            break

    try:
        activity_uuid = servicem8.create_scheduled_activity(
            api_key, job.servicem8_uuid, start_dt, end_dt, job_day.servicem8_activity_uuid, staff_uuid
        )
    except Exception:
        logger.exception("ServiceM8 booking write-back failed for job %s day %s", job_id, job_day_id)
        return RedirectResponse(f"{return_to}{separator}booked=error", status_code=303)

    if activity_uuid:
        job_day.servicem8_activity_uuid = activity_uuid
    job_day.servicem8_booked = True
    job_day.servicem8_last_synced_at = datetime.datetime.utcnow()

    booked_status = db.query(Status).filter(Status.name == BOOKED_STATUS_NAME).first()
    if booked_status:
        job.status_id = booked_status.id

    _touch(job, user)
    db.commit()
    return RedirectResponse(f"{return_to}{separator}booked=ok", status_code=303)


@router.post("/jobs/{job_id}/days/{job_day_id}/resync-booking")
def resync_booking(
    job_id: int,
    job_day_id: int,
    return_to: str = Form("/week"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pull one day's real booking state from ServiceM8 and reconcile the
    local copy:
    - gone/deactivated there -> unlock locally and set status to Cancelled.
    - still there but a different date/time -> adopt ServiceM8's date/time, stay locked.
    - matches -> just refresh the synced timestamp."""
    separator = "&" if "?" in return_to else "?"
    job_day = db.get(JobDay, job_day_id)
    if job_day is None or job_day.job_id != job_id:
        return RedirectResponse(return_to, status_code=303)

    if not job_day.servicem8_booked or not job_day.servicem8_activity_uuid:
        return RedirectResponse(f"{return_to}{separator}booked=notbooked", status_code=303)

    api_key = get_setting(db, "servicem8_api_key")
    if not api_key:
        return RedirectResponse(f"{return_to}{separator}booked=nokey", status_code=303)

    try:
        outcome = sync.reconcile_booking(db, api_key, job_day)
    except Exception:
        logger.exception("ServiceM8 booking re-sync failed for job %s day %s", job_id, job_day_id)
        return RedirectResponse(f"{return_to}{separator}booked=error", status_code=303)

    _touch(job_day.job, user)
    db.commit()
    return RedirectResponse(f"{return_to}{separator}booked={outcome}", status_code=303)


@router.get("/api/jobs/search")
def search_scheduled_jobs(
    q: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sidebar search over jobs already on the calendar — the sidebar's own
    filtering only covers unscheduled cards, so a job booked on some past or
    future week would otherwise be unfindable. Returns one hit per scheduled
    day, newest first, so the board can jump straight to it."""
    term = q.strip()
    if len(term) < 2:
        return {"results": []}
    like = f"%{term}%"
    job_days = (
        db.query(JobDay)
        .join(Job)
        .filter(or_(Job.job_number.ilike(like), Job.customer_name.ilike(like), Job.description.ilike(like)))
        .options(selectinload(JobDay.job), selectinload(JobDay.assignments).selectinload(JobDayAssignment.worker))
        .order_by(JobDay.day.desc())
        .limit(30)
        .all()
    )
    return {
        "results": [
            {
                "job_id": jd.job_id,
                "job_day_id": jd.id,
                "job_number": jd.job.job_number,
                "customer_name": jd.job.customer_name,
                "day": jd.day.isoformat(),
                "day_label": jd.day.strftime("%a %d/%m/%Y"),
                "start_time": jd.start_time.strftime("%H:%M") if jd.start_time else None,
                "workers": [a.worker.name for a in jd.assignments],
            }
            for jd in job_days
        ]
    }


@router.post("/api/jobs/{job_id}/schedule")
async def schedule_job(
    job_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Drag-and-drop, resize, duration steppers, and copy/paste all land
    here. A `job_day_id` in the payload means "update that occurrence"
    (move/resize/reassign); its absence means "add a new day to this job" —
    covering first-ever scheduling from the sidebar, dropping onto an empty
    day, and pasting a copied job onto a new day. There's no other
    distinction between those cases."""
    payload = await request.json()
    job = db.get(Job, job_id)
    if job is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    job_day_id = payload.get("job_day_id")
    job_day = db.get(JobDay, job_day_id) if job_day_id else None
    if job_day_id and (job_day is None or job_day.job_id != job_id):
        return JSONResponse({"error": "not found"}, status_code=404)

    if job_day is not None:
        effective_day = datetime.date.fromisoformat(payload["day"]) if payload.get("day") else job_day.day
        day_changed = bool(payload.get("day")) and effective_day != job_day.day
        current_worker_ids = {a.worker_id for a in job_day.assignments}
        dropped_worker_id = int(payload["worker_id"]) if payload.get("worker_id") else None

        if day_changed:
            clash = (
                db.query(JobDay)
                .filter(JobDay.job_id == job_id, JobDay.day == effective_day, JobDay.id != job_day.id)
                .first()
            )
            if clash is not None:
                return JSONResponse(
                    {"ok": False, "error": "already_scheduled", "message": "This job is already scheduled that day."},
                    status_code=409,
                )

        # Dropping a job onto a lane for someone already assigned to it is
        # just a time/day move — a multi-worker job must keep its whole
        # team, not collapse down to the one lane it happened to land in.
        # Dropping onto a lane for someone NOT currently assigned is an
        # explicit reassignment (spec §6.2), which replaces the assignment.
        if dropped_worker_id is not None and dropped_worker_id not in current_worker_ids:
            new_worker_ids = {dropped_worker_id}
        else:
            new_worker_ids = current_worker_ids

        check_worker_ids = workers_needing_leave_check(current_worker_ids, new_worker_ids, day_changed)
        conflict = worker_on_leave_conflict(db, effective_day, check_worker_ids)
        if conflict:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "worker_on_leave",
                    "message": f"{conflict.name} is on leave on {effective_day.strftime('%d %b %Y')}.",
                },
                status_code=409,
            )

        job_day.day = effective_day
        if payload.get("start_time"):
            job_day.start_time = datetime.time.fromisoformat(payload["start_time"])
        if payload.get("end_time"):
            job_day.end_time = datetime.time.fromisoformat(payload["end_time"])

        # ServiceM8 never carries scheduling info, so a day with nothing
        # ever recorded has nothing to base a time on — default to a
        # sensible 8am-9am slot instead of leaving it blank.
        if job_day.start_time is None and job_day.end_time is None:
            job_day.start_time = datetime.time(8, 0)
            job_day.end_time = datetime.time(9, 0)

        if dropped_worker_id is not None:
            _set_assigned_workers(job_day, new_worker_ids)

        _touch(job, user)
        db.commit()
        return JSONResponse(
            {"ok": True, "needs_worker": len(job_day.assignments) == 0, "job_day_id": job_day.id}
        )

    # No job_day_id: add a new day to this job.
    if not payload.get("day"):
        return JSONResponse({"error": "day required"}, status_code=400)
    new_day = datetime.date.fromisoformat(payload["day"])

    clash = db.query(JobDay).filter(JobDay.job_id == job_id, JobDay.day == new_day).first()
    if clash is not None:
        return JSONResponse(
            {"ok": False, "error": "already_scheduled", "message": "This job is already scheduled that day."},
            status_code=409,
        )

    worker_id = int(payload["worker_id"]) if payload.get("worker_id") else None
    new_worker_ids = {worker_id} if worker_id is not None else set()

    conflict = worker_on_leave_conflict(db, new_day, new_worker_ids)
    if conflict:
        return JSONResponse(
            {
                "ok": False,
                "error": "worker_on_leave",
                "message": f"{conflict.name} is on leave on {new_day.strftime('%d %b %Y')}.",
            },
            status_code=409,
        )

    start_time = datetime.time.fromisoformat(payload["start_time"]) if payload.get("start_time") else None
    end_time = datetime.time.fromisoformat(payload["end_time"]) if payload.get("end_time") else None
    if start_time is None and end_time is None:
        start_time = datetime.time(8, 0)
        end_time = datetime.time(9, 0)

    new_job_day = JobDay(job_id=job.id, day=new_day, start_time=start_time, end_time=end_time)
    db.add(new_job_day)
    db.flush()
    if worker_id is not None:
        new_job_day.assignments.append(JobDayAssignment(worker_id=worker_id))

    _touch(job, user)
    db.commit()
    # Tell the caller if this day still has nobody assigned — happens when a
    # brand-new job is dropped somewhere with no lane to infer a worker from
    # (e.g. an empty day). The frontend uses this to open the edit modal so a
    # worker can be picked, rather than silently leaving the job invisible.
    return JSONResponse(
        {"ok": True, "needs_worker": len(new_job_day.assignments) == 0, "job_day_id": new_job_day.id}
    )
