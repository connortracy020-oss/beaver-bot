/* The pages beside the chat: Topics, Deadlines, Offices, Saved and About. */
import { h, add, clear, icon, shortDate, parseDate, plural } from "./dom.js";
import { t, lang } from "./i18n.js";
import * as api from "./api.js";
import * as saved from "./saved.js";
import { toast } from "./ui.js";
import { createMascot } from "./mascot.js";
import { renderStored } from "./chat.js";

let actions = {};
export function initPages(hooks) { actions = hooks; }

const header = (kicker, title, lede) => h("header.page-head", h("p.kicker", kicker), h("h1.title", title), lede ? h("p.lede", lede) : null);
function skeleton(n = 4) { return h("div.skeleton", { "aria-hidden": "true" }, Array.from({ length: n }, () => h("div.skel"))); }
function problem(view, retry) {
  const m = createMascot("mini"); m.setMood("confused");
  return h("div.empty", m.el, h("p.h2", t("error.title")), h("p.muted", t("error.library")),
    h("button.btn.quiet", { type: "button", onclick: retry }, icon("refresh"), t("retry")));
}
const askBtn = q => h("button.chip.q-chip", { type: "button", onclick: () => actions.ask(q) }, q);

/* ---- Topics ----------------------------------------------------------------------------------- */
export async function topicsPage(root) {
  const list = h("div.topic-list");
  root.append(h("div.page", header(t("topics.kicker"), t("topics.title"), t("topics.lede")), list));
  list.append(skeleton(6));
  let data;
  try { data = await api.getJSON("/api/topics"); } catch (e) { clear(list).append(problem(root, () => actions.refresh())); return; }
  clear(list);
  const wanted = new URLSearchParams(location.search).get("t") || location.hash.slice(1);
  data.topics.forEach((topic, i) => {
    const body = h("div.topic-body", { hidden: true, id: "topic-" + topic.id });
    const head = h("button.topic-head", { type: "button", "aria-expanded": "false", "aria-controls": body.id, onclick: () => toggle() },
      h("span.topic-ico", icon(topic.icon)),
      h("span.topic-names", h("span.h2", topic.name[lang()]), h("span.muted.small", topic.covers[lang()])),
      h("span.topic-count.num", plural(topic.count, t("unit.page"), t("unit.pages"))), icon("down", "caret"));
    const fill = () => {
      if (body.childNodes.length) return;
      body.append(
        h("div.topic-col", h("div.label", t("topics.ask")), h("div.chips.stack", topic.questions[lang()].map(askBtn))),
        h("div.topic-col", h("div.label", t("topics.pages")), h("ul.linklist", topic.pages.map(p => h("li", h("a", { href: p.url, target: "_blank", rel: "noopener" },
          h("span", p.title), icon("external")), h("small", (p.office || "") + " · " + t("checked.short", { date: shortDate(p.checked, lang()) })))))),
        h("div.topic-col", h("div.label", t("topics.offices")), h("ul.linklist", topic.contacts.map(c => h("li", h("a", { href: c.url, target: "_blank", rel: "noopener" }, h("span", c.name), icon("external")))))));
    };
    const toggle = (force) => {
      const open = force ?? body.hidden;
      if (open) fill();
      body.hidden = !open; head.setAttribute("aria-expanded", String(open)); card.classList.toggle("open", open);
    };
    const card = h("section.topic.card", { style: { animationDelay: (i * 35) + "ms" } }, head, body);
    list.append(card);
    if (wanted === topic.id) { toggle(true); requestAnimationFrame(() => card.scrollIntoView({ block: "start" })); }
  });
}

