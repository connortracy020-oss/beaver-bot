/* Cards under a chat reply that list classes. SAMPLE DATA ONLY.

   The main one is the suggested schedule, which the student edits right in the chat before anything is added:
   remove a class, swap its section, replace it with another class that meets the same requirement, or add one.
   The list being edited is a draft, like the contents of a form. Every edit asks the server what the draft looks
   like now (times, credits, clashes), and "Review and add" sends it through the same review, confirm and undo
   steps as every other change. Nothing here changes the student's classes on its own. */
import { h, clear, icon, reducedMotion } from "../dom.js";
import { buddy } from "../buddy.js";
import { toast, announce } from "../ui.js";
import { L, post, review, openPanel, explain, undo, showOnDesk } from "./core.js";
import { classRow, statusRows, week, credits, classes, seatsText, num } from "./rows.js";

const sample = () => h("span.pill.sample", L("Sample data", "Datos de muestra"));
const btn = (label, onclick, { cls = ".quiet", ico = null, key = null, disabled = false } = {}) =>
  h("button.btn.small" + cls, { type: "button", onclick, disabled, "data-key": key }, ico ? icon(ico) : null, h("span", label));

/* ---- the questions asked once, before the first plan --------------------------------------------------- */
/* Answers are kept by Beaver Bot for the session (never written into a university system) and reused by the class
   finder. Every question can be left at "No preference", and the whole thing can be skipped. */
