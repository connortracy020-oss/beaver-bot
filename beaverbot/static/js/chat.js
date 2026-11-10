/* The conversation: welcome screen, question bar, streamed answers, sources and the actions under an answer. */
import { $, h, add, clear, icon, reducedMotion, replay, shortDate, sleep } from "./dom.js";
import { t, lang } from "./i18n.js";
import * as api from "./api.js";
import { createMascot, setGaze, sparkle } from "./mascot.js";
import { buddy } from "./buddy.js";
import { AnswerStream, plainText } from "./render.js";
import { toast, sheet, announce, copyText } from "./ui.js";
import { prefs, speak, stopSpeaking, speechSupported } from "./settings.js";
import * as saved from "./saved.js";

const feed = $("#feed"), thread = $("#thread"), input = $("#q"), form = $("#ask");
const PRIVATE_RE = /[\w.+-]+@[\w-]+\.[\w.-]+|\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b|\b9\d{8}\b|\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b|\bpassword is\b|\bcontrase[nñ]a es\b/i;
const STATUS_MS = 430;

let cfg = null, hooks = {}, welcome = null, active = null, lastQuestion = null, turnCount = 0, lead = null;
/* The last few messages, sent along with each new one so replies can follow the conversation. They live in this
   tab's memory only: gone on New chat, on reload, and never saved by the server. */
let history = [];
const remember = (role, text) => { if (text) { history.push({ role, text: text.slice(0, 700) }); history = history.slice(-8); } };
/* The mascot that reacts right now is the one living in the question bar (js/buddy.js). The small logo beside each
   reply shows the same mood, and passes it on while its reply is the newest one. */
const faceOf = () => buddy.actor;
function linked(avatar) {
  const set = avatar.setMood, react = avatar.react;
  avatar.setMood = (name, opts) => { set(name, opts); if (lead === avatar) buddy.mood(name, opts); return avatar; };
  avatar.react = (name, ms) => { react(name, ms); if (lead === avatar) buddy.react(name, ms); return avatar; };
  return avatar;
}
/* Health, counselling and disability topics get the same steady treatment as a crisis answer: no playing around. */
const hushed = m => m.kind === "crisis" || m.tool === "wellness" || (m.card && m.card.system === "wellness")
  || /health|counsel|wellness|disab|safety|crisis/i.test((m.category && (m.category.id || m.category.name)) || "");

export function initChat(config, appHooks) {
  cfg = config; hooks = appHooks || {};
  buildDock();
  buddy.mount(form);
  renderWelcome();
  addEventListener("resize", fitLastTurn);
  scrolling();
  const shared = new URLSearchParams(location.search).get("q");
  if (shared) {            /* a shared link re-asks the question; the link is then cleaned out of the address bar */
    history.replaceState(null, "", location.pathname);
    setTimeout(() => ask(shared.slice(0, 400)), 350);
  }
}

/* ---- welcome ---------------------------------------------------------------------------------- */
/* The headline is the hero: one large greeting, the question in italics, then things to ask. The mascot isn't
   drawn here any more; it is in the question bar, where it stays for the whole conversation. */
export function renderWelcome() {
  if (welcome) welcome.remove();
  const demo = hooks.demoStudent && hooks.demoStudent();
  const hello = demo ? t("welcome.demo", { name: demo.first_name }) : t("welcome.title");
  const cut = hello.search(/\.\s/);                         /* "Hi Juniper." then "What do you need?" */
  const chips = h("div.chips.popular", { role: "group", "aria-label": demo ? t("welcome.demo.try") : t("welcome.popular") });
  const questions = demo ? hooks.demoPrompts() : cfg.popular[lang()];
  questions.forEach((q, i) => { const c = questionChip(q); c.style.animationDelay = (260 + i * 60) + "ms"; chips.append(c); });
  welcome = h("section.welcome", { id: "welcome" },
    h("p.kicker", h("span.kicker-rule"), demo ? t("welcome.demo.kicker") : t("tagline")),
    h("h1.display.hello", cut > 0 ? [h("span.hello-a", hello.slice(0, cut + 1)), " ", h("em.hello-b", hello.slice(cut + 2))] : hello),
    demo ? h("p.lede", demo.situation) : null,
    h("p.label.popular-label", demo ? t("welcome.demo.try") : t("welcome.popular")), chips);
  thread.prepend(welcome);
  welcome.hidden = turnCount > 0;
  buddy.setEmpty(turnCount === 0);
}

