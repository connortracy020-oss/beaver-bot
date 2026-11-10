/* The panels of the signed-in demo, one per connected system. SAMPLE DATA ONLY.

   A panel never keeps data of its own. It asks the server what to show (core.read), draws it, and sends every
   change through core.review, which shows the server's own summary and waits for the student's confirmation. */
import { h, icon, money, plural, shortDate } from "../dom.js";
import { lang } from "../i18n.js";
import { toast } from "../ui.js";
import * as api from "../api.js";
import { weekGrid, weekStrip, whenWhere, seats, check, bar, progressRing } from "../demo/parts.js";
import { idCard } from "./objects.js";
import { L, register, read, post, review, undo, reset, setClock, session, profile, signOut, explain, verify } from "./core.js";

const day = iso => shortDate(iso, lang());
const sect = (title, ...kids) => h("section.hub-sec", title ? h("h3.hub-h", title) : null, kids);
const kv = (label, value) => h("div.kv", h("span.muted", label), h("strong", value));
const empty = (iconName, text, action) => h("div.hub-empty", icon(iconName), h("p", text), action || null);
const btn = (label, onclick, cls = "") => h("button.btn.small" + cls, { type: "button", onclick }, label);
const link = (label, onclick) => h("button.linkish", { type: "button", onclick }, label);
const note = (text, tone = "") => h("p.hub-note" + tone, icon(tone === ".warn" ? "alert" : "info"), h("span", text));
const badge = status => h("span.badge." + status, { planned: L("Planned", "Planeada"), cart: L("In cart", "En el carrito"), registered: L("Registered", "Inscrita"),
  waitlisted: L("Waitlisted", "En lista de espera"), withdrawn: L("Withdrawn", "Retirada") }[status]);
/* Where a real version would hand off to another site's own page (payments, applications). Never a form here. */
/* The same three steps everywhere: review what would happen, a line saying the real version opens the other site with it
   filled in, then a pretend step (marked Sample data) that updates the sample data and can be undone. */
const handoff = (data, verb, ...actions) => h("div.handoff", icon("external"), h("div", h("strong", `${verb} ${L("happens on", "se hace en")} ${data.name}`), h("p.small.muted", data.note),
  h("p.small.muted", L(`In the real version this opens ${data.name} with it filled in. Here you can review it and pretend it went through.`, `En la versión real esto abre ${data.name} con los datos listos. Aquí puedes revisarlo y fingir que se completó.`)),
  actions.some(Boolean) ? h("div.row-actions", h("span.pill.sample", L("Sample data", "Datos de muestra")), actions) : null));
const blockBox = (b, ctx) => h("div.rv-reason.inline", icon("alert"), h("div", h("p", h("strong", b.reason)), b.next ? h("p.muted", b.next) : null,
  b.action && b.action.panel ? btn(b.action.panel === "advising" ? (b.action.booked ? L("See my meeting", "Ver mi reunión") : L("Book my advisor", "Reservar con mi asesor")) : b.action.panel === "billing" ? L("See where to pay", "Ver dónde pagar") : L("Find a class", "Buscar una clase"),
    () => ctx.open(b.action.panel)) : null));

/* ---- home: one line per system ------------------------------------------------------------------- */
register("home", { title: () => L("Everything in one place", "Todo en un solo lugar"), async render(ctx) {
  const d = await read("home"); ctx.stamp(d);
  const up = d.appointments.upcoming[0], b = d.billing, blocking = d.holds.filter(x => x.blocks);
  const tile = (iconName, title, line, panel, tone = "") => h("button.tile" + tone, { type: "button", onclick: () => ctx.open(panel) }, h("span.tile-ico", icon(iconName)),
    h("span.tile-text", h("strong", title), h("small", line)), icon("chevron"));
  return h("div",
    d.cannot_register ? blockBox(d.cannot_register, ctx) : note(d.registration.note),
    h("div.tiles",
      tile("calendar", L("Classes and registration", "Clases e inscripción"), `${d.this_term.length} ${L("classes this term", "clases este trimestre")} · ${d.credits.total} ${L("credits planned for", "créditos planeados para")} ${d.registration.name}`, "schedule"),
      tile("user", L("Advisor", "Asesor"), up ? `${L("Meeting", "Cita")} ${up.day_inline} ${L("at", "a las")} ${up.time_label}` : L("No meeting booked", "Sin cita reservada"), "advising", blocking.some(x => x.type === "advising") ? ".warn" : ""),
      tile("cap", L("Degree progress", "Avance del título"), L("What's done, what's left, what-if", "Lo hecho, lo que falta y qué pasaría si"), "degree"),
      tile("wallet", L("Bill", "Cuenta"), b.balance > 0 ? `${money(b.balance)} ${b.past_due > 0 ? L("past due", "vencido") : L("due", "vence") + " " + b.due_label}` : L("Nothing due", "Nada pendiente"), "billing", b.past_due > 0 ? ".warn" : ""),
      tile("book", L("Coursework", "Tareas"), L("What's due in your classes", "Lo que vence en tus clases"), "canvas"),
      tile("home", L("Housing", "Vivienda"), L("Room, mail, maintenance", "Cuarto, correo, mantenimiento"), "housing"),
      tile("heart", L("ID card and dining money", "Credencial y dinero de comida"), `Dining Dollars ${money(b.meal_plan || 0)} · Orange Cash ${money(b.orange_cash || 0)}`, "card"),
      tile("pin", L("Parking", "Estacionamiento"), L("Permits, vehicles, waitlists", "Permisos, vehículos, listas de espera"), "parking"),
      tile("search", L("Jobs and career help", "Empleos y orientación"), L("Saved jobs, career advising", "Empleos guardados, asesoría"), "careers"),
      tile("list", L("Library", "Biblioteca"), L("Loans and study rooms", "Préstamos y salas de estudio"), "library"),
      tile("access", L("Health and access", "Salud y accesibilidad"), L("Shows that an appointment or letter exists, not what it's for", "Muestra que existe una cita o carta, no para qué es"), "wellness"),
      tile("form", L("Forms and BeaverHub tools", "Formularios y herramientas"), L("Find the right one in plain words", "Encuentra el correcto en palabras simples"), "finders")),
    sect(L("This session", "Esta sesión"), h("div.row-actions", btn(L("What I've done", "Lo que he hecho"), () => ctx.open("history"), ".quiet"), btn(L("Demo controls", "Controles de la demo"), () => ctx.open("controls"), ".quiet"))));
} });

