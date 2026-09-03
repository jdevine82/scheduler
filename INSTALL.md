# Installing Job Scheduler

Self-hosted job scheduling board for Border to Border, built with Python/FastAPI. Runs as a native process on a Proxmox VM or LXC container — no Docker required.

## Prerequisites

- Python 3.10 or newer
- A ServiceM8 account with API access (Settings → API Keys, in ServiceM8) — only needed once you're ready to connect live data; the app works fine locally without it first

## 1. Get the code onto the server

```bash
git clone https://github.com/jdevine82/scheduler.git job-scheduler
cd job-scheduler
```

(Or copy the files across some other way — there's nothing Git-specific about running the app.)

## 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set:

| Variable | Required | Notes |
|---|---|---|
| `SESSION_SECRET` | **Yes** | Random string used to sign login session cookies. Generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"` — never reuse the example value in production. |
| `DATABASE_PATH` | No | Defaults to `./job_scheduler.db`. Only change this if you want the database file somewhere else. |
| `SERVICEM8_API_KEY` | No | Can be left blank here and set later from the app itself (Settings → ServiceM8 connection) — that's the easier path, since it's stored per-install in the database rather than a file. |
| `SERVICEM8_POLL_INTERVAL_SECONDS` | No | Defaults to 300 (5 minutes). Also editable from Settings once running. |
| `WEEK_VIEW_START_HOUR` / `WEEK_VIEW_END_HOUR` | No | Defaults to 6am–6pm. Adjust to your typical work hours. |

`.env` is already excluded from version control — never commit it.

## 4. Create the database and the first admin login

```bash
.venv/bin/python -m app.seed
```

This creates the default status list (Loosely Planned, Booked with Customer, etc.) and prompts you to create the first admin username/password interactively. Run it again later and it'll skip anything that already exists — safe to re-run.

If you want some sample data to look at before connecting a real ServiceM8 account:

```bash
.venv/bin/python -m app.seed --demo
```

(Only meant for a first look — don't run `--demo` against a database that already has real workers, or it'll skip adding demo workers because some already exist, but this is generally safe to skip once you have real data.)

## 5. Run it

**For a quick look / development:**

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8420
```

Visit `http://<this-machine's-IP>:8420` and log in with the admin account you just created. `--host 0.0.0.0` makes it reachable from other devices on your network; use `127.0.0.1` instead if you only want it accessible from the same machine.

**For a permanent install (recommended for real use):** run it as a `systemd` service so it starts on boot and restarts automatically if it ever crashes.

1. Edit `deploy/job-scheduler.service` and update the `User`, `WorkingDirectory`, and `ExecStart` paths to match where you installed it.
2. Install and enable it:

   ```bash
   sudo cp deploy/job-scheduler.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now job-scheduler
   ```

3. Check it's running and watch the logs:

   ```bash
   sudo systemctl status job-scheduler
   sudo journalctl -u job-scheduler -f
   ```

## 6. Connect ServiceM8

Once logged in as an admin:

1. Settings → ServiceM8 connection → paste in your API key (generated in ServiceM8 under Settings → API Keys, with the scopes: `read_job_queues`, `manage_job_queues`, `read_jobs`, `manage_jobs`, `read_staff`, `read_schedule`, `manage_schedule`, `read_customers`) → Save → Test connection.
2. Settings → Queues → "Refresh queue list from ServiceM8" → toggle **Watch** on whichever queues hold jobs you want pulled into the sidebar.
3. Settings → Workers → add your team, and optionally link each one to their matching ServiceM8 staff member (only needed for the "Book in ServiceM8" write-back feature to work).
4. Click "Sync now" in the top bar, or just wait for the background poll (every `SERVICEM8_POLL_INTERVAL_SECONDS`).

See [USER_GUIDE.md](USER_GUIDE.md) for how to use the board day to day.

## Backing up

- **From the app**: Settings → Backup → "Download backup now" gives you a timestamped copy of the whole database whenever you want one.
- **At the host level** (recommended in addition to the above): since everything lives in the single SQLite file at `DATABASE_PATH`, a nightly Proxmox snapshot of the VM/container, or a simple cron job copying that file elsewhere, is enough for disaster recovery.

## Upgrading

```bash
git pull   # or otherwise update the code
.venv/bin/pip install -r requirements.txt
sudo systemctl restart job-scheduler   # if running as a service
```

The database schema is currently managed by hand (no migration tool) — if a future update adds new columns, the release notes will say so and give the exact command to run.

### Upgrading to multi-day jobs (schema change)

The update that added multi-day job support changed how scheduling is stored (jobs can now span several days, each with their own workers and times), which isn't compatible with the previous database schema. If your install hasn't gone live yet, the simplest path is to recreate the database from scratch rather than migrate it:

1. Stop the app: `sudo systemctl stop job-scheduler` (or Ctrl-C if running it directly).
2. Move or delete the existing database file and any journal alongside it: `rm job_scheduler.db job_scheduler.db-journal` (or `mv` them aside if you'd rather keep a copy).
3. `git pull` and reinstall dependencies as above.
4. Recreate the database and first admin login: `.venv/bin/python -m app.seed`.
5. Restart the app: `sudo systemctl start job-scheduler`.

If your install already has real data you need to keep, don't run this — get in touch before upgrading so the data can be migrated instead of recreated.