function questionChip(q, label) {
  return h("button.chip.q-chip", { type: "button", onclick: () => ask(q) }, label || q);
}

/* ---- question bar ----------------------------------------------------------------------------- */
let items = [], activeItem = -1, placeholderTimer = null, placeholderIndex = 0;
function buildDock() {
  const list = $("#suggest"), go = $("#go"), topicsBtn = $("#topicsBtn"), hint = $("#privateHint");
  const label = () => {
    input.setAttribute("aria-label", t("ask.label"));
    input.placeholder = turnCount ? t("ask.placeholder.chat") : t("ask.placeholder");
    clear(go).append(h("span.go-text", t("ask.go")), icon("send"));
    go.setAttribute("aria-label", t("ask.go"));
    clear(topicsBtn).append(icon("grid"), h("span", t("nav.topics")));
    clear($("#fine")).append(h("span.fine-long", t("fine.project") + " " + t("fine.private")), h("span.fine-short", t("fine.short")), " ",
      h("a", { href: "/about", "data-link": "" }, t("fine.more")));
    hint.textContent = t("ask.private");
  };
  label(); buildDock.relabel = label;

  const hide = () => { list.hidden = true; activeItem = -1; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); };
  const paint = () => [...list.children].forEach((li, i) => { li.classList.toggle("on", i === activeItem); li.setAttribute("aria-selected", String(i === activeItem)); });
  input.addEventListener("input", () => {
    const face = faceOf();
    if (face && face.mood !== "calm") { if (face.mood !== "listening" && input.value) face.setMood("listening"); face.react("ping", 320); }
    if (!input.value && face && face.mood === "listening") face.setMood("idle");
    setGaze(input.value ? input : null);
    hint.hidden = !PRIVATE_RE.test(input.value);
    const text = input.value.trim().toLowerCase();
    items = text.length >= 2 ? cfg.questions[lang()].filter(q => q.toLowerCase().includes(text)).slice(0, 5) : [];
    activeItem = -1;
    list.replaceChildren(...items.map((q, i) => h("li", { role: "option", id: "sug-" + i, "aria-selected": "false",
      onpointerdown: e => { e.preventDefault(); hide(); ask(q); } }, icon("search"), h("span", q))));
    list.hidden = !items.length;
    input.setAttribute("aria-expanded", String(!!items.length));
  });
  input.addEventListener("keydown", e => {
    if (e.key === "Escape") return hide();
    if (list.hidden || !items.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      activeItem = e.key === "ArrowDown" ? (activeItem + 1) % items.length : (activeItem <= 0 ? items.length - 1 : activeItem - 1);
      paint(); input.setAttribute("aria-activedescendant", "sug-" + activeItem);
    }
  });
  input.addEventListener("blur", () => { hide(); setGaze(null); const f = faceOf(); if (f && f.mood === "listening") f.setMood("idle"); });
  form.addEventListener("submit", e => {
    e.preventDefault();
    const q = activeItem >= 0 ? items[activeItem] : input.value.trim();
    hide();
    if (q) ask(q); else { input.focus(); replay($(".ask-row"), "nudge", 400); }
  });
  addEventListener("keydown", e => {
    if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) && !document.querySelector("dialog[open]") && !$("#view-ask").hidden) {
      e.preventDefault(); input.focus();
    }
  });
  if (!reducedMotion()) placeholderTimer = setInterval(() => {
    if (input.value || document.activeElement === input || turnCount) return;
    const prompts = [t("ask.placeholder"), ...cfg.popular[lang()].slice(0, 3)];
    input.placeholder = prompts[++placeholderIndex % prompts.length];
  }, 3200);

  /* the small Topics menu */
  const menu = $("#topicsMenu");
  let loaded = false;
  const show = on => {
    menu.hidden = !on; topicsBtn.setAttribute("aria-expanded", String(on));
    if (on) { hide(); if (!loaded) { loaded = true; fillTopics(menu, show); } }
  };
  topicsBtn.addEventListener("click", () => show(menu.hidden));
  addEventListener("pointerdown", e => { if (!menu.hidden && !menu.contains(e.target) && !topicsBtn.contains(e.target)) show(false); });
  addEventListener("keydown", e => { if (e.key === "Escape" && !menu.hidden) { show(false); topicsBtn.focus(); } });
  buildDock.closeMenu = () => show(false);
  buildDock.reloadTopics = () => { loaded = false; clear(menu); };
}