const QUESTIONS = () => [
  { key: "times", many: true, label: L("What time of day?", "¿A qué hora del día?"), hint: L("Pick any.", "Elige las que quieras."),
    options: [["morning", L("Mornings", "Mañanas")], ["midday", L("Midday", "Mediodía")], ["afternoon", L("Afternoons", "Tardes")], ["evening", L("Evenings", "Noches")]],
    extra: ["no8", L("No 8 AMs", "Nada a las 8 AM")] },
  { key: "days", label: L("Which days?", "¿Qué días?"), options: [["mwf", L("Mon, Wed, Fri", "Lun, mié, vie")], ["tr", L("Tue, Thu", "Mar, jue")], ["four", L("4 days, Fridays off", "4 días, viernes libre")], ["five", L("5 days", "5 días")]] },
  { key: "gap", label: L("Time between classes?", "¿Tiempo entre clases?"), options: [["tight", L("Back to back", "Seguidas")], ["short", L("10 to 30 minutes", "10 a 30 minutos")], ["long", L("An hour or more", "Una hora o más")]] },
  { key: "credits", label: L("How many credits?", "¿Cuántos créditos?"), hint: L("Full-time starts at 12. The limit is 19.", "Tiempo completo desde 12. El límite es 19."), options: [["12", "12"], ["13-15", "13–15"], ["16+", "16+"]] },
  { key: "mode", label: L("In person or online?", "¿Presencial o en línea?"), options: [["campus", L("In person", "Presencial")], ["online", L("Online", "En línea")]] },
  { key: "busy", many: true, label: L("Times to keep open (work, practice)?", "¿Horas que quieres libres (trabajo, práctica)?"),
    options: [["evenings", L("Evenings, after 5", "Noches, después de las 5")], ["fridays", L("Fridays", "Viernes")], ["mornings", L("Mornings, before 10", "Mañanas, antes de las 10")]] },
];
/* The answers as short chips: "Mornings · Mon, Wed, Fri · 13–15 credits". */
export function prefChips(prefs) {
  const out = [];
  for (const q of QUESTIONS()) {
    const v = prefs[q.key], name = k => (q.options.find(o => o[0] === k) || [k, k])[1];
    if (q.many) (v || []).filter(k => q.options.some(o => o[0] === k)).forEach(k => out.push(q.key === "busy" ? L(`Free: ${name(k)}`, `Libre: ${name(k)}`) : name(k)));
    else if (v && q.options.some(o => o[0] === v)) out.push(q.key === "credits" ? L(`${name(v)} credits`, `${name(v)} créditos`) : name(v));
    if (q.extra && prefs[q.extra[0]]) out.push(q.extra[1]);
  }
  return out;
}
function prefsForm(prefs, { onBuild, onSkip, onCancel }) {
  const a = { times: [...(prefs.times || [])], busy: [...(prefs.busy || [])], days: prefs.days || null, gap: prefs.gap || null, credits: prefs.credits || null, mode: prefs.mode || null, no8: !!prefs.no8, note: prefs.note || "" };
  const form = h("div.prefs-form");
  const draw = () => {
    clear(form);
    QUESTIONS().forEach(q => {
      const on = k => (q.many ? a[q.key].includes(k) : a[q.key] === k), nothing = q.many ? !a[q.key].length && !(q.extra && a[q.extra[0]]) : !a[q.key];
      const opt = (label, pressed, onclick) => h("button.opt", { type: "button", "aria-pressed": String(pressed), onclick: () => { onclick(); const at = [...form.querySelectorAll("button")].indexOf(document.activeElement); draw(); const b = form.querySelectorAll("button")[at]; b && b.focus({ preventScroll: true }); } }, label);
      form.append(h("fieldset.pref-q", h("legend", q.label, q.hint ? h("small.muted", " " + q.hint) : null), h("div.opts",
        q.options.map(([k, label]) => opt(label, on(k), () => { if (q.many) a[q.key] = on(k) ? a[q.key].filter(x => x !== k) : [...a[q.key], k]; else a[q.key] = on(k) ? null : k; })),
        q.extra ? opt(q.extra[1], a[q.extra[0]], () => { a[q.extra[0]] = !a[q.extra[0]]; }) : null,
        opt(L("No preference", "Sin preferencia"), nothing, () => { if (q.many) a[q.key] = []; else a[q.key] = null; if (q.extra) a[q.extra[0]] = false; }))));
    });
    const other = h("input.input", { type: "text", value: a.note, maxlength: "120", placeholder: L("Other: anything else, like “work Tue 2 to 6”", "Otro: algo más, como “trabajo mar 2 a 6”"), "aria-label": L("Other", "Otro"), oninput: e => { a.note = e.target.value; } });
    form.append(h("fieldset.pref-q", h("legend", L("Other", "Otro"), h("small.muted", L(" Kept as a note with your plan. It isn't used to pick sections yet.", " Se guarda como nota con tu plan. Aún no se usa para elegir secciones."))), other),
      h("div.row-actions", h("button.btn.small", { type: "button", onclick: () => onBuild(a) }, icon("check"), h("span", L("Build my plan", "Armar mi plan"))),
        onSkip ? h("button.btn.small.quiet", { type: "button", onclick: onSkip }, L("Skip, just build it", "Omitir, solo ármalo")) : null,
        onCancel ? h("button.btn.small.plain", { type: "button", onclick: onCancel }, L("Cancel", "Cancelar")) : null),
      h("p.small.muted", icon("lock"), L(" Beaver Bot keeps these answers for this session. They are never written into a university system.", " Beaver Bot guarda estas respuestas durante esta sesión. Nunca se escriben en un sistema de la universidad.")));
  };
  draw();
  return form;
}
export function prefsCard(card) {
  const root = h("section.dcard.card.planner.prefs-card", { "aria-label": L("A few questions before your plan", "Unas preguntas antes de tu plan") });
  const go = async prefs => {
    root.classList.add("busy");
    try { root.replaceWith(showDraft(await post("draft", prefs ? { op: "build", prefs } : { op: "build", prefs: {} }))); announce(L("Your plan is ready below.", "Tu plan está listo abajo.")); }
    catch (e) { toast(explain(e)); root.classList.remove("busy"); }
  };
  root.append(h("header.dcard-head", h("span.dcard-ico", icon("sliders")), h("strong", L(`A few questions before your ${card.term.name} plan`, `Unas preguntas antes de tu plan de ${card.term.name}`)), sample()),
    h("div.dcard-body", prefsForm(card.prefs || {}, { onBuild: go, onSkip: () => go(null) })));
  return root;
}

/* Only one plan card can be worked on and confirmed. A newer one retires the one before it. */
let live = null;
const watchers = [];
/* The question bar's shelf listens here, to say what is being worked on. */
export const watchDraft = fn => watchers.push(fn);
const tell = info => watchers.forEach(fn => { try { fn(info); } catch (e) { /* the shelf is optional */ } });
export function showDraft(card) {
  const el = draftCard(card);
  if (live && live !== el && live.isConnected) live.retire();
  live = el;
  el.report();
  showOnDesk("degree", { view: "remaining" });        /* beside a plan, the desk shows what is still left to take */
  return el;
}

