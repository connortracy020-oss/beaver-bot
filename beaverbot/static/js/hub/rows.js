/* One class to a row: the code and name, a line for each meeting, and the credits. Used wherever the demo lists
   classes (a review, a chat card, the schedule being edited), so they always read the same way. SAMPLE DATA ONLY.
   Every string in a row comes from the server; this only lays it out. */
import { h, icon } from "../dom.js";
import { lang } from "../i18n.js";
import { weekGrid } from "../demo/parts.js";

const L = (en, es) => (lang() === "es" ? es : en);
export const num = n => String(+(+n).toFixed(1));
export const credits = n => L(`${num(n)} credit${+n === 1 ? "" : "s"}`, `${num(n)} crédito${+n === 1 ? "" : "s"}`);
export const classes = n => L(`${n} class${n === 1 ? "" : "es"}`, `${n} clase${n === 1 ? "" : "s"}`);
export const seatsText = r => (r.seats_open <= 0 ? L("Full", "Llena") : L(`${r.seats_open} of ${r.seats_total} seats open`, `${r.seats_open} de ${r.seats_total} lugares libres`));

/* What is happening to a class in a review, or where it stands in a list of the student's classes. */
const TAGS = () => ({
  remove: [L("Remove", "Quitar"), "out"], drop: [L("Drop", "Dar de baja"), "out"], withdraw: [L("Withdraw", "Retirar"), "out"],
  from: [L("From", "De"), "out"], to: [L("To", "A"), "in"], registered: [L("Register", "Inscribir"), "in"],
  waitlisted: [L("Waitlist", "Lista de espera"), "wait"], failed: [L("Won't go through", "No pasará"), "out"],
});
const STATUS = () => ({ planned: L("Planned", "Planeada"), cart: L("In cart", "En el carrito"), registered: L("Registered", "Inscrita"), waitlisted: L("Waitlisted", "En lista de espera") });

export function classRow(row, { tag = null, tone = "", actions = null, below = null } = {}) {
  const notes = [...(row.notes || []), ...(row.misses || []), ...(row.note ? [row.note] : [])];
  return h("li.crow" + (row.blocked || row.action === "failed" ? ".off" : "") + (row.clash && row.clash.length ? ".clash" : ""), { "data-crn": row.crn },
    h("div.crow-top",
      h("div.crow-name", tag ? h("span.badge." + (tone || "planned"), tag) : null, h("strong", row.code), h("span", row.name)),
      h("span.crow-cr", credits(row.credits))),
    h("ul.crow-times", (row.times || []).map(t => h("li", icon("clock"), h("span", t)))),
    row.requirement && row.requirement !== `${row.code} ${row.name}` ? h("p.crow-for", L("Counts for: ", "Cuenta para: "), row.requirement) : null,
    notes.map(n => h("p.crow-note", icon("alert"), h("span", n))),
    actions && actions.length ? h("div.crow-actions", actions) : null, below);
}

export const week = rows => weekGrid(rows.filter(r => r.lecture).map(r => ({ lecture: r.lecture, linked: r.linked })), { es: lang() === "es" });

/* The classes a change touches, for the review and for the card in the chat. */
export function changeRows(plan, { grid = true } = {}) {
  const rows = plan.classes || [];
  if (!rows.length) return null;
  const tags = TAGS();
  const adds = rows.filter(r => r.action === "add" || r.action === "to" || r.action === "registered" || r.action === "waitlisted");
  const total = adds.reduce((n, r) => n + (+r.credits || 0), 0);
  return h("div.crows-wrap",
    h("ul.crows", rows.map(r => classRow(r, tags[r.action] ? { tag: tags[r.action][0], tone: tags[r.action][1] } : {}))),
    rows.length > 1 && adds.length === rows.length ? h("p.crows-total", h("strong", `${classes(adds.length)} · ${credits(total)}`)) : null,
    grid && adds.length > 1 ? h("details.planner-week", h("summary", L("Week view", "Vista de la semana")), week(adds)) : null);
}

/* The student's classes in one term, each with where it stands. */
export function statusRows(rows) {
  const status = STATUS();
  return h("ul.crows", rows.map(r => classRow(r, { tag: status[r.action] || null, tone: r.action })));
}
