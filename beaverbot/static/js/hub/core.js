/* The signed-in demo in the browser: sign-in, the session, the side panel, and the review-and-confirm step.
   SAMPLE DATA ONLY.

   The browser holds no student data of its own and no record of who is signed in. The server knows that from an
   HttpOnly cookie this code cannot read. Every panel asks the server for what to show, and every change goes
   through the same three steps: the server writes out exactly what would change (a proposal), the student reads
   it and confirms, and the server carries it out. Nothing here can skip the middle step. */
import { $, h, clear, icon, reducedMotion, replay } from "../dom.js";
import { lang } from "../i18n.js";
import { sheet, toast, announce } from "../ui.js";
import { createMascot } from "../mascot.js";
import { changeRows } from "./rows.js";

export const L = (en, es) => (lang() === "es" ? es : en);
const PKCE_KEY = "bb-signin";
let S = { signedIn: false, csrf: null, profile: null, expiresIn: 0, warn: 120, verified: false, clockDays: 0 };
let deps = {}, listeners = [], idleTimer = null, warning = null;
const drafts = {};

export const signedIn = () => S.signedIn;
export const profile = () => S.profile;
export const session = () => S;
export const onChange = fn => listeners.push(fn);
const changed = what => listeners.forEach(fn => { try { fn(what); } catch (e) { /* a closed panel */ } });
export const draft = name => (drafts[name] || (drafts[name] = {}));

/* ---- talking to the server ---------------------------------------------------------------------- */
export class HubError extends Error { constructor(code, status, detail) { super(code); this.code = code; this.status = status; this.detail = detail; } }