/* ---- the schedule: every term, every class editable ------------------------------------------------ */
register("schedule", { title: () => L("Classes and registration", "Clases e inscripción"), async render(ctx) {
  const term = ctx.args.term || ctx.draft.term || "202702";
  ctx.draft.term = term;
  const d = await read("registration", { term }); ctx.stamp(d);
  const t = d.term, live = d.items.filter(i => i.status !== "withdrawn");
  const tabs = h("div.seg.terms", { role: "tablist", "aria-label": L("Term", "Trimestre") }, d.terms.map(x =>
    h("button", { type: "button", role: "tab", "aria-selected": String(x.code === term), onclick: () => { ctx.draft.term = x.code; ctx.args.term = x.code; ctx.reload(); } }, x.name, x.count ? h("span.count", String(x.count)) : null)));
  const c = d.credits, over = c.total > c.max;
  const meter = h("div.credits" + (over ? ".over" : ""), { role: "img", "aria-label": `${c.total} credits; full-time is ${c.min}, the limit is ${c.max}` },
    h("div.credits-bar", (() => { const f = h("i"); f.style.width = Math.min(100, c.total / c.max * 100) + "%"; return f; })(), (() => { const m = h("b"); m.style.left = c.min / c.max * 100 + "%"; return m; })()),
    h("div.credits-text", h("strong", `${c.total} ${L("credits", "créditos")}`), h("span.muted", t.mode === "current" ? ` · ${c.registered} ${L("registered", "inscritos")}` : ""),
      h("span.muted", ` · ${L("full-time", "tiempo completo")} ${c.min} · ${L("limit", "límite")} ${c.max}`)));
  const conflicts = d.conflicts.map(x => note(`${x.a} ${L("and", "y")} ${x.b} ${L("meet at the same time. Swap one of them to another section.", "se cruzan. Cambia una a otra sección.")}`, ".warn"));
  const rows = d.items.length ? h("ul.classlist", d.items.map(i => h("li.classrow." + i.status,
    h("button.classrow-main", { type: "button", onclick: () => ctx.open("class", { term, crn: i.crn }) },
      h("span.classrow-top", h("strong", i.lecture.course), h("span", i.lecture.title), badge(i.status)),
      h("span.classrow-when", weekStrip(i.lecture.meetings), h("span", whenWhere(i.lecture)), i.linked ? h("span.muted", ` + ${i.linked.type.toLowerCase()} ${whenWhere(i.linked)}`) : null),
      h("span.small.muted", `${i.credits} ${L("credits", "créditos")} · ${i.grade_mode} · CRN ${i.crn}`)),
    h("span.classrow-edit", icon("chevron")))))
    : empty("calendar", t.mode === "current" ? L("No classes this term.", "Sin clases este trimestre.") : L(`Nothing planned for ${t.name} yet.`, `Aún no hay nada planeado para ${t.name}.`),
      t.mode !== "current" ? btn(L("Find a class", "Buscar una clase"), () => ctx.open("finder", { term })) : null);
  const inCart = d.items.filter(i => i.status === "cart").length, planned = d.items.filter(i => i.status === "planned").length;
  if (t.mode !== "current") ctx.foot(
    btn(L("Find a class", "Buscar una clase"), () => ctx.open("finder", { term }), ".quiet"),
    t.mode === "registration" && (inCart || planned) ? btn(inCart ? L(`Register ${inCart} in cart`, `Inscribir ${inCart} del carrito`) : L(`Register all ${planned}`, `Inscribir las ${planned}`),
      () => review("registration", { type: "register", term })) : null);
  return h("div", tabs, d.cannot_register ? blockBox(d.cannot_register, ctx) : note(t.note), meter, conflicts,
    sect(L("Your classes", "Tus clases") + ` · ${t.name}`, h("p.small.muted", L("Tap a class to change its section, linked class, grading, term, or to remove it.", "Toca una clase para cambiar sección, clase enlazada, calificación, trimestre o quitarla.")),
      t.mode === "registration" ? h("p.small.muted", L("Planned = you're thinking about it. In cart = the ones you'll register in one step. Registered = you have a seat.", "Planeada = la estás considerando. En el carrito = las que inscribirás en un paso. Inscrita = tienes lugar.")) : null, rows),
    live.length ? sect(L("Your week", "Tu semana"), weekGrid(live, { onPick: crn => ctx.open("class", { term, crn }) })) : null);
} });

