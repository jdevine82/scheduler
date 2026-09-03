"""Bootstrap the database: default statuses, and a first admin user if none exists.

Usage:
    python -m app.seed                          # statuses + admin only
    python -m app.seed --demo                   # also adds sample workers/jobs for visual testing
"""

import argparse
import datetime
import getpass
import sys

from app.database import Base, SessionLocal, engine
from app.models import Job, JobDay, JobDayAssignment, Status, User, Worker
from app.security import hash_password

DEFAULT_STATUSES = [
    ("Loosely Planned", "#6B7684", False),
    ("Booked with Customer", "#0F766E", True),
    ("Urgent", "#DC2626", False),
    ("On Hold", "#B45309", False),
    ("Completed", "#15803D", False),
    ("Cancelled", "#6B7280", False),
]

DEMO_WORKERS = [
    ("Dave", "#2563EB"),
    ("Mick", "#7C3AED"),
    ("Sarah", "#0891B2"),
    ("Tom", "#DB2777"),
    ("Jason", "#65A30D"),
]


def seed_statuses(db) -> dict[str, Status]:
    existing = {s.name: s for s in db.query(Status).all()}
    for i, (name, color, locked) in enumerate(DEFAULT_STATUSES):
        if name not in existing:
            s = Status(name=name, color_hex=color, sort_order=i, is_locked=locked)
            db.add(s)
            existing[name] = s
    db.commit()
    return {s.name: s for s in db.query(Status).all()}


def seed_admin(db) -> None:
    if db.query(User).count() > 0:
        return
    print("No users exist yet — create the first admin account.")
    username = input("Admin username: ").strip() or "admin"
    display_name = input("Display name [Admin]: ").strip() or "Admin"
    password = getpass.getpass("Password: ")
    if not password:
        print("Password cannot be empty.", file=sys.stderr)
        sys.exit(1)
    db.add(
        User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
            is_admin=True,
            active=True,
        )
    )
    db.commit()
    print(f"Created admin user '{username}'.")


def seed_demo(db, statuses: dict[str, Status]) -> None:
    if db.query(Worker).count() > 0:
        print("Workers already exist — skipping demo data.")
        return
    workers = {}
    for name, color in DEMO_WORKERS:
        w = Worker(name=name, color_hex=color, active=True)
        db.add(w)
        workers[name] = w
    db.commit()

    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())

    demo_jobs = [
        ("3987", "D. Harrow", "Split system fault, no cooling — return to replace valve and retest.",
         monday, datetime.time(8, 0), datetime.time(10, 0), "Booked with Customer", ["Dave"]),
        ("4002", "Mid West Cotton", "Switchboard warning light — urgent callout.",
         monday, datetime.time(10, 0), datetime.time(10, 30), "Urgent", ["Dave"]),
        ("3995", "Bland Shire Council", "Solar panel inspection, two-person job.",
         monday, datetime.time(13, 0), datetime.time(15, 0), "Loosely Planned", ["Mick", "Sarah"]),
        ("4008", "Barellan Grain Store", "3-phase board upgrade.",
         monday + datetime.timedelta(days=1), datetime.time(9, 0), datetime.time(12, 0), "Booked with Customer", ["Dave"]),
        ("4023", "West Wyalong RSL", "Ripple test.",
         monday + datetime.timedelta(days=2), datetime.time(13, 0), datetime.time(15, 0), "On Hold", ["Dave"]),
        ("3960", "R. Byrne", "Annual solar inverter check.",
         monday + datetime.timedelta(days=4), datetime.time(9, 0), datetime.time(9, 30), "Completed", ["Jason"]),
    ]

    for i, (num, cust, desc, day, start, end, status_name, worker_names) in enumerate(demo_jobs):
        job = Job(
            servicem8_uuid=f"demo-{num}",
            job_number=num,
            customer_name=cust,
            description=desc,
            queue_name="Work Bay",
            status_id=statuses[status_name].id,
        )
        db.add(job)
        db.flush()
        job_day = JobDay(job_id=job.id, day=day, start_time=start, end_time=end)
        db.add(job_day)
        db.flush()
        for wn in worker_names:
            db.add(JobDayAssignment(job_day_id=job_day.id, worker_id=workers[wn].id))

    db.add(
        Job(
            servicem8_uuid="demo-4021",
            job_number="4021",
            customer_name="R. Fenwick",
            description="Split system fault, no cooling — Clear Ridge Rd",
            queue_name="Work Bay",
            status_id=statuses["Loosely Planned"].id,
        )
    )
    db.commit()
    print("Added demo workers and jobs.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="also add sample workers/jobs")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        statuses = seed_statuses(db)
        seed_admin(db)
        if args.demo:
            seed_demo(db, statuses)
    finally:
        db.close()


if __name__ == "__main__":
    main()
