(function () {
  // Calendar views reload themselves every 15 minutes so a wall display
  // (usually not logged in) picks up new bookings and rolls over to the
  // next day without anyone hitting refresh. Any click or keypress restarts
  // the countdown, and a reload is postponed while a modal or dialog is
  // open or a field has focus, so it never yanks the page out from under
  // someone who's actually using it.
  const REFRESH_MS = 15 * 60 * 1000;
  const RETRY_MS = 60 * 1000;
  let timer = null;

  function busy() {
    if (new URLSearchParams(window.location.search).has("job")) return true;
    const overlayOpen = Array.from(document.querySelectorAll(".overlay")).some(
      (o) => getComputedStyle(o).display !== "none"
    );
    if (overlayOpen) return true;
    const active = document.activeElement;
    return Boolean(active && active.matches("input, textarea, select"));
  }

  function tick() {
    if (busy()) {
      timer = setTimeout(tick, RETRY_MS);
    } else {
      window.location.reload();
    }
  }

  function restart() {
    clearTimeout(timer);
    timer = setTimeout(tick, REFRESH_MS);
  }

  ["pointerdown", "keydown", "wheel"].forEach((evt) =>
    document.addEventListener(evt, restart, { passive: true })
  );
  restart();
})();