register("class", { title: () => L("Change this class", "Cambiar esta clase"), async render(ctx) {
  const { term, crn } = ctx.args;
  const d = await read("registration", { term }); ctx.stamp(d);
  const i = d.items.find(x => x.crn === crn);
  if (!i) { ctx.land("schedule", { term }); return null; }
  ctx.setTitle(`${i.lecture.course} · ${i.lecture.title}`);
  const t = d.term, change = c => review("registration", { term, crn, ...c });
  const act = (iconName, title, line, fn, tone = "") => h("button.tile" + tone, { type: "button", onclick: fn }, h("span.tile-ico", icon(iconName)), h("span.tile-text", h("strong", title), h("small", line)), icon("chevron"));
  const others = d.terms.filter(x => x.code !== term && x.code !== "202701");
  const acts = [];
  if (i.status === "withdrawn") return h("div", h("p", badge(i.status)), note(L("You withdrew from this class. A W shows on the transcript. Getting back in takes a petition to the Registrar.", "Te retiraste de esta clase. Aparece una W en tu historial. Volver requiere una petición al Registrar.")));
  if (t.mode !== "current") {
    acts.push(act("swap", L("Swap to another section", "Cambiar a otra sección"), L("Different time or instructor, same class", "Otro horario o profesor, misma clase"), () => ctx.open("sections", { term, code: i.lecture.course, swap: crn })));
    if (i.has_linked) acts.push(act("list", L(`Change the ${i.linked ? i.linked.type.toLowerCase() : "linked section"}`, "Cambiar la sección enlazada"), i.linked ? whenWhere(i.linked) : "", () => ctx.open("linked", { term, crn })));
    if (i.status === "planned" || i.status === "cart") others.forEach(o => acts.push(act("calendar", L(`Move to ${o.name}`, `Mover a ${o.name}`), L("Pick a section in that term", "Elige una sección en ese trimestre"), () => ctx.open("sections", { term: o.code, code: i.lecture.course, move: { term, crn } }))));
    if (t.mode === "registration" && i.status === "planned") acts.push(act("plus", L("Put in my cart", "Poner en mi carrito"), L("Ready to register when it opens", "Lista para inscribir cuando abra"), () => change({ type: "cart" })));
    if (i.status === "cart") acts.push(act("minus", L("Take out of my cart", "Sacar de mi carrito"), L("Back to planned", "Vuelve a planeada"), () => change({ type: "uncart" })));
  }
  if (i.can_su) acts.push(act("scale", i.grade_mode === "S/U" ? L("Grade it A-F", "Calificar A-F") : L("Grade it S/U", "Calificar S/U"), L("Now: ", "Ahora: ") + i.grade_mode, () => change({ type: "grade_mode", mode: i.grade_mode === "S/U" ? "Normal grading (A-F)" : "S/U" })));
  let creditPick = null;
  if (i.credit_range) {
    const options = []; for (let n = i.credit_range[0]; n <= i.credit_range[1]; n++) options.push(n);
    creditPick = sect(L("Credits", "Créditos"), h("p.small.muted", L(`This class can be taken for ${i.credit_range[0]} to ${i.credit_range[1]} credits. Now: ${i.credits}.`, `Esta clase permite de ${i.credit_range[0]} a ${i.credit_range[1]} créditos. Ahora: ${i.credits}.`)),
      h("div.seg.wrap", { role: "group", "aria-label": L("Credits", "Créditos") }, options.map(n => h("button", { type: "button", "aria-pressed": String(n === i.credits), disabled: n === i.credits, onclick: () => change({ type: "credits", credits: n }) }, String(n)))));
  }
  if (t.mode === "current") acts.push(act("door", L("Withdraw from this class", "Retirarme de esta clase"), t.can_withdraw ? L(`Leaves a W. Allowed through ${t.withdraw_label}`, `Deja una W. Permitido hasta ${t.withdraw_label}`) : L("The deadline has passed", "La fecha límite pasó"), () => change({ type: "withdraw" }), ".warn"));
  else acts.push(act("trash", i.status === "registered" || i.status === "waitlisted" ? L("Drop this class", "Dar de baja esta clase") : L("Remove from plan", "Quitar del plan"),
    i.status === "registered" ? L("No W: the term hasn't started", "Sin W: el trimestre no ha empezado") : L("Nothing was registered", "No había nada inscrito"), () => review("registration", { term, crn, type: "remove" }, { onDone: () => ctx.land("schedule", { term }) }), ".warn"));
  return h("div", h("p.class-state", badge(i.status), h("span.muted", ` ${t.name} · ${i.credits} ${L("credits", "créditos")} · ${i.grade_mode}`)),
    h("div.sec", h("div.sec-when", weekStrip(i.lecture.meetings), h("span", whenWhere(i.lecture))), h("div.small.muted", `${i.lecture.type} ${i.lecture.section} · ${i.lecture.instructor || ""} · CRN ${i.crn}`), seats(i.lecture)),
    i.linked ? h("div.sec", h("div.sec-when", weekStrip(i.linked.meetings), h("span", whenWhere(i.linked))), h("div.small.muted", `${i.linked.type} ${i.linked.section} · CRN ${i.linked.crn}`)) : null,
    sect(L("What you can change", "Lo que puedes cambiar"), h("div.tiles.one", acts)), creditPick,
    h("p.small.muted", L("CRN is the section's number in the registration system. S/U means graded Satisfactory or Unsatisfactory, with no letter grade.", "CRN es el número de la sección. S/U significa Satisfactorio o No satisfactorio, sin letra.")),
    t.mode === "current" ? note(t.note) : null);
} });

/* Pick a section of a course in a term: for adding, swapping, or moving a class to another term. */
register("sections", { title: a => a.swap ? L("Swap section", "Cambiar sección") : a.move ? L("Move to another term", "Mover a otro trimestre") : L("Pick a section", "Elige una sección"), async render(ctx) {
  const { term, code, swap, move } = ctx.args;
  const [d, reg] = await Promise.all([read("sections", { term, code }), read("registration", { term })]); ctx.stamp(reg);
  if (!swap && !move) ctx.steps([L("Class", "Clase"), L("Section", "Sección"), L("Review", "Revisar"), L("Done", "Listo")], 1);
  ctx.setTitle(swap ? L(`Swap ${code} to another section`, `Cambiar ${code} a otra sección`) : move ? L(`Move ${code} to ${reg.term.name}`, `Mover ${code} a ${reg.term.name}`) : L(`Add ${code} to ${reg.term.name}`, `Agregar ${code} a ${reg.term.name}`));
  const pick = (lec, linked) => review("registration", swap ? { type: "swap", term, crn: swap, to_crn: lec.crn, linked } : move ? { type: "move", term: move.term, crn: move.crn, to_term: term, to_crn: lec.crn, linked }
    : { type: "add", term, crn: lec.crn, linked }, { onDone: () => ctx.land("schedule", { term }) });
  const list = d.sections.filter(s => s.crn !== swap);
  if (!list.length) return empty("calendar", L(`${code} has no ${swap ? "other " : ""}sections in ${reg.term.name}.`, `${code} no tiene ${swap ? "otras " : ""}secciones en ${reg.term.name}.`), btn(L("Back to my classes", "Volver a mis clases"), () => ctx.land("schedule", {})));
  return h("div", h("p.small.muted", `${d.course.title} · ${d.course.credits_text} ${L("credits", "créditos")}. ${L("Pick a lecture. If it has recitations or labs, choose one too, or leave it and the first open one that fits your week is picked. The review shows which.", "Elige una clase. Si tiene recitaciones o laboratorios, elige uno, o se elige el primero disponible que encaje. La revisión muestra cuál.")}`),
    d.course.prereq_text ? note(L("Prerequisite: ", "Prerrequisito: ") + d.course.prereq_text) : null,
    h("div.options", list.map(s => {
      let chosen = null;
      const linked = s.linked.length ? h("div.linked-pick", h("div.label", L("Choose its ", "Elige su ") + s.linked[0].type.toLowerCase()),
        h("div.chips", s.linked.map(k => h("button.chip", { type: "button", "aria-pressed": "false", disabled: k.seats_open <= 0, onclick: e => { chosen = k.crn; [...e.currentTarget.parentNode.children].forEach(x => x.setAttribute("aria-pressed", "false")); e.currentTarget.setAttribute("aria-pressed", "true"); } },
          `${(k.meetings[0] && !k.meetings[0].tba) ? k.meetings[0].days_label + " " + k.meetings[0].time_label.split(" to ")[0] : L("Online", "En línea")}${k.seats_open <= 0 ? L(" · full", " · llena") : ""}`)))) : null;
      return h("article.option.card", h("header.option-head", h("div", h("span.h3", `${s.type} ${s.section}`), h("span.muted.small", ` CRN ${s.crn}`)), seats(s)),
        h("div.sec-when", weekStrip(s.meetings), h("span", whenWhere(s))), h("div.small.muted", [s.instructor, s.campus, s.grade_mode, s.restrictions ? L("Restricted: ", "Restringida: ") + s.restrictions : null].filter(Boolean).join(" · ")),
        linked, h("footer.option-foot", btn(swap ? L("Swap to this one", "Cambiar a esta") : move ? L("Move here", "Mover aquí") : L("Review and add", "Revisar y agregar"), () => pick(s, chosen || undefined))));
    })));
} });

