/* The card under a chat reply about a connected site: a short version of that site's panel. SAMPLE DATA ONLY.

   The server sends the site's data with the reply (beaverbot/demo/draft.py, chat_card), read from the visitor's own
   sandbox, so the card and the full panel always show the same thing. Each site has one entry in BRIEF below; a
   test checks that every site the server can send has one, so a reply can never point at a card that isn't drawn. */
import { h, icon, money, shortDate } from "../dom.js";
import { lang } from "../i18n.js";
import { L, openPanel, review, profile } from "./core.js";
import { idCard, hangtag, tearoff } from "./objects.js";

const day = iso => shortDate(iso, lang());
const kv = (label, value, tone = "") => h("div.kv", h("span.muted", label), h("strong" + tone, value));
const note = (text, tone = "") => h("p.hub-note" + tone, icon(tone === ".warn" ? "alert" : "info"), h("span", text));
const list = items => h("ul.brief-list", items);
const line = (main, side, sub) => h("li", h("div", h("span", main), sub ? h("small.muted", sub) : null), side != null ? h("strong", side) : null);
const more = (n, shown) => (n > shown ? h("p.small.muted", L(`and ${n - shown} more in the full view`, `y ${n - shown} más en la vista completa`)) : null);
const handoff = (d, verb) => (d ? h("div.handoff", icon("external"), h("div", h("strong", `${verb} ${L("happens on", "se hace en")} ${d.name}`), h("p.small.muted", d.note))) : null);
const none = text => h("p.editor-empty", text);
const btn = (label, onclick, cls = "") => h("button.btn.small" + cls, { type: "button", onclick }, label);

