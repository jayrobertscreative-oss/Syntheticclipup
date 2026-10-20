// Synthetic Clip Up — shared page behaviour (menus, dashboard drawer, chart tooltips). No tracking, no storage.
(() => {
  // Public header menu
  const mb = document.querySelector("[data-menu]"), mn = document.getElementById("mnav");
  if (mb && mn) mb.addEventListener("click", () => {
    const open = mn.classList.toggle("open"); mb.setAttribute("aria-expanded", String(open));
  });

  // Dashboard drawer (mobile)
  const dash = document.querySelector(".dash");
  document.querySelectorAll("[data-drawer]").forEach(b => b.addEventListener("click", () => {
    const open = dash.classList.toggle("open"); b.setAttribute("aria-expanded", String(open));
  }));
  document.querySelector(".scrim")?.addEventListener("click", () => dash.classList.remove("open"));
  document.addEventListener("keydown", e => { if (e.key === "Escape") { dash?.classList.remove("open"); mn?.classList.remove("open"); } });

  // Chart tooltips: any element with data-tip inside a .chart shows a tooltip on hover/focus.
  document.querySelectorAll(".chart").forEach(chart => {
    const tip = chart.querySelector(".tip"); if (!tip) return;
    const svg = chart.querySelector("svg"), guide = chart.querySelector("[data-guide]"), dot = chart.querySelector("[data-dot]");
    const show = el => {
      const vb = svg.viewBox.baseVal, r = svg.getBoundingClientRect(), cr = chart.getBoundingClientRect();
      const x = +el.dataset.x, y = +el.dataset.y, sx = r.width / vb.width, sy = r.height / vb.height;
      tip.innerHTML = el.dataset.tip; tip.classList.add("on");
      tip.style.left = (r.left - cr.left + x * sx) + "px"; tip.style.top = (r.top - cr.top + y * sy) + "px";
      if (guide) { guide.setAttribute("x1", x); guide.setAttribute("x2", x); guide.style.opacity = 1; }
      if (dot) { dot.setAttribute("cx", x); dot.setAttribute("cy", el.dataset.dy || y); dot.style.opacity = 1; }
    };
    const hide = () => { tip.classList.remove("on"); if (guide) guide.style.opacity = 0; if (dot) dot.style.opacity = 0; };
    chart.querySelectorAll("[data-tip]").forEach(el => {
      el.addEventListener("mouseenter", () => show(el)); el.addEventListener("focus", () => show(el));
      el.addEventListener("mouseleave", hide); el.addEventListener("blur", hide);
    });
  });

  // Simple tab/segmented toggles: [data-seg] buttons set aria-pressed within their group
  document.querySelectorAll("[data-seg-group]").forEach(g => g.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    g.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    const t = g.dataset.segTarget && document.querySelector(g.dataset.segTarget);
    if (t && b.dataset.value) t.className = b.dataset.value;
  })));
})();