register("linked", { title: () => L("Change the linked section", "Cambiar la sección enlazada"), async render(ctx) {
  const { term, crn } = ctx.args;
  const reg = await read("registration", { term }); ctx.stamp(reg);
  const i = reg.items.find(x => x.crn === crn), d = await read("sections", { term, code: i.lecture.course });
  const s = d.sections.find(x => x.crn === crn);
  return h("div", h("p.small.muted", L(`${i.lecture.course}'s lecture stays the same. Pick a different ${s.linked[0].type.toLowerCase()}.`, "La clase principal no cambia. Elige otra sección enlazada.")),
    h("div.options", s.linked.map(k => h("article.option.card" + (i.linked && i.linked.crn === k.crn ? ".current" : ""), h("header.option-head", h("div", h("span.h3", `${k.type} ${k.section}`), h("span.muted.small", ` CRN ${k.crn}`)), seats(k)),
      h("div.sec-when", weekStrip(k.meetings), h("span", whenWhere(k))),
      h("footer.option-foot", i.linked && i.linked.crn === k.crn ? h("span.badge.registered", L("Current", "Actual")) : btn(L("Switch to this", "Cambiar a esta"), () => review("registration", { type: "linked", term, crn, linked: k.crn }, { onDone: () => ctx.back() })))))));
} });

/* The class finder: step 1 of 4. The draft (what was typed) survives closing the panel. */
register("finder", { title: () => L("Find a class", "Buscar una clase"), async render(ctx) {
  const term = ctx.args.term || ctx.draft.term || "202702";
  ctx.draft.term = term;
  const [reg, left] = await Promise.all([read("registration", { term }), read("degree", { view: "remaining" })]); ctx.stamp(reg);
  ctx.steps([L("Class", "Clase"), L("Section", "Sección"), L("Review", "Revisar"), L("Done", "Listo")], 0);
  const results = h("div.finder-results", { "aria-live": "polite" });
  const input = h("input.input", { type: "search", value: ctx.args.q || ctx.draft.q || "", placeholder: L("Course code or a word, like MTH 254 or writing", "Código o palabra, como MTH 254 o writing"), "aria-label": L("Search classes", "Buscar clases") });
  const go = code => ctx.open("sections", { term, code });
  const search = async () => {
    ctx.draft.q = input.value;
    if (input.value.trim().length < 2) { results.replaceChildren(); return; }
    try {
      const found = (await api.getJSON("/api/demo/courses?q=" + encodeURIComponent(input.value.trim()))).courses;
      results.replaceChildren(found.length ? h("ul.picklist", found.map(c => h("li", h("button", { type: "button", onclick: () => go(c.code) }, h("strong", c.code), h("span", c.title), h("small.muted", c.credits ? `${c.credits} ${L("credits", "créditos")}` : "")))))
        : empty("search", L("No class matches that. Try a course code like MTH 254, or one word from the title.", "Ninguna clase coincide. Prueba un código como MTH 254 o una palabra del título.")));
    } catch (e) { results.replaceChildren(empty("alert", explain({ code: "offline" }))); }
  };
  let timer; input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 220); });
  if (input.value) search();
  const needs = (left.items || []).filter(i => i.code).slice(0, 6);
  return h("div", h("p.small.muted", `${L("Adding to", "Agregando a")} ${reg.term.name}. ${reg.term.note}`), input, results,
    needs.length ? sect(L("Still on your requirements", "Aún en tus requisitos"), h("ul.picklist", needs.map(n => h("li", h("button", { type: "button", onclick: () => go(n.code) }, h("strong", n.code), h("span", n.title), h("small.muted", n.requirement || "")))))) : null);
} });

/* ---- advising ------------------------------------------------------------------------------------- */
register("advising", { title: () => L("Your advisor", "Tu asesor"), async render(ctx) {
  const d = await read("advising"); ctx.stamp(d);
  const up = d.appointments.upcoming[0], hold = d.holds.find(x => x.blocks && x.type === "advising");
  return h("div", h("p", h("strong", d.advisor), h("span.muted", ` · ${d.office}`)),
    hold ? note(L("An advising hold is blocking registration. It comes off after you meet, not when you book.", "Una retención de asesoría bloquea la inscripción. Se quita después de la reunión, no al reservar."), ".warn") : null,
    up ? h("div.callout.ok", icon("check"), h("div", h("strong", `${L("You're meeting", "Tienes cita")} ${up.day_inline} ${L("at", "a las")} ${up.time_label}`), h("p.small.muted", `${up.mode} · ${up.minutes} min · ${up.location || ""}`),
      h("div.row-actions", btn(L("Cancel meeting", "Cancelar cita"), () => review("advising", { type: "cancel" }), ".quiet"),
        hold ? btn(L("Demo: pretend we met", "Demo: fingir que nos reunimos"), () => review("advising", { type: "attend" }), ".plain") : null))) : null,
    sect(up ? L("Move it to another time", "Moverla a otro horario") : L("Open times", "Horarios disponibles"),
      d.slots.length ? h("ul.slots", d.slots.map(s => h("li", h("button.slot", { type: "button", onclick: () => review("advising", { type: "book", slot: s.id }) }, h("strong", `${s.day_label}`), h("span", s.time_label), h("small.muted", `${s.mode} · ${s.minutes} min`)))))
        : empty("calendar", L("No open times this week. Check back, or email the advising office.", "Sin horarios esta semana."))),
    d.appointments.past.length ? sect(L("Past meetings", "Citas pasadas"), h("ul.plain", d.appointments.past.slice(0, 3).map(a => h("li.small.muted", `${day(a.date)} · ${a.topic}`)))) : null);
} });