export const BRIEF = {
  registration: d => [
    kv(d.term.name, d.term.open ? L("Registration is open", "Inscripción abierta") : d.term.opens_label ? L(`Opens ${d.term.opens_label}`, `Abre el ${d.term.opens_label}`) : L("Planning only", "Solo para planear")),
    kv(L("Classes in your plan", "Clases en tu plan"), `${d.items.length} · ${+d.credits.total} ${L("credits", "créditos")}`),
    d.cannot_register ? h("div.rv-reason", icon("alert"), h("div", h("p", h("strong", d.cannot_register.reason)), d.cannot_register.next ? h("p.muted", d.cannot_register.next) : null))
      : note(L("Nothing is blocking you from registering.", "Nada te impide inscribirte.")),
    d.holds.filter(x => !x.blocks && !x.cleared).map(x => note(`${x.title}: ${x.how_to_clear}`)),
  ],
  advising: d => {
    const up = d.appointments.upcoming[0];
    return [
      kv(L("Your advisor", "Tu asesor"), d.advisor), h("p.small.muted", d.office),
      up ? h("div.callout.ok", icon("check"), h("div", h("strong", L(`Booked: ${up.day_label} at ${up.time_label}`, `Reservada: ${up.day_label} a las ${up.time_label}`)), h("p.small.muted", `${up.mode} · ${up.location}`)))
        : note(L("No meeting is booked yet.", "Aún no hay reunión reservada."), d.holds.some(x => x.blocks && x.type === "advising") ? ".warn" : ""),
      h("p.hub-h", up ? L("Move it to another time", "Moverla a otro horario") : L("Open times", "Horarios libres")),
      tearoff(d.slots.slice(0, 6), s => review("advising", { type: "book", slot: s.id })),
      more(d.slots.length, 6),
    ];
  },
  billing: d => {
    const b = d.billing;
    return [
      h("div.bigfig", h("span.muted", `${b.term} ${L("balance", "saldo")}`), h("strong", money(b.balance)),
        h("span" + (b.past_due > 0 ? ".bad" : ".muted"), b.balance <= 0 ? L("Nothing is due.", "Nada pendiente.") : b.past_due > 0 ? `${money(b.past_due)} ${L("is past due", "está vencido")}` : `${L("Due", "Vence")} ${b.due_label}`)),
      d.holds.filter(x => x.blocks).map(x => note(`${x.title}: ${x.how_to_clear}`, ".warn")),
      b.plan_enrolled ? h("div.callout.ok", icon("check"), h("div", h("strong", L("You're on a payment plan this term", "Tienes un plan de pagos este trimestre")))) : null,
      h("p.hub-h", L("What the charges are", "Qué son los cargos")),
      h("ul.ledger", b.transactions.slice(0, 6).map(x => h("li", h("span.muted", day(x.date)), h("span", x.description), h("strong" + (x.amount < 0 ? ".good" : ""), money(x.amount))))),
      more(b.transactions.length, 6),
      b.balance > 0 ? handoff(d.handoff, L("Paying", "El pago")) : null,
      d.rules[0] ? h("p.small.muted", d.rules[0]) : null,
    ];
  },
  housing: d => (d.on_campus ? [
    kv(L("Your room", "Tu cuarto"), `${d.room.hall} ${d.room.room}`), kv(L("Room type", "Tipo de cuarto"), d.room.type),
    kv(L("Mailbox", "Buzón"), d.mail.box), h("p.small.muted", icon("lock"), L(" The combination stays hidden until you open Housing and approve a fresh check.", " La combinación sigue oculta hasta que abras Vivienda y apruebes una verificación.")),
    kv(L("Maintenance requests", "Solicitudes de mantenimiento"), d.requests.length ? String(d.requests.length) : L("None open", "Ninguna abierta")),
    note(d.urgent, ".warn"),
  ] : [none(L("You don't live in university housing, so there is no room or mailbox here.", "No vives en vivienda universitaria, así que aquí no hay cuarto ni buzón."))]),
  card: d => [
    idCard(d, profile()), d.note ? note(d.note) : null,
    d.accounts.filter(a => a.note).map(a => h("p.small.muted.aside", `${a.name}: ${a.note}`)),
    h("p.hub-h", L("Latest purchases", "Últimas compras")), d.transactions.length ? null : h("p.small.muted", L("No purchases.", "Sin compras.")),
    h("ul.ledger", d.transactions.slice(0, 4).map(x => h("li", h("span.muted", day(x.date)), h("span", `${x.place} · ${x.account}`), h("strong", money(x.amount))))),
    handoff(d.handoff, L("Adding money", "Agregar dinero")),
  ],
  parking: d => [
    kv(L("Permits", "Permisos"), d.permits.length ? d.permits.map(p => p.name).join(", ") : L("None", "Ninguno")),
    kv(L("Vehicles on file", "Vehículos registrados"), d.vehicles.length ? d.vehicles.map(v => v.plate || v).join(", ") : L("None", "Ninguno")),
    kv(L("Citations", "Multas"), d.tickets.length ? String(d.tickets.length) : L("None", "Ninguna"), d.tickets.length ? ".bad" : ""),
    note(d.eligibility),
    d.for_sale.length ? h("p.hub-h", L("Permits you can get", "Permisos que puedes obtener")) : null,
    h("ul.hangtags", d.for_sale.map(p => hangtag(p))),
    handoff(d.handoff, L("Buying a permit", "Comprar un permiso")),
  ],
  careers: d => [
    kv(L("Career appointment", "Cita de carrera"), d.appointment ? d.appointment.label || L("Booked", "Reservada") : L("None booked", "Ninguna reservada")),
    kv(L("Getting ready", "Preparación"), `${d.checklist.filter(c => c.done).length} ${L("of", "de")} ${d.checklist.length} ${L("done", "hechos")}`),
    h("p.hub-h", L("Openings", "Vacantes")),
    list(d.jobs.slice(0, 4).map(j => line(j.title, j.pay, `${j.employer} · ${L("apply by", "solicita antes del")} ${day(j.apply_by)}${j.saved ? " · " + L("saved", "guardada") : ""}${j.applied ? " · " + L("applied (sample)", "postulado (muestra)") : ""}`))),
    more(d.jobs.length, 4), handoff(d.handoff, L("Applying", "Solicitar")),
  ],
  library: d => [
    kv(L("Checked out", "En préstamo"), d.loans.length ? String(d.loans.length) : L("Nothing", "Nada")),
    d.loans.length ? list(d.loans.slice(0, 4).map(x => line(x.title, x.due ? `${L("due", "vence")} ${day(x.due)}` : null))) : null,
    kv(L("Fines", "Multas"), money(d.fines), d.fines > 0 ? ".bad" : ""),
    kv(L("Study rooms booked", "Salas reservadas"), d.bookings.length ? d.bookings.map(b => `${b.name || b.room} ${b.time || ""}`.trim()).join(", ") : L("None", "Ninguna")),
    h("p.small.muted", d.limit), d.note ? note(d.note) : null,
  ],
  canvas: d => [
    h("p.hub-h", L("Due next", "Lo próximo a entregar")),
    d.todo.length ? list(d.todo.slice(0, 6).map(x => line(x.title, day(x.due), x.course))) : none(L("Nothing is due.", "No hay entregas.")),
    more(d.todo.length, 6), note(d.note),
  ],
  wellness: d => [list(d.items.map(x => line(x.office, null, `${x.line} ${L("Open it on", "Ábrelo en")} ${x.portal}.`))), note(d.rule)],
  degree: (d, view) => (view === "checklist" ? [
    kv(L("Before registration", "Antes de inscribirte"), `${d.done} ${L("of", "de")} ${d.total} ${L("done", "hechos")}`),
    h("ul.checks", d.items.map(i => h("li.chk" + (i.done ? ".ok" : ".no"), icon(i.done ? "check" : "x"), h("span", h("strong", i.title), h("small.muted", " " + i.detail))))),
  ] : view === "remaining" ? [
    d.caught_up ? note(L("You're caught up on this year's requirements. These come next.", "Estás al día con los requisitos de este año. Sigue esto.")) : kv(L("Left this year", "Faltan este año"), String(d.count)),
    list(d.items.map(i => line(i.requirement, i.credits ? `${i.credits} ${L("cr", "cr")}` : null,
      !i.code ? null : i.offered && i.ready ? L(`${i.code} is offered in ${d.term}`, `${i.code} se ofrece en ${d.term}`) : i.offered ? L(`${i.code} is offered, but a prerequisite is missing`, `${i.code} se ofrece, pero falta un prerrequisito`) : L(`${i.code} isn't offered in ${d.term}`, `${i.code} no se ofrece en ${d.term}`)))),
  ] : [
    kv(L("Degree progress", "Avance del título"), `${d.percent}%`),
    kv(L("Requirements", "Requisitos"), L(`${d.counts.met} done · ${d.counts.in_progress} in progress · ${d.counts.needed + d.counts.not_met} to go`, `${d.counts.met} hechos · ${d.counts.in_progress} en curso · ${d.counts.needed + d.counts.not_met} por hacer`)),
    d.blocks.flatMap(b => b.requirements).filter(r => r.status === "not_met").map(r => note(L(`${r.label}: minimum grade not met. That usually means retaking it.`, `${r.label}: nota mínima no alcanzada. Normalmente hay que repetirla.`), ".warn")),
    h("p.hub-h", L("Still needed", "Aún falta")),
    list(d.blocks.flatMap(b => b.requirements.filter(r => r.status === "needed").map(r => line(r.label, null, b.name))).slice(0, 6)),
    more(d.counts.needed, 6),
  ]),
  whatif: d => [
    kv(d.program.name, `${d.percent}% ${L("already covered", "ya cubierto")}`),
    kv(L("Your classes that would count", "Tus clases que contarían"), `${d.counted.length} ${L("of", "de")} ${d.total}`),
    d.current && d.current.name ? kv(L(`Your major now (${d.current.name})`, `Tu carrera actual (${d.current.name})`), `${d.current.percent}%`) : null,
    h("p.hub-h", L("You'd still need", "Aún necesitarías")),
    list(d.needed.slice(0, 5).map(n => line(n.label, n.credits ? `${+n.credits} cr` : null, n.block))), more(d.needed.length, 5),
    note(L("A what-if changes nothing. Changing your major takes a form and an advisor.", "Un \"qué pasaría si\" no cambia nada. Cambiar de carrera requiere un formulario y un asesor.")),
  ],
  whatif_ask: () => [note(L("Type the name of a major or minor, or pick one of the suggestions under this card. Nothing changes: it only shows how your classes would count.",
    "Escribe una carrera o un minor, o elige una sugerencia debajo. Nada cambia: solo muestra cómo contarían tus clases."))],
  forms: d => [list(d.forms.slice(0, 5).map(f => line(f.name, null, `${f.purpose} ${L("Goes to:", "Va a:")} ${f.goes_to}.`))), more(d.forms.length, 5),
    note(L("Nothing is ever submitted from here.", "Desde aquí nunca se envía nada."))],
  resources: d => [list(d.resources.slice(0, 5).map(r => line(r.name, null, r.plain))), more(d.resources.length, 5)],
  finder_course: d => [d.suggestions.length ? h("p.hub-h", L("Classes you still need", "Clases que aún te faltan")) : null,
    list(d.suggestions.map(s => line(`${s.code} ${s.title}`))), note(L("Tell me the class you want, by code or by name.", "Dime la clase que quieres, por código o por nombre."))],
  finder_prefs: d => [kv(d.course.code, d.course.title), d.course.credits ? kv(L("Credits", "Créditos"), String(d.course.credits)) : null,
    note(L("Tell me when you'd like it: mornings, afternoons, days to avoid, on campus or online. Or say any time works.", "Dime cuándo la quieres: mañanas, tardes, días a evitar, presencial o en línea. O di que cualquier hora sirve."))],
};

