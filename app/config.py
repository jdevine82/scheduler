import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-secret-change-me")
DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "job_scheduler.db"))
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

SERVICEM8_API_KEY = os.environ.get("SERVICEM8_API_KEY", "")
SERVICEM8_POLL_INTERVAL_SECONDS = int(os.environ.get("SERVICEM8_POLL_INTERVAL_SECONDS", "300"))

WEEK_VIEW_START_HOUR = int(os.environ.get("WEEK_VIEW_START_HOUR", "6"))
WEEK_VIEW_END_HOUR = int(os.environ.get("WEEK_VIEW_END_HOUR", "18"))
