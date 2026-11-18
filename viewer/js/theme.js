// Theme: dark stage (default) or light canvas, like Intern Break. A classic script in <head> so the right theme is set before the first paint
// (a module would run too late and flash). The choice is remembered in localStorage when it is available; the default is the dark stage.
(function () {
  var KEY = "vid3d-theme", root = document.documentElement;
  function stored() { try { var v = localStorage.getItem(KEY); return v === "light" || v === "dark" ? v : null; } catch (e) { return null; } }
  function apply(theme) {
    root.dataset.theme = theme;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "light" ? "#f4f6fa" : "#0c0e12";
    var cs = document.querySelector('meta[name="color-scheme"]');
    if (cs) cs.content = theme;
    var btn = document.getElementById("theme-btn");
    if (btn) {
      btn.setAttribute("aria-pressed", String(theme === "light"));
      btn.setAttribute("aria-label", theme === "light" ? "Light theme on. Switch to dark" : "Dark theme on. Switch to light");
    }
    document.dispatchEvent(new CustomEvent("themechange", { detail: theme }));
  }
  apply(stored() || "dark"); // dark stage by default (the point cloud reads best on it); light is an explicit, remembered choice
  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-btn");
    apply(root.dataset.theme); // the button exists now: label it
    if (btn) btn.addEventListener("click", function () {
      var next = root.dataset.theme === "light" ? "dark" : "light";
      try { localStorage.setItem(KEY, next); } catch (e) { /* storage blocked: the choice lasts until reload */ }
      apply(next);
    });
  });
})();
