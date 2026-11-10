/* The demo's stand-in for a university sign-in page. SAMPLE ACCOUNTS ONLY.

   In a real version this page would belong to OSU, not to Beaver Bot: the browser would be sent to OSU's own
   sign-in, the student would sign in there, and Beaver Bot would only ever receive a one-time code. This page
   plays that part so the demo can show the same round trip. It has no password field at all. */
import { $, h, clear, icon } from "./dom.js";

/* The language chosen in the app wins; the browser's language is only the fallback. */
const ES = (() => { try { const chosen = JSON.parse(localStorage.getItem("bb-prefs") || "{}").lang; if (chosen) return chosen === "es"; } catch (e) { /* no saved choice */ } return (navigator.language || "").startsWith("es"); })();
const T = ES ? {
  banner: "Esta es una página de inicio de sesión de práctica. No es de Oregon State y nunca pide una contraseña.",
  title: "Elige una cuenta de demostración", lede: "Son estudiantes inventados. Elige una para ver qué podría hacer un Beaver Bot conectado.",
  locked: "Cuenta de muestra, bloqueada", next: "Continuar", cancel: "Cancelar y volver",
  step2: "Verificación en dos pasos", step2lede: "Un inicio de sesión real te pediría aprobar desde tu teléfono. Aquí solo se muestra el paso: no hay teléfono, código ni servicio real.",
  approve: "Aprobar", back: "Atrás", working: "Entrando…", expired: "Esta solicitud de inicio de sesión venció. Vuelve a Beaver Bot y empieza de nuevo.",
  home: "Volver a Beaver Bot", failed: "No se pudo iniciar sesión. Inténtalo de nuevo.", foot: "Proyecto estudiantil independiente, no afiliado a Oregon State University.",
  as: "Entrarás como", shares: "Beaver Bot recibirá: el nombre de esta cuenta de muestra. Nada más.",
} : {
  banner: "This is a practice sign-in page. It is not Oregon State's, and it never asks for a password.",
  title: "Choose a demo account", lede: "These are made-up students. Pick one to see what a connected Beaver Bot could do.",
  locked: "Ready-made sample account", next: "Continue", cancel: "Cancel and go back",
  step2: "Two-step verification", step2lede: "A real sign-in would ask you to approve on your phone. This only shows the step: no phone, code or real service is involved.",
  approve: "Approve", back: "Back", working: "Signing in…", expired: "This sign-in request ran out. Go back to Beaver Bot and start again.",
  home: "Back to Beaver Bot", failed: "Sign-in didn't work. Try again.", foot: "Independent student project, not affiliated with Oregon State University.",
  as: "You'll sign in as", shares: "Beaver Bot will receive: this sample account's name. Nothing else.",
};

const body = $("#idpBody");
const request = new URLSearchParams(location.search).get("request") || "";
let accounts = [], chosen = null;

function fail(text) {
  clear(body).append(h("div.idp-step", h("h1.idp-title", text), h("a.btn", { href: "/" }, T.home)));
}

function pick() {
  const list = h("div.idp-accounts", { role: "radiogroup", "aria-label": T.title });
  const next = h("button.btn", { type: "button", disabled: !chosen, onclick: approve }, T.next, icon("chevron"));
  accounts.forEach(a => {
    const card = h("button.idp-account", { type: "button", role: "radio", "aria-checked": String(chosen === a.slug), onclick: () => { chosen = a.slug; pick(); } },
      h("span.avatar-dot", a.first_name[0]),
      h("span.idp-who", h("strong", `${a.first_name} ${a.last_name}`), h("small", `${a.program} · ${a.standing}`), h("small.muted", a.situation)),
      h("span.idp-lock", { title: T.locked }, icon("lock")));
    list.append(card);
  });
  clear(body).append(h("div.idp-step", h("h1.idp-title", T.title), h("p.muted", T.lede), list,
    h("div.idp-actions", h("a.btn.quiet", { href: "/" }, T.cancel), next)));
  const current = list.querySelector('[aria-checked="true"]') || list.firstChild;
  if (current) current.focus();
}

function approve() {
  const who = accounts.find(a => a.slug === chosen);
  const status = h("p.muted", { role: "status" }, "");
  const ok = h("button.btn", { type: "button" }, T.approve);
  const back = h("button.btn.quiet", { type: "button", onclick: pick }, T.back);
  ok.addEventListener("click", async () => {
    ok.disabled = back.disabled = true; status.textContent = T.working;
    try {
      const res = await fetch("/api/idp/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request, account: chosen }) });
      const data = await res.json();
      if (!res.ok) return fail(data.error === "sign_in_expired" ? T.expired : T.failed);
      location.replace(data.redirect);            /* back to the app with a one-time code, never a password or a session */
    } catch (e) { ok.disabled = back.disabled = false; status.textContent = T.failed; }
  });
  clear(body).append(h("div.idp-step", h("div.verify-ring", icon("phone")), h("h1.idp-title", T.step2), h("p.muted", T.step2lede),
    h("p.idp-consent", icon("shield"), h("span", `${T.as} ${who.first_name} ${who.last_name}. ${T.shares}`)), status, h("div.idp-actions", back, ok)));
  ok.focus();
}

(async () => {
  document.documentElement.lang = ES ? "es" : "en";
  $("#idpBanner").textContent = T.banner; $("#idpFoot").textContent = T.foot;
  if (!request) return fail(T.expired);
  try { accounts = (await (await fetch("/api/idp/accounts")).json()).accounts; } catch (e) { return fail(T.failed); }
  if (!accounts.length) return fail(T.failed);
  pick();
})();
