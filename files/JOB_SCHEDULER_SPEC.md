# Job Scheduler — Build Spec
### (Border to Border)

A self-hosted job scheduling board that pulls unscheduled jobs out of ServiceM8, lets you drag them onto a calendar and assign them to workers, and writes the booking back to ServiceM8 when confirmed. Branded for Border to Border — logo and usage detailed in `STYLE_GUIDE.md`; asset at `assets/border-to-border-logo.png`.

**Files in this handoff, and what each is for:**
- `JOB_SCHEDULER_SPEC.md` (this file) — behaviour, data model, ServiceM8 integration. The source of truth.
- `STYLE_GUIDE.md` — design tokens (colors, type, spacing, components) — light, Pico-CSS-inspired theme.
- `mockup.html` / `mockup_edit_job.html` — working HTML/CSS mockups of the week view and the job edit modal. Point Claude Code at these directly rather than describing the layout in prose — it can read the exact markup and CSS variables and reuse them, which is more reliable than reconstructing a design from a description.
- `print_day.html` / `print_day_example.pdf` — the day print-out layout (§6.7) as HTML and a rendered PDF example, for the single-day printable/exportable view.
- `screenshots/` — rendered PNGs of the three mockups above, for a quick visual sanity-check without needing to open/run the HTML.

Status: draft spec, ready for build. Confidence noted per section — sections marked **[ASSUMPTION]** are decisions made on your behalf that should be double-checked before or during build.

---

## 1. Purpose

Jason (electrician/QS, HVAC, solar — West Wyalong, NSW) currently has jobs sitting unscheduled in ServiceM8 queues. This app gives a single visual board to:

- See a month at a glance, and drill into a week with real start/end times.
- Pull unscheduled jobs from chosen ServiceM8 queues into a sidebar.
- Drag jobs onto a day/time slot and assign one or more workers.
- See each worker's day fill up as color-coded blocks stack underneath their name.
- Track a job's planning status (loosely planned → booked with customer → etc.) independently of ServiceM8, until it's confirmed.
- Push the confirmed booking back into ServiceM8 with one click.

---