/* ---- Deadlines -------------------------------------------------------------------------------- */
const KIND_ICON = { add_drop: "swap", withdraw: "undo", grading: "form", registration: "list", start: "bolt", finals: "book", end: "check", grades: "cap", break: "sun", other: "calendar" };
export async function deadlinesPage(root) {
  const box = h("div.deadlines");
  const page = h("div.page.narrow", header(t("dl.kicker"), t("dl.title"), t("dl.lede")), box);
  root.append(page);
  box.append(skeleton(5));
  let data;
  try { data = await api.getJSON("/api/deadlines"); } catch (e) { clear(box).append(problem(root, () => actions.refresh())); return; }
  const state = { kind: "all", term: "all", sessions: false, past: false };
  const kinds = [["all", t("dl.all")], ["add_drop", t("dl.add_drop")], ["withdraw", t("dl.withdraw")], ["registration", t("dl.registration")],
                 ["start", t("dl.terms")], ["finals", t("dl.finals")], ["break", t("dl.breaks")]];
  const chipRow = h("div.chips.filters", { role: "group", "aria-label": t("dl.filter") });
  const termSel = h("select.input.term-select", { "aria-label": t("dl.term"), onchange: e => { state.term = e.target.value; draw(); } },
    h("option", { value: "all" }, t("dl.allterms")), data.terms.map(term => h("option", { value: term }, term)));
  const sessionsToggle = h("button.chip", { type: "button", "aria-pressed": "false", onclick: e => { state.sessions = !state.sessions; e.currentTarget.setAttribute("aria-pressed", String(state.sessions)); draw(); } }, t("dl.sessions"));
  const listEl = h("div.dl-list", { "aria-live": "polite" });
  kinds.forEach(([key, label]) => chipRow.append(h("button.chip", { type: "button", "aria-pressed": String(key === "all"), onclick: e => {
    state.kind = key; [...chipRow.children].forEach(c => c.setAttribute("aria-pressed", "false")); e.currentTarget.setAttribute("aria-pressed", "true"); draw();
  } }, label)));
  const groupOf = { end: "start", grades: "finals", grading: "withdraw" };
  function draw() {
    clear(listEl);
    const rows = data.items.filter(i => (state.kind === "all" || i.kind === state.kind || groupOf[i.kind] === state.kind)
      && (state.term === "all" || i.term === state.term || (!i.term && state.kind === "break"))
      && (state.sessions || !i.session) && (state.past || !i.past));
    if (!rows.length) {
      const m = createMascot("mini"); m.setMood("confused");
      listEl.append(h("div.empty", m.el, h("p.h2", t("dl.none")), h("p.muted", t("dl.none.hint"))));
      return;
    }
    let month = null, group = null, shown = 0;
    for (const item of rows) {
      const d = parseDate(item.date);
      const key = d.getFullYear() + "-" + d.getMonth();
      if (key !== month) {
        month = key;
        group = h("ol.dl-month");
        listEl.append(h("section.dl-group", h("h2.dl-month-name", d.toLocaleDateString(lang() === "es" ? "es" : "en-US", { month: "long", year: "numeric" })), group));
      }
      const soon = !item.past && item.days >= 0 && item.days <= 7;
      const when = item.past ? t("dl.past") : item.days < 0 ? t("dl.now") : item.days === 0 ? t("dl.today") : item.days === 1 ? t("dl.tomorrow") : t("dl.in", { n: item.days });
      group.append(h("li.dl-row" + (item.past ? ".past" : "") + (soon ? ".soon" : ""), { style: { animationDelay: Math.min(shown++, 14) * 28 + "ms" } },
        h("div.dl-date", h("span.dl-day.num", String(d.getDate())), h("span.dl-wd", d.toLocaleDateString(lang() === "es" ? "es" : "en-US", { weekday: "short" }))),
        h("div.dl-what", h("span.dl-ico", icon(KIND_ICON[item.kind] || "calendar")),
          h("div", h("p.dl-name", item.name), h("p.small.muted", [item.term, item.end ? t("dl.through", { date: shortDate(item.end, lang()) }) : null].filter(Boolean).join(" · ")))),
        h("span.pill" + (soon ? ".warn" : ".line"), when)));
    }
  }
  clear(box).append(
    h("div.dl-controls", chipRow, h("div.dl-controls-2", termSel, sessionsToggle,
      h("button.chip", { type: "button", "aria-pressed": "false", onclick: e => { state.past = !state.past; e.currentTarget.setAttribute("aria-pressed", String(state.past)); draw(); } }, t("dl.showpast")))),
    listEl,
    h("aside.source-note.card", icon("calendar"),
      h("div", h("p", t("dl.source"), " ", h("a", { href: data.source.url, target: "_blank", rel: "noopener" }, t("dl.source.link")), "."),
        h("p.small.muted", t("checked", { date: shortDate(data.checked, lang()) }) + ". " + t("dl.confirm")))));
  draw();
}

