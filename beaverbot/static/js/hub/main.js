/* Wires the signed-in demo into the page: the banner, the heads-up, and the cards under chat replies.
   SAMPLE DATA ONLY. */
import { $, h, clear, icon, reducedMotion } from "../dom.js";
import { t } from "../i18n.js";
import { toast } from "../ui.js";
import { createMascot } from "../mascot.js";
import * as core from "./core.js";
import { L, openPanel, review, read } from "./core.js";
import { PANEL_FOR } from "./panels.js";
import { showDraft, prefsCard, classesCard, optionsCard, watchDraft } from "./planner.js";
import { buddy } from "../buddy.js";
import { changeRows } from "./rows.js";
import { siteCard } from "./briefs.js";

let deps = {}, flow = null, nudgeEl = null, home = null, draft = null;

export const signedIn = core.signedIn;
export const student = () => core.profile();
/* The chat sends only where the class-finder conversation is. Who is asking comes from the session cookie. */
/* `draft` is the schedule being edited in the chat, if there is one, so "add them all" means the list as edited. */
export const context = () => (core.signedIn() ? { flow, draft } : null);
export const setFlow = f => { flow = f; };
export const setDraft = d => { draft = d; };
export const signIn = () => core.signIn();

export async function init(d) {
  deps = d;
  const state = await core.init({ cfg: d.cfg, mood: m => (m === "happy" ? d.chat.cheer() : d.chat.frown()), afterChange: () => { loadHome(); } });
  core.onChange(what => { if (what === "session") { flow = null; draft = null; closeNudge(); shelf(null); d.chat.newChat(); } loadHome().then(() => d.onChange()); });
  $("#signInBtn").addEventListener("click", () => core.signIn());
  watchDraft(shelf);
  if (state.signedIn) { await loadHome(); d.onChange(); core.openDesk(); if (state.fresh) { d.chat.newChat(); if (!core.onDesk()) setTimeout(nudge, reducedMotion() ? 0 : 800); } }
  else d.onChange();
}

async function loadHome() {
  if (!core.signedIn()) { home = null; return; }
  try { home = await read("home"); } catch (e) { home = null; }
}

export function prompts() {
  const list = [L("When can I register?", "¿Cuándo puedo inscribirme?"), L("What do I still need?", "¿Qué me falta?"), L("Find a class for winter", "Busca una clase para invierno"), L("Build my winter plan", "Arma mi plan de invierno")];
  if (home && home.billing && home.billing.balance > 0) list.push(L("What's my balance?", "¿Cuál es mi saldo?"));
  list.push(L("Explain my degree audit", "Explica mi auditoría de grado"));
  return list;
}

/* ---- the shelf: a tab on the question bar that says what is being worked on ------------------------------ */
let shelfEl = null;
function shelf(info) {
  if (shelfEl) { shelfEl.remove(); shelfEl = null; }
  if (!info || !core.signedIn()) return;
  const n = info.n, cr = +(+info.credits).toFixed(1);
  shelfEl = h("button.shelf", { type: "button", title: L("Go to the plan you're working on", "Ir al plan que estás armando"),
    onclick: () => { const feed = $("#feed"); feed.scrollTo({ top: feed.scrollTop + info.el.getBoundingClientRect().top - feed.getBoundingClientRect().top - 14, behavior: reducedMotion() ? "auto" : "smooth" }); const at = info.el.querySelector('[data-key="totals"]'); at && at.focus({ preventScroll: true }); } },
    h("span.shelf-dot"), h("span.shelf-label", L("Working on", "En curso")),
    h("span.shelf-text", L(`${info.term} plan · ${n} class${n === 1 ? "" : "es"} · ${cr} credits · not added yet`, `Plan de ${info.term} · ${n} clase${n === 1 ? "" : "s"} · ${cr} créditos · sin agregar`)
      + (info.clash ? L(" · time clash", " · cruce de horario") : "")), icon("chevron"));
  $("#ask").before(shelfEl);
}

