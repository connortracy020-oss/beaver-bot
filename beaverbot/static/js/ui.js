/* Shared interface pieces: the sheet (a modal popup), small popovers and toasts. */
import { h, add, clear, icon, reducedMotion } from "./dom.js";
import { t } from "./i18n.js";

/* A sheet is a native <dialog>: the browser traps focus inside it, Esc closes it, and focus goes back to
   whatever opened it. On a phone it slides up from the bottom. */
export function sheet({ title, sub, iconName, size = "", sample = false, onClose, label } = {}) {
  const opener = document.activeElement;
  const titleEl = h("h2.sheet-title", { id: "sheet-title-" + Math.random().toString(36).slice(2, 8) }, title || "");
  const subEl = h("p.sheet-sub", { hidden: !sub }, sub || "");
  const iconEl = h("div.sheet-icon", { hidden: !iconName }, iconName ? icon(iconName) : null);
  const closeBtn = h("button.icon-btn", { type: "button", "aria-label": t("close"), onclick: () => api.close() }, icon("x"));
  const head = h("header.sheet-head", iconEl, h("div.sheet-titles", titleEl, subEl,
    sample ? h("span.pill.sample", { style: { marginTop: "7px" } }, t("demo.sample")) : null), closeBtn);
  const body = h("div.sheet-body");
  const foot = h("footer.sheet-foot", { hidden: true });
  const el = h("dialog.sheet" + (size ? "." + size : ""), { "aria-labelledby": titleEl.id, "aria-label": label || null }, head, body, foot);
  let closed = false;

  const api = {
    el, body, foot, head,
    setTitle(text, subText) { titleEl.textContent = text; subEl.textContent = subText || ""; subEl.hidden = !subText; },
    setIcon(name) { clear(iconEl).append(icon(name)); iconEl.hidden = false; },
    setBody(...kids) { clear(body); add(body, kids); body.scrollTop = 0; return api; },
    /* Swap the body with a small slide, for multi-step popups (sign-in, booking). */
    step(...kids) { const wrap = h("div.sheet-step", kids); clear(body).append(wrap); body.scrollTop = 0; return wrap; },
    setFoot(...kids) { clear(foot); add(foot, kids); foot.hidden = !foot.childNodes.length; return api; },
    open() { document.body.append(el); el.showModal(); return api; },
    close(result) {
      if (closed) return;
      closed = true;
      const finish = () => { el.close(); el.remove(); if (opener && opener.isConnected) opener.focus({ preventScroll: true }); onClose && onClose(result); };
      if (reducedMotion()) return finish();
      el.classList.add("closing");
      setTimeout(finish, 170);
    },
  };
  el.addEventListener("cancel", e => { e.preventDefault(); api.close(); });
  el.addEventListener("click", e => { if (e.target === el) api.close(); });   /* a click on the backdrop */
  return api;
}

let toastBox;
export function toast(message, { action, onAction, ms = 2600, iconName } = {}) {
  /* An open popup sits in the browser's top layer, above everything else, so the toast has to live inside it. */
  const dialogs = document.querySelectorAll("dialog[open]"), top = dialogs[dialogs.length - 1];
  if (top) { toastBox = top.querySelector(":scope > .toasts") || top.appendChild(h("div.toasts.in-sheet", { "aria-live": "polite" })); }
  else toastBox = document.getElementById("toasts");
  const el = h("div.toast", { role: "status" }, iconName ? icon(iconName) : null, h("span", message));
  const remove = () => { el.classList.add("out"); setTimeout(() => el.remove(), reducedMotion() ? 0 : 190); };
  if (action) el.append(h("button", { type: "button", onclick: () => { onAction && onAction(); remove(); } }, action));
  while (toastBox.children.length >= 2) toastBox.firstChild.remove();
  toastBox.append(el);
  setTimeout(remove, action ? ms + 2400 : ms);
}

/* A small menu anchored to a button. Closes on outside click, Esc, or choosing an item. */
let openPop = null;
export function closePopover() { if (openPop) openPop(); }
export function popover(anchor, build, { align = "right" } = {}) {
  if (openPop) { const same = openPop.anchor === anchor; openPop(); if (same) return; }
  const el = h("div.pop", { role: "menu" });
  const close = () => {
    el.remove(); anchor.setAttribute("aria-expanded", "false");
    removeEventListener("pointerdown", outside, true); removeEventListener("keydown", keys, true); removeEventListener("resize", close);
    if (openPop === close) openPop = null;
  };
  close.anchor = anchor;
  const outside = e => { if (!el.contains(e.target) && !anchor.contains(e.target)) close(); };
  const keys = e => {
    if (e.key === "Escape") { close(); anchor.focus(); }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const items = [...el.querySelectorAll("button, a")]; if (!items.length) return;
      e.preventDefault();
      const i = items.indexOf(document.activeElement);
      items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    }
  };
  build(el, close);
  document.body.append(el);
  const r = anchor.getBoundingClientRect(), w = el.offsetWidth;
  el.style.top = Math.min(r.bottom + 8, innerHeight - el.offsetHeight - 10) + "px";
  el.style.left = Math.max(10, Math.min(align === "right" ? r.right - w : r.left, innerWidth - w - 10)) + "px";
  el.style.transformOrigin = align === "right" ? "top right" : "top left";
  anchor.setAttribute("aria-expanded", "true");
  addEventListener("pointerdown", outside, true); addEventListener("keydown", keys, true); addEventListener("resize", close);
  openPop = close;
  const first = el.querySelector("button, a"); if (first) first.focus({ preventScroll: true });
  return close;
}

export function announce(text) {
  const el = document.getElementById("announce");
  el.textContent = ""; setTimeout(() => { el.textContent = text; }, 40);
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch (e) {
    const area = h("textarea", { style: { position: "fixed", opacity: "0" } }); area.value = text; document.body.append(area); area.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
    area.remove(); return ok;
  }
}