/* ---- Offices ---------------------------------------------------------------------------------- */
export async function officesPage(root) {
  const grid = h("div.office-grid");
  const search = h("input.input", { type: "search", placeholder: t("of.search"), "aria-label": t("of.search"), oninput: () => draw() });
  root.append(h("div.page", header(t("of.kicker"), t("of.title"), t("of.lede")), h("div.search.of-search", icon("search"), search), grid));
  grid.append(skeleton(6));
  let data;
  try { data = await api.getJSON("/api/offices"); } catch (e) { clear(grid).append(problem(root, () => actions.refresh())); return; }
  function draw() {
    const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
    const rows = data.offices.filter(o => words.every(w => (o.name + " " + o.topic_name[lang()] + " " + (o.note || "")).toLowerCase().includes(w)));
    clear(grid);
    if (!rows.length) { grid.append(h("div.empty", h("p.h2", t("of.none")), h("p.muted", t("of.none.hint")))); return; }
    rows.forEach((o, i) => grid.append(h("article.office.card", { style: { animationDelay: Math.min(i, 16) * 26 + "ms" } },
      h("div.office-head", h("span.topic-ico", icon(o.icon)), h("div", h("h2.h3", o.name), h("p.small.muted", o.topic_name[lang()]))),
      o.note && !/24\/7/.test(o.note) ? h("p.small.muted", o.note) : null,
      h("div.office-links",
        o.phone ? h("a.btn.small.quiet", { href: "tel:+1" + o.phone.replace(/\D/g, "") }, icon("call"), o.phone + (o.note && /24\/7/.test(o.note) ? " · 24/7" : "")) : null,
        h("a.btn.small.quiet", { href: o.url, target: "_blank", rel: "noopener" }, t("office.open"), icon("external")),
        h("a.btn.small.plain", { href: "/topics?t=" + o.topic, "data-link": "" }, t("of.topic"))))));
  }
  draw();
}

/* ---- Saved ------------------------------------------------------------------------------------ */
export function savedPage(root) {
  const list = h("div.saved-list");
  const clearBtn = h("button.btn.small.quiet", { type: "button", onclick: () => { const backup = saved.all(); saved.clearAll(); draw(); toast(t("saved.cleared"), { action: t("undo"), onAction: () => { backup.reverse().forEach(saved.add); draw(); } }); } }, icon("trash"), t("saved.clear"));
  root.append(h("div.page.narrow", header(t("saved.kicker"), t("saved.title"), t("saved.lede")), h("div.saved-tools", clearBtn), list));
  function draw() {
    const items = saved.all();
    clear(list); clearBtn.hidden = !items.length;
    if (!items.length) {
      const m = createMascot("mini");
      list.append(h("div.empty", m.el, h("p.h2", t("saved.none")), h("p.muted", t("saved.none.hint")),
        h("a.btn", { href: "/", "data-link": "" }, t("saved.ask"))));
      return;
    }
    items.forEach((item, i) => {
      const body = h("div.saved-body", { hidden: true });
      const card = h("article.saved.card", { style: { animationDelay: i * 40 + "ms" } },
        h("button.saved-head", { type: "button", "aria-expanded": "false", onclick: e => {
          const open = body.hidden;
          if (open && !body.childNodes.length) {
            renderStored(item, body);
            if (item.pages && item.pages.length) body.append(h("ul.linklist.saved-sources", item.pages.map(p => h("li", h("a", { href: p.url, target: "_blank", rel: "noopener" }, h("span", p.p + ". " + p.title), icon("external")),
              h("small", t("checked.short", { date: shortDate(p.checked, item.lang) }))))));
          }
          body.hidden = !open; e.currentTarget.setAttribute("aria-expanded", String(open)); card.classList.toggle("open", open);
        } }, h("span.h3", item.question), h("span.small.muted", t("saved.on", { date: shortDate(item.savedAt, lang()) })), icon("down", "caret")),
        body,
        h("div.saved-foot", h("button.btn.small.plain", { type: "button", onclick: () => actions.ask(item.question) }, icon("refresh"), t("saved.again")),
          h("button.btn.small.plain", { type: "button", onclick: () => { saved.remove(item.id); draw(); toast(t("save.removed"), { action: t("undo"), onAction: () => { saved.add(item); draw(); } }); } }, icon("trash"), t("saved.remove"))));
      list.append(card);
    });
  }
  draw();
}