async function fillTopics(menu, show) {
  clear(menu).append(h("p.menu-note", t("loading")));
  let data;
  try { data = await api.getJSON("/api/topics"); } catch (e) { clear(menu).append(h("p.menu-note", t("error.library"))); return; }
  clear(menu);
  for (const topic of data.topics) {
    const body = h("div.rowbody", { hidden: true });
    const btn = h("button.rowbtn", { type: "button", "aria-expanded": "false", onclick: () => {
      const open = body.hidden;
      menu.querySelectorAll(".rowbody").forEach(b => { b.hidden = true; });
      menu.querySelectorAll(".rowbtn").forEach(b => b.setAttribute("aria-expanded", "false"));
      body.hidden = !open; btn.setAttribute("aria-expanded", String(open));
    } }, icon(topic.icon), h("span", topic.name[lang()]));
    topic.questions[lang()].forEach(q => body.append(h("button.rowq", { type: "button", onclick: () => { show(false); ask(q); } }, q)));
    topic.contacts.slice(0, 2).forEach(c => body.append(h("a.office", { href: c.url, target: "_blank", rel: "noopener" }, c.name, icon("external"))));
    menu.append(h("div", btn, body));
  }
  menu.append(h("a.menu-all", { href: "/topics", "data-link": "", onclick: () => show(false) }, t("topics.all"), icon("chevron")));
}

/* ---- scrolling the conversation ----------------------------------------------------------------- */
/* The conversation is the only thing on the page that scrolls, so the wheel, the trackpad and the keyboard move
   it wherever the pointer or the focus happens to be: over the header, over the question bar, or on nothing at all.
   Anything that scrolls by itself (a panel, a dialog, a menu, a long card) keeps its own scrolling. */
function scrolling() {
  const own = el => { for (let n = el; n && n !== document.body; n = n.parentElement) {
    if (n === feed) return true;
    const s = getComputedStyle(n); if (/(auto|scroll)/.test(s.overflowY) && n.scrollHeight > n.clientHeight + 1) return true; } return false; };
  const blocked = () => $("#view-ask").hidden || document.querySelector("dialog[open]");
  addEventListener("wheel", e => {
    if (e.ctrlKey || blocked() || own(e.target)) return;
    feed.scrollTop += e.deltaMode === 1 ? e.deltaY * 34 : e.deltaMode === 2 ? e.deltaY * feed.clientHeight : e.deltaY;
  }, { passive: true });
  addEventListener("keydown", e => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || blocked()) return;
    const at = document.activeElement, typing = at && (/^(INPUT|TEXTAREA|SELECT)$/.test(at.tagName) || at.isContentEditable);
    const page = feed.clientHeight * .85;
    const by = { PageDown: page, PageUp: -page }[e.key] ?? (typing ? null : { ArrowDown: 60, ArrowUp: -60, Home: -1e7, End: 1e7 }[e.key]);
    if (by == null || (at && at !== document.body && at !== feed && !typing && own(at) && !feed.contains(at))) return;
    if (at && at.closest && at.closest('[role="menu"], [role="listbox"], [role="radiogroup"], [role="tablist"]')) return;
    e.preventDefault();
    feed.scrollBy({ top: by, behavior: reducedMotion() || Math.abs(by) < 100 ? "auto" : "smooth" });
  });
}