/* ---- motion: things move from where they were to where they are, so a change can be followed ---------- */
const SPRING = "cubic-bezier(.2,1.25,.3,1)";
function glide(el, from, ms = 520) {
  const to = el.getBoundingClientRect();
  const dx = from.left - to.left, dy = from.top - to.top;
  if (Math.abs(dx) < 1 && Math.abs(dy) < 1 && Math.abs(from.height - to.height) < 1) return;
  el.animate([{ transform: `translate(${dx}px, ${dy}px) scaleY(${from.height / Math.max(1, to.height)})`, transformOrigin: "top left" }, { transform: "none", transformOrigin: "top left" }], { duration: ms, easing: SPRING });
}
function countUp(el, from, to, write, ms = 600) {
  if (reducedMotion() || from === to || from == null) { el.textContent = write(to); return; }
  const start = performance.now();
  const tick = now => {
    const t = Math.min(1, (now - start) / ms), eased = 1 - Math.pow(1 - t, 3);
    el.textContent = write(Math.round((from + (to - from) * eased) * 2) / 2);
    if (t < 1 && el.isConnected) requestAnimationFrame(tick); else el.textContent = write(to);
  };
  requestAnimationFrame(tick);
}
const DAYS = "MTWRF";

/* ---- the schedule a student can edit before adding it ------------------------------------------------ */
export function draftCard(card) {
  const term = card.term.code;
  const onItems = null;
  let shown = null;           /* what was on screen before a redraw: where each row and block was, and the totals */
  let data = card, items = card.items.map(i => ({ ...i })), open = null, done = null, focusKey = null;
  const root = h("section.dcard.card.planner", { "aria-label": L(`Suggested ${card.term.name} schedule`, `Horario sugerido de ${card.term.name}`) });
  const same = (a, b) => a.length === b.length && a.every((x, i) => x.crn === b[i].crn && x.linked === b[i].linked);

  const totalsText = () => {
    const live = data.rows.filter(r => !r.blocked);
    return `${classes(live.length)}, ${credits(data.credits.adding)}.` + (data.conflicts.length ? " " + L("There is a time clash.", "Hay un cruce de horario.") : "");
  };

  async function load(next, said, key) {
    root.classList.add("busy");
    try {
      data = await post("draft", { op: "set", items: next });
      items = data.items.map(i => ({ ...i })); open = null; focusKey = key || "totals";
      onItems && onItems(items);
      draw();
      if (said) announce(`${said} ${totalsText()}`);
    } catch (e) { toast(explain(e)); }
    finally { root.classList.remove("busy"); }
  }

  async function show(kind, crn, key) {
    if (open && open.kind === kind && open.crn === crn) { open = null; focusKey = key; return draw(); }
    root.classList.add("busy");
    try {
      const found = kind === "swap" ? await post("draft/sections", { term, items, crn }) : await post("draft/options", { term, items, replace: kind === "replace" ? crn : null });
      open = { kind, crn, found, query: "" }; focusKey = "editor";
      draw();
    } catch (e) { toast(explain(e)); }
    finally { root.classList.remove("busy"); }
  }

  const without = crn => items.filter(i => i.crn !== crn);
  const swapped = (crn, to) => items.map(i => (i.crn === crn ? to : i));

  /* ---- the three editors, each opening in place under the thing it edits ---- */
  function sectionEditor(row) {
    const f = open.found, current = f.sections.find(s => s.current);
    const pick = (s, label, onclick) => h("li", h("button.pick" + (s.current ? ".current" : ""), { type: "button", onclick, "aria-pressed": String(!!s.current), disabled: s.current && !label },
      h("span.pick-main", s.times[0]), h("span.pick-side",
        s.current ? h("span.badge.registered", L("Chosen", "Elegida")) : null,
        s.clash ? h("span.badge.cart", L("Clashes", "Se cruza")) : null,
        h("span.small.muted", seatsText(s)))));
    return h("div.crow-editor", { tabindex: "-1", "data-key": "editor" },
      h("div.editor-head", h("strong", L(`Sections of ${row.code}`, `Secciones de ${row.code}`)), btn(L("Close", "Cerrar"), () => { open = null; focusKey = `swap:${row.crn}`; draw(); }, { cls: ".plain", ico: "x" })),
      h("ul.picks", f.sections.map(s => pick(s, null, () => load(swapped(row.crn, { crn: s.crn, linked: null }), L(`${row.code} moved to another section.`, `${row.code} pasó a otra sección.`), `swap:${s.crn}`)))),
      current && current.linked.length ? h("div", h("p.editor-sub", L("Recitation or lab that goes with it", "Recitación o laboratorio que la acompaña")),
        h("ul.picks", current.linked.map(k => pick(k, true, () => load(swapped(row.crn, { crn: row.crn, linked: k.crn }), L(`${row.code} recitation or lab changed.`, `Cambió la recitación o laboratorio de ${row.code}.`), `swap:${row.crn}`))))) : null);
  }

  const courseList = (courses, label, choose) => h("ul.crows.inner", courses.map(c => classRow(c, { actions: [btn(label, () => choose(c), { cls: "", ico: "plus" })] })));

  function replaceEditor(row) {
    const f = open.found;
    return h("div.crow-editor", { tabindex: "-1", "data-key": "editor" },
      h("div.editor-head", h("strong", f.requirement ? L(`Other classes that count for: ${f.requirement}`, `Otras clases que cuentan para: ${f.requirement}`) : L(`Replace ${row.code}`, `Reemplazar ${row.code}`)),
        btn(L("Close", "Cerrar"), () => { open = null; focusKey = `replace:${row.crn}`; draw(); }, { cls: ".plain", ico: "x" })),
      f.courses.length ? courseList(f.courses, L("Use this instead", "Usar esta"), c => load(swapped(row.crn, c.item), L(`${row.code} replaced with ${c.code}.`, `${row.code} reemplazada por ${c.code}.`), `replace:${c.crn}`))
        : h("p.editor-empty", f.requirement ? L(`${row.code} is the only class offered in ${data.term.name} that meets this requirement and that you're ready for. You can still remove it, or add any other class below.`,
          `${row.code} es la única clase de ${data.term.name} que cumple este requisito y para la que tienes los prerrequisitos. Puedes quitarla o agregar otra clase abajo.`)
          : L(`${row.code} isn't tied to one of your open requirements, so there's no like-for-like swap. Use Add a class below to search for anything else.`,
            `${row.code} no está ligada a uno de tus requisitos pendientes. Usa Agregar una clase para buscar otra.`)));
  }

  function addEditor() {
    const f = open.found;
    const q = h("input.input", { type: "search", value: open.query, placeholder: L("A course code or a word, like MTH 254 or statistics", "Un código o una palabra, como MTH 254 o estadística"), "aria-label": L("Search for a class to add", "Buscar una clase para agregar"), maxlength: "60", autocomplete: "off" });
    const search = async e => {
      e.preventDefault();
      const query = q.value.trim();
      root.classList.add("busy");
      try { open = { kind: "add", crn: null, found: await post("draft/options", { term, items, query }), query }; focusKey = "search"; draw(); }
      catch (err) { toast(explain(err)); } finally { root.classList.remove("busy"); }
    };
    q.dataset.key = "search";
    return h("div.crow-editor.add", { tabindex: "-1", "data-key": "editor" },
      h("div.editor-head", h("strong", L("Add a class", "Agregar una clase")), btn(L("Close", "Cerrar"), () => { open = null; focusKey = "add"; draw(); }, { cls: ".plain", ico: "x" })),
      h("form.inline-form", { onsubmit: search, role: "search" }, q, h("button.btn.small", { type: "submit" }, L("Search", "Buscar"))),
      h("p.editor-sub", f.query ? L(`Classes matching “${f.query}”`, `Clases que coinciden con “${f.query}”`) : L("Classes your open requirements call for", "Clases que piden tus requisitos pendientes")),
      f.courses.length ? courseList(f.courses, L("Add", "Agregar"), c => load([...items, c.item], L(`${c.code} added to the list.`, `${c.code} agregada a la lista.`), `swap:${c.crn}`))
        : h("p.editor-empty", f.query ? L(`Nothing offered in ${data.term.name} matches that. Try a course code like “WR 227Z”.`, `Nada de ${data.term.name} coincide. Prueba un código como “WR 227Z”.`)
          : L("Your open requirements are all covered by this list. Search above for any other class.", "Esta lista ya cubre tus requisitos pendientes. Busca arriba cualquier otra clase.")));
  }

  /* The answers given before the plan was built, as chips. Tapping them reopens the questions and rebuilds. */
  function answers() {
    const chips = prefChips(data.prefs || {});
    const reopen = () => { open = open && open.kind === "prefs" ? null : { kind: "prefs" }; focusKey = "prefs"; draw(); };
    const rebuild = async prefs => { root.classList.add("busy"); try { data = await post("draft", { op: "build", prefs }); items = data.items.map(i => ({ ...i })); open = null; focusKey = "totals"; draw(); announce(L("Plan rebuilt.", "Plan rearmado.") + " " + totalsText()); } catch (e) { toast(explain(e)); } finally { root.classList.remove("busy"); } };
    return h("div.pref-row",
      h("button.pref-chips", { type: "button", "data-key": "prefs", "aria-expanded": String(!!(open && open.kind === "prefs")), onclick: reopen, title: L("Change your preferences and rebuild", "Cambiar tus preferencias y rearmar") },
        icon("sliders"), chips.length ? chips.map(c => h("span.pchip", c)) : h("span.pchip.none", L("No preferences set", "Sin preferencias")), h("span.pchip.edit", L("Change", "Cambiar"))),
      open && open.kind === "prefs" ? h("div.crow-editor", prefsForm(data.prefs || {}, { onBuild: rebuild, onCancel: reopen })) : null,
      (data.bends || []).map(b => h("p.crow-note", icon("alert"), h("span", b))));
  }

  /* ---- drawing ---- */
  function totals() {
    const c = data.credits, live = data.rows.filter(r => !r.blocked);
    const fill = h("i"), pct = Math.min(100, c.total / c.max * 100);
    fill.style.width = (shown ? shown.pct : 0) + "%"; requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = pct + "%"; }));
    const figure = h("strong.count-up");
    countUp(figure, shown ? shown.credits : 0, c.adding, v => `${classes(live.length)} · ${credits(v)}`);
    totals.pct = pct;
    const mark = h("b", { title: L("Full-time: 12 credits", "Tiempo completo: 12 créditos") }); mark.style.left = (c.min / c.max * 100) + "%";
    const state = c.over ? [L(`Over the ${c.max}-credit limit. Remove a class.`, `Sobre el límite de ${c.max} créditos. Quita una clase.`), "bad"]
      : c.full_time ? [L("Full-time (12 or more)", "Tiempo completo (12 o más)"), "good"]
        : [L(`Under full-time: ${num(c.min - c.total)} more to reach 12`, `Menos de tiempo completo: faltan ${num(c.min - c.total)} para 12`), "warn"];
    const pairs = [...new Set(data.conflicts.map(x => [x.a, x.b].sort().join(L(" and ", " y "))))];
    return h("div.planner-totals" + (c.over ? ".over" : ""), { tabindex: "-1", "data-key": "totals" },
      h("div.totals-line", figure,
        c.existing ? h("span.small.muted", L(` + ${num(c.existing)} already in your ${data.term.name} classes = ${num(c.total)}`, ` + ${num(c.existing)} que ya tienes en ${data.term.name} = ${num(c.total)}`)) : null),
      h("div.credits-bar", { role: "img", "aria-label": L(`${num(c.total)} of ${c.max} credits`, `${num(c.total)} de ${c.max} créditos`) }, fill, mark),
      h("div.totals-flags",
        h("span.flag." + state[1], icon(state[1] === "good" ? "check" : "alert"), state[0]),
        pairs.length ? h("span.flag.bad", icon("alert"), L("Time clash: ", "Cruce de horario: ") + pairs.join("; ")) : h("span.flag.good", icon("check"), L("No time clashes", "Sin cruces de horario"))));
  }

  function draw() {
    const was = root.isConnected && !reducedMotion() ? {
      rows: new Map([...root.querySelectorAll(".crows > .crow[data-code]")].map(el => [el.dataset.code, { rect: el.getBoundingClientRect(), crn: el.dataset.crn }])),
      blocks: new Map([...root.querySelectorAll(".wg-block[data-k]")].map(el => [el.dataset.k, el.getBoundingClientRect()])),
    } : null;
    clear(root);
    if (done) {
      root.classList.add("added");
      root.append(h("header.dcard-head", h("span.dcard-ico", icon("check")), h("strong", done.summary), sample()),
        h("div.dcard-body", statusRows(done.rows.map(r => ({ ...r, action: "planned", notes: [], clash: [] }))),
          h("p.small.muted", L("These are in your plan now, not registered. To change them from here on, open your classes.", "Ya están en tu plan, sin inscribir. Para cambiarlas desde ahora, abre tus clases."))),
        h("footer.dcard-foot", btn(L("Edit my classes", "Editar mis clases"), () => openPanel("schedule", { term }), { cls: "", ico: "calendar", key: "totals" }),
          done.can_undo ? btn(L("Undo", "Deshacer"), async () => { await undo(done.history_id); const back = done.rows.map(r => ({ crn: r.crn, linked: r.linked ? r.linked.crn : null })); done = null; root.classList.remove("added"); load(back, L("Undone.", "Deshecho.")); }, { ico: "refresh" }) : null));
      root.report();
      return refocus();
    }
    const live = data.rows.filter(r => !r.blocked);
    const rows = data.rows.map((r, n) => mark(r, n, classRow(r, {
      actions: [
        btn(L("Swap section", "Cambiar sección"), () => show("swap", r.crn, `swap:${r.crn}`), { ico: "refresh", key: `swap:${r.crn}`, disabled: r.sections < 2 && !r.linked_options }),
        btn(L("Replace", "Reemplazar"), () => show("replace", r.crn, `replace:${r.crn}`), { ico: "sliders", key: `replace:${r.crn}` }),
        btn(L("Remove", "Quitar"), () => load(without(r.crn), L(`${r.code} removed from the list.`, `${r.code} quitada de la lista.`)), { ico: "x", key: `remove:${r.crn}` }),
      ].map((b, i) => { b.setAttribute("aria-label", `${b.textContent} ${r.code}`); if (open && open.crn === r.crn && ["swap", "replace"][i] === open.kind) b.setAttribute("aria-expanded", "true"); return b; }),
      below: open && open.crn === r.crn ? (open.kind === "swap" ? sectionEditor(r) : replaceEditor(r)) : null,
    })));
    const go = btn(L("Review and add to my plan", "Revisar y agregar a mi plan"), () => review("registration", { type: "add_many", term, items: live.map(r => ({ crn: r.crn, linked: r.linked ? r.linked.crn : null })) },
      { onDone: res => { done = { ...res, rows: live }; post("draft", { op: "clear" }).catch(() => {}); focusKey = "totals"; draw();
        buddy.stamp(root, L("Added · sample", "Agregado · muestra")); } }), { cls: "", ico: "check", disabled: !live.length || data.credits.over });
    root.append(
      h("header.dcard-head", h("span.dcard-ico", icon("calendar")), h("strong", L(`Suggested ${data.term.name} schedule`, `Horario sugerido de ${data.term.name}`)), sample()),
      h("div.dcard-body",
        h("p.planner-lede", icon("info"), h("span", L("Not added yet. Change anything here first: every class has Swap section, Replace and Remove, and you can add classes at the bottom.",
          "Aún no se agrega nada. Cambia lo que quieras aquí: cada clase tiene Cambiar sección, Reemplazar y Quitar, y abajo puedes agregar clases."))),
        answers(),
        (data.rows.length || data.existing.length) ? h("div.planner-grid", week([...data.existing, ...data.rows]),
          data.rows.length ? h("p.grid-hint", L("Drag a class to another time to swap its section, or press it to see the choices.", "Arrastra una clase a otra hora para cambiar su sección, o tócala para ver las opciones.")) : null) : null,
        data.existing.length ? h("p.small.muted", L(`Already in your ${data.term.name} classes: `, `Ya en tus clases de ${data.term.name}: `) + data.existing.map(r => r.code).join(", ") + ".") : null,
        rows.length ? h("ul.crows", rows) : h("p.editor-empty", L("No classes in this list yet. Add one below.", "Aún no hay clases en esta lista. Agrega una abajo.")),
        open && open.kind === "add" ? addEditor() : h("button.add-class", { type: "button", "data-key": "add", onclick: () => show("add", null, "add"), disabled: data.rows.length >= 8 }, icon("plus"), h("span", L("Add a class", "Agregar una clase"))),
        totals()),
      h("footer.dcard-foot", go,
        data.can_undo ? btn(L("Undo last change", "Deshacer el último cambio"), async () => { root.classList.add("busy"); try { data = await post("draft", { op: "undo" }); items = data.items.map(i => ({ ...i })); open = null; focusKey = "totals"; draw(); announce(L("Undone.", "Deshecho.") + " " + totalsText()); } catch (e) { toast(explain(e)); } finally { root.classList.remove("busy"); } }, { ico: "undo", key: "undo" }) : null,
        h("span.small.muted.foot-note", L("Nothing changes until you confirm on the next step.", "Nada cambia hasta que confirmes en el paso siguiente."))));
    armGrid();
    if (was) {
      root.querySelectorAll(".crows > .crow[data-code]").forEach(el => {
        const old = was.rows.get(el.dataset.code);
        if (!old || old.crn !== el.dataset.crn) el.classList.add("slid");          /* new, or a different section: it slides in */
        else glide(el, old.rect, 420);
      });
      root.querySelectorAll(".wg-block[data-k]").forEach(el => {
        const old = was.blocks.get(el.dataset.k);
        if (old) glide(el, old);
        else el.animate([{ opacity: 0, transform: "scale(.6)" }, { opacity: 1, transform: "none" }], { duration: 420, easing: SPRING });
      });
    }
    shown = { credits: data.credits.adding, pct: totals.pct };
    if (data.conflicts.length && root.isConnected) buddy.squint();
    root.report();
    refocus();
  }

  /* The week is something you can move: press a class to see its other sections, or drag it to another time and the
     section that meets then is swapped in. Everything it does, the Swap section button does too. */
  function armGrid() {
    const grid = root.querySelector(".planner-grid .weekgrid");
    if (!grid) return;
    const cols = [...grid.querySelectorAll(".wg-col")], from = +grid.dataset.from, to = +grid.dataset.to;
    const mine = new Set(data.rows.filter(r => !r.blocked).map(r => String(r.crn)));
    grid.querySelectorAll(".wg-block").forEach(block => {
      if (!mine.has(block.dataset.crn)) return;
      const crn = +block.dataset.crn;
      block.classList.add("mine");
      let start = null, moved = false;
      block.addEventListener("pointerdown", e => { if (e.button) return; start = { x: e.clientX, y: e.clientY }; moved = false; block.setPointerCapture(e.pointerId); });
      block.addEventListener("pointermove", e => {
        if (!start) return;
        const dx = e.clientX - start.x, dy = e.clientY - start.y;
        if (!moved && Math.hypot(dx, dy) < 7) return;
        moved = true; block.classList.add("lifted");
        block.style.transform = `translate(${dx}px, ${dy}px) rotate(-2deg)`;
        cols.forEach(c => { const r = c.getBoundingClientRect(); c.classList.toggle("aim", e.clientX >= r.left && e.clientX <= r.right); });
      });
      const end = async e => {
        if (!start) return;
        start = null; cols.forEach(c => c.classList.remove("aim"));
        if (!moved) return show("swap", crn, `swap:${crn}`);
        block.classList.remove("lifted");
        const day = cols.findIndex(c => { const r = c.getBoundingClientRect(); return e.clientX >= r.left && e.clientX <= r.right; });
        const box = cols[0].getBoundingClientRect(), minute = from + (block.getBoundingClientRect().top - box.top) / box.height * (to - from);      /* where the top of the block was let go */
        const back = () => { block.style.transition = "transform .35s " + SPRING; block.style.transform = ""; setTimeout(() => { block.style.transition = ""; }, 380); };
        if (day < 0) return back();
        const row = data.rows.find(r => r.crn === crn);
        let found;
        try { found = await post("draft/sections", { term, items, crn }); } catch (err) { back(); return toast(explain(err)); }
        const current = found.sections.find(s => s.current), linkedPart = block.dataset.part === "linked";
        const pool = (linkedPart ? (current ? current.linked : []) : found.sections).filter(s => !s.current && s.start != null && s.days.includes(DAYS[day]));
        const best = pool.sort((a, b) => Math.abs(a.start - minute) - Math.abs(b.start - minute))[0];
        if (!best || Math.abs(best.start - minute) > 110) {
          back();
          toast(L(`No ${row.code} section meets then. Here are the ones that do.`, `Ninguna sección de ${row.code} se reúne a esa hora. Estas son las que hay.`));
          open = { kind: "swap", crn, found, query: "" }; focusKey = "editor";
          return draw();
        }
        load(swapped(crn, linkedPart ? { crn, linked: best.crn } : { crn: best.crn, linked: null }), L(`${row.code} moved to ${best.times[0]}.`, `${row.code} pasó a ${best.times[0]}.`), `swap:${linkedPart ? crn : best.crn}`);
      };
      block.addEventListener("pointerup", end);
      block.addEventListener("pointercancel", () => { start = null; block.classList.remove("lifted"); block.style.transform = ""; cols.forEach(c => c.classList.remove("aim")); });
    });
  }

  /* A redraw rebuilds the card, so put the keyboard back where the student was working. */
  function refocus() {
    if (!focusKey) return;
    const el = root.querySelector(`[data-key="${focusKey}"]`) || root.querySelector('[data-key="totals"]');
    focusKey = null;
    if (el) el.focus({ preventScroll: true });
  }

  /* The row a chat follow-up or the last edit changed stands out, so the difference is easy to find. */
  function mark(r, n, li) {
    li.dataset.code = r.code;
    li.dataset.tone = String((data.existing.length + n) % 5);          /* the same colour as its blocks on the week */
    if (data.changed !== r.crn) return li;
    li.classList.add("changed");
    li.querySelector(".crow-name").prepend(h("span.badge.in", L("Changed", "Cambiada")));
    if (shown === null) setTimeout(() => { if (li.isConnected) buddy.tap(li); }, 700);       /* it arrived changed: the mascot points it out */
    return li;
  }
  /* A newer card has taken over: this one can no longer be edited or confirmed. */
  root.retire = () => {
    if (done) return;
    root.classList.add("older"); root.inert = true;
    if (live === root) tell(null);
    clear(root).append(h("header.dcard-head", h("span.dcard-ico", icon("clock")), h("strong", L("Older version of this plan", "Versión anterior de este plan")), sample()),
      h("div.dcard-body", h("p.small.muted", L(`${classes(data.rows.length)}, ${credits(data.credits.adding)}. The current version is further down, and that is the one to review.`,
        `${classes(data.rows.length)}, ${credits(data.credits.adding)}. La versión actual está más abajo, y esa es la que se revisa.`))));
  };
  /* What the shelf on the question bar says about this card (nothing, once it is added or replaced). */
  root.report = () => { if (live === root) tell(done || root.classList.contains("older") ? null : { el: root, term: data.term.name, n: data.rows.filter(r => !r.blocked).length, credits: data.credits.adding, clash: data.conflicts.length }); };
  draw();
  return root;
}

