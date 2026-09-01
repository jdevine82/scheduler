import calendar as pycalendar
import datetime
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import sync as servicem8_sync
from app.config import WEEK_VIEW_END_HOUR, WEEK_VIEW_START_HOUR
from app.database import get_db
from app.deps import get_current_user
from app.models import Job, Queue, Status, User, Worker
from app.routers.settings import get_setting
from app.scheduling import build_day_lanes, hour_labels, week_start
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()

WORKER_LEGEND_COLORS_NOTE = "Lane = who · left stripe = status · fill = worker (secondary)"


@router.get("/")
def root(user: User = Depends(get_current_user)):
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
        servicem8_sync.sync_jobs(db, api_key)
        booking_summary = servicem8_sync.resync_all_bookings(db, api_key)
        if booking_summary["cancelled"]:
            return RedirectResponse(
                f"{return_to}{separator}synced=ok&unbooked={booking_summary['cancelled']}", status_code=303
            )
        return RedirectResponse(f"{return_to}{separator}synced=ok", status_code=303)
    except Exception:
        logger.exception("Manual sync failed")
        return RedirectResponse(f"{return_to}{separator}synced=error", status_code=303)


def _sidebar_context(db: Session, queue_filter: str | None):
    queues = db.query(Queue).filter(Queue.watched.is_(True)).order_by(Queue.name).all()
    q = db.query(Job).filter(Job.day.is_(None))
    if queue_filter:
        q = q.filter(Job.queue_name == queue_filter)
    unscheduled_jobs = q.order_by(Job.created_at.desc()).all()
    return {
        "queues": queues,
        "unscheduled_jobs": unscheduled_jobs,
        "selected_queue": queue_filter or "",
    }


@router.get("/week")
def week_view(
    request: Request,
    start: str | None = None,
    queue: str | None = None,
    job: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if start:
        anchor = datetime.date.fromisoformat(start)
    else:
        anchor = datetime.date.today()
    monday = week_start(anchor)
    days = [monday + datetime.timedelta(days=i) for i in range(7)]

    day_data = []
    for d in days:
        lanes, lane_height = build_day_lanes(db, d)
        day_data.append({"date": d, "lanes": lanes, "lane_height": lane_height})

    workers = db.query(Worker).filter(Worker.active.is_(True)).order_by(Worker.id).all()
    statuses = db.query(Status).order_by(Status.sort_order).all()

    ctx = {
        "request": request,
        "user": user,
        "view": "week",
        "hours": hour_labels(),
        "days": day_data,
        "week_label": f"{monday.strftime('%d %b')} – {(monday + datetime.timedelta(days=6)).strftime('%d %b %Y')}",
        "prev_week": (monday - datetime.timedelta(days=7)).isoformat(),
        "next_week": (monday + datetime.timedelta(days=7)).isoformat(),
        "today": datetime.date.today(),
        "workers": workers,
        "statuses": statuses,
        "open_job": db.get(Job, job) if job else None,
        "start_hour": WEEK_VIEW_START_HOUR,
        "end_hour": WEEK_VIEW_END_HOUR,
        "print_default_date": monday.isoformat(),
    }
    ctx.update(_sidebar_context(db, queue))
    return templates.TemplateResponse(request, "week.html", ctx)


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
    lanes, lane_height = build_day_lanes(db, day)
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

    day_data = []
    job_ids: set[int] = set()
    for d in days:
        lanes, lane_height = build_day_lanes(db, d)
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
        "week_label": f"{monday.strftime('%d %b')} – {(monday + datetime.timedelta(days=6)).strftime('%d %b %Y')}",
        "worker_filter": worker_obj,
        "job_count": len(job_ids),
    }
    return templates.TemplateResponse(request, "print_week.html", ctx)


@router.get("/month")
def month_view(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    queue: str | None = None,
    job: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = datetime.date.today()
    year = year or today.year
    month = month or today.month

    cal = pycalendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    jobs_by_day: dict[datetime.date, list[Job]] = {}
    all_dates = [d for week in weeks for d in week]
    jobs = (
        db.query(Job)
        .filter(Job.day.in_(all_dates))
        .order_by(Job.start_time.is_(None), Job.start_time)
        .all()
    )
    for j in jobs:
        jobs_by_day.setdefault(j.day, []).append(j)

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
        "open_job": db.get(Job, job) if job else None,
        "print_default_date": (today if today.year == year and today.month == month else datetime.date(year, month, 1)).isoformat(),
    }
    ctx.update(_sidebar_context(db, queue))
    return templates.TemplateResponse(request, "month.html", ctx)
