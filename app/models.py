import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now() -> datetime.datetime:
    return datetime.datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=now)
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    color_hex: Mapped[str] = mapped_column(String(7))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=now)

    # Optional link to a ServiceM8 Staff member, used only for the staff_uuid
    # that booking write-back appears to require — the worker list itself
    # stays local per spec §3, this doesn't drive it.
    servicem8_staff_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    assignments: Mapped[list["JobAssignment"]] = relationship(back_populates="worker")
    leave_periods: Mapped[list["WorkerLeave"]] = relationship(
        back_populates="worker", cascade="all, delete-orphan"
    )


class WorkerLeave(Base):
    __tablename__ = "worker_leave"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"))
    start_date: Mapped[datetime.date] = mapped_column(Date)
    end_date: Mapped[datetime.date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=now)

    worker: Mapped["Worker"] = relationship(back_populates="leave_periods")


class Status(Base):
    __tablename__ = "statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    color_hex: Mapped[str] = mapped_column(String(7))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    jobs: Mapped[list["Job"]] = relationship(back_populates="status")


class Queue(Base):
    __tablename__ = "queues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    servicem8_queue_uuid: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    watched: Mapped[bool] = mapped_column(Boolean, default=False)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    servicem8_uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    job_number: Mapped[str] = mapped_column(String(32))
    customer_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    queue_name: Mapped[str] = mapped_column(String(128), default="")

    # A manually-added task with no ServiceM8 job behind it — schedules,
    # edits, and deletes like any other job, but can never be booked or
    # touched by ServiceM8 sync (servicem8_uuid is a local placeholder).
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)

    status_id: Mapped[int] = mapped_column(ForeignKey("statuses.id"))
    status: Mapped["Status"] = relationship(back_populates="jobs")

    day: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[datetime.time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[datetime.time | None] = mapped_column(Time, nullable=True)

    servicem8_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    servicem8_last_synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    servicem8_activity_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Job moved out of a watched ServiceM8 queue since import — surfaced, not deleted.
    flagged_missing_from_queue: Mapped[bool] = mapped_column(Boolean, default=False)

    last_modified_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_modified_by: Mapped["User | None"] = relationship()
    last_modified_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=now, onupdate=now)

    assignments: Mapped[list["JobAssignment"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobAssignment(Base):
    __tablename__ = "job_assignments"
    __table_args__ = (UniqueConstraint("job_id", "worker_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"))

    job: Mapped["Job"] = relationship(back_populates="assignments")
    worker: Mapped["Worker"] = relationship(back_populates="assignments")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