## 2. Tech Stack & Deployment

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI |
| Database | SQLite (single file, on local disk) |
| Frontend | Server-rendered templates (Jinja2) + vanilla JS for drag-and-drop and calendar interactivity — no heavy JS framework needed for this scope |
| Auth | Multiple named users, each with their own username/password. Server-side session cookie per login. Passwords hashed (e.g. bcrypt/argon2), never stored plain. A simple `is_admin` flag on each user gates access to Settings (queues, statuses, user management) — everyone else can use the board but not reconfigure it. **[ASSUMPTION — confirm whether all logged-in users should be able to edit any job, or only their own/assigned jobs; currently assumed: anyone logged in can edit any job, tracked via the last-modified record below]** |
| Deployment | **Runs directly on a Proxmox VM or LXC container — no Docker.** Installed as a standard Python app (virtualenv) with a `systemd` service managing the process, so it starts on boot and restarts on failure like any other native service. **[ASSUMPTION — an LXC container is the lighter-weight Proxmox-native option and is assumed here; if you'd rather it run in a full VM, the install steps are effectively identical, just say the word]** |
| Scheduling of ServiceM8 sync | Background polling task inside the app (e.g. every 5 minutes) rather than webhooks, to keep things simple and not require a public HTTPS endpoint |

**Why polling instead of webhooks:** ServiceM8 webhooks need a publicly reachable HTTPS URL. Since this runs on your local Proxmox network, polling avoids exposing anything to the internet. If you later want instant sync, this can be upgraded to webhooks with a reverse proxy.

---

## 3. ServiceM8 Integration

Confirmed from ServiceM8's developer docs (developer.servicem8.com):

- **Auth**: Private Application API Key. Sent as `X-API-Key` header on every request. Generated in ServiceM8 under Settings → API Keys. No OAuth needed for a single-account internal tool.
- **Scopes to request when generating the key**: `read_job_queues`, `manage_job_queues`, `read_jobs`, `manage_jobs`, `read_staff`, `read_schedule`, `manage_schedule`, `read_customers`.

### Objects used

| ServiceM8 object | Used for |
|---|---|
| `JobQueue` | The "folders" jobs sit in before scheduling. Queue list is configurable in-app (see §6.6) rather than hardcoded, so it stays in sync if queue names change in ServiceM8. |
| `Job` | Source of job number, customer/company reference, and job description. |
| `Company` | Resolves the customer name linked to a job. |
| `Staff` | **[ASSUMPTION]** Not used to drive the worker list — workers are managed inside this app (see §4), not synced from ServiceM8 Staff. If you'd rather the worker list *be* ServiceM8 Staff, flag this and it changes the data model slightly. |
| `JobActivity` (`activity_was_scheduled = 1`) | Used when writing the booking back — this is how ServiceM8 represents a "Scheduled Booking." |

### Fields pulled from each ServiceM8 job

Per your instruction, kept deliberately minimal:
- Job Number
- Customer Name (via linked Company)
- Job Description

### Sync behaviour

1. On each poll cycle, fetch jobs in the queues configured in Settings (§6.6).
2. New jobs not already in the local DB are added to the sidebar as unscheduled.
3. Jobs that have moved out of the watched queues in ServiceM8 (e.g. someone manually changed them) are flagged, not silently deleted — surfaced in-app so nothing gets lost.
4. Local scheduling data (assigned worker, day, time, status) is never overwritten by sync — sync only brings in *new* unscheduled jobs, it doesn't touch jobs you've already planned.

### Booking write-back

When you click **"Book in ServiceM8"** on a job:

1. The app creates/updates a `JobActivity` on that Job with `activity_was_scheduled = 1` and the date/start/end time set from the block's position on the calendar.
2. The app sets the job's status (local) to **Booked with Customer** automatically — this is a hard rule per your instruction: booking in ServiceM8 always forces this status, regardless of what it was before.
3. Because "Booked with Customer" is meant to represent "the customer has this date locked in," moving it to any other status afterward (e.g. Completed) requires an explicit separate action from you in this app — the app will never auto-change it away from Booked with Customer on its own.

---

## 4. Data Model (local SQLite)

```
User
  id, username, password_hash, display_name, is_admin (bool), active (bool),
  created_at, last_login_at

Worker
  id, name, color_hex, active (bool), created_at

Job
  id, servicem8_uuid, job_number, customer_name, description,
  queue_name (at time of import),
  status_id (FK → Status),
  day (date, nullable until scheduled),
  start_time (nullable),
  end_time (nullable),
  servicem8_booked (bool),
  servicem8_last_synced_at,
  last_modified_by (FK → User, nullable),
  last_modified_at,
  created_at, updated_at

JobAssignment  (many-to-many: a job can have multiple workers)
  id, job_id (FK), worker_id (FK)

Status
  id, name, color_hex, sort_order, is_locked (bool)
  -- is_locked = true for "Booked with Customer" so it can't be deleted from Settings,
  -- since the booking write-back logic depends on it existing

Queue
  id, servicem8_queue_uuid, name, watched (bool)
  -- editable in Settings; "watched" queues are the ones polled for new jobs

Setting
  key, value   -- for ServiceM8 API key, poll interval, etc.
```

**Tracking "who last touched a job":** every write to a `Job` (status change, reschedule, reassignment, booking) updates `last_modified_by` and `last_modified_at` to the currently logged-in user and now. This is shown as a small breadcrumb line in the job detail modal (e.g. "Last edited by Sarah · 2 hours ago") and, per your earlier decision, alongside the ServiceM8 booking indicator. **[ASSUMPTION]** This is a single "last touched" record, not a full change history — if you'd also like a scrollable audit log of every past change (who changed the status from what to what, and when), that's a bigger addition (a separate `JobHistory` table logging each change) — flag it if you want that in scope for v1 rather than a later enhancement.

---

## 5. Statuses (default seed list — editable in Settings)

| Status | Notes |
|---|---|
| Loosely Planned | Default for a job once it's dragged onto a day but nothing confirmed |
| Booked with Customer | **Locked status** — cannot be renamed/deleted, because "Book in ServiceM8" always sets this |
| Urgent | |
| On Hold | |
| Completed | |
| Cancelled | |

All statuses (other than the locked one) can be renamed, recolored, reordered, added, or removed from Settings.

---

## 6. Feature Spec

### 6.1 Month View
- Standard month grid, one cell per day.
- Each day cell shows compact job blocks: worker color strip + job number + a short status label (or status dot only, if the toggle is set to compact and space is tight). Toggle (per your earlier answer) switches every block between compact and detailed (customer name, status badge, time) — a single view-wide toggle, not per-card.
- Jobs can be dragged from one day to another directly in month view (this reschedules the day but leaves time TBD until opened).
- Clicking a day opens Week View centred on that day.

### 6.2 Week View (time-grid + worker swimlanes)

Revised after feedback that color alone doesn't make "who's working what" easy to scan. Worker identity is now conveyed primarily by **position**, with color as a secondary/reinforcing cue rather than the only signal — this also makes the board usable at a glance for anyone with colorblindness.

- 7-day columns, hour lines down the side (default range e.g. 6am–6pm, configurable) — unchanged.
- **Each day column is split into vertical lanes, one per worker.** Only workers who have at least one job that day get a lane (no empty lanes wasting width) — lanes are sized dynamically, `day width ÷ number of active workers that day`.
- Each lane has a small persistent header at the top of the day column: worker initial + color swatch, so the lane's owner is always visible even when scrolled.
- Job blocks sit inside their worker's lane and are positioned/sized vertically by actual start/end time, same as before.
- Block styling keeps three redundant cues for status/worker, never relying on color alone: **worker** = lane position (primary) + fill color (secondary); **status** = left border stripe (color) + a text label shown directly on the block whenever there's room (e.g. "Urgent," "Booked with customer"). Blocks tall enough for 2+ lines of content show the full status label under the time; very short blocks (roughly under 45px, e.g. a 30-minute job) show only the stripe + a small colored status dot, since there's no room for text — opening the job's detail modal always shows the full status regardless of block size.
- **Multiple workers on one job:** the job block is duplicated into each assigned worker's lane at the same time slot (visually linked — e.g. a thin connecting line or matching subtle outline between the linked copies), rather than living in only one lane. This means a two-person job is honestly visible in both people's day, not hidden in one person's lane with a small chip. Clicking either copy opens the same job.
- Drag a job block to a new day/time/lane to reschedule and/or reassign; dragging a block into a different worker's lane changes its assignment. Resize the block's edges to change duration.
- If a worker has enough jobs that their lane would overflow vertically past the visible hour range, the lane scrolls independently rather than compressing blocks unreadably small (relevant given your up-to-10-jobs-a-day worst case).

### 6.3 Sidebar — Unscheduled Jobs
- Left-hand panel, always visible, listing jobs pulled from watched ServiceM8 queues that haven't been dragged onto the calendar yet.
- **Queue filter**: a dropdown at the top of the sidebar, defaulting to "All queues," with an entry per watched queue (§6.6) — e.g. "Work Bay," "Quotes." Selecting one filters the list to just that queue; the count of jobs matches the filter. This is a client-side filter over already-synced jobs, not a re-fetch, so it's instant.
- Each entry: job number, customer name, description (truncated), source queue (shown as a small tag on the card regardless of filter state, so it's still clear which queue a job came from when viewing "All").
- Drag directly from here onto a day (month view) or a day+time slot (week view).

### 6.4 Job Card / Detail Modal
Mockup: `mockup_edit_job.html`.

Clicking a scheduled job opens a modal with:
- Job number, customer name, description (read-only, from ServiceM8)
- Status dropdown (editable, from the Status list)
- Assigned worker(s) — multi-select
- Day, start time, end time
- "Booked in ServiceM8" indicator + the **Book in ServiceM8** button (disabled/greyed once already booked, with a "re-sync booking" option if the time is changed after booking)
- A small breadcrumb line: who last modified the job and when (e.g. "Last edited by Sarah · 2 hours ago")

### 6.5 Worker Colors & Identity
- **Primary identity signal is lane position** (§6.2) — which worker a job belongs to is shown by which lane it sits in, and by the always-visible worker initial in that lane's header. This works regardless of color vision.
- Color remains a secondary/reinforcing cue: each worker gets a distinct color, auto-assigned from a fixed palette when created, editable in Settings, used as the block fill and in the worker legend at the top of the calendar.
- Job **status** is shown separately again (a left border stripe + small badge/icon on the block) so status and worker-identity never compete for the same color channel.
- Month view (§6.1), which doesn't have room for full lanes, keeps the worker initial as a small always-visible label on each compact block — not color alone — for the same reason.

### 6.6 Settings Page
- **ServiceM8 connection**: API key entry, test-connection button, poll interval.
- **Queues**: list of ServiceM8 queues, toggle which are "watched" (pulled into the sidebar).
- **Statuses**: add/edit/reorder/delete (except the locked "Booked with Customer").
- **Workers**: add/edit/deactivate workers and their colors.
- **Users** (admin-only): add/edit/deactivate login accounts, reset passwords, toggle the `is_admin` flag. Settings itself is only reachable by admin users.

### 6.7 Print / Export
- Print-friendly stylesheet for the Week View (removes sidebar/nav chrome, keeps the time-grid and job blocks) so a physical copy can be printed or handed to someone without app access.
- Export as PDF using the same print stylesheet (browser print-to-PDF is sufficient for v1, rather than building a separate PDF generator — **[ASSUMPTION, low-risk]**).

### 6.8 Volume / Performance
- Designed to comfortably handle up to ~10 jobs per worker per day (your stated worst case) without layout breaking — week view lanes should scroll internally on a busy day rather than compress blocks unreadably small.

---

## 7. Non-Functional Requirements
- Runs entirely on the local network — no requirement for external HTTPS access.
- Deployed directly on a Proxmox VM/LXC (no Docker) — a Python virtualenv managed by a `systemd` unit, so it behaves like any other native Linux service (starts on boot, restarts on crash, logs via `journalctl`).
- SQLite DB backed up via a simple scheduled file copy (can be handled at the Proxmox/host level, e.g. a nightly Proxmox snapshot or a cron `cp`, rather than in-app).
- Config (ServiceM8 API key, session secret) via a `.env` file read at startup, not hardcoded — kept out of version control.
- Passwords hashed at rest; session cookies marked `HttpOnly` (and `Secure` if you later put this behind HTTPS on your local network).

---

## 8. Open Items to Confirm Before/During Build

1. Should the worker list sync from ServiceM8 Staff, or stay fully local as currently specced? (§3, Staff row)
2. Should every logged-in user be able to edit any job, or only ones assigned to them? (currently assumed: anyone can edit any job, with the last-modified breadcrumb as the accountability mechanism)
3. LXC container vs full VM on Proxmox — assumed LXC for lighter weight; flag if you want a full VM instead.
4. Default week-view hour range (currently assumed 6am–6pm) — adjust to your typical work hours.
5. Multi-worker job block styling (§6.2) — the linked-lane-copy approach is confirmed based on your feedback, noting it here as settled rather than open.
6. Full audit history vs. just "last modified by" (§4) — currently specced as last-touch only; say if you want the fuller change log in v1.

---

## 9. Suggested Build Order (MVP → full)

1. Multi-user auth (login, session, `is_admin` flag) + empty month/week calendar shell + Settings page (queues/statuses/workers as static local data first, no ServiceM8 yet).
2. ServiceM8 API key connection + pull jobs from a watched queue into the sidebar (read-only).
3. Drag-and-drop: sidebar → month/week calendar, with local status + worker assignment + last-modified tracking (no ServiceM8 write-back yet).
4. Booking write-back to ServiceM8 (`JobActivity` creation + forced "Booked with Customer" status).
5. Print/export stylesheet.
6. Polish: multi-worker lane-linking styling, day-cell density handling for 10+ jobs, color customization in Settings, `systemd` service file for the Proxmox VM/LXC.