/* ---- About ------------------------------------------------------------------------------------ */
export async function aboutPage(root) {
  let cfg = null;
  try { cfg = await api.config(); } catch (e) { cfg = null; }
  const lib = cfg && cfg.library;
  const fact = (n, label) => h("div.fact", h("span.fact-n.num", n), h("span.small.muted", label));
  const block = (iconName, title, ...body) => h("section.about-block.card", h("span.topic-ico", icon(iconName)), h("div", h("h2.h2", title), body));
  const m = createMascot("mini");
  root.append(h("div.page.narrow", h("header.page-head.about-head", m.el, h("div", h("p.kicker", t("about.kicker")), h("h1.title", t("about.title")), h("p.lede", t("about.lede")))),
    lib ? h("div.facts", fact(lib.pages.toLocaleString(), t("about.fact.pages")), fact(lib.pdfs.toLocaleString(), t("about.fact.pdfs")), fact(String(lib.sites), t("about.fact.sites")),
      fact(shortDate(lib.checked, lang()), t("about.fact.checked"))) : null,
    block("shield", t("about.not.title"), h("p", t("about.not.body"))),
    block("book", t("about.how.title"), h("p", t("about.how.body")), h("ul.ticks", t("about.how.points").map(p => h("li", icon("check"), h("span", p))))),
    block("lock", t("about.privacy.title"), h("p", t("about.privacy.body")), h("ul.ticks", t("about.privacy.points").map(p => h("li", icon("check"), h("span", p))))),
    block("bolt", t("about.mode.title"), h("p", cfg && cfg.offline ? t("about.mode.offline") : t("about.mode.model", { name: cfg ? cfg.provider : "" }))),
    block("user", t("about.demo.title"), h("p", t("about.demo.body"))),
    block("access", t("about.a11y.title"), h("p", t("about.a11y.body")), h("div.chips", { style: { marginTop: "12px" } },
      h("button.chip", { type: "button", onclick: () => actions.settings() }, icon("sliders"), t("set.title")))),
    block("heart", t("about.crisis.title"), h("p", t("about.crisis.body")),
      h("div.chips", { style: { marginTop: "12px" } }, h("a.chip", { href: "tel:911" }, icon("call"), "911"), h("a.chip", { href: "tel:+15417372131" }, icon("call"), "CAPS 541-737-2131"),
        h("a.chip", { href: "https://counseling.oregonstate.edu/crisis-resources", target: "_blank", rel: "noopener" }, t("crisis.page"), icon("external"))))));
}

export function notFoundPage(root) {
  const m = createMascot("mini"); m.setMood("confused");
  root.append(h("div.page.narrow", h("div.empty", m.el, h("h1.title", t("nf.title")), h("p.muted", t("nf.body")), h("a.btn", { href: "/", "data-link": "" }, t("nf.home")))));
}
