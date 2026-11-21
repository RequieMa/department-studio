// Runs before the stylesheet so a saved theme never flashes the wrong surface.
(() => {
  const key = "department-studio-theme";
  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  const stored = () => {
    try {
      const value = localStorage.getItem(key);
      return value === "light" || value === "dark" ? value : null;
    } catch {
      return null;
    }
  };
  const apply = (mode) => {
    document.documentElement.dataset.theme = mode;
    document.documentElement.style.colorScheme = mode;
  };
  apply(stored() || (media?.matches ? "dark" : "light"));
  media?.addEventListener?.("change", (event) => {
    if (!stored()) apply(event.matches ? "dark" : "light");
  });
  window.studioTheme = { key, stored, apply };
})();
