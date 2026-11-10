/* Starts the site: the top bar, moving between pages, and wiring the chat, pages and demo together. */
import { $, $$, h, clear, icon } from "./dom.js";
import { t, lang, setLang, onLang } from "./i18n.js";
import * as api from "./api.js";
import { prefs, setPref, apply, isDark, toggleTheme, openSettings, onPrefs, stopSpeaking } from "./settings.js";
import { createMascot } from "./mascot.js";
import { sheet, closePopover } from "./ui.js";
import * as chat from "./chat.js";
import * as pages from "./pages.js";
import * as demo from "./hub/main.js";

const ROUTES = { "/": "ask", "/topics": "topics", "/deadlines": "deadlines", "/offices": "offices", "/saved": "saved", "/about": "about" };
const viewAsk = $("#view-ask"), viewPage = $("#view-page");
let cfg = null, brand = null;

function setTitle(name) { document.title = name === "ask" ? "Beaver Bot" : `${t("nav." + name)} · Beaver Bot`; }

function render(path, { focus = false } = {}) {
  const name = ROUTES[path] || "missing";
  closePopover();
  $$("#nav a").forEach(a => { if (a.dataset.nav === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  viewAsk.hidden = name !== "ask"; viewPage.hidden = name === "ask";
  setTitle(name === "missing" ? "about" : name);
  if (name === "ask") { if (focus && !matchMedia("(pointer: coarse)").matches) $("#q").focus({ preventScroll: true }); return; }
  stopSpeaking();
  clear(viewPage); viewPage.scrollTop = 0;
  ({ topics: pages.topicsPage, deadlines: pages.deadlinesPage, offices: pages.officesPage, saved: pages.savedPage, about: pages.aboutPage, missing: pages.notFoundPage })[name](viewPage);
  if (focus) $("#main").focus({ preventScroll: true });
}
function go(url, replace = false) {
  const target = new URL(url, location.origin);
  if (target.pathname + target.search !== location.pathname + location.search) history[replace ? "replaceState" : "pushState"](null, "", target.pathname + target.search);
  render(target.pathname, { focus: true });
}
const showAsk = () => { if (location.pathname !== "/") go("/"); };

function labelShell() {
  $$("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  const set = (id, iconName, label, text) => { const b = $(id); clear(b).append(icon(iconName)); if (text) b.append(h("span", text)); b.setAttribute("aria-label", label); b.title = label; };
  set("#themeBtn", isDark() ? "sun" : "moon", t(isDark() ? "theme.light" : "theme.dark"));
  set("#settingsBtn", "sliders", t("nav.settings"));
  set("#menuBtn", "menu", t("nav.menu"));
  set("#newChat", "plus", t("nav.new"));
  const langBtn = $("#langBtn"); langBtn.textContent = lang() === "es" ? "EN" : "ES"; langBtn.setAttribute("aria-label", t("lang.switch")); langBtn.title = t("lang.switch");
  document.querySelector('meta[name="theme-color"]');
  demo.renderBar();
}

function openMenu() {
  const s = sheet({ title: "Beaver Bot", sub: t("tagline"), size: "slim" });
  const link = (href, iconName, label) => h("a.pop-item", { href, onclick: e => { e.preventDefault(); s.close(); go(href); } }, icon(iconName), h("span", label));
  const act = (iconName, label, fn) => h("button.pop-item", { type: "button", onclick: () => { s.close(); setTimeout(fn, 190); } }, icon(iconName), h("span", label));
  s.setBody(h("nav.menu-sheet", { "aria-label": t("nav.menu") },
    link("/", "send", t("nav.ask")), link("/topics", "grid", t("nav.topics")), link("/deadlines", "calendar", t("nav.deadlines")),
    link("/offices", "pin", t("nav.offices")), link("/saved", "bookmark", t("nav.saved")), link("/about", "info", t("nav.about")),
    h("hr"),
    act(isDark() ? "sun" : "moon", t(isDark() ? "theme.light" : "theme.dark"), toggleTheme),
    act("globe", t("lang.switch"), switchLang),
    act("sliders", t("nav.settings"), openSettings)));
  s.open();
}
function switchLang() { const next = lang() === "es" ? "en" : "es"; setLang(next); setPref("lang", next); }

async function boot() {
  apply();
  if (prefs.lang) setLang(prefs.lang);
  brand = createMascot("brand");
  $("#brandLogo").append(brand.el);
  try { cfg = await api.config(); }
  catch (e) { cfg = { popular: { en: [], es: [] }, questions: { en: [], es: [] }, demo: false, offline: true, library: null }; }

  pages.initPages({ ask: q => { go("/"); chat.ask(q); }, refresh: () => render(location.pathname), settings: openSettings });
  chat.initChat(cfg, {
    showAsk, go,
    demoStudent: () => demo.student(), demoPrompts: () => demo.prompts(), demoContext: () => demo.context(),
    demoCard: meta => demo.card(meta), onFlow: flow => demo.setFlow(flow),
    offerDemo: () => demo.signIn(), onNewChat: () => { demo.setFlow(null); demo.setDraft(null); }, onAsk: () => demo.closeNudge(),
  });
  labelShell();
  render(location.pathname === "/auth/callback" ? "/" : location.pathname);
  /* After the chat exists: finish a sign-in that just came back, or pick up a session that is still alive. */
  await demo.init({ cfg, chat, go, onChange: () => { labelShell(); chat.renderWelcome(); } });

  /* links inside the app change the view without reloading the page */
  document.addEventListener("click", e => {
    const a = e.target.closest("a[data-link]");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
    e.preventDefault();
    if (a.id === "brand" && location.pathname === "/") { brand.react("boing", 580); chat.newChat(); return; }
    go(a.getAttribute("href"));
  });
  addEventListener("popstate", () => render(location.pathname));
  $("#themeBtn").addEventListener("click", toggleTheme);
  $("#settingsBtn").addEventListener("click", openSettings);
  $("#langBtn").addEventListener("click", switchLang);
  $("#menuBtn").addEventListener("click", openMenu);
  $("#newChat").addEventListener("click", () => { go("/"); chat.newChat(); });
  onPrefs(key => { if (key === "theme") labelShell(); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", labelShell);
  onLang(() => { labelShell(); chat.relabel(); render(location.pathname); });
  document.documentElement.classList.add("ready");
}
boot();
