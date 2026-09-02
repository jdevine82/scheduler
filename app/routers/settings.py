import datetime
import logging
import shutil
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import servicem8, sync
from app.config import DATABASE_PATH
from app.database import engine, get_db
from app.deps import require_admin
from app.models import JobAssignment, Queue, Setting, Status, User, Worker, WorkerLeave
from app.security import hash_password
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings")

BACKUPS_DIR = Path(DATABASE_PATH).resolve().parent / "backups"

WORKER_PALETTE = [
    "#2563EB", "#7C3AED", "#0891B2", "#DB2777",
    "#65A30D", "#B45309", "#4F46E5", "#A21CAF",
]

DEFAULT_STATUSES = [
    ("Loosely Planned", "#6B7684", False),
    ("Booked with Customer", "#0F766E", True),
    ("Urgent", "#DC2626", False),
    ("On Hold", "#B45309", False),
    ("Completed", "#15803D", False),
    ("Cancelled", "#6B7280", False),
]


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def _base_ctx(request: Request, user: User, active_tab: str) -> dict:
    return {"request": request, "user": user, "active_tab": active_tab}


@router.get("")
def settings_index(user: User = Depends(require_admin)):
    return RedirectResponse("/settings/connection")


@router.get("/connection")
def connection_get(
    request: Request,
    test: str | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ctx = _base_ctx(request, user, "connection")
    ctx["api_key_set"] = bool(get_setting(db, "servicem8_api_key"))
    ctx["poll_interval"] = get_setting(db, "servicem8_poll_interval_seconds", "300")
    ctx["test_result"] = test
    return templates.TemplateResponse(request, "settings/connection.html", ctx)


@router.post("/connection")
def connection_post(
    api_key: str = Form(""),
    poll_interval: str = Form("300"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if api_key:
        set_setting(db, "servicem8_api_key", api_key)
    set_setting(db, "servicem8_poll_interval_seconds", poll_interval)
    db.commit()
    return RedirectResponse("/settings/connection", status_code=303)


@router.post("/connection/test")
def connection_test(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    api_key = get_setting(db, "servicem8_api_key")
    ok = bool(api_key) and servicem8.test_connection(api_key)
    return RedirectResponse(f"/settings/connection?test={'ok' if ok else 'fail'}", status_code=303)


@router.get("/queues")
def queues_get(
    request: Request,
    refreshed: str | None = None,
    synced: str | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ctx = _base_ctx(request, user, "queues")
    ctx["queues"] = db.query(Queue).order_by(Queue.name).all()
    ctx["refreshed"] = refreshed
    ctx["synced"] = synced
    ctx["completion_queue_uuid"] = get_setting(db, "completion_queue_uuid")
    return templates.TemplateResponse(request, "settings/queues.html", ctx)


@router.post("/queues/{queue_id}/toggle")
def queue_toggle(queue_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.get(Queue, queue_id)
    if q:
        q.watched = not q.watched
        db.commit()
    return RedirectResponse("/settings/queues", status_code=303)


@router.post("/queues/completion")
def set_completion_queue(
    completion_queue_uuid: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    set_setting(db, "completion_queue_uuid", completion_queue_uuid)
    db.commit()
    return RedirectResponse("/settings/queues", status_code=303)


@router.post("/queues/refresh")
def queues_refresh(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    api_key = get_setting(db, "servicem8_api_key")
    if not api_key:
        return RedirectResponse("/settings/queues?refreshed=nokey", status_code=303)
    try:
        added = sync.refresh_queues(db, api_key)
        return RedirectResponse(f"/settings/queues?refreshed={added}", status_code=303)
    except Exception:
        return RedirectResponse("/settings/queues?refreshed=error", status_code=303)


@router.post("/queues/sync")
def queues_sync_now(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    api_key = get_setting(db, "servicem8_api_key")
    if not api_key:
        return RedirectResponse("/settings/queues?synced=nokey", status_code=303)
    try:
        completion_queue_uuid = get_setting(db, "completion_queue_uuid")
        summary = sync.sync_jobs(db, api_key, completion_queue_uuid)
        return RedirectResponse(f"/settings/queues?synced={summary['added']}", status_code=303)
    except Exception:
        return RedirectResponse("/settings/queues?synced=error", status_code=303)


@router.get("/statuses")
def statuses_get(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    ctx = _base_ctx(request, user, "statuses")
    ctx["statuses"] = db.query(Status).order_by(Status.sort_order).all()
    return templates.TemplateResponse(request, "settings/statuses.html", ctx)


@router.post("/statuses")
def status_create(
    name: str = Form(...),
    color_hex: str = Form("#6B7684"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    max_order = db.query(Status).count()
    db.add(Status(name=name, color_hex=color_hex, sort_order=max_order, is_locked=False))
    db.commit()
    return RedirectResponse("/settings/statuses", status_code=303)


@router.post("/statuses/{status_id}/update")
def status_update(
    status_id: int,
    name: str = Form(...),
    color_hex: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    s = db.get(Status, status_id)
    if s and not (s.is_locked and name != s.name):
        s.name = name
        s.color_hex = color_hex
        db.commit()
    return RedirectResponse("/settings/statuses", status_code=303)


@router.post("/statuses/{status_id}/delete")
def status_delete(status_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Status, status_id)
    if s and not s.is_locked:
        db.delete(s)
        db.commit()
    return RedirectResponse("/settings/statuses", status_code=303)


@router.get("/workers")
def workers_get(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    ctx = _base_ctx(request, user, "workers")
    ctx["workers"] = db.query(Worker).order_by(Worker.id).all()

    api_key = get_setting(db, "servicem8_api_key")
    ctx["staff_list"] = []
    ctx["staff_fetch_error"] = None
    if api_key:
        try:
            ctx["staff_list"] = servicem8.fetch_staff(api_key)
        except Exception:
            ctx["staff_fetch_error"] = "Couldn't reach ServiceM8 to load staff — check the connection under Settings."

    return templates.TemplateResponse(request, "settings/workers.html", ctx)


@router.post("/workers")
def worker_create(user: User = Depends(require_admin), db: Session = Depends(get_db), name: str = Form(...)):
    existing_count = db.query(Worker).count()
    color = WORKER_PALETTE[existing_count % len(WORKER_PALETTE)]
    db.add(Worker(name=name, color_hex=color, active=True))
    db.commit()
    return RedirectResponse("/settings/workers", status_code=303)


@router.post("/workers/{worker_id}/update")
def worker_update(
    worker_id: int,
    name: str = Form(...),
    color_hex: str = Form(...),
    servicem8_staff_uuid: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    w = db.get(Worker, worker_id)
    if w:
        w.name = name
        w.color_hex = color_hex
        w.servicem8_staff_uuid = servicem8_staff_uuid or None
        db.commit()
    return RedirectResponse("/settings/workers", status_code=303)


@router.post("/workers/{worker_id}/toggle-active")
def worker_toggle_active(worker_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    w = db.get(Worker, worker_id)
    if w:
        w.active = not w.active
        db.commit()
    return RedirectResponse("/settings/workers", status_code=303)


@router.post("/workers/{worker_id}/delete")
def worker_delete(worker_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    w = db.get(Worker, worker_id)
    if w:
        db.query(JobAssignment).filter(JobAssignment.worker_id == worker_id).delete()
        db.delete(w)
        db.commit()
    return RedirectResponse("/settings/workers", status_code=303)


@router.get("/holidays")
def holidays_get(
    request: Request,
    error: str | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ctx = _base_ctx(request, user, "holidays")
    ctx["leave_periods"] = (
        db.query(WorkerLeave).join(Worker).order_by(WorkerLeave.start_date.desc()).all()
    )
    ctx["workers"] = db.query(Worker).filter(Worker.active.is_(True)).order_by(Worker.name).all()
    ctx["error"] = error
    return templates.TemplateResponse(request, "settings/holidays.html", ctx)


@router.post("/holidays")
def holiday_create(
    worker_id: int = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    start = datetime.date.fromisoformat(start_date)
    end = datetime.date.fromisoformat(end_date)
    if end < start:
        return RedirectResponse("/settings/holidays?error=daterange", status_code=303)
    db.add(WorkerLeave(worker_id=worker_id, start_date=start, end_date=end, reason=reason))
    db.commit()
    return RedirectResponse("/settings/holidays", status_code=303)


@router.post("/holidays/{leave_id}/delete")
def holiday_delete(leave_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    h = db.get(WorkerLeave, leave_id)
    if h:
        db.delete(h)
        db.commit()
    return RedirectResponse("/settings/holidays", status_code=303)


@router.get("/users")
def users_get(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    ctx = _base_ctx(request, user, "users")
    ctx["users"] = db.query(User).order_by(User.id).all()
    return templates.TemplateResponse(request, "settings/users.html", ctx)


@router.post("/users")
def user_create(
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    is_admin: str = Form(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    db.add(
        User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
            is_admin=bool(is_admin),
            active=True,
        )
    )
    db.commit()
    return RedirectResponse("/settings/users", status_code=303)


@router.post("/users/{user_id}/toggle-active")
def user_toggle_active(user_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target and target.id != user.id:
        target.active = not target.active
        db.commit()
    return RedirectResponse("/settings/users", status_code=303)


@router.post("/users/{user_id}/toggle-admin")
def user_toggle_admin(user_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target and target.id != user.id:
        target.is_admin = not target.is_admin
        db.commit()
    return RedirectResponse("/settings/users", status_code=303)


@router.post("/users/{user_id}/reset-password")
def user_reset_password(
    user_id: int,
    new_password: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target:
        target.password_hash = hash_password(new_password)
        db.commit()
    return RedirectResponse("/settings/users", status_code=303)


def _is_valid_job_scheduler_db(path: Path) -> bool:
    """Sanity-check an uploaded file before it's allowed to replace the live
    database: real SQLite file, with the tables this app expects."""
    try:
        with open(path, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                return False
        conn = sqlite3.connect(path)
        try:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        finally:
            conn.close()
        return {"jobs", "workers", "users", "statuses"}.issubset(tables)
    except sqlite3.Error:
        return False


@router.get("/backup")
def backup_get(
    request: Request,
    restored: str | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ctx = _base_ctx(request, user, "backup")
    ctx["restored"] = restored
    ctx["pre_restore_backups"] = (
        sorted((p.name for p in BACKUPS_DIR.glob("pre-restore-*.db")), reverse=True)
        if BACKUPS_DIR.exists()
        else []
    )
    return templates.TemplateResponse(request, "settings/backup.html", ctx)


@router.get("/backup/download")
def backup_download(user: User = Depends(require_admin)):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return FileResponse(
        DATABASE_PATH,
        filename=f"job_scheduler_backup_{timestamp}.db",
        media_type="application/octet-stream",
    )


@router.post("/backup/restore")
async def backup_restore(
    backup_file: UploadFile,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    upload_tmp_path = BACKUPS_DIR / f"upload-tmp-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.db"

    with open(upload_tmp_path, "wb") as f:
        shutil.copyfileobj(backup_file.file, f)

    if not _is_valid_job_scheduler_db(upload_tmp_path):
        upload_tmp_path.unlink(missing_ok=True)
        return RedirectResponse("/settings/backup?restored=invalid", status_code=303)

    # Safety net: keep a copy of what's about to be overwritten, so a mistaken
    # restore can itself be undone (spec §7 calls for backups generally; this
    # is the one taken automatically right before a destructive restore).
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    pre_restore_path = BACKUPS_DIR / f"pre-restore-{timestamp}.db"
    shutil.copy2(DATABASE_PATH, pre_restore_path)

    # Close every pooled connection before swapping the file out from under
    # them — SQLAlchemy will transparently open fresh connections to the
    # restored file on the next request.
    db.close()
    engine.dispose()

    try:
        shutil.move(str(upload_tmp_path), DATABASE_PATH)
    except OSError:
        logger.exception("Failed to move restored database into place")
        return RedirectResponse("/settings/backup?restored=error", status_code=303)

    return RedirectResponse("/settings/backup?restored=ok", status_code=303)