/* ---- billing --------------------------------------------------------------------------------------- */
register("billing", { title: () => L("Your bill", "Tu cuenta"), async render(ctx) {
  const d = await read("billing"); ctx.stamp(d);
  const b = d.billing;
  return h("div", h("div.bigfig", h("span.muted", `${b.term} ${L("balance", "saldo")}`), h("strong", money(b.balance)),
    h("span" + (b.past_due > 0 ? ".bad" : ".muted"), b.balance <= 0 ? L("Nothing is due.", "Nada pendiente.") : b.past_due > 0 ? `${money(b.past_due)} ${L("is past due", "está vencido")}` : `${L("Due", "Vence")} ${b.due_label}`)),
    d.holds.filter(x => x.blocks).map(x => note(`${x.title}: ${x.how_to_clear}`, ".warn")),
    b.plan_enrolled ? h("div.callout.ok", icon("check"), h("div", h("strong", L("You're on a payment plan this term", "Tienes un plan de pagos este trimestre")))) : null,
    b.balance > 0 ? handoff(d.handoff, L("Paying", "El pago"), btn(L("Review paying it", "Revisar el pago"), () => review("billing", { type: "paid" }))) : null,
    h("div.row-actions", b.balance > 0 && !b.plan_enrolled ? btn(L("Join a payment plan", "Unirme a un plan de pagos"), () => review("billing", { type: "enroll_plan" }), ".quiet") : null),
    sect(L("Good to know", "Conviene saber"), h("ul.plain", d.rules.map(r => h("li.small", r)))),
    sect(L("This term's activity", "Movimientos del trimestre"), h("ul.ledger", b.transactions.map(x => h("li", h("span.muted", day(x.date)), h("span", x.description), h("strong" + (x.amount < 0 ? ".good" : ""), money(x.amount)))))),
    sect(L("Statements", "Estados de cuenta"), h("ul.ledger", d.statements.map(x => h("li", h("span.muted", day(x.date)), h("span", `${L("Due", "Vence")} ${day(x.due)}`), h("strong", money(x.amount)))))));
} });

/* ---- housing --------------------------------------------------------------------------------------- */
register("housing", { title: () => L("Housing", "Vivienda"), async render(ctx) {
  const d = ctx.args.reveal ? await post("reveal", { system: "housing" }) : await read("housing"); ctx.stamp(d);
  ctx.args.reveal = false;                      /* shown once: any redraw hides it again */
  if (!d.on_campus) return empty("home", L("You don't live in a residence hall, so there's no room, mailbox or maintenance to show.", "No vives en una residencia, así que no hay cuarto ni buzón que mostrar."));
  const area = h("select.input", { "aria-label": L("Where is the problem?", "¿Dónde está el problema?") }, d.areas.map(a => h("option", a)));
  const text = h("textarea.input", { rows: 3, maxLength: 300, placeholder: L("What's wrong? One or two sentences.", "¿Qué pasa? Una o dos frases."), "aria-label": L("Describe the problem", "Describe el problema") });
  text.value = ctx.draft.text || ""; text.addEventListener("input", () => { ctx.draft.text = text.value; });
  /* A sensitive detail: hidden until a fresh "it's really me" step. */
  const reveal = btn(L("Show the combination", "Mostrar la combinación"), async () => {
    if (await verify(L("Your mailbox combination is hidden by default. Showing it needs a fresh check.", "La combinación de tu buzón está oculta. Mostrarla requiere una verificación."))) ctx.replace("housing", { reveal: true });
  }, ".quiet");
  return h("div", sect(L("Your room", "Tu cuarto"), kv(L("Hall", "Residencia"), d.room.hall), kv(L("Room", "Cuarto"), `${d.room.room} · ${d.room.type}`)),
    sect(L("Mail", "Correo"), kv(L("Mailbox", "Buzón"), d.mail.box), d.mail.hidden ? h("div.kv", h("span.muted", L("Combination", "Combinación")), h("span", "• • •  ", reveal)) : kv(L("Combination", "Combinación"), d.mail.combination),
      d.mail.hidden ? null : h("p.small.muted", L("Shown for this view only. It is hidden again next time.", "Se muestra solo esta vez."))),
    sect(L("Maintenance request", "Solicitud de mantenimiento"), note(d.urgent, ".warn"), area, text,
      h("div.row-actions", btn(L("Review request", "Revisar solicitud"), () => { if (text.value.trim().length < 8) { toast(L("Describe the problem in a sentence first.", "Primero describe el problema en una frase.")); text.focus(); return; }
        review("housing", { type: "maintenance", area: area.value, description: text.value }, { onDone: () => { ctx.draft.text = ""; } }); }))),
    sect(L("Your requests", "Tus solicitudes"), d.requests.length ? h("ul.ledger", d.requests.map(r => h("li", h("span.muted", day(r.filed)), h("span", `${r.area}: ${r.description}`), h("span.badge." + (r.status === "Open" ? "cart" : "withdrawn"), r.status),
      r.status === "Open" ? link(L("Cancel", "Cancelar"), () => review("housing", { type: "cancel_request", id: r.id })) : null))) : h("p.small.muted", L("No requests yet.", "Aún no hay solicitudes."))));
} });

/* ---- ID card ---------------------------------------------------------------------------------------- */
register("card", { title: () => L("ID card and dining money", "Credencial y dinero de comida"), async render(ctx) {
  const d = await read("card"); ctx.stamp(d);
  return h("div", idCard(d, profile()),
    d.accounts.filter(a => a.note).map(a => h("p.small.muted.aside", `${a.name}: ${a.note}`)),
    d.accounts.some(a => a.low) ? note(L("Running low. At this pace it won't last the term.", "Queda poco. A este ritmo no alcanza para el trimestre."), ".warn") : null,
    d.note ? note(d.note) : null,
    handoff(d.handoff, L("Adding money", "Agregar dinero"), [10, 25, 50].map(n => btn(L(`Review adding $${n}`, `Revisar agregar $${n}`), () => review("card", { type: "add_money", amount: n, account: "Orange Cash" }), ".quiet"))),
    sect(L("Last 30 days", "Últimos 30 días"), d.transactions.length ? null : h("p.small.muted", L("No purchases.", "Sin compras.")), h("ul.ledger", d.transactions.map(x => h("li", h("span.muted", day(x.date)), h("span", `${x.place} · ${x.account}`), h("strong", money(x.amount)))))));
} });