/* ---- asking ----------------------------------------------------------------------------------- */
/* The newest turn is made tall enough to sit at the top of the view with the earlier ones scrolled away above it.
   With a single turn there is nothing above, so it gets no extra height and no empty scroll bar is drawn. */
function fitLastTurn() {
  const turns = thread.querySelectorAll(".turn");
  turns.forEach(el => { el.style.minHeight = ""; });
  if (turns.length > 1) turns[turns.length - 1].style.minHeight = (feed.clientHeight - 36) + "px";
}

export function newChat() {
  if (active) active.stop();
  active = null; lastQuestion = null; turnCount = 0; history = [];
  stopSpeaking();
  thread.querySelectorAll(".turn").forEach(el => el.remove());
  document.body.classList.remove("chatting");
  buddy.setCalm(false);
  renderWelcome();
  $("#newChat").hidden = true;
  input.placeholder = t("ask.placeholder");
  feed.scrollTop = 0;
  hooks.onNewChat && hooks.onNewChat();
}

export function relabel() {
  buildDock.relabel(); buildDock.reloadTopics(); buddy.relabel();
  if (!turnCount) renderWelcome();
}

/* A small celebration from whichever mascot is on screen (a class was added to the plan). */
export function frown() { const f = faceOf(); if (f && f.mood !== "calm") f.setMood("confused", { ms: 1800 }); }
export function cheer() { buddy.cheer(); }

/* Add a Beaver Bot message that didn't come from a question (for example after a demo action). */
export function say(text, { card, chips, mood = "happy" } = {}) {
  hooks.showAsk && hooks.showAsk();
  const turn = makeTurn(null);
  turn.note(text, card, chips, mood);
  return turn;
}

export function ask(question, opts = {}) {
  question = question.trim().slice(0, 400);
  if (!question) return;
  hooks.showAsk && hooks.showAsk();
  hooks.onAsk && hooks.onAsk();
  buildDock.closeMenu();
  if (active) active.stop();
  stopSpeaking();
  document.body.classList.remove("calm-mode");
  buddy.setCalm(false); buddy.setEmpty(false);
  input.value = ""; $("#privateHint").hidden = true; setGaze(null);
  input.placeholder = t("ask.placeholder.chat");
  if (matchMedia("(pointer: coarse)").matches) input.blur();
  const turn = makeTurn(question);
  active = turn;
  turn.start(opts);
}

