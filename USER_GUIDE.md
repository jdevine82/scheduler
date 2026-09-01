# Job Scheduler — Features & How-To Guide

A visual scheduling board for pulling unscheduled jobs out of ServiceM8, dragging them onto a calendar, assigning workers, and booking confirmed dates back into ServiceM8.

## Logging in

Go to the app's URL and log in with the username/password an admin created for you (Settings → Users, or via `python -m app.seed` for the very first account). There's no self-signup — accounts are created by an admin.

## The calendar

### Week view

The default view. Each day column splits into a lane per worker who has a job that day — lanes only appear for workers who are actually booked in on that day, so the board doesn't waste space on empty lanes.

- **Worker identity** = which lane a job sits in, plus the fill colour (shown at the top of each lane as an initial + colour dot, and in the legend along the bottom).
- **Status** = the coloured stripe down the left edge of each block, plus a text label if the block is tall enough.
- **Multi-worker jobs** appear once per assigned worker's lane (linked with a dashed outline), so a two-person job is visible in both people's day rather than hidden under one name.
- Click a worker's name in the bottom legend to show only their lanes for the week — click it again to go back to everyone.
- Use the ← → arrows next to the date range to move between weeks.

### Month view

A compact overview — useful for seeing the shape of the month or jumping to a specific day (click the date number to open that day in Week view). Each job shows as a small coloured strip with the worker's initial and job number.

## Scheduling jobs

### Drag-and-drop

- **From the sidebar onto the calendar**: drag an unscheduled job card onto a worker's lane (week view) at the time you want — it's scheduled immediately, snapped to 15-minute increments. Drop it on a day with no existing lanes yet, or onto a month view day cell, and it'll open the edit dialog so you can pick a worker (there's no lane to infer one from yet).
- **Moving an already-scheduled job**: drag its block to a new day, time, or lane — it updates instantly, no dialog interruption. Dragging in month view moves the day only; if the job already has a time, that's kept as-is.
- Jobs with no time ever recorded (which is normal — ServiceM8 doesn't carry scheduling info) default to **8:00–9:00 AM** when first dropped, adjustable afterwards.

### Adjusting duration without opening anything

Each scheduled block (tall enough to show its status label) has small **▲ / ▼** arrows in the top-right corner — click to nudge the finish time by 15 minutes at a time. You can also drag the bottom edge of a block up or down to resize it freehand.

### Opening a job's details

**Double-click** a job block (week or month view) to open the edit modal. A single click/drag does nothing by itself — it's reserved for moving the block.

In the modal you can change:
- **Status** — from the list configured in Settings.
- **Assigned workers** — tick any number of workers.
- **Day**, **Start time**, and **Duration** (pick from common lengths, or "Custom…" to type a finish time directly — it auto-calculates from start + duration otherwise).
- **ServiceM8 booking** — see below.

A breadcrumb at the bottom shows who last edited the job and when.

## Booking into ServiceM8

Once a job has a day, start time, and finish time, the modal's **"Book in ServiceM8"** button becomes active. Clicking it:

1. Creates (or updates) a scheduled activity in ServiceM8 for that job, with the exact date/time shown on the calendar.
2. Forces the job's status to **Booked with Customer** — this always happens on booking, no exceptions, since that status means "the customer has this date locked in."
3. **Locks the job on the calendar**: it can no longer be dragged around (shown with a 🔒 next to its job number). Double-click still opens the modal to make a deliberate change — that's the only way to move a booked job.

### Re-syncing a booking

If you've changed a booked job's time in the modal and saved, or you just want to double-check ServiceM8 still has it, click **"Re-sync booking."** This checks ServiceM8's actual current state and reconciles automatically:

- **Booking still there, but a different time** → the calendar updates to match ServiceM8, and stays locked.
- **Booking no longer exists in ServiceM8** (someone removed or changed it there) → the job is unlocked and its status is set to **Cancelled**.
- **Matches already** → nothing changes except the "last synced" timestamp.

The top-bar **"Sync now"** button (see below) runs this same check across *every* currently-booked job in one go, not just one at a time.

## The sidebar

Lists every job pulled from your watched ServiceM8 queues that hasn't been scheduled yet.

- **Queue dropdown** — filter to a single queue, or "All queues." Instant, no reload.
- **Search box** — filters by job number, customer name, or description as you type. Instant, no reload.
- A ⚠ next to a job number means it's no longer sitting in a watched ServiceM8 queue (someone may have moved or closed it there) — it's flagged, not deleted, so you can investigate.

## Top bar actions

- **Sync now** — pulls the latest jobs from your watched ServiceM8 queues right away (instead of waiting for the background poll), and re-checks every booked job's ServiceM8 state at the same time.
- **Clear past weeks** — deletes local scheduling for anything before the current week. Anything still sitting in a watched ServiceM8 queue comes back as unscheduled on the next sync. Available to any logged-in user, with a confirmation prompt first.
- **Print** — opens a dialog to print or export a schedule (see below).
- **⚙ Settings** — admin only.

## Printing and exporting

Click **Print** in the top bar and choose:

- **Scope**: a single day, or a whole week.
- **Date**: defaults to whatever you're currently viewing.
- **Worker**: all workers, or just one person's jobs.

This opens a clean, chrome-free printable sheet in a new tab — use the **"Print / Save as PDF"** button there (or your browser's own print function) to get a physical copy or PDF.

## Settings (admin only)

| Tab | What it's for |
|---|---|
| **ServiceM8 connection** | API key, poll interval, and a "Test connection" check. |
| **Queues** | Which ServiceM8 queues get pulled into the sidebar. "Refresh queue list" fetches the current names from ServiceM8; toggle **Watch** per queue. |
| **Statuses** | Add, rename, recolour, or delete statuses. "Booked with Customer" is locked — it can't be renamed or deleted, since the booking write-back depends on it existing. |
| **Workers** | Add/rename/recolour/deactivate/delete your team. Optionally link each one to their matching ServiceM8 staff member — only needed for "Book in ServiceM8" to work, the worker list itself always stays local to this app. |
| **Users** | Create logins for your team, reset passwords, toggle admin access, deactivate accounts. |
| **Backup** | Download a full copy of the database any time. Restoring from a backup file replaces *everything* currently in the app — a safety copy of what it replaces is taken automatically first. |

Everyone else (non-admin users) can use the board — view, schedule, edit, and sync jobs — but can't reach Settings.
