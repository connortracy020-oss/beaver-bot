/* Runs before the page paints, so a saved theme or text size never flashes in late. Preferences live only in
   this browser (localStorage); nothing is sent anywhere. */
(function () {
  try {
    var prefs = JSON.parse(localStorage.getItem("bb-prefs") || "{}");
    var root = document.documentElement;
    if (prefs.theme === "light" || prefs.theme === "dark") root.dataset.theme = prefs.theme;
    if (prefs.size) root.dataset.size = String(prefs.size);
    if (prefs.contrast) root.dataset.contrast = "high";
    if (prefs.spacing) root.dataset.spacing = "wide";
    if (prefs.motion === "reduce") root.dataset.motion = "reduce";
    if (prefs.lang === "es") root.lang = "es";
  } catch (e) { /* storage can be blocked; the defaults are fine */ }
})();
