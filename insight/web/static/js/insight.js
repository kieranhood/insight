// Insight client helpers: live refresh (Server-Sent Events, falling back to polling)
// and small charts. Everything is served by Insight itself; nothing is fetched elsewhere.
(function () {
  "use strict";

  var POLL_MS = 30000;
  var pollTimer = null;

  function refresh() {
    document.body.dispatchEvent(new CustomEvent("insight:refresh", { bubbles: true }));
  }

  function startPolling() {
    if (pollTimer === null) {
      pollTimer = window.setInterval(refresh, POLL_MS);
    }
  }

  function startLive() {
    if (!document.body.hasAttribute("data-live")) return;
    if (!("EventSource" in window)) { startPolling(); return; }
    var source = new EventSource("/events/stream");
    source.addEventListener("refresh", refresh);
    source.onerror = function () {
      // Keep the page fresh even if the stream drops (slow or interrupted links).
      startPolling();
    };
    source.onopen = function () {
      if (pollTimer !== null) { window.clearInterval(pollTimer); pollTimer = null; }
    };
  }

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function drawCharts(root) {
    if (!window.uPlot) return;
    (root || document).querySelectorAll("[data-chart]").forEach(function (el) {
      if (el.dataset.drawn) return;
      el.dataset.drawn = "1";
      fetch(el.dataset.chart, { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data.x || !data.x.length) { el.textContent = "No readings in this period."; return; }
          var opts = {
            width: Math.max(260, el.clientWidth),
            height: 180,
            series: [{}, { label: data.label || "", stroke: css("--accent"), width: 2, spanGaps: false }],
            axes: [
              { stroke: css("--muted"), grid: { stroke: css("--border") } },
              { stroke: css("--muted"), grid: { stroke: css("--border") }, label: data.unit || "" },
            ],
            legend: { show: false },
          };
          new window.uPlot(opts, [data.x, data.y], el);
        })
        .catch(function () { el.textContent = "Readings unavailable."; });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    startLive();
    drawCharts(document);
  });
  document.addEventListener("htmx:afterSwap", function (e) { drawCharts(e.target); });
})();
