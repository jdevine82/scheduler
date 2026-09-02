import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.reports import incomplete_jobs_for_week
from app.scheduling import week_label, week_start
from app.templating import templates

router = APIRouter()


@router.get("/report")
def report_view(
    request: Request,
    start: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    anchor = datetime.date.fromisoformat(start) if start else datetime.date.today()
    monday = week_start(anchor)

    groups = incomplete_jobs_for_week(db, monday)

    ctx = {
        "request": request,
        "user": user,
        "groups": groups,
        "week_label": week_label(monday),
        "prev_week": (monday - datetime.timedelta(days=7)).isoformat(),
        "next_week": (monday + datetime.timedelta(days=7)).isoformat(),
        "today": datetime.date.today(),
        "start": monday.isoformat(),
    }
    return templates.TemplateResponse(request, "report.html", ctx)


@router.get("/print/report")
def print_report(
    request: Request,
    start: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Print/export view for the weekly report — no chrome, suitable for
    printing or browser print-to-PDF, same pattern as print_day/print_week."""
    anchor = datetime.date.fromisoformat(start) if start else datetime.date.today()
    monday = week_start(anchor)

    groups = incomplete_jobs_for_week(db, monday)

    ctx = {
        "request": request,
        "groups": groups,
        "week_label": week_label(monday),
        "start": monday.isoformat(),
    }
    return templates.TemplateResponse(request, "print_report.html", ctx)