function makeTurn(question) {
  turnCount++;
  buddy.setEmpty(false);          /* the conversation has started: the dam it was building clears away */
  document.body.classList.add("chatting");
  if (welcome) welcome.hidden = true;
  $("#newChat").hidden = false;
  const mascot = linked(createMascot("avatar"));
  lead = mascot;
  const thought = h("div.thought", { hidden: true }, h("span.trail", { "aria-hidden": "true" }, h("i"), h("i")),
    h("span.thought-text"), h("span.dots", { "aria-hidden": "true" }, h("i"), h("i"), h("i")));
  const out = h("div.out", { "aria-busy": "true" });
  const extras = h("div.extras", { hidden: true });
  const el = h("article.turn", question ? h("h2.question", h("span.sr-only", t("you.asked") + " "), question) : null,
    h("div.reply", mascot.el, h("div.reply-body", h("span.sr-only", t("bot.says")), thought, out, extras)));
  thread.append(el);
  fitLastTurn();
  feed.scrollTo({ top: question ? (turnCount > 1 ? el.offsetTop - 14 : 0) : feed.scrollHeight, behavior: reducedMotion() ? "auto" : "smooth" });

  let controller = null, meta = null, stream = null, text = "", done = false, stopped = false;
  const queue = []; let pumping = false;

  /* Status lines and answer pieces arrive faster than is pleasant to read, so they are played in order with a
     short minimum time for each status. With reduced motion everything shows at once. */
  async function pump() {
    if (pumping) return;
    pumping = true;
    while (queue.length && !stopped) {
      const [kind, data] = queue.shift();
      if (kind === "status") { showStatus(data); await sleep(STATUS_MS); }
      else if (kind === "meta") begin(data);
      else if (kind === "delta") { stream && stream.feed(data.t); follow(); }
      else if (kind === "done") finish(data.text);
      else if (kind === "error") fail(data.message);
    }
    pumping = false;
  }

  function showStatus(s) {
    const label = { reading: t("status.reading"), searching: t("status.searching", { n: (s.pages || 0).toLocaleString() }),
      found: t(s.count === 1 ? "status.found.one" : "status.found", { n: s.count }), none: t("status.none"),
      writing: t("status.writing"), checking: t("status.checking") }[s.step];
    if (!label) return;
    /* the bar mascot shows what kind of work this is: an umbrella out while it searches, a pencil while it writes */
    if (lead === mascot) buddy.mood({ reading: "searching", searching: "searching", found: "thinking", none: "confused", writing: "writing", checking: "writing" }[s.step] || "thinking");
    thought.hidden = false;
    const textEl = thought.querySelector(".thought-text");
    textEl.textContent = label; replay(textEl, "swap", 300);
    if (s.step === "found" && mascot.mood !== "calm") mascot.react("ping", 320);
  }

  function begin(m) {
    meta = m;
    thought.hidden = true;
    el.dataset.kind = m.kind;
    if (hushed(m)) buddy.setCalm(true);
    if (m.kind === "crisis") {
      el.classList.add("calm");
      mascot.setMood("calm");
      document.body.classList.add("calm-mode");
    } else if (m.kind === "refusal" || m.kind === "setup") mascot.setMood("confused");
    stream = new AnswerStream(out, {
      citeFor: n => m.cites && m.cites[String(n)] != null ? m.cites[String(n)] : null,
      citeLabel: n => t("source.n", { n }),
      onCite: n => { const card = extras.querySelector(`[data-card="${n}"]`); if (card) { card.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" }); replay(card, "flash", 1200); } },
    });
    if (m.kind === "crisis") out.classList.add("crisis-text");
  }

  function follow() {
    /* Keep the newest line in view while the answer grows, unless the reader has scrolled up. */
    const gap = feed.scrollHeight - feed.scrollTop - feed.clientHeight;
    if (gap < 140 && out.getBoundingClientRect().bottom > feed.getBoundingClientRect().bottom - 30) feed.scrollTop = feed.scrollHeight;
  }

  function finish(fullText) {
    if (done) return;
    done = true; text = fullText;
    stream && stream.end();
    out.setAttribute("aria-busy", "false");
    if (active === api_) active = null;
    const kind = meta.kind;
    if (kind === "answer") { mascot.setMood("happy", { ms: 2400 }); mascot.react("boing", 580); lastQuestion = question; hooks.onFlow && hooks.onFlow(null); }
    else if (kind === "demo") {
      mascot.setMood("happy", { ms: 1600 }); hooks.onFlow && hooks.onFlow(meta.flow || null);
    }
    else if (kind === "chat") mascot.setMood("happy", { ms: 1200 });
    else if (kind === "refusal") hooks.onFlow && hooks.onFlow(null);
    if (kind !== "crisis") { remember("user", question); remember("bot", meta.said || plainText(text)); }
    renderExtras();
    announce(plainText(text));
    if (prefs.autoRead && kind !== "demo") readAloud(extras.querySelector('[data-do="read"]'));
  }

  function fail(message) {
    done = true; thought.hidden = true; out.setAttribute("aria-busy", "false");
    if (active === api_) active = null;
    mascot.setMood("confused");
    clear(out).append(h("p.lead", t("error." + (["offline", "busy", "locked"].includes(message) ? message : "server"))));
    if (question) out.append(h("div.chips", h("button.chip", { type: "button", onclick: () => { el.remove(); turnCount--; ask(question); } }, icon("refresh"), t("retry"))));
    announce(out.textContent);
  }

  /* ---- everything under the answer ---- */
  function renderExtras() {
    clear(extras); extras.hidden = false;
    const kind = meta.kind;
    if (kind === "demo") {
      const card = hooks.demoCard && hooks.demoCard(meta, api_);
      if (card) { extras.append(card); if (lead === mascot && !hushed(meta)) setTimeout(() => buddy.deliver(card), 420); }
      if (meta.chips && meta.chips.length) extras.append(h("div.chips", meta.chips.map(c => questionChip(c))));
      return;
    }
    if (kind === "crisis") { extras.append(crisisActions()); return; }
    if (kind === "chat") {      /* just talking: no sources or ratings, only things to say next */
      if (meta.offer_demo && hooks.offerDemo) extras.append(h("div.chips", h("button.chip", { type: "button", onclick: hooks.offerDemo }, icon("sparkle"), t("demo.offer"))));
      if (meta.followups && meta.followups.length) extras.append(h("div.chips", meta.followups.map(q => questionChip(q))));
      extras.hidden = !extras.childNodes.length;
      return;
    }
    if (meta.contacts && meta.contacts.length) {
      extras.append(h("div.offices-row", meta.contacts.slice(0, 4).map(c => h("a.office-card", { href: c.url, target: "_blank", rel: "noopener" },
        h("span.office-ico", icon("pin")), h("span", h("strong", c.name.replace(/\s*\(24\/7.*?\)/, "")), h("small", t("office.open"))), icon("external")))));
    }
    if (meta.offer_demo && hooks.offerDemo) extras.append(h("div.chips", h("button.chip", { type: "button", onclick: hooks.offerDemo }, icon("sparkle"), t("demo.offer"))));
    if (kind === "answer") extras.append(actionRow());
    if (meta.pages && meta.pages.length) {
      const label = h("div.sources-head", h("span.label", t("sources")),
        meta.checked ? h("span.checked", icon("clock"), t("checked", { date: shortDate(meta.checked, lang()) })) : null,
        meta.live ? h("span.pill.line", { title: t("mode.live.hint") }, t("mode.live")) : null,
        meta.mode === "guide" || meta.mode === "extractive" ? h("span.pill.line", { title: t("mode.quotes.hint") }, t("mode.quotes")) : null);
      const grid = h("div.sources");
      meta.pages.forEach((p, i) => {
        /* the fullest quote under about 190 characters says the most in the space a card has */
        const best = p.quotes.filter(q => q.length <= 190).sort((a, b) => b.length - a.length)[0] || p.quotes[0];
        const card = h("a.source", { href: p.url, target: "_blank", rel: "noopener", "data-card": p.p, style: { animationDelay: (i * 70) + "ms" } },
          h("span.source-top", h("span.source-n", String(p.p)), h("strong", p.title), icon("external")),
          best ? h("q", best.length > 190 ? best.slice(0, 188).trimEnd() + "…" : best) : null,
          p.quotes.length > 1 ? h("small.more-quotes", t("source.more", { n: p.quotes.length - 1 })) : null,
          h("small", (p.office || p.site) + " · " + t("checked.short", { date: shortDate(p.checked, lang()) })));
        grid.append(card);
      });
      extras.append(h("div", label, grid));
    }
    if (kind === "refusal") extras.append(h("div.actions", actionButton("report", "flag", t("act.report"), openReport)));
    if (meta.followups && meta.followups.length) {
      extras.append(h("div", h("div.label.next-label", t("next")), h("div.chips", meta.followups.map(q => questionChip(q)))));
    }
  }

  function actionButton(name, iconName, label, onclick, extra = {}) {
    return h("button.act", { type: "button", "data-do": name, title: label, "aria-label": label, onclick, ...extra }, icon(iconName), h("span", label));
  }

  function actionRow() {
    const id = saved.idFor(question, meta.lang);
    const rate = which => e => {
      const btn = e.currentTarget, other = extras.querySelector(`[data-do="${which === "up" ? "down" : "up"}"]`);
      const on = btn.getAttribute("aria-pressed") !== "true";
      btn.setAttribute("aria-pressed", String(on)); other.setAttribute("aria-pressed", "false");
      if (!on) return;
      api.postJSON("/api/feedback", { rating: which, kind: meta.kind, category: meta.category && meta.category.id, lang: meta.lang,
        mode: meta.mode, sources: meta.pages.map(p => p.url) }).catch(() => {});
      if (which === "up") { mascot.react("wink", 700); toast(t("rate.thanks.up")); }
      else { mascot.react("oops", 1100); toast(t("rate.thanks.down"), { action: t("act.report"), onAction: openReport }); }
    };
    const save = e => {
      const btn = e.currentTarget, on = btn.getAttribute("aria-pressed") !== "true";
      if (on) saved.add({ id, question, text, pages: meta.pages, cites: meta.cites, checked: meta.checked, lang: meta.lang, savedAt: new Date().toISOString().slice(0, 10) });
      else saved.remove(id);
      btn.setAttribute("aria-pressed", String(on));
      toast(on ? t("save.done") : t("save.removed"), on ? { action: t("save.view"), onAction: () => hooks.go && hooks.go("/saved") } : {});
      if (on) mascot.react("ping", 320);
    };
    return h("div.actions",
      actionButton("up", "up", t("act.up"), rate("up"), { "aria-pressed": "false" }),
      actionButton("down", "downthumb", t("act.down"), rate("down"), { "aria-pressed": "false" }),
      h("span.act-gap"),
      actionButton("copy", "copy", t("act.copy"), async () => toast((await copyText(shareText())) ? t("copy.done") : t("copy.fail"))),
      actionButton("share", "share", t("act.share"), share),
      actionButton("save", "bookmark", t("act.save"), save, { "aria-pressed": String(saved.has(id)) }),
      speechSupported() ? actionButton("read", "volume", t("act.read"), e => readAloud(e.currentTarget)) : null,
      actionButton("report", "flag", t("act.report"), openReport));
  }

  function shareText() {
    const links = (meta.pages || []).map(p => `${p.p}. ${p.title}: ${p.url}`).join("\n");
    return `${question}\n\n${plainText(text)}${links ? `\n\n${t("sources")}:\n${links}` : ""}\n\n${t("share.by")}`;
  }
  async function share() {
    const url = location.origin + "/?q=" + encodeURIComponent(question);
    if (navigator.share && matchMedia("(pointer: coarse)").matches) {
      try { await navigator.share({ title: "Beaver Bot", text: shareText(), url }); return; } catch (e) { if (e.name === "AbortError") return; }
    }
    toast((await copyText(shareText() + "\n" + url)) ? t("share.done") : t("copy.fail"));
  }
  function readAloud(btn) {
    if (!btn) return;
    if (btn.getAttribute("aria-pressed") === "true") return stopSpeaking();
    const reset = () => { btn.setAttribute("aria-pressed", "false"); clear(btn).append(icon("volume"), h("span", t("act.read"))); };
    if (speak(plainText(text), meta.lang, reset)) { btn.setAttribute("aria-pressed", "true"); clear(btn).append(icon("stop"), h("span", t("act.stop"))); }
  }
  function openReport() {
    const note = h("textarea.input", { id: "report-note", maxlength: "600", placeholder: t("report.placeholder") });
    const s = sheet({ title: t("report.title"), sub: t("report.sub"), iconName: "flag", size: "slim" });
    s.setBody(h("div.report-what", h("div.label", t("report.saved")), h("p", question || ""), h("p.muted.small", plainText(text).slice(0, 220) + (text.length > 220 ? "…" : ""))),
      h("div.field", { style: { marginTop: "14px" } }, h("label", { for: "report-note" }, t("report.note")), note),
      h("p.small.muted", { style: { marginTop: "10px" } }, icon("shield"), " ", t("report.privacy")));
    s.setFoot(h("button.btn.quiet", { type: "button", onclick: () => s.close() }, t("cancel")),
      h("button.btn", { type: "button", onclick: async e => {
        e.currentTarget.disabled = true;
        try {
          await api.postJSON("/api/report", { question, answer: plainText(text), note: note.value, sources: (meta.pages || []).map(p => p.url),
            category: meta.category && meta.category.id, lang: meta.lang, mode: meta.mode });
          s.close(); toast(t("report.done"), { iconName: "check" });
        } catch (err) { e.currentTarget.disabled = false; toast(t("error.server")); }
      } }, t("report.send")));
    s.open(); note.focus();
  }

  function crisisActions() {
    const caps = (meta.contacts || []).find(c => /crisis|counsel/i.test(c.name));
    return h("div.crisis-actions",
      h("a.btn.calm-btn", { href: "tel:911" }, icon("call"), t("crisis.911")),
      h("a.btn.calm-btn", { href: "tel:+15417372131" }, icon("call"), t("crisis.caps")),
      caps ? h("a.btn.quiet", { href: caps.url, target: "_blank", rel: "noopener" }, t("crisis.page"), icon("external")) : null,
      meta.pages && meta.pages[0] ? h("p.small.muted", t("crisis.from", { date: shortDate(meta.pages[0].checked, lang()) })) : null);
  }

  const api_ = {
    el, mascot, question,
    get meta() { return meta; },
    start(opts) {
      mascot.setMood("thinking");
      controller = new AbortController();
      const body = { question, lang: lang(), history, stream: !reducedMotion() };
      const demo = hooks.demoContext && hooks.demoContext();
      if (demo && !opts.noDemo) body.demo = demo;
      api.ask(body, (event, data) => { queue.push([event, data]); pump(); }, controller.signal);
    },
    note(textValue, card, chips, mood) {
      meta = { kind: "note", lang: lang() }; done = true; text = textValue;
      stream = new AnswerStream(out, { citeFor: () => null, onCite() {}, citeLabel: () => "" });
      stream.feed(textValue); stream.end();
      out.setAttribute("aria-busy", "false");
      if (card || (chips && chips.length)) { extras.hidden = false; if (card) extras.append(card); if (chips && chips.length) extras.append(h("div.chips", chips.map(c => questionChip(c)))); }
      mascot.setMood(mood, { ms: 2200 });
      if (mood === "happy") { mascot.react("celebrate", 720); sparkle(mascot.el); }
      announce(textValue);
    },
    stop() {
      if (done) return;
      stopped = true; done = true;
      controller && controller.abort();
      thought.hidden = true; out.setAttribute("aria-busy", "false");
      /* Show whatever is still waiting at once, so a new question never leaves half an answer behind. */
      for (const [kind, data] of queue.splice(0)) {
        if (kind === "meta") begin(data);
        else if (kind === "delta" && stream) stream.feed(data.t);
        else if (kind === "done" && meta) { done = false; finish(data.text); }
      }
      if (!meta) el.remove();
      mascot.setMood(meta && meta.kind === "crisis" ? "calm" : "idle");
    },
  };
  return api_;
}

/* Used by the Saved page to show a stored answer again. */
export function renderStored(item, container) {
  const out = h("div.out");
  const stream = new AnswerStream(out, { citeFor: n => item.cites && item.cites[String(n)] != null ? item.cites[String(n)] : null, citeLabel: n => t("source.n", { n }), onCite() {} });
  stream.feed(item.text); stream.end();
  container.append(out);
}