/* ---- the banner that stays visible while signed in ------------------------------------------------ */
export function renderBar() {
  const bar = $("#demoBar"), btn = $("#signInBtn");
  btn.hidden = !deps.cfg || !deps.cfg.demo || core.signedIn();
  clear(btn).append(icon("user"), h("span", t("nav.signin")));
  bar.hidden = !core.signedIn();
  const p = core.profile();
  if (!core.signedIn() || !p) return;
  clear(bar).append(h("div.demo-bar-in",
    h("span.pill.sample", L("Sample data", "Datos de muestra")),
    h("span.demo-text", L("Demo: no real accounts.", "Demo: sin cuentas reales.")),
    h("span.demo-who.static", h("span.avatar-dot", p.first_name[0]), h("span.demo-name", p.name)),
    h("span.demo-gap"),
    h("button.btn.small.quiet", { type: "button", onclick: () => openPanel("home") }, icon("grid"), h("span", L("My stuff", "Mis cosas"))),
    h("button.btn.small.quiet.demo-tools", { type: "button", onclick: () => openPanel("history") }, icon("clock"), h("span", L("What I've done", "Lo que he hecho"))),
    h("button.icon-btn", { type: "button", "aria-label": L("Sign out of the demo", "Cerrar la sesión de demostración"), title: L("Sign out", "Cerrar sesión"), onclick: () => core.signOut() }, icon("door"))));
}

/* ---- the heads-up after signing in ---------------------------------------------------------------- */
export function closeNudge() { if (nudgeEl) { const el = nudgeEl; nudgeEl = null; el.classList.add("out"); setTimeout(() => el.remove(), reducedMotion() ? 0 : 220); } }
export function nudge() {
  if (!core.signedIn() || !home) return;
  closeNudge();
  const reg = home.registration, block = home.cannot_register, up = home.appointments.upcoming[0];
  let text, actions;
  if (block && block.action && block.action.booked) { text = block.reason + " " + block.next; actions = [[L("See my meeting", "Ver mi reunión"), () => openPanel("advising")], [L("See my classes", "Ver mis clases"), () => openPanel("schedule")]]; }
  else if (block && block.action && block.action.panel === "advising") { text = L(`Registration opens ${reg.opens_label}, but an advising hold is blocking you. Book your advisor?`, `La inscripción abre ${reg.opens_label}, pero una retención de asesoría te bloquea. ¿Reservar con tu asesor?`);
    actions = [[L("Book my advisor", "Reservar con mi asesor"), () => openPanel("advising")], [L("See my classes", "Ver mis clases"), () => openPanel("schedule")]]; }
  else if (block && block.action) { text = L(`Registration opens ${reg.opens_label}, but a past-due balance is blocking you. See where to pay?`, `La inscripción abre ${reg.opens_label}, pero un saldo vencido te bloquea. ¿Ver dónde pagar?`);
    actions = [[L("See my bill", "Ver mi cuenta"), () => openPanel("billing")], [L("See my classes", "Ver mis clases"), () => openPanel("schedule")]]; }
  else { text = L(`Registration opens ${reg.opens_label}. Nothing is blocking you${up ? `, and you meet your advisor ${up.day_inline}` : ""}. Want to plan your classes?`, `La inscripción abre ${reg.opens_label}. Nada te bloquea. ¿Planear tus clases?`);
    actions = [[L("Plan my classes", "Planear mis clases"), () => openPanel("schedule")], [L("What's left to take", "Lo que me falta"), () => openPanel("degree", { view: "remaining" })]]; }
  const m = createMascot("mini");
  nudgeEl = h("aside.nudge", { role: "dialog", "aria-label": L("A heads-up from Beaver Bot", "Un aviso de Beaver Bot") },
    h("button.icon-btn.nudge-x", { type: "button", "aria-label": L("Dismiss", "Cerrar"), onclick: closeNudge }, icon("x")),
    h("div.nudge-top", m.el, h("div", h("span.pill.sample", L("Sample data", "Datos de muestra")), h("p.nudge-text", text))),
    h("div.nudge-actions", actions.map(([label, fn], i) => h("button.btn.small" + (i ? ".quiet" : ""), { type: "button", onclick: () => { closeNudge(); fn(); } }, label))));
  document.body.append(nudgeEl);
  nudgeEl.addEventListener("keydown", e => { if (e.key === "Escape") closeNudge(); });
}

