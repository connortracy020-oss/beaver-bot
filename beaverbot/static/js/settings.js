/* Preferences for this device: theme, language, text size and the other accessibility settings, plus read aloud.
   They are kept in this browser only (localStorage) and are never sent to the server. */
import { h, icon } from "./dom.js";
import { t, setLang, lang } from "./i18n.js";
import { sheet } from "./ui.js";

const DEFAULTS = { theme: "system", size: 2, contrast: false, spacing: false, motion: "system", lang: null, autoRead: false, rate: 1 };
const listeners = new Set();
export const prefs = { ...DEFAULTS };
try { Object.assign(prefs, JSON.parse(localStorage.getItem("bb-prefs") || "{}")); } catch (e) { /* blocked storage: use defaults */ }

export function onPrefs(fn) { listeners.add(fn); }
export function setPref(key, value) {
  prefs[key] = value;
  try { localStorage.setItem("bb-prefs", JSON.stringify(prefs)); } catch (e) { /* fine */ }
  apply();
  listeners.forEach(fn => fn(key, value));
}

export function isDark() {
  if (prefs.theme === "dark") return true;
  if (prefs.theme === "light") return false;
  return matchMedia("(prefers-color-scheme: dark)").matches;
}

export function apply() {
  const root = document.documentElement;
  if (prefs.theme === "system") delete root.dataset.theme; else root.dataset.theme = prefs.theme;
  root.dataset.size = String(prefs.size);
  if (prefs.contrast) root.dataset.contrast = "high"; else delete root.dataset.contrast;
  if (prefs.spacing) root.dataset.spacing = "wide"; else delete root.dataset.spacing;
  if (prefs.motion === "reduce") root.dataset.motion = "reduce"; else delete root.dataset.motion;
  root.lang = lang();
}

/* The switch in the top bar flips between light and dark. "Match my device" lives in the settings sheet. */
export function toggleTheme() { setPref("theme", isDark() ? "light" : "dark"); }

function row(title, hint, control) {
  return h("div.set-row", h("div", h("div.h3", title), hint ? h("p", hint) : null), control);
}
function segmented(options, current, onPick, label) {
  const box = h("div.seg", { role: "radiogroup", "aria-label": label });
  for (const [value, text] of options) {
    box.append(h("button", { type: "button", role: "radio", "aria-checked": String(value === current), onclick: e => {
      [...box.children].forEach(b => b.setAttribute("aria-checked", "false"));
      e.currentTarget.setAttribute("aria-checked", "true"); onPick(value);
    } }, text));
  }
  return box;
}
function toggle(on, onFlip, label) {
  return h("button.switch", { type: "button", role: "switch", "aria-checked": String(!!on), "aria-label": label,
    onclick: e => { const next = e.currentTarget.getAttribute("aria-checked") !== "true"; e.currentTarget.setAttribute("aria-checked", String(next)); onFlip(next); } });
}

export function openSettings() {
  const s = sheet({ title: t("set.title"), sub: t("set.sub"), iconName: "sliders" });
  const draw = () => {
    const sizes = h("div.size-steps", { role: "group", "aria-label": t("set.size") });
    [1, 2, 3, 4].forEach(n => sizes.append(h("button", { type: "button", "aria-pressed": String(prefs.size === n), "aria-label": t("set.size.n", { n }),
      onclick: () => { setPref("size", n); [...sizes.children].forEach((b, i) => b.setAttribute("aria-pressed", String(i + 1 === n))); } }, "A")));
    const rate = h("input", { type: "range", min: "0.7", max: "1.4", step: "0.1", value: String(prefs.rate), "aria-label": t("set.rate"),
      oninput: e => setPref("rate", Number(e.target.value)) });
    s.setTitle(t("set.title"), t("set.sub"));
    s.setBody(
      row(t("set.size"), t("set.size.hint"), sizes),
      row(t("set.theme"), null, segmented([["system", t("set.theme.system")], ["light", t("set.theme.light")], ["dark", t("set.theme.dark")]], prefs.theme, v => setPref("theme", v), t("set.theme"))),
      row(t("set.lang"), t("set.lang.hint"), segmented([["en", "English"], ["es", "Español"]], lang(), v => { setLang(v); setPref("lang", v); draw(); }, t("set.lang"))),
      row(t("set.contrast"), t("set.contrast.hint"), toggle(prefs.contrast, v => setPref("contrast", v), t("set.contrast"))),
      row(t("set.spacing"), t("set.spacing.hint"), toggle(prefs.spacing, v => setPref("spacing", v), t("set.spacing"))),
      row(t("set.motion"), t("set.motion.hint"), toggle(prefs.motion === "reduce", v => setPref("motion", v ? "reduce" : "system"), t("set.motion"))),
      row(t("set.read"), speechSupported() ? t("set.read.hint") : t("set.read.none"), toggle(prefs.autoRead, v => setPref("autoRead", v), t("set.read"))),
      row(t("set.rate"), null, rate),
    );
    s.setFoot(h("button.btn.plain.grow", { type: "button", onclick: () => { Object.keys(DEFAULTS).forEach(k => { if (k !== "lang") setPref(k, DEFAULTS[k]); }); draw(); } }, icon("refresh"), t("set.reset")),
      h("button.btn", { type: "button", onclick: () => s.close() }, t("done")));
  };
  draw();
  s.open();
}

/* ---- read aloud (the browser's own speech; nothing leaves the device) ---------------------------- */
export const speechSupported = () => "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
let speaking = null;
export function stopSpeaking() {
  if (!speechSupported()) return;
  speechSynthesis.cancel();
  if (speaking) { const done = speaking; speaking = null; done(); }
}
export function speak(text, language, onEnd) {
  if (!speechSupported()) return false;
  stopSpeaking();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = language === "es" ? "es-US" : "en-US";
  u.rate = prefs.rate || 1;
  const voice = speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith(language === "es" ? "es" : "en"));
  if (voice) u.voice = voice;
  const finish = () => { if (speaking === finish) speaking = null; onEnd && onEnd(); };
  u.onend = finish; u.onerror = finish;
  speaking = finish;
  speechSynthesis.speak(u);
  return true;
}
addEventListener("pagehide", () => { if (speechSupported()) speechSynthesis.cancel(); });