const ICON = { registration: "calendar", advising: "user", billing: "wallet", housing: "home", card: "wallet", parking: "pin", careers: "bolt", library: "book", canvas: "list", wellness: "heart", degree: "cap" };
const OPEN = () => ({ schedule: L("Open my classes", "Abrir mis clases"), advising: L("Open my advisor", "Abrir mi asesor"), degree: L("Open my degree progress", "Abrir mi avance"), billing: L("Open my bill", "Abrir mi cuenta"),
  housing: L("Open housing", "Abrir vivienda"), card: L("Open my ID card", "Abrir mi tarjeta"), parking: L("Open parking", "Abrir estacionamiento"), careers: L("Open jobs and careers", "Abrir empleos"),
  library: L("Open the library", "Abrir biblioteca"), canvas: L("Open coursework", "Abrir tareas"), wellness: L("Open health and access", "Abrir salud y acceso"), finders: L("Open forms and tools", "Abrir formularios y herramientas"),
  finder: L("Open the class finder", "Abrir el buscador de clases") });

export function siteCard(card) {
  const d = card.data, draw = BRIEF[card.system];
  if (!draw) return null;
  const [panel, args] = card.panel;
  return h("section.dcard.card.brief", { "data-site": card.system },
    h("header.dcard-head", h("span.dcard-ico", icon(ICON[card.system] || "info")), h("strong", d.system), h("span.pill.sample", L("Sample data", "Datos de muestra"))),
    h("div.dcard-body", h("p.brief-from", `${L("From", "De")} ${d.source} · ${L("as of", "a las")} ${d.as_of}`), draw(d, card.view)),
    h("footer.dcard-foot", btn(OPEN()[panel] || L("Open the full view", "Abrir la vista completa"), () => openPanel(panel, args || {}), ".quiet")));
}