/* ---- parking ---------------------------------------------------------------------------------------- */
register("parking", { title: () => L("Parking", "Estacionamiento"), async render(ctx) {
  const d = await read("parking"); ctx.stamp(d);
  const plate = h("input.input", { maxLength: 8, placeholder: L("Plate, like ABC123", "Placa, como ABC123"), "aria-label": L("Licence plate", "Placa") });
  return h("div", sect(L("Your permits", "Tus permisos"), d.permits.length ? h("ul.ledger", d.permits.map(p => h("li", h("strong", p.name), h("span.badge.registered", L("Active (sample)", "Activo (muestra)")))))
      : empty("pin", L("No active permits.", "Sin permisos activos."))),
    sect(L("Permits you can get", "Permisos que puedes obtener"), note(d.eligibility),
      h("ul.permits", d.for_sale.map(p => h("li.permit" + (p.sold_out && !p.owned ? ".off" : ""), h("span.tag-zone", { "aria-hidden": "true" }, p.id), h("div.permit-main", h("strong", p.name), h("small.muted", p.zone)), h("strong.permit-price", money(p.price)),
        h("div.permit-act", p.owned ? h("span.badge.registered", L("Yours", "Tuyo"))
          : p.sold_out ? (p.on_waitlist ? [h("span.badge.waitlisted", L("On waitlist", "En lista")), btn(L("Leave waitlist", "Salir de la lista"), () => review("parking", { type: "leave_waitlist", permit: p.id }), ".quiet")]
            : [h("span.badge.withdrawn", L("Sold out", "Agotado")), btn(L("Join waitlist", "Unirme a la lista"), () => review("parking", { type: "join_waitlist", permit: p.id }))])
            : btn(L("Review buying it", "Revisar la compra"), () => review("parking", { type: "buy_permit", permit: p.id }))))))),
    handoff(d.handoff, L("Buying a permit", "Comprar un permiso")),
    sect(L("Your vehicles", "Tus vehículos"), d.vehicles.length ? h("ul.ledger", d.vehicles.map(v => h("li", h("strong", v.plate), link(L("Remove", "Quitar"), () => review("parking", { type: "remove_vehicle", plate: v.plate })))))
      : h("p.small.muted", L("No vehicles yet. Your plate is your permit.", "Sin vehículos. Tu placa es tu permiso.")),
      h("div.inline-form", plate, btn(L("Add vehicle", "Agregar vehículo"), () => { if (plate.value.replace(/[^a-z0-9]/gi, "").length < 3) { toast(L("Type the plate first: at least 3 letters or numbers.", "Escribe la placa: al menos 3 letras o números.")); plate.focus(); return; }
        review("parking", { type: "add_vehicle", plate: plate.value }, { onDone: () => { plate.value = ""; } }); }))),
    sect(L("Citations", "Multas"), h("p.small.muted", L("No unpaid citations.", "Sin multas pendientes."))));
} });

/* ---- careers ---------------------------------------------------------------------------------------- */
register("careers", { title: () => L("Jobs and career help", "Empleos y orientación"), async render(ctx) {
  const d = await read("careers"); ctx.stamp(d);
  return h("div", sect(L("Career advising", "Asesoría profesional"),
    d.appointment ? h("div.callout.ok", icon("check"), h("div", h("strong", d.appointment.label), h("div.row-actions", btn(L("Cancel", "Cancelar"), () => review("careers", { type: "cancel_career" }), ".quiet"))))
      : h("ul.slots", d.slots.map(s => h("li", h("button.slot", { type: "button", onclick: () => review("careers", { type: "book_career", slot: s.id }) }, h("strong", s.label)))))),
    sect(L("Jobs you might like", "Empleos que podrían interesarte"), h("ul.ledger.tall", d.jobs.map(j => h("li", h("span", h("strong", j.title), h("small.muted", ` ${j.employer} · ${j.pay} · ${j.type} · ${L("apply by", "postula antes del")} ${day(j.apply_by)}`)),
      h("span.job-acts", btn(j.saved ? L("Saved · Remove", "Guardado · Quitar") : L("Save", "Guardar"), () => review("careers", { type: j.saved ? "unsave_job" : "save_job", job: j.id }), j.saved ? ".quiet" : ".plain"),
        j.applied ? h("span.badge.registered", L("Applied (sample)", "Postulado (muestra)")) : btn(L("Review applying", "Revisar postulación"), () => review("careers", { type: "apply_job", job: j.id }), ".quiet")))))),
    handoff(d.handoff, L("Applying", "Postular")),
    sect(L("Profile checklist", "Lista del perfil"), h("ul.checks", d.checklist.map(c => check(c.done, c.title, !c.done)))));
} });

/* ---- library ---------------------------------------------------------------------------------------- */
register("library", { title: () => L("Library", "Biblioteca"), async render(ctx) {
  const d = await read("library"); ctx.stamp(d);
  const dr = ctx.draft; dr.date = dr.date || d.days[0].date; dr.time = dr.time || d.times[2];
  const pick = (items, key, label) => h("div.seg.wrap", { role: "radiogroup", "aria-label": label }, items.map(([v, text]) => h("button", { type: "button", role: "radio", "aria-checked": String(dr[key] === v), onclick: () => { dr[key] = v; ctx.reload(); } }, text)));
  return h("div", d.note ? note(d.note) : null, sect(L("Your bookings", "Tus reservas"), d.bookings.length ? h("ul.ledger", d.bookings.map(b => h("li", h("span", h("strong", b.room), h("small.muted", ` ${b.label} · ${b.time}`)), link(L("Cancel", "Cancelar"), () => review("library", { type: "cancel_room", id: b.id })))))
    : h("p.small.muted", L("No study rooms booked.", "Sin salas reservadas."))),
    sect(L("Book a study room", "Reservar una sala"), h("p.small.muted", d.limit), pick(d.days.map(x => [x.date, x.label]), "date", L("Day", "Día")), pick(d.times.map(x => [x, x]), "time", L("Start time", "Hora")),
      h("ul.ledger.tall", d.rooms.map(r => h("li", h("span", h("strong", r.name), h("small.muted", ` ${L("Floor", "Piso")} ${r.floor} · ${L("up to", "hasta")} ${r.seats}${r.monitor ? L(" · monitor", " · monitor") : ""}`)),
        btn(L("Book", "Reservar"), () => review("library", { type: "book_room", room: r.id, date: dr.date, time: dr.time }), ".plain"))))),
    sect(L("Loans and fines", "Préstamos y multas"), h("p.small.muted", L("Nothing checked out, no requests, no fines.", "Nada prestado, sin solicitudes ni multas."))));
} });

