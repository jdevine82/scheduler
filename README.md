# Job Scheduler

A self-hosted job scheduling board for **Border to Border**, built for pulling unscheduled jobs out of ServiceM8, dragging them onto a visual weekly calendar, assigning workers, and booking confirmed dates back into ServiceM8 with one click.

- **Backend**: Python, FastAPI, SQLite
- **Frontend**: Server-rendered Jinja2 templates + vanilla JS (drag-and-drop, no framework)
- **Deployment**: runs as a native process (systemd) on a Proxmox VM/LXC — no Docker
- **Repo**: [github.com/jdevine82/scheduler](https://github.com/jdevine82/scheduler)

## Getting started

- **[INSTALL.md](INSTALL.md)** — set up, configure, and run the app (dev and production)
- **[USER_GUIDE.md](USER_GUIDE.md)** — how to use the board day to day

## Project layout

```
app/
  models.py, database.py     — SQLAlchemy models and DB session
  routers/                   — FastAPI route handlers (auth, calendar, jobs, reports, settings)
  scheduling.py               — week/day lane-building logic shared by the calendar and print views
  servicem8.py, sync.py       — ServiceM8 API client and sync/reconciliation logic
  templates/                  — Jinja2 templates
  static/                     — CSS and JS
  seed.py                     — bootstraps default statuses and the first admin user
deploy/job-scheduler.service   — systemd unit file for production
files/                         — original design spec, style guide, and mockups this app was built from
```

## Status

Feature-complete proof of concept: multi-user auth (with a public read-only calendar for logged-out visitors), month/week/day calendar with drag-and-drop, ServiceM8 sync (read + booking write-back), worker holiday/leave tracking with scheduling conflict prevention, a weekly completion report, print/export, and an in-app database backup/restore. See `files/JOB_SCHEDULER_SPEC.md` for the original build spec.