/* ---- under a chat reply: the proposal to review, or a way into the full panel -------------------------- */
export function card(meta) {
  const out = h("div.chat-card");
  if (meta.proposal) {
    const p = meta.proposal, blocked = p.blocks && p.blocks.length;
    const state = h("p.small.muted", blocked ? L("Blocked. Nothing changed.", "Bloqueado. Nada cambió.") : L("Waiting for you. Nothing has changed.", "Esperándote. Nada ha cambiado."));
    if (blocked) setTimeout(() => buddy.squint(), 500);
    const go = h("button.btn.small", { type: "button", onclick: () => review(p.system, null, { proposal: p, onDone: done => { go.disabled = true; if (edit) edit.remove(); state.textContent = done.summary;
      buddy.stamp(out.firstElementChild, L("Done · sample", "Hecho · muestra")); } }) },
      blocked ? L("See why", "Ver por qué") : L("Review and confirm", "Revisar y confirmar"));
    /* Classes about to be added can still be edited first: the card turns into the editable list. */
    const adds = !blocked && (p.classes || []).length && p.classes.every(c => c.action === "add") ? p.classes : null;
    const edit = adds ? h("button.btn.small.quiet", { type: "button", onclick: async () => {
      try { out.replaceChildren(showDraft(await core.post("draft", { op: "set", items: adds.map(c => ({ crn: c.crn, linked: c.linked ? c.linked.crn : null })) }))); }
      catch (e) { toast(core.explain(e)); }
    } }, icon("sliders"), h("span", L("Edit this list first", "Editar esta lista primero"))) : null;
    out.append(h("section.dcard.card.proposal" + (blocked ? ".blocked" : ""), h("header.dcard-head", h("span.dcard-ico", icon(blocked ? "alert" : "check")), h("strong", p.title), h("span.pill.sample", L("Sample data", "Datos de muestra"))),
      h("div.dcard-body", blocked ? p.blocks.map(b => h("p.small", b.reason)) : (changeRows(p) || p.effects.map(x => h("p.small", x))), state), h("footer.dcard-foot", go, edit)));
    return out;
  }
  /* A card the server wrote for this reply: the schedule to edit, the student's classes, or sections to pick from. */
  if (meta.card) {
    const c = meta.card;
    out.append(c.kind === "draft" ? showDraft(c) : c.kind === "prefs" ? prefsCard(c) : c.kind === "classes" ? classesCard(c) : c.kind === "options" ? optionsCard(c) : siteCard(c));
    /* the desk beside the conversation turns to the same site */
    if (c.kind === "site" && c.panel) core.showOnDesk(c.panel[0], c.panel[1] || {});
    else if (c.kind === "classes" || c.kind === "options") core.showOnDesk("schedule", { term: (c.term && c.term.code) || "202702" });
    return out;
  }
  const target = PANEL_FOR[meta.tool];
  if (!target) return null;
  const [name, args] = Array.isArray(target) ? target : [target, {}];
  const label = { schedule: L("my classes", "mis clases"), finder: L("the class finder", "el buscador de clases"), advising: L("my advisor", "mi asesor"), degree: L("my degree progress", "mi avance"), billing: L("my bill", "mi cuenta"), finders: L("forms and tools", "formularios y herramientas") }[name];
  out.append(h("button.btn.small.quiet", { type: "button", onclick: () => openPanel(name, args) }, icon("external"), L("Open ", "Abrir ") + label));
  return out;
}
