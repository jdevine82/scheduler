(function () {
  function formatAuDate(iso) {
    if (!iso) return "";
    const parts = iso.split("-");
    if (parts.length !== 3) return "";
    const [y, m, d] = parts;
    return `${d}/${m}/${y}`;
  }

  // Native <input type="date"> renders its closed-state text (and lets you
  // type into it) using the browser's own locale, which shows US mm/dd/yyyy
  // regardless of this being an Australian business — and there's no HTML
  // attribute that reliably overrides that across browsers. So every native
  // date input is paired with a read-only dd/mm/yyyy display sitting on top
  // of it. The native input stays underneath and fully functional — its
  // calendar picker is unambiguous either way — but typing into it directly
  // is blocked so a locale-ordered keyboard entry can never happen; picking
  // a date is always done via the picker.
  const ALLOWED_KEYS = new Set(["Tab", "Escape", "Enter"]);

  document.querySelectorAll('input[type="date"]').forEach((native) => {
    if (native.closest(".aus-date")) return;

    const wrapper = document.createElement("div");
    wrapper.className = "aus-date";
    native.parentNode.insertBefore(wrapper, native);
    wrapper.appendChild(native);

    const display = document.createElement("input");
    display.type = "text";
    display.className = `${native.className} aus-date-display`.trim();
    display.placeholder = "dd/mm/yyyy";
    display.readOnly = true;
    display.tabIndex = -1;
    display.setAttribute("aria-hidden", "true");
    display.value = formatAuDate(native.value);
    wrapper.appendChild(display);

    native.classList.add("aus-date-native");
    native.addEventListener("input", () => {
      display.value = formatAuDate(native.value);
    });
    native.addEventListener("keydown", (e) => {
      if (!ALLOWED_KEYS.has(e.key)) e.preventDefault();
    });
  });
})();