/* ---- coursework ------------------------------------------------------------------------------------- */
register("canvas", { title: () => L("Coursework", "Tareas"), async render(ctx) {
  const d = await read("canvas"); ctx.stamp(d);
  return h("div", note(d.note), sect(L("Due next", "Próximas entregas"), d.todo.length ? h("ul.ledger", d.todo.map(x => h("li", h("span.muted", day(x.due)), h("span", x.title), h("strong", x.course)))) : empty("check", L("Nothing due.", "Nada pendiente."))),
    sect(L("Your courses", "Tus cursos"), h("ul.plain", d.courses.map(c => h("li", h("strong", c.course), h("span.muted", ` ${c.title} · ${plural(c.due.length, "item")} ${L("due", "por entregar")}`))))));
} });

/* ---- degree progress: the audit, what's left, a winter plan, the checklist, what-if ---------------------- */
register("degree", { title: () => L("Degree progress", "Avance del título"), async render(ctx) {
  const view = ctx.args.view || ctx.draft.view || "audit"; ctx.draft.view = view;
  const tabs = h("div.seg.terms", { role: "tablist" }, [["audit", L("Requirements", "Requisitos")], ["remaining", L("What's left", "Lo que falta")], ["plan", L("Suggested winter classes", "Clases sugeridas de invierno")], ["checklist", L("Before registering", "Antes de inscribir")], ["whatif", L("What if", "Qué pasaría si")]]
    .map(([v, text]) => h("button", { type: "button", role: "tab", "aria-selected": String(v === view), onclick: () => { ctx.args.view = v; ctx.draft.view = v; ctx.reload(); } }, text)));
  if (view === "whatif") {
    const out = h("div", { "aria-live": "polite" });
    const input = h("input.input", { type: "search", placeholder: L("A major or minor, like Computer Science", "Una carrera, como Computer Science"), "aria-label": L("Major or minor", "Carrera") });
    const show = async id => { try { const w = await read("degree", { view: "whatif", program: id }); ctx.stamp(w);
      out.replaceChildren(h("div.callout", icon("info"), h("div", h("strong", `${w.program.name}: ${w.counted.length} ${L("of", "de")} ${w.total} ${L("requirements already covered", "requisitos ya cubiertos")}`), h("p.small.muted", `${w.needed.length} ${L("would be new. This changes nothing on your record.", "serían nuevos. Esto no cambia nada en tu expediente.")}`))),
        sect(L("Already counts", "Ya cuenta"), h("ul.plain", w.counted.slice(0, 12).map(c => h("li.small", c.label || c.requirement || "")))), sect(L("Still needed", "Aún falta"), h("ul.plain", w.needed.slice(0, 14).map(c => h("li.small", c.label || c.requirement || ""))))); } catch (e) { toast(explain(e)); } };
    let timer; input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(async () => {
      const found = input.value.trim().length > 1 ? (await api.getJSON("/api/demo/programs?q=" + encodeURIComponent(input.value.trim()))).programs : [];
      out.replaceChildren(h("ul.picklist", found.map(p => h("li", h("button", { type: "button", onclick: () => show(p.id) }, h("strong", p.name), h("small.muted", p.degree || ""))))));
    }, 220); });
    return h("div", tabs, h("p.small.muted", L("See how your classes would count toward another major or minor. No form, and nothing is changed.", "Mira cómo contarían tus clases para otra carrera. Sin formulario y sin cambiar nada.")), input, out);
  }
  const d = await read("degree", { view }); ctx.stamp(d);
  if (view === "remaining") return h("div", tabs, h("p", d.caught_up ? L("You're caught up on this year's requirements.", "Vas al día con los requisitos de este año.") : L(`${d.count} requirements left this year.`, `Faltan ${d.count} requisitos este año.`)),
    h("ul.ledger.tall", d.items.map(i => h("li", h("span", h("strong", i.code || i.requirement), h("small.muted", ` ${i.title || ""}`)), i.code ? btn(L("Find sections", "Ver secciones"), () => ctx.open("sections", { term: "202702", code: i.code }), ".plain") : null))));
  if (view === "plan") return h("div", tabs, h("p", L(`A winter plan to bring to ${d.advisor}: ${d.picks.length} classes, ${d.credits} credits, no time clashes.`, `Un plan de invierno para ${d.advisor}: ${d.picks.length} clases, ${d.credits} créditos.`)),
    note(L("This is a suggestion. Nothing is in your plan until you add it.", "Es una sugerencia. Nada está en tu plan hasta que lo agregues.")),
    h("ul.ledger.tall", d.picks.map(p => h("li", h("span", h("strong", p.course.code), h("small.muted", ` ${p.course.title} · ${whenWhere(p.option.lecture)} · ${L("for", "para")} ${p.requirement}`))))),
    h("div.row-actions", btn(L("Review and add all", "Revisar y agregar todo"), () => review("registration", { type: "add_many", term: "202702", items: d.picks.map(p => ({ crn: p.option.lecture.crn, linked: p.option.linked ? p.option.linked.crn : undefined })) }, { onDone: () => ctx.land("schedule", { term: "202702" }) }))));
  if (view === "checklist") return h("div", tabs, bar(d.done, d.total, L("Ready to register", "Lista para inscribir")), h("ul.checks", d.items.map(i => h("li.chk" + (i.done ? ".ok" : ".no"), icon(i.done ? "check" : "x"), h("span", h("strong", i.title), h("small.muted", ` ${i.detail}`)),
    !i.done && i.action ? link(L("Fix this", "Resolver"), () => ctx.open({ appointment: "advising", plan: "finder", billing: "billing" }[i.action] || "schedule")) : null))));
  return h("div", tabs, h("div.audit-top", progressRing(d.percent), h("div", h("strong", `${d.counts.met} ${L("done", "hechos")} · ${d.counts.in_progress} ${L("in progress", "en curso")} · ${d.counts.needed + d.counts.not_met} ${L("to go", "por hacer")}`), h("p.small.muted", d.snapshot))),
    d.blocks.map(b => h("details.audit-block", h("summary", h("strong", b.name), h("span.muted", ` ${b.done} ${L("of", "de")} ${b.total}`)), h("ul.checks", b.requirements.map(r => h("li.chk" + (r.status === "met" ? ".ok" : r.status === "not_met" ? ".warn" : ".no"),
      icon(r.status === "met" ? "check" : r.status === "not_met" ? "alert" : "minus"), h("span", h("strong", r.label), h("small.muted", ` ${d.notes[r.note] ? d.notes[r.note].title + ". " + d.notes[r.note].text : ""}`))))))));
} });

