import calendar as pycalendar
import datetime
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, selectinload

from app import sync as servicem8_sync
from app.config import WEEK_VIEW_END_HOUR, WEEK_VIEW_START_HOUR
from app.database import get_db
from app.deps import get_current_user, get_current_user_optional
from app.models import Job, JobDay, JobDayAssignment, Queue, Status, User, Worker, WorkerLeave
from app.routers.settings import get_setting
from app.scheduling import (
    build_day_lanes,
    day_position,
    hour_labels,
    job_day_positions,
    leave_worker_ids_by_day,
    leave_worker_ids_for_day,
    week_label,
    week_start,
)
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()

WORKER_LEGEND_COLORS_NOTE = "Lane = who · left stripe = status · fill = worker (secondary)"


@router.get("/")
def root():
    return RedirectResponse("/week")


@router.post("/sync-now")
def sync_now(
    return_to: str = Form("/week"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    api_key = get_setting(db, "servicem8_api_key")
    separator = "&" if "?" in return_to else "?"
    if not api_key:
        return RedirectResponse(f"{return_to}{separator}synced=nokey", status_code=303)
    try:
        completion_queue_uuid = get_setting(db, "completion_queue_uuid")
        servicem8_sync.sync_jobs(db, api_key, completion_queue_uuid)
        booking_summary = servicem8_sync.resync_all_bookings(db, api_key)
        if booking_summary["cancelled"]:
            return RedirectResponse(
                f"{return_to}{separator}synced=ok&unbooked={booking_summary['cancelled']}", status_code=303
            )
        return RedirectResponse(f"{return_to}{separator}synced=ok", status_code=303)
    except Exception:
        logger.exception("Manual sync failed")
        return RedirectResponse(f"{return_to}{separator}synced=error", status_code=303)


def _sidebar_context(db: Session):
    # Queue and search filtering both happen client-side (see calendar.js) —
    # every unscheduled job is rendered once and instantly shown/hidden, no
    # reload needed to switch queues.
    queues = db.query(Queue).filter(Queue.watched.is_(True)).order_by(Queue.name).all()
    unscheduled_jobs = db.query(Job).filter(~Job.days.any()).order_by(Job.created_at.desc()).all()
    return {
        "queues": queues,
        "unscheduled_jobs": unscheduled_jobs,
    }


def _open_job_context(db: Session, job: int | None, day: int | None) -> dict:
    """Resolve the job/job-day the modal should open for. A block's URL
    always carries its own job_day_id (`day`), which is authoritative and
    unambiguous even for a multi-day job; `job` alone is a defensive
    fallback for links that don't specify a day."""
    open_job_day = db.get(JobDay, day) if day else None
    open_job = open_job_day.job if open_job_day else (db.get(Job, job) if job else None)
    return {
        "open_job": open_job,
        "open_job_day": open_job_day,
        "leave_worker_ids": leave_worker_ids_for_day(db, open_job_day.day) if open_job_day else set(),
    }


@router.get("/week")
def week_view(
    request: Request,
    start: str | None = None,
    job: int | None = None,
    day: int | None = None,
    leave_conflict: str | None = None,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if start:
        anchor = datetime.date.fromisoformat(start)
    else:
        anchor = datetime.date.today()
    monday = week_start(anchor)
    days = [monday + datetime.timedelta(days=i) for i in range(7)]

    workers = db.query(Worker).filter(Worker.active.is_(True)).order_by(Worker.id).all()
    leave_by_day = leave_worker_ids_by_day(db, days)

    day_data = []
    for d in days:
        lanes, lane_height = build_day_lanes(db, d, active_workers=workers, leave_ids=leave_by_day[d])
        day_data.append({"date": d, "lanes": lanes, "lane_height": lane_height})

    statuses = db.query(Status).order_by(Status.sort_order).all()

    ctx = {
        "request": request,
        "user": user,
        "view": "week",
        "hours": hour_labels(),
        "days": day_data,
        "week_label": week_label(monday),
        "prev_week": (monday - datetime.timedelta(days=7)).isoformat(),
        "next_week": (monday + datetime.timedelta(days=7)).isoformat(),
        "today": datetime.date.today(),
        "workers": workers,
        "statuses": statuses,
        "leave_conflict": leave_conflict,
        "start_hour": WEEK_VIEW_START_HOUR,
        "end_hour": WEEK_VIEW_END_HOUR,
        "print_default_date": monday.isoformat(),
    }
    ctx.update(_open_job_context(db, job, day))
    if user:
        ctx.update(_sidebar_context(db))
    return templates.TemplateResponse(request, "week.html", ctx)


@router.get("/day")
def day_view(
    request: Request,
    date: str | None = None,
    job: int | None = None,
    day: int | None = None,
    leave_conflict: str | None = None,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    d = datetime.date.fromisoformat(date) if date else datetime.date.today()
    workers = db.query(Worker).filter(Worker.active.is_(True)).order_by(Worker.id).all()
    lanes, lane_height = build_day_lanes(db, d, active_workers=workers)

    statuses = db.query(Status).order_by(Status.sort_order).all()

    ctx = {
        "request": request,
        "user": user,
        "view": "day",
        "hours": hour_labels(),
        "date": d,
        "lanes": lanes,
        "lane_height": lane_height,
        "day_label": d.strftime("%A %d %b %Y"),
        "prev_day": (d - datetime.timedelta(days=1)).isoformat(),
        "next_day": (d + datetime.timedelta(days=1)).isoformat(),
        "today": datetime.date.today(),
        "workers": workers,
        "statuses": statuses,
        "leave_conflict": leave_conflict,
        "start_hour": WEEK_VIEW_START_HOUR,
        "end_hour": WEEK_VIEW_END_HOUR,
        "print_default_date": d.isoformat(),
    }
    ctx.update(_open_job_context(db, job, day))
    if user:
        ctx.update(_sidebar_context(db))
    return templates.TemplateResponse(request, "day.html", ctx)


@router.get("/print/day")
def print_day(
    request: Request,
    date: str,
    worker: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Print/export view for a single day (spec §6.7) — no sidebar/nav chrome,
    just the day's worker columns, suitable for printing or browser print-to-PDF.
    Optionally filtered down to a single worker."""
    day = datetime.date.fromisoformat(date)
    workers = db.query(Worker).filter(Worker.active.is_(True)).order_by(Worker.id).all()
    lanes, lane_height = build_day_lanes(db, day, active_workers=workers)
    if worker:
        lanes = [lane for lane in lanes if lane["worker"].id == worker]
    statuses = db.query(Status).order_by(Status.sort_order).all()

    job_ids = {b["job"].id for lane in lanes for b in lane["blocks"]}
    worker_names = [lane["worker"].name for lane in lanes]

    ctx = {
        "request": request,
        "day": day,
        "lanes": lanes,
        "lane_height": lane_height,
        "hours": hour_labels(),
        "statuses": statuses,
        "job_count": len(job_ids),
        "worker_names": worker_names,
    }
    return templates.TemplateResponse(request, "print_day.html", ctx)


@router.get("/print/week")
def print_week(
    request: Request,
    start: str,
    worker: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Print/export view for a whole week — one column per day, optionally
    filtered to a single worker's jobs across the week."""
    anchor = datetime.date.fromisoformat(start)
    monday = week_start(anchor)
    days = [monday + datetime.timedelta(days=i) for i in range(7)]

    worker_obj = db.get(Worker, worker) if worker else None
    active_workers = db.query(Worker).filter(Worker.active.is_(True)).order_by(Worker.id).all()
    leave_by_day = leave_worker_ids_by_day(db, days)

    day_data = []
    job_ids: set[int] = set()
    for d in days:
        lanes, lane_height = build_day_lanes(db, d, active_workers=active_workers, leave_ids=leave_by_day[d])
        if worker:
            lanes = [lane for lane in lanes if lane["worker"].id == worker]
        for lane in lanes:
            for b in lane["blocks"]:
                job_ids.add(b["job"].id)
        day_data.append({"date": d, "lanes": lanes, "lane_height": lane_height})

    statuses = db.query(Status).order_by(Status.sort_order).all()

    ctx = {
        "request": request,
        "days": day_data,
        "today": datetime.date.today(),
        "hours": hour_labels(),
        "statuses": statuses,
        "week_label": week_label(monday),
        "worker_filter": worker_obj,
        "job_count": len(job_ids),
    }
    return templates.TemplateResponse(request, "print_week.html", ctx)


@router.get("/month")
def month_view(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    job: int | None = None,
    day: int | None = None,
    leave_conflict: str | None = None,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    today = datetime.date.today()
    year = year or today.year
    month = month or today.month

    cal = pycalendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    jobs_by_day: dict[datetime.date, list[JobDay]] = {}
    all_dates = [d for week in weeks for d in week]
    job_days = (
        db.query(JobDay)
        .options(
            selectinload(JobDay.assignments).selectinload(JobDayAssignment.worker),
            selectinload(JobDay.job).selectinload(Job.status),
        )
        .filter(JobDay.day.in_(all_dates))
        .order_by(JobDay.start_time.is_(None), JobDay.start_time)
        .all()
    )
    positions = job_day_positions(db, {jd.job_id for jd in job_days})
    day_badge_by_job_day_id = {jd.id: day_position(positions, jd.job_id, jd.day) for jd in job_days}
    for jd in job_days:
        jobs_by_day.setdefault(jd.day, []).append(jd)

    leave_by_day: dict[datetime.date, list[Worker]] = {}
    leave_rows = (
        db.query(WorkerLeave)
        .join(Worker)
        .filter(
            WorkerLeave.start_date <= all_dates[-1],
            WorkerLeave.end_date >= all_dates[0],
            Worker.active.is_(True),
        )
        .all()
    )
    for lv in leave_rows:
        for d in all_dates:
            if lv.start_date <= d <= lv.end_date:
                leave_by_day.setdefault(d, []).append(lv.worker)

    prev_month = (datetime.date(year, month, 1) - datetime.timedelta(days=1))
    next_month = (datetime.date(year, month, 28) + datetime.timedelta(days=7)).replace(day=1)

    workers = db.query(Worker).filter(Worker.active.is_(True)).order_by(Worker.id).all()
    statuses = db.query(Status).order_by(Status.sort_order).all()

    ctx = {
        "request": request,
        "user": user,
        "view": "month",
        "weeks": weeks,
        "jobs_by_day": jobs_by_day,
        "day_badge_by_job_day_id": day_badge_by_job_day_id,
        "leave_by_day": leave_by_day,
        "month_label": datetime.date(year, month, 1).strftime("%B %Y"),
        "current_month": month,
        "current_year": year,
        "today": today,
        "prev_year": prev_month.year,
        "prev_month": prev_month.month,
        "next_year": next_month.year,
        "next_month": next_month.month,
        "workers": workers,
        "statuses": statuses,
        "leave_conflict": leave_conflict,
        "print_default_date": (today if today.year == year and today.month == month else datetime.date(year, month, 1)).isoformat(),
    }
    ctx.update(_open_job_context(db, job, day))
    if user:
        ctx.update(_sidebar_context(db))
    return templates.TemplateResponse(request, "month.html", ctx)
