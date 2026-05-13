/*
 * claude-backlog web UI — Phase 5.1 client (task-442)
 *
 * Vanilla Alpine.js. No build step. Loaded via <script defer> after the CDN
 * Alpine bundle so `Alpine.data()` is registered before x-data evaluates.
 *
 * This file intentionally stays small in 5.1 — it sets up the tab nav, route
 * state, and theme toggle. Phase 5.2+ extends `backlogApp()` with view-
 * specific state (tasks, filters, sidecart) and `init()` becomes the place
 * where /api/* fetches kick off.
 */

document.addEventListener("alpine:init", () => {
  Alpine.data("backlogApp", () => ({
    // --- nav contract --------------------------------------------------
    // Order matches the canonical 10-view set documented in task-442.
    // Glyphs intentionally use unicode block / geometric symbols so the
    // UI works with zero icon-font dependencies.
    tabs: [
      { path: "/",        label: "Kanban",   glyph: "▦" },
      { path: "/list",    label: "List",     glyph: "≡" },
      { path: "/stats",   label: "Stats",    glyph: "▤" },
      { path: "/graph",   label: "Network",  glyph: "◇" },
      { path: "/embed",   label: "Embed 2D", glyph: "✦" },
      { path: "/heatmap", label: "Heatmap",  glyph: "▩" },
      { path: "/fdg",     label: "FDG 2D",   glyph: "✧" },
      { path: "/fdg-hm",  label: "FDG HM",   glyph: "▦" },
      { path: "/compass", label: "Compass",  glyph: "◉" },
    ],

    // --- runtime state -------------------------------------------------
    route: window.location.pathname || "/",
    theme: localStorage.getItem("backlog.theme") || "dark",
    version: { name: "claude-backlog", version: "?", phase: "?" },

    // --- lifecycle -----------------------------------------------------
    async init() {
      window.addEventListener("popstate", () => {
        this.route = window.location.pathname || "/";
      });
      try {
        const resp = await fetch("/api/version");
        if (resp.ok) {
          this.version = await resp.json();
        }
      } catch (err) {
        console.warn("[backlog] /api/version probe failed", err);
      }
    },

    // --- navigation ----------------------------------------------------
    navigate(path) {
      if (path === this.route) return;
      window.history.pushState({}, "", path);
      this.route = path;
    },

    // --- theme ---------------------------------------------------------
    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark";
      localStorage.setItem("backlog.theme", this.theme);
    },
  }));
});