/* ---- "what am I taking": the student's classes, one to a row ------------------------------------------ */
export function classesCard(card) {
  const reg = card.groups[0];
  return h("section.dcard.card.planner", h("header.dcard-head", h("span.dcard-ico", icon("calendar")), h("strong", L("Your classes", "Tus clases")), sample()),
    h("div.dcard-body", card.groups.map(g => h("div.planner-group", h("p.hub-h", g.term.name),
      g.rows.length ? statusRows(g.rows) : h("p.editor-empty", L("Nothing here yet.", "Aún no hay nada aquí.")),
      g.rows.length > 1 && g === reg ? h("details.planner-week", h("summary", L("Week view", "Vista de la semana")), week(g.rows)) : null))),
    h("footer.dcard-foot", btn(L("Edit my classes", "Editar mis clases"), () => openPanel("schedule", { term: reg.term.code }), { cls: "", ico: "calendar" }),
      btn(L("Find a class", "Buscar una clase"), () => openPanel("finder"), { ico: "plus" })));
}

/* ---- sections that fit what they asked for, each with its own Add button -------------------------------- */
export function optionsCard(card) {
  const term = card.term.code;
  const root = h("section.dcard.card.planner");
  root.append(h("header.dcard-head", h("span.dcard-ico", icon("list")), h("strong", card.closest ? L("Closest sections", "Secciones más cercanas") : L("Sections that fit", "Secciones que encajan")), sample()),
    h("div.dcard-body", card.drafting ? h("p.planner-lede", icon("info"), h("span", card.swap ? L(`Pick one and it replaces the ${card.code} section in your plan. You get the whole plan back to check.`, `Elige una y reemplaza la sección de ${card.code} en tu plan. Verás el plan completo de nuevo.`)
      : L(`Pick one and it joins the plan you're working on. You get the whole plan back to check.`, `Elige una y se suma al plan que estás armando. Verás el plan completo de nuevo.`))) : null,
      h("ul.crows", card.rows.map(r => {
      const now = card.swap === r.crn;
      /* While a plan is being worked on, a section goes into that plan (replacing the same course), never beside it. */
      const put = async () => { root.classList.add("busy"); try { root.replaceWith(showDraft(await post("draft", { op: "put", ...r.item }))); announce(L(`${r.code} updated. Your whole plan is shown again.`, `${r.code} actualizada. Se muestra tu plan completo.`)); } catch (e) { toast(explain(e)); root.classList.remove("busy"); } };
      const add = card.drafting ? btn(now ? L("In your plan now", "En tu plan ahora") : card.swap ? L("Swap in this one", "Cambiar a esta") : L("Add to this plan", "Agregar a este plan"), put, { cls: "", ico: now ? "check" : card.swap ? "swap" : "plus", disabled: now })
        : btn(L("Add to my plan", "Agregar a mi plan"), () => review("registration", { type: "add", term, ...r.item }, { onDone: () => { add.disabled = true; add.lastChild.textContent = L("In your plan", "En tu plan"); } }), { cls: "", ico: "plus" });
      add.setAttribute("aria-label", `${add.textContent}: ${r.times[0]}`);
      return classRow({ ...r, notes: [seatsText(r)].filter(() => r.seats_open <= 5) }, { actions: [add] });
    }))),
    h("footer.dcard-foot", btn(L("See my classes", "Ver mis clases"), () => openPanel("schedule", { term }), { ico: "calendar" })));
  return root;
}
