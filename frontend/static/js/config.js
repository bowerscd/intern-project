// Read configuration from data attributes on the <body> element.
// This replaces the inline <script> block to allow a strict CSP.
(function () {
  var b = document.body.dataset;
  window.__API_BASE = b.apiBase || "";
  window.__USE_MOCK = b.useMock === "true";
  window.__DEV_MODE = b.devMode === "true";
})();