async function call(path, body) {
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 15000);
  let res;
  try {
    /* X-Lang tells the server which language to write its sentences in (reviews, reasons, results). */
    res = await fetch(path, body === undefined ? { headers: { Accept: "application/json", "X-Lang": lang() }, signal: ctl.signal }
      : { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": S.csrf || "", "X-Lang": lang() }, body: JSON.stringify(body), signal: ctl.signal });
  } catch (e) { throw new HubError(e.name === "AbortError" ? "timeout" : "offline", 0); }
  finally { clearTimeout(timer); }
  let data = {};
  try { data = await res.json(); } catch (e) { /* an empty body */ }
  if (res.status === 401) { ended(); throw new HubError("signed_out", 401); }
  if (!res.ok) throw new HubError(data.error || "server", res.status, data.detail);
  return data;
}
export const read = (system, query = {}) => call(`/api/hub/${system}` + (Object.keys(query).length ? "?" + new URLSearchParams(query) : ""));
export const post = (name, body = {}) => call(`/api/hub/${name}`, body);

export function explain(err) {
  const map = {
    offline: L("Couldn't reach Beaver Bot. Check your connection and try again.", "No se pudo conectar con Beaver Bot. Revisa tu conexión e inténtalo de nuevo."),
    timeout: L("That took too long. Nothing was changed. Try again.", "Eso tardó demasiado. No se cambió nada. Inténtalo de nuevo."),
    signed_out: L("Your demo session ended. Sign in again to keep going.", "Tu sesión de demostración terminó. Inicia sesión de nuevo para continuar."),
    proposal_expired: L("That review ran out after five minutes. Nothing was changed. Start it again.", "Esa revisión venció a los cinco minutos. No se cambió nada. Empiézala de nuevo."),
    proposal_changed: L("Something changed since you read that review, so it wasn't carried out. Open it again to see what would happen now.", "Algo cambió desde que leíste esa revisión, así que no se realizó. Ábrela de nuevo."),
    proposal_gone: L("That was already confirmed or replaced. Nothing was done twice.", "Eso ya se confirmó o se reemplazó. Nada se hizo dos veces."),
    blocked: L("That can't be done right now.", "Eso no se puede hacer ahora."),
    slow_down: L("That's a lot of tries in a minute. Wait a moment and try again.", "Son muchos intentos en un minuto. Espera un momento e inténtalo de nuevo."),
    cannot_undo: L("That can't be undone any more.", "Eso ya no se puede deshacer."),
    undo_latest_first: L("Undo the more recent change in that system first.", "Primero deshaz el cambio más reciente en ese sistema."),
    csrf: L("This page is out of date. Reload it and try again.", "Esta página está desactualizada. Recárgala e inténtalo de nuevo."),
  };
  if (err && err.code === "blocked" && err.detail) return err.detail;
  return map[err && err.code] || (err && err.detail) || L("Something went wrong on our side. Nothing was changed.", "Algo salió mal de nuestro lado. No se cambió nada.");
}

/* ---- sign-in: a redirect to a separate sign-in page, then a one-time code swapped for a session ---- */
const b64url = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const random = n => b64url(crypto.getRandomValues(new Uint8Array(n)));

export async function signIn() {
  if (!deps.cfg || !deps.cfg.demo) { toast(L("The sample data isn't built on this computer yet.", "Los datos de muestra aún no están en esta computadora.")); return; }
  const s = sheet({ size: "slim", label: L("Sign in to the demo", "Entrar a la demostración") });
  s.head.classList.add("bare");
  const m = createMascot("mini");
  s.setBody(h("div.signin",
    h("div.signin-top", m.el, h("h2.sheet-title", L("Sign in to the demo", "Entrar a la demostración")),
      h("p.muted", L("See what a connected Beaver Bot could do, using a made-up student.", "Mira lo que podría hacer un Beaver Bot conectado, con un estudiante inventado."))),
    h("ol.signin-steps",
      h("li", icon("door"), h("span", L("You'll go to a separate practice sign-in page.", "Irás a una página de inicio de sesión de práctica, aparte."))),
      h("li", icon("user"), h("span", L("You pick a locked sample account there. No password exists, so none is asked for.", "Ahí eliges una cuenta de muestra bloqueada. No existe contraseña, así que no se pide."))),
      h("li", icon("shield"), h("span", L("You come back signed in. Beaver Bot only receives a one-time code.", "Regresas con la sesión iniciada. Beaver Bot solo recibe un código de un solo uso.")))),
    h("p.signin-note", icon("info"), h("span", L("A real version would send you to Oregon State's own sign-in the same way, so Beaver Bot would never see your password.",
      "Una versión real te enviaría igual al inicio de sesión de Oregon State, así Beaver Bot nunca vería tu contraseña.")))));
  const go = h("button.btn", { type: "button", onclick: async () => {
    go.disabled = true;
    const verifier = random(48), state = random(16);
    const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
    sessionStorage.setItem(PKCE_KEY, JSON.stringify({ verifier, state }));     /* the verifier never leaves this tab until the code comes back */
    location.assign(`/auth/start?challenge=${challenge}&state=${state}`);
  } }, L("Continue to sign-in", "Continuar al inicio de sesión"), icon("chevron"));
  s.setFoot(h("button.btn.quiet", { type: "button", onclick: () => s.close() }, L("Cancel", "Cancelar")), go);
  s.open(); go.focus();
}

async function finishSignIn() {
  const q = new URLSearchParams(location.search), code = q.get("code"), state = q.get("state");
  let saved = null;
  try { saved = JSON.parse(sessionStorage.getItem(PKCE_KEY) || "null"); } catch (e) { /* nothing saved */ }
  sessionStorage.removeItem(PKCE_KEY);
  history.replaceState(null, "", "/");           /* the code is used once and never stays in the address bar */
  if (!code || !saved || saved.state !== state) { toast(L("Sign-in didn't finish. Try again.", "El inicio de sesión no terminó. Inténtalo de nuevo.")); return false; }
  try { adopt(await call("/api/session/token", { code, verifier: saved.verifier })); return true; }
  catch (e) { toast(explain(e)); return false; }
}

function adopt(data) {
  S = { signedIn: !!data.signed_in, csrf: data.csrf || null, profile: data.profile || null, expiresIn: data.expires_in || 0,
        warn: data.warn_seconds || 120, verified: !!data.verified, clockDays: data.clock_days || 0 };
  watchIdle();
}

export async function init(d) {
  deps = d;
  let fresh = false;
  if (location.pathname === "/auth/callback") fresh = await finishSignIn();
  if (!S.signedIn) { try { adopt(await call("/api/session")); } catch (e) { /* signed out */ } }
  return { signedIn: S.signedIn, fresh };
}

export async function signOut() {
  try { await call("/api/session/signout", {}); } catch (e) { /* already gone */ }
  ended(L("Signed out. Your demo session was ended on the server.", "Sesión cerrada. Tu sesión de demostración terminó en el servidor."));
}

function ended(message) {
  const was = S.signedIn;
  S = { signedIn: false, csrf: null, profile: null, expiresIn: 0, warn: 120, verified: false, clockDays: 0 };
  clearInterval(idleTimer); if (warning) { warning.close(); warning = null; }
  closePanel(true);
  if (was) { changed("session"); toast(message || explain({ code: "signed_out" }), { ms: 5000 }); }
}

/* ---- idle timeout: a warning, then the session ends on the server ---------------------------------- */
function watchIdle() {
  clearInterval(idleTimer);
  if (!S.signedIn) return;
  idleTimer = setInterval(async () => {
    let now;
    try { now = await call("/api/session?peek=1"); } catch (e) { return; }
    if (!now.signed_in) return ended(L("You were signed out after 20 minutes without activity. Anything you'd confirmed is saved; a review you hadn't confirmed was not carried out.",
      "Se cerró tu sesión tras 20 minutos sin actividad. Lo que confirmaste quedó guardado; una revisión sin confirmar no se realizó."));
    S.expiresIn = now.expires_in;
    if (now.expires_in <= S.warn && !warning) warnIdle();
  }, 30000);
}
function warnIdle() {
  warning = sheet({ size: "slim", title: L("Still there?", "¿Sigues ahí?"), iconName: "clock", onClose: () => { warning = null; },
    sub: L("For your privacy the demo signs you out after 20 minutes without activity. That's about two minutes from now.",
      "Por tu privacidad la demostración cierra la sesión tras 20 minutos sin actividad. Faltan unos dos minutos.") });
  warning.setFoot(h("button.btn.quiet", { type: "button", onclick: () => { warning.close(); signOut(); } }, L("Sign out", "Cerrar sesión")),
    h("button.btn", { type: "button", onclick: async () => { try { adopt({ ...(await call("/api/session/keepalive", {})), signed_in: true, profile: S.profile }); } catch (e) { toast(explain(e)); } warning && warning.close(); } },
      L("Stay signed in", "Seguir conectado")));
  warning.open();
}

/* ---- the side panel ------------------------------------------------------------------------------ */
const registry = {};
export const register = (name, def) => { registry[name] = def; };
let panel = null;

/* On a wide screen the panel is a desk beside the conversation: always there once you are signed in, showing
   whichever connected site was last talked about. On a narrower screen it slides over from what was pressed. */
const wide = () => matchMedia("(min-width: 1180px)").matches;
export const onDesk = () => !!panel && document.body.classList.contains("desk");
export function openDesk() { if (S.signedIn && wide() && !panel) openPanel("home", {}, { quiet: true }); }
/* The conversation moved on to another site, so the desk shows it. Nothing happens if the desk was put away. */
export function showOnDesk(name, args = {}) {
  if (!onDesk() || !registry[name]) return;
  const top = panel.stack[panel.stack.length - 1];
  if (top.name === name && JSON.stringify(top.args) === JSON.stringify(args)) return draw(true, true);
  panel.stack = [{ name, args }];
  draw(false, true);
}
matchMedia("(min-width: 1180px)").addEventListener("change", e => { if (panel) document.body.classList.toggle("desk", e.matches); });

export function closePanel(silent) {
  if (!panel) return;
  const p = panel; panel = null;
  document.body.classList.remove("hub-open", "desk");
  /* Focus goes back to what opened the panel, or to the question box if that button has since been redrawn. */
  const done = () => { p.el.remove(); if (!silent) { const to = p.opener && p.opener.isConnected ? p.opener : $("#q"); to && to.focus({ preventScroll: true }); } };
  if (reducedMotion()) done(); else { p.el.classList.add("closing"); setTimeout(done, 180); }
}

export function openPanel(name, args = {}, { quiet = false } = {}) {
  if (!S.signedIn) { signIn(); return; }
  const def = registry[name];
  if (!def) return;
  if (!panel) {
    const opener = document.activeElement;
    const title = h("h2.hub-title", { id: "hub-title", tabindex: "-1" });
    const meta = h("p.hub-meta");
    const back = h("button.icon-btn.hub-back", { type: "button", hidden: true, "aria-label": L("Back", "Atrás"), title: L("Back", "Atrás"), onclick: () => goBack() }, icon("chevron"));
    const steps = h("ol.hub-steps", { hidden: true });
    const body = h("div.hub-body"), foot = h("footer.hub-foot", { hidden: true });
    const el = h("aside.hub-panel", { role: "complementary", "aria-labelledby": "hub-title" },
      h("header.hub-head", back, h("div.hub-titles", title, meta),
        h("button.icon-btn", { type: "button", "aria-label": L("Close panel", "Cerrar panel"), title: L("Close panel (Esc)", "Cerrar panel (Esc)"), onclick: () => closePanel() }, icon("x"))),
      steps, body, foot);
    el.addEventListener("keydown", e => { if (e.key === "Escape" && !document.querySelector("dialog[open]")) { e.stopPropagation(); if (panel.stack.length > 1) goBack(); else closePanel(); } });
    /* it grows out of whatever was pressed to open it */
    const from = opener && opener !== document.body && opener.getBoundingClientRect ? opener.getBoundingClientRect() : null;
    if (from && from.width) { el.style.setProperty("--ox", Math.max(0, Math.min(100, (from.left + from.width / 2 - (innerWidth - 480)) / 480 * 100)) + "%"); el.style.setProperty("--oy", (from.top + from.height / 2) / innerHeight * 100 + "%"); }
    document.body.append(el);
    document.body.classList.add("hub-open");
    document.body.classList.toggle("desk", wide());
    panel = { el, title, meta, back, steps, body, foot, stack: [], opener };
  }
  panel.stack.push({ name, args });
  draw(false, quiet);
}
function goBack() { if (panel && panel.stack.length > 1) { panel.stack.pop(); draw(); } }
export const refreshPanel = () => { if (panel) draw(true); };

/* A panel with several sections becomes a few tabs, so a site is a page or two and not one long scroll. Whatever
   sits above the sections (the balance, the card, a note) stays in view above the tabs. */
const tabAt = {};
function tabify(p, name) {
  const sheet = p.body.firstElementChild;
  if (!sheet) return;
  const secs = [...sheet.children].filter(el => el.matches("section.hub-sec") && el.querySelector(":scope > .hub-h"));
  if (secs.length < 3) return;
  const bar = h("div.sheet-tabs", { role: "tablist", "aria-label": p.title.textContent });
  const pick = (i, focus) => {
    tabAt[name] = i;
    secs.forEach((s, n) => { s.hidden = n !== i; });
    [...bar.children].forEach((b, n) => { b.setAttribute("aria-selected", String(n === i)); b.tabIndex = n === i ? 0 : -1; });
    if (focus) bar.children[i].focus();
  };
  secs.forEach((s, i) => {
    const id = `tab-${name}-${i}`;
    s.classList.add("tabbed"); s.setAttribute("role", "tabpanel"); s.setAttribute("aria-labelledby", id);
    bar.append(h("button", { type: "button", role: "tab", id, onclick: () => pick(i) }, s.querySelector(":scope > .hub-h").textContent));
  });
  bar.addEventListener("keydown", e => {
    const at = [...bar.children].indexOf(document.activeElement), n = secs.length;
    const to = { ArrowRight: (at + 1) % n, ArrowLeft: (at - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (to === undefined || at < 0) return;
    e.preventDefault(); pick(to, true);
  });
  sheet.append(bar, ...secs);
  pick(Math.min(tabAt[name] || 0, secs.length - 1));
}

async function draw(keepScroll, quiet) {
  const p = panel, top = p.stack[p.stack.length - 1], def = registry[top.name];
  const scroll = keepScroll ? p.body.scrollTop : 0;
  /* A redraw rebuilds the body. Remember which control had focus (by its text) so the keyboard doesn't fall out of the panel. */
  const held = keepScroll && p.el.contains(document.activeElement) ? (document.activeElement.textContent || "").trim() : null;
  p.back.hidden = p.stack.length < 2;
  p.title.textContent = typeof def.title === "function" ? def.title(top.args) : def.title;
  p.steps.hidden = true; clear(p.foot); p.foot.hidden = true;
  if (!keepScroll) { clear(p.body).append(h("div.hub-loading", { role: "status" }, h("span.spinner"), L("Loading…", "Cargando…"))); clear(p.meta); }
  const ctx = {
    args: top.args, body: p.body, draft: draft(top.name),
    setTitle: text => { if (panel === p && p.stack[p.stack.length - 1] === top) p.title.textContent = text; },
    /* Where this came from: the system's name, that it is sample data, and when it was read. */
    stamp: data => { clear(p.meta).append(h("span.pill.sample", L("Sample data", "Datos de muestra")), h("span", `${data.source ? L("From ", "De ") + data.source : data.system} · ${L("as of", "a las")} ${data.as_of}`)); },
    steps: (list, at) => { clear(p.steps); list.forEach((label, i) => p.steps.append(h("li" + (i < at ? ".done" : i === at ? ".now" : ""), { "aria-current": i === at ? "step" : null }, h("span.n", i < at ? icon("check") : String(i + 1)), h("span", label)))); p.steps.hidden = false; },
    foot: (...kids) => { clear(p.foot); kids.filter(Boolean).forEach(k => p.foot.append(k)); p.foot.hidden = !p.foot.childNodes.length; },
    open: (n, a) => openPanel(n, a), back: goBack, close: () => closePanel(), reload: () => draw(true),
    replace: (n, a) => { p.stack[p.stack.length - 1] = { name: n, args: a || {} }; draw(); },
    /* Finish a multi-step flow: forget the steps and land on one panel. */
    land: (n, a) => { p.stack = [{ name: n, args: a || {} }]; if (p.last) p.last.name = n; draw(); },
  };
  try {
    const content = await def.render(ctx);
    if (panel !== p || p.stack[p.stack.length - 1] !== top) return;      /* the student moved on while this loaded */
    clear(p.body); if (content) p.body.append(content);
    tabify(p, top.name);
    p.body.scrollTop = scroll;
    if (p.last && p.last.name === top.name) p.body.prepend(p.last.el); else p.last = null;
    if (!keepScroll && !quiet) { p.title.focus({ preventScroll: true }); announce(p.title.textContent); }
    else if (held !== null && !p.el.contains(document.activeElement)) {
      const again = [...p.el.querySelectorAll("button, input, select, textarea")].find(x => (x.textContent || "").trim() === held && !x.disabled);
      (again || p.title).focus({ preventScroll: true });
    }
  } catch (e) {
    if (panel !== p) return;
    clear(p.body).append(h("div.hub-empty", icon("alert"), h("p", explain(e)),
      e.code === "signed_out" ? null : h("button.btn.small", { type: "button", onclick: () => draw() }, L("Try again", "Reintentar"))));
  }
}

/* ---- review and confirm ---------------------------------------------------------------------------- */
/* Ask the server what a change would do, show exactly that, and carry it out only on the student's own click.
   `proposal` may be one the assistant prepared; it is shown the same way and needs the same click. */
export async function review(system, change, { proposal = null, onDone } = {}) {
  let plan = proposal;
  if (!plan) { try { plan = await post("propose", { system, change }); } catch (e) { toast(explain(e)); return; } }
  const blocked = plan.blocks && plan.blocks.length;
  /* A change to several classes is a list, so it gets the wider dialog. */
  const s = sheet({ size: !blocked && plan.classes && plan.classes.length > 1 ? "" : "slim", title: plan.title, iconName: blocked ? "alert" : "check", sample: true,
    sub: blocked ? L("This can't be done yet. Here's why.", "Esto aún no se puede hacer. Esta es la razón.")
      : plan.by === "assistant" ? L("Beaver Bot set this up. Nothing happens unless you confirm.", "Beaver Bot preparó esto. Nada pasa a menos que confirmes.")
        : L("Check this over. Nothing has changed yet.", "Revísalo. Aún no ha cambiado nada.") });
  const list = (label, items, cls, ic) => items && items.length ? h("section.rv" + cls, h("h3.rv-h", label), h("ul", items.map(x => h("li", icon(ic), h("span", x))))) : null;
  const blocks = blocked ? h("section.rv.rv-block", plan.blocks.map(b => h("div.rv-reason", icon("alert"), h("div", h("p", h("strong", b.reason)), b.next ? h("p.muted", b.next) : null,
    b.action && b.action.panel ? h("button.btn.small", { type: "button", onclick: () => { s.close(); openPanel(b.action.panel); } },
      b.action.panel === "advising" ? (b.action.booked ? L("See my meeting", "Ver mi reunión") : L("Book my advisor", "Reservar con mi asesor")) : b.action.panel === "billing" ? L("See where to pay", "Ver dónde pagar") : L("Find a class", "Buscar una clase")) : null,
    b.action && b.action.withdraw && change ? h("button.btn.small", { type: "button", onclick: () => { s.close(); review(system, { type: "withdraw", term: change.term, crn: b.action.withdraw }); } }, L("Withdraw instead", "Retirarme en su lugar")) : null,
    b.action && (b.action.swap || b.action.linked) ? h("button.btn.small", { type: "button", onclick: () => { s.close(); openPanel("schedule", { term: change && change.term }); } }, L("Open my classes", "Abrir mis clases")) : null)))) : null;
  s.setBody(h("div.review", blocks,
    blocked ? null : (plan.classes && plan.classes.length ? h("section.rv.rv-do", h("h3.rv-h", L("What will happen", "Qué pasará")), changeRows(plan))
      : list(L("What will happen", "Qué pasará"), plan.effects, ".rv-do", "check")),
    blocked ? null : list(L("What won't change", "Qué no cambia"), plan.unchanged, ".rv-keep", "minus"),
    list(L("Good to know first", "Conviene saber antes"), plan.warnings, ".rv-warn", "alert"),
    blocked ? null : h("p.rv-undo.small.muted", icon(plan.undoable ? "refresh" : "lock"),
      plan.undoable ? L(" You can undo this afterwards.", " Podrás deshacerlo después.") : L(" This one can't be undone here.", " Esto no se puede deshacer aquí."))));
  const cancel = h("button.btn.quiet", { type: "button", onclick: () => s.close() }, blocked ? L("OK", "Entendido") : L("Cancel", "Cancelar"));
  if (blocked) { s.setFoot(cancel); s.open(); deps.mood && deps.mood("confused"); cancel.focus(); return; }

  const ok = h("button.btn", { type: "button" }, plan.button || L("Confirm", "Confirmar"));
  const confirm = async () => {
    ok.disabled = cancel.disabled = true;
    try {
      const done = await post("confirm", { id: plan.id, token: plan.token });
      s.close();
      finished(done);
      onDone && onDone(done);
    } catch (e) {
      if (e.code === "verify_first") { ok.disabled = cancel.disabled = false; return verifyStep(); }
      s.close(); setTimeout(() => toast(explain(e), { ms: 5200 }), 260); refreshPanel();
    }
  };
  /* High-impact changes need a fresh "it's really me" step first. In the demo that is an Approve button. */
  const verifyStep = () => {
    s.setTitle(L("One more check that it's you", "Una verificación más de que eres tú"),
      L("This change is hard to reverse or involves money, so a real version would ask you to approve it again through the university's sign-in.",
        "Este cambio es difícil de revertir o implica dinero, así que una versión real te pediría aprobarlo otra vez con el inicio de sesión de la universidad."));
    s.setIcon("shield");
    s.setBody(h("div.signin", h("div.verify-ring", icon("phone")), list(L("You're approving", "Estás aprobando"), plan.effects, ".rv-do", "check"), h("p.signin-note", icon("info"),
      h("span", L("Demo: pressing Approve stands in for that step. No phone or code is involved.", "Demostración: Aprobar representa ese paso. No hay teléfono ni código.")))));
    const approve = h("button.btn", { type: "button", onclick: async () => {
      approve.disabled = true;
      try { await call("/api/session/verify", {}); await confirm(); } catch (e) { s.close(); toast(explain(e)); }
    } }, L("Approve and ", "Aprobar y ") + (plan.button || L("confirm", "confirmar")).toLowerCase());
    s.setFoot(h("button.btn.quiet", { type: "button", onclick: () => s.close() }, L("Cancel", "Cancelar")), approve);
    approve.focus();
  };
  ok.addEventListener("click", plan.verify ? verifyStep : confirm);
  s.setFoot(cancel, ok); s.open(); ok.focus();
}

/* A confirmed change folds up and flies to "What I've done", which is where to find it (and undo it) afterwards. */
function fileAway() {
  const to = document.querySelector(".demo-tools");
  if (!to || reducedMotion()) return;
  const r = to.getBoundingClientRect(), x = innerWidth / 2, y = innerHeight / 2;
  const slip = h("span.slip-ghost", { "aria-hidden": "true" });
  slip.style.left = x + "px"; slip.style.top = y + "px";
  document.body.append(slip);
  slip.animate([{ transform: "none", opacity: 1 }, { transform: `translate(${(r.left + r.width / 2 - x) * .5}px, ${(r.top - y) * .7}px) scale(.7) rotate(-8deg)`, opacity: 1, offset: .55 },
    { transform: `translate(${r.left + r.width / 2 - x}px, ${r.top + r.height / 2 - y}px) scale(.2) rotate(14deg)`, opacity: .4 }], { duration: 640, easing: "cubic-bezier(.5,0,.3,1)" })
    .onfinish = () => { slip.remove(); replay(to, "bump", 520); };
}

function finished(done) {
  announce(done.summary);
  fileAway();
  changed(done.system);
  if (panel) {
    const strip = h("div.justnow", { role: "status" }, icon("check"), h("div", h("strong", L("Just now: ", "Recién: ") + done.summary), (done.details || []).map(x => h("p.small.muted", x))),
      done.can_undo ? h("button.btn.small.quiet", { type: "button", onclick: () => { panel && (panel.last = null); undo(done.history_id); } }, L("Undo", "Deshacer")) : null);
    panel.last = { name: panel.stack[panel.stack.length - 1].name, el: strip };
  }
  refreshPanel();
  deps.mood && deps.mood("happy");
  /* after the review dialog has gone, or the message would be removed along with it */
  setTimeout(() => toast(done.summary, { iconName: "check", ms: 5200, ...(done.can_undo ? { action: L("Undo", "Deshacer"), onAction: () => undo(done.history_id) } : {}) }), 260);
  deps.afterChange && deps.afterChange(done);
}

/* The fresh "it's really me" step on its own, for showing a sensitive detail. Resolves true once approved. */
export function verify(what) {
  return new Promise(resolve => {
    let ok = false;
    const s = sheet({ size: "slim", title: L("One more check that it's you", "Una verificación más de que eres tú"), iconName: "shield", sample: true, sub: what, onClose: () => resolve(ok) });
    s.setBody(h("div.signin", h("div.verify-ring", icon("phone")), h("p.signin-note", icon("info"), h("span", L("Demo: pressing Approve stands in for approving again through the university's sign-in. No phone or code is involved.", "Demostración: Aprobar representa aprobar de nuevo con el inicio de sesión de la universidad.")))));
    const approve = h("button.btn", { type: "button", onclick: async () => { approve.disabled = true; try { await call("/api/session/verify", {}); ok = true; } catch (e) { toast(explain(e)); } s.close(); } }, L("Approve", "Aprobar"));
    s.setFoot(h("button.btn.quiet", { type: "button", onclick: () => s.close() }, L("Cancel", "Cancelar")), approve);
    s.open(); approve.focus();
  });
}

export async function undo(id) {
  try { let done;
    try { done = await post("undo", { id }); }
    catch (e) { if (e.code !== "verify_first") throw e;       /* undoing this would drop below full-time: the same extra check applies */
      if (!(await verify(L("Undoing this would take you below full-time, so it needs a fresh check.", "Deshacer esto te dejaría por debajo de tiempo completo, así que requiere una verificación.")))) return;
      done = await post("undo", { id }); }
    announce(done.summary); toast(done.summary, { iconName: "refresh" }); changed(done.system); refreshPanel(); deps.afterChange && deps.afterChange(done); }
  catch (e) { toast(explain(e)); }
}

export async function reset(everyone) {
  try { await post("reset", { everyone }); Object.keys(drafts).forEach(k => delete drafts[k]); changed("reset"); refreshPanel(); toast(L("Sample data is back to how it started.", "Los datos de muestra volvieron al inicio."), { iconName: "refresh" }); }
  catch (e) { toast(explain(e)); }
}
export async function setClock(days) {
  try { const now = await post("clock", { days }); S.clockDays = now.clock_days; changed("clock"); refreshPanel();
    toast(days ? L("The demo now runs as if it were registration week.", "La demo ahora corre como si fuera la semana de inscripción.") : L("The demo is back on today's date.", "La demo volvió a la fecha de hoy."), { iconName: "clock" }); }
  catch (e) { toast(explain(e)); }
}