/* ---- health and access: the light-touch rule --------------------------------------------------------- */
register("wellness", { title: () => L("Health and access", "Salud y accesibilidad"), async render(ctx) {
  const d = await read("wellness"); ctx.stamp(d);
  return h("div", note(d.rule), h("ul.ledger.tall", d.items.map(i => h("li", h("span", h("strong", i.office), h("small.muted", ` ${i.line}`)), h("span.small.muted", `${L("Details are in", "Los detalles están en")} ${i.portal}`)))));
} });

/* ---- forms and BeaverHub tools (public catalog data, no session needed) -------------------------------- */
register("finders", { title: () => L("Forms and BeaverHub tools", "Formularios y herramientas"), async render(ctx) {
  const out = h("div", { "aria-live": "polite" });
  const input = h("input.input", { type: "search", value: ctx.draft.q || "", placeholder: L("What are you trying to do? Like: change grading, pay my bill", "¿Qué quieres hacer? Ej.: cambiar calificación"), "aria-label": L("Search forms and tools", "Buscar") });
  const run = async () => {
    ctx.draft.q = input.value; const q = encodeURIComponent(input.value.trim());
    const [f, r] = await Promise.all([api.getJSON("/api/demo/forms?q=" + q), api.getJSON("/api/demo/resources?q=" + q)]);
    out.replaceChildren(sect(L("Forms", "Formularios"), f.forms.length ? h("ul.ledger.tall", f.forms.slice(0, 6).map(x => h("li", h("span", h("strong", x.name), h("small.muted", ` ${x.purpose} ${L("Goes to", "Va a")} ${x.goes_to}.`))))) : h("p.small.muted", L("No form matches.", "Ningún formulario coincide."))),
      sect(L("BeaverHub tools, in plain words", "Herramientas de BeaverHub, en palabras simples"), r.resources.length ? h("ul.ledger.tall", r.resources.slice(0, 8).map(x => h("li", h("span", h("strong", x.name), h("small.muted", ` ${x.plain || x.description || ""}`))))) : h("p.small.muted", L("No tool matches.", "Ninguna herramienta coincide."))),
      note(L("Beaver Bot never submits a form for you. It shows which one, what it's for, and who gets it.", "Beaver Bot nunca envía un formulario por ti.")));
  };
  let timer; input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 220); });
  run();
  return h("div", input, out);
} });

/* ---- what was done this session, with Undo -------------------------------------------------------------- */
register("history", { title: () => L("What I've done this session", "Lo que he hecho en esta sesión"), async render(ctx) {
  const d = await read("history");
  if (!d.history.length) return empty("clock", L("Nothing has been changed yet. Every change you confirm shows up here, with Undo where the real system would allow it.", "Aún no se ha cambiado nada. Cada cambio que confirmes aparece aquí."));
  return h("ul.history", d.history.map(e => h("li" + (e.undone ? ".undone" : ""), h("span.muted.small", e.at), h("div", h("strong", e.summary), e.details.map(x => h("p.small.muted", x)), e.undone ? h("p.small.muted", L("Undone.", "Deshecho.")) : null),
    e.can_undo ? btn(L("Undo", "Deshacer"), () => undo(e.id), ".quiet") : e.undone || /^Undid/.test(e.summary) ? null
      : h("span.small.muted", /can't be undone|W will show/.test(e.summary + e.details.join(" ")) ? L("Can't be undone", "No se puede deshacer") : L("Undo the newer change first", "Deshaz primero el cambio más nuevo")))));
} });

/* ---- demo controls --------------------------------------------------------------------------------------- */
register("controls", { title: () => L("Demo controls", "Controles de la demostración"), async render(ctx) {
  const s = session(), p = profile();
  return h("div", note(L("These exist only so the demo can show what happens next. A real version would have none of them.", "Solo existen para mostrar lo que pasa después. Una versión real no los tendría.")),
    sect(L("Pretend it's a later day", "Fingir que es otro día"), h("p.small.muted", s.clockDays ? L(`The demo is running ${s.clockDays} days ahead, so registration is open.`, `La demo va ${s.clockDays} días adelante.`) : L("Registration hasn't opened yet for any sample student. Jump ahead to try registering.", "La inscripción aún no abre. Adelanta el día para probarla.")),
      h("div.row-actions", btn(L("Jump to registration week", "Ir a la semana de inscripción"), () => setClock(8), s.clockDays ? ".quiet" : ""), s.clockDays ? btn(L("Back to today", "Volver a hoy"), () => setClock(0)) : null)),
    sect(L("Start over", "Empezar de nuevo"), h("div.row-actions", btn(L(`Reset ${p ? p.first_name : "this student"}'s sample data`, "Reiniciar los datos de este estudiante"), () => reset(false), ".quiet"), btn(L("Reset the whole demo", "Reiniciar toda la demo"), e => { const b = e.currentTarget; if (b.dataset.armed) return reset(true); b.dataset.armed = "1"; b.textContent = L("Really reset everything? Press again", "¿Reiniciar todo? Presiona otra vez"); }, ".quiet"))),
    sect(L("Account", "Cuenta"), h("p.small.muted", L("To try another sample student, sign out and pick a different account on the sign-in page. Each visitor has their own copy of the sample data.", "Para probar otro estudiante, cierra sesión y elige otra cuenta. Cada visitante tiene su propia copia de los datos.")),
      h("div.row-actions", btn(L("Sign out", "Cerrar sesión"), () => signOut(), ".quiet"))));
} });

/* The card under a chat reply: a short summary that opens the full panel. */
export const PANEL_FOR = { registration: "schedule", schedule: "schedule", finder_options: "schedule", finder_prefs: "finder", finder_course: "finder", appointment: "advising",
  checklist: ["degree", { view: "checklist" }], remaining: ["degree", { view: "remaining" }], plan: ["degree", { view: "plan" }], audit: ["degree", { view: "audit" }],
  whatif: ["degree", { view: "whatif" }], whatif_ask: ["degree", { view: "whatif" }], billing: "billing", forms: "finders", resources: "finders" };
