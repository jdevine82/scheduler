(function () {
  const PX_PER_HOUR = 56;
  const SNAP_MIN = 15;
  const DEFAULT_DURATION_MIN = 60;

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function minutesToTimeStr(totalMinutes) {
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    return `${pad(h)}:${pad(m)}`;
  }

  function parseTimeStr(value) {
    if (!value) return null;
    const [h, m] = value.split(":").map((v) => parseInt(v, 10));
    if (Number.isNaN(h) || Number.isNaN(m)) return null;
    return h * 60 + m;
  }

  function snap(minutes) {
    return Math.round(minutes / SNAP_MIN) * SNAP_MIN;
  }

  async function postSchedule(jobId, body) {
    const res = await fetch(`/api/jobs/${jobId}/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      if (data && (data.error === "worker_on_leave" || data.error === "already_scheduled")) alert(data.message);
      return null;
    }
    return data;
  }

  function openJobModal(jobId, jobDayId) {
    const url = new URL(window.location.href);
    url.searchParams.set("job", jobId);
    if (jobDayId) url.searchParams.set("day", jobDayId);
    window.location.href = url.toString();
  }

  // Print dialog — pick scope (day/week), date, and an optional worker filter,
  // then open the right print view in a new tab.
  const printDialogOpen = document.getElementById("print-dialog-open");
  const printDialogOverlay = document.getElementById("print-dialog-overlay");
  if (printDialogOpen && printDialogOverlay) {
    const printDialogClose = document.getElementById("print-dialog-close");
    const printDialogCancel = document.getElementById("print-dialog-cancel");
    const printDialogSubmit = document.getElementById("print-dialog-submit");
    const printDialogDate = document.getElementById("print-dialog-date");
    const printDialogWorker = document.getElementById("print-dialog-worker");

    const hideDialog = () => {
      printDialogOverlay.style.display = "none";
    };

    printDialogOpen.addEventListener("click", () => {
      printDialogOverlay.style.display = "flex";
    });
    printDialogClose.addEventListener("click", hideDialog);
    printDialogCancel.addEventListener("click", hideDialog);
    printDialogOverlay.addEventListener("click", (e) => {
      if (e.target === printDialogOverlay) hideDialog();
    });

    printDialogSubmit.addEventListener("click", () => {
      const scope = document.querySelector('input[name="print-scope"]:checked').value;
      const date = printDialogDate.value;
      if (!date) return;
      const worker = printDialogWorker.value;
      const path = scope === "week" ? "/print/week" : "/print/day";
      const dateParam = scope === "week" ? "start" : "date";
      let url = `${path}?${dateParam}=${date}`;
      if (worker) url += `&worker=${worker}`;
      window.open(url, "_blank");
      hideDialog();
    });
  }

  // Add-task dialog — a manual task with no ServiceM8 job behind it.
  const addTaskOpen = document.getElementById("add-task-open");
  const addTaskOverlay = document.getElementById("add-task-overlay");
  if (addTaskOpen && addTaskOverlay) {
    const addTaskClose = document.getElementById("add-task-close");
    const addTaskCancel = document.getElementById("add-task-cancel");
    const addTaskReturnTo = document.getElementById("add-task-return-to");

    const hideAddTask = () => {
      addTaskOverlay.style.display = "none";
    };

    addTaskOpen.addEventListener("click", () => {
      addTaskReturnTo.value = window.location.pathname + window.location.search;
      addTaskOverlay.style.display = "flex";
    });
    addTaskClose.addEventListener("click", hideAddTask);
    addTaskCancel.addEventListener("click", hideAddTask);
    addTaskOverlay.addEventListener("click", (e) => {
      if (e.target === addTaskOverlay) hideAddTask();
    });
  }

  function addDragHighlight(el) {
    el.addEventListener("dragenter", () => el.classList.add("drag-over"));
    el.addEventListener("dragleave", () => el.classList.remove("drag-over"));
    el.addEventListener("drop", () => el.classList.remove("drag-over"));
  }

  // Sidebar search + queue filter — both instant and client-side over the
  // already-loaded unscheduled job cards, no reload/re-fetch needed for
  // either. The queue choice is remembered across page reloads (drag-and-drop
  // reloads the page a lot) since there's no URL param driving it anymore.
  const sidebarSearch = document.getElementById("sidebar-search");
  const sidebarQueueFilter = document.getElementById("sidebar-queue-filter");
  if (sidebarSearch || sidebarQueueFilter) {
    const cards = document.querySelectorAll(".sidebar .job-card");
    const emptyState = document.getElementById("sidebar-search-empty");

    function applySidebarFilters() {
      const term = sidebarSearch ? sidebarSearch.value.trim().toLowerCase() : "";
      const queue = sidebarQueueFilter ? sidebarQueueFilter.value : "";
      let visibleCount = 0;
      cards.forEach((card) => {
        const matchesTerm = !term || card.textContent.toLowerCase().includes(term);
        const matchesQueue = !queue || card.dataset.queue === queue;
        const visible = matchesTerm && matchesQueue;
        card.style.display = visible ? "" : "none";
        if (visible) visibleCount += 1;
      });
      if (emptyState) emptyState.style.display = (term || queue) && visibleCount === 0 ? "" : "none";
    }

    if (sidebarSearch) sidebarSearch.addEventListener("input", applySidebarFilters);

    if (sidebarQueueFilter) {
      const savedQueue = localStorage.getItem("sidebarQueueFilter") || "";
      const hasOption = Array.from(sidebarQueueFilter.options).some((o) => o.value === savedQueue);
      if (hasOption) sidebarQueueFilter.value = savedQueue;

      sidebarQueueFilter.addEventListener("change", () => {
        localStorage.setItem("sidebarQueueFilter", sidebarQueueFilter.value);
        applySidebarFilters();
      });
    }

    applySidebarFilters();
  }

  // Legend: click a worker's name to show only their jobs (week: full lanes,
  // month: matching blocks). Click the active name again to go back to everyone.
  document.querySelectorAll(".legend-worker").forEach((btn) => {
    btn.addEventListener("click", () => {
      const alreadyActive = btn.classList.contains("active");
      document.querySelectorAll(".legend-worker").forEach((b) => b.classList.remove("active"));
      const selectedId = alreadyActive ? null : btn.dataset.workerId;
      if (selectedId) btn.classList.add("active");

      document.querySelectorAll(".lane[data-worker-id]").forEach((lane) => {
        lane.classList.toggle("worker-hidden", selectedId !== null && lane.dataset.workerId !== selectedId);
      });

      document.querySelectorAll(".month-block[data-worker-ids]").forEach((block) => {
        const ids = block.dataset.workerIds.split(",").filter(Boolean);
        block.classList.toggle("worker-hidden", selectedId !== null && !ids.includes(selectedId));
      });
    });
  });

  function dragPayload(el) {
    return JSON.stringify({
      jobId: el.dataset.jobId,
      jobDayId: el.dataset.jobDayId ? parseInt(el.dataset.jobDayId, 10) : null,
      durationMin: parseInt(el.dataset.durationMin || DEFAULT_DURATION_MIN, 10),
    });
  }

  // Right-click a scheduled job block to copy it, then right-click a lane
  // (or a day cell in month view) on another day to paste — adds the job to
  // that day without touching where it already is. The copied job persists
  // in localStorage (same pattern as the sidebar queue filter) so it
  // survives a page reload between copy and paste.
  const COPIED_JOB_KEY = "copiedJob";

  function getCopiedJob() {
    try {
      return JSON.parse(localStorage.getItem(COPIED_JOB_KEY) || "null");
    } catch {
      return null;
    }
  }

  function updateCopiedIndicator() {
    const el = document.getElementById("copied-job-indicator");
    if (!el) return;
    const copied = getCopiedJob();
    if (copied) {
      el.textContent = `Job #${copied.number} copied — right-click a day to paste`;
      el.style.display = "";
    } else {
      el.style.display = "none";
    }
  }

  function setCopiedJob(job) {
    localStorage.setItem(COPIED_JOB_KEY, JSON.stringify(job));
    updateCopiedIndicator();
  }

  function clearCopiedJob() {
    localStorage.removeItem(COPIED_JOB_KEY);
    updateCopiedIndicator();
  }

  const copiedJobIndicator = document.getElementById("copied-job-indicator");
  if (copiedJobIndicator) copiedJobIndicator.addEventListener("click", clearCopiedJob);
  updateCopiedIndicator();

  let contextMenuEl = null;
  function closeContextMenu() {
    if (contextMenuEl) {
      contextMenuEl.remove();
      contextMenuEl = null;
    }
  }
  document.addEventListener("click", closeContextMenu);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeContextMenu();
  });

  function showContextMenu(x, y, items) {
    closeContextMenu();
    const menu = document.createElement("div");
    menu.className = "context-menu";
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    items.forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = item.label;
      btn.disabled = !!item.disabled;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        closeContextMenu();
        item.onClick();
      });
      menu.appendChild(btn);
    });
    document.body.appendChild(menu);
    contextMenuEl = menu;
  }

  async function pasteJobOnto(day, workerId) {
    const copied = getCopiedJob();
    if (!copied) return;
    const result = await postSchedule(copied.id, {
      day,
      worker_id: workerId || undefined,
    });
    if (!result) return;
    if (result.needs_worker) {
      openJobModal(copied.id, result.job_day_id);
    } else {
      window.location.reload();
    }
  }

  document.querySelectorAll(".job-block[data-job-id][data-job-number], .month-block[data-job-id][data-job-number]").forEach((block) => {
    block.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      showContextMenu(e.pageX, e.pageY, [
        {
          label: `Copy #${block.dataset.jobNumber}`,
          onClick: () => setCopiedJob({ id: block.dataset.jobId, number: block.dataset.jobNumber }),
        },
      ]);
    });
  });

  document.querySelectorAll(".lane-body[data-worker-id], .lane-body.empty-day").forEach((laneBody) => {
    laneBody.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      const copied = getCopiedJob();
      showContextMenu(e.pageX, e.pageY, [
        {
          label: copied ? `Paste #${copied.number} here` : "Nothing copied",
          disabled: !copied,
          onClick: () => {
            if (laneBody.dataset.onLeave === "true") {
              alert("This worker is on leave that day and can't be assigned.");
              return;
            }
            pasteJobOnto(laneBody.dataset.day, laneBody.dataset.workerId ? parseInt(laneBody.dataset.workerId, 10) : null);
          },
        },
      ]);
    });
  });

  document.querySelectorAll(".month-cell[data-day]").forEach((cell) => {
    cell.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      const copied = getCopiedJob();
      showContextMenu(e.pageX, e.pageY, [
        {
          label: copied ? `Paste #${copied.number} here` : "Nothing copied",
          disabled: !copied,
          onClick: () => pasteJobOnto(cell.dataset.day, null),
        },
      ]);
    });
  });

  // Sidebar job cards
  document.querySelectorAll(".job-card[draggable]").forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", dragPayload(card));
    });
  });

  // Scheduled job blocks (week view)
  document.querySelectorAll(".job-block[draggable]").forEach((block) => {
    block.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", dragPayload(block));
    });
  });

  // Month view blocks
  document.querySelectorAll(".month-block[draggable]").forEach((block) => {
    block.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", dragPayload(block));
    });
  });

  // Week view: lane bodies with an active worker lane
  document.querySelectorAll(".lane-body[data-worker-id]").forEach((laneBody) => {
    addDragHighlight(laneBody);
    laneBody.addEventListener("dragover", (e) => e.preventDefault());
    laneBody.addEventListener("drop", async (e) => {
      e.preventDefault();
      if (laneBody.dataset.onLeave === "true") {
        alert("This worker is on leave that day and can't be assigned.");
        return;
      }
      const data = JSON.parse(e.dataTransfer.getData("text/plain"));
      const rect = laneBody.getBoundingClientRect();
      const offsetY = e.clientY - rect.top;
      const startHour = parseInt(laneBody.dataset.startHour, 10);
      const minutesFromStart = snap(Math.max(0, (offsetY / PX_PER_HOUR) * 60));
      const startTotalMin = startHour * 60 + minutesFromStart;
      const endTotalMin = startTotalMin + data.durationMin;

      const result = await postSchedule(data.jobId, {
        job_day_id: data.jobDayId || undefined,
        day: laneBody.dataset.day,
        worker_id: parseInt(laneBody.dataset.workerId, 10),
        start_time: minutesToTimeStr(startTotalMin),
        end_time: minutesToTimeStr(endTotalMin),
      });
      if (result) window.location.reload();
    });
  });

  // Week view: empty days (no lanes yet) — set day only (server defaults the
  // time to 8am-9am if the job never had one). If the job still has nobody
  // assigned afterward (a brand-new job with no lane to infer a worker from),
  // open the edit modal so a worker can be picked — otherwise it'd vanish
  // with no lane to show it in. A job already assigned before the drag keeps
  // its worker and just moves silently.
  document.querySelectorAll(".lane-body.empty-day").forEach((laneBody) => {
    addDragHighlight(laneBody);
    laneBody.addEventListener("dragover", (e) => e.preventDefault());
    laneBody.addEventListener("drop", async (e) => {
      e.preventDefault();
      const data = JSON.parse(e.dataTransfer.getData("text/plain"));
      const result = await postSchedule(data.jobId, {
        job_day_id: data.jobDayId || undefined,
        day: laneBody.dataset.day,
      });
      if (!result) return;
      if (result.needs_worker) {
        openJobModal(data.jobId, result.job_day_id);
      } else {
        window.location.reload();
      }
    });
  });

  // Month view: day cells — day only, time/worker stay TBD (or unchanged if already set)
  document.querySelectorAll(".month-cell[data-day]").forEach((cell) => {
    addDragHighlight(cell);
    cell.addEventListener("dragover", (e) => e.preventDefault());
    cell.addEventListener("drop", async (e) => {
      e.preventDefault();
      const data = JSON.parse(e.dataTransfer.getData("text/plain"));
      const result = await postSchedule(data.jobId, {
        job_day_id: data.jobDayId || undefined,
        day: cell.dataset.day,
      });
      if (!result) return;
      if (result.needs_worker) {
        openJobModal(data.jobId, result.job_day_id);
      } else {
        window.location.reload();
      }
    });
  });

  // Double-click a job block (week or month view) to open its edit dialog.
  // Single click/drag is reserved for moving it — no dialog interruption.
  document.querySelectorAll(".job-block[data-open-url], .month-block[data-open-url]").forEach((block) => {
    block.addEventListener("dblclick", () => {
      window.location.href = block.dataset.openUrl;
    });
  });

  // Duration stepper arrows — nudge a job's finish time by 15 min without opening the dialog.
  document.querySelectorAll(".dur-btn").forEach((btn) => {
    btn.addEventListener("dblclick", (e) => e.stopPropagation());
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const block = btn.closest(".job-block");
      const startMin = parseTimeStr(block.dataset.startTime);
      const endMin = parseTimeStr(block.dataset.endTime);
      if (startMin === null || endMin === null) return;
      const delta = btn.classList.contains("dur-up") ? SNAP_MIN : -SNAP_MIN;
      const newDuration = Math.max(SNAP_MIN, endMin - startMin + delta);
      const ok = await postSchedule(btn.dataset.jobId, {
        job_day_id: block.dataset.jobDayId ? parseInt(block.dataset.jobDayId, 10) : undefined,
        end_time: minutesToTimeStr((startMin + newDuration) % 1440),
      });
      if (ok) window.location.reload();
    });
  });

  // Resize handles on scheduled job blocks (week view) — drag bottom edge to change duration
  document.querySelectorAll(".job-block .resize-handle").forEach((handle) => {
    handle.addEventListener("dblclick", (e) => e.stopPropagation());

    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const block = handle.closest(".job-block");
      const laneBody = block.closest(".lane-body");
      const startHour = parseInt(laneBody.dataset.startHour, 10);
      const jobId = block.dataset.jobId;
      const jobDayId = block.dataset.jobDayId ? parseInt(block.dataset.jobDayId, 10) : undefined;
      const initialTop = parseInt(block.style.top, 10);
      const initialHeight = parseInt(block.style.height, 10);
      const startY = e.clientY;

      function onMouseMove(moveEvent) {
        const delta = moveEvent.clientY - startY;
        const newHeight = Math.max(18, initialHeight + delta);
        block.style.height = `${newHeight}px`;
      }

      async function onMouseUp() {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        const finalHeight = parseInt(block.style.height, 10);
        const startMinutesFromRangeStart = (initialTop / PX_PER_HOUR) * 60;
        const durationMin = Math.max(SNAP_MIN, snap((finalHeight / PX_PER_HOUR) * 60));
        const startTotalMin = startHour * 60 + snap(startMinutesFromRangeStart);
        const endTotalMin = startTotalMin + durationMin;
        const ok = await postSchedule(jobId, { job_day_id: jobDayId, end_time: minutesToTimeStr(endTotalMin) });
        if (ok) window.location.reload();
      }

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });
  });

  const DURATION_PRESETS = [15, 30, 45, 60, 90, 120, 180, 240, 360, 480];

  // Job edit modal: Start time + Duration drive Finish time automatically.
  // Exposed on window since the modal's inline <script> (server-rendered,
  // outside this file's scope) calls it after DOMContentLoaded.
  window.initJobDurationField = function (initialDurationMin) {
    const durationSelect = document.getElementById("job-duration");
    const startInput = document.getElementById("job-start-time");
    const endInput = document.getElementById("job-end-time");
    if (!durationSelect || !startInput || !endInput) return;

    function setCustomMode(isCustom) {
      if (isCustom) {
        endInput.removeAttribute("readonly");
      } else {
        endInput.setAttribute("readonly", "readonly");
      }
    }

    function recomputeEnd() {
      const duration = parseInt(durationSelect.value, 10);
      const startMin = parseTimeStr(startInput.value);
      if (!Number.isNaN(duration) && startMin !== null) {
        endInput.value = minutesToTimeStr((startMin + duration) % 1440);
      }
    }

    if (initialDurationMin !== null && DURATION_PRESETS.includes(initialDurationMin)) {
      durationSelect.value = String(initialDurationMin);
      setCustomMode(false);
    } else if (initialDurationMin === null) {
      durationSelect.value = "60";
      setCustomMode(false);
    } else {
      durationSelect.value = "custom";
      setCustomMode(true);
    }

    durationSelect.addEventListener("change", () => {
      if (durationSelect.value === "custom") {
        setCustomMode(true);
        endInput.focus();
      } else {
        setCustomMode(false);
        recomputeEnd();
      }
    });

    startInput.addEventListener("input", () => {
      if (durationSelect.value !== "custom") recomputeEnd();
    });
  };
})();
