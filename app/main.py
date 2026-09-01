import asyncio
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import sync
from app.config import SESSION_SECRET
from app.database import Base, SessionLocal, engine
from app.routers import auth, calendar, jobs, settings
from app.routers.settings import get_setting

logger = logging.getLogger(__name__)

app = FastAPI(title="Job Scheduler")

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=False)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(calendar.router)
app.include_router(jobs.router)
app.include_router(settings.router)


async def _poll_loop():
    while True:
        db = SessionLocal()
        try:
            api_key = get_setting(db, "servicem8_api_key")
            interval = int(get_setting(db, "servicem8_poll_interval_seconds", "300"))
            if api_key:
                try:
                    summary = await asyncio.to_thread(sync.sync_jobs, db, api_key)
                    logger.info("ServiceM8 sync: %s", summary)
                except Exception:
                    logger.exception("ServiceM8 background sync failed")
        finally:
            db.close()
        await asyncio.sleep(max(interval, 60))


@app.on_event("startup")
async def on_startup():
    Base.metadata.create_all(bind=engine)
    asyncio.create_task(_poll_loop())
